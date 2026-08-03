"""Standalone (non-Docker) bootstrap for NekoMail.

Sets up sys.path so the flat, unqualified imports used throughout
``app/`` (``from config import settings``, ``from models.account import
Account``, etc. -- the same convention the Docker image relies on via
``cd app && uvicorn main:app``) keep resolving when this runs as a
PyInstaller-frozen executable, points the app at a persistent per-user
data directory instead of a relative ``./data`` folder, runs migrations
and admin-user seeding programmatically (no ``alembic``/subprocess CLI
calls available in a frozen bundle), and exposes start_server()/
stop_server() for a GUI layer (desktop_app.py) to drive.

This module has no GUI dependency and can run headless.
"""
import asyncio
import os
import secrets
import sys
import threading
from pathlib import Path

# Must happen before any import of an app-internal module (config,
# database, main, seed, or alembic's env.py, which itself imports
# database) -- see module docstring.
if getattr(sys, "frozen", False):
    BUNDLE_ROOT = Path(sys._MEIPASS)  # type: ignore[attr-defined]
else:
    BUNDLE_ROOT = Path(__file__).resolve().parent
APP_DIR = BUNDLE_ROOT / "app"
sys.path.insert(0, str(APP_DIR))

from cryptography.fernet import Fernet  # noqa: E402
from dotenv import dotenv_values  # noqa: E402

APPDATA_ROOT = Path(os.environ["APPDATA"]) / "NekoMail"
DATA_DIR = APPDATA_ROOT / "data"
MAIL_DIR = DATA_DIR / "mail"
CONFIG_ENV_PATH = APPDATA_ROOT / "config.env"

PLACEHOLDER_PASSWORD = "CHANGE_ME"

_CONFIG_ENV_TEMPLATE = """\
# NekoMail standalone configuration.
# Edit ADMIN_PASSWORD below to a real password, then restart NekoMail.
# Back this file up -- losing SECRET_KEY/MAIL_ENCRYPTION_KEY without losing
# the database makes every stored mail account credential permanently
# undecryptable.

ADMIN_USERNAME=admin
ADMIN_PASSWORD={placeholder}

APP_PORT=8090
# Must match how NekoMail is actually reached for Outlook OAuth linking to
# work -- link Outlook accounts from the desktop app window (localhost),
# not from a phone over the LAN.
PUBLIC_BASE_URL=http://localhost:8090

# Set to true if this is ever put behind HTTPS.
COOKIE_SECURE=false

# Optional: enables the "Link Outlook Account" button. Leave blank to
# disable it. See NEXT_STEPS.md Phase 7 for the Azure App Registration steps.
AZURE_CLIENT_ID=
AZURE_AUTHORITY=https://login.microsoftonline.com/common

# Generated automatically -- do not edit.
SECRET_KEY={secret_key}
MAIL_ENCRYPTION_KEY={mail_encryption_key}
"""


class SetupRequiredError(Exception):
    """Raised when config.env was just created or still has its placeholder
    admin password -- the caller (desktop_app.py) should show setup
    instructions instead of starting the server."""

    def __init__(self, config_path: Path):
        self.config_path = config_path
        super().__init__(f"Edit {config_path} and restart NekoMail.")


def _ensure_config_env() -> None:
    APPDATA_ROOT.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MAIL_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_ENV_PATH.exists():
        CONFIG_ENV_PATH.write_text(
            _CONFIG_ENV_TEMPLATE.format(
                placeholder=PLACEHOLDER_PASSWORD,
                secret_key=secrets.token_hex(32),
                mail_encryption_key=Fernet.generate_key().decode(),
            ),
            encoding="utf-8",
        )


def _load_env() -> None:
    """Populate os.environ from config.env plus the computed data paths,
    before any app-internal module is imported."""
    _ensure_config_env()
    for key, value in dotenv_values(CONFIG_ENV_PATH).items():
        if value is not None:
            os.environ[key] = value

    db_path = (DATA_DIR / "nekomail.db").as_posix()
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    os.environ["MAIL_STORAGE_PATH"] = str(MAIL_DIR)


def _run_migrations() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BUNDLE_ROOT / "alembic.ini"))
    # Overridden to an absolute path -- the ini's relative
    # "script_location = app/alembic" only resolves correctly when cwd is
    # backend/ (Docker's convention), which doesn't hold for a frozen exe.
    cfg.set_main_option("script_location", str(APP_DIR / "alembic"))
    cfg.set_main_option("prepend_sys_path", str(BUNDLE_ROOT))
    command.upgrade(cfg, "head")


def _run_seed() -> None:
    import seed as seed_module

    asyncio.run(seed_module.seed())


def bootstrap():
    """Run first-run setup, migrations, and seeding. Raises
    SetupRequiredError if the admin password still needs to be set.
    Must be called exactly once, before start_server()."""
    _load_env()
    if os.environ.get("ADMIN_PASSWORD") == PLACEHOLDER_PASSWORD:
        raise SetupRequiredError(CONFIG_ENV_PATH)

    _run_migrations()
    _run_seed()


_server = None
_server_thread = None


def start_server():
    """Start uvicorn on 0.0.0.0 (LAN-reachable, so a phone client can reach
    it) in a background thread. Must be called after bootstrap()."""
    global _server, _server_thread
    import uvicorn

    from main import app

    port = int(os.environ.get("APP_PORT", "8090"))
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    _server = uvicorn.Server(config)

    _server_thread = threading.Thread(target=_server.run, daemon=True)
    _server_thread.start()
    return port


def stop_server(timeout: float = 10.0) -> None:
    """Ask uvicorn (and the FastAPI lifespan's scheduler.stop()) to shut
    down cleanly and wait for it. Never kill the thread directly -- a hard
    kill can leave IMAP IDLE connections wedged server-side (see
    scheduler.py's notes on idle_done())."""
    global _server, _server_thread
    if _server is not None:
        _server.should_exit = True
    if _server_thread is not None:
        _server_thread.join(timeout=timeout)
    _server = None
    _server_thread = None


if __name__ == "__main__":
    # Headless run, useful for testing without the desktop GUI layer.
    bootstrap()
    port = start_server()
    print(f"NekoMail running at http://localhost:{port}/ (Ctrl+C to stop)")
    try:
        while _server_thread.is_alive():
            _server_thread.join(timeout=1.0)
    except KeyboardInterrupt:
        stop_server()
