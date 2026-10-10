"""Ultimit desktop integration: tell the frontend which skin the desktop uses."""
import time

from fastapi import APIRouter, Response

import desktop_env

router = APIRouter(prefix="/api/ultimit", tags=["ultimit"])

_cache: tuple[float, dict] = (0.0, {})


@router.get("/skin")
async def skin(response: Response):
    """Public (a skin name is not sensitive; the login page needs it too).
    Reads ``~/.config/ultimit/shell.json`` ("skin" key, default "mine");
    the frontend polls this so a skin change in Ultimit's Settings re-skins
    NekoMail live. Cached ~1s so several windows/polls don't re-read the file."""
    global _cache
    now = time.monotonic()
    if now - _cache[0] > 1.0:
        _cache = (now, desktop_env.read_skin())
    response.headers["Cache-Control"] = "no-store"
    return _cache[1]
