import secrets

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import get_settings

PUBLIC_PATHS = {"/api/health"}
COOKIE = "la_token"
WEAK_TOKENS = {"", "change-me", "changeme", "secret", "token"}
MIN_TOKEN_LENGTH = 16


def check_token(token: str) -> None:
    if token.strip() in WEAK_TOKENS or len(token) < MIN_TOKEN_LENGTH:
        raise RuntimeError(
            "LA_TOKEN is unset or too weak: set it in .env to a random value of at least "
            f"{MIN_TOKEN_LENGTH} characters (e.g. `openssl rand -hex 24`)"
        )


class BearerTokenMiddleware:
    """Require the shared token on /api and /mcp, as Kist does.

    Accepted as `Authorization: Bearer <token>`, a `token` query parameter, or (GET/HEAD
    only) the `la_token` cookie the web UI sets so <img>/<video> tags load. The cookie is
    read-only so another site can't ride it into state-changing requests.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        if not (path.startswith("/api") or path.startswith("/mcp")) or path in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        token = ""
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
        if not token and scope["method"] in ("GET", "HEAD"):
            token = request.cookies.get(COOKIE, "")
        if not token:
            token = request.query_params.get("token", "")
        if not token or not secrets.compare_digest(token, get_settings().token):
            await JSONResponse({"detail": "invalid or missing token"}, status_code=401)(
                scope, receive, send)
            return
        await self.app(scope, receive, send)
