# NekoMail on Ultimit (branch `ultimit`)

NekoMail is Ultimit's mail app: the rail's MAILER button runs `nekomail`.
Everything here targets a single-user Linux desktop (Ubuntu 26.04, Python 3.14,
Wayland). The Docker and Windows paths still work as before.

## Install (no root)

```sh
sh ultimit/install-ultimit.sh          # needs node/npm, python3, python3-gi + gir1.2-webkit2-4.1
systemctl --user start nekomail        # the installer enables it; this starts it now
nekomail                               # opens the window (starts the service itself if needed)
```

The installer: builds the frontend (`npm ci`/`npm install` + `vite build`, copied to
`backend/app/static`), creates `backend/.venv` (`--system-site-packages`, so pywebview's GTK
backend uses the system PyGObject/WebKitGTK; if `python3-venv` is missing it bootstraps pip from
PyPI with a sha256 check, `ultimit/bootstrap_pip.py`), installs
`backend/requirements-linux.txt`, writes `~/.local/bin/nekomail`, the user unit
`~/.config/systemd/user/nekomail.service`, `~/.local/share/applications/nekomail.desktop`
(`StartupWMClass=nekomail`, `Icon=nekomail`) and icons (hicolor, scalable SVG + PNG).
Overrides: `DEST=<dir>` (everything under a fake home, skips systemctl), `XDG_CONFIG_HOME`,
`XDG_DATA_HOME`, `BIN_DIR`, `SKIP_FRONTEND=1`, `NO_SYSTEMCTL=1`, `START=1`.
`~/.local/bin` must be on PATH (the shell's MAILER detection also falls back to it).

## Desktop mode design

Desktop mode is on when `launcher.py` runs on Linux (`DESKTOP_MODE=true` is set for the app).

* **Config**: first run generates `${XDG_CONFIG_HOME:-~/.config}/nekomail/config.env` (0600, dir
  0700) with random `SECRET_KEY`, `MAIL_ENCRYPTION_KEY` and a random `ADMIN_PASSWORD` (it never
  stops on a placeholder; a leftover `CHANGE_ME` is replaced with a random one). The admin
  password only matters for LAN logins.
* **Data**: `${XDG_DATA_HOME:-~/.local/share}/nekomail/{nekomail.db, mail/, webview/}`.
  If `~/.nekomail` (old nekOS layout) exists and the new config doesn't, its `config.env` and
  `data/` are *copied* over (same keys, so stored credentials still decrypt); the old dir stays.
* **Network**: binds `127.0.0.1` only. `LISTEN_LAN=true` in `config.env` opts into `0.0.0.0`
  (Android client); LAN clients use the normal login.
* **Auth (local auto-login)**: at start the server writes a random secret to
  `$XDG_RUNTIME_DIR/nekomail/token` (0600 in a 0700 tmpfs dir, removed on clean shutdown).
  The window reads it and POSTs it (`Authorization: Bearer`) to `/api/auth/local/ticket`, gets a
  single-use 30 s ticket, and navigates to `/api/auth/local/session?ticket=...`, which sets the
  normal session cookie and 303-redirects to `/`. The long-lived secret never appears in a URL;
  a ticket left in history is dead. Both endpoints answer 404 unless it is a direct loopback
  request (loopback peer, localhost Host header, no `X-Forwarded-For`/`Forwarded`), so LAN and
  proxied access get the normal login page and other local users cannot read the token (other
  processes of the *same* user can, which is the same boundary as `config.env` and the DB).
  If the cookie expires or the server restarts, the page asks the host (`window.pywebview.api.
  local_login_url`) for a fresh ticket instead of showing the login.
* **Window** (`backend/desktop_app.py`, Linux path): GTK prgname/program class `nekomail` is set
  before GTK starts, so the Wayland app_id is `nekomail`. Single instance via `flock` on
  `$XDG_RUNTIME_DIR/nekomail/window.lock` plus a unix socket (`window.sock`): a second `nekomail`
  asks the first to raise and exits (Wayland clients cannot un-minimize themselves, so under
  Ultimit the first instance also calls `ultimitctl focus`). `nekomail /mail/...` opens a route.
  If the server is down it runs `systemctl --user start nekomail`, else spawns `launcher.py`
  detached, shows a "starting" page and waits for `/health`. Closing the window just exits.
* **Background sync**: `ultimit/nekomail.service` (`Restart=on-failure`, SIGTERM-clean) runs
  `launcher.py`, so IDLE/poll sync and notifications work with no window open.
* **Session start** (for `ultimit-session`, not edited here): see the shell handoff, one line,
  `systemctl --user start nekomail 2>/dev/null` when installed.

## Theme

`frontend/src/theme/ultimit.css` (mirrors `shell/Theme.qml`: mine, amber, silver, verdant):
glass-black panels over the skin gradient, thin light lines, Share Tech Mono small-caps labels,
Michroma headings, chamfered buttons/panels, corner brackets, accent colour; the neko stays as a
cat glyph in empty states and two small ears on the wordmark. `NIcon.vue` draws thin-line inline
SVGs (folders, compose, reply, star, attach, lock...) under the Ultimit theme and falls back to
the old emoji otherwise. `tokens.css` (neko theme) is untouched.

The backend endpoint `GET /api/ultimit/skin` (public) reads `~/.config/ultimit/shell.json`
("skin", default `mine`) and says whether this is an Ultimit desktop (`XDG_CURRENT_DESKTOP`
contains Ultimit, or the file exists); the frontend polls it every 3 s and sets
`<html data-theme data-skin>`, so changing the skin in Ultimit's Settings re-skins NekoMail live.
Ultimit is the default under Ultimit; `?theme=neko|ultimit|auto` is a hidden developer override.

## Desktop hooks (`backend/app/services/desktop.py`)

* **Unread badge**: total unread INBOX count (active accounts) in `$XDG_RUNTIME_DIR/nekomail/unread`
  (plain integer, atomic rewrite, only on change, recreated if deleted). Updated after every
  sync, after mutating `/api/messages*` requests, and by a 10 s loop.
* **Notifications**: only for new INBOX mail reported by the forward-sync path (IDLE push or poll;
  never initial sync or backfill), that is still unread and in the inbox after filters ran.
  Coalesced: queued, flushed after 3 s of quiet (max 10 s): one message shows sender + subject,
  a burst shows "N new messages". Sent with `notify-send --action=default=...` (falls back to
  `gdbus call ... Notify`); clicking runs the window command. Off with `DESKTOP_NOTIFICATIONS=false`.

## Other fixes

* The default view (unified inbox) never fetched its first page (the store's default view
  counted as "same view"): `mail.viewLoaded` fixes it. Added a `c` shortcut for compose.
* Dependency bumps for Python 3.14: `pydantic 2.10.3 -> 2.14.0` (pydantic-core 2.50 has cp314
  wheels), `sqlalchemy 2.0.36 -> 2.0.54` (3.14 typing fix). Everything else keeps its pin and
  installs from wheels (`cryptography 43.0.3`, `bcrypt 3.2.2`, `uvicorn 0.32.1`, `fastapi 0.115.5`,
  `aiosqlite 0.20`, `alembic 1.14`...). New `requirements-linux.txt` adds `pywebview 6.2.1`,
  `python-dotenv`; `requirements-test.txt` adds `aiosmtpd`. `PIL` is no longer imported on Linux.

## Tests (all under a fake HOME in /tmp; no real accounts or servers)

`ultimit/tests/` has a fake IMAP server (LOGIN/LIST/SELECT/FETCH/STORE/APPEND/IDLE, inject dir for
new mail), a fake SMTP sink (aiosmtpd), a fake `org.freedesktop.Notifications` server and
`stack.sh` to start/stop them plus the server on a private D-Bus. Verified: installer into a fake
home (unit passes `systemd-analyze verify`), 6 Alembic migrations on py3.14, server up, token
login works and token-less requests get 401 (ticket endpoint 403/404 for wrong token, proxy
header, foreign Host, LAN peer, reused ticket), `~/.nekomail` migration, `LISTEN_LAN` bind,
window in a headless Ultimit compositor (app_id `nekomail`, single instance, raise, autostart of a
stopped server), screenshots for mine/amber/silver/verdant incl. live re-skin and compose, send
through the fake SMTP with attachment, IDLE-driven notification ("Aura / The Fragment"; a burst
becomes "12 new messages"; nothing on initial sync), the unread file, notification action
launching the window command (via a notify-send shim), and the Ultimit rail badge (copy of the
shell) with real clicks on MAILER launching `nekomail`.

## Caveats

* The unit file itself was only verified with `systemd-analyze verify` and by running its
  `ExecStart` directly; I did not install it into a real user manager.
* `notify-send --action` returned "actions not supported" against my fake server under
  AppArmor (notify-send's profile could not call my unconfined fake); the notification still
  displays and the action path was tested with a shim. Check once against Ultimit's own server.
* In Ultimit's WINDOWS list the NekoMail entry shows the letter fallback until Ultimit's icon
  theme resolves the `nekomail` icon (installed in hicolor).
* `nekos/` (Void/nekOS port) is kept but superseded by `ultimit/`.
