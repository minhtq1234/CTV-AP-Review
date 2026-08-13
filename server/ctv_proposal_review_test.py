import http.client
import json
from io import BytesIO
from pathlib import Path
import socket
from urllib.parse import urlsplit

import fitz
from openpyxl import Workbook
import pytest

from ctv_inspection import inspect_observation
from ctv_inventory import open_inventory_observation
from ctv_proposal import ProposalState
from ctv_proposal_review import ReviewError, run_local_review


PRIVATE_NAME = "PRIVATE-ROSTER-079123456789"
PRIVATE_PATH_PART = "private-source-079123456789"


def _workbook_bytes():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "payment roster private"
    sheet.append(("Ho ten", "Ma so nhan vien", "So tien"))
    sheet.append((PRIVATE_NAME, "CTV-001", 100))
    stream = BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


def _pdf_bytes():
    document = fitz.open()
    page = document.new_page(width=120, height=80)
    page.insert_textbox(
        fitz.Rect(5, 5, 115, 75),
        "HOP DONG DICH VU BEN A BEN B NOI DUNG CHI TIET CHU KY CAC BEN",
        fontsize=6,
    )
    snapshot = document.tobytes()
    document.close()
    return snapshot


def _state(tmp_path):
    source = tmp_path / PRIVATE_PATH_PART
    source.mkdir()
    (source / "private-roster.xlsx").write_bytes(_workbook_bytes())
    (source / "private-contract.pdf").write_bytes(_pdf_bytes())
    (source / "private-note.txt").write_text("local private supporting note")
    context = open_inventory_observation(source)
    observation = context.__enter__()
    state = ProposalState.from_inspection(observation, inspect_observation(observation))
    return source, context, state


def _request(parsed, method, target, *, cookie=None, csrf=None, body=None, headers=None):
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
    merged = dict(headers or {})
    if cookie is not None:
        merged["Cookie"] = cookie
    if csrf is not None:
        merged["X-CSRF-Token"] = csrf
    encoded = body
    if isinstance(body, (dict, list)):
        encoded = json.dumps(body, separators=(",", ":")).encode("utf-8")
        merged.setdefault("Content-Type", "application/json")
    connection.request(method, target, body=encoded, headers=merged)
    response = connection.getresponse()
    payload = response.read()
    result = response.status, response.getheaders(), payload
    connection.close()
    return result


def _header(headers, name):
    values = [value for key, value in headers if key.lower() == name.lower()]
    assert len(values) == 1
    return values[0]


def _bootstrap(url):
    parsed = urlsplit(url)
    assert parsed.hostname == "127.0.0.1"
    status, headers, body = _request(parsed, "GET", f"{parsed.path}?{parsed.query}")
    assert status == 303
    assert body == b""
    assert _header(headers, "Location") == "/"
    cookie_header = _header(headers, "Set-Cookie")
    assert "HttpOnly" in cookie_header
    assert "SameSite=Strict" in cookie_header
    assert "Path=/" in cookie_header
    return parsed, cookie_header.split(";", 1)[0], headers


def _json(payload):
    return json.loads(payload.decode("utf-8"))


def _security_headers(headers):
    assert _header(headers, "Cache-Control") == "no-store"
    assert _header(headers, "Referrer-Policy") == "no-referrer"
    assert _header(headers, "X-Content-Type-Options") == "nosniff"
    assert _header(headers, "X-Frame-Options") == "DENY"
    csp = _header(headers, "Content-Security-Policy")
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "style-src 'self'" in csp
    assert "connect-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp


def _post(parsed, route, cookie, csrf, body):
    return _request(
        parsed,
        "POST",
        route,
        cookie=cookie,
        csrf=csrf,
        body=body,
        headers={"Origin": f"http://127.0.0.1:{parsed.port}"},
    )


def test_bootstrap_is_one_time_static_routes_are_authenticated_and_shutdown_is_terminal(tmp_path):
    source, context, state = _state(tmp_path)
    captured = {}

    def drive(url):
        parsed, cookie, bootstrap_headers = _bootstrap(url)
        captured["port"] = parsed.port
        _security_headers(bootstrap_headers)
        for route, content_type in (("/", "text/html"), ("/review.css", "text/css"), ("/review.js", "text/javascript")):
            status, headers, body = _request(parsed, "GET", route, cookie=cookie)
            assert status == 200
            assert _header(headers, "Content-Type").startswith(content_type)
            assert body
            _security_headers(headers)

        status, _headers, _body = _request(parsed, "GET", urlsplit(url).path + "?" + urlsplit(url).query)
        assert status == 403
        status, _headers, _body = _request(parsed, "GET", "/api/state")
        assert status == 403

        status, headers, body = _request(parsed, "GET", "/api/state", cookie=cookie)
        assert status == 200
        _security_headers(headers)
        local_state = _json(body)
        assert set(local_state) == {"csrfToken", "units", "sources", "participants", "summary"}
        captured["csrf"] = local_state["csrfToken"]

        raw = socket.create_connection(("127.0.0.1", parsed.port), timeout=2)
        raw.sendall(b"GET /api/state HTTP/1.1\r\nHost: 127.0.0.1\r\n")
        raw.close()

        status, _headers, _body = _post(parsed, "/api/cancel", cookie, local_state["csrfToken"], {})
        assert status == 200
        return True

    try:
        result = run_local_review(state, browser_open=drive)
        assert result == {"version": "1.0", "outcome": "cancelled", "readyToPrepare": False}
        assert PRIVATE_NAME not in repr(result)
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", captured["port"]), timeout=0.2)
    finally:
        context.__exit__(None, None, None)


def test_http_boundary_rejects_malformed_authorization_routes_and_json(tmp_path):
    _source, context, state = _state(tmp_path)

    def drive(url):
        parsed, cookie, _headers = _bootstrap(url)
        status, _headers, body = _request(parsed, "GET", "/api/state", cookie=cookie)
        csrf = _json(body)["csrfToken"]

        invalid_requests = [
            ("GET", "/api/state?extra=1", {"Cookie": cookie}, None),
            ("GET", "/private/file", {"Cookie": cookie}, None),
            ("GET", "/upload", {"Cookie": cookie}, None),
            ("GET", "/proxy?url=http%3A%2F%2Fexample.invalid", {"Cookie": cookie}, None),
            ("BREW", "/api/state", {"Cookie": cookie}, None),
            ("PUT", "/api/heartbeat", {"Cookie": cookie}, b"{}"),
            ("POST", "/api/heartbeat", {"Cookie": cookie, "Origin": "http://evil.invalid", "Content-Type": "application/json", "X-CSRF-Token": csrf}, b"{}"),
            ("POST", "/api/heartbeat", {"Cookie": cookie, "Origin": f"http://127.0.0.1:{parsed.port}", "Content-Type": "text/plain", "X-CSRF-Token": csrf}, b"{}"),
            ("POST", "/api/heartbeat", {"Cookie": cookie, "Origin": f"http://127.0.0.1:{parsed.port}", "Content-Type": "application/json", "X-CSRF-Token": "wrong"}, b"{}"),
            ("POST", "/api/heartbeat?extra=1", {"Cookie": cookie, "Origin": f"http://127.0.0.1:{parsed.port}", "Content-Type": "application/json", "X-CSRF-Token": csrf}, b"{}"),
            ("POST", "/api/heartbeat?", {"Cookie": cookie, "Origin": f"http://127.0.0.1:{parsed.port}", "Content-Type": "application/json", "X-CSRF-Token": csrf}, b"{}"),
            ("POST", "/api/heartbeat", {"Cookie": cookie, "Origin": f"http://127.0.0.1:{parsed.port}", "Content-Type": "application/json", "X-CSRF-Token": csrf}, b'{"x":1,"x":2}'),
            ("POST", "/api/heartbeat", {"Cookie": cookie, "Origin": f"http://127.0.0.1:{parsed.port}", "Content-Type": "application/json", "X-CSRF-Token": csrf}, b'{"extra":true}'),
            ("POST", "/api/roster", {"Cookie": cookie, "Origin": f"http://127.0.0.1:{parsed.port}", "Content-Type": "application/json", "X-CSRF-Token": csrf}, b'{"rosterUnitId":true}'),
            ("POST", "/api/unit", {"Cookie": cookie, "Origin": f"http://127.0.0.1:{parsed.port}", "Content-Type": "application/json", "X-CSRF-Token": csrf}, b'{"unitId":"unit-9999","decision":"not-valid"}'),
        ]
        for method, route, headers, request_body in invalid_requests:
            status, response_headers, response_body = _request(
                parsed, method, route, body=request_body, headers=headers
            )
            assert status in {400, 403, 404, 405, 415}
            assert _json(response_body) == {"error": _json(response_body)["error"]}
            _security_headers(response_headers)

        connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
        connection.putrequest("POST", "/api/heartbeat", skip_host=True)
        connection.putheader("Host", f"127.0.0.1:{parsed.port}")
        connection.putheader("Cookie", cookie)
        connection.putheader("Origin", f"http://127.0.0.1:{parsed.port}")
        connection.putheader("Content-Type", "application/json")
        connection.putheader("X-CSRF-Token", csrf)
        connection.putheader("Content-Length", str(1024 * 1024 + 1))
        connection.endheaders()
        response = connection.getresponse()
        assert response.status == 413
        assert _json(response.read()) == {"error": "request-too-large"}
        connection.close()

        status, _headers, body = _post(parsed, "/api/heartbeat", cookie, csrf, {})
        assert status == 200
        assert _json(body) == {"status": "active"}
        status, _headers, body = _post(parsed, "/api/draft", cookie, csrf, {})
        assert status == 200
        assert _json(body)["outcome"] == "draft"
        return True

    try:
        result = run_local_review(state, browser_open=drive)
        assert result["outcome"] == "draft"
        assert PRIVATE_NAME not in repr(result)
    finally:
        context.__exit__(None, None, None)


def test_preview_state_mutations_summary_and_approval_use_exact_current_ids(tmp_path):
    _source, context, state = _state(tmp_path)
    approved_response = {}

    def drive(url):
        parsed, cookie, _headers = _bootstrap(url)
        status, _headers, body = _request(parsed, "GET", "/api/state", cookie=cookie)
        client_state = _json(body)
        csrf = client_state["csrfToken"]
        roster = next(unit for unit in client_state["units"] if unit["suggestedRole"] == "payment-roster")

        status, _headers, body = _post(
            parsed, "/api/roster", cookie, csrf, {"rosterUnitId": roster["unitId"]}
        )
        assert status == 200
        assert _json(body)["participants"] == [
            {"participantHandle": "participant-0001", "name": PRIVATE_NAME, "identityHint": "***-001"}
        ]

        status, headers, body = _request(
            parsed, "GET", f'/api/preview?unitId={roster["unitId"]}', cookie=cookie
        )
        assert status == 200
        assert _header(headers, "Content-Type") == "application/json; charset=utf-8"
        preview = _json(body)
        assert preview["rows"][0][:2] == ["Ho ten", "Ma so nhan vien"]
        assert len(body) <= 25 * 1024 * 1024

        for route in (
            "/api/preview?unitId=unit-9999",
            f'/api/preview?%75nitId={roster["unitId"]}',
            f'/api/preview?unitId={roster["unitId"]}&extra=1',
            f'/api/preview?unitId={roster["unitId"]}&unitId={roster["unitId"]}',
        ):
            status, _headers, _body = _request(parsed, "GET", route, cookie=cookie)
            assert status in {400, 404}

        for unit in client_state["units"]:
            status, _headers, _body = _post(
                parsed,
                "/api/unit",
                cookie,
                csrf,
                {"unitId": unit["unitId"], "decision": "excluded", "reason": "irrelevant"},
            )
            assert status == 200
        unit_evidence = {unit["evidenceId"] for unit in client_state["units"]}
        for source in client_state["sources"]:
            if source["evidenceId"] not in unit_evidence:
                status, _headers, _body = _post(
                    parsed,
                    "/api/source",
                    cookie,
                    csrf,
                    {"evidenceId": source["evidenceId"], "decision": "excluded", "reason": "irrelevant"},
                )
                assert status == 200

        status, _headers, body = _post(parsed, "/api/summary", cookie, csrf, {})
        summary = _json(body)
        assert status == 200
        assert summary["readyToPrepare"] is True
        assert PRIVATE_NAME not in repr(summary)

        status, _headers, _body = _post(
            parsed, "/api/approve", cookie, csrf, {"expectedProposalDigest": "0" * 64}
        )
        assert status == 400
        status, _headers, body = _post(
            parsed,
            "/api/approve",
            cookie,
            csrf,
            {"expectedProposalDigest": summary["proposalDigest"]},
        )
        assert status == 200
        approved_response.update(_json(body))
        return True

    try:
        result = run_local_review(state, browser_open=drive)
        assert result == approved_response
        assert result["outcome"] == "approved"
        assert PRIVATE_NAME not in repr(result)
    finally:
        context.__exit__(None, None, None)


def test_browser_failure_and_timeout_are_fixed_cleanup_errors_without_logs_or_writes(tmp_path, capsys):
    import ctv_proposal_review as review

    source, context, state = _state(tmp_path)
    before = {path.relative_to(source): path.read_bytes() for path in source.rglob("*") if path.is_file()}
    try:
        with pytest.raises(ReviewError, match="^review-browser-open-failed$"):
            run_local_review(state, browser_open=lambda _url: False)
        with pytest.raises(ReviewError, match="^review-timeout$"):
            run_local_review(
                state,
                browser_open=lambda _url: True,
                clock=iter((0.0, 301.0, 301.0)).__next__,
            )
        with pytest.raises(ReviewError, match="^review-timeout$"):
            run_local_review(
                state,
                browser_open=lambda _url: True,
                clock=iter((0.0, 7200.0, 7200.0)).__next__,
            )

        class BindFailure:
            def __init__(self, *_args, **_kwargs):
                raise OSError("PRIVATE-BIND-DETAIL")

        original_server = review.HTTPServer
        review.HTTPServer = BindFailure
        try:
            with pytest.raises(ReviewError, match="^review-server-failed$"):
                run_local_review(state, browser_open=lambda _url: True)
        finally:
            review.HTTPServer = original_server
    finally:
        context.__exit__(None, None, None)
    after = {path.relative_to(source): path.read_bytes() for path in source.rglob("*") if path.is_file()}
    assert after == before
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert PRIVATE_NAME not in captured.out + captured.err
    assert PRIVATE_PATH_PART not in captured.out + captured.err
