"""Windows desktop shell: a pywebview window + system tray icon around the
standalone NekoMail server (launcher.py).

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
"""
import threading
from pathlib import Path

import pystray
import webview
from PIL import Image

import launcher

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


def _run_setup_required(icon_image: Image.Image, config_path: Path) -> None:
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
    webview.start()
    tray.stop()


def _run_app(icon_image: Image.Image) -> None:
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
    webview.start()
    tray.stop()


def main():
    icon_image = _load_icon()
    try:
        launcher.bootstrap()
    except launcher.SetupRequiredError as exc:
        _run_setup_required(icon_image, exc.config_path)
        return
    _run_app(icon_image)


if __name__ == "__main__":
    main()
