"""Ephemeral loopback-only review session for one trusted CTV proposal state."""

from __future__ import annotations

import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import re
from secrets import token_urlsafe
import threading
import time
from urllib.parse import parse_qsl, urlsplit
import webbrowser

from ctv_inspection_media import (
    MediaPreviewError,
    render_image_preview,
    render_pdf_page_preview,
)
from ctv_inspection_model import DEFAULT_INSPECTION_LIMITS
from ctv_inspection_workbook import WorkbookPreviewError, worksheet_preview
from ctv_inventory import InventoryError
from ctv_proposal import ProposalState
from ctv_proposal_review_ui import UI_CSS, UI_HTML, UI_JS


_MAX_REQUEST_BYTES = 1024 * 1024
_MAX_JSON_BYTES = 16 * 1024 * 1024
_MAX_PREVIEW_BYTES = 25 * 1024 * 1024
_IDLE_TIMEOUT_SECONDS = 5 * 60
_TOTAL_TIMEOUT_SECONDS = 2 * 60 * 60
_SESSION_COOKIE = "ctv_review_session"
_UNIT_ID = re.compile(r"^unit-[0-9]{4,}$")
_DIGEST = re.compile(r"^[a-f0-9]{64}$")
_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "img-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
    "form-action 'none'; frame-ancestors 'none'"
)
_POST_ROUTES = frozenset({
    "/api/roster",
    "/api/unit",
    "/api/source",
    "/api/summary",
    "/api/approve",
    "/api/draft",
    "/api/cancel",
    "/api/heartbeat",
})


class ReviewError(RuntimeError):
    """Fixed lifecycle failure safe for later CLI mapping."""

    def __init__(self, code: str) -> None:
        if code not in {
            "review-browser-open-failed",
            "review-timeout",
            "review-server-failed",
            "review-source-changed",
        }:
            raise ValueError("review error code must be fixed")
        super().__init__(code)


class _DuplicateJsonKey(ValueError):
    pass


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateJsonKey()
        value[key] = item
    return value


def _reject_constant(_value):
    raise ValueError("non-finite JSON is forbidden")


def _strict_json(content: bytes) -> dict:
    try:
        decoded = content.decode("utf-8", errors="strict")
        value = json.loads(
            decoded,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except Exception:
        raise ValueError("request JSON is invalid") from None
    if type(value) is not dict:
        raise ValueError("request JSON must be an object")
    return value


def _exact_empty(mapping: dict) -> None:
    if type(mapping) is not dict or mapping:
        raise ValueError("request must use an empty object")


class _Session:
    def __init__(self, state: ProposalState, clock) -> None:
        self.state = state
        self.clock = clock
        started_at = clock()
        if type(started_at) not in {int, float} or isinstance(started_at, bool):
            raise TypeError("clock must return a number")
        self.started_at = float(started_at)
        self.last_activity = float(started_at)
        self.bootstrap_token = token_urlsafe(32)
        self.session_token = token_urlsafe(32)
        self.csrf_token = token_urlsafe(32)
        self.host = ""
        self.origin = ""
        self.terminal = threading.Event()
        self.lock = threading.Lock()
        self.result = None
        self.error_code = None

    def touch(self) -> None:
        value = self.clock()
        if type(value) not in {int, float} or isinstance(value, bool):
            raise TypeError("clock must return a number")
        with self.lock:
            self.last_activity = float(value)

    def consume_bootstrap(self, supplied: str) -> bool:
        with self.lock:
            expected = self.bootstrap_token
            if expected is None or not hmac.compare_digest(supplied, expected):
                return False
            self.bootstrap_token = None
            return True

    def authenticated(self, supplied: str) -> bool:
        token = self.session_token
        return (
            not self.terminal.is_set()
            and type(token) is str
            and hmac.compare_digest(supplied, token)
        )

    def csrf_matches(self, supplied: str) -> bool:
        token = self.csrf_token
        return type(token) is str and hmac.compare_digest(supplied, token)

    def finish(self, result: dict) -> None:
        with self.lock:
            if self.terminal.is_set():
                return
            self.result = result
            self.terminal.set()

    def fail(self, code: str) -> None:
        ReviewError(code)
        with self.lock:
            if self.terminal.is_set():
                return
            self.error_code = code
            self.terminal.set()

    def snapshot_terminal(self):
        with self.lock:
            return self.result, self.error_code

    def clear(self) -> None:
        with self.lock:
            self.bootstrap_token = None
            self.session_token = None
            self.csrf_token = None
            self.state = None
            self.clock = None


class _ReviewHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "CTVLocalReview"
    sys_version = ""

    @property
    def session(self) -> _Session:
        return self.server.review_session  # type: ignore[attr-defined]

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(2)

    def log_message(self, _format, *_args) -> None:
        return None

    def log_error(self, _format, *_args) -> None:
        return None

    def send_error(self, code, _message=None, _explain=None) -> None:
        """Replace parser/default errors with fixed, fully hardened responses."""
        if code == 501:
            self._reject(405, "method-not-allowed")
        elif code in {413, 414, 431}:
            self._reject(413, "request-too-large")
        else:
            self._reject(400, "invalid-request")

    def _one_header(self, name: str) -> str | None:
        values = self.headers.get_all(name, failobj=[])
        if len(values) != 1 or type(values[0]) is not str:
            return None
        return values[0]

    def _host_ok(self) -> bool:
        host = self._one_header("Host")
        return host is not None and hmac.compare_digest(host, self.session.host)

    def _cookie_token(self) -> str | None:
        value = self._one_header("Cookie")
        prefix = f"{_SESSION_COOKIE}="
        if value is None or not value.startswith(prefix) or ";" in value:
            return None
        token = value[len(prefix):]
        return token if token else None

    def _authenticated(self) -> bool:
        token = self._cookie_token()
        return token is not None and self.session.authenticated(token)

    def _security_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", _CSP)
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")

    def _send_bytes(
        self,
        status: int,
        content_type: str,
        content: bytes,
        *,
        extra_headers=(),
    ) -> None:
        if type(content) is not bytes:
            content = b""
            status = 500
            content_type = "application/octet-stream"
        self.send_response(status)
        self._security_headers()
        self.send_header("Content-Type", content_type)
        for name, value in extra_headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        if self.command == "HEAD" or not content:
            return
        try:
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
            return

    def _send_json(self, status: int, value: dict) -> None:
        try:
            content = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except Exception:
            content = b'{"error":"response-invalid"}'
            status = 500
        if len(content) > _MAX_JSON_BYTES:
            content = b'{"error":"response-too-large"}'
            status = 500
        self._send_bytes(
            status,
            "application/json; charset=utf-8",
            content,
        )

    def _reject(self, status: int, code: str) -> None:
        self._send_json(status, {"error": code})

    def _target(self):
        try:
            target = urlsplit(self.path)
        except Exception:
            return None
        if target.scheme or target.netloc or target.fragment:
            return None
        return target

    def _client_state(self) -> dict:
        state = self.session.state
        return {
            "csrfToken": self.session.csrf_token,
            "units": [dict(unit) for unit in state.units],
            "sources": [dict(source) for source in state.sources],
            "participants": state.participants_for_local_review(),
            "summary": state.approval_summary(),
        }

    def _bootstrap(self, target) -> None:
        try:
            pairs = parse_qsl(
                target.query,
                keep_blank_values=True,
                strict_parsing=True,
                max_num_fields=1,
            )
        except Exception:
            self._reject(400, "invalid-request")
            return
        if len(pairs) != 1 or pairs[0][0] != "token" or not pairs[0][1]:
            self._reject(400, "invalid-request")
            return
        if target.query != f"token={pairs[0][1]}":
            self._reject(400, "invalid-request")
            return
        if not self.session.consume_bootstrap(pairs[0][1]):
            self._reject(403, "bootstrap-invalid")
            return
        self.session.touch()
        cookie = (
            f"{_SESSION_COOKIE}={self.session.session_token}; "
            "HttpOnly; SameSite=Strict; Path=/"
        )
        self._send_bytes(
            303,
            "text/plain; charset=utf-8",
            b"",
            extra_headers=(("Location", "/"), ("Set-Cookie", cookie)),
        )

    def _serve_static(self, path: str) -> bool:
        asset = {
            "/": ("text/html; charset=utf-8", UI_HTML),
            "/review.css": ("text/css; charset=utf-8", UI_CSS),
            "/review.js": ("text/javascript; charset=utf-8", UI_JS),
        }.get(path)
        if asset is None:
            return False
        content_type, text = asset
        self._send_bytes(200, content_type, text.encode("utf-8"))
        return True

    def _preview(self, target) -> None:
        try:
            pairs = parse_qsl(
                target.query,
                keep_blank_values=True,
                strict_parsing=True,
                max_num_fields=1,
            )
        except Exception:
            self._reject(400, "invalid-request")
            return
        if (
            len(pairs) != 1
            or pairs[0][0] != "unitId"
            or not _UNIT_ID.fullmatch(pairs[0][1])
        ):
            self._reject(400, "invalid-request")
            return
        unit_id = pairs[0][1]
        if target.query != f"unitId={unit_id}":
            self._reject(400, "invalid-request")
            return
        state = self.session.state
        inspection_unit = next(
            (unit for unit in state._inspection.units if unit.unit_id == unit_id),
            None,
        )
        if inspection_unit is None:
            self._reject(404, "preview-not-found")
            return
        max_snapshot_bytes = (
            DEFAULT_INSPECTION_LIMITS.max_pdf_source_bytes
            if inspection_unit.unit_kind == "pdf-page"
            else 25 * 1024 * 1024
        )
        try:
            snapshot = state._observation.snapshot(
                inspection_unit.evidence_id,
                max_bytes=max_snapshot_bytes,
            )
            if inspection_unit.unit_kind == "pdf-page":
                content = render_pdf_page_preview(snapshot, inspection_unit.unit_index)
                if len(content) > _MAX_PREVIEW_BYTES:
                    raise MediaPreviewError("preview-over-limit")
                self._send_bytes(200, "image/png", content)
            elif inspection_unit.unit_kind == "image":
                content = render_image_preview(snapshot)
                if len(content) > _MAX_PREVIEW_BYTES:
                    raise MediaPreviewError("preview-over-limit")
                self._send_bytes(200, "image/png", content)
            elif inspection_unit.unit_kind == "worksheet":
                preview = worksheet_preview(snapshot, inspection_unit.unit_index)
                self._send_json(200, preview)
            else:
                self._reject(404, "preview-not-found")
        except InventoryError:
            self.session.fail("review-source-changed")
            self._reject(409, "source-changed")
        except (MediaPreviewError, WorkbookPreviewError) as error:
            self._reject(422, str(error))
        except Exception:
            self._reject(422, "preview-unavailable")

    def _read_json_body(self) -> dict | None:
        if self._one_header("Transfer-Encoding") is not None:
            self._reject(400, "invalid-request")
            return None
        content_type = self._one_header("Content-Type")
        if content_type != "application/json":
            self._reject(415, "content-type-invalid")
            return None
        length_text = self._one_header("Content-Length")
        if (
            length_text is None
            or not length_text.isascii()
            or not length_text.isdigit()
        ):
            self._reject(400, "invalid-request")
            return None
        length = int(length_text)
        if length > _MAX_REQUEST_BYTES:
            self._reject(413, "request-too-large")
            return None
        try:
            content = self.rfile.read(length)
        except Exception:
            self._reject(400, "invalid-request")
            return None
        if len(content) != length:
            self._reject(400, "invalid-request")
            return None
        try:
            return _strict_json(content)
        except ValueError:
            self._reject(400, "invalid-request")
            return None

    def _do_get(self) -> None:
        if not self._host_ok():
            self._reject(400, "host-invalid")
            return
        target = self._target()
        if target is None:
            self._reject(400, "invalid-request")
            return
        if target.path == "/bootstrap":
            self._bootstrap(target)
            return
        if not self._authenticated():
            self._reject(403, "session-invalid")
            return
        if target.path == "/api/preview":
            self.session.touch()
            self._preview(target)
            return
        if target.query or "?" in self.path:
            self._reject(400, "invalid-request")
            return
        self.session.touch()
        if target.path == "/api/state":
            self._send_json(200, self._client_state())
        elif not self._serve_static(target.path):
            self._reject(404, "route-not-found")

    def do_GET(self) -> None:
        try:
            self._do_get()
        except BaseException:
            self.session.fail("review-server-failed")
            try:
                self._reject(500, "review-failed")
            except BaseException:
                return

    def _post_result(self, route: str, mapping: dict):
        state = self.session.state
        if route == "/api/heartbeat":
            _exact_empty(mapping)
            return {"status": "active"}, False
        if route == "/api/roster":
            state.select_roster(mapping)
            return self._client_state(), False
        if route == "/api/unit":
            state.set_unit_decision(mapping)
            return self._client_state(), False
        if route == "/api/source":
            state.set_source_disposition(mapping)
            return self._client_state(), False
        if route == "/api/summary":
            _exact_empty(mapping)
            return state.approval_summary(), False
        if route == "/api/draft":
            _exact_empty(mapping)
            return state.draft_result(), True
        if route == "/api/cancel":
            _exact_empty(mapping)
            return state.cancelled_result(), True
        if route == "/api/approve":
            if type(mapping) is not dict or set(mapping) != {"expectedProposalDigest"}:
                raise ValueError("approval request shape is invalid")
            digest = mapping["expectedProposalDigest"]
            if type(digest) is not str or not _DIGEST.fullmatch(digest):
                raise ValueError("approval digest is invalid")
            return state.approve(digest), True
        raise ValueError("route is invalid")

    def _do_post(self) -> None:
        if not self._host_ok():
            self._reject(400, "host-invalid")
            return
        target = self._target()
        if target is None or target.query or "?" in self.path:
            self._reject(400, "invalid-request")
            return
        if target.path not in _POST_ROUTES:
            self._reject(404, "route-not-found")
            return
        if not self._authenticated():
            self._reject(403, "session-invalid")
            return
        origin = self._one_header("Origin")
        if origin is None or not hmac.compare_digest(origin, self.session.origin):
            self._reject(403, "origin-invalid")
            return
        csrf = self._one_header("X-CSRF-Token")
        if csrf is None or not self.session.csrf_matches(csrf):
            self._reject(403, "csrf-invalid")
            return
        mapping = self._read_json_body()
        if mapping is None:
            return
        try:
            response, terminal = self._post_result(target.path, mapping)
        except (ValueError, TypeError):
            self._reject(400, "invalid-request")
            return
        self.session.touch()
        if terminal:
            self.session.finish(response)
        self._send_json(200, response)

    def do_POST(self) -> None:
        try:
            self._do_post()
        except BaseException:
            self.session.fail("review-server-failed")
            try:
                self._reject(500, "review-failed")
            except BaseException:
                return

    def _method_not_allowed(self) -> None:
        if not self._host_ok():
            self._reject(400, "host-invalid")
            return
        self._reject(405, "method-not-allowed")

    do_HEAD = _method_not_allowed
    do_PUT = _method_not_allowed
    do_PATCH = _method_not_allowed
    do_DELETE = _method_not_allowed
    do_OPTIONS = _method_not_allowed
    do_TRACE = _method_not_allowed
    do_CONNECT = _method_not_allowed


def run_local_review(
    state,
    *,
    browser_open=webbrowser.open,
    clock=time.monotonic,
) -> dict:
    """Run one memory-only loopback review and return its terminal public dict."""
    if type(state) is not ProposalState:
        raise TypeError("state must be a proposal state")
    if not callable(browser_open) or not callable(clock):
        raise TypeError("review dependencies must be callable")

    session = _Session(state, clock)
    try:
        server = HTTPServer(("127.0.0.1", 0), _ReviewHandler)
    except OSError:
        session.clear()
        raise ReviewError("review-server-failed") from None
    port = server.server_address[1]
    session.host = f"127.0.0.1:{port}"
    session.origin = f"http://{session.host}"
    server.review_session = session
    server_thread = threading.Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": 0.02},
        name="ctv-local-review",
        daemon=True,
    )
    server_thread.start()
    browser_url = f"{session.origin}/bootstrap?token={session.bootstrap_token}"

    try:
        try:
            opened = browser_open(browser_url)
        except Exception:
            opened = False
        if opened is False:
            session.fail("review-browser-open-failed")

        while not session.terminal.wait(0.02):
            if not server_thread.is_alive():
                session.fail("review-server-failed")
                break
            now = clock()
            if type(now) not in {int, float} or isinstance(now, bool):
                session.fail("review-server-failed")
                break
            with session.lock:
                total = float(now) - session.started_at
                idle = float(now) - session.last_activity
            if total >= _TOTAL_TIMEOUT_SECONDS or idle >= _IDLE_TIMEOUT_SECONDS:
                session.fail("review-timeout")
                break
        result, error_code = session.snapshot_terminal()
    finally:
        server.shutdown()
        server_thread.join(timeout=2)
        server.server_close()
        session.clear()

    if error_code is not None:
        raise ReviewError(error_code)
    if type(result) is not dict:
        raise ReviewError("review-server-failed")
    return result
