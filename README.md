# NekoMail

A self-hosted, neko-themed email client. One web app, multiple mail accounts (self-hosted IMAP/SMTP, Gmail via app password, Outlook via OAuth), installable as a PWA on desktop and Android.

## Status

All 10 phases of the original build plan are code-complete: multi-account mail sync (IMAP IDLE + poll), a full mailbox UI, compose/send with attachments, Outlook OAuth account linking, mail filter rules, and client-side-only PGP. See `NEXT_STEPS.md` for what's been live-verified against a real mailbox vs. what still needs a manual pass (mainly browser click-through UI testing and a real Android device test) before calling it fully done.

## Stack

FastAPI (async SQLAlchemy + Alembic) backend, Vue 3 + Vite + Pinia frontend, SQLite storage, Docker Compose deployment. See the sibling projects NekoTicket and NekoBooru for the conventions this follows.

## Getting started

```bash
cp .env.example .env
# edit .env: set SECRET_KEY, MAIL_ENCRYPTION_KEY, ADMIN_USERNAME, ADMIN_PASSWORD

docker compose up -d --build
```

The app will be available at `http://localhost:${APP_PORT:-8090}`. On first start it runs migrations and seeds the admin user from `.env`.

## Data storage

SQLite database + raw mail (`.eml`) storage live at `C:\NekoMailData` on the host, bind-mounted into the container. **This must be a local disk path, not a network-mapped drive** — a network-mapped bind mount (e.g. an `N:`-style drive) silently backs onto storage that doesn't support the `mmap()` semantics SQLite's WAL mode needs, which crashes the app with a hard `Bus error (core dumped)` crash-loop (hit for real 2026-08-02; the data itself was recoverable, but don't reintroduce this). Back up `C:\NekoMailData` **and** `.env` together — the encryption keys in `.env` are required to decrypt stored mail-account credentials.

```bash
sqlite3 /c/NekoMailData/nekomail.db ".backup '/c/NekoMailData/backup-$(date +%F).db'"
```

## Stopping

```bash
docker compose down
```
