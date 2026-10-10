"""Local fake SMTP sink (aiosmtpd) for NekoMail's Ultimit tests: accepts
anything, prints each message's envelope + subject, writes it to --out-dir.
No auth, no TLS; use smtp_security "none"."""
import argparse
import asyncio
from pathlib import Path

from aiosmtpd.controller import Controller
from aiosmtpd.smtp import AuthResult, LoginPassword


def accept_any(server, session, envelope, mechanism, auth_data):
    return AuthResult(success=True)


class Sink:
    def __init__(self, out: Path):
        self.out = out
        self.n = 0

    async def handle_DATA(self, server, session, envelope):
        self.n += 1
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / f"{self.n}.eml").write_bytes(envelope.content)
        print(f"SMTP {envelope.mail_from} -> {envelope.rcpt_tos} ({len(envelope.content)} bytes)", flush=True)
        return "250 OK"


ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=1025)
ap.add_argument("--out-dir", type=Path, default=Path("smtp-out"))
a = ap.parse_args()
c = Controller(Sink(a.out_dir), hostname="127.0.0.1", port=a.port, auth_required=False,
               authenticator=accept_any, auth_require_tls=False)
c.start()
print(f"fake SMTP on 127.0.0.1:{a.port}", flush=True)
try:
    asyncio.get_event_loop_policy()
    import time
    while True:
        time.sleep(3600)
except KeyboardInterrupt:
    c.stop()
