import copy
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal


_OPERATIONS = frozenset({"version", "doctor", "contract.verify", "inventory", "inspect"})
_ERROR_CODE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class CliError:
    code: str
    message: str

    def __post_init__(self) -> None:
        if not _ERROR_CODE.fullmatch(self.code):
            raise ValueError("error code must be lower-case kebab case")


@dataclass(frozen=True)
class CliEnvelope:
    schema_version: str
    operation: str
    status: Literal["succeeded", "failed"]
    summary: str
    result: Mapping[str, object]
    errors: tuple[CliError, ...]
    retryable: bool

    def __post_init__(self) -> None:
        if self.schema_version != "1.0":
            raise ValueError("schema_version must be 1.0")
        if self.operation not in _OPERATIONS:
            raise ValueError("operation must be a supported operation")
        if not self.summary:
            raise ValueError("summary must not be empty")
        if self.status not in {"succeeded", "failed"}:
            raise ValueError("status must be succeeded or failed")
        if not isinstance(self.result, Mapping):
            raise ValueError("result must be a mapping")

        errors = tuple(self.errors)
        if not all(isinstance(error, CliError) for error in errors):
            raise ValueError("errors must contain CliError values")
        if self.status == "succeeded" and (errors or self.retryable):
            raise ValueError("succeeded envelopes cannot have errors or be retryable")

        object.__setattr__(self, "result", copy.deepcopy(dict(self.result)))
        object.__setattr__(self, "errors", errors)

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": self.schema_version,
            "operation": self.operation,
            "status": self.status,
            "summary": self.summary,
            "result": copy.deepcopy(dict(self.result)),
            "errors": [
                {"code": error.code, "message": error.message} for error in self.errors
            ],
            "retryable": self.retryable,
        }


def succeeded(
    operation: str,
    summary: str,
    result: Mapping[str, object],
) -> CliEnvelope:
    return CliEnvelope(
        schema_version="1.0",
        operation=operation,
        status="succeeded",
        summary=summary,
        result=copy.deepcopy(dict(result)),
        errors=(),
        retryable=False,
    )


def failed(
    operation: str,
    summary: str,
    errors: Sequence[CliError],
    *,
    retryable: bool,
    result: Mapping[str, object] | None = None,
) -> CliEnvelope:
    return CliEnvelope(
        schema_version="1.0",
        operation=operation,
        status="failed",
        summary=summary,
        result=copy.deepcopy(dict({} if result is None else result)),
        errors=tuple(errors),
        retryable=retryable,
    )


def canonical_json_bytes(envelope: CliEnvelope) -> bytes:
    return (
        json.dumps(
            envelope.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ).encode("utf-8")
        + b"\n"
    )
