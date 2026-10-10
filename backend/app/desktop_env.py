"""Paths and small helpers shared by the server, the launcher and the native
window for Ultimit's single-user desktop mode.

Runtime files (token, unread count, window lock/socket) live in
``$XDG_RUNTIME_DIR/nekomail`` (a 0700 directory on tmpfs that only this user
can read). Nothing here imports the rest of the app, so desktop_app.py can use
it without a configured database.
"""
import json
import os
import stat
import tempfile
from pathlib import Path

SKINS = ("mine", "amber", "silver", "verdant")


def runtime_dir() -> Path:
    """The per-user runtime directory, created 0700. Refuses (raises) if it
    exists but belongs to someone else."""
    override = os.environ.get("NEKOMAIL_RUNTIME_DIR")
    if override:
        d = Path(override)
    else:
        xdg = os.environ.get("XDG_RUNTIME_DIR")
        if xdg and Path(xdg).is_dir():
            d = Path(xdg) / "nekomail"
        elif Path(f"/run/user/{os.getuid()}").is_dir():
            d = Path(f"/run/user/{os.getuid()}") / "nekomail"
        else:
            d = Path(tempfile.gettempdir()) / f"nekomail-{os.getuid()}"
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = d.stat()
    if st.st_uid != os.getuid():
        raise PermissionError(f"{d} is owned by another user")
    if stat.S_IMODE(st.st_mode) & 0o077:
        d.chmod(0o700)
    return d


def token_path() -> Path:
    return runtime_dir() / "token"


def unread_path() -> Path:
    return runtime_dir() / "unread"


def write_private_file(path: Path, data: str) -> None:
    """Atomically write ``data`` to ``path`` with mode 0600."""
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def ultimit_shell_json() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "ultimit" / "shell.json"


def read_skin() -> dict:
    """{"ultimit": bool, "skin": str}: whether we run under Ultimit, and the
    skin from ~/.config/ultimit/shell.json (default "mine")."""
    path = ultimit_shell_json()
    under_ultimit = path.exists() or "ultimit" in os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    skin = "mine"
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("skin")
        if value in SKINS:
            skin = value
    except (OSError, ValueError, AttributeError):
        pass
    return {"ultimit": under_ultimit, "skin": skin}
