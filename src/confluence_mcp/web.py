"""Local web page where a person approves queued Confluence writes."""

from __future__ import annotations

import json
import secrets
import subprocess
import sys
import threading
import webbrowser
from collections import Counter
from contextlib import ExitStack
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from . import queue
from .apply import approve_and_apply
from .preview import provenance, proposed_storage, render_document
from .web_page import PAGE

COOKIE = "cmr_session"
MAX_BODY = 64 * 1024
CSP = (
    "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
    "connect-src 'self'; frame-src 'self'"
)
# The rendered body is untrusted, so its document is sandboxed even when framed directly.
PREVIEW_CSP = (
    "default-src 'none'; img-src http: https: data:; style-src 'unsafe-inline'; base-uri 'none'; "
    "form-action 'none'; frame-ancestors 'self'; sandbox"
)
_ACTIVE = ("pending", "approved", "executing")
_ATTENTION = ("failed", "indeterminate")
_HISTORY_STATUSES = {
    "all": ("succeeded", "rejected", *_ATTENTION),
    "succeeded": ("succeeded",),
    "attention": _ATTENTION,
    "rejected": ("rejected",),
}
_FIELDS = (
    "id", "status", "action", "kind", "space_key", "page_id", "version_before",
    "summary", "preview", "result", "error", "created_at", "updated_at",
)
_HISTORY_PAGE_SIZE = 20
_TITLE_MAX = 300
_REJECTION_REASON_MAX = 500
_PER_OPERATION = ("/api/body", "/api/render", "/api/location")
# Serializes sends so two clicks on one operation cannot race for the claim.
_apply_lock = threading.Lock()


def _view(op: dict[str, Any]) -> dict[str, Any]:
    view = {key: op[key] for key in _FIELDS}
    payload = op["payload"]
    # The page title lives only in the payload; a section update's summary is the heading.
    view["title"] = _title(op)
    version = payload.get("version")
    message = version.get("message") if isinstance(version, dict) else None
    view["version_message"] = (
        message if isinstance(message, str) and message.strip() not in {"", "[MCP]"} else None
    )
    # Explicit provenance labels only (see preview.provenance); derived locally, no Confluence read.
    info = provenance(proposed_storage(op)) or {}
    view["collection"] = info.get("collection")
    view["source"] = info.get("source")
    view["attachments"] = queue.attachment_summaries(op["id"])
    return view


def _title(op: dict[str, Any]) -> str | None:
    title = op["payload"].get("title")
    return title[:_TITLE_MAX] if isinstance(title, str) else None


def _state(history: str, page: int, query: str, space: str) -> dict[str, Any]:
    ops = queue.list_ops()
    counts = Counter(op["status"] for op in ops)
    active = [op for op in ops if op["status"] in _ACTIVE]
    statuses = _HISTORY_STATUSES[history]
    query = query.strip().lower()
    finished = sorted(
        (
            op for op in reversed(ops)
            if op["status"] in statuses
            and (not space or op["space_key"] == space)
            and (not query or query in _history_search_text(op))
        ),
        key=lambda op: op["updated_at"],
        reverse=True,
    )
    pages = max(1, (len(finished) + _HISTORY_PAGE_SIZE - 1) // _HISTORY_PAGE_SIZE)
    page = min(page, pages)
    start = (page - 1) * _HISTORY_PAGE_SIZE
    return {
        "operations": [_view(op) for op in active + finished[start : start + _HISTORY_PAGE_SIZE]],
        "totals": {
            "active": len(active),
            "succeeded": counts["succeeded"],
            "attention": sum(counts[status] for status in _ATTENTION),
        },
        "total": len(ops),
        "spaces": sorted({op["space_key"] for op in ops if op["space_key"]}),
        "history": {"page": page, "pages": pages},
    }


def _history_search_text(op: dict[str, Any]) -> str:
    title = _title(op)
    if not title:
        title = "评论 · 页面 " + str(op["page_id"]) if op["action"] == "add_comment" else op["summary"]
    return " ".join((title, op["id"], op["summary"])).lower()


def _location(client: Any, op: dict[str, Any]) -> dict[str, Any]:
    """Where a queued write lands: the page it changes, its container, or a new page's parent.

    Read on demand for one operation and never stored, so the queue is not touched.
    """
    payload = op["payload"]
    ancestors = payload.get("ancestors") or []
    # A create names its parent only in the payload, so the queue row has no page_id for it.
    page_id = op["page_id"] or (str(ancestors[-1]["id"]) if ancestors else None)
    if op["action"] == "add_comment":
        mode = "comment"
    elif op["action"] == "move_page":
        mode = "move"
    elif op["kind"] == "create":
        mode = "create"
    else:
        mode = "update"
    location: dict[str, Any] = {
        "mode": mode,
        "space_key": op["space_key"],
        "title": payload.get("title"),
        "trail": [],
        "partial": False,
    }
    if page_id is None:
        return location
    page = client.get_page(page_id)
    trail = [*(page.get("ancestors") or []), page]
    location["trail"] = [
        {"title": item.get("title") or "", "url": client.page_url(item)} for item in trail
    ]
    location["partial"] = "ancestors" not in page
    return location


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        # The request line of the first visit carries the token, so log nothing.
        pass

    def _send(
        self,
        status: int,
        body: bytes = b"",
        content_type: str = "application/json",
        headers: tuple[tuple[str, str], ...] = (),
        frame: str = "DENY",
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", frame)
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: Any) -> None:
        self._send(status, json.dumps(payload).encode("utf-8"))

    def _deny(self) -> None:
        self._json(403, {"error": "forbidden"})

    def _hosts(self) -> set[str]:
        port = self.server.server_address[1]
        return {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _host_ok(self) -> bool:
        # Rejecting other Host values stops DNS-rebinding pages from reaching us.
        return self.headers.get("Host") in self._hosts()

    def _authorized(self, require_origin: bool) -> bool:
        if not self._host_ok():
            return False
        if require_origin and self.headers.get("Origin") not in {
            f"http://{host}" for host in self._hosts()
        }:
            return False
        jar = SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie", ""))
        except CookieError:
            return False
        morsel = jar.get(COOKIE)
        return morsel is not None and secrets.compare_digest(
            morsel.value.encode("utf-8"), self.server.token.encode("utf-8")
        )

    def _drain(self) -> None:
        # Discard (never parse) a bounded request body so closing the socket does not
        # reset the connection before the client reads our answer.
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return
        if length > 0:
            self.rfile.read(min(length, MAX_BODY))

    def _read_action(self, path: str) -> tuple[list[str], str]:
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= MAX_BODY:
            raise ValueError("请求内容为空或过大。")
        data = json.loads(self.rfile.read(length))
        ids = data.get("ids") if isinstance(data, dict) else None
        if not isinstance(ids, list) or not 1 <= len(ids) <= 200 or not all(
            isinstance(item, str) for item in ids
        ):
            raise ValueError("ids must be a list of 1 to 200 strings")
        reason = data.get("reason", "") if path == "/api/reject" else ""
        if not isinstance(reason, str) or len(reason.strip()) > _REJECTION_REASON_MAX:
            raise ValueError(f"拒绝原因须为不超过 {_REJECTION_REASON_MAX} 个字符的文本。")
        return ids, reason.strip()

    def _per_operation(self, path: str, op_id: str) -> None:
        op = queue.get_op(op_id) if op_id else None
        if op is None:
            self._json(404, {"error": "not found"})
        elif path == "/api/body":
            self._json(200, {"storage": proposed_storage(op)})
        elif path == "/api/render":
            self._send(
                200,
                render_document(proposed_storage(op), queue.get_attachments(op["id"])).encode("utf-8"),
                "text/html; charset=utf-8",
                (("Content-Security-Policy", PREVIEW_CSP),),
                frame="SAMEORIGIN",
            )
        else:
            try:
                location = _location(self.server.client, op)
            except Exception as exc:
                self._json(502, {"error": str(exc)})
                return
            self._json(200, location)

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        params = parse_qs(url.query)
        token = params.get("token")
        if url.path == "/" and token:
            if self._host_ok() and secrets.compare_digest(
                token[0].encode("utf-8"), self.server.token.encode("utf-8")
            ):
                cookie = f"{COOKIE}={self.server.token}; HttpOnly; SameSite=Strict; Path=/"
                self._send(302, headers=(("Location", "/"), ("Set-Cookie", cookie)))
            else:
                self._deny()
            return
        if not self._authorized(False):
            self._deny()
        elif url.path == "/":
            self._send(
                200,
                PAGE.encode("utf-8"),
                "text/html; charset=utf-8",
                (("Content-Security-Policy", CSP),),
            )
        elif url.path == "/api/state":
            history = params.get("history", ["all"])[0]
            try:
                page = int(params.get("page", ["1"])[0])
            except ValueError:
                page = 0
            if history not in _HISTORY_STATUSES or page < 1:
                self._json(400, {"error": "无效的历史记录筛选条件。"})
                return
            self._json(200, _state(history, page, params.get("q", [""])[0], params.get("space", [""])[0]))
        elif url.path in _PER_OPERATION:
            self._per_operation(url.path, params.get("id", [""])[0])
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if not self._authorized(True):
            self._drain()
            self._deny()
            return
        path = urlsplit(self.path).path
        if path not in ("/api/approve", "/api/reject"):
            self._drain()
            self._json(404, {"error": "not found"})
            return
        try:
            ids, reason = self._read_action(path)
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return
        try:
            if path == "/api/approve":
                with _apply_lock:
                    result = approve_and_apply(self.server.client, ids)
            else:
                result = {"rejected": queue.reject(ids, reason=reason)}
        except Exception as exc:
            self._json(500, {"error": str(exc)})
            return
        self._json(200, result)


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], client: Any, token: str) -> None:
        super().__init__(address, _Handler)
        self.client = client
        self.token = token

    @property
    def browser_url(self) -> str:
        return f"http://127.0.0.1:{self.server_port}/?token={self.token}"


def make_server(
    client: Any, token: str, host: str = "127.0.0.1", port: int = 0
) -> _Server:
    return _Server((host, port), client, token)


def _open_browser(url: str) -> None:
    # The launcher receives the approval URL via a private pipe and cannot write to MCP's stdio.
    try:
        subprocess.run(
            [sys.executable, "-I", "-c", (
                "import sys, webbrowser\n"
                "sys.exit(0 if webbrowser.open(sys.stdin.read()) else 1)"
            )],
            input=url,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            check=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError(
            "Could not open the default browser. Run `confluence-mcp-review web` in an interactive terminal."
        ) from None


class ReviewPage:
    """Own the approval listener used by one MCP process."""

    def __init__(self) -> None:
        self._server: _Server | None = None
        self._lock = threading.Lock()

    def open(self, client: Any) -> None:
        with self._lock:
            if self._server is not None:
                _open_browser(self._server.browser_url)
                return
            with ExitStack() as startup:
                try:
                    server = startup.enter_context(make_server(client, secrets.token_urlsafe(32)))
                except OSError:
                    raise RuntimeError(
                        "Could not start the approval page on 127.0.0.1. Check the MCP host's localhost permissions."
                    ) from None
                threading.Thread(target=server.serve_forever, daemon=True).start()
                startup.callback(server.shutdown)
                _open_browser(server.browser_url)
                self._server = server
                startup.pop_all()

    def close(self) -> None:
        with self._lock:
            if self._server is not None:
                with self._server:
                    self._server.shutdown()
                self._server = None


def serve(client: Any) -> None:
    """Run the approval page until Ctrl+C."""
    with make_server(client, secrets.token_urlsafe(32)) as server:
        url = server.browser_url
        print(f"Approval page: {url}\nPress Ctrl+C to stop.", flush=True)
        webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
