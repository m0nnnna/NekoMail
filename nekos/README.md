# NekoMail on nekOS

nekOS is a custom desktop environment (Void Linux, running nested inside WSL2 via
Xephyr) — see [nekOS](https://github.com/m0nnnna/nekos). NekoMail runs there as a
native app: a background mail-sync server (the same `backend/launcher.py` bootstrap
used by the [Windows standalone desktop app](../NEXT_STEPS.md)) plus a small
`pywebview` window that shows its web UI.

## Install

```bash
sudo sh nekos/install-nekos.sh
```

This builds the Vue frontend, creates a Python venv at `backend/.venv`, and installs
two wrappers onto `$PATH`:

- `nekomail-server` — runs the backend in the foreground (manual testing/debugging).
- `nekomail` — opens the viewer window against an already-running server.

First run of `nekomail-server` creates `$HOME/.nekomail/config.env` with a placeholder
admin password (same first-run flow as the Windows app — see the main
[NEXT_STEPS.md](../NEXT_STEPS.md)'s "Standalone packaging" section) and exits;
edit the password in that file, then run it again.

## Why there's no tray icon here, unlike Windows

The Windows desktop app (`backend/desktop_app.py`) closes to a system tray icon so
mail sync keeps running in the background. nekOS's own bar
(`bar/nekos-bar.c` in the nekOS repo) never implemented a system tray protocol
(`_NET_SYSTEM_TRAY`/XEmbed) — there's nowhere for a tray icon to render. Instead, on
Linux the mail-sync server and the viewer window are two independent processes:
the server runs continuously in the background regardless of whether any window is
open, and the `nekomail` viewer is just a disposable window onto it — closing it
doesn't stop mail sync, and reopening it (via the `nekomail` command or nekOS's app
launcher) just points a fresh window at the same still-running server. See
`desktop_app.py`'s module docstring for the full rationale.

## How nekOS wires this in

nekOS's own repo (`provision/install-nekomail.sh`) starts the background server: it
looks for `backend/.venv` and a built `backend/app/static` under `/opt/nekomail`, and
if present, backgrounds `nekomail-server`'s underlying `launcher.py` and writes a
`.desktop` entry (`Exec=nekomail`) so nekos-launch lists it. The expected flow is:

1. From the Windows host: sync this repo into the nekOS WSL distro at `/opt/nekomail`
   (`robocopy N:\projects\nekomail \\wsl.localhost\nekos-void\opt\nekomail /E /XD .git node_modules .venv dist android-client\android`).
2. Inside the distro: `sudo sh /opt/nekomail/nekos/install-nekos.sh` once (or again
   after pulling changes, to rebuild the frontend/venv).
3. nekOS's `start-session.sh` runs `install-nekomail.sh` on every session start,
   which starts the background server (if not already running) and refreshes the
   `.desktop` entry.

This `nekos/` folder's `install-nekos.sh` is the standalone equivalent for building
and installing NekoMail on Void Linux directly, independent of nekOS's own session
scripts (mirrors NekoShot's `nekos/install-nekos.sh` in shape).

**Scope note:** this is currently wired up for personal use only (dev-sync via
`robocopy`, not a public GitHub repo) — unlike NekoShot/NekoPlayer, it isn't wired
into `provision/install-companions.sh`'s fresh-install flow or given a
prebuilt-tarball CI tier. See the NekoMail project's own planning notes if that
changes.
