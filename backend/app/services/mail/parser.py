"""Parse a raw RFC822 message (as fetched from IMAP) into the fields the
sync engine (Phase 4) needs to populate Message/Attachment rows.

Uses stdlib `email` with `policy.default` so headers come back as already
RFC2047-decoded str/structured objects instead of raw encoded-word text.
"""

import html as html_module
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from email import message_from_bytes
from email.message import EmailMessage
from email.policy import default as default_policy

SNIPPET_LENGTH = 200

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass
class ParsedAddress:
    name: str | None
    email: str


@dataclass
class ParsedAttachment:
    filename: str | None
    mime_type: str
    size: int
    content_id: str | None
    is_inline: bool


@dataclass
class ParsedMessage:
    message_id_header: str | None
    in_reply_to: str | None
    references: str | None
    thread_id: str

    from_addrs: list[dict] = field(default_factory=list)
    to_addrs: list[dict] = field(default_factory=list)
    cc_addrs: list[dict] = field(default_factory=list)
    bcc_addrs: list[dict] = field(default_factory=list)

    subject: str | None = None
    date: datetime | None = None
    snippet: str | None = None
    body_text: str | None = None

    has_attachments: bool = False
    is_encrypted: bool = False

    attachments: list[ParsedAttachment] = field(default_factory=list)


def _addresses(msg: EmailMessage, header: str) -> list[dict]:
    field_obj = msg.get(header)
    if field_obj is None:
        return []
    addresses = getattr(field_obj, "addresses", None)
    if addresses is None:
        return []
    return [{"name": a.display_name or None, "email": a.addr_spec} for a in addresses if a.addr_spec]


def _clean_id(raw: str | None) -> str | None:
    if raw is None:
        return None
    raw = str(raw).strip()
    return raw or None


def _extract_text(msg: EmailMessage) -> str | None:
    body = msg.get_body(preferencelist=("plain",))
    if body is not None:
        try:
            return body.get_content()
        except Exception:
            return None

    body = msg.get_body(preferencelist=("html",))
    if body is not None:
        try:
            raw_html = body.get_content()
        except Exception:
            return None
        text = _TAG_RE.sub(" ", raw_html)
        text = html_module.unescape(text)
        return _WHITESPACE_RE.sub(" ", text).strip()

    return None


def _make_snippet(text: str | None) -> str | None:
    if not text:
        return None
    collapsed = _WHITESPACE_RE.sub(" ", text).strip()
    if not collapsed:
        return None
    return collapsed[:SNIPPET_LENGTH]


def _detect_encrypted(msg: EmailMessage, body_text: str | None) -> bool:
    if msg.get_content_type() == "multipart/encrypted":
        return True
    for part in msg.walk():
        if part.get_content_type() == "application/pgp-encrypted":
            return True
    if body_text and body_text.lstrip().startswith("-----BEGIN PGP MESSAGE-----"):
        return True
    return False


def _extract_attachments(msg: EmailMessage) -> list[ParsedAttachment]:
    attachments = []
    try:
        parts = list(msg.iter_attachments())
    except Exception:
        parts = []

    for part in parts:
        try:
            payload = part.get_payload(decode=True)
        except Exception:
            payload = None
        attachments.append(ParsedAttachment(
            filename=part.get_filename(),
            mime_type=part.get_content_type() or "application/octet-stream",
            size=len(payload) if payload is not None else 0,
            content_id=_clean_id(part.get("Content-ID")),
            is_inline=part.get_content_disposition() == "inline",
        ))
    return attachments


def _thread_id(message_id: str | None, in_reply_to: str | None, references: str | None) -> str:
    if references:
        first = references.split()[0] if references.split() else None
        if first:
            return first
    if in_reply_to:
        return in_reply_to
    if message_id:
        return message_id
    return f"generated:{uuid.uuid4()}"


def extract_html_body(raw: bytes) -> str | None:
    """Pull the HTML part out of a raw .eml on demand -- there's deliberately
    no `body_html` DB column (see parse_message/_extract_text), so the
    reading pane re-parses the stored .eml each time it wants to render one."""
    msg = message_from_bytes(raw, policy=default_policy)
    body = msg.get_body(preferencelist=("html",))
    if body is None:
        return None
    try:
        return body.get_content()
    except Exception:
        return None


def extract_pgp_ciphertext(raw: bytes) -> str | None:
    """Pull just the armored ciphertext block out of a raw .eml for
    client-side decryption (Phase 9) -- the backend never decrypts, it only
    locates the blob within whatever real-world MIME structure the sending
    client used, since hand-parsing PGP/MIME's `multipart/encrypted` (RFC
    3156: a version-marker part + an application/octet-stream part holding
    the actual ciphertext) client-side in JS would mean re-implementing a
    MIME parser in the browser -- stdlib `email` already does this robustly.

    Handles both PGP/MIME (the structured form NekoMail's own compose flow
    produces) and legacy inline PGP (a bare `-----BEGIN PGP MESSAGE-----`
    block directly in a text part, for interop with older senders)."""
    msg = message_from_bytes(raw, policy=default_policy)

    if msg.get_content_type() == "multipart/encrypted":
        for part in msg.iter_parts():
            if part.get_content_type() == "application/octet-stream":
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(errors="replace")
        return None

    body = msg.get_body(preferencelist=("plain",))
    if body is not None:
        try:
            text = body.get_content()
        except Exception:
            text = None
        if text and "-----BEGIN PGP MESSAGE-----" in text:
            return text

    return None


def extract_attachment_payload(raw: bytes, ordinal: int) -> tuple[bytes, str, str | None] | None:
    """Re-parse a raw .eml and return the ordinal-th attachment's
    (payload, mime_type, filename). `ordinal` must match the position the
    matching Attachment row was created at in `_extract_attachments` --
    callers derive this by ordering their Attachment rows by `id` (insertion
    order), which reproduces `iter_attachments()`'s traversal order exactly."""
    msg = message_from_bytes(raw, policy=default_policy)
    try:
        parts = list(msg.iter_attachments())
    except Exception:
        parts = []

    if ordinal < 0 or ordinal >= len(parts):
        return None

    part = parts[ordinal]
    try:
        payload = part.get_payload(decode=True)
    except Exception:
        payload = None
    if payload is None:
        return None

    mime_type = part.get_content_type() or "application/octet-stream"
    filename = part.get_filename()
    return payload, mime_type, filename


def parse_message(raw: bytes) -> ParsedMessage:
    msg = message_from_bytes(raw, policy=default_policy)

    message_id = _clean_id(msg.get("Message-ID"))
    in_reply_to = _clean_id(msg.get("In-Reply-To"))
    references = _clean_id(msg.get("References"))

    subject = msg.get("Subject")
    subject = str(subject) if subject is not None else None

    date_header = msg.get("Date")
    date = None
    if date_header is not None:
        try:
            date = date_header.datetime
        except Exception:
            date = None

    body_text = _extract_text(msg)
    attachments = _extract_attachments(msg)

    return ParsedMessage(
        message_id_header=message_id,
        in_reply_to=in_reply_to,
        references=references,
        thread_id=_thread_id(message_id, in_reply_to, references),
        from_addrs=_addresses(msg, "From"),
        to_addrs=_addresses(msg, "To"),
        cc_addrs=_addresses(msg, "Cc"),
        bcc_addrs=_addresses(msg, "Bcc"),
        subject=subject,
        date=date,
        snippet=_make_snippet(body_text),
        body_text=body_text,
        has_attachments=len(attachments) > 0,
        is_encrypted=_detect_encrypted(msg, body_text),
        attachments=attachments,
    )
