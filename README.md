# NekoMail

A self-hosted, neko-themed email client. One web app, multiple mail accounts (self-hosted IMAP/SMTP, Gmail via app password, Outlook via OAuth) — runs as a standalone Windows desktop app, with a thin native Android client that connects to it.

## Status

All 10 phases of the original build plan are code-complete and browser-verified: multi-account mail sync (IMAP IDLE + poll), a full mailbox UI, compose/send with attachments, Outlook OAuth account linking (live-tested against a real Microsoft account), mail filter rules, and client-side-only PGP. It's packaged as a standalone Windows desktop app (see below) plus a thin Android client; see `NEXT_STEPS.md` for the packaging session's details and the still-open real-Android-device verification pass.

## Stack

FastAPI (async SQLAlchemy + Alembic) backend, Vue 3 + Vite + Pinia frontend, SQLite storage. Standalone Windows desktop app (pywebview + PyInstaller) is the primary deployment; Docker Compose remains supported as an alternate path. See the sibling projects NekoTicket and NekoBooru for the conventions this follows.

## Getting started

### Standalone desktop app (recommended, Windows)

No Docker required — a single packaged app runs the backend and opens a
window on it, and keeps running in the system tray so mail sync (IDLE
push, the safety-net poll loop) keeps working while the window is closed.

Build it (from a **local disk checkout**, not a network-mapped drive — see
"A note on network drives" below):

```powershell
python -m venv backend\.venv
backend\.venv\Scripts\pip install -r backend\requirements-desktop.txt
powershell -File build-desktop.ps1
```

This produces `backend\dist\NekoMail\NekoMail.exe`. Run it: on first launch
it creates `%APPDATA%\NekoMail\config.env` with freshly generated
`SECRET_KEY`/`MAIL_ENCRYPTION_KEY` and a placeholder admin password, and
shows a window telling you to edit that file and restart. After that it
seeds the admin user, runs migrations, and opens the mailbox UI — the
window's close button hides it to the tray rather than quitting; use the
tray icon's "Quit" to actually stop it.

If you already have a Docker deployment with real accounts, see "Migrating
from Docker" below before your first launch, so you don't start from an
empty mailbox.

The server also listens on your LAN (not just `localhost`), so the Android
client can reach it — expect a Windows Firewall prompt the first time.
**Link Outlook accounts from the desktop app's own window**, not from a
phone over the LAN — the OAuth redirect URI has to match `PUBLIC_BASE_URL`
(`http://localhost:<port>` by default) exactly.

### Docker (alternate path, still supported)

```bash
cp .env.example .env
# edit .env: set SECRET_KEY, MAIL_ENCRYPTION_KEY, ADMIN_USERNAME, ADMIN_PASSWORD

docker compose up -d --build
```

The app will be available at `http://localhost:${APP_PORT:-8090}`. On first start it runs migrations and seeds the admin user from `.env`.

### Android client

`android-client/` is a thin Capacitor app — it has no copy of the mail UI
built in; it just opens the URL of your running desktop app (or Docker
deployment) in a native WebView, so it needs the server already running
and reachable on your LAN. First launch asks for that server's address
(e.g. `http://192.168.1.20:8090`) and remembers it.

Building the APK needs Android Studio / the Android SDK + a JDK 11+, which
this project doesn't assume you have installed. From `android-client/`:

```bash
npm install
npx cap sync android
cd android && ./gradlew assembleDebug
```

Install the result (`android/app/build/outputs/apk/debug/app-debug.apk`) via
`adb install` or by copying it to the device and opening it — no Play Store
signing/distribution needed for personal use.

### A note on network drives

If your working copy lives on a network-mapped drive (e.g. an `N:`-style
share), build tooling (Python venvs, `npm install`'s native binaries like
esbuild, PyInstaller) needs to run against a **local disk** copy — executing
binaries directly from a network share has been observed to fail (`npm
install` errors `EPERM` spawning esbuild.exe) or hang indefinitely (a venv's
`python.exe`). Plain file edits/git operations on the share are fine; it's
specifically running binaries from it that doesn't work. Copy the repo to a
local path first (`robocopy` or a fresh `git clone`) and build from there.

## Data storage

### Standalone desktop app

SQLite database + raw mail (`.eml`) storage + `config.env` (holding the
encryption keys) live at `%APPDATA%\NekoMail\`. Back up that whole folder —
losing `MAIL_ENCRYPTION_KEY` makes every stored mail-account credential
permanently undecryptable.

### Docker

SQLite database + raw mail (`.eml`) storage live at `C:\NekoMailData` on the host, bind-mounted into the container. **This must be a local disk path, not a network-mapped drive** — a network-mapped bind mount (e.g. an `N:`-style drive) silently backs onto storage that doesn't support the `mmap()` semantics SQLite's WAL mode needs, which crashes the app with a hard `Bus error (core dumped)` crash-loop (hit for real 2026-08-02; the data itself was recoverable, but don't reintroduce this). Back up `C:\NekoMailData` **and** `.env` together — the encryption keys in `.env` are required to decrypt stored mail-account credentials.

```bash
sqlite3 /c/NekoMailData/nekomail.db ".backup '/c/NekoMailData/backup-$(date +%F).db'"
```

### Migrating from Docker to the standalone app

So an existing Docker deployment's accounts/mail aren't orphaned, copy its
data across **before** the first standalone launch:

1. Copy `C:\NekoMailData\nekomail.db` and `C:\NekoMailData\mail\` →
   `%APPDATA%\NekoMail\data\`.
2. Copy the exact `SECRET_KEY` and `MAIL_ENCRYPTION_KEY` values from the
   Docker `.env` into `%APPDATA%\NekoMail\config.env` — these must be an
   **exact copy**, not regenerated, or existing stored credentials become
   permanently undecryptable.
3. Copy `ADMIN_USERNAME`/`ADMIN_PASSWORD` over the same way.
4. Only then launch `NekoMail.exe` for the first time.

## Stopping

Standalone app: tray icon → Quit (closing the window alone only hides it,
so background sync keeps running).

Docker:

```bash
docker compose down
```
