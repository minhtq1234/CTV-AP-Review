import ast
import importlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).with_name("ctv_intake_cli.py")
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_COMMIT = "75b3b3bc7e3d4edef1b24a0cfc9bb6c039320f3a"
EXPECTED_TREE = "83d0523ffdf871d79597310d2a24424c8bb17b6fcdb208d9bf28afc70da6900d"


def _run(*args: str, cwd: Path | None = None, script: Path = SCRIPT):
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=cwd,
        capture_output=True,
        check=False,
    )


def _envelope(result, operation: str, status: str):
    assert result.stdout.endswith(b"\n")
    payload = json.loads(result.stdout)
    assert payload["schemaVersion"] == "1.0"
    assert payload["operation"] == operation
    assert payload["status"] == status
    assert result.stdout == (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        + b"\n"
    )
    return payload


def _module():
    return importlib.import_module("ctv_intake_cli")


def _captured_envelope(capsysbinary, operation: str, status: str):
    captured = capsysbinary.readouterr()
    result = SimpleNamespace(stdout=captured.out)
    payload = _envelope(result, operation, status)
    assert captured.err == b""
    return payload


def _copy_toolkit(tmp_path: Path) -> Path:
    root = tmp_path / "Bộ công cụ CTV thử nghiệm"
    server = root / "server"
    server.mkdir(parents=True)
    for source in (REPOSITORY_ROOT / "server").glob("*.py"):
        if source.name.endswith("_test.py"):
            continue
        shutil.copy2(source, server / source.name)

    intake = root / "contracts" / "ctv-intake"
    intake.mkdir(parents=True)
    shutil.copy2(
        REPOSITORY_ROOT / "contracts" / "ctv-intake" / "PIN.json",
        intake / "PIN.json",
    )
    shutil.copytree(
        REPOSITORY_ROOT / "contracts" / "ctv-intake" / "v1",
        intake / "v1",
    )
    return root


def test_version_reports_the_reviewed_identity_from_an_unrelated_cwd(tmp_path):
    result = _run("version", "--json", cwd=tmp_path)
    payload = _envelope(result, "version", "succeeded")
    assert result.returncode == 0
    assert result.stderr == b""
    assert payload["result"]["sourceCommit"] == EXPECTED_COMMIT
    assert payload["result"]["contractTreeSha256"] == EXPECTED_TREE
    assert payload["result"]["compatibilityTarget"] == "ctv-intake-v1"


def test_doctor_reports_the_real_runtime_without_reading_documents(tmp_path):
    result = _run("doctor", "--json", cwd=tmp_path)
    payload = _envelope(result, "doctor", "succeeded")
    assert result.returncode == 0
    assert result.stderr == b""
    assert payload["result"]["ready"] is True


def test_contract_verify_reports_the_approved_tree(tmp_path):
    result = _run("contract", "verify", "--json", cwd=tmp_path)
    payload = _envelope(result, "contract.verify", "succeeded")
    assert result.returncode == 0
    assert result.stderr == b""
    assert payload["result"]["verified"] is True
    assert payload["result"]["actualTreeSha256"] == EXPECTED_TREE


def test_doctor_missing_dependency_is_safe_retryable_failure(
    monkeypatch, capsysbinary
):
    cli = _module()
    result = SimpleNamespace(
        ready=False,
        python_version="3.14.3",
        validator_version="1.0.0",
        checked=("fitz",),
        issues=(SimpleNamespace(code="dependency-missing", dependency="fitz"),),
    )
    monkeypatch.setattr(cli, "run_doctor", lambda: result)

    exit_code = cli.main(["doctor", "--json"])

    payload = _captured_envelope(capsysbinary, "doctor", "failed")
    assert exit_code == 2
    assert payload["retryable"] is True
    assert [error["code"] for error in payload["errors"]] == [
        "dependency-missing"
    ]


def test_contract_mismatch_is_safe_non_retryable_failure(monkeypatch, capsysbinary):
    cli = _module()
    verification = SimpleNamespace(
        pin=SimpleNamespace(
            source_commit=EXPECTED_COMMIT,
            contract_tree_sha256=EXPECTED_TREE,
            compatibility_target="ctv-intake-v1",
        ),
        actual_tree_sha256="0" * 64,
        verified=False,
    )
    monkeypatch.setattr(cli, "verify_contract", lambda _root: verification)

    exit_code = cli.main(["contract", "verify", "--json"])

    payload = _captured_envelope(capsysbinary, "contract.verify", "failed")
    assert exit_code == 2
    assert payload["retryable"] is False
    assert [error["code"] for error in payload["errors"]] == [
        "contract-tree-mismatch"
    ]


def test_structural_contract_failure_returns_safe_code(monkeypatch, capsysbinary):
    cli = _module()
    from ctv_contract_pin import ContractPinError

    def fail(_root):
        raise ContractPinError("contract-pin-invalid")

    monkeypatch.setattr(cli, "verify_contract", fail)

    exit_code = cli.main(["contract", "verify", "--json"])

    payload = _captured_envelope(capsysbinary, "contract.verify", "failed")
    assert exit_code == 1
    assert payload["retryable"] is False
    assert payload["result"] == {}
    assert payload["errors"] == [
        {
            "code": "contract-pin-invalid",
            "message": "The local contract pin or tree could not be verified safely.",
        }
    ]


def test_unexpected_handler_exception_never_exposes_its_message(
    tmp_path, monkeypatch, capsysbinary
):
    cli = _module()
    private_path = tmp_path / "private-client-file.pdf"

    def fail(_root):
        raise RuntimeError(f"could not read {private_path}")

    monkeypatch.setattr(cli, "load_contract_pin", fail)

    exit_code = cli.main(["version", "--json"])

    payload = _captured_envelope(capsysbinary, "version", "failed")
    assert exit_code == 1
    assert payload["result"] == {}
    assert payload["errors"] == [
        {
            "code": "internal-error",
            "message": "The local toolkit could not complete the check.",
        }
    ]
    assert str(private_path).encode() not in json.dumps(payload).encode()


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["unknown", "--json"],
        ["version"],
        ["doctor"],
        ["contract", "verify"],
    ],
)
def test_invalid_invocation_emits_only_bounded_guidance(argv, capsysbinary):
    cli = _module()

    exit_code = cli.main(argv)

    captured = capsysbinary.readouterr()
    assert exit_code == 1
    assert captured.out == b""
    assert captured.err.startswith(b"usage: ctv_intake_cli.py ")
    assert len(captured.err) <= 512
    assert captured.err.count(b"version --json") == 1
    assert captured.err.count(b"doctor --json") == 1
    assert captured.err.count(b"contract verify --json") == 1


@pytest.mark.parametrize(
    "argv",
    [
        ["version", "--j"],
        ["doctor", "--j"],
        ["contract", "verify", "--j"],
        ["version", "--json", "--json"],
        ["doctor", "--json", "--json"],
        ["contract", "verify", "--json", "--json"],
    ],
)
def test_abbreviated_and_repeated_json_flags_are_rejected(argv):
    result = _run(*argv)

    assert result.returncode == 1
    assert result.stdout == b""
    assert result.stderr.startswith(b"usage: ctv_intake_cli.py ")
    assert len(result.stderr) <= 512


@pytest.mark.parametrize(
    "argv",
    [
        ["--json", "version"],
        ["--json", "doctor"],
        ["contract", "--json", "verify"],
    ],
)
def test_reordered_json_flags_are_rejected(argv):
    result = _run(*argv)

    assert result.returncode == 1
    assert result.stdout == b""
    assert result.stderr.startswith(b"usage: ctv_intake_cli.py ")
    assert len(result.stderr) <= 512


@pytest.mark.parametrize(
    "argv",
    [
        ["version", "--json"],
        ["doctor", "--json"],
        ["contract", "verify", "--json"],
    ],
)
def test_foundation_commands_reject_document_path_arguments(
    argv, tmp_path, capsysbinary
):
    cli = _module()
    private_path = tmp_path / "client source.pdf"

    exit_code = cli.main([*argv, str(private_path)])

    captured = capsysbinary.readouterr()
    assert exit_code == 1
    assert captured.out == b""
    assert 0 < len(captured.err) <= 512
    assert str(private_path).encode() not in captured.err


@pytest.mark.parametrize(
    ("argv", "operation"),
    [
        (("version", "--json"), "version"),
        (("doctor", "--json"), "doctor"),
        (("contract", "verify", "--json"), "contract.verify"),
    ],
)
def test_all_commands_launch_from_a_relocated_unicode_repository(
    argv, operation, tmp_path
):
    root = _copy_toolkit(tmp_path)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()

    result = _run(*argv, cwd=unrelated, script=root / "server" / SCRIPT.name)

    payload = _envelope(result, operation, "succeeded")
    assert result.returncode == 0
    assert result.stderr == b""
    if operation == "version":
        assert payload["result"]["sourceCommit"] == EXPECTED_COMMIT
        assert payload["result"]["contractTreeSha256"] == EXPECTED_TREE
    elif operation == "doctor":
        assert payload["result"]["ready"] is True
    else:
        assert payload["result"]["verified"] is True
        assert payload["result"]["actualTreeSha256"] == EXPECTED_TREE


def _import_roots(path: Path) -> set[str]:
    roots = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def test_foundation_modules_have_no_network_or_client_imports():
    forbidden = {
        "socket",
        "urllib",
        "http",
        "requests",
        "httpx",
        "ftplib",
        "webbrowser",
    }
    for name in ("ctv_intake_cli.py", "ctv_cli_doctor.py", "ctv_contract_pin.py"):
        assert _import_roots(SCRIPT.with_name(name)).isdisjoint(forbidden)
    assert "subprocess" not in _import_roots(SCRIPT)


def test_parser_exposes_only_the_foundation_json_surface():
    cli = _module()
    forbidden = {
        "source-root",
        "workspace-root",
        "input-file",
        "output-file",
        "install",
        "repair",
        "update",
    }
    seen = set()
    pending = [cli._parser()]
    while pending:
        parser = pending.pop()
        for action in parser._actions:
            seen.add(action.dest.replace("_", "-"))
            seen.update(option.lstrip("-") for option in action.option_strings)
            choices = getattr(action, "choices", None)
            if isinstance(choices, dict):
                pending.extend(choices.values())

    assert seen.isdisjoint(forbidden)
