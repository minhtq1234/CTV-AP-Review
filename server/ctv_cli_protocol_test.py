import json

import pytest

from ctv_cli_protocol import CliEnvelope, CliError, canonical_json_bytes, failed, succeeded


def test_success_envelope_is_exact_canonical_utf8_json():
    envelope = succeeded(
        "doctor",
        "Bộ công cụ CTV đã sẵn sàng",
        {"pythonVersion": "3.14.3"},
    )

    content = canonical_json_bytes(envelope)

    assert content.endswith(b"\n")
    assert content.count(b"\n") > 1  # canonical, indented single JSON object
    assert json.loads(content) == {
        "schemaVersion": "1.0",
        "operation": "doctor",
        "status": "succeeded",
        "summary": "Bộ công cụ CTV đã sẵn sàng",
        "result": {"pythonVersion": "3.14.3"},
        "errors": [],
        "retryable": False,
    }
    assert b"\\u1ed9" not in content  # ensure_ascii=False
    assert content == canonical_json_bytes(envelope)


def test_failure_envelope_copies_inputs_and_preserves_error_order():
    result = {"checked": ["fitz"]}
    errors = [
        CliError("dependency-missing", "A required dependency is missing."),
        CliError("secure-open-unavailable", "Secure local file opening is unavailable."),
    ]
    envelope = failed(
        "doctor",
        "Local CTV toolkit is not ready",
        errors,
        retryable=True,
        result=result,
    )
    result["checked"].append("untrusted-later-mutation")
    errors.reverse()

    payload = json.loads(canonical_json_bytes(envelope))

    assert payload["status"] == "failed"
    assert payload["retryable"] is True
    assert payload["result"] == {"checked": ["fitz"]}
    assert [error["code"] for error in payload["errors"]] == [
        "dependency-missing",
        "secure-open-unavailable",
    ]


@pytest.mark.parametrize("operation", ["", "unknown"])
def test_succeeded_rejects_empty_or_unknown_operation(operation):
    with pytest.raises(ValueError, match="operation"):
        succeeded(operation, "Ready", {})


def test_succeeded_rejects_empty_summary():
    with pytest.raises(ValueError, match="summary"):
        succeeded("doctor", "", {})


@pytest.mark.parametrize("code", ["", "UPPERCASE", "has_underscore", "two--hyphens"])
def test_error_rejects_invalid_code(code):
    with pytest.raises(ValueError, match="code"):
        CliError(code, "Invalid error code")


def test_success_envelope_rejects_errors():
    with pytest.raises(ValueError, match="succeeded"):
        CliEnvelope(
            schema_version="1.0",
            operation="doctor",
            status="succeeded",
            summary="Ready",
            result={},
            errors=(CliError("dependency-missing", "Missing dependency"),),
            retryable=False,
        )
