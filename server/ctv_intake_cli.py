"""Read-only preflight commands for the standalone local CTV toolkit."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from ctv_cli_doctor import run_doctor
from ctv_cli_protocol import CliError, canonical_json_bytes, failed, succeeded
from ctv_contract_pin import ContractPinError, load_contract_pin, verify_contract
from ctv_inventory import InventoryError, inventory_source
from ctv_inventory_model import DEFAULT_LIMITS


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_INVOCATION_GUIDANCE = (
    "usage: ctv_intake_cli.py "
    "{version --json | doctor --json | contract verify --json | "
    "inventory --source-root <path> --json}\n"
)
_APPROVED_ARGV = frozenset(
    {
        ("version", "--json"),
        ("doctor", "--json"),
        ("contract", "verify", "--json"),
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
_INVENTORY_ERROR_MESSAGE = "The source folder could not be inventoried safely."


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
    version.add_argument("--json", action="store_true", required=True)
    version.set_defaults(operation="version")

    doctor = commands.add_parser("doctor", add_help=False)
    doctor.add_argument("--json", action="store_true", required=True)
    doctor.set_defaults(operation="doctor")

    contract = commands.add_parser("contract", add_help=False)
    contract_commands = contract.add_subparsers(dest="contract_command", required=True)
    verify = contract_commands.add_parser("verify", add_help=False)
    verify.add_argument("--json", action="store_true", required=True)
    verify.set_defaults(operation="contract.verify")

    inventory = commands.add_parser("inventory", add_help=False)
    inventory.add_argument("--source-root", type=Path, required=True)
    inventory.add_argument("--json", action="store_true", required=True)
    inventory.set_defaults(operation="inventory")
    return parser


def _is_inventory_argv(invocation: list[str]) -> bool:
    if (
        len(invocation) != 4
        or invocation[0] != "inventory"
        or invocation[1] != "--source-root"
        or invocation[3] != "--json"
    ):
        return False
    raw_source = invocation[2]
    if not raw_source or raw_source.startswith("-"):
        return False
    components = raw_source.split(os.sep)
    if raw_source.startswith(os.sep):
        components = components[1:]
    return bool(components) and all(components)


def _emit_stdout(content: bytes) -> None:
    stream = getattr(sys.stdout, "buffer", sys.stdout)
    stream.write(content)
    stream.flush()


def _version_envelope():
    pin = load_contract_pin(REPOSITORY_ROOT)
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


def _contract_result():
    verification = verify_contract(REPOSITORY_ROOT)
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


def _operation_failure(operation: str, code: str, message: str):
    return failed(
        operation,
        "The local toolkit could not complete the check",
        [CliError(code, message)],
        retryable=False,
    )


def main(argv: list[str] | None = None) -> int:
    invocation = list(sys.argv[1:] if argv is None else argv)
    if (
        tuple(invocation) not in _APPROVED_ARGV
        and not _is_inventory_argv(invocation)
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
            envelope, exit_code = _version_envelope(), 0
        elif operation == "doctor":
            envelope, exit_code = _doctor_result()
        elif operation == "contract.verify":
            envelope, exit_code = _contract_result()
        else:
            envelope, exit_code = _inventory_result(args.source_root)
    except InventoryError as error:
        envelope = _operation_failure(
            operation,
            error.code,
            _INVENTORY_ERROR_MESSAGE,
        )
        exit_code = 2
    except ContractPinError as error:
        envelope = _operation_failure(
            operation,
            error.code,
            "The local contract pin or tree could not be verified safely.",
        )
        exit_code = 1
    except Exception:
        envelope = _operation_failure(
            operation,
            "internal-error",
            "The local toolkit could not complete the check.",
        )
        exit_code = 1

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
