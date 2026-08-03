import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from starlette.middleware.base import BaseHTTPMiddleware

from config import settings
from routers import accounts as accounts_router
from routers import auth as auth_router
from routers import compose as compose_router
from routers import contacts as contacts_router
from routers import messages as messages_router
from routers import oauth as oauth_router
from routers import rules as rules_router
from routers import ws as ws_router
from services.mail import scheduler

logging.basicConfig(level=logging.INFO)

FRONTEND_DIST = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await scheduler.start()
    try:
        yield
    finally:
        await scheduler.stop()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response


app = FastAPI(
    title="NekoMail API",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(SecurityHeadersMiddleware)

app.include_router(auth_router.router)
app.include_router(accounts_router.router)
app.include_router(messages_router.router)
app.include_router(compose_router.router)
app.include_router(contacts_router.router)
app.include_router(oauth_router.router)
app.include_router(rules_router.router)
app.include_router(ws_router.router)


@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.app_name}


# --- Serve the built Vue SPA (frontend/dist copied into ./static at build time) ---
# Anything under /api or /ws is handled by routers above; everything else falls
# through to the SPA's index.html so client-side routing (Vue Router) works,
# except when the request matches a real built asset (js/css/icons/manifest/sw.js).
if FRONTEND_DIST.exists():
    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
