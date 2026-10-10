"""A tiny fake IMAP4 server for NekoMail's Ultimit tests -- no real mail
server, no credentials. Plain TCP on 127.0.0.1 (use imap_security "none").

  python fake_imap.py [--port 1143] [--inject-dir DIR] [--seed]

* Any LOGIN is accepted.
* Folders: INBOX, Sent, Drafts, Trash, Archive, Junk (RFC 6154 flags on LIST).
* Commands: CAPABILITY LOGIN LIST SELECT NOOP IDLE/DONE LOGOUT
  [UID] SEARCH, [UID] FETCH (FLAGS RFC822 | header fields), [UID] STORE.
* Drop an .eml file into --inject-dir and it is delivered to INBOX (the file
  is deleted); IDLE clients get an untagged EXISTS, like a real delivery.
* --seed fills INBOX/Sent with a handful of sample messages.
"""
import argparse
import asyncio
import re
import sys
import time
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from datetime import datetime, timedelta, timezone
from pathlib import Path

FOLDERS = [
    ("INBOX", ""), ("Sent", "\\Sent"), ("Drafts", "\\Drafts"),
    ("Trash", "\\Trash"), ("Archive", "\\Archive"), ("Junk", "\\Junk"),
]


class Mailbox:
    def __init__(self):
        self.msgs = []   # [uid, flags(set), raw]
        self.uidnext = 1

    def add(self, raw: bytes, flags=()):
        self.msgs.append([self.uidnext, set(flags), raw])
        self.uidnext += 1


boxes = {name: Mailbox() for name, _ in FOLDERS}
idlers = []   # writers currently in IDLE on INBOX


def make_eml(sender, subject, body, html=None, attach=None, minutes_ago=0, to="me@example.test"):
    m = EmailMessage()
    m["From"] = sender
    m["To"] = to
    m["Subject"] = subject
    m["Date"] = format_datetime(datetime.now(timezone.utc) - timedelta(minutes=minutes_ago))
    m["Message-ID"] = make_msgid(domain="example.test")
    m.set_content(body)
    if html:
        m.add_alternative(html, subtype="html")
    if attach:
        m.add_attachment(attach[1], maintype="application", subtype="octet-stream", filename=attach[0])
    return m.as_bytes()


def seed():
    def put(box, *args, flags=(), **kw):
        boxes[box].add(make_eml(*args, **kw), flags)

    put("INBOX", "Hikari Tanaka <hikari@example.test>", "Welcome to Ultimit", "The Wired is quiet tonight.\nSee you in the Root Town.", minutes_ago=5,
        html="<p>The <b>Wired</b> is quiet tonight.</p><p>See you in the Root Town.</p>")
    put("INBOX", "Orca <orca@example.test>", "Re: Pluto's Kiss lead", "I checked the logs. Nothing out of the ordinary.", minutes_ago=90)
    put("INBOX", "Build Bot <ci@example.test>", "[nekomail] build #412 passed", "All checks passed.", minutes_ago=240, flags=["\\Seen"])
    put("INBOX", "Mimiru <mimiru@example.test>", "Skeith screenshots", "Attached the shots from last night.", minutes_ago=600,
        attach=("skeith.bin", b"\x00\x01fake"))
    put("INBOX", "Balmung <balmung@example.test>", "Raid on Saturday?", "Same time as before, bring the party.", minutes_ago=1500, flags=["\\Seen", "\\Flagged"])
    put("INBOX", "Neko Weekly <news@example.test>", "Ten cats who found the Wired", "Whiskers, keyboards and a surprising amount of nap.", minutes_ago=3000, flags=["\\Seen"])
    put("Sent", "me@example.test", "Quick question", "Is the server back up?", to="orca@example.test", minutes_ago=800, flags=["\\Seen"])


def fmt_flags(flags):
    return "(" + " ".join(sorted(flags)) + ")"


def parse_set(spec, uids):
    out = set()
    top = max(uids) if uids else 0
    for part in spec.split(","):
        if ":" in part:
            a, b = part.split(":")
            a = top if a == "*" else int(a)
            b = top if b == "*" else int(b)
            out.update(u for u in uids if min(a, b) <= u <= max(a, b))
        elif part:
            n = top if part == "*" else int(part)
            if n in uids:
                out.add(n)
    return out


async def deliver(raw: bytes):
    inbox = boxes["INBOX"]
    inbox.add(raw)
    for w in list(idlers):
        try:
            w.write(f"* {len(inbox.msgs)} EXISTS\r\n".encode())
            await w.drain()
        except Exception:
            idlers.remove(w)


async def watch_inject(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    while True:
        for f in sorted(directory.glob("*.eml")):
            await deliver(f.read_bytes())
            f.unlink()
        await asyncio.sleep(0.3)


async def handle(reader, writer):
    selected = None
    uidvalidity = 1
    send = lambda s: writer.write(s if isinstance(s, bytes) else s.encode())
    send("* OK fake IMAP ready\r\n")
    await writer.drain()
    while True:
        line = await reader.readline()
        if not line:
            break
        text = line.decode(errors="replace").rstrip("\r\n")
        if not text:
            continue
        tag, _, rest = text.partition(" ")
        cmd, _, args = rest.partition(" ")
        cmd = cmd.upper()
        uid_mode = False
        if cmd == "UID":
            uid_mode = True
            cmd, _, args = args.partition(" ")
            cmd = cmd.upper()
        if cmd == "CAPABILITY":
            send("* CAPABILITY IMAP4rev1 IDLE SPECIAL-USE\r\n")
            send(f"{tag} OK CAPABILITY completed\r\n")
        elif cmd == "LOGIN":
            send(f"{tag} OK LOGIN completed\r\n")
        elif cmd == "LIST":
            for name, attr in FOLDERS:
                send(f'* LIST ({attr}) "/" {name}\r\n')
            send(f"{tag} OK LIST completed\r\n")
        elif cmd == "SELECT":
            name = args.strip().strip('"')
            if name not in boxes:
                send(f"{tag} NO no such mailbox\r\n")
            else:
                selected = name
                b = boxes[name]
                send(f"* {len(b.msgs)} EXISTS\r\n* 0 RECENT\r\n* FLAGS (\\Seen \\Answered \\Flagged \\Deleted \\Draft)\r\n"
                     f"* OK [UIDVALIDITY {uidvalidity}] ok\r\n* OK [UIDNEXT {b.uidnext}] ok\r\n"
                     f"{tag} OK [READ-WRITE] SELECT completed\r\n")
        elif cmd == "NOOP":
            send(f"{tag} OK NOOP completed\r\n")
        elif cmd == "SEARCH" and selected:
            b = boxes[selected]
            m = re.search(r"UID\s+(\S+)", args)
            uids = [u for u, _, _ in b.msgs]
            chosen = sorted(parse_set(m.group(1), uids)) if m else uids
            send("* SEARCH " + " ".join(map(str, chosen)) + "\r\n" if chosen else "* SEARCH\r\n")
            send(f"{tag} OK SEARCH completed\r\n")
        elif cmd == "FETCH" and selected:
            b = boxes[selected]
            spec, _, items = args.partition(" ")
            uids = [u for u, _, _ in b.msgs]
            wanted = parse_set(spec, uids) if uid_mode else {b.msgs[i - 1][0] for i in parse_set(spec, list(range(1, len(b.msgs) + 1)))}
            for idx, (uid, flags, raw) in enumerate(b.msgs, 1):
                if uid not in wanted:
                    continue
                if "RFC822" in items and "HEADER" not in items:
                    send(f"* {idx} FETCH (UID {uid} FLAGS {fmt_flags(flags)} RFC822 {{{len(raw)}}}\r\n")
                    send(raw)
                    send(")\r\n")
                else:
                    hdr = raw.split(b"\r\n\r\n", 1)[0] + b"\r\n\r\n"
                    send(f"* {idx} FETCH (UID {uid} FLAGS {fmt_flags(flags)} BODY[HEADER.FIELDS (MESSAGE-ID)] {{{len(hdr)}}}\r\n")
                    send(hdr)
                    send(")\r\n")
            send(f"{tag} OK FETCH completed\r\n")
        elif cmd == "STORE" and selected:
            b = boxes[selected]
            spec, _, rest2 = args.partition(" ")
            m = re.match(r"([+-]?)FLAGS(?:\.SILENT)?\s+\(?([^)]*)\)?", rest2.strip(), re.I)
            uids = [u for u, _, _ in b.msgs]
            wanted = parse_set(spec, uids) if uid_mode else {b.msgs[i - 1][0] for i in parse_set(spec, list(range(1, len(b.msgs) + 1)))}
            if m:
                sign, fl = m.group(1), set(m.group(2).split())
                for entry in b.msgs:
                    if entry[0] in wanted:
                        entry[1] = (entry[1] | fl) if sign == "+" else (entry[1] - fl) if sign == "-" else fl
            send(f"{tag} OK STORE completed\r\n")
        elif cmd == "IDLE" and selected == "INBOX":
            send("+ idling\r\n")
            await writer.drain()
            idlers.append(writer)
            while True:
                l = await reader.readline()
                if not l or l.strip().upper() == b"DONE":
                    break
            if writer in idlers:
                idlers.remove(writer)
            send(f"{tag} OK IDLE terminated\r\n")
        elif cmd == "APPEND":
            m = re.match(r'"?([^"\s]+)"?\s+(?:\(([^)]*)\)\s+)?(?:"[^"]*"\s+)?\{(\d+)\+?\}', args)
            if not m or m.group(1) not in boxes:
                send(f"{tag} NO bad APPEND\r\n")
            else:
                send("+ ready\r\n")
                await writer.drain()
                raw = await reader.readexactly(int(m.group(3)))
                await reader.readline()
                box = boxes[m.group(1)]
                flags = set((m.group(2) or "").split())
                box.add(raw, flags)
                send(f"{tag} OK [APPENDUID {uidvalidity} {box.uidnext - 1}] APPEND completed\r\n")
        elif cmd == "LOGOUT":
            send(f"* BYE\r\n{tag} OK LOGOUT completed\r\n")
            await writer.drain()
            break
        else:
            send(f"{tag} NO unsupported in fake server\r\n")
        await writer.drain()
    writer.close()


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=1143)
    ap.add_argument("--inject-dir", type=Path)
    ap.add_argument("--seed", action="store_true")
    a = ap.parse_args()
    if a.seed:
        seed()
    server = await asyncio.start_server(handle, "127.0.0.1", a.port)
    if a.inject_dir:
        asyncio.create_task(watch_inject(a.inject_dir))
    print(f"fake IMAP on 127.0.0.1:{a.port}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
