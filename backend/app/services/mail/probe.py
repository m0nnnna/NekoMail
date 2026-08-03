"""Live IMAP/SMTP connectivity checks and folder discovery for account
management (Phase 3). Not the sync engine (Phase 4) -- these are one-shot
connect/verify/close operations, not long-lived pooled connections."""

import asyncio
import base64
import re
import ssl
from dataclasses import dataclass

import aioimaplib
import aiosmtplib

CONNECT_TIMEOUT = 10


@dataclass
class ImapParams:
    host: str
    port: int
    security: str  # "ssl" | "starttls" | "none"
    username: str
    password: str  # for auth_type="oauth_outlook", this holds a resolved bearer access token, not a stored password
    verify_ssl: bool = True
    auth_type: str = "password"  # "password" | "oauth_outlook"


@dataclass
class SmtpParams:
    host: str
    port: int
    security: str  # "ssl" | "starttls" | "none"
    username: str
    password: str  # see ImapParams.password
    verify_ssl: bool = True
    auth_type: str = "password"


async def imap_login(client: aioimaplib.IMAP4, params: ImapParams):
    if params.auth_type == "oauth_outlook":
        return await client.xoauth2(params.username, params.password)
    return await client.login(params.username, params.password)


async def smtp_login(client: aiosmtplib.SMTP, params: SmtpParams) -> None:
    if params.auth_type == "oauth_outlook":
        # aiosmtplib has no built-in XOAUTH2 -- same SASL string format as
        # aioimaplib.IMAP4.xoauth2() (RFC 7628 / Microsoft & Google's shared
        # convention), sent via the low-level command API. Bypassing
        # client.login() means its internal ehlo-before-auth call is
        # skipped too -- must send it explicitly or the server rejects
        # AUTH with "503 Send hello first".
        await client.ehlo()
        sasl = base64.b64encode(f"user={params.username}\1auth=Bearer {params.password}\1\1".encode()).decode()
        response = await client.execute_command(b"AUTH", b"XOAUTH2", sasl.encode())
        if response.code != aiosmtplib.SMTPStatus.auth_successful:
            raise aiosmtplib.SMTPAuthenticationError(response.code, response.message)
        return
    await client.login(params.username, params.password)


def build_ssl_context(verify: bool) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


async def connect_imap(params: ImapParams) -> aioimaplib.IMAP4:
    ctx = build_ssl_context(params.verify_ssl)
    if params.security == "ssl":
        client = aioimaplib.IMAP4_SSL(host=params.host, port=params.port, timeout=CONNECT_TIMEOUT, ssl_context=ctx)
        await client.wait_hello_from_server()
    else:
        client = aioimaplib.IMAP4(host=params.host, port=params.port, timeout=CONNECT_TIMEOUT)
        await client.wait_hello_from_server()
        if params.security == "starttls":
            resp = await client.starttls(ssl_context=ctx)
            if resp.result != "OK":
                raise RuntimeError(f"STARTTLS failed: {resp.lines}")
    return client


async def check_imap(params: ImapParams) -> tuple[bool, str]:
    try:
        client = await asyncio.wait_for(connect_imap(params), timeout=CONNECT_TIMEOUT)
    except Exception as exc:
        return False, f"Could not connect: {exc}"

    try:
        resp = await imap_login(client, params)
        if resp.result != "OK":
            lines = " ".join(line.decode(errors="replace") for line in resp.lines)
            return False, f"Login failed: {lines}"
        return True, "Connected and logged in."
    except Exception as exc:
        return False, f"Login failed: {exc}"
    finally:
        try:
            await asyncio.wait_for(client.logout(), timeout=5)
        except Exception:
            pass


async def check_smtp(params: SmtpParams) -> tuple[bool, str]:
    ctx = build_ssl_context(params.verify_ssl)
    kwargs = dict(hostname=params.host, port=params.port, timeout=CONNECT_TIMEOUT)
    if params.security == "ssl":
        kwargs["use_tls"] = True
        kwargs["tls_context"] = ctx
    elif params.security == "starttls":
        kwargs["start_tls"] = True
        kwargs["tls_context"] = ctx

    client = aiosmtplib.SMTP(**kwargs)
    try:
        await client.connect()
        await smtp_login(client, params)
        return True, "Connected and authenticated."
    except Exception as exc:
        return False, f"Connection/auth failed: {exc}"
    finally:
        try:
            await client.quit()
        except Exception:
            pass


# --- Folder discovery (RFC 6154 SPECIAL-USE, with fallbacks) ---

_SPECIAL_USE_FLAGS = {
    "\\All": "all",
    "\\Archive": "archive",
    "\\Drafts": "drafts",
    "\\Flagged": "flagged",
    "\\Junk": "junk",
    "\\Sent": "sent",
    "\\Trash": "trash",
    "\\Important": "important",
}

# Fallback for servers that support neither SPECIAL-USE nor auto-tagged
# LIST flags -- matched against the folder's own name only (not full path).
_NAME_HEURISTICS = {
    "sent": "sent", "sent items": "sent", "sent mail": "sent", "sent messages": "sent",
    "drafts": "drafts",
    "trash": "trash", "deleted items": "trash", "deleted messages": "trash", "bin": "trash",
    "junk": "junk", "junk e-mail": "junk", "spam": "junk",
    "archive": "archive", "all mail": "archive",
}

# `(flags) "delimiter" name` -- RFC 3501 mailbox-list, e.g.:
#   (\HasNoChildren \Sent) "/" Sent
#   (\HasNoChildren) "/" "INBOX/Sub Folder"
_LIST_LINE_RE = re.compile(r'^\((?P<flags>[^)]*)\)\s+(?P<delim>"(?:[^"\\]|\\.)*"|NIL)\s+(?P<name>.+)$')


def _unquote(raw: str) -> str | None:
    raw = raw.strip()
    if raw == "NIL":
        return None
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return raw


@dataclass
class DiscoveredFolder:
    name: str
    delimiter: str | None
    special_use: str | None
    is_selectable: bool


def _parse_list_line(raw: bytes) -> DiscoveredFolder | None:
    match = _LIST_LINE_RE.match(raw.decode(errors="replace"))
    if not match:
        return None

    flags = match.group("flags").split()
    delimiter = _unquote(match.group("delim"))
    name = _unquote(match.group("name")) or match.group("name").strip()

    special_use = next((_SPECIAL_USE_FLAGS[f] for f in flags if f in _SPECIAL_USE_FLAGS), None)
    if special_use is None:
        if name.upper() == "INBOX":
            special_use = "inbox"
        else:
            special_use = _NAME_HEURISTICS.get(name.rsplit(delimiter or "/", 1)[-1].strip().lower())

    return DiscoveredFolder(
        name=name,
        delimiter=delimiter,
        special_use=special_use,
        is_selectable="\\Noselect" not in flags,
    )


async def discover_folders(params: ImapParams) -> list[DiscoveredFolder]:
    client = await asyncio.wait_for(connect_imap(params), timeout=CONNECT_TIMEOUT)
    try:
        resp = await imap_login(client, params)
        if resp.result != "OK":
            raise RuntimeError(f"Login failed: {resp.lines}")

        resp = None
        try:
            resp = await asyncio.wait_for(
                client.protocol.simple_command("LIST", '""', '"*"', "RETURN", "(SPECIAL-USE)"),
                client.timeout,
            )
        except Exception:
            resp = None

        if resp is None or resp.result != "OK":
            resp = await client.list('""', '"*"')

        folders = []
        for line in resp.lines:
            parsed = _parse_list_line(line)
            if parsed is not None:
                folders.append(parsed)
        return folders
    finally:
        try:
            await asyncio.wait_for(client.logout(), timeout=5)
        except Exception:
            pass
