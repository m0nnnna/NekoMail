from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from dependencies import require_auth
from models.user import User
from services.ws_manager import manager

router = APIRouter(tags=["ws"])


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, user: Annotated[User, Depends(require_auth)]):
    await manager.connect(websocket)
    try:
        while True:
            # Server push only -- just block until the client disconnects.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket)
