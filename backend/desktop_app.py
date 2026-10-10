"""Desktop shell around the standalone NekoMail server (launcher.py).

Windows: a pywebview window + system tray icon.

Thread layout (deliberate -- see NEXT_STEPS.md for why):
  - main thread:            webview.start() (blocking; pywebview needs the
                             main thread for its native message pump)
  - launcher's own thread:  uvicorn.Server.run() (started inside
                             launcher.start_server())
  - background thread:      pystray.Icon().run() (its own Win32 message loop,
                             fine off the main thread)

Closing the window hides it instead of exiting, so the poll loop / IMAP IDLE
watchers keep running in the background. Only the tray's "Quit" does a real,
graceful shutdown.

Linux (nekOS/Void): nekOS's own bar (bar/nekos-bar.c) never implemented a
system tray -- see its tray_x()/TRAY_WIDTH comment ("no XEmbed/
_NET_SYSTEM_TRAY protocol") -- so hide-to-tray has nowhere to render. Instead
the mail-sync server runs as its own separate background process, started
once at nekOS session start by provision/install-nekomail.sh (same treatment
the xdg-desktop-portal daemons get in start-session.sh), independent of any
window. This module becomes a thin, on-demand *viewer* on Linux: it does not
call launcher.bootstrap()/start_server() itself -- it just opens a pywebview
window against the already-running server, and exits normally when that
window is closed. Mail sync keeps going in the background either way. No
`pystray` import at all on this path (not installed by nekos/install-nekos.sh
either -- there's nothing for it to attach to).
"""
import sys
import threading
from pathlib import Path

if sys.platform != "win32":
    # The Wayland app_id (and X11 WM_CLASS) GTK gives the window comes from
    # the program name/class. Set it before anything initialises GTK so the
    # compositor's window list and the shell's focus matching see "nekomail".
    try:
        import gi

        from gi.repository import GLib

        GLib.set_prgname("nekomail")
        GLib.set_application_name("NekoMail")
        gi.require_version("Gdk", "3.0")
        from gi.repository import Gdk

        Gdk.set_program_class("nekomail")
    except Exception:  # pragma: no cover - GTK not importable: the Windows/Docker paths don't care
        pass

import webview

import launcher

if sys.platform == "win32":
    import pystray

APP_NAME = "NekoMail"


def _load_icon() -> "Image.Image":
    from PIL import Image

    icon_path = launcher.APP_DIR / "static" / "icons" / "icon-192.png"
    if icon_path.exists():
        return Image.open(icon_path)
    # Fallback for dev runs before a frontend build has been copied into
    # app/static -- keeps this script runnable on its own for quick testing.
    return Image.new("RGB", (192, 192), "#f5a3c7")


def _setup_required_html(config_path: Path) -> str:
    return f"""
    <html><body style="font-family: sans-serif; padding: 2em; background:#fff5f9;">
      <h2>NekoMail setup required</h2>
      <p>A configuration file was just created at:</p>
      <pre style="background:#fff;padding:0.75em;border-radius:6px;overflow-wrap:anywhere;">{config_path}</pre>
      <p>Edit <b>ADMIN_PASSWORD</b> in that file to a real password, then use
      the tray icon to Quit and reopen NekoMail.</p>
    </body></html>
    """


def _win_run_setup_required(icon_image, config_path: Path) -> None:
    window = webview.create_window(
        f"{APP_NAME} - Setup required",
        html=_setup_required_html(config_path),
        width=640,
        height=360,
    )

    def do_quit():
        window.destroy()

    tray = pystray.Icon(
        APP_NAME,
        icon_image,
        f"{APP_NAME} (setup required)",
        menu=pystray.Menu(pystray.MenuItem("Quit", do_quit)),
    )
    threading.Thread(target=tray.run, daemon=True).start()
    # private_mode=False: see _run_linux_viewer's own note below -- pywebview
    # defaults to private/incognito browsing (no persistent localStorage),
    # which isn't what a native desktop mail client wants on any platform.
    webview.start(private_mode=False)
    tray.stop()


def _win_run_app(icon_image) -> None:
    port = launcher.start_server()
    window = webview.create_window(APP_NAME, f"http://127.0.0.1:{port}/", width=1280, height=800)

    def on_closing():
        window.hide()
        return False  # cancel the actual close; stay running in the tray

    window.events.closing += on_closing

    def do_open():
        window.show()

    def do_quit():
        launcher.stop_server()
        window.destroy()

    tray = pystray.Icon(
        APP_NAME,
        icon_image,
        APP_NAME,
        menu=pystray.Menu(
            pystray.MenuItem("Open NekoMail", do_open, default=True),
            pystray.MenuItem("Quit", do_quit),
        ),
    )
    threading.Thread(target=tray.run, daemon=True).start()
    webview.start(private_mode=False)
    tray.stop()


def _linux_server_port() -> int:
    """Reads APP_PORT out of the background server's own config.env, rather
    than starting a server here -- see the module docstring's Linux section.
    Falls back to 8090 if config.env doesn't exist yet (first launch: the
    server creates it)."""
    from dotenv import dotenv_values

    values = dotenv_values(launcher.CONFIG_ENV_PATH)
    return int(values.get("APP_PORT", "8090"))


_STARTING_HTML = """
<html><body style="margin:0;background:#050607;color:#8d949e;display:flex;height:100vh;
align-items:center;justify-content:center;font:12px 'Share Tech Mono',monospace;letter-spacing:.2em">
<div>NEKOMAIL &middot; STARTING&hellip;</div></body></html>
"""


def _server_healthy(port: int) -> bool:
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False


def _ensure_server(port: int, timeout: float = 90.0) -> bool:
    """Make sure the sync server is up: ask systemd's user manager first
    (the nekomail.service unit installed by ultimit/install-ultimit.sh); if
    that isn't possible, start launcher.py ourselves as a detached process.
    Returns once /health answers (or False on timeout)."""
    import subprocess
    import time

    if _server_healthy(port):
        return True
    started = False
    try:
        r = subprocess.run(
            ["systemctl", "--user", "start", "nekomail.service"],
            capture_output=True, timeout=30,
        )
        started = r.returncode == 0
    except Exception:
        pass
    if not started:
        subprocess.Popen(
            [sys.executable, str(Path(launcher.BUNDLE_ROOT) / "launcher.py")],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _server_healthy(port):
            return True
        time.sleep(0.5)
    return False


def _local_login_url(port: int, timeout: float = 30.0) -> str | None:
    """Local auto-login (see app/services/local_auth.py): read the token the
    server wrote to $XDG_RUNTIME_DIR/nekomail/token, trade it for a
    single-use ticket, and return the session URL to load. None on failure
    (the page then shows the normal login)."""
    import json
    import time
    import urllib.error
    import urllib.request

    import desktop_env

    deadline = time.monotonic() + timeout
    while True:
        try:
            token = desktop_env.token_path().read_text().strip()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/auth/local/ticket", data=b"", method="POST",
                headers={"Authorization": f"Bearer {token}"},
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                ticket = json.load(r)["ticket"]
            return f"http://127.0.0.1:{port}/api/auth/local/session?ticket={ticket}"
        except Exception:
            if time.monotonic() > deadline:
                return None
            time.sleep(0.5)  # token not written yet / stale from a crashed run


class _WindowApi:
    """Exposed to the page as window.pywebview.api. Lets the frontend renew
    its local session (cookie expiry, server restart) without a login page."""

    def __init__(self, port: int):
        self._port = port

    def local_login_url(self):
        return _local_login_url(self._port, timeout=5.0)


class _SingleInstance:
    """One NekoMail window per user. An flock on $XDG_RUNTIME_DIR/nekomail/
    window.lock marks the owner; a later `nekomail` connects to the owner's
    unix socket (window.sock, 0600 dir) and asks it to raise its window."""

    def __init__(self):
        import desktop_env

        self._dir = desktop_env.runtime_dir()
        self._lock_path = self._dir / "window.lock"
        self._sock_path = self._dir / "window.sock"
        self._lock_fd = None
        self._server = None

    def acquire(self) -> bool:
        import fcntl
        import os

        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        self._lock_fd = fd  # held until the process exits
        return True

    def ask_owner_to_raise(self, path: str = "") -> bool:
        import socket
        import time

        for _ in range(40):  # the owner may still be binding its socket
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as c:
                    c.settimeout(2)
                    c.connect(str(self._sock_path))
                    c.sendall(b"raise " + path.encode() + b"\n")
                    return True
            except OSError:
                time.sleep(0.1)
        return False

    def serve(self, on_raise) -> None:
        import socket

        try:
            self._sock_path.unlink()
        except FileNotFoundError:
            pass
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(self._sock_path))
        self._sock_path.chmod(0o600)
        srv.listen(4)
        self._server = srv

        def loop():
            while True:
                try:
                    conn, _ = srv.accept()
                except OSError:
                    return
                with conn:
                    try:
                        conn.settimeout(2)
                        cmd, _, arg = conn.recv(512).decode(errors="replace").strip().partition(" ")
                        if cmd == "raise":
                            on_raise(arg.strip())
                    except OSError:
                        pass

        threading.Thread(target=loop, daemon=True).start()

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            try:
                self._sock_path.unlink()
            except FileNotFoundError:
                pass


def _ultimit_focus() -> None:
    """Wayland clients cannot un-minimize or focus themselves; present() is
    only a request. Under Ultimit the compositor's control socket can: ask
    `ultimitctl` to focus our window (it also restores it if minimized).
    Silently does nothing on other compositors / when ultimitctl is absent."""
    import json
    import shutil
    import subprocess

    ctl = shutil.which("ultimitctl")
    if not ctl:
        return
    try:
        state = json.loads(subprocess.run([ctl, "state"], capture_output=True, timeout=5, text=True).stdout)
        for w in state.get("windows", []):
            if w.get("app_id") == "nekomail":
                subprocess.run([ctl, "focus", str(w["id"])], capture_output=True, timeout=5)
                break
    except Exception:
        pass


def _run_linux_viewer() -> None:
    """The `nekomail` window command (Ultimit / Ubuntu).

    Single instance; makes sure the sync server is running (systemd user
    unit, else a detached launcher.py); signs in through the local
    auto-login ticket so no login page is shown; closing the window just
    exits -- mail sync lives in the server.
    """
    import os

    # Optional first argument: an app route to open, e.g. `nekomail /mail`.
    start_path = next((a for a in sys.argv[1:] if a.startswith("/")), "")
    instance = _SingleInstance()
    if not instance.acquire():
        sys.exit(0 if instance.ask_owner_to_raise(start_path) else 1)

    port = _linux_server_port()
    icon = launcher.APP_DIR / "static" / "icons" / "icon-192.png"
    window = webview.create_window(
        APP_NAME, html=_STARTING_HTML, width=1280, height=800, background_color="#050607",
        js_api=_WindowApi(port),
    )

    def raise_window(path: str = ""):
        # Called from the IPC thread; GTK work must happen on the GTK main loop.
        if path.startswith("/"):
            window.load_url(f"http://127.0.0.1:{port}{path}")
        from gi.repository import GLib

        def _present():
            win = window.native
            if win is not None:
                win.deiconify()
                win.present()
            return False

        GLib.idle_add(_present)
        _ultimit_focus()

    instance.serve(raise_window)

    loaded = threading.Event()
    window.events.loaded += loaded.set

    def connect():
        if not _ensure_server(port):
            window.load_html(_STARTING_HTML.replace("STARTING&hellip;", "SERVER DID NOT START &middot; see journalctl --user -u nekomail"))
            return
        url = _local_login_url(port)
        if url is None:
            window.load_url(f"http://127.0.0.1:{port}{start_path or '/'}")
            return
        loaded.clear()
        window.load_url(url)  # sets the session cookie, then redirects to /
        if start_path and start_path != "/":
            loaded.wait(15)  # the redirect has landed, so the cookie is set
            window.load_url(f"http://127.0.0.1:{port}{start_path}")

    # private_mode=False: pywebview defaults to private/incognito browsing
    # (no persistent localStorage); on the GTK/WebKitGTK backend that makes
    # window.localStorage itself null and NekoMail's frontend reads it
    # unconditionally on startup -- a blank window (see NEXT_STEPS.md).
    storage = str(launcher.DATA_DIR / "webview")
    # The app is served from the local server, so the PWA service worker only
    # risks showing a stale UI for one launch after an upgrade: start clean.
    import shutil

    for stale in ("serviceworkers", "cache", "domcache"):
        shutil.rmtree(Path(storage) / stale, ignore_errors=True)
    try:
        webview.start(
            connect, debug=bool(os.environ.get("NEKOMAIL_DEBUG")), private_mode=False,
            storage_path=storage, icon=str(icon) if icon.exists() else None,
        )
    finally:
        instance.release()


def main():
    if sys.platform != "win32":
        _run_linux_viewer()
        return

    icon_image = _load_icon()
    try:
        launcher.bootstrap()
    except launcher.SetupRequiredError as exc:
        _win_run_setup_required(icon_image, exc.config_path)
        return
    _win_run_app(icon_image)


if __name__ == "__main__":
    main()
