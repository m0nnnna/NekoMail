"""In-process WebSocket fan-out for push events (new mail, etc).

Single admin user (see NEXT_STEPS.md confirmed decisions) so there's no
per-user routing -- every connected client gets every broadcast. Requires
`uvicorn --workers 1`: connections live in this process's memory only.
"""

import json
import logging

from starlette.websockets import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    async def broadcast(self, message: dict) -> None:
        if not self._connections:
            return
        payload = json.dumps(message)
        dead = []
        for ws in list(self._connections):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections.discard(ws)


manager = ConnectionManager()
