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

import webview
from PIL import Image

import launcher

if sys.platform == "win32":
    import pystray

APP_NAME = "NekoMail"


def _load_icon() -> Image.Image:
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


def _win_run_setup_required(icon_image: Image.Image, config_path: Path) -> None:
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


def _win_run_app(icon_image: Image.Image) -> None:
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
    """Reads APP_PORT out of the already-running background server's own
    config.env, rather than starting a server here -- see the module
    docstring's Linux section. Falls back to the same 8090 default
    launcher.py itself uses if config.env doesn't exist yet (e.g.
    nekos/install-nekos.sh hasn't run the first-boot bootstrap yet)."""
    from dotenv import dotenv_values

    values = dotenv_values(launcher.CONFIG_ENV_PATH)
    return int(values.get("APP_PORT", "8090"))


def _run_linux_viewer() -> None:
    # No bootstrap()/start_server() here -- provision/install-nekomail.sh
    # already started launcher.py as a standalone background process before
    # this viewer is ever launched. If that server isn't actually up yet
    # (e.g. launched before setup finished, or crashed), the window just
    # shows a connection error -- no retry/wait logic here, matching the
    # project's usual practice of accepting a known, documented v1 gap
    # rather than adding speculative handling.
    port = _linux_server_port()
    webview.create_window(APP_NAME, f"http://127.0.0.1:{port}/", width=1280, height=800)
    # private_mode=False: pywebview defaults to private/incognito browsing
    # (no persistent localStorage) -- on the GTK/WebKitGTK backend this
    # makes window.localStorage itself null, not just empty, and NekoMail's
    # frontend reads it unconditionally on startup (theme/session state),
    # throwing before Vue ever mounts. Confirmed live (2026-08-05): this is
    # exactly what produced a blank white window with no console errors
    # visible until WebKit's inspector was turned on -- everything else
    # (server, network requests, GL/compositing env vars) was a red herring.
    webview.start(debug=False, private_mode=False)


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
