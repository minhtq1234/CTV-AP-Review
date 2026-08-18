"""Read-only preflight commands for the standalone local CTV toolkit."""
from __future__ import annotations

import sys

# The exact CLI may itself be located beneath the selected inventory root.
# Disable import cache writes before loading any source-backed module.
sys.dont_write_bytecode = True

import argparse
import hmac
import os
from pathlib import Path
import re

from ctv_cli_doctor import run_doctor
from ctv_cli_protocol import CliError, canonical_json_bytes, failed, succeeded
from ctv_contract_pin import ContractPinError, load_contract_pin, verify_contract
from ctv_inventory import InventoryError, inventory_source
from ctv_inventory_model import DEFAULT_LIMITS


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_INVOCATION_GUIDANCE = (
    "usage: ctv_intake_cli.py "
    "{version --json | version --target ctv-intake-v1|ctv-intake-v2 --json | "
    "doctor --json | contract verify --json | "
    "contract verify --target ctv-intake-v1|ctv-intake-v2 --json | "
    "inventory --source-root <path> --json | "
    "inspect --source-root <path> --json | "
    "proposal review --source-root <path> --json | "
    "package prepare --source-root <path> --output-root <path> --json}\n"
)
_APPROVED_ARGV = frozenset(
    {
        ("version", "--json"),
        ("version", "--target", "ctv-intake-v1", "--json"),
        ("version", "--target", "ctv-intake-v2", "--json"),
        ("doctor", "--json"),
        ("contract", "verify", "--json"),
        ("contract", "verify", "--target", "ctv-intake-v1", "--json"),
        ("contract", "verify", "--target", "ctv-intake-v2", "--json"),
    }
)
_RETRYABLE_DOCTOR_CODES = frozenset(
    {"dependency-missing", "dependency-incompatible"}
)
_DOCTOR_ERROR_MESSAGES = {
    "dependency-missing": "A required local dependency is missing.",
    "dependency-incompatible": "A required local dependency is incompatible.",
    "secure-open-unavailable": "Secure local file opening is unavailable.",
}
_INVENTORY_ERROR_CODES = frozenset(
    {
        "inventory-depth-exceeded",
        "inventory-directory-count-exceeded",
        "inventory-directory-unreadable",
        "inventory-entry-count-exceeded",
        "inventory-entry-unsafe",
        "inventory-item-count-exceeded",
        "inventory-output-too-large",
        "inventory-regular-file-count-exceeded",
        "inventory-tree-changed",
        "secure-open-unavailable",
        "source-root-missing",
        "source-root-unsafe",
    }
)
_INVENTORY_ERROR_MESSAGE = "The source folder could not be inventoried safely."
_INSPECTION_ERROR_CODES = frozenset(
    {
        "inspection-output-too-large",
        "inspection-parser-boundary-exceeded",
        "inspection-pdf-page-count-exceeded",
        "inspection-tree-changed",
        "inspection-unit-count-exceeded",
        "inspection-worksheet-count-exceeded",
        "inventory-depth-exceeded",
        "inventory-directory-count-exceeded",
        "inventory-directory-unreadable",
        "inventory-entry-count-exceeded",
        "inventory-entry-unsafe",
        "inventory-item-count-exceeded",
        "inventory-output-too-large",
        "inventory-regular-file-count-exceeded",
        "secure-open-unavailable",
        "source-root-missing",
        "source-root-unsafe",
    }
)
_INSPECTION_ERROR_MESSAGE = "The source folder could not be inspected safely."
_INSPECTION_MAX_JSON_BYTES = 16 * 1024 * 1024
_PROPOSAL_MAX_JSON_BYTES = 16 * 1024 * 1024
_PACKAGE_MAX_JSON_BYTES = 16 * 1024 * 1024
_INSPECT_INTERNAL_FAILURE = object()
_PROPOSAL_INTERNAL_FAILURE = object()
_PACKAGE_INTERNAL_FAILURE = object()
_INSPECT_INTERNAL_ERROR_BYTES = (
    b'{\n'
    b'  "errors": [\n'
    b'    {\n'
    b'      "code": "internal-error",\n'
    b'      "message": "The local toolkit could not complete the check."\n'
    b'    }\n'
    b'  ],\n'
    b'  "operation": "inspect",\n'
    b'  "result": {},\n'
    b'  "retryable": false,\n'
    b'  "schemaVersion": "1.0",\n'
    b'  "status": "failed",\n'
    b'  "summary": "The local toolkit could not complete the check"\n'
    b'}\n'
)
_PROPOSAL_INTERNAL_ERROR_BYTES = (
    b'{\n'
    b'  "errors": [\n'
    b'    {\n'
    b'      "code": "internal-error",\n'
    b'      "message": "The local toolkit could not complete the check."\n'
    b'    }\n'
    b'  ],\n'
    b'  "operation": "proposal.review",\n'
    b'  "result": {},\n'
    b'  "retryable": false,\n'
    b'  "schemaVersion": "1.0",\n'
    b'  "status": "failed",\n'
    b'  "summary": "The local toolkit could not complete the check"\n'
    b'}\n'
)
_PACKAGE_INTERNAL_ERROR_BYTES = (
    b'{\n'
    b'  "errors": [\n'
    b'    {\n'
    b'      "code": "internal-error",\n'
    b'      "message": "The local toolkit could not complete the check."\n'
    b'    }\n'
    b'  ],\n'
    b'  "operation": "package.prepare",\n'
    b'  "result": {},\n'
    b'  "retryable": false,\n'
    b'  "schemaVersion": "1.0",\n'
    b'  "status": "failed",\n'
    b'  "summary": "The local toolkit could not complete the check"\n'
    b'}\n'
)
_PROPOSAL_REVIEW_ERRORS = {
    "review-browser-open-failed": (
        "proposal-browser-unavailable",
        "The local proposal review browser could not be opened.",
    ),
    "review-timeout": (
        "proposal-session-timeout",
        "The local proposal review session timed out.",
    ),
    "review-server-failed": (
        "proposal-session-failed",
        "The local proposal review session could not be completed.",
    ),
    "review-source-changed": (
        "proposal-source-changed",
        "The source folder changed during local proposal review.",
    ),
}
_PROPOSAL_SOURCE_ERROR_CODES = _INSPECTION_ERROR_CODES | frozenset(
    {"inventory-tree-changed"}
)
_PROPOSAL_SUMMARIES = {
    "approved": "Proposal review approved",
    "draft": "Proposal review returned a draft",
    "cancelled": "Proposal review cancelled",
}
_PACKAGE_TRANSACTION_ERROR_CODES = frozenset(
    {
        "atomic-install-unavailable",
        "atomic-publish-unavailable",
        "output-root-changed",
        "output-root-closed",
        "output-root-missing",
        "output-root-unsafe",
        "package-aggregate-over-limit",
        "package-cleanup-failed",
        "package-final-name-invalid",
        "package-output-collision",
        "package-path-collision",
        "package-path-unsafe",
        "package-publish-failed",
        "package-staging-changed",
        "package-staging-closed",
        "package-staging-collision",
        "package-staging-create-failed",
        "package-temporary-collision",
        "package-write-failed",
        "secure-output-unavailable",
        "source-output-identity-invalid",
        "source-output-overlap",
    }
)
_PACKAGE_BUILD_ERROR_CODES = frozenset(
    {
        "package-source-over-limit",
        "package-artifact-over-limit",
        "package-aggregate-over-limit",
        "package-pdf-unavailable",
        "package-roster-unavailable",
        "package-evidence-unavailable",
        "package-receipt-invalid",
        "package-plan-invalid",
    }
)
_PACKAGE_WRITER_ERROR_CODES = frozenset(
    {
        "package-build-failed",
        "package-content-validation-failed",
        "package-publication-validation-failed",
        "package-receipt-write-failed",
        "package-source-finalization-failed",
        "package-staging-changed",
    }
)
_PACKAGE_PIN_ERROR_CODES = frozenset(
    {
        "contract-depth-exceeded",
        "contract-directory-count-exceeded",
        "contract-entry-count-exceeded",
        "contract-entry-unsafe",
        "contract-file-count-exceeded",
        "contract-file-too-large",
        "contract-pin-invalid",
        "contract-pin-missing",
        "contract-pin-too-large",
        "contract-target-invalid",
        "contract-tree-changed",
        "contract-tree-too-large",
        "secure-open-unavailable",
    }
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PACKAGE_ID = re.compile(r"^package-[0-9a-f]{64}$")
_PACKAGE_DIRECTORY = re.compile(r"^ctv-package-[0-9a-f]{24}$")
_OBSERVATION_ID = re.compile(r"^observation-[0-9a-f]{64}$")
_UNIT_ID = re.compile(r"^unit-[0-9]{4,}$")
_EVIDENCE_ID = re.compile(r"^evidence-[0-9]{4,}$")
_PARTICIPANT_HANDLE = re.compile(r"^participant-[0-9]{4,}$")
_SAFE_CODE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_PROPOSAL_ROLES = frozenset(
    {
        "payment-roster",
        "service-contract",
        "acceptance-record",
        "payment-tax-form",
        "identity-front",
        "identity-back",
        "shared-supporting-evidence",
        "other-supporting-evidence",
    }
)
_PROPOSAL_SCOPES = frozenset({"individual", "shared", "case"})
_PROPOSAL_EXCLUSION_REASONS = frozenset(
    {
        "duplicate",
        "irrelevant",
        "unreadable-replacement-available",
        "intentionally-omitted",
        "other",
    }
)
_INTERNAL_PREPARED_CHECK_CODES = (
    "manifest-valid",
    "package-tree-valid",
    "artifacts-valid",
    "source-binding-valid",
    "package-identity-valid",
    "sources-valid",
    "pdf-coverage-valid",
    "roster-valid",
    "exceptions-valid",
    "assignments-valid",
    "production-projection-valid",
    "validation-report-consistent",
)
_PUBLIC_PREPARED_CHECK_CODES = (
    "manifest-valid",
    "assignments-valid",
    "source-verification-complete",
    "validation-report-consistent",
)
_PREPARED_COUNT_LIMITS = {
    "sources": 10_000,
    "participants": 10_000,
    "pdfPages": 25_000,
    "evidenceArtifacts": 1_000,
    "assignments": 10_000,
    "exclusions": 20_000,
}


class CliInvocationError(RuntimeError):
    pass


class _ArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs) -> None:
        kwargs["allow_abbrev"] = False
        super().__init__(*args, **kwargs)

    def error(self, message: str) -> None:
        raise CliInvocationError from None


def _parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(prog="ctv_intake_cli.py", add_help=False)
    commands = parser.add_subparsers(dest="command", required=True)

    version = commands.add_parser("version", add_help=False)
    version.add_argument("--target", choices=("ctv-intake-v1", "ctv-intake-v2"), default="ctv-intake-v1")
    version.add_argument("--json", action="store_true", required=True)
    version.set_defaults(operation="version")

    doctor = commands.add_parser("doctor", add_help=False)
    doctor.add_argument("--json", action="store_true", required=True)
    doctor.set_defaults(operation="doctor")

    contract = commands.add_parser("contract", add_help=False)
    contract_commands = contract.add_subparsers(dest="contract_command", required=True)
    verify = contract_commands.add_parser("verify", add_help=False)
    verify.add_argument("--target", choices=("ctv-intake-v1", "ctv-intake-v2"), default="ctv-intake-v1")
    verify.add_argument("--json", action="store_true", required=True)
    verify.set_defaults(operation="contract.verify")

    inventory = commands.add_parser("inventory", add_help=False)
    inventory.add_argument("--source-root", type=Path, required=True)
    inventory.add_argument("--json", action="store_true", required=True)
    inventory.set_defaults(operation="inventory")

    inspect = commands.add_parser("inspect", add_help=False)
    inspect.add_argument("--source-root", type=Path, required=True)
    inspect.add_argument("--json", action="store_true", required=True)
    inspect.set_defaults(operation="inspect")

    proposal = commands.add_parser("proposal", add_help=False)
    proposal_commands = proposal.add_subparsers(
        dest="proposal_command", required=True
    )
    review = proposal_commands.add_parser("review", add_help=False)
    review.add_argument("--source-root", type=Path, required=True)
    review.add_argument("--json", action="store_true", required=True)
    review.set_defaults(operation="proposal.review")

    package = commands.add_parser("package", add_help=False)
    package_commands = package.add_subparsers(
        dest="package_command", required=True
    )
    prepare = package_commands.add_parser("prepare", add_help=False)
    prepare.add_argument("--source-root", type=Path, required=True)
    prepare.add_argument("--output-root", type=Path, required=True)
    prepare.add_argument("--json", action="store_true", required=True)
    prepare.set_defaults(operation="package.prepare")
    return parser


def _is_source_root_argv(invocation: list[str], operation: str) -> bool:
    if (
        len(invocation) != 4
        or invocation[0] != operation
        or invocation[1] != "--source-root"
        or invocation[3] != "--json"
    ):
        return False
    raw_source = invocation[2]
    if not raw_source or raw_source.startswith("-"):
        return False
    if raw_source == os.sep:
        return True
    components = raw_source.split(os.sep)
    if raw_source.startswith(os.sep):
        components = components[1:]
    return bool(components) and all(components)


def _is_inventory_argv(invocation: list[str]) -> bool:
    return _is_source_root_argv(invocation, "inventory")


def _is_inspect_argv(invocation: list[str]) -> bool:
    return _is_source_root_argv(invocation, "inspect")


def _is_proposal_review_argv(invocation: list[str]) -> bool:
    if (
        len(invocation) != 5
        or invocation[0] != "proposal"
        or invocation[1] != "review"
        or invocation[2] != "--source-root"
        or invocation[4] != "--json"
    ):
        return False
    raw_source = invocation[3]
    if not raw_source or raw_source.startswith("-"):
        return False
    if raw_source == os.sep:
        return True
    components = raw_source.split(os.sep)
    if raw_source.startswith(os.sep):
        components = components[1:]
    return bool(components) and all(components)


def _is_safe_path_argument(raw_path: str) -> bool:
    if not raw_path or raw_path.startswith("-"):
        return False
    if raw_path == os.sep:
        return True
    components = raw_path.split(os.sep)
    if raw_path.startswith(os.sep):
        components = components[1:]
    return bool(components) and all(components)


def _is_package_prepare_argv(invocation: list[str]) -> bool:
    return (
        len(invocation) == 7
        and invocation[0] == "package"
        and invocation[1] == "prepare"
        and invocation[2] == "--source-root"
        and _is_safe_path_argument(invocation[3])
        and invocation[4] == "--output-root"
        and _is_safe_path_argument(invocation[5])
        and invocation[6] == "--json"
    )


def _emit_stdout(content: bytes) -> None:
    stream = getattr(sys.stdout, "buffer", sys.stdout)
    written = stream.write(content)
    if type(written) is not int or written != len(content):
        raise OSError("stdout-write-failed")
    stream.flush()


def _version_envelope(target: str = "ctv-intake-v1"):
    pin = (
        load_contract_pin(REPOSITORY_ROOT)
        if target == "ctv-intake-v1"
        else load_contract_pin(REPOSITORY_ROOT, target=target)
    )
    return succeeded(
        "version",
        "Local CTV toolkit identity is ready",
        {
            "toolkitName": "ctv-intake",
            "toolkitVersion": "1.0.0",
            "cliSchemaVersion": "1.0",
            "sourceCommit": pin.source_commit,
            "contractTreeSha256": pin.contract_tree_sha256,
            "compatibilityTarget": pin.compatibility_target,
        },
    )


def _doctor_result():
    doctor = run_doctor()
    result = {
        "ready": doctor.ready,
        "pythonVersion": doctor.python_version,
        "validatorVersion": doctor.validator_version,
        "checked": list(doctor.checked),
        "localOcr": {
            "available": doctor.local_ocr.available,
            "language": doctor.local_ocr.language,
        },
    }
    if doctor.ready:
        return succeeded("doctor", "Local CTV toolkit is ready", result), 0

    errors = [
        CliError(
            issue.code,
            _DOCTOR_ERROR_MESSAGES.get(
                issue.code, "A required local capability is unavailable."
            ),
        )
        for issue in doctor.issues
    ]
    retryable = all(
        issue.code in _RETRYABLE_DOCTOR_CODES for issue in doctor.issues
    )
    return (
        failed(
            "doctor",
            "Local CTV toolkit is not ready",
            errors,
            retryable=retryable,
            result=result,
        ),
        2,
    )


def _contract_result(target: str = "ctv-intake-v1"):
    verification = (
        verify_contract(REPOSITORY_ROOT)
        if target == "ctv-intake-v1"
        else verify_contract(REPOSITORY_ROOT, target=target)
    )
    result = {
        "verified": verification.verified,
        "sourceCommit": verification.pin.source_commit,
        "contractTreeSha256": verification.pin.contract_tree_sha256,
        "actualTreeSha256": verification.actual_tree_sha256,
        "compatibilityTarget": verification.pin.compatibility_target,
    }
    if verification.verified:
        return (
            succeeded(
                "contract.verify",
                "Local CTV contract matches the approved tree",
                result,
            ),
            0,
        )
    return (
        failed(
            "contract.verify",
            "Local CTV contract does not match the approved tree",
            [
                CliError(
                    "contract-tree-mismatch",
                    "The local contract tree does not match the approved pin.",
                )
            ],
            retryable=False,
            result=result,
        ),
        2,
    )


def _inventory_result(source_root: Path):
    result = inventory_source(source_root)
    result_dict = result.to_dict()
    totals = result_dict["totals"]
    regular_files = totals["regularFiles"]
    issues = totals["issues"]
    return (
        succeeded(
            "inventory",
            f"Inventory completed: {regular_files} files, "
            f"{issues} items need attention",
            result_dict,
        ),
        0,
    )


def inspect_source(source_root: Path):
    from ctv_inspection import inspect_source as inspect_source_impl

    return inspect_source_impl(source_root)


def _inspection_result(source_root: Path):
    inspection_error_type = None
    try:
        from ctv_inspection import InspectionError

        inspection_error_type = InspectionError
        result = inspect_source(source_root)
        result_dict = result.to_dict()
        totals = result_dict["totals"]
        return (
            succeeded(
                "inspect",
                f"Inspection completed: {totals['units']} units, "
                f"{totals['needsUserReview']} need attention",
                result_dict,
            ),
            0,
        )
    except BaseException as error:
        if inspection_error_type is not None and type(error) is inspection_error_type:
            code = _safe_inspection_error_code(error)
            if code is not None:
                return (
                    _operation_failure(
                        "inspect",
                        code,
                        _INSPECTION_ERROR_MESSAGE,
                    ),
                    2,
                )
        return _INSPECT_INTERNAL_FAILURE, 1


def proposal_review_source(source_root: Path, *, review_driver=None):
    """Run one review against one retained observation and return after close."""
    from ctv_inspection import inspect_observation
    from ctv_grouping_evidence import GroupingEvidence
    from ctv_inventory import open_inventory_observation
    from ctv_proposal import ProposalState

    if review_driver is None:
        from ctv_proposal_review import run_local_review

        review_driver = run_local_review
    if not callable(review_driver):
        raise TypeError("review driver must be callable")

    with open_inventory_observation(source_root) as observation:
        grouping_evidence = GroupingEvidence()
        try:
            for item in observation.result.items:
                if item.duplicate_group_id is not None:
                    grouping_evidence.capture_source_duplicate(
                        item.evidence_id,
                        item.duplicate_group_id,
                    )
            inspection = inspect_observation(
                observation,
                _private_text_sink=grouping_evidence.capture,
            )
            state = ProposalState.from_inspection(
                observation,
                inspection,
                _grouping_evidence=grouping_evidence,
            )
            result = review_driver(state)
        finally:
            grouping_evidence.clear()
    return result


def _safe_fixed_error_code(error, error_type, allowed) -> str | None:
    if error_type is None or type(error) is not error_type:
        return None
    try:
        code = error.code
    except BaseException:
        try:
            arguments = error.args
            code = arguments[0] if len(arguments) == 1 else None
        except BaseException:
            return None
    if type(code) is str and code in allowed:
        return code
    return None


def _proposal_result(source_root: Path, *, review_driver=None):
    inspection_error_type = None
    review_error_type = None
    try:
        from ctv_inspection import InspectionError
        from ctv_proposal_review import ReviewError

        inspection_error_type = InspectionError
        review_error_type = ReviewError
        result = proposal_review_source(
            source_root,
            review_driver=review_driver,
        )
        result = _normalize_proposal_terminal(result)
        outcome = result.get("outcome")
        if type(outcome) is not str or outcome not in _PROPOSAL_SUMMARIES:
            raise ValueError("proposal outcome must be terminal")
        return (
            succeeded(
                "proposal.review",
                _PROPOSAL_SUMMARIES[outcome],
                result,
            ),
            0,
        )
    except BaseException as error:
        review_code = _safe_fixed_error_code(
            error,
            review_error_type,
            frozenset(_PROPOSAL_REVIEW_ERRORS),
        )
        if review_code is not None:
            public_code, message = _PROPOSAL_REVIEW_ERRORS[review_code]
            return (
                failed(
                    "proposal.review",
                    "Local proposal review could not be completed",
                    [CliError(public_code, message)],
                    retryable=False,
                ),
                2,
            )

        inventory_code = _safe_fixed_error_code(
            error,
            InventoryError,
            _PROPOSAL_SOURCE_ERROR_CODES,
        )
        inspection_code = _safe_fixed_error_code(
            error,
            inspection_error_type,
            _INSPECTION_ERROR_CODES,
        )
        code = inventory_code if inventory_code is not None else inspection_code
        if code is not None:
            if code in {"inventory-tree-changed", "inspection-tree-changed"}:
                code = "proposal-source-changed"
                message = "The source folder changed during local proposal review."
            else:
                message = "The source folder could not be reviewed safely."
            return (
                failed(
                    "proposal.review",
                    "Local proposal review could not be completed",
                    [CliError(code, message)],
                    retryable=False,
                ),
                2,
            )
        return _PROPOSAL_INTERNAL_FAILURE, 1


def _package_failure(code: str, message: str):
    return failed(
        "package.prepare",
        "CTV package could not be prepared",
        [CliError(code, message)],
        retryable=False,
    )


def _package_controlled_failure(code: str):
    return _package_failure(
        code,
        "The local CTV package could not be prepared safely.",
    )


def _require_exact_dict(value, keys: frozenset[str], name: str) -> dict:
    if (
        type(value) is not dict
        or any(type(key) is not str for key in value)
        or frozenset(value) != keys
    ):
        raise ValueError(f"{name} must use its exact public shape")
    return value


def _require_nonnegative_counts(
    value,
    keys: frozenset[str],
    *,
    limits: dict[str, int] | None = None,
) -> dict[str, int]:
    counts = _require_exact_dict(value, keys, "counts")
    if any(type(count) is not int or count < 0 for count in counts.values()):
        raise ValueError("counts must be non-negative integers")
    if limits is not None and any(
        counts[name] > limit for name, limit in limits.items()
    ):
        raise ValueError("counts exceed their fixed public bounds")
    return dict(counts)


def _require_safe_codes(value, name: str) -> list[str]:
    if type(value) is not list or any(
        type(code) is not str or _SAFE_CODE.fullmatch(code) is None
        for code in value
    ):
        raise ValueError(f"{name} must contain fixed codes")
    return list(value)


def _require_opaque_id(value, pattern: re.Pattern, name: str) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise ValueError(f"{name} must be a valid opaque ID")
    return value


def _normalize_proposal_terminal(result: dict) -> dict[str, object]:
    if type(result) is not dict:
        raise TypeError("proposal terminal must be a dictionary")
    if any(type(key) is not str for key in result):
        raise ValueError("proposal terminal must use exact string keys")
    outcome = result.get("outcome")
    if type(outcome) is str and outcome in {"draft", "cancelled"}:
        return _normalize_review_terminal(result)
    if type(outcome) is not str or outcome != "approved":
        raise ValueError("proposal outcome must be terminal")

    terminal = _require_exact_dict(
        result,
        frozenset(
            {
                "version",
                "outcome",
                "observationId",
                "proposalDigest",
                "readyToPrepare",
                "rosterUnitId",
                "participantHandles",
                "unitAssignments",
                "sourceDispositions",
                "counts",
                "issueCodes",
                "approval",
            }
        ),
        "approved result",
    )
    if (
        type(terminal["version"]) is not str
        or terminal["version"] != "1.0"
        or terminal["readyToPrepare"] is not True
    ):
        raise ValueError("approved result is invalid")
    observation_id = _require_opaque_id(
        terminal["observationId"], _OBSERVATION_ID, "observationId"
    )
    proposal_digest = terminal["proposalDigest"]
    if type(proposal_digest) is not str or _SHA256.fullmatch(proposal_digest) is None:
        raise ValueError("proposalDigest must be a SHA-256 digest")
    roster_unit_id = _require_opaque_id(
        terminal["rosterUnitId"], _UNIT_ID, "rosterUnitId"
    )

    handles = terminal["participantHandles"]
    if (
        type(handles) is not list
        or len(handles) > 10_000
        or any(
            type(handle) is not str
            or _PARTICIPANT_HANDLE.fullmatch(handle) is None
            for handle in handles
        )
        or len(handles) != len(set(handles))
    ):
        raise ValueError("participantHandles must contain bounded opaque IDs")

    assignments = terminal["unitAssignments"]
    if type(assignments) is not list or len(assignments) > 10_000:
        raise ValueError("unitAssignments must be a bounded list")
    normalized_assignments = []
    seen_units = set()
    for value in assignments:
        if type(value) is not dict:
            raise ValueError("unit assignment must use its exact public shape")
        decision = value.get("decision")
        if type(decision) is str and decision in {"accepted", "reassigned"}:
            item = _require_exact_dict(
                value,
                frozenset({"unitId", "decision", "role", "target"}),
                "unit assignment",
            )
            role = item["role"]
            if type(role) is not str or role not in _PROPOSAL_ROLES:
                raise ValueError("unit assignment role is invalid")
            target = _require_exact_dict(
                item["target"],
                frozenset({"scope", "participantHandles"}),
                "assignment target",
            )
            scope = target["scope"]
            target_handles = target["participantHandles"]
            if (
                type(scope) is not str
                or scope not in _PROPOSAL_SCOPES
                or type(target_handles) is not list
                or any(
                    type(handle) is not str
                    or _PARTICIPANT_HANDLE.fullmatch(handle) is None
                    or handle not in handles
                    for handle in target_handles
                )
                or len(target_handles) != len(set(target_handles))
            ):
                raise ValueError("assignment target is invalid")
            normalized = {
                "unitId": _require_opaque_id(
                    item["unitId"], _UNIT_ID, "unitId"
                ),
                "decision": decision,
                "role": role,
                "target": {
                    "scope": scope,
                    "participantHandles": list(target_handles),
                },
            }
        elif decision == "excluded":
            item = _require_exact_dict(
                value,
                frozenset({"unitId", "decision", "reason"}),
                "unit exclusion",
            )
            reason = item["reason"]
            if type(reason) is not str or reason not in _PROPOSAL_EXCLUSION_REASONS:
                raise ValueError("unit exclusion reason is invalid")
            normalized = {
                "unitId": _require_opaque_id(
                    item["unitId"], _UNIT_ID, "unitId"
                ),
                "decision": "excluded",
                "reason": reason,
            }
        else:
            raise ValueError("approved unit decision is invalid")
        if normalized["unitId"] in seen_units:
            raise ValueError("unitAssignments must use unique unit IDs")
        seen_units.add(normalized["unitId"])
        normalized_assignments.append(normalized)

    dispositions = terminal["sourceDispositions"]
    if type(dispositions) is not list or len(dispositions) > 10_000:
        raise ValueError("sourceDispositions must be a bounded list")
    normalized_dispositions = []
    seen_sources = set()
    for value in dispositions:
        item = _require_exact_dict(
            value,
            frozenset({"evidenceId", "decision", "reason"}),
            "source disposition",
        )
        reason = item["reason"]
        if (
            type(item["decision"]) is not str
            or item["decision"] != "excluded"
            or type(reason) is not str
            or reason not in _PROPOSAL_EXCLUSION_REASONS
        ):
            raise ValueError("source disposition is invalid")
        evidence_id = _require_opaque_id(
            item["evidenceId"], _EVIDENCE_ID, "evidenceId"
        )
        if evidence_id in seen_sources:
            raise ValueError("sourceDispositions must use unique evidence IDs")
        seen_sources.add(evidence_id)
        normalized_dispositions.append(
            {
                "evidenceId": evidence_id,
                "decision": "excluded",
                "reason": reason,
            }
        )

    counts = _require_nonnegative_counts(
        terminal["counts"],
        frozenset(
            {
                "sources",
                "units",
                "participants",
                "accepted",
                "reassigned",
                "excluded",
                "unresolved",
            }
        ),
    )
    if (
        counts["participants"] != len(handles)
        or counts["units"] != len(normalized_assignments)
        or counts["unresolved"] != 0
        or counts["accepted"]
        != sum(item["decision"] == "accepted" for item in normalized_assignments)
        or counts["reassigned"]
        != sum(item["decision"] == "reassigned" for item in normalized_assignments)
        or counts["excluded"]
        != sum(item["decision"] == "excluded" for item in normalized_assignments)
        + len(normalized_dispositions)
    ):
        raise ValueError("approved counts do not match terminal facts")

    approval = _require_exact_dict(
        terminal["approval"],
        frozenset({"status", "approvedProposalDigest"}),
        "approval",
    )
    approved_digest = approval["approvedProposalDigest"]
    if (
        type(approval["status"]) is not str
        or approval["status"] != "user-approved"
        or type(approved_digest) is not str
        or not hmac.compare_digest(approved_digest, proposal_digest)
    ):
        raise ValueError("approval is invalid")

    return {
        "version": "1.0",
        "outcome": "approved",
        "observationId": observation_id,
        "proposalDigest": proposal_digest,
        "readyToPrepare": True,
        "rosterUnitId": roster_unit_id,
        "participantHandles": list(handles),
        "unitAssignments": normalized_assignments,
        "sourceDispositions": normalized_dispositions,
        "counts": counts,
        "issueCodes": _require_safe_codes(terminal["issueCodes"], "issueCodes"),
        "approval": {
            "status": "user-approved",
            "approvedProposalDigest": approved_digest,
        },
    }


def _normalize_review_terminal(result: dict) -> dict[str, object]:
    if type(result) is not dict:
        raise TypeError("review terminal must be a dictionary")
    if any(type(key) is not str for key in result):
        raise ValueError("review terminal must use exact string keys")
    outcome = result.get("outcome")
    if type(outcome) is str and outcome == "cancelled":
        terminal = _require_exact_dict(
            result,
            frozenset({"version", "outcome", "readyToPrepare"}),
            "cancelled result",
        )
        if (
            type(terminal["version"]) is not str
            or terminal["version"] != "1.0"
            or terminal["readyToPrepare"] is not False
        ):
            raise ValueError("cancelled result is invalid")
        return {
            "version": "1.0",
            "outcome": "cancelled",
            "readyToPrepare": False,
        }
    if type(outcome) is str and outcome == "draft":
        terminal = _require_exact_dict(
            result,
            frozenset(
                {
                    "version",
                    "outcome",
                    "observationId",
                    "readyToPrepare",
                    "counts",
                    "issueCodes",
                }
            ),
            "draft result",
        )
        observation_id = terminal["observationId"]
        if (
            type(terminal["version"]) is not str
            or terminal["version"] != "1.0"
            or terminal["readyToPrepare"] is not False
            or type(observation_id) is not str
            or not observation_id.startswith("observation-")
            or _SHA256.fullmatch(observation_id.removeprefix("observation-")) is None
        ):
            raise ValueError("draft result is invalid")
        counts = _require_nonnegative_counts(
            terminal["counts"],
            frozenset(
                {
                    "sources",
                    "units",
                    "participants",
                    "accepted",
                    "reassigned",
                    "excluded",
                    "unresolved",
                }
            ),
        )
        return {
            "version": "1.0",
            "outcome": "draft",
            "observationId": observation_id,
            "readyToPrepare": False,
            "counts": counts,
            "issueCodes": _require_safe_codes(
                terminal["issueCodes"], "issueCodes"
            ),
        }
    raise ValueError("review outcome must be terminal")


def _normalize_prepared_result(result) -> dict[str, object]:
    to_dict = getattr(result, "to_dict", None)
    if not callable(to_dict):
        raise TypeError("package result must provide a public dictionary")
    public = _require_exact_dict(
        to_dict(),
        frozenset(
            {
                "packageId",
                "packageDirectoryName",
                "manifestSha256",
                "declaredArtifactSetSha256",
                "publishedTreeSha256",
                "contractVersion",
                "counts",
                "validation",
                "readyForCtvReview",
            }
        ),
        "prepared result",
    )
    package_id = public["packageId"]
    package_directory = public["packageDirectoryName"]
    if (
        type(package_id) is not str
        or _PACKAGE_ID.fullmatch(package_id) is None
        or type(package_directory) is not str
        or _PACKAGE_DIRECTORY.fullmatch(package_directory) is None
        or package_directory.removeprefix("ctv-package-")
        != package_id.removeprefix("package-")[:24]
    ):
        raise ValueError("prepared package identity is invalid")
    for name in (
        "manifestSha256",
        "declaredArtifactSetSha256",
        "publishedTreeSha256",
    ):
        digest = public[name]
        if type(digest) is not str or _SHA256.fullmatch(digest) is None:
            raise ValueError("prepared package digest is invalid")
    contract_version = public["contractVersion"]
    if (
        type(contract_version) is not str
        or contract_version != "2.0"
        or public["readyForCtvReview"] is not True
    ):
        raise ValueError("prepared package status is invalid")
    counts = _require_nonnegative_counts(
        public["counts"],
        frozenset(
            {
                "sources",
                "participants",
                "pdfPages",
                "evidenceArtifacts",
                "assignments",
                "exclusions",
            }
        ),
        limits=_PREPARED_COUNT_LIMITS,
    )
    validation = _require_exact_dict(
        public["validation"],
        frozenset({"outcome", "checkCodes", "warningCodes"}),
        "validation",
    )
    validation_outcome = validation["outcome"]
    if type(validation_outcome) is not str or validation_outcome != "valid":
        raise ValueError("prepared package validation is invalid")
    check_codes = validation["checkCodes"]
    warning_codes = validation["warningCodes"]
    if (
        type(check_codes) is not list
        or any(type(code) is not str for code in check_codes)
        or tuple(check_codes) != _INTERNAL_PREPARED_CHECK_CODES
        or type(warning_codes) is not list
        or warning_codes
    ):
        raise ValueError("prepared package validation facts are invalid")
    return {
        "version": "1.0",
        "outcome": "prepared",
        "packageId": package_id,
        "packageDirectoryName": package_directory,
        "manifestSha256": public["manifestSha256"],
        "declaredArtifactSetSha256": public["declaredArtifactSetSha256"],
        "publishedTreeSha256": public["publishedTreeSha256"],
        "contractVersion": "2.0",
        "counts": counts,
        "validation": {
            "outcome": "valid",
            "checkCodes": list(_PUBLIC_PREPARED_CHECK_CODES),
            "warningCodes": [],
        },
        "readyForCtvReview": True,
    }


def _package_result(
    source_root: Path,
    output_root: Path,
    *,
    review_driver=None,
    prepare_driver=None,
):
    try:
        verification = verify_contract(
            REPOSITORY_ROOT, target="ctv-intake-v2"
        )
    except BaseException as error:
        code = _safe_fixed_error_code(
            error, ContractPinError, _PACKAGE_PIN_ERROR_CODES
        )
        if code is None:
            return _PACKAGE_INTERNAL_FAILURE, 1
        return (
            _package_failure(
                code,
                "The local v2 contract could not be verified safely.",
            ),
            2,
        )
    try:
        verified = verification.verified
    except BaseException:
        return _PACKAGE_INTERNAL_FAILURE, 1
    if verified is False:
        return (
            _package_failure(
                "contract-tree-mismatch",
                "The local v2 contract does not match the approved tree.",
            ),
            2,
        )
    if verified is not True:
        return _PACKAGE_INTERNAL_FAILURE, 1

    inspection_error_type = None
    review_error_type = None
    transaction_error_type = None
    collision_error_type = None
    build_error_type = None
    writer_error_type = None
    try:
        from ctv_grouping_evidence import GroupingEvidence
        from ctv_inspection import InspectionError, inspect_observation
        from ctv_inventory import open_inventory_observation
        from ctv_package_builder import PackageBuildError
        from ctv_package_transaction import (
            OutputParent,
            PackageCollisionError,
            PackageTransactionError,
        )
        from ctv_package_writer import PackageWriterError, prepare_package
        from ctv_proposal import ProposalState
        from ctv_proposal_review import ReviewError, run_local_review

        inspection_error_type = InspectionError
        review_error_type = ReviewError
        transaction_error_type = PackageTransactionError
        collision_error_type = PackageCollisionError
        build_error_type = PackageBuildError
        writer_error_type = PackageWriterError
        if review_driver is None:
            review_driver = run_local_review
        if prepare_driver is None:
            prepare_driver = prepare_package
        if not callable(review_driver) or not callable(prepare_driver):
            raise TypeError("package drivers must be callable")

        with OutputParent.open(output_root) as output:
            with open_inventory_observation(source_root) as observation:
                output.require_disjoint(observation.directory_identity_chain())
                grouping_evidence = GroupingEvidence()
                try:
                    for item in observation.result.items:
                        if item.duplicate_group_id is not None:
                            grouping_evidence.capture_source_duplicate(
                                item.evidence_id,
                                item.duplicate_group_id,
                            )
                    inspection = inspect_observation(
                        observation,
                        _private_text_sink=grouping_evidence.capture,
                    )
                    state = ProposalState.from_inspection(
                        observation,
                        inspection,
                        _grouping_evidence=grouping_evidence,
                    )
                    terminal = _normalize_proposal_terminal(review_driver(state))
                    outcome = terminal.get("outcome")
                    if outcome in {"draft", "cancelled"}:
                        return (
                            succeeded(
                                "package.prepare",
                                (
                                    "Package preparation returned a draft"
                                    if outcome == "draft"
                                    else "Package preparation cancelled"
                                ),
                                terminal,
                            ),
                            0,
                        )
                    if outcome != "approved":
                        raise ValueError("package review outcome must be terminal")
                    try:
                        approved = state.consume_approved_package_snapshot(
                            terminal.get("proposalDigest")
                        )
                    except ValueError:
                        return (
                            _package_controlled_failure("package-approval-invalid"),
                            2,
                        )
                    prepared = prepare_driver(
                        observation, inspection, approved, output
                    )
                finally:
                    grouping_evidence.clear()
        return (
            succeeded(
                "package.prepare",
                "Prepared package is ready for CTV review",
                _normalize_prepared_result(prepared),
            ),
            0,
        )
    except BaseException as error:
        review_code = _safe_fixed_error_code(
            error,
            review_error_type,
            frozenset(_PROPOSAL_REVIEW_ERRORS),
        )
        if review_code is not None:
            public_code, message = _PROPOSAL_REVIEW_ERRORS[review_code]
            return _package_failure(public_code, message), 2

        inventory_code = _safe_fixed_error_code(
            error, InventoryError, _PROPOSAL_SOURCE_ERROR_CODES
        )
        inspection_code = _safe_fixed_error_code(
            error, inspection_error_type, _INSPECTION_ERROR_CODES
        )
        source_code = inventory_code if inventory_code is not None else inspection_code
        if source_code is not None:
            if source_code in {"inventory-tree-changed", "inspection-tree-changed"}:
                source_code = "package-source-changed"
                message = "The source folder changed during package preparation."
            else:
                message = "The source folder could not be prepared safely."
            return _package_failure(source_code, message), 2

        for error_type, allowed in (
            (collision_error_type, frozenset({"package-output-collision"})),
            (transaction_error_type, _PACKAGE_TRANSACTION_ERROR_CODES),
            (build_error_type, _PACKAGE_BUILD_ERROR_CODES),
            (writer_error_type, _PACKAGE_WRITER_ERROR_CODES),
        ):
            code = _safe_fixed_error_code(error, error_type, allowed)
            if code is not None:
                return _package_controlled_failure(code), 2
        return _PACKAGE_INTERNAL_FAILURE, 1


def _operation_failure(operation: str, code: str, message: str):
    return failed(
        operation,
        "The local toolkit could not complete the check",
        [CliError(code, message)],
        retryable=False,
    )


def _safe_inspection_error_code(error) -> str | None:
    try:
        code = error.code
    except BaseException:
        return None
    if type(code) is str and code in _INSPECTION_ERROR_CODES:
        return code
    return None


def _internal_failure(operation: str):
    return _operation_failure(
        operation,
        "internal-error",
        "The local toolkit could not complete the check.",
    )


def _emit_inspection_result(envelope, exit_code: int) -> int:
    if envelope is _INSPECT_INTERNAL_FAILURE:
        content = _INSPECT_INTERNAL_ERROR_BYTES
        exit_code = 1
    else:
        try:
            content = canonical_json_bytes(envelope)
            if type(content) is not bytes:
                raise TypeError("canonical inspect output must be bytes")
            if len(content) > _INSPECTION_MAX_JSON_BYTES:
                content = canonical_json_bytes(
                    _operation_failure(
                        "inspect",
                        "inspection-output-too-large",
                        _INSPECTION_ERROR_MESSAGE,
                    )
                )
                if (
                    type(content) is not bytes
                    or len(content) > _INSPECTION_MAX_JSON_BYTES
                ):
                    raise ValueError("canonical inspect failure exceeds output limit")
                exit_code = 2
        except BaseException:
            content = _INSPECT_INTERNAL_ERROR_BYTES
            exit_code = 1
    _emit_stdout(content)
    return exit_code


def _emit_proposal_result(envelope, exit_code: int) -> int:
    if envelope is _PROPOSAL_INTERNAL_FAILURE:
        content = _PROPOSAL_INTERNAL_ERROR_BYTES
        exit_code = 1
    else:
        try:
            content = canonical_json_bytes(envelope)
            if type(content) is not bytes:
                raise TypeError("canonical proposal output must be bytes")
            if len(content) > _PROPOSAL_MAX_JSON_BYTES:
                content = canonical_json_bytes(
                    failed(
                        "proposal.review",
                        "Local proposal review could not be completed",
                        [
                            CliError(
                                "proposal-output-too-large",
                                "The local proposal review result exceeded its safe limit.",
                            )
                        ],
                        retryable=False,
                    )
                )
                if type(content) is not bytes or len(content) > _PROPOSAL_MAX_JSON_BYTES:
                    raise ValueError("canonical proposal failure exceeds output limit")
                exit_code = 2
        except BaseException:
            content = _PROPOSAL_INTERNAL_ERROR_BYTES
            exit_code = 1
    _emit_stdout(content)
    return exit_code


def _emit_package_result(envelope, exit_code: int) -> int:
    if envelope is _PACKAGE_INTERNAL_FAILURE:
        content = _PACKAGE_INTERNAL_ERROR_BYTES
        exit_code = 1
    else:
        try:
            content = canonical_json_bytes(envelope)
            if type(content) is not bytes:
                raise TypeError("canonical package output must be bytes")
            if len(content) > _PACKAGE_MAX_JSON_BYTES:
                content = canonical_json_bytes(
                    _package_failure(
                        "package-output-too-large",
                        "The package preparation result exceeded its safe limit.",
                    )
                )
                if type(content) is not bytes or len(content) > _PACKAGE_MAX_JSON_BYTES:
                    raise ValueError("canonical package failure exceeds output limit")
                exit_code = 2
        except BaseException:
            content = _PACKAGE_INTERNAL_ERROR_BYTES
            exit_code = 1
    try:
        _emit_stdout(content)
    except BaseException:
        return 1
    return exit_code


def main(
    argv: list[str] | None = None,
    *,
    proposal_review_driver=None,
    package_review_driver=None,
    package_prepare_driver=None,
) -> int:
    invocation = list(sys.argv[1:] if argv is None else argv)
    if (
        tuple(invocation) not in _APPROVED_ARGV
        and not _is_inventory_argv(invocation)
        and not _is_inspect_argv(invocation)
        and not _is_proposal_review_argv(invocation)
        and not _is_package_prepare_argv(invocation)
    ):
        sys.stderr.write(_INVOCATION_GUIDANCE)
        sys.stderr.flush()
        return 1

    try:
        args = _parser().parse_args(invocation)
    except CliInvocationError:
        sys.stderr.write(_INVOCATION_GUIDANCE)
        sys.stderr.flush()
        return 1

    operation = args.operation
    try:
        if operation == "version":
            envelope, exit_code = (
                (_version_envelope(), 0)
                if args.target == "ctv-intake-v1"
                else (_version_envelope(args.target), 0)
            )
        elif operation == "doctor":
            envelope, exit_code = _doctor_result()
        elif operation == "contract.verify":
            envelope, exit_code = (
                _contract_result()
                if args.target == "ctv-intake-v1"
                else _contract_result(args.target)
            )
        elif operation == "inventory":
            envelope, exit_code = _inventory_result(args.source_root)
        elif operation == "inspect":
            envelope, exit_code = _inspection_result(args.source_root)
        elif operation == "proposal.review":
            envelope, exit_code = _proposal_result(
                args.source_root,
                review_driver=proposal_review_driver,
            )
        else:
            envelope, exit_code = _package_result(
                args.source_root,
                args.output_root,
                review_driver=package_review_driver,
                prepare_driver=package_prepare_driver,
            )
    except InventoryError as error:
        if isinstance(error.code, str) and error.code in _INVENTORY_ERROR_CODES:
            envelope = _operation_failure(
                operation,
                error.code,
                _INVENTORY_ERROR_MESSAGE,
            )
            exit_code = 2
        else:
            envelope = _internal_failure(operation)
            exit_code = 1
    except ContractPinError as error:
        envelope = _operation_failure(
            operation,
            error.code,
            "The local contract pin or tree could not be verified safely.",
        )
        exit_code = 1
    except RuntimeError:
        envelope = _internal_failure(operation)
        exit_code = 1
    except Exception:
        envelope = _internal_failure(operation)
        exit_code = 1

    if operation == "inspect":
        return _emit_inspection_result(envelope, exit_code)
    if operation == "proposal.review":
        return _emit_proposal_result(envelope, exit_code)
    if operation == "package.prepare":
        return _emit_package_result(envelope, exit_code)

    content = canonical_json_bytes(envelope)
    if operation == "inventory" and len(content) > DEFAULT_LIMITS.max_json_bytes:
        envelope = _operation_failure(
            "inventory",
            "inventory-output-too-large",
            _INVENTORY_ERROR_MESSAGE,
        )
        exit_code = 2
        content = canonical_json_bytes(envelope)
    _emit_stdout(content)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
