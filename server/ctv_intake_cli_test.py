import ast
import importlib
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from types import SimpleNamespace

import fitz
from openpyxl import Workbook
from PIL import Image
import pytest


SCRIPT = Path(__file__).with_name("ctv_intake_cli.py")
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_COMMIT = "75b3b3bc7e3d4edef1b24a0cfc9bb6c039320f3a"
EXPECTED_TREE = "83d0523ffdf871d79597310d2a24424c8bb17b6fcdb208d9bf28afc70da6900d"
INSPECTION_MODULE_FILENAMES = (
    "ctv_inspection.py",
    "ctv_inspection_classifier.py",
    "ctv_inspection_media.py",
    "ctv_inspection_model.py",
    "ctv_inspection_workbook.py",
)
PROPOSAL_MODULE_FILENAMES = (
    "ctv_grouping_evidence.py",
    "ctv_proposal.py",
    "ctv_proposal_grouping.py",
    "ctv_proposal_roster.py",
    "ctv_proposal_review.py",
    "ctv_proposal_review_ui.py",
)
PACKAGE_MODULE_FILENAMES = (
    "ctv_package_assignment.py",
    "ctv_package_builder.py",
    "ctv_package_transaction.py",
    "ctv_package_writer.py",
    "intake_package_validator_v2.py",
)
_PROPOSAL_DIGEST = "0" * 64
_INTERNAL_VALIDATION_CODES = [
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
]
_PUBLIC_VALIDATION_CODES = [
    "manifest-valid",
    "assignments-valid",
    "source-verification-complete",
    "validation-report-consistent",
]
_PREPARED_RESULT = {
    "packageId": "package-" + "0" * 64,
    "packageDirectoryName": "ctv-package-" + "0" * 24,
    "manifestSha256": "1" * 64,
    "declaredArtifactSetSha256": "2" * 64,
    "publishedTreeSha256": "3" * 64,
    "contractVersion": "2.0",
    "counts": {
        "sources": 5,
        "participants": 2,
        "pdfPages": 3,
        "evidenceArtifacts": 2,
        "assignments": 5,
        "exclusions": 1,
    },
    "validation": {
        "outcome": "valid",
        "checkCodes": list(_INTERNAL_VALIDATION_CODES),
        "warningCodes": [],
    },
    "readyForCtvReview": True,
}


def _approved_terminal():
    return {
        "version": "1.0",
        "outcome": "approved",
        "observationId": "observation-" + "0" * 64,
        "proposalDigest": _PROPOSAL_DIGEST,
        "readyToPrepare": True,
        "rosterUnitId": "unit-0001",
        "participantHandles": [],
        "unitAssignments": [],
        "sourceDispositions": [],
        "counts": {
            "sources": 0,
            "units": 0,
            "participants": 0,
            "accepted": 0,
            "reassigned": 0,
            "excluded": 0,
            "unresolved": 0,
        },
        "issueCodes": [],
        "approval": {
            "status": "user-approved",
            "approvedProposalDigest": _PROPOSAL_DIGEST,
        },
    }


class _EqualitySpoof:
    def __init__(self):
        self.comparisons = 0

    def __eq__(self, _other):
        self.comparisons += 1
        return True


class _TrackingGroupingEvidence:
    instances = []

    def __init__(self):
        self.captures = []
        self.duplicates = []
        self.cleared = False
        type(self).instances.append(self)

    def capture(self, evidence_id, unit_kind, unit_index, private_text):
        assert self.cleared is False
        self.captures.append(
            (evidence_id, unit_kind, unit_index, private_text)
        )

    def capture_source_duplicate(self, evidence_id, duplicate_group_id):
        assert self.cleared is False
        self.duplicates.append((evidence_id, duplicate_group_id))

    def clear(self):
        self.captures.clear()
        self.duplicates.clear()
        self.cleared = True


def _run(
    *args: str,
    cwd: Path | None = None,
    script: Path = SCRIPT,
    env: dict[str, str] | None = None,
):
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=cwd,
        env=env,
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
    shutil.copy2(
        REPOSITORY_ROOT / "contracts" / "ctv-intake" / "PIN.v2.json",
        intake / "PIN.v2.json",
    )
    shutil.copytree(
        REPOSITORY_ROOT / "contracts" / "ctv-intake" / "v2",
        intake / "v2",
    )
    return root


def _install_package_lifecycle(monkeypatch, cli, *, events=None):
    """Install path-free fakes around the real package lifecycle composition."""
    import ctv_inspection
    import ctv_grouping_evidence
    import ctv_inventory
    import ctv_package_transaction
    import ctv_proposal

    events = [] if events is None else events
    inspection = object()
    approved = object()

    class Observation:
        result = SimpleNamespace(
            items=(
                SimpleNamespace(
                    evidence_id="evidence-0001",
                    duplicate_group_id="duplicate-0001",
                ),
            )
        )

        def __enter__(self):
            events.append("source-enter")
            return self

        def __exit__(self, *_args):
            events.append("source-exit")
            return False

        def directory_identity_chain(self):
            events.append("source-chain")
            return ((7, 11),)

    class Output:
        def __enter__(self):
            events.append("output-enter")
            return self

        def __exit__(self, *_args):
            events.append("output-exit")
            return False

        def require_disjoint(self, chain):
            assert chain == ((7, 11),)
            events.append("disjoint")

    class State:
        def local_review_snapshot(self):
            return {
                "roster": {"status": "selected"},
                "review": {
                    "coverage": {
                        "unaccountedUnits": 0,
                        "automaticallyOrganizedUnits": 2,
                    }
                },
            }

        def consume_approved_package_snapshot(self, digest):
            assert digest == _PROPOSAL_DIGEST
            events.append("consume")
            return approved

    monkeypatch.setattr(
        cli,
        "verify_contract",
        lambda _root, *, target: (
            events.append(("pin", target))
            or SimpleNamespace(verified=True)
        ),
    )
    monkeypatch.setattr(
        ctv_package_transaction.OutputParent,
        "open",
        staticmethod(
            lambda path: events.append(("output-open", path)) or Output()
        ),
    )
    monkeypatch.setattr(
        ctv_inventory,
        "open_inventory_observation",
        lambda path: events.append(("source-open", path)) or Observation(),
    )
    class TrackingGroupingEvidence(_TrackingGroupingEvidence):
        def capture(self, evidence_id, unit_kind, unit_index, private_text):
            events.append("capture-private")
            super().capture(evidence_id, unit_kind, unit_index, private_text)

        def capture_source_duplicate(self, evidence_id, duplicate_group_id):
            events.append("capture-duplicate")
            super().capture_source_duplicate(evidence_id, duplicate_group_id)

        def clear(self):
            events.append("grouping-clear")
            super().clear()

    TrackingGroupingEvidence.instances = []
    monkeypatch.setattr(
        ctv_grouping_evidence,
        "GroupingEvidence",
        TrackingGroupingEvidence,
    )

    def inspect(observation, *, _private_text_sink):
        events.append("inspect")
        _private_text_sink(
            "evidence-0001",
            "pdf-page",
            1,
            "PRIVATE-GROUPING-MARKER",
        )
        return inspection

    def state_from_inspection(
        observation,
        inspected,
        *,
        _grouping_evidence,
    ):
        assert inspected is inspection
        assert _grouping_evidence is TrackingGroupingEvidence.instances[0]
        assert _grouping_evidence.cleared is False
        events.append("state")
        return State()

    monkeypatch.setattr(ctv_inspection, "inspect_observation", inspect)
    monkeypatch.setattr(
        ctv_proposal.ProposalState,
        "from_inspection",
        state_from_inspection,
    )
    return events, inspection, approved


def _install_generator_exit_injection(root: Path, injection: str) -> None:
    inspection_path = root / "server" / "ctv_inspection.py"
    if injection == "import":
        inspection_path.write_text(
            "raise GeneratorExit('PRIVATE_GENERATOR_DETAIL')\n",
            encoding="utf-8",
        )
        return

    if injection == "engine":
        module_source = """
class InspectionError(RuntimeError):
    pass

def inspect_source(_source_root):
    raise GeneratorExit("PRIVATE_GENERATOR_DETAIL")
"""
    elif injection == "error-accessor":
        module_source = """
class InspectionError(RuntimeError):
    @property
    def code(self):
        raise GeneratorExit("PRIVATE_GENERATOR_DETAIL")

def inspect_source(_source_root):
    raise InspectionError("PRIVATE_GENERATOR_DETAIL")
"""
    elif injection == "to-dict":
        module_source = """
class InspectionError(RuntimeError):
    pass

class HostileResult:
    def to_dict(self):
        raise GeneratorExit("PRIVATE_GENERATOR_DETAIL")

def inspect_source(_source_root):
    return HostileResult()
"""
    elif injection == "serializer":
        protocol_path = root / "server" / "ctv_cli_protocol.py"
        protocol_path.write_text(
            protocol_path.read_text(encoding="utf-8")
            + "\ndef canonical_json_bytes(_envelope):\n"
            + "    raise GeneratorExit('PRIVATE_GENERATOR_DETAIL')\n",
            encoding="utf-8",
        )
        return
    else:
        raise AssertionError(f"unknown injection: {injection}")

    inspection_path.write_text(module_source, encoding="utf-8")


def _external_tree_snapshot(root: Path):
    snapshot = {}
    for path in (root, *root.rglob("*")):
        metadata = path.lstat()
        relative_name = path.relative_to(root).as_posix()
        content = path.read_bytes() if stat.S_ISREG(metadata.st_mode) else None
        snapshot[relative_name] = (
            metadata.st_mode,
            metadata.st_mtime_ns,
            content,
        )
    return snapshot


def _assert_external_tree_unchanged(root: Path, before) -> None:
    after = _external_tree_snapshot(root)
    added = sorted(after.keys() - before.keys())
    removed = sorted(before.keys() - after.keys())
    changed = sorted(
        name for name in after.keys() & before.keys() if after[name] != before[name]
    )
    assert not (added or removed or changed), (
        f"external tree mutated: added={added}, removed={removed}, changed={changed}"
    )


def _inventory_result(*, with_issue: bool = False):
    from ctv_inventory_model import InventoryItem, InventoryResult, InventoryTotals

    items = ()
    if with_issue:
        items = (
            InventoryItem(
                evidence_id="evidence-0001",
                depth=1,
                extension="unknown",
                detected_type="unknown",
                size=None,
                sha256=None,
                hash_status="not-applicable",
                duplicate_group_id=None,
                issue_codes=("symlink",),
            ),
        )
    return InventoryResult(
        inventory_version="1.0",
        inventory_status="complete-with-issues" if with_issue else "complete",
        totals=InventoryTotals(
            regular_files=0,
            directories=0,
            issues=1 if with_issue else 0,
            total_bytes=0,
        ),
        items=items,
    )


def _inspection_result(*, with_issue: bool = False):
    return SimpleNamespace(
        to_dict=lambda: {
            "inspectionVersion": "1.0",
            "inspectionStatus": "complete-with-issues" if with_issue else "complete",
            "observationId": "observation-" + "0" * 64,
            "totals": {
                "sources": 1,
                "units": 1,
                "classified": 0,
                "unknown": 1,
                "needsUserReview": 1,
                "issues": 1 if with_issue else 0,
            },
            "sources": [],
            "units": [],
        }
    )


def _synthetic_inspection_folder(tmp_path: Path) -> Path:
    source = tmp_path / "Nguồn CTV riêng tư có dấu"
    source.mkdir()

    document = fitz.open()
    page = document.new_page()
    page.insert_text(
        (72, 72),
        "HOP DONG DICH VU\nBEN A\nBEN B\nCHU KY\nPRIVATE-ID-079123456789",
    )
    document.save(source / "hợp đồng 079123456789.pdf")
    document.close()

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Bảng kê 13-08-2026"
    worksheet.append(("HO TEN", "CCCD", "SO TIEN"))
    worksheet.append(("PRIVATE PERSON", "079123456789", 987654321))
    workbook.save(source / "bảng kê riêng 987654321.xlsx")
    workbook.close()

    with Image.new("RGB", (64, 64), "white") as image:
        image.save(source / "ảnh riêng 13-08-2026.png")
    return source


def _synthetic_exception_first_folder(
    tmp_path: Path,
    *,
    pdf_pages: int = 1,
    roster_copies: int = 1,
) -> Path:
    source = tmp_path / "synthetic exception first source"
    source.mkdir()

    document = fitz.open()
    for page_number in range(1, pdf_pages + 1):
        page = document.new_page()
        page.insert_text(
            (72, 72),
            "HOP DONG DICH VU SYNTHETIC "
            f"PAGE {page_number}\nBEN A\nBEN B\nCHU KY",
        )
    document.save(source / "case-contract.pdf")
    document.close()

    for index in range(1, roster_copies + 1):
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = f"Payment roster {index}"
        worksheet.append(
            (
                "name",
                "identity",
                "faCode",
                "taxId",
                "birthDate",
                "bankAccount",
                "serviceFee",
                "product",
                "So tien",
            )
        )
        worksheet.append(
            (
                "Synthetic Grouped Person",
                "SYNTHETIC-ID-0001",
                "FA-SYNTHETIC-GROUPED",
                "SYNTHETIC-TAX-0001",
                "1990-01-01",
                "SYNTHETIC-BANK-0001",
                "100",
                "Synthetic Product",
                "100",
            )
        )
        workbook.save(source / f"roster-{index}.xlsx")
        workbook.close()
    return source


def _private_fixture_strings(source: Path) -> tuple[str, ...]:
    return (
        str(source),
        source.name,
        "hợp đồng 079123456789.pdf",
        "bảng kê riêng 987654321.xlsx",
        "ảnh riêng 13-08-2026.png",
        "HOP DONG DICH VU",
        "PRIVATE-ID-079123456789",
        "Bảng kê 13-08-2026",
        "PRIVATE PERSON",
        "079123456789",
        "987654321",
    )


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
    assert set(payload["result"]["localOcr"]) == {"available", "language"}
    assert payload["result"]["localOcr"]["available"] == (
        payload["result"]["localOcr"]["language"] == "vie"
    )


def test_contract_verify_reports_the_approved_tree(tmp_path):
    result = _run("contract", "verify", "--json", cwd=tmp_path)
    payload = _envelope(result, "contract.verify", "succeeded")
    assert result.returncode == 0
    assert result.stderr == b""
    assert payload["result"]["verified"] is True
    assert payload["result"]["actualTreeSha256"] == EXPECTED_TREE


def test_v1_cli_target_is_byte_identical_to_legacy_no_target_commands(tmp_path):
    legacy_version = _run("version", "--json", cwd=tmp_path)
    explicit_version = _run(
        "version", "--target", "ctv-intake-v1", "--json", cwd=tmp_path
    )
    legacy_contract = _run("contract", "verify", "--json", cwd=tmp_path)
    explicit_contract = _run(
        "contract", "verify", "--target", "ctv-intake-v1", "--json", cwd=tmp_path
    )

    assert explicit_version.returncode == legacy_version.returncode == 0
    assert explicit_contract.returncode == legacy_contract.returncode == 0
    assert explicit_version.stderr == legacy_version.stderr == b""
    assert explicit_contract.stderr == legacy_contract.stderr == b""
    assert explicit_version.stdout == legacy_version.stdout
    assert explicit_contract.stdout == legacy_contract.stdout


def test_v2_cli_target_reports_and_verifies_the_v2_pin(tmp_path):
    version = _run("version", "--target", "ctv-intake-v2", "--json", cwd=tmp_path)
    contract = _run(
        "contract", "verify", "--target", "ctv-intake-v2", "--json", cwd=tmp_path
    )

    version_payload = _envelope(version, "version", "succeeded")
    contract_payload = _envelope(contract, "contract.verify", "succeeded")
    assert version.returncode == contract.returncode == 0
    assert version_payload["result"]["compatibilityTarget"] == "ctv-intake-v2"
    assert contract_payload["result"]["compatibilityTarget"] == "ctv-intake-v2"
    assert contract_payload["result"]["verified"] is True


def test_inventory_returns_private_canonical_json_from_unrelated_cwd(tmp_path):
    source = tmp_path / "Tên khách hàng tuyệt mật"
    source.mkdir()
    private_file = source / "CCCD-012345678901.PDF"
    private_file.write_bytes(b"%PDF-1.7\nprivate")
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()

    result = _run(
        "inventory", "--source-root", str(source), "--json", cwd=unrelated
    )

    payload = _envelope(result, "inventory", "succeeded")
    assert result.returncode == 0
    assert result.stderr == b""
    assert payload["result"]["inventoryStatus"] == "complete"
    assert payload["result"]["totals"]["regularFiles"] == 1
    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(source) not in serialized
    assert source.name not in serialized
    assert private_file.name not in serialized


def test_inventory_is_byte_identical_for_an_unchanged_source(tmp_path):
    source = tmp_path / "synthetic source"
    source.mkdir()
    (source / "a.pdf").write_bytes(b"%PDF-1.7\nsynthetic")
    (source / "b.zip").write_bytes(b"PK\x03\x04synthetic")

    first = _run("inventory", "--source-root", str(source), "--json")
    second = _run("inventory", "--source-root", str(source), "--json")

    _envelope(first, "inventory", "succeeded")
    _envelope(second, "inventory", "succeeded")
    assert first.returncode == second.returncode == 0
    assert first.stderr == second.stderr == b""
    assert first.stdout == second.stdout


def test_inspect_returns_private_canonical_units_from_unrelated_cwd(tmp_path):
    source = _synthetic_inspection_folder(tmp_path)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()

    first = _run("inspect", "--source-root", str(source), "--json", cwd=unrelated)
    second = _run("inspect", "--source-root", str(source), "--json", cwd=unrelated)

    payload = _envelope(first, "inspect", "succeeded")
    _envelope(second, "inspect", "succeeded")
    assert first.returncode == second.returncode == 0
    assert first.stderr == second.stderr == b""
    assert first.stdout == second.stdout
    assert payload["result"]["inspectionStatus"] in {
        "complete",
        "complete-with-issues",
    }
    assert payload["result"]["totals"]["units"] >= 3
    assert {unit["unitKind"] for unit in payload["result"]["units"]} == {
        "pdf-page",
        "worksheet",
        "image",
    }
    raw = first.stdout.decode("utf-8")
    for private in _private_fixture_strings(source):
        assert private not in raw


def test_inspect_complete_with_issues_remains_successful(monkeypatch, capsysbinary):
    cli = _module()
    monkeypatch.setattr(
        cli, "inspect_source", lambda _root: _inspection_result(with_issue=True)
    )

    exit_code = cli.main(
        ["inspect", "--source-root", "synthetic-source", "--json"]
    )

    payload = _captured_envelope(capsysbinary, "inspect", "succeeded")
    assert exit_code == 0
    assert payload["result"]["inspectionStatus"] == "complete-with-issues"
    assert payload["summary"] == "Inspection completed: 1 units, 1 need attention"


def test_inspect_dispatches_only_to_the_inspection_engine(monkeypatch, capsysbinary):
    cli = _module()
    dispatched = []

    def record(source_root):
        dispatched.append(source_root)
        return _inspection_result()

    def reject_inventory(_source_root):
        raise AssertionError("inventory_source must not be dispatched for inspect")

    monkeypatch.setattr(cli, "inspect_source", record)
    monkeypatch.setattr(cli, "inventory_source", reject_inventory)

    exit_code = cli.main(
        ["inspect", "--source-root", "synthetic-source", "--json"]
    )

    _captured_envelope(capsysbinary, "inspect", "succeeded")
    assert exit_code == 0
    assert dispatched == [Path("synthetic-source")]


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
        local_ocr=SimpleNamespace(available=False, language=None),
    )
    monkeypatch.setattr(cli, "run_doctor", lambda: result)

    exit_code = cli.main(["doctor", "--json"])

    payload = _captured_envelope(capsysbinary, "doctor", "failed")
    assert exit_code == 2
    assert payload["retryable"] is True
    assert [error["code"] for error in payload["errors"]] == [
        "dependency-missing"
    ]
    assert payload["result"]["localOcr"] == {
        "available": False,
        "language": None,
    }


def test_doctor_missing_pillow_uses_existing_dependency_failure_semantics(
    monkeypatch,
    capsysbinary,
):
    cli = _module()
    result = SimpleNamespace(
        ready=False,
        python_version="3.14.3",
        validator_version="1.0.0",
        checked=("fitz", "openpyxl", "pydantic", "Pillow"),
        issues=(
            SimpleNamespace(code="dependency-missing", dependency="Pillow"),
        ),
        local_ocr=SimpleNamespace(available=False, language=None),
    )
    monkeypatch.setattr(cli, "run_doctor", lambda: result)

    exit_code = cli.main(["doctor", "--json"])

    payload = _captured_envelope(capsysbinary, "doctor", "failed")
    assert exit_code == 2
    assert payload["retryable"] is True
    assert payload["result"]["ready"] is False
    assert payload["result"]["checked"][-1] == "Pillow"
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
    ("code", "private_fragment"),
    [
        ("source-root-missing", b"private-missing-source"),
        ("inventory-tree-changed", b"private-changing-source"),
    ],
)
def test_inventory_controlled_failure_is_safe_and_non_retryable(
    code, private_fragment, monkeypatch, capsysbinary
):
    cli = _module()
    from ctv_inventory import InventoryError

    def fail(_source_root):
        raise InventoryError(code)

    monkeypatch.setattr(cli, "inventory_source", fail)

    exit_code = cli.main(
        ["inventory", "--source-root", private_fragment.decode(), "--json"]
    )

    payload = _captured_envelope(capsysbinary, "inventory", "failed")
    assert exit_code == 2
    assert payload["retryable"] is False
    assert payload["result"] == {}
    assert payload["errors"] == [
        {
            "code": code,
            "message": "The source folder could not be inventoried safely.",
        }
    ]
    assert private_fragment not in json.dumps(payload).encode()


@pytest.mark.parametrize(
    "private_code",
    [
        "private-client-identifier",
        "/private/client/record-012345678901",
    ],
)
def test_unapproved_inventory_error_code_becomes_private_safe_internal_error(
    private_code, monkeypatch, capsysbinary
):
    cli = _module()
    from ctv_inventory import InventoryError

    def fail(_source_root):
        raise InventoryError(private_code)

    monkeypatch.setattr(cli, "inventory_source", fail)

    exit_code = cli.main(
        ["inventory", "--source-root", "synthetic-source", "--json"]
    )

    payload = _captured_envelope(capsysbinary, "inventory", "failed")
    assert exit_code == 1
    assert payload["retryable"] is False
    assert payload["result"] == {}
    assert payload["errors"] == [
        {
            "code": "internal-error",
            "message": "The local toolkit could not complete the check.",
        }
    ]
    assert private_code.encode() not in json.dumps(payload).encode()


def test_inventory_error_allowlist_matches_every_engine_emitted_code():
    cli = _module()
    inventory_path = SCRIPT.with_name("ctv_inventory.py")
    tree = ast.parse(inventory_path.read_text(encoding="utf-8"))
    engine_codes = set()
    unsupported_shapes = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "InventoryError"
        ):
            continue
        if node.keywords or len(node.args) != 1:
            unsupported_shapes.append(
                f"line {node.lineno}: expected one positional argument and no keywords"
            )
            continue
        argument = node.args[0]
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            engine_codes.add(argument.value)
            continue
        if (
            isinstance(argument, ast.IfExp)
            and isinstance(argument.body, ast.Constant)
            and isinstance(argument.body.value, str)
            and isinstance(argument.orelse, ast.Constant)
            and isinstance(argument.orelse.value, str)
        ):
            engine_codes.update((argument.body.value, argument.orelse.value))
            continue
        unsupported_shapes.append(
            f"line {node.lineno}: expected a string literal or conditional string literals"
        )

    assert not unsupported_shapes, (
        "Unsupported InventoryError call shape; allowlist extraction would drift:\n"
        + "\n".join(unsupported_shapes)
    )
    assert engine_codes == cli._INVENTORY_ERROR_CODES


def test_unexpected_inventory_error_never_exposes_private_details(
    tmp_path, monkeypatch, capsysbinary
):
    cli = _module()
    private_path = tmp_path / "private-client-file.pdf"

    def fail(_source_root):
        raise RuntimeError(f"could not read {private_path}")

    monkeypatch.setattr(cli, "inventory_source", fail)

    exit_code = cli.main(
        ["inventory", "--source-root", str(tmp_path), "--json"]
    )

    payload = _captured_envelope(capsysbinary, "inventory", "failed")
    assert exit_code == 1
    assert payload["result"] == {}
    assert payload["errors"] == [
        {
            "code": "internal-error",
            "message": "The local toolkit could not complete the check.",
        }
    ]
    assert str(private_path).encode() not in json.dumps(payload).encode()


def test_inventory_envelope_over_exact_limit_is_replaced_without_partial_stdout(
    monkeypatch, capsysbinary
):
    cli = _module()

    class OversizedResult:
        def to_dict(self):
            return {
                "inventoryVersion": "1.0",
                "inventoryStatus": "complete",
                "totals": {
                    "regularFiles": 0,
                    "directories": 0,
                    "issues": 0,
                    "totalBytes": 0,
                },
                "items": [],
                "oversized": "x" * cli.DEFAULT_LIMITS.max_json_bytes,
            }

    monkeypatch.setattr(cli, "inventory_source", lambda _root: OversizedResult())

    exit_code = cli.main(
        ["inventory", "--source-root", "synthetic-source", "--json"]
    )

    payload = _captured_envelope(capsysbinary, "inventory", "failed")
    assert exit_code == 2
    assert payload["retryable"] is False
    assert payload["errors"] == [
        {
            "code": "inventory-output-too-large",
            "message": "The source folder could not be inventoried safely.",
        }
    ]
    assert b"oversized" not in json.dumps(payload).encode()


def test_inventory_complete_with_issues_remains_successful(
    monkeypatch, capsysbinary
):
    cli = _module()
    monkeypatch.setattr(
        cli, "inventory_source", lambda _root: _inventory_result(with_issue=True)
    )

    exit_code = cli.main(
        ["inventory", "--source-root", "synthetic-source", "--json"]
    )

    payload = _captured_envelope(capsysbinary, "inventory", "succeeded")
    assert exit_code == 0
    assert payload["result"]["inventoryStatus"] == "complete-with-issues"
    assert payload["result"]["totals"]["issues"] == 1
    assert payload["summary"] == (
        "Inventory completed: 0 files, 1 items need attention"
    )


@pytest.mark.parametrize(
    "code",
    (
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
    ),
)
def test_every_controlled_inspection_error_is_safe_and_non_retryable(
    code, monkeypatch, capsysbinary
):
    cli = _module()
    from ctv_inspection import InspectionError

    def fail(_source_root):
        raise InspectionError(code)

    monkeypatch.setattr(cli, "inspect_source", fail)

    exit_code = cli.main(
        ["inspect", "--source-root", "synthetic-source", "--json"]
    )

    payload = _captured_envelope(capsysbinary, "inspect", "failed")
    assert exit_code == 2
    assert payload["retryable"] is False
    assert payload["result"] == {}
    assert payload["errors"] == [
        {
            "code": code,
            "message": "The source folder could not be inspected safely.",
        }
    ]


@pytest.mark.parametrize(
    "private_code",
    (
        "private-client-identifier",
        "/private/client/record-079123456789",
        79123456789,
    ),
)
def test_unapproved_or_malformed_inspection_error_is_fixed_internal_error(
    private_code, monkeypatch, capsysbinary
):
    cli = _module()
    from ctv_inspection import InspectionError

    error = InspectionError.__new__(InspectionError)
    RuntimeError.__init__(error, "private-inspection-diagnostic")
    error.code = private_code

    def fail(_source_root):
        raise error

    monkeypatch.setattr(cli, "inspect_source", fail)

    exit_code = cli.main(
        ["inspect", "--source-root", "synthetic-source", "--json"]
    )

    payload = _captured_envelope(capsysbinary, "inspect", "failed")
    assert exit_code == 1
    assert payload["errors"] == [
        {
            "code": "internal-error",
            "message": "The local toolkit could not complete the check.",
        }
    ]
    rendered = json.dumps(payload).encode()
    assert b"private-inspection-diagnostic" not in rendered
    assert str(private_code).encode() not in rendered


def test_hostile_inspection_error_code_accessor_is_fixed_internal_error(
    monkeypatch, capsysbinary
):
    cli = _module()
    from ctv_inspection import InspectionError

    class HostileInspectionError(InspectionError):
        @property
        def code(self):
            raise RuntimeError("private-code-accessor-diagnostic")

    error = HostileInspectionError.__new__(HostileInspectionError)
    RuntimeError.__init__(error, "private-error-message")

    def fail(_source_root):
        raise error

    monkeypatch.setattr(cli, "inspect_source", fail)

    exit_code = cli.main(
        ["inspect", "--source-root", "synthetic-source", "--json"]
    )

    payload = _captured_envelope(capsysbinary, "inspect", "failed")
    assert exit_code == 1
    assert payload["errors"] == [
        {
            "code": "internal-error",
            "message": "The local toolkit could not complete the check.",
        }
    ]
    assert b"private" not in json.dumps(payload).encode()


def test_inspection_runtime_failure_is_separate_from_controlled_errors(
    monkeypatch, capsysbinary
):
    cli = _module()

    def fail(_source_root):
        raise RuntimeError("private-task-7-internal-detail")

    monkeypatch.setattr(cli, "inspect_source", fail)

    exit_code = cli.main(
        ["inspect", "--source-root", "synthetic-source", "--json"]
    )

    payload = _captured_envelope(capsysbinary, "inspect", "failed")
    assert exit_code == 1
    assert payload["errors"] == [
        {
            "code": "internal-error",
            "message": "The local toolkit could not complete the check.",
        }
    ]
    assert b"private-task-7-internal-detail" not in json.dumps(payload).encode()


@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit])
def test_inspection_process_control_failure_is_fixed_internal_error(
    error_type, monkeypatch, capsysbinary
):
    cli = _module()

    def fail(_source_root):
        raise error_type("private-process-control-detail")

    monkeypatch.setattr(cli, "inspect_source", fail)

    exit_code = cli.main(
        ["inspect", "--source-root", "synthetic-source", "--json"]
    )

    payload = _captured_envelope(capsysbinary, "inspect", "failed")
    assert exit_code == 1
    assert payload["errors"] == [
        {
            "code": "internal-error",
            "message": "The local toolkit could not complete the check.",
        }
    ]
    assert b"private-process-control-detail" not in json.dumps(payload).encode()


def test_inspection_generator_exit_is_fixed_internal_error(
    monkeypatch, capsysbinary
):
    cli = _module()

    def fail(_source_root):
        raise GeneratorExit("PRIVATE_GENERATOR_DETAIL")

    monkeypatch.setattr(cli, "inspect_source", fail)

    exit_code = cli.main(
        ["inspect", "--source-root", "synthetic-source", "--json"]
    )

    payload = _captured_envelope(capsysbinary, "inspect", "failed")
    assert exit_code == 1
    assert [entry["code"] for entry in payload["errors"]] == ["internal-error"]
    assert b"PRIVATE_GENERATOR_DETAIL" not in json.dumps(payload).encode()


def test_inspection_error_subclass_is_never_trusted_as_controlled(
    monkeypatch, capsysbinary
):
    cli = _module()
    from ctv_inspection import InspectionError

    class DerivedInspectionError(InspectionError):
        pass

    def fail(_source_root):
        raise DerivedInspectionError("source-root-missing")

    monkeypatch.setattr(cli, "inspect_source", fail)

    exit_code = cli.main(
        ["inspect", "--source-root", "synthetic-source", "--json"]
    )

    payload = _captured_envelope(capsysbinary, "inspect", "failed")
    assert exit_code == 1
    assert [error["code"] for error in payload["errors"]] == ["internal-error"]


@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit])
def test_exact_inspection_error_with_hostile_code_accessor_is_fixed_internal(
    error_type, monkeypatch, capsysbinary
):
    cli = _module()
    from ctv_inspection import InspectionError

    error = InspectionError("source-root-missing")

    def hostile_code(_self):
        raise error_type("private-code-accessor-control-detail")

    monkeypatch.setattr(
        InspectionError,
        "code",
        property(hostile_code),
        raising=False,
    )

    def fail(_source_root):
        raise error

    monkeypatch.setattr(cli, "inspect_source", fail)

    exit_code = cli.main(
        ["inspect", "--source-root", "synthetic-source", "--json"]
    )

    payload = _captured_envelope(capsysbinary, "inspect", "failed")
    assert exit_code == 1
    assert [entry["code"] for entry in payload["errors"]] == ["internal-error"]
    assert b"private-code-accessor-control-detail" not in json.dumps(payload).encode()


@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit])
def test_inspection_to_dict_process_control_failure_uses_fixed_fallback(
    error_type, monkeypatch, capsysbinary
):
    cli = _module()

    class HostileResult:
        def to_dict(self):
            raise error_type("private-result-serialization-detail")

    monkeypatch.setattr(cli, "inspect_source", lambda _root: HostileResult())

    exit_code = cli.main(
        ["inspect", "--source-root", "synthetic-source", "--json"]
    )

    payload = _captured_envelope(capsysbinary, "inspect", "failed")
    assert exit_code == 1
    assert [entry["code"] for entry in payload["errors"]] == ["internal-error"]
    assert b"private-result-serialization-detail" not in json.dumps(payload).encode()


def test_unserializable_inspection_result_uses_preconstructed_internal_bytes(
    monkeypatch,
):
    cli = _module()

    class UnserializableResult:
        def to_dict(self):
            result = _inspection_result().to_dict()
            result["privateUnserializable"] = object()
            return result

    writes = []
    monkeypatch.setattr(cli, "inspect_source", lambda _root: UnserializableResult())
    monkeypatch.setattr(cli, "_emit_stdout", writes.append)

    exit_code = cli.main(
        ["inspect", "--source-root", "synthetic-source", "--json"]
    )

    assert exit_code == 1
    assert writes == [cli._INSPECT_INTERNAL_ERROR_BYTES]
    payload = _envelope(SimpleNamespace(stdout=writes[0]), "inspect", "failed")
    assert [entry["code"] for entry in payload["errors"]] == ["internal-error"]
    assert b"privateUnserializable" not in writes[0]


@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit])
def test_inspect_canonical_serializer_failure_does_not_recurse(
    error_type, monkeypatch
):
    cli = _module()
    calls = []
    writes = []

    def fail_serialization(_envelope):
        calls.append("called")
        raise error_type("private-canonical-serialization-detail")

    monkeypatch.setattr(cli, "inspect_source", lambda _root: _inspection_result())
    monkeypatch.setattr(cli, "canonical_json_bytes", fail_serialization)
    monkeypatch.setattr(cli, "_emit_stdout", writes.append)

    exit_code = cli.main(
        ["inspect", "--source-root", "synthetic-source", "--json"]
    )

    assert exit_code == 1
    assert calls == ["called"]
    assert writes == [cli._INSPECT_INTERNAL_ERROR_BYTES]
    assert b"private-canonical-serialization-detail" not in writes[0]


@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit])
def test_inspect_output_cap_failure_uses_fixed_internal_bytes(
    error_type, monkeypatch
):
    cli = _module()

    class HostileCanonicalContent:
        def __len__(self):
            raise error_type("private-output-cap-detail")

    writes = []
    monkeypatch.setattr(cli, "inspect_source", lambda _root: _inspection_result())
    monkeypatch.setattr(
        cli, "canonical_json_bytes", lambda _envelope: HostileCanonicalContent()
    )
    monkeypatch.setattr(cli, "_emit_stdout", writes.append)

    exit_code = cli.main(
        ["inspect", "--source-root", "synthetic-source", "--json"]
    )

    assert exit_code == 1
    assert writes == [cli._INSPECT_INTERNAL_ERROR_BYTES]


def test_inspect_oversized_replacement_cannot_bypass_the_output_cap(monkeypatch):
    cli = _module()
    calls = []
    writes = []

    def always_oversized(_envelope):
        calls.append("called")
        return b"x" * (cli._INSPECTION_MAX_JSON_BYTES + 1)

    monkeypatch.setattr(cli, "inspect_source", lambda _root: _inspection_result())
    monkeypatch.setattr(cli, "canonical_json_bytes", always_oversized)
    monkeypatch.setattr(cli, "_emit_stdout", writes.append)

    exit_code = cli.main(
        ["inspect", "--source-root", "synthetic-source", "--json"]
    )

    assert exit_code == 1
    assert calls == ["called", "called"]
    assert writes == [cli._INSPECT_INTERNAL_ERROR_BYTES]
    assert len(writes[0]) <= cli._INSPECTION_MAX_JSON_BYTES


def test_inspect_full_envelope_over_limit_is_replaced_before_one_stdout_write(
    monkeypatch,
):
    cli = _module()

    class OversizedResult:
        def to_dict(self):
            result = _inspection_result().to_dict()
            result["oversized"] = "x" * cli._INSPECTION_MAX_JSON_BYTES
            return result

    writes = []
    monkeypatch.setattr(cli, "inspect_source", lambda _root: OversizedResult())
    monkeypatch.setattr(cli, "_emit_stdout", writes.append)

    exit_code = cli.main(
        ["inspect", "--source-root", "synthetic-source", "--json"]
    )

    assert exit_code == 2
    assert len(writes) == 1
    payload = _envelope(
        SimpleNamespace(stdout=writes[0]), "inspect", "failed"
    )
    assert payload["errors"] == [
        {
            "code": "inspection-output-too-large",
            "message": "The source folder could not be inspected safely.",
        }
    ]
    assert b"oversized" not in writes[0]


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["unknown", "--json"],
        ["version"],
        ["doctor"],
        ["contract", "verify"],
        ["inspect"],
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
    assert captured.err.count(b"inventory --source-root <path> --json") == 1
    assert captured.err.count(b"inspect --source-root <path> --json") == 1
    assert captured.err.count(
        b"proposal review --source-root <path> --json"
    ) == 1


@pytest.mark.parametrize(
    "argv",
    [
        ["inventory", "--source-root", "", "--json"],
        ["inventory", "--source-root", "--json"],
        ["inventory", "--source-r", "/private/tmp/Tên tuyệt mật", "--json"],
        ["inventory", "--source-root", "/private/tmp/Tên tuyệt mật", "--j"],
        [
            "inventory",
            "--source-root",
            "/private/tmp/Tên tuyệt mật",
            "--source-root",
            "/private/tmp/Khác",
            "--json",
        ],
        [
            "inventory",
            "--source-root",
            "/private/tmp/Tên tuyệt mật",
            "--json",
            "--json",
        ],
        [
            "inventory",
            "--json",
            "--source-root",
            "/private/tmp/Tên tuyệt mật",
        ],
        [
            "inventory",
            "--source-root",
            "/private/tmp/Tên tuyệt mật",
            "--json",
            "extra",
        ],
        ["inventory", "--source-root", "--private-source", "--json"],
        [
            "inventory",
            "--source-root",
            "/private/tmp/Tên tuyệt mật/",
            "--json",
        ],
        [
            "inventory",
            "--source-root",
            "/private/tmp//Tên tuyệt mật",
            "--json",
        ],
        ["inventory", "--source-root", "////", "--json"],
    ],
)
def test_invalid_inventory_surface_emits_only_fixed_private_guidance(argv):
    result = _run(*argv)

    assert result.returncode == 1
    assert result.stdout == b""
    assert result.stderr.startswith(b"usage: ctv_intake_cli.py ")
    assert 0 < len(result.stderr) <= 512
    assert "Tên tuyệt mật".encode() not in result.stderr
    assert b"--private-source" not in result.stderr


@pytest.mark.parametrize(
    "argv",
    [
        ["inspect", "--source-root", "", "--json"],
        ["inspect", "--source-root", "--json"],
        ["inspect", "--source-r", "/private/tmp/Tên tuyệt mật", "--json"],
        ["inspect", "--source-root", "/private/tmp/Tên tuyệt mật", "--j"],
        [
            "inspect",
            "--source-root",
            "/private/tmp/Tên tuyệt mật",
            "--source-root",
            "/private/tmp/Khác",
            "--json",
        ],
        [
            "inspect",
            "--source-root",
            "/private/tmp/Tên tuyệt mật",
            "--json",
            "--json",
        ],
        ["inspect", "--json", "--source-root", "/private/tmp/Tên tuyệt mật"],
        [
            "inspect",
            "--source-root",
            "/private/tmp/Tên tuyệt mật",
            "--json",
            "extra",
        ],
        ["inspect", "--source-root", "--private-source", "--json"],
        ["inspect", "--source-root", "/private/tmp/Tên tuyệt mật/", "--json"],
        ["inspect", "--source-root", "/private/tmp//Tên tuyệt mật", "--json"],
        ["inspect", "--source-root", "////", "--json"],
    ],
)
def test_invalid_inspect_surface_emits_only_fixed_private_guidance(argv):
    result = _run(*argv)

    assert result.returncode == 1
    assert result.stdout == b""
    assert result.stderr.startswith(b"usage: ctv_intake_cli.py ")
    assert 0 < len(result.stderr) <= 512
    assert "Tên tuyệt mật".encode() not in result.stderr
    assert b"--private-source" not in result.stderr


@pytest.mark.parametrize(
    "argv",
    [
        ["proposal"],
        ["proposal", "review"],
        ["proposal", "review", "--source-root", "", "--json"],
        ["proposal", "review", "--source-root", "--json"],
        ["proposal", "rev", "--source-root", "/private/Ten", "--json"],
        ["proposal", "review", "--source-r", "/private/Ten", "--json"],
        ["proposal", "review", "--source-root", "/private/Ten", "--j"],
        [
            "proposal",
            "review",
            "--source-root",
            "/private/Ten",
            "--source-root",
            "/private/Khac",
            "--json",
        ],
        [
            "proposal",
            "review",
            "--source-root",
            "/private/Ten",
            "--json",
            "--json",
        ],
        ["proposal", "review", "--json", "--source-root", "/private/Ten"],
        [
            "proposal",
            "review",
            "--source-root",
            "/private/Ten",
            "--json",
            "extra",
        ],
        ["proposal", "review", "--source-root", "--private-source", "--json"],
        ["proposal", "review", "--source-root", "/private/Ten/", "--json"],
        ["proposal", "review", "--source-root", "/private//Ten", "--json"],
        ["proposal", "review", "--source-root", "////", "--json"],
    ],
)
def test_invalid_proposal_review_surface_emits_only_fixed_private_guidance(argv):
    result = _run(*argv)

    assert result.returncode == 1
    assert result.stdout == b""
    assert result.stderr.startswith(b"usage: ctv_intake_cli.py ")
    assert 0 < len(result.stderr) <= 512
    assert b"/private/Ten" not in result.stderr
    assert b"--private-source" not in result.stderr


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
    "operation", ["version", "doctor", "contract.verify", "inventory", "inspect"]
)
def test_all_commands_launch_from_a_relocated_unicode_repository(
    operation, tmp_path
):
    root = _copy_toolkit(tmp_path)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    if operation == "version":
        argv = ("version", "--json")
    elif operation == "doctor":
        argv = ("doctor", "--json")
    elif operation == "contract.verify":
        argv = ("contract", "verify", "--json")
    elif operation == "inventory":
        source = tmp_path / "Nguồn CTV tổng hợp"
        source.mkdir()
        (source / "hồ sơ thử.pdf").write_bytes(b"%PDF-1.7\nsynthetic")
        argv = ("inventory", "--source-root", str(source), "--json")
    else:
        source = _synthetic_inspection_folder(tmp_path)
        argv = ("inspect", "--source-root", str(source), "--json")

    result = _run(*argv, cwd=unrelated, script=root / "server" / SCRIPT.name)

    payload = _envelope(result, operation, "succeeded")
    assert result.returncode == 0
    assert result.stderr == b""
    if operation == "version":
        assert payload["result"]["sourceCommit"] == EXPECTED_COMMIT
        assert payload["result"]["contractTreeSha256"] == EXPECTED_TREE
    elif operation == "doctor":
        assert payload["result"]["ready"] is True
    elif operation == "contract.verify":
        assert payload["result"]["verified"] is True
        assert payload["result"]["actualTreeSha256"] == EXPECTED_TREE
    elif operation == "inventory":
        assert payload["result"]["inventoryStatus"] == "complete"
        assert payload["result"]["totals"]["regularFiles"] == 1
        serialized = json.dumps(payload, ensure_ascii=False)
        assert str(source) not in serialized
        assert source.name not in serialized
    else:
        assert payload["result"]["inspectionStatus"] in {
            "complete",
            "complete-with-issues",
        }
        assert payload["result"]["totals"]["units"] >= 3
        serialized = json.dumps(payload, ensure_ascii=False)
        for private in _private_fixture_strings(source):
            assert private not in serialized


@pytest.mark.parametrize("module_filename", INSPECTION_MODULE_FILENAMES)
@pytest.mark.parametrize("module_fault", ["missing", "poisoned"])
def test_every_legacy_form_survives_each_broken_inspection_module(
    module_filename, module_fault, tmp_path
):
    root = _copy_toolkit(tmp_path)
    module_path = root / "server" / module_filename
    if module_fault == "missing":
        module_path.unlink()
    else:
        module_path.write_text(
            "raise KeyboardInterrupt('private-poisoned-inspection-import')\n",
            encoding="utf-8",
        )
    source = tmp_path / "synthetic-source"
    source.mkdir()
    invocations = (
        (("version", "--json"), "version"),
        (("doctor", "--json"), "doctor"),
        (("contract", "verify", "--json"), "contract.verify"),
        (("inventory", "--source-root", str(source), "--json"), "inventory"),
    )

    for argv, operation in invocations:
        result = _run(*argv, cwd=tmp_path, script=root / "server" / SCRIPT.name)

        _envelope(result, operation, "succeeded")
        assert result.returncode == 0
        assert result.stderr == b""
        assert b"private-poisoned-inspection-import" not in result.stdout


@pytest.mark.parametrize("module_filename", PROPOSAL_MODULE_FILENAMES)
@pytest.mark.parametrize("module_fault", ["missing", "poisoned"])
def test_legacy_and_invalid_forms_do_not_import_proposal_or_browser_modules(
    module_filename, module_fault, tmp_path
):
    root = _copy_toolkit(tmp_path)
    module_path = root / "server" / module_filename
    if module_fault == "missing":
        module_path.unlink()
    else:
        module_path.write_text(
            "raise KeyboardInterrupt('private-poisoned-proposal-import')\n",
            encoding="utf-8",
        )
    source = tmp_path / "synthetic-source"
    source.mkdir()
    invocations = (
        (("version", "--json"), "version", 0),
        (("doctor", "--json"), "doctor", 0),
        (("contract", "verify", "--json"), "contract.verify", 0),
        (("inventory", "--source-root", str(source), "--json"), "inventory", 0),
        (("inspect", "--source-root", str(source), "--json"), "inspect", 0),
        (("proposal", "review", "--json"), None, 1),
    )

    for argv, operation, expected_exit in invocations:
        result = _run(*argv, cwd=tmp_path, script=root / "server" / SCRIPT.name)

        assert result.returncode == expected_exit
        if operation is None:
            assert result.stdout == b""
            assert result.stderr.startswith(b"usage: ctv_intake_cli.py ")
        else:
            _envelope(result, operation, "succeeded")
            assert result.stderr == b""
        assert b"private-poisoned-proposal-import" not in result.stdout
        assert b"private-poisoned-proposal-import" not in result.stderr


def test_exact_proposal_review_argv_dispatches_source_root_lazily(
    monkeypatch, capsysbinary
):
    cli = _module()
    dispatched = []

    def review(source_root, *, review_driver=None):
        dispatched.append((source_root, review_driver))
        return {
            "version": "1.0",
            "outcome": "cancelled",
            "readyToPrepare": False,
        }

    marker = object()
    monkeypatch.setattr(cli, "proposal_review_source", review, raising=False)

    exit_code = cli.main(
        [
            "proposal",
            "review",
            "--source-root",
            "synthetic-source",
            "--json",
        ],
        proposal_review_driver=marker,
    )

    payload = _captured_envelope(capsysbinary, "proposal.review", "succeeded")
    assert exit_code == 0
    assert dispatched == [(Path("synthetic-source"), marker)]
    assert payload["result"] == {
        "version": "1.0",
        "outcome": "cancelled",
        "readyToPrepare": False,
    }


def test_exception_first_proposal_wires_one_pass_grouping_evidence_and_clears(
    monkeypatch,
    capsysbinary,
):
    cli = _module()
    import ctv_grouping_evidence
    import ctv_inspection
    import ctv_inventory
    import ctv_proposal

    events = []
    inspection = object()

    class Observation:
        result = SimpleNamespace(
            items=(
                SimpleNamespace(
                    evidence_id="evidence-0001",
                    duplicate_group_id="duplicate-0001",
                ),
                SimpleNamespace(
                    evidence_id="evidence-0002",
                    duplicate_group_id=None,
                ),
            )
        )

        def __enter__(self):
            events.append("source-enter")
            return self

        def __exit__(self, *_args):
            events.append("source-exit")
            return False

    class TrackingGroupingEvidence(_TrackingGroupingEvidence):
        def capture_source_duplicate(self, evidence_id, duplicate_group_id):
            events.append(("duplicate", evidence_id, duplicate_group_id))
            super().capture_source_duplicate(evidence_id, duplicate_group_id)

        def capture(self, evidence_id, unit_kind, unit_index, private_text):
            events.append("private-capture")
            super().capture(evidence_id, unit_kind, unit_index, private_text)

        def clear(self):
            events.append("clear")
            super().clear()

    TrackingGroupingEvidence.instances = []

    inspection_calls = []

    def inspect_once(observation, *, _private_text_sink):
        inspection_calls.append(observation)
        assert len(inspection_calls) == 1, "inspection must remain one pass"
        _private_text_sink(
            "evidence-0002",
            "pdf-page",
            1,
            "PRIVATE-GROUPING-MARKER",
        )
        events.append("inspect")
        return inspection

    class State:
        def local_review_snapshot(self):
            return {
                "roster": {"status": "selected"},
                "review": {
                    "coverage": {
                        "unaccountedUnits": 0,
                        "automaticallyOrganizedUnits": 1,
                    }
                },
            }

        def draft_result(self):
            return {
                "version": "1.0",
                "outcome": "draft",
                "observationId": "observation-" + "0" * 64,
                "readyToPrepare": False,
                "counts": {
                    "sources": 2,
                    "units": 1,
                    "participants": 1,
                    "accepted": 1,
                    "reassigned": 0,
                    "excluded": 0,
                    "unresolved": 0,
                },
                "issueCodes": [],
            }

    def state_from_inspection(
        observation,
        actual_inspection,
        *,
        _grouping_evidence,
    ):
        assert actual_inspection is inspection
        assert _grouping_evidence is TrackingGroupingEvidence.instances[0]
        assert _grouping_evidence.cleared is False
        events.append("state")
        return State()

    def review(state):
        local = state.local_review_snapshot()
        assert local["roster"]["status"] == "selected"
        assert local["review"]["coverage"]["unaccountedUnits"] == 0
        assert (
            local["review"]["coverage"]["automaticallyOrganizedUnits"] > 0
        )
        assert TrackingGroupingEvidence.instances[0].cleared is False
        events.append("review")
        return state.draft_result()

    monkeypatch.setattr(
        ctv_grouping_evidence,
        "GroupingEvidence",
        TrackingGroupingEvidence,
    )
    monkeypatch.setattr(
        ctv_inventory,
        "open_inventory_observation",
        lambda _path: Observation(),
    )
    monkeypatch.setattr(ctv_inspection, "inspect_observation", inspect_once)
    monkeypatch.setattr(
        ctv_proposal.ProposalState,
        "from_inspection",
        state_from_inspection,
    )

    exit_code = cli.main(
        [
            "proposal",
            "review",
            "--source-root",
            "synthetic-source",
            "--json",
        ],
        proposal_review_driver=review,
    )

    payload = _captured_envelope(capsysbinary, "proposal.review", "succeeded")
    assert exit_code == 0
    assert payload["result"]["outcome"] == "draft"
    assert "PRIVATE-GROUPING-MARKER" not in json.dumps(payload)
    assert len(TrackingGroupingEvidence.instances) == 1
    assert TrackingGroupingEvidence.instances[0].cleared is True
    assert TrackingGroupingEvidence.instances[0].captures == []
    assert TrackingGroupingEvidence.instances[0].duplicates == []
    assert len(inspection_calls) == 1
    assert events == [
        "source-enter",
        ("duplicate", "evidence-0001", "duplicate-0001"),
        "private-capture",
        "inspect",
        "state",
        "review",
        "clear",
        "source-exit",
    ]


def test_exception_first_real_no_exception_proposal_needs_only_final_approval(
    tmp_path,
    capsysbinary,
):
    cli = _module()
    source = _synthetic_exception_first_folder(tmp_path)
    observed = []

    def approve_without_item_review(state):
        local = state.local_review_snapshot()
        observed.append(local)
        assert local["roster"]["status"] == "selected"
        assert local["review"]["exceptions"] == []
        assert local["review"]["coverage"] == {
            "groups": 2,
            "automaticallyOrganizedUnits": 2,
            "exceptionClusters": 0,
            "exceptionUnits": 0,
            "unaccountedUnits": 0,
        }
        assert local["summary"]["readyToPrepare"] is True
        return state.approve(local["summary"]["proposalDigest"])

    exit_code = cli.main(
        [
            "proposal",
            "review",
            "--source-root",
            str(source),
            "--json",
        ],
        proposal_review_driver=approve_without_item_review,
    )

    payload = _captured_envelope(capsysbinary, "proposal.review", "succeeded")
    result = payload["result"]
    assert exit_code == 0
    assert result["outcome"] == "approved"
    assert result["readyToPrepare"] is True
    assert len(observed) == 1
    serialized = json.dumps(result, ensure_ascii=False)
    assert "Synthetic Grouped Person" not in serialized
    assert "SYNTHETIC-ID-0001" not in serialized
    assert str(source) not in serialized


def test_grouping_evidence_cap_exhaustion_is_an_exception_not_a_guess(
    tmp_path,
    monkeypatch,
):
    cli = _module()
    import ctv_grouping_evidence

    source = _synthetic_exception_first_folder(tmp_path, pdf_pages=2)
    actual_type = ctv_grouping_evidence.GroupingEvidence
    collectors = []

    def bounded_collector():
        value = actual_type(
            max_units=1,
            max_chars_per_unit=32 * 1024,
            max_total_chars=16 * 1024 * 1024,
        )
        collectors.append(value)
        return value

    monkeypatch.setattr(
        ctv_grouping_evidence,
        "GroupingEvidence",
        bounded_collector,
    )

    def review(state):
        local = state.local_review_snapshot()
        assert local["roster"]["status"] == "selected"
        assert local["review"]["coverage"]["unaccountedUnits"] == 0
        assert local["review"]["coverage"]["exceptionClusters"] == 1
        assert local["review"]["coverage"]["exceptionUnits"] == 1
        assert local["review"]["exceptions"][0]["issueCode"] == (
            "private-fact-incomplete"
        )
        return state.draft_result()

    result = cli.proposal_review_source(source, review_driver=review)

    assert result["outcome"] == "draft"
    assert len(collectors) == 1
    assert collectors[0].complete is False
    assert "Synthetic Grouped Person" not in repr(collectors[0])
    assert "SYNTHETIC-ID-0001" not in repr(collectors[0])


def test_exception_first_real_no_exception_package_publishes_after_approval(
    tmp_path,
    capsysbinary,
):
    cli = _module()
    source = _synthetic_exception_first_folder(tmp_path)
    output = tmp_path / "output"
    output.mkdir()

    def approve_without_item_review(state):
        local = state.local_review_snapshot()
        assert local["roster"]["status"] == "selected"
        assert local["review"]["exceptions"] == []
        assert local["review"]["coverage"]["automaticallyOrganizedUnits"] == 2
        assert local["review"]["coverage"]["unaccountedUnits"] == 0
        assert local["summary"]["readyToPrepare"] is True
        return state.approve(local["summary"]["proposalDigest"])

    exit_code = cli.main(
        [
            "package",
            "prepare",
            "--source-root",
            str(source),
            "--output-root",
            str(output),
            "--json",
        ],
        package_review_driver=approve_without_item_review,
    )

    payload = _captured_envelope(capsysbinary, "package.prepare", "succeeded")
    assert exit_code == 0
    assert payload["result"]["outcome"] == "prepared"
    assert payload["result"]["readyForCtvReview"] is True
    assert [path.name for path in output.iterdir()] == [
        payload["result"]["packageDirectoryName"]
    ]
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "Synthetic Grouped Person" not in serialized
    assert "SYNTHETIC-ID-0001" not in serialized
    assert str(source) not in serialized
    assert str(output) not in serialized


def test_exception_first_ambiguous_roster_stays_one_roster_exception(
    tmp_path,
):
    cli = _module()
    source = _synthetic_exception_first_folder(tmp_path, roster_copies=2)

    def review(state):
        local = state.local_review_snapshot()
        assert local["roster"]["status"] == "ambiguous"
        assert local["roster"]["issueCodes"] == ["roster-ambiguous"]
        assert len(local["review"]["exceptions"]) == 1
        assert local["review"]["exceptions"][0]["kind"] == "roster"
        assert local["review"]["exceptions"][0]["issueCode"] == (
            "roster-ambiguous"
        )
        return state.cancelled_result()

    result = cli.proposal_review_source(source, review_driver=review)

    assert result == {
        "version": "1.0",
        "outcome": "cancelled",
        "readyToPrepare": False,
    }


@pytest.mark.parametrize("operation", ("proposal", "package"))
def test_grouping_evidence_is_cleared_when_grouping_construction_fails(
    operation,
    tmp_path,
    monkeypatch,
    capsysbinary,
):
    cli = _module()
    import ctv_grouping_evidence
    import ctv_proposal

    source = _synthetic_exception_first_folder(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    actual_type = ctv_grouping_evidence.GroupingEvidence
    collectors = []

    def collector():
        value = actual_type()
        collectors.append(value)
        return value

    monkeypatch.setattr(ctv_grouping_evidence, "GroupingEvidence", collector)
    monkeypatch.setattr(
        ctv_proposal,
        "build_grouping_plan",
        lambda *_args: (_ for _ in ()).throw(
            RuntimeError("PRIVATE-GROUPING-CONSTRUCTION-DETAIL")
        ),
    )
    argv = (
        [
            "proposal",
            "review",
            "--source-root",
            str(source),
            "--json",
        ]
        if operation == "proposal"
        else [
            "package",
            "prepare",
            "--source-root",
            str(source),
            "--output-root",
            str(output),
            "--json",
        ]
    )

    exit_code = cli.main(argv)

    payload = _captured_envelope(
        capsysbinary,
        "proposal.review" if operation == "proposal" else "package.prepare",
        "failed",
    )
    assert exit_code == 1
    assert payload["errors"] == [
        {
            "code": "internal-error",
            "message": "The local toolkit could not complete the check.",
        }
    ]
    assert "PRIVATE-GROUPING-CONSTRUCTION-DETAIL" not in json.dumps(payload)
    assert len(collectors) == 1
    assert collectors[0].complete is False
    assert list(output.iterdir()) == []


def test_exception_first_proposal_rejects_malformed_injected_terminal(
    monkeypatch,
    capsysbinary,
):
    cli = _module()
    monkeypatch.setattr(
        cli,
        "proposal_review_source",
        lambda _root, *, review_driver=None: {
            "version": "1.0",
            "outcome": "cancelled",
            "readyToPrepare": False,
            "privateMarker": "PRIVATE-INJECTED-TERMINAL",
        },
    )

    exit_code = cli.main(
        [
            "proposal",
            "review",
            "--source-root",
            "synthetic-source",
            "--json",
        ]
    )

    payload = _captured_envelope(capsysbinary, "proposal.review", "failed")
    assert exit_code == 1
    assert payload["errors"] == [
        {
            "code": "internal-error",
            "message": "The local toolkit could not complete the check.",
        }
    ]
    assert "PRIVATE-INJECTED-TERMINAL" not in json.dumps(payload)


def test_exception_first_package_rejects_malformed_injected_terminal(
    monkeypatch,
    capsysbinary,
):
    cli = _module()
    events, _inspection, _approved = _install_package_lifecycle(
        monkeypatch, cli
    )
    terminal = {
        **_approved_terminal(),
        "privateMarker": "PRIVATE-INJECTED-TERMINAL",
    }
    writer_calls = []

    exit_code = cli.main(
        [
            "package",
            "prepare",
            "--source-root",
            "synthetic-source",
            "--output-root",
            "synthetic-output",
            "--json",
        ],
        package_review_driver=lambda _state: terminal,
        package_prepare_driver=lambda *_args: writer_calls.append(_args),
    )

    payload = _captured_envelope(capsysbinary, "package.prepare", "failed")
    assert exit_code == 1
    assert payload["errors"] == [
        {
            "code": "internal-error",
            "message": "The local toolkit could not complete the check.",
        }
    ]
    assert "PRIVATE-INJECTED-TERMINAL" not in json.dumps(payload)
    assert writer_calls == []
    assert events[-3:] == ["grouping-clear", "source-exit", "output-exit"]


@pytest.mark.parametrize("operation", ("proposal", "package"))
def test_grouping_evidence_source_mutation_invalidates_approval_and_publication(
    operation,
    tmp_path,
    monkeypatch,
    capsysbinary,
):
    cli = _module()
    import ctv_grouping_evidence

    source = _synthetic_exception_first_folder(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    source_file = source / "case-contract.pdf"
    actual_type = ctv_grouping_evidence.GroupingEvidence
    collectors = []

    def collector():
        value = actual_type()
        collectors.append(value)
        return value

    monkeypatch.setattr(ctv_grouping_evidence, "GroupingEvidence", collector)

    def mutate_then_approve(state):
        local = state.local_review_snapshot()
        assert local["review"]["exceptions"] == []
        source_file.write_bytes(source_file.read_bytes() + b"SOURCE-MUTATED")
        return state.approve(local["summary"]["proposalDigest"])

    argv = (
        [
            "proposal",
            "review",
            "--source-root",
            str(source),
            "--json",
        ]
        if operation == "proposal"
        else [
            "package",
            "prepare",
            "--source-root",
            str(source),
            "--output-root",
            str(output),
            "--json",
        ]
    )

    exit_code = cli.main(
        argv,
        proposal_review_driver=(
            mutate_then_approve if operation == "proposal" else None
        ),
        package_review_driver=(
            mutate_then_approve if operation == "package" else None
        ),
    )

    payload = _captured_envelope(
        capsysbinary,
        "proposal.review" if operation == "proposal" else "package.prepare",
        "failed",
    )
    assert exit_code == 2
    assert [item["code"] for item in payload["errors"]] == [
        "proposal-source-changed"
        if operation == "proposal"
        else "package-source-changed"
    ]
    assert len(collectors) == 1
    assert collectors[0].complete is False
    assert list(output.iterdir()) == []


def test_exception_first_package_prepare_runs_one_retained_approved_lifecycle(
    monkeypatch, capsysbinary
):
    cli = _module()
    events, inspection, approved = _install_package_lifecycle(monkeypatch, cli)

    def review(state):
        local = state.local_review_snapshot()
        assert local["roster"]["status"] == "selected"
        assert local["review"]["coverage"]["unaccountedUnits"] == 0
        assert (
            local["review"]["coverage"]["automaticallyOrganizedUnits"] > 0
        )
        events.append("review")
        return _approved_terminal()

    def prepare(observation, actual_inspection, actual_approved, output):
        assert actual_inspection is inspection
        assert actual_approved is approved
        events.append("prepare")
        return SimpleNamespace(to_dict=lambda: dict(_PREPARED_RESULT))

    exit_code = cli.main(
        [
            "package",
            "prepare",
            "--source-root",
            "synthetic-source",
            "--output-root",
            "synthetic-output",
            "--json",
        ],
        package_review_driver=review,
        package_prepare_driver=prepare,
    )

    payload = _captured_envelope(capsysbinary, "package.prepare", "succeeded")
    assert exit_code == 0
    assert payload["result"] == {
        "version": "1.0",
        "outcome": "prepared",
        **_PREPARED_RESULT,
        "validation": {
            "outcome": "valid",
            "checkCodes": _PUBLIC_VALIDATION_CODES,
            "warningCodes": [],
        },
    }
    assert events == [
        ("pin", "ctv-intake-v2"),
        ("output-open", Path("synthetic-output")),
        "output-enter",
        ("source-open", Path("synthetic-source")),
        "source-enter",
        "source-chain",
        "disjoint",
        "capture-duplicate",
        "inspect",
        "capture-private",
        "state",
        "review",
        "consume",
        "prepare",
        "grouping-clear",
        "source-exit",
        "output-exit",
    ]


@pytest.mark.parametrize(
    ("check_codes", "warning_codes"),
    [
        ([], []),
        (_INTERNAL_VALIDATION_CODES[:-1], []),
        (
            [
                *_INTERNAL_VALIDATION_CODES[:-1],
                "private-name-nguyen-van-a",
            ],
            [],
        ),
        (_INTERNAL_VALIDATION_CODES, ["private-name-nguyen-van-a"]),
    ],
)
def test_prepared_result_rejects_incomplete_or_private_validation_facts(
    check_codes, warning_codes
):
    cli = _module()
    result = dict(_PREPARED_RESULT)
    result["validation"] = {
        "outcome": "valid",
        "checkCodes": list(check_codes),
        "warningCodes": list(warning_codes),
    }

    with pytest.raises((TypeError, ValueError)) as raised:
        cli._normalize_prepared_result(
            SimpleNamespace(to_dict=lambda: result)
        )

    assert "nguyen-van-a" not in str(raised.value)


@pytest.mark.parametrize(
    "validation",
    [
        {},
        {"outcome": "valid", "warningCodes": []},
        {
            "outcome": "valid",
            "checkCodes": {"privateValue": "Synthetic Person"},
            "warningCodes": [],
        },
        {
            "outcome": "valid",
            "checkCodes": list(_INTERNAL_VALIDATION_CODES),
            "warningCodes": {"privateValue": "Synthetic Person"},
        },
    ],
)
def test_prepared_result_rejects_missing_or_private_shaped_validation(validation):
    cli = _module()
    result = {**_PREPARED_RESULT, "validation": validation}

    with pytest.raises((TypeError, ValueError)) as raised:
        cli._normalize_prepared_result(
            SimpleNamespace(to_dict=lambda: result)
        )

    assert "Synthetic Person" not in str(raised.value)


@pytest.mark.parametrize("field", ["contractVersion", "validation.outcome"])
def test_prepared_result_rejects_equality_spoofing_fixed_strings_without_comparison(
    field,
):
    cli = _module()
    spoof = _EqualitySpoof()
    result = {
        **_PREPARED_RESULT,
        "validation": dict(_PREPARED_RESULT["validation"]),
    }
    if field == "contractVersion":
        result["contractVersion"] = spoof
    else:
        result["validation"]["outcome"] = spoof

    with pytest.raises(ValueError):
        cli._normalize_prepared_result(
            SimpleNamespace(to_dict=lambda: result)
        )

    assert spoof.comparisons == 0


@pytest.mark.parametrize("index", range(len(_INTERNAL_VALIDATION_CODES)))
def test_prepared_result_rejects_equality_spoofing_each_check_code_without_comparison(
    index,
):
    cli = _module()
    spoof = _EqualitySpoof()
    check_codes = list(_INTERNAL_VALIDATION_CODES)
    check_codes[index] = spoof
    result = {
        **_PREPARED_RESULT,
        "validation": {
            **_PREPARED_RESULT["validation"],
            "checkCodes": check_codes,
        },
    }

    with pytest.raises(ValueError):
        cli._normalize_prepared_result(
            SimpleNamespace(to_dict=lambda: result)
        )

    assert spoof.comparisons == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sources", 10_001),
        ("participants", 10_001),
        ("pdfPages", 25_001),
        ("evidenceArtifacts", 1_001),
        ("assignments", 10_001),
        ("exclusions", 20_001),
    ],
)
def test_prepared_result_rejects_counts_above_fixed_public_bounds(field, value):
    cli = _module()
    result = dict(_PREPARED_RESULT)
    result["counts"] = {**_PREPARED_RESULT["counts"], field: value}

    with pytest.raises(ValueError, match="counts"):
        cli._normalize_prepared_result(
            SimpleNamespace(to_dict=lambda: result)
        )


@pytest.mark.parametrize(
    ("outcome", "ready"),
    [("invalid", True), ("valid", False)],
)
def test_prepared_result_requires_valid_ready_coupling(outcome, ready):
    cli = _module()
    result = dict(_PREPARED_RESULT)
    result["readyForCtvReview"] = ready
    result["validation"] = {
        **_PREPARED_RESULT["validation"],
        "outcome": outcome,
    }

    with pytest.raises(ValueError):
        cli._normalize_prepared_result(
            SimpleNamespace(to_dict=lambda: result)
        )


def test_real_writer_validation_is_projected_to_exact_public_codes():
    cli = _module()
    probe = """
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path.cwd() / "server"))

from ctv_inspection import inspect_observation
from ctv_inventory import open_inventory_observation
from ctv_package_transaction import OutputParent
from ctv_package_writer import prepare_package
from intake_fixture_factory_v2 import _approve, _write_sources

with TemporaryDirectory(prefix="ctv-writer-probe-", dir="/private/tmp") as temp:
    root = Path(temp)
    source = root / "source"
    output = root / "output"
    output.mkdir()
    _write_sources(source)

    with OutputParent.open(output) as output_parent:
        with open_inventory_observation(source) as observation:
            output_parent.require_disjoint(
                observation.directory_identity_chain()
            )
            inspection = inspect_observation(observation)
            approved = _approve(observation, inspection)
            writer_result = prepare_package(
                observation,
                inspection,
                approved,
                output_parent,
            )

print(json.dumps(writer_result.to_dict(), sort_keys=True))
"""
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        pytest.fail("isolated real writer probe failed")
    writer_result = json.loads(completed.stdout)

    assert writer_result["validation"]["checkCodes"] == _INTERNAL_VALIDATION_CODES
    projected = cli._normalize_prepared_result(
        SimpleNamespace(to_dict=lambda: writer_result)
    )
    assert projected["validation"] == {
        "outcome": "valid",
        "checkCodes": _PUBLIC_VALIDATION_CODES,
        "warningCodes": [],
    }


@pytest.mark.skipif(os.uname().sysname != "Darwin", reason="Darwin renameatx_np contract")
def test_real_package_cli_returns_prepared_after_post_rename_parent_fsync_failure(
    tmp_path, monkeypatch, capsysbinary
):
    cli = _module()
    import ctv_package_transaction as transaction_module
    from intake_fixture_factory_v2 import _write_sources

    source = tmp_path / "source"
    output = tmp_path / "output"
    output.mkdir()
    _write_sources(source)
    parent_identity = (output.stat().st_dev, output.stat().st_ino)
    real_fsync = os.fsync
    failed = False

    def fail_parent_fsync_after_rename(descriptor):
        nonlocal failed
        metadata = os.fstat(descriptor)
        if (
            not failed
            and stat.S_ISDIR(metadata.st_mode)
            and (metadata.st_dev, metadata.st_ino) == parent_identity
            and any(path.name.startswith("ctv-package-") for path in output.iterdir())
        ):
            failed = True
            raise OSError("private post-rename sync diagnostic")
        return real_fsync(descriptor)

    def approve(state):
        roster = next(
            unit
            for unit in state.units
            if unit["suggestedRole"] == "payment-roster"
        )
        state.select_roster({"rosterUnitId": roster["unitId"]})
        pdf_targets = {
            "unit-0001": ("individual", ["participant-0001"]),
            "unit-0002": ("shared", ["participant-0001", "participant-0002"]),
            "unit-0003": ("individual", ["participant-0002"]),
            "unit-0004": ("case", []),
        }
        for unit in state.units:
            if unit["unitId"] == roster["unitId"]:
                role, target = "payment-roster", ("case", [])
            elif unit["unitKind"] == "pdf-page":
                role, target = "service-contract", pdf_targets[unit["unitId"]]
            elif unit["unitKind"] == "image":
                role, target = "identity-front", (
                    "individual",
                    ["participant-0001"],
                )
            else:
                role, target = "other-supporting-evidence", ("case", [])
            decision = (
                "accepted" if unit["suggestedRole"] == role else "reassigned"
            )
            state.set_unit_decision(
                {
                    "unitId": unit["unitId"],
                    "decision": decision,
                    "role": role,
                    "target": {
                        "scope": target[0],
                        "participantHandles": target[1],
                    },
                }
            )
        unit_source_ids = {unit["evidenceId"] for unit in state.units}
        for record in state.sources:
            if record["evidenceId"] not in unit_source_ids:
                state.set_source_disposition(
                    {
                        "evidenceId": record["evidenceId"],
                        "decision": "excluded",
                        "reason": "irrelevant",
                    }
                )
        digest = state.approval_summary()["proposalDigest"]
        return state.approve(digest)

    monkeypatch.setattr(transaction_module.os, "fsync", fail_parent_fsync_after_rename)
    exit_code = cli.main(
        [
            "package",
            "prepare",
            "--source-root",
            str(source),
            "--output-root",
            str(output),
            "--json",
        ],
        package_review_driver=approve,
    )

    payload = _captured_envelope(capsysbinary, "package.prepare", "succeeded")
    assert exit_code == 0
    assert failed is True
    assert payload["result"]["outcome"] == "prepared"
    final_name = payload["result"]["packageDirectoryName"]
    assert (output / final_name / "validation-report.json").is_file()
    assert not list(output.glob(".ctv-staging-*"))


@pytest.mark.parametrize(
    ("outcome", "terminal"),
    [
        (
            "draft",
            {
                "version": "1.0",
                "outcome": "draft",
                "observationId": "observation-" + "0" * 64,
                "readyToPrepare": False,
                "counts": {
                    "sources": 1,
                    "units": 2,
                    "participants": 0,
                    "accepted": 0,
                    "reassigned": 0,
                    "excluded": 0,
                    "unresolved": 2,
                },
                "issueCodes": ["review-required"],
            },
        ),
        (
            "cancelled",
            {"version": "1.0", "outcome": "cancelled", "readyToPrepare": False},
        ),
    ],
)
def test_package_draft_and_cancel_write_nothing(
    outcome, terminal, monkeypatch, capsysbinary, tmp_path
):
    cli = _module()
    import ctv_grouping_evidence
    import ctv_inspection
    import ctv_proposal

    source = tmp_path / "source"
    source.mkdir()
    output = tmp_path / "output"
    output.mkdir()
    source_before = _external_tree_snapshot(source)
    events = []
    actual_grouping_type = ctv_grouping_evidence.GroupingEvidence
    collectors = []

    def grouping_collector():
        value = actual_grouping_type()
        collectors.append(value)
        return value

    monkeypatch.setattr(
        ctv_grouping_evidence,
        "GroupingEvidence",
        grouping_collector,
    )

    class State:
        def consume_approved_package_snapshot(self, _digest):
            events.append("consume")
            raise AssertionError("draft/cancel must not consume approval")

    monkeypatch.setattr(
        cli,
        "verify_contract",
        lambda _root, *, target: SimpleNamespace(verified=True),
    )
    monkeypatch.setattr(
        ctv_inspection,
        "inspect_observation",
        lambda _observation, *, _private_text_sink: object(),
    )
    monkeypatch.setattr(
        ctv_proposal.ProposalState,
        "from_inspection",
        lambda _observation, _inspection, *, _grouping_evidence: State(),
    )
    writer_calls = []

    exit_code = cli.main(
        [
            "package",
            "prepare",
            "--source-root",
            str(source),
            "--output-root",
            str(output),
            "--json",
        ],
        package_review_driver=lambda _state: dict(terminal),
        package_prepare_driver=lambda *_args: writer_calls.append(_args),
    )

    payload = _captured_envelope(capsysbinary, "package.prepare", "succeeded")
    assert exit_code == 0
    assert payload["result"] == terminal
    assert payload["result"]["outcome"] == outcome
    assert writer_calls == []
    assert "consume" not in events
    assert "prepare" not in events
    assert list(output.iterdir()) == []
    assert len(collectors) == 1
    assert collectors[0].complete is False
    _assert_external_tree_unchanged(source, source_before)


def test_package_v2_pin_failure_precedes_output_and_source_open(
    monkeypatch, capsysbinary
):
    cli = _module()
    import ctv_inventory
    import ctv_package_transaction

    opened = []
    monkeypatch.setattr(
        cli,
        "verify_contract",
        lambda _root, *, target: (_ for _ in ()).throw(
            cli.ContractPinError("contract-tree-changed")
        ),
    )
    monkeypatch.setattr(
        ctv_package_transaction.OutputParent,
        "open",
        staticmethod(lambda _path: opened.append("output")),
    )
    monkeypatch.setattr(
        ctv_inventory,
        "open_inventory_observation",
        lambda _path: opened.append("source"),
    )

    exit_code = cli.main(
        [
            "package",
            "prepare",
            "--source-root",
            "synthetic-source",
            "--output-root",
            "synthetic-output",
            "--json",
        ]
    )

    payload = _captured_envelope(capsysbinary, "package.prepare", "failed")
    assert exit_code == 2
    assert opened == []
    assert payload["errors"] == [
        {
            "code": "contract-tree-changed",
            "message": "The local v2 contract could not be verified safely.",
        }
    ]


def test_package_missing_v2_pin_is_controlled_before_source_open(
    monkeypatch, capsysbinary
):
    cli = _module()
    import ctv_inventory

    opened = []
    monkeypatch.setattr(
        cli,
        "verify_contract",
        lambda _root, *, target: (_ for _ in ()).throw(
            cli.ContractPinError("contract-pin-missing")
        ),
    )
    monkeypatch.setattr(
        ctv_inventory,
        "open_inventory_observation",
        lambda _path: opened.append("source"),
    )

    exit_code = cli.main(
        [
            "package",
            "prepare",
            "--source-root",
            "PRIVATE-SOURCE",
            "--output-root",
            "PRIVATE-OUTPUT",
            "--json",
        ]
    )

    payload = _captured_envelope(capsysbinary, "package.prepare", "failed")
    assert exit_code == 2
    assert opened == []
    assert payload["errors"] == [
        {
            "code": "contract-pin-missing",
            "message": "The local v2 contract could not be verified safely.",
        }
    ]
    assert "PRIVATE" not in json.dumps(payload)


def test_package_v2_pin_mismatch_precedes_output_and_source_open(
    monkeypatch, capsysbinary
):
    cli = _module()
    import ctv_package_transaction

    opened = []
    monkeypatch.setattr(
        cli,
        "verify_contract",
        lambda _root, *, target: SimpleNamespace(verified=False),
    )
    monkeypatch.setattr(
        ctv_package_transaction.OutputParent,
        "open",
        staticmethod(lambda _path: opened.append("output")),
    )

    exit_code = cli.main(
        [
            "package",
            "prepare",
            "--source-root",
            "synthetic-source",
            "--output-root",
            "synthetic-output",
            "--json",
        ]
    )

    payload = _captured_envelope(capsysbinary, "package.prepare", "failed")
    assert exit_code == 2
    assert opened == []
    assert payload["errors"][0]["code"] == "contract-tree-mismatch"


@pytest.mark.parametrize(
    ("error_factory", "expected_code"),
    [
        (
            lambda: __import__("ctv_proposal_review").ReviewError("review-timeout"),
            "proposal-session-timeout",
        ),
        (
            lambda: __import__("ctv_package_writer").PackageWriterError(
                "package-build-failed"
            ),
            "package-build-failed",
        ),
        (
            lambda: __import__("ctv_package_writer").PackageWriterError(
                "package-content-validation-failed"
            ),
            "package-content-validation-failed",
        ),
        (
            lambda: __import__("ctv_package_transaction").PackageCollisionError(),
            "package-output-collision",
        ),
        (
            lambda: __import__("ctv_package_transaction").PackageTransactionError(
                "package-cleanup-failed"
            ),
            "package-cleanup-failed",
        ),
    ],
)
def test_package_controlled_failures_are_private_exit_two(
    error_factory, expected_code, monkeypatch, capsysbinary
):
    cli = _module()
    events, _inspection, _approved = _install_package_lifecycle(
        monkeypatch, cli
    )

    def fail(_state):
        raise error_factory()

    exit_code = cli.main(
        [
            "package",
            "prepare",
            "--source-root",
            "PRIVATE-SOURCE",
            "--output-root",
            "PRIVATE-OUTPUT",
            "--json",
        ],
        package_review_driver=fail,
    )

    payload = _captured_envelope(capsysbinary, "package.prepare", "failed")
    assert exit_code == 2
    assert payload["errors"][0]["code"] == expected_code
    assert events[-3:] == ["grouping-clear", "source-exit", "output-exit"]
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "PRIVATE-SOURCE" not in serialized
    assert "PRIVATE-OUTPUT" not in serialized


@pytest.mark.parametrize(
    ("stage", "expected_code"),
    [
        ("output", "output-root-unsafe"),
        ("source", "source-root-unsafe"),
    ],
)
def test_package_output_and_source_failures_stop_before_review(
    stage, expected_code, monkeypatch, capsysbinary
):
    cli = _module()
    import ctv_inventory
    import ctv_package_transaction

    events, _inspection, _approved = _install_package_lifecycle(monkeypatch, cli)
    if stage == "output":
        monkeypatch.setattr(
            ctv_package_transaction.OutputParent,
            "open",
            staticmethod(
                lambda _path: (_ for _ in ()).throw(
                    ctv_package_transaction.PackageTransactionError(
                        "output-root-unsafe"
                    )
                )
            ),
        )
    else:
        monkeypatch.setattr(
            ctv_inventory,
            "open_inventory_observation",
            lambda _path: (_ for _ in ()).throw(
                ctv_inventory.InventoryError("source-root-unsafe")
            ),
        )

    review_calls = []
    exit_code = cli.main(
        [
            "package",
            "prepare",
            "--source-root",
            "synthetic-source",
            "--output-root",
            "synthetic-output",
            "--json",
        ],
        package_review_driver=lambda state: review_calls.append(state),
    )

    payload = _captured_envelope(capsysbinary, "package.prepare", "failed")
    assert exit_code == 2
    assert payload["errors"][0]["code"] == expected_code
    assert review_calls == []
    assert "review" not in events


def test_package_unexpected_failure_uses_fixed_internal_result(
    monkeypatch, capsysbinary
):
    cli = _module()
    events, _inspection, _approved = _install_package_lifecycle(
        monkeypatch, cli
    )

    def fail(_state):
        raise RuntimeError("PRIVATE unexpected parser detail")

    exit_code = cli.main(
        [
            "package",
            "prepare",
            "--source-root",
            "synthetic-source",
            "--output-root",
            "synthetic-output",
            "--json",
        ],
        package_review_driver=fail,
    )

    payload = _captured_envelope(capsysbinary, "package.prepare", "failed")
    assert exit_code == 1
    assert payload["errors"] == [
        {
            "code": "internal-error",
            "message": "The local toolkit could not complete the check.",
        }
    ]
    assert events[-3:] == ["grouping-clear", "source-exit", "output-exit"]
    assert b"PRIVATE" not in capsysbinary.readouterr().out


def test_package_oversized_result_is_replaced_before_one_stdout_write(
    monkeypatch
):
    cli = _module()
    _install_package_lifecycle(monkeypatch, cli)
    writes = []
    monkeypatch.setattr(cli, "_emit_stdout", lambda content: writes.append(content))
    canonical = cli.canonical_json_bytes

    def oversized_success(envelope):
        if envelope.operation == "package.prepare" and envelope.status == "succeeded":
            return b"x" * (16 * 1024 * 1024 + 1)
        return canonical(envelope)

    monkeypatch.setattr(cli, "canonical_json_bytes", oversized_success)

    exit_code = cli.main(
        [
            "package",
            "prepare",
            "--source-root",
            "synthetic-source",
            "--output-root",
            "synthetic-output",
            "--json",
        ],
        package_review_driver=lambda _state: _approved_terminal(),
        package_prepare_driver=lambda *_args: SimpleNamespace(
            to_dict=lambda: dict(_PREPARED_RESULT)
        ),
    )

    assert exit_code == 2
    assert len(writes) == 1
    payload = json.loads(writes[0])
    assert payload["errors"][0]["code"] == "package-output-too-large"
    assert len(writes[0]) <= 16 * 1024 * 1024
    assert b"package-output-too-large" in writes[0]


def test_published_package_survives_stdout_failure(monkeypatch):
    cli = _module()
    events, _inspection, _approved = _install_package_lifecycle(monkeypatch, cli)
    published = []

    def prepare(*_args):
        published.append("ctv-package-" + "0" * 24)
        events.append("prepare")
        return SimpleNamespace(to_dict=lambda: dict(_PREPARED_RESULT))

    monkeypatch.setattr(
        cli,
        "_emit_stdout",
        lambda _content: (_ for _ in ()).throw(BrokenPipeError()),
    )

    exit_code = cli.main(
        [
            "package",
            "prepare",
            "--source-root",
            "synthetic-source",
            "--output-root",
            "synthetic-output",
            "--json",
        ],
        package_review_driver=lambda _state: _approved_terminal(),
        package_prepare_driver=prepare,
    )

    assert exit_code == 1
    assert published == ["ctv-package-" + "0" * 24]
    assert "prepare" in events


@pytest.mark.parametrize("returned", [1, None, True, "all-bytes"])
def test_published_package_survives_invalid_stdout_write_count(
    returned, monkeypatch
):
    cli = _module()
    _install_package_lifecycle(monkeypatch, cli)
    published = []

    class ShortStream:
        def __init__(self):
            self.writes = 0
            self.received = b""
            self.flushes = 0

        def write(self, content):
            self.writes += 1
            self.received = content[:1]
            return returned

        def flush(self):
            self.flushes += 1

    stream = ShortStream()
    monkeypatch.setattr(cli.sys, "stdout", SimpleNamespace(buffer=stream))

    def prepare(*_args):
        published.append("ctv-package-" + "0" * 24)
        return SimpleNamespace(to_dict=lambda: dict(_PREPARED_RESULT))

    exit_code = cli.main(
        [
            "package",
            "prepare",
            "--source-root",
            "synthetic-source",
            "--output-root",
            "synthetic-output",
            "--json",
        ],
        package_review_driver=lambda _state: _approved_terminal(),
        package_prepare_driver=prepare,
    )

    assert exit_code == 1
    assert published == ["ctv-package-" + "0" * 24]
    assert stream.writes == 1
    assert len(stream.received) == 1
    assert stream.flushes == 0


@pytest.mark.parametrize(
    "argv",
    [
        ["package", "prepare"],
        ["package", "prep", "--source-root", "/source", "--output-root", "/output", "--json"],
        ["package", "prepare", "--source-root", "", "--output-root", "/output", "--json"],
        ["package", "prepare", "--source-root", "/source", "--output-root", "", "--json"],
        ["package", "prepare", "--source-root", "--private", "--output-root", "/output", "--json"],
        ["package", "prepare", "--source-root", "/source", "--output-root", "--private", "--json"],
        ["package", "prepare", "--output-root", "/output", "--source-root", "/source", "--json"],
        ["package", "prepare", "--source-root", "/source", "--json", "--output-root", "/output"],
        ["package", "prepare", "--source-root", "/source/", "--output-root", "/output", "--json"],
        ["package", "prepare", "--source-root", "/source", "--output-root", "/output//child", "--json"],
        ["package", "prepare", "--source-root", "/source", "--output-root", "/output", "--json", "extra"],
        ["package", "prepare", "--source-root", "/source", "--source-root", "/other", "--output-root", "/output", "--json"],
        ["package", "prepare", "--source-root", "/source", "--output-root", "/output", "--json", "--json"],
    ],
)
def test_invalid_package_prepare_surface_is_exact_and_private(argv):
    result = _run(*argv)

    assert result.returncode == 1
    assert result.stdout == b""
    assert result.stderr.startswith(b"usage: ctv_intake_cli.py ")
    assert 0 < len(result.stderr) <= 512
    assert b"--private" not in result.stderr


@pytest.mark.parametrize(
    "argv",
    [
        ["contract", "verify", "--json", "--target", "ctv-intake-v2"],
        ["contract", "verify", "--target", "ctv-intake-v2", "--json", "--json"],
        ["contract", "verify", "--target", "ctv-intake-v2", "--target", "ctv-intake-v2", "--json"],
        ["contract", "verify", "--target", "ctv-intake-v", "--json"],
        ["contract", "verify", "--target", "", "--json"],
    ],
)
def test_v2_contract_verify_accepts_only_its_exact_argv(argv):
    result = _run(*argv)

    assert result.returncode == 1
    assert result.stdout == b""
    assert result.stderr.startswith(b"usage: ctv_intake_cli.py ")
    assert len(result.stderr) <= 512


@pytest.mark.parametrize("module_filename", PACKAGE_MODULE_FILENAMES)
@pytest.mark.parametrize("module_fault", ["missing", "poisoned"])
def test_nonpackage_forms_do_not_import_package_writer_modules(
    module_filename, module_fault, tmp_path
):
    root = _copy_toolkit(tmp_path)
    module_path = root / "server" / module_filename
    if module_fault == "missing":
        module_path.unlink()
    else:
        module_path.write_text(
            "raise KeyboardInterrupt('private-poisoned-package-import')\n",
            encoding="utf-8",
        )
    source = tmp_path / "synthetic-source"
    source.mkdir()
    invocations = (
        (("version", "--json"), "version", 0),
        (("doctor", "--json"), "doctor", 0),
        (("contract", "verify", "--json"), "contract.verify", 0),
        (("contract", "verify", "--target", "ctv-intake-v2", "--json"), "contract.verify", 0),
        (("inventory", "--source-root", str(source), "--json"), "inventory", 0),
        (("inspect", "--source-root", str(source), "--json"), "inspect", 0),
        (("package", "prepare", "--json"), None, 1),
    )

    for argv, operation, expected_exit in invocations:
        result = _run(*argv, cwd=tmp_path, script=root / "server" / SCRIPT.name)

        assert result.returncode == expected_exit
        if operation is None:
            assert result.stdout == b""
            assert result.stderr.startswith(b"usage: ctv_intake_cli.py ")
        else:
            _envelope(result, operation, "succeeded")
            assert result.stderr == b""
        assert b"private-poisoned-package-import" not in result.stdout
        assert b"private-poisoned-package-import" not in result.stderr


def test_proposal_review_output_over_16_mib_is_replaced_before_one_stdout_write(
    monkeypatch, capsysbinary
):
    cli = _module()
    monkeypatch.setattr(
        cli,
        "proposal_review_source",
        lambda _root, *, review_driver=None: {
            "version": "1.0",
            "outcome": "draft",
            "observationId": "observation-" + "0" * 64,
            "readyToPrepare": False,
            "counts": {
                "sources": 1,
                "units": 1,
                "participants": 0,
                "accepted": 0,
                "reassigned": 0,
                "excluded": 0,
                "unresolved": 1,
            },
            "issueCodes": ["review-required"] * 1_000_000,
        },
        raising=False,
    )

    exit_code = cli.main(
        [
            "proposal",
            "review",
            "--source-root",
            "synthetic-source",
            "--json",
        ]
    )

    payload = _captured_envelope(capsysbinary, "proposal.review", "failed")
    assert exit_code == 2
    assert payload["result"] == {}
    assert payload["errors"] == [
        {
            "code": "proposal-output-too-large",
            "message": "The local proposal review result exceeded its safe limit.",
        }
    ]


@pytest.mark.parametrize("module_filename", INSPECTION_MODULE_FILENAMES)
@pytest.mark.parametrize("module_fault", ["missing", "poisoned"])
def test_inspect_broken_module_import_is_fixed_internal_error(
    module_filename, module_fault, tmp_path
):
    root = _copy_toolkit(tmp_path)
    module_path = root / "server" / module_filename
    if module_fault == "missing":
        module_path.unlink()
    else:
        module_path.write_text(
            "raise SystemExit('private-poisoned-inspection-import')\n",
            encoding="utf-8",
        )
    source = tmp_path / "synthetic-source"
    source.mkdir()

    result = _run(
        "inspect",
        "--source-root",
        str(source),
        "--json",
        cwd=tmp_path,
        script=root / "server" / SCRIPT.name,
    )

    payload = _envelope(result, "inspect", "failed")
    assert result.returncode == 1
    assert result.stderr == b""
    assert [entry["code"] for entry in payload["errors"]] == ["internal-error"]
    assert b"private-poisoned-inspection-import" not in result.stdout


@pytest.mark.parametrize(
    "injection",
    ("import", "engine", "error-accessor", "to-dict", "serializer"),
)
def test_inspect_contains_generator_exit_at_every_safety_boundary(
    injection, tmp_path
):
    root = _copy_toolkit(tmp_path)
    _install_generator_exit_injection(root, injection)
    source = tmp_path / "synthetic-source"
    source.mkdir()

    result = _run(
        "inspect",
        "--source-root",
        str(source),
        "--json",
        cwd=tmp_path,
        script=root / "server" / SCRIPT.name,
    )

    payload = _envelope(result, "inspect", "failed")
    assert result.returncode == 1
    assert result.stderr == b""
    assert [entry["code"] for entry in payload["errors"]] == ["internal-error"]
    assert b"PRIVATE_GENERATOR_DETAIL" not in result.stdout
    assert b"Traceback" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("controlled_failure", "expected_exit", "expected_status"),
    [(False, 0, "succeeded"), (True, 2, "failed")],
)
def test_relocated_toolkit_inside_selected_root_never_mutates_external_tree(
    tmp_path, controlled_failure, expected_exit, expected_status
):
    selected_root = _copy_toolkit(tmp_path)
    if controlled_failure:
        nested = selected_root
        for index in range(33):
            nested = nested / f"synthetic-depth-{index:02d}"
            nested.mkdir()
    before = _external_tree_snapshot(selected_root)
    environment = dict(os.environ)
    environment.pop("PYTHONDONTWRITEBYTECODE", None)
    environment.pop("PYTHONPYCACHEPREFIX", None)

    result = _run(
        "inventory",
        "--source-root",
        str(selected_root),
        "--json",
        cwd=tmp_path,
        script=selected_root / "server" / SCRIPT.name,
        env=environment,
    )

    payload = _envelope(result, "inventory", expected_status)
    assert result.returncode == expected_exit
    assert result.stderr == b""
    if controlled_failure:
        assert [error["code"] for error in payload["errors"]] == [
            "inventory-depth-exceeded"
        ]
    else:
        assert payload["result"]["inventoryStatus"] == "complete"
    _assert_external_tree_unchanged(selected_root, before)


@pytest.mark.parametrize(
    ("controlled_failure", "expected_exit", "expected_status"),
    [(False, 0, "succeeded"), (True, 2, "failed")],
)
def test_relocated_inspection_toolkit_inside_source_never_writes_or_caches_bytecode(
    tmp_path, controlled_failure, expected_exit, expected_status
):
    selected_root = _copy_toolkit(tmp_path)
    if controlled_failure:
        nested = selected_root
        for index in range(33):
            nested = nested / f"synthetic-depth-{index:02d}"
            nested.mkdir()
    before = _external_tree_snapshot(selected_root)
    environment = dict(os.environ)
    environment.pop("PYTHONDONTWRITEBYTECODE", None)
    environment.pop("PYTHONPYCACHEPREFIX", None)

    result = _run(
        "inspect",
        "--source-root",
        str(selected_root),
        "--json",
        cwd=tmp_path,
        script=selected_root / "server" / SCRIPT.name,
        env=environment,
    )

    payload = _envelope(result, "inspect", expected_status)
    assert result.returncode == expected_exit
    assert result.stderr == b""
    if controlled_failure:
        assert [error["code"] for error in payload["errors"]] == [
            "inventory-depth-exceeded"
        ]
    else:
        assert payload["result"]["inspectionStatus"] == "complete-with-issues"
    assert not tuple(selected_root.rglob("__pycache__"))
    assert not tuple(selected_root.rglob("*.pyc"))
    _assert_external_tree_unchanged(selected_root, before)


def test_canonical_root_path_is_dispatched_without_traversing_it(
    monkeypatch, capsysbinary
):
    cli = _module()
    dispatched = []

    def record(source_root):
        dispatched.append(source_root)
        return _inventory_result()

    monkeypatch.setattr(cli, "inventory_source", record)

    exit_code = cli.main(["inventory", "--source-root", os.sep, "--json"])

    payload = _captured_envelope(capsysbinary, "inventory", "succeeded")
    assert exit_code == 0
    assert payload["result"]["inventoryStatus"] == "complete"
    assert dispatched == [Path(os.sep)]


def test_canonical_root_path_is_dispatched_to_inspection_without_traversing_it(
    monkeypatch, capsysbinary
):
    cli = _module()
    dispatched = []

    def record(source_root):
        dispatched.append(source_root)
        return _inspection_result()

    monkeypatch.setattr(cli, "inspect_source", record)

    exit_code = cli.main(["inspect", "--source-root", os.sep, "--json"])

    payload = _captured_envelope(capsysbinary, "inspect", "succeeded")
    assert exit_code == 0
    assert payload["result"]["inspectionStatus"] == "complete"
    assert dispatched == [Path(os.sep)]


def _import_roots(path: Path) -> set[str]:
    roots = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def _attribute_calls(path: Path) -> set[str]:
    calls = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
        ):
            calls.add(f"{node.func.value.id}.{node.func.attr}")
    return calls


def _called_attribute_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


def _shell_enabled_call_lines(path: Path) -> set[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and any(
            keyword.arg == "shell"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is True
            for keyword in node.keywords
        )
    }


def test_inventory_modules_have_no_network_subprocess_parser_ocr_or_ai_imports():
    network_forbidden = {
        "socket",
        "urllib",
        "http",
        "requests",
        "httpx",
        "ftplib",
        "webbrowser",
    }
    for name in (
        "ctv_intake_cli.py",
        "ctv_cli_doctor.py",
        "ctv_contract_pin.py",
        "ctv_inventory.py",
        "ctv_inventory_detection.py",
    ):
        assert _import_roots(SCRIPT.with_name(name)).isdisjoint(network_forbidden)

    inventory_forbidden = network_forbidden | {
        "subprocess",
        "zipfile",
        "tarfile",
        "rarfile",
        "py7zr",
        "fitz",
        "pypdf",
        "PyPDF2",
        "docx",
        "openpyxl",
        "PIL",
        "pytesseract",
        "cv2",
        "torch",
        "transformers",
        "openai",
        "anthropic",
    }
    for name in ("ctv_inventory.py", "ctv_inventory_detection.py"):
        assert _import_roots(SCRIPT.with_name(name)).isdisjoint(
            inventory_forbidden
        )
    assert "subprocess" not in _import_roots(SCRIPT)
    forbidden_shell_calls = {
        "os.system",
        "os.popen",
        "os.spawnl",
        "os.spawnle",
        "os.spawnlp",
        "os.spawnlpe",
        "os.spawnv",
        "os.spawnve",
        "os.spawnvp",
        "os.spawnvpe",
    }
    assert _attribute_calls(SCRIPT).isdisjoint(forbidden_shell_calls)


def test_all_production_modules_keep_process_archive_network_ai_and_shell_boundaries_static():
    production_modules = tuple(
        path
        for path in SCRIPT.parent.glob("*.py")
        if not path.name.endswith("_test.py")
    )
    assert {path.name for path in production_modules} >= {
        "app.py",
        "ctv_intake_cli.py",
        "pipeline.py",
        "roster_workbook.py",
    }
    subprocess_importers = {
        path.name
        for path in production_modules
        if "subprocess" in _import_roots(path)
    }
    assert subprocess_importers == {"ctv_local_ocr.py", "export_contract_pin.py"}

    zip_importers = {
        path.name
        for path in production_modules
        if "zipfile" in _import_roots(path)
    }
    assert zip_importers == {
        "cccd_workbook.py",
        "ctv_inspection_workbook.py",
        "roster_workbook.py",
    }

    archive_extractors = {"tarfile", "rarfile", "py7zr"}
    remote_or_ai = {
        "anthropic",
        "ftplib",
        "http",
        "httpx",
        "openai",
        "requests",
        "socket",
        "torch",
        "transformers",
        "urllib",
        "webbrowser",
    }
    for path in production_modules:
        roots = _import_roots(path)
        assert roots.isdisjoint(archive_extractors)
        if path.name == "ctv_proposal_review.py":
            assert roots.intersection(remote_or_ai) == {
                "http",
                "urllib",
                "webbrowser",
            }
        else:
            assert roots.isdisjoint(remote_or_ai)
        assert _called_attribute_names(path).isdisjoint(
            {"extract", "extractall", "unpack_archive"}
        )

    local_ocr_importers = {
        path.name
        for path in production_modules
        if "pytesseract" in _import_roots(path)
    }
    assert local_ocr_importers == {"cccd_ocr.py", "ocr_extract.py"}

    temporary_file_importers = {
        path.name
        for path in production_modules
        if "tempfile" in _import_roots(path)
    }
    assert temporary_file_importers == {"cccd_ingest.py", "cccd_ocr.py"}
    assert all("shlex" not in _import_roots(path) for path in production_modules)

    forbidden_shell_calls = {
        "os.system",
        "os.popen",
        "os.spawnl",
        "os.spawnle",
        "os.spawnlp",
        "os.spawnlpe",
        "os.spawnv",
        "os.spawnve",
        "os.spawnvp",
        "os.spawnvpe",
    }
    for path in production_modules:
        assert _attribute_calls(path).isdisjoint(forbidden_shell_calls)
        assert not _shell_enabled_call_lines(path)


def test_inspection_cli_error_allowlist_matches_literal_engine_declaration():
    cli = _module()
    inspection_path = SCRIPT.with_name("ctv_inspection.py")
    tree = ast.parse(inspection_path.read_text(encoding="utf-8"))
    assignments = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "INSPECTION_ERROR_CODES"
            for target in node.targets
        )
    ]
    assert len(assignments) == 1
    declaration = assignments[0].value
    assert isinstance(declaration, ast.Tuple)
    assert all(
        isinstance(element, ast.Constant) and type(element.value) is str
        for element in declaration.elts
    ), "Inspection error declarations must remain fail-closed string literals"
    engine_codes = tuple(element.value for element in declaration.elts)
    assert engine_codes == tuple(sorted(engine_codes))
    assert len(engine_codes) == len(set(engine_codes))

    cli_tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    cli_assignments = [
        node
        for node in cli_tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "_INSPECTION_ERROR_CODES"
            for target in node.targets
        )
    ]
    assert len(cli_assignments) == 1
    cli_declaration = cli_assignments[0].value
    assert (
        isinstance(cli_declaration, ast.Call)
        and isinstance(cli_declaration.func, ast.Name)
        and cli_declaration.func.id == "frozenset"
        and not cli_declaration.keywords
        and len(cli_declaration.args) == 1
        and isinstance(cli_declaration.args[0], ast.Set)
    ), "CLI inspection allowlist must remain one fail-closed literal frozenset"
    cli_elements = cli_declaration.args[0].elts
    assert all(
        isinstance(element, ast.Constant) and type(element.value) is str
        for element in cli_elements
    ), "CLI inspection allowlist must not contain dynamic values"
    cli_codes = tuple(element.value for element in cli_elements)
    assert len(cli_codes) == len(set(cli_codes))
    assert frozenset(cli_codes) == frozenset(engine_codes)
    assert cli._INSPECTION_ERROR_CODES == frozenset(engine_codes)

    retained_assignments = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "_RETAINED_INVENTORY_ERROR_CODES"
            for target in node.targets
        )
    ]
    assert len(retained_assignments) == 1
    retained_declaration = retained_assignments[0].value
    assert (
        isinstance(retained_declaration, ast.Call)
        and isinstance(retained_declaration.func, ast.Name)
        and retained_declaration.func.id == "frozenset"
        and not retained_declaration.keywords
        and len(retained_declaration.args) == 1
        and isinstance(retained_declaration.args[0], ast.Set)
    )
    retained_elements = retained_declaration.args[0].elts
    assert all(
        isinstance(element, ast.Constant) and type(element.value) is str
        for element in retained_elements
    )
    retained_codes = {element.value for element in retained_elements}

    mapped_function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_mapped_inventory_error_code"
    )
    guarded_dynamic_returns = 0
    for node in ast.walk(mapped_function):
        if not (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "code"
            and len(node.test.ops) == len(node.test.comparators) == 1
            and isinstance(node.test.ops[0], ast.In)
            and isinstance(node.test.comparators[0], ast.Name)
            and node.test.comparators[0].id == "_RETAINED_INVENTORY_ERROR_CODES"
        ):
            continue
        if node.orelse or len(node.body) != 1 or not isinstance(node.body[0], ast.Return):
            continue
        guarded = node.body[0].value
        if (
            isinstance(guarded, ast.Name)
            and guarded.id == "code"
        ):
            guarded_dynamic_returns += 1

    assert guarded_dynamic_returns == 1

    raise_function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_raise_controlled_failure"
    )
    guarded_dynamic_calls = {
        id(node)
        for node in ast.walk(raise_function)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "InspectionError"
            and not node.keywords
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "code"
        )
    }
    assert len(guarded_dynamic_calls) == 1

    emitted_codes = set(retained_codes)
    emitted_codes.update(
        node.value.value
        for node in ast.walk(tree)
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "failure_code"
                for target in node.targets
            )
            and isinstance(node.value, ast.Constant)
            and type(node.value.value) is str
        )
    )
    unsupported_calls = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "InspectionError"
        ):
            continue
        if node.keywords or len(node.args) != 1:
            unsupported_calls.append(
                f"line {node.lineno}: expected one positional argument"
            )
            continue
        argument = node.args[0]
        if isinstance(argument, ast.Constant) and type(argument.value) is str:
            emitted_codes.add(argument.value)
        elif id(node) not in guarded_dynamic_calls:
            unsupported_calls.append(
                f"line {node.lineno}: unsupported dynamic InspectionError code"
            )
    assert not unsupported_calls, "\n".join(unsupported_calls)
    assert emitted_codes == set(engine_codes)


def _parser_destinations(parser) -> set[str]:
    seen = set()
    pending = [parser]
    while pending:
        current = pending.pop()
        for action in current._actions:
            seen.add(action.dest.replace("_", "-"))
            seen.update(option.lstrip("-") for option in action.option_strings)
            choices = getattr(action, "choices", None)
            if isinstance(choices, dict):
                pending.extend(choices.values())
    return seen


def test_parser_exposes_source_root_only_on_document_commands():
    cli = _module()
    parser = cli._parser()
    command_action = next(
        action for action in parser._actions if isinstance(action.choices, dict)
    )
    commands = command_action.choices
    assert "source-root" in _parser_destinations(commands["inventory"])
    assert "source-root" in _parser_destinations(commands["inspect"])
    assert "source-root" in _parser_destinations(commands["proposal"])
    assert "source-root" in _parser_destinations(commands["package"])
    assert "output-root" in _parser_destinations(commands["package"])
    for command in ("version", "doctor", "contract"):
        assert "source-root" not in _parser_destinations(commands[command])
        assert "output-root" not in _parser_destinations(commands[command])

    forbidden = {
        "workspace-root",
        "input-file",
        "output-file",
        "install",
        "repair",
        "update",
    }
    assert _parser_destinations(parser).isdisjoint(forbidden)


@pytest.mark.parametrize(
    "argv",
    [
        ["version", "--json"],
        ["doctor", "--json"],
        ["contract", "verify", "--json"],
        ["inventory", "--source-root", "synthetic-source", "--json"],
        ["inspect", "--source-root", "synthetic-source", "--json"],
    ],
)
def test_exact_argv_validation_accepts_only_documented_forms(
    argv, monkeypatch, capsysbinary
):
    cli = _module()
    monkeypatch.setattr(
        cli,
        "_version_envelope",
        lambda: cli.succeeded("version", "synthetic", {}),
    )
    monkeypatch.setattr(
        cli,
        "_doctor_result",
        lambda: (cli.succeeded("doctor", "synthetic", {}), 0),
    )
    monkeypatch.setattr(
        cli,
        "_contract_result",
        lambda: (cli.succeeded("contract.verify", "synthetic", {}), 0),
    )
    monkeypatch.setattr(cli, "inventory_source", lambda _root: _inventory_result())
    monkeypatch.setattr(cli, "inspect_source", lambda _root: _inspection_result())

    exit_code = cli.main(argv)

    captured = capsysbinary.readouterr()
    assert exit_code == 0
    assert captured.out.endswith(b"\n")
    assert captured.err == b""
