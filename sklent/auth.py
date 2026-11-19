"""Who may call /api and /mcp: the admin token (SK_TOKEN) or a read-only viewer token.

A viewer token (Settings → Tokens, see `sklent.features.inputs.tokens`) may browse, view
and download: GET and HEAD under /api (except the token list), and MCP tools that only
read. Everything else answers 403. A tool counts as read-only when it is in
VIEWER_TOOLS, was added with `allow_viewer_tools(...)`, or declares
`annotations=ToolAnnotations(readOnlyHint=True)`.

The role is put in the request scope: `scope["state"]["sk_role"]` is "admin" or "viewer"
(`GET /api/whoami` reports it), and `scope["state"]["sk_viewer"]` names the viewer token.
"""

import json
import secrets

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import get_settings

PUBLIC_PATHS = {"/api/health"}
COOKIE = "sk_token"
WEAK_TOKENS = {"", "change-me", "changeme", "secret", "token"}
MIN_TOKEN_LENGTH = 16

# API paths a viewer may not read even with GET.
VIEWER_DENIED_PREFIXES = ("/api/tokens",)
# MCP tools a viewer may call (they only read). Features add theirs with allow_viewer_tools()
# or by marking the tool read-only (ToolAnnotations(readOnlyHint=True)).
VIEWER_TOOLS = {
    "list_sources", "list_designs", "job_status", "list_jobs", "wait_for_job", "get_render_set",
    "view_render", "get_render_settings",
}


def allow_viewer_tools(*names: str) -> None:
    """Let viewer tokens call these MCP tools (each must only read)."""
    VIEWER_TOOLS.update(names)


def check_token(token: str) -> None:
    if token.strip() in WEAK_TOKENS or len(token) < MIN_TOKEN_LENGTH:
        raise RuntimeError(
            "SK_TOKEN is unset or too weak: set it in .env to a random value of at least "
            f"{MIN_TOKEN_LENGTH} characters (e.g. `openssl rand -hex 24`)"
        )


def viewer_for(token: str) -> dict | None:
    """The live viewer token with this value, or None."""
    try:
        from .features.inputs import tokens
    except ImportError:  # pragma: no cover - the feature ships with the app
        return None
    return tokens.lookup(token)


def viewer_may_call(tool: str) -> bool:
    try:
        from .mcp_server import WRITE_TOOLS
    except Exception:  # noqa: BLE001
        WRITE_TOOLS = frozenset()  # noqa: N806
    if tool in WRITE_TOOLS:  # classified as writing: never, whatever else says otherwise
        return False
    if tool in VIEWER_TOOLS:
        return True
    try:
        from .mcp_server import mcp

        t = mcp._tool_manager.get_tool(tool)
    except Exception:  # noqa: BLE001 - unknown tool or MCP internals moved: deny
        return False
    ann = getattr(t, "annotations", None) if t else None
    return bool(ann and (getattr(ann, "read_only_hint", None) or getattr(ann, "readOnlyHint", None)))


def _denied(message: str) -> JSONResponse:
    return JSONResponse({"detail": message}, status_code=403)


class BearerTokenMiddleware:
    """Require a token on /api and /mcp, as Kist does.

    Accepted as an `Authorization: Bearer` header, a `token` query parameter, or (GET/HEAD
    only) the `sk_token` cookie the web UI sets so <img>/<video> tags load. The cookie is
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
        viewer = None
        if not token:
            ok = False
        elif secrets.compare_digest(token, get_settings().token):
            ok = True
        else:
            viewer = viewer_for(token)
            ok = viewer is not None
        if not ok:
            await JSONResponse({"detail": "invalid or missing token"}, status_code=401)(scope, receive, send)
            return
        state = scope.setdefault("state", {})
        state["sk_role"] = "viewer" if viewer else "admin"
        if viewer:
            state["sk_viewer"] = viewer["name"]
            if path.startswith("/api"):
                if scope["method"] not in ("GET", "HEAD"):
                    await _denied("this is a read-only viewer token")(scope, receive, send)
                    return
                if path.startswith(VIEWER_DENIED_PREFIXES):
                    await _denied("viewer tokens can't manage tokens")(scope, receive, send)
                    return
            elif scope["method"] == "POST":
                checked = await self._check_mcp(scope, receive, send)
                if checked is None:
                    return
                receive = checked
        await self.app(scope, receive, send)

    async def _check_mcp(self, scope: Scope, receive: Receive, send: Send) -> Receive | None:
        """Read an MCP request body and refuse a viewer's call to a tool that writes.
        Returns a receive callable that replays the body, or None when refused."""
        chunks, more = [], True
        while more:
            msg = await receive()
            if msg["type"] != "http.request":
                return receive
            chunks.append(msg.get("body", b""))
            more = msg.get("more_body", False)
        body = b"".join(chunks)
        try:
            payload = json.loads(body or b"null")
        except ValueError:
            payload = None
        for m in payload if isinstance(payload, list) else [payload]:
            if isinstance(m, dict) and m.get("method") == "tools/call":
                name = str((m.get("params") or {}).get("name") or "")
                if not viewer_may_call(name):
                    await JSONResponse({
                        "jsonrpc": "2.0", "id": m.get("id"),
                        "error": {"code": -32001, "message": f"{name} changes things; a viewer token can only read"},
                    }, status_code=403)(scope, receive, send)
                    return None
        sent = False

        async def replay() -> Message:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        return replay
