"""
Phase 2 spike: confirm aioimaplib IDLE/DONE/cancellation behavior in isolation
before building the sync manager around it.

Target: mailcow instance at mail.nekos.farm. Standard IMAPS on 993
(confirmed reachable directly -- this host is on the same LAN as the
mail server, so no relay/tunnel is needed here).

Usage:
    N:\\projects\\nekomail\\backend\\.venv\\Scripts\\python.exe idle_spike.py

What this verifies:
  1. Can we log in at all over the multiplexed port?
  2. Does IDLE actually deliver an unsolicited EXISTS/EXPUNGE untagged
     response when new mail arrives, within a reasonable window?
  3. Does `idle_done()` cleanly end the IDLE command so the connection
     can immediately issue another command afterward?
  4. What happens if we cancel the idle_start() task mid-flight (simulates
     shutdown/reconnect) -- does the connection end up in a usable state?
"""

import asyncio
import ssl

from aioimaplib import aioimaplib

HOST = "mail.nekos.farm"
PORT = 993
EMAIL = "test123@nekos.farm"
PASSWORD = "test123"

IDLE_WINDOW_SECONDS = 60


def make_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    # This mailcow instance's Dovecot IMAPS cert is self-signed (separate
    # from the web UI's cert). Fine for this throwaway spike against our
    # own known test server; the real account-management code must NOT
    # do this for user-supplied hosts.
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


async def connect() -> aioimaplib.IMAP4_SSL:
    client = aioimaplib.IMAP4_SSL(
        host=HOST,
        port=PORT,
        ssl_context=make_ssl_context(),
    )
    await client.wait_hello_from_server()
    return client


async def login(client: aioimaplib.IMAP4_SSL) -> None:
    resp = await client.login(EMAIL, PASSWORD)
    print(f"LOGIN -> {resp.result}: {resp.lines}")
    if resp.result != "OK":
        raise RuntimeError("login failed")


async def select_inbox(client: aioimaplib.IMAP4_SSL) -> None:
    resp = await client.select("INBOX")
    print(f"SELECT INBOX -> {resp.result}: {resp.lines}")


async def run_idle_window(client: aioimaplib.IMAP4_SSL, seconds: int) -> None:
    print(f"\n--- starting IDLE, watching for {seconds}s (send mail to {EMAIL} now) ---")
    idle_task = await client.idle_start(timeout=seconds)
    try:
        while True:
            msg = await client.wait_server_push(timeout=seconds)
            if msg is None or msg == aioimaplib.STOP_WAIT_SERVER_PUSH:
                break
            print(f"PUSH: {msg}")
    finally:
        client.idle_done()
        try:
            await asyncio.wait_for(idle_task, timeout=5)
        except asyncio.TimeoutError:
            print("WARNING: idle_task did not finish within 5s of idle_done()")
    print("--- IDLE ended cleanly ---")


async def run_idle_cancellation_check(client: aioimaplib.IMAP4_SSL) -> None:
    """Uses its own connection: a bare task.cancel() can wedge the socket
    (server is left thinking IDLE is still active), so this must not share
    a connection with anything that needs to keep working afterward."""
    print("\n--- starting IDLE, then cancelling the task after 3s (own connection) ---")
    idle_task = await client.idle_start(timeout=30)
    await asyncio.sleep(3)
    idle_task.cancel()
    try:
        await idle_task
    except asyncio.CancelledError:
        print("idle_task cancelled as expected")

    try:
        resp = await asyncio.wait_for(client.noop(), timeout=8)
        print(f"NOOP after cancel -> {resp.result}: {resp.lines}")
    except asyncio.TimeoutError:
        print("FINDING: NOOP after raw task.cancel() timed out -- connection is "
              "wedged. Cancelling the asyncio task does NOT send IMAP DONE; the "
              "server still thinks we're in IDLE. Shutdown/reconnect paths must "
              "always call idle_done() (and await it) instead of bare cancel().")


async def main() -> None:
    client = await connect()
    try:
        await login(client)
        await select_inbox(client)
        await run_idle_window(client, IDLE_WINDOW_SECONDS)
        try:
            await asyncio.wait_for(client.logout(), timeout=5)
        except asyncio.TimeoutError:
            print("WARNING: logout after graceful IDLE window timed out")
    finally:
        pass

    cancel_client = await connect()
    try:
        await login(cancel_client)
        await select_inbox(cancel_client)
        await run_idle_cancellation_check(cancel_client)
    finally:
        try:
            await asyncio.wait_for(cancel_client.logout(), timeout=5)
        except asyncio.TimeoutError:
            print("logout on wedged connection timed out as expected -- "
                  "closing transport directly instead")
            cancel_client.protocol.transport.close()


if __name__ == "__main__":
    asyncio.run(main())
