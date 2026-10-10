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

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    APPDATA_ROOT = Path(os.environ["APPDATA"]) / "NekoMail"
    CONFIG_DIR = APPDATA_ROOT
    DATA_DIR = APPDATA_ROOT / "data"
    LEGACY_ROOT = None
else:
    # Linux desktop (Ultimit / Ubuntu): single-user XDG layout.
    #   config: ${XDG_CONFIG_HOME:-~/.config}/nekomail/config.env  (0600)
    #   data:   ${XDG_DATA_HOME:-~/.local/share}/nekomail/{nekomail.db,mail/}
    # The older nekOS port used ~/.nekomail (config.env + data/); it is
    # migrated (copied, not moved) on first run -- see _migrate_legacy().
    CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "nekomail"
    DATA_DIR = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "nekomail"
    APPDATA_ROOT = CONFIG_DIR
    LEGACY_ROOT = Path.home() / ".nekomail"
MAIL_DIR = DATA_DIR / "mail"
CONFIG_ENV_PATH = CONFIG_DIR / "config.env"

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


_LINUX_CONFIG_ENV_TEMPLATE = """\
# NekoMail desktop configuration (generated on first run).
# Back this file up -- losing SECRET_KEY/MAIL_ENCRYPTION_KEY without losing
# the database makes every stored mail account credential permanently
# undecryptable.

# The native NekoMail window signs in automatically (see ultimit/NOTES.md),
# so you never need this password on this machine. It only matters if you
# enable the LAN listener below and sign in from another device.
ADMIN_USERNAME=admin
ADMIN_PASSWORD={admin_password}

APP_PORT=8090
# Loopback only by default. Set to true to also listen on the LAN (e.g. for
# the Android client); LAN clients use the normal login with the password above.
LISTEN_LAN=false
# Must match how NekoMail is actually reached for Outlook OAuth linking to
# work -- link Outlook accounts from the desktop window (localhost).
PUBLIC_BASE_URL=http://localhost:8090

# Desktop notification for new inbox mail (one per burst).
DESKTOP_NOTIFICATIONS=true

# Set to true if this is ever put behind HTTPS.
COOKIE_SECURE=false

# Optional: enables the "Link Outlook Account" button. Leave blank to disable.
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


def _write_private(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    path.chmod(0o600)


def _migrate_legacy() -> None:
    """Copy a nekOS-era ~/.nekomail (config.env + data/) into the XDG dirs.
    Copies rather than moves, so the old directory stays as a backup. Only
    runs when the new config does not exist yet."""
    import shutil

    if LEGACY_ROOT is None or CONFIG_ENV_PATH.exists() or not (LEGACY_ROOT / "config.env").is_file():
        return
    print(f"NekoMail: migrating {LEGACY_ROOT} -> {CONFIG_DIR} and {DATA_DIR}")
    _write_private(CONFIG_ENV_PATH, (LEGACY_ROOT / "config.env").read_text(encoding="utf-8"))
    legacy_data = LEGACY_ROOT / "data"
    if legacy_data.is_dir():
        shutil.copytree(legacy_data, DATA_DIR, dirs_exist_ok=True)


def _fix_placeholder_password() -> None:
    """Desktop mode never stops on a placeholder admin password: replace it
    (e.g. one carried over from the nekOS/Windows template) with a random one."""
    import re

    text = CONFIG_ENV_PATH.read_text(encoding="utf-8")
    values = dotenv_values(CONFIG_ENV_PATH)
    if values.get("ADMIN_PASSWORD") not in (None, "", PLACEHOLDER_PASSWORD):
        return
    line = f"ADMIN_PASSWORD={secrets.token_urlsafe(18)}"
    if re.search(r"^ADMIN_PASSWORD=.*$", text, flags=re.M):
        text = re.sub(r"^ADMIN_PASSWORD=.*$", line, text, flags=re.M)
    else:
        text += f"\n{line}\n"
    _write_private(CONFIG_ENV_PATH, text)


def _ensure_config_env() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MAIL_DIR.mkdir(parents=True, exist_ok=True)
    if not IS_WINDOWS:
        CONFIG_DIR.chmod(0o700)
        DATA_DIR.chmod(0o700)
        _migrate_legacy()
        DATA_DIR.chmod(0o700)  # copytree copies the source dir's mode onto it
        MAIL_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_ENV_PATH.exists():
        keys = dict(secret_key=secrets.token_hex(32), mail_encryption_key=Fernet.generate_key().decode())
        if IS_WINDOWS:
            CONFIG_ENV_PATH.write_text(_CONFIG_ENV_TEMPLATE.format(placeholder=PLACEHOLDER_PASSWORD, **keys), encoding="utf-8")
        else:
            _write_private(CONFIG_ENV_PATH, _LINUX_CONFIG_ENV_TEMPLATE.format(admin_password=secrets.token_urlsafe(18), **keys))
    if not IS_WINDOWS:
        CONFIG_ENV_PATH.chmod(0o600)
        _fix_placeholder_password()


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
    if not IS_WINDOWS:
        os.environ["DESKTOP_MODE"] = "true"


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
    if IS_WINDOWS and os.environ.get("ADMIN_PASSWORD") == PLACEHOLDER_PASSWORD:
        raise SetupRequiredError(CONFIG_ENV_PATH)

    _run_migrations()
    _run_seed()


_server = None
_server_thread = None


def listen_host() -> str:
    """Windows: 0.0.0.0 (LAN-reachable, so a phone client can reach it).
    Linux desktop: loopback only unless LISTEN_LAN=true in config.env."""
    if IS_WINDOWS or os.environ.get("LISTEN_LAN", "").strip().lower() in ("1", "true", "yes", "on"):
        return "0.0.0.0"
    return "127.0.0.1"


def start_server():
    """Start uvicorn in a background thread (host from listen_host()).
    Must be called after bootstrap()."""
    global _server, _server_thread
    import uvicorn

    from main import app

    port = int(os.environ.get("APP_PORT", "8090"))
    config = uvicorn.Config(app, host=listen_host(), port=port, log_level="info")
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
    # Headless run: useful for testing without the desktop GUI layer, and
    # also the real Linux (nekOS) entry point -- provision/install-nekomail.sh
    # runs this directly as a background daemon, with no GUI layer at all
    # (see desktop_app.py's module docstring). Catch SetupRequiredError here
    # rather than letting it crash with a bare traceback in that daemon's
    # log -- there's no window to show desktop_app.py's setup-required
    # message in this path.
    try:
        bootstrap()
    except SetupRequiredError as exc:
        print(f"NekoMail: {exc}")
        sys.exit(1)
    port = start_server()
    print(f"NekoMail running at http://localhost:{port}/ on {listen_host()} (Ctrl+C to stop)", flush=True)
    # systemd stops the service with SIGTERM: shut down gracefully (IDLE
    # connections, token/unread files) instead of dying mid-sync.
    import signal

    def _term(*_):
        stop_server()

    signal.signal(signal.SIGTERM, _term)
    try:
        while _server_thread is not None and _server_thread.is_alive():
            _server_thread.join(timeout=1.0)
    except KeyboardInterrupt:
        stop_server()
