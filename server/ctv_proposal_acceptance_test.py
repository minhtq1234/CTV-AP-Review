"""Generated end-to-end acceptance for the local proposal-review CLI."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
import stat

import fitz
from openpyxl import Workbook
from PIL import Image
import pytest


PRIVATE_VALUES = (
    "PRIVATE PERSON ONE",
    "PRIVATE PERSON TWO",
    "079123456781",
    "079123456782",
    "PRIVATE-CONTRACT-079123456789",
    "hop-dong-rieng-079123456789.pdf",
    "bang-ke-rieng-079123456789.xlsx",
    "anh-rieng-079123456789.png",
)


def _cli():
    return importlib.import_module("ctv_intake_cli")


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "Nguon CTV rieng tu"
    source.mkdir()

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Bang ke rieng"
    worksheet.append(("HO TEN", "CCCD", "FACODE", "SO TIEN"))
    worksheet.append(("PRIVATE PERSON ONE", "079123456781", "FA-001", 100_000))
    worksheet.append(("PRIVATE PERSON TWO", "079123456782", "FA-001", 200_000))
    workbook.save(source / "bang-ke-rieng-079123456789.xlsx")
    workbook.close()

    document = fitz.open()
    page = document.new_page()
    page.insert_text(
        (72, 72),
        "HOP DONG DICH VU\nBEN A\nBEN B\nCHU KY\n"
        "PRIVATE-CONTRACT-079123456789",
    )
    document.save(source / "hop-dong-rieng-079123456789.pdf")
    document.close()

    with Image.new("RGB", (64, 64), "white") as image:
        image.save(source / "anh-rieng-079123456789.png")

    (source / "ghi-chu-khong-ho-tro.txt").write_text(
        "PRIVATE NOTE 079123456789", encoding="utf-8"
    )
    return source


def _tree_snapshot(root: Path):
    snapshot = {}
    for path in (root, *root.rglob("*")):
        metadata = path.lstat()
        snapshot[path.relative_to(root).as_posix()] = (
            metadata.st_mode,
            metadata.st_mtime_ns,
            path.read_bytes() if stat.S_ISREG(metadata.st_mode) else None,
        )
    return snapshot


def _run(cli, argv, capsysbinary, *, driver):
    exit_code = cli.main(argv, proposal_review_driver=driver)
    captured = capsysbinary.readouterr()
    assert captured.err == b""
    assert captured.out.endswith(b"\n")
    payload = json.loads(captured.out)
    assert captured.out == (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        + b"\n"
    )
    assert payload["schemaVersion"] == "1.0"
    assert payload["operation"] == "proposal.review"
    return exit_code, payload, captured.out


def _approved_driver(state):
    roster = next(
        unit
        for unit in state.units
        if unit["unitKind"] == "worksheet"
        and unit["suggestedRole"] == "payment-roster"
    )
    assert state.local_review_snapshot()["roster"]["rosterUnitId"] == roster["unitId"]
    handles = state.approval_summary()["participantHandles"]
    assert len(handles) == 2

    for index, unit in enumerate(state.units):
        suggested = unit["suggestedRole"]
        if index == 0:
            target = {"scope": "individual", "participantHandles": [handles[0]]}
        elif index == 1:
            target = {"scope": "shared", "participantHandles": handles}
        else:
            target = {"scope": "case", "participantHandles": []}
        if suggested == "unknown":
            mapping = {
                "unitId": unit["unitId"],
                "decision": "reassigned",
                "role": "other-supporting-evidence",
                "target": target,
            }
        else:
            mapping = {
                "unitId": unit["unitId"],
                "decision": "accepted",
                "role": suggested,
                "target": target,
            }
        state.set_unit_decision(mapping)

    unit_evidence_ids = {unit["evidenceId"] for unit in state.units}
    for source in state.sources:
        if source["evidenceId"] not in unit_evidence_ids:
            state.set_source_disposition(
                {
                    "evidenceId": source["evidenceId"],
                    "decision": "excluded",
                    "reason": "irrelevant",
                }
            )
    summary = state.approval_summary()
    assert summary["readyToPrepare"] is True
    return state.approve(summary["proposalDigest"])


@pytest.mark.parametrize(
    ("driver", "outcome"),
    [
        (_approved_driver, "approved"),
        (lambda state: state.draft_result(), "draft"),
        (lambda state: state.cancelled_result(), "cancelled"),
    ],
)
def test_generated_terminal_outcomes_are_canonical_private_safe_and_read_only(
    driver, outcome, tmp_path, capsysbinary
):
    cli = _cli()
    source = _source(tmp_path)
    before = _tree_snapshot(source)

    exit_code, payload, raw = _run(
        cli,
        ["proposal", "review", "--source-root", str(source), "--json"],
        capsysbinary,
        driver=driver,
    )

    assert exit_code == 0
    assert payload["status"] == "succeeded"
    assert payload["result"]["outcome"] == outcome
    assert payload["result"]["readyToPrepare"] is (outcome == "approved")
    if outcome != "approved":
        assert "unitAssignments" not in payload["result"]
        assert "sourceDispositions" not in payload["result"]
    for private in (*PRIVATE_VALUES, str(source), source.name, "PRIVATE NOTE"):
        assert private.encode("utf-8") not in raw
    assert _tree_snapshot(source) == before
    assert sorted(path.name for path in tmp_path.iterdir()) == [source.name]


def test_source_mutation_discards_buffered_terminal_result(
    tmp_path, capsysbinary
):
    cli = _cli()
    source = _source(tmp_path)
    target = source / "hop-dong-rieng-079123456789.pdf"

    def mutate_then_return(state):
        result = state.draft_result()
        target.write_bytes(target.read_bytes() + b"PRIVATE-MUTATION")
        return result

    exit_code, payload, raw = _run(
        cli,
        ["proposal", "review", "--source-root", str(source), "--json"],
        capsysbinary,
        driver=mutate_then_return,
    )

    assert exit_code == 2
    assert payload["status"] == "failed"
    assert payload["result"] == {}
    assert payload["errors"] == [
        {
            "code": "proposal-source-changed",
            "message": "The source folder changed during local proposal review.",
        }
    ]
    assert b'"outcome"' not in raw
    assert b"PRIVATE-MUTATION" not in raw


def test_controlled_review_failure_returns_one_fixed_failure(
    tmp_path, capsysbinary
):
    cli = _cli()
    source = _source(tmp_path)

    def fail(_state):
        from ctv_proposal_review import ReviewError

        raise ReviewError("review-server-failed")

    exit_code, payload, raw = _run(
        cli,
        ["proposal", "review", "--source-root", str(source), "--json"],
        capsysbinary,
        driver=fail,
    )

    assert exit_code == 2
    assert payload["status"] == "failed"
    assert payload["result"] == {}
    assert payload["errors"] == [
        {
            "code": "proposal-session-failed",
            "message": "The local proposal review session could not be completed.",
        }
    ]
    assert raw.count(b'"schemaVersion"') == 1


def test_delegated_base_exception_is_fixed_and_has_no_partial_result(
    tmp_path, capsysbinary
):
    cli = _cli()
    source = _source(tmp_path)

    def fail(_state):
        raise GeneratorExit("PRIVATE GENERATOR DETAIL 079123456789")

    exit_code, payload, raw = _run(
        cli,
        ["proposal", "review", "--source-root", str(source), "--json"],
        capsysbinary,
        driver=fail,
    )

    assert exit_code == 1
    assert payload["status"] == "failed"
    assert payload["result"] == {}
    assert payload["errors"] == [
        {
            "code": "internal-error",
            "message": "The local toolkit could not complete the check.",
        }
    ]
    assert b"PRIVATE GENERATOR DETAIL" not in raw
    assert b"Traceback" not in raw


def test_unchanged_generated_approval_is_byte_deterministic(
    tmp_path, capsysbinary
):
    cli = _cli()
    source = _source(tmp_path)
    argv = ["proposal", "review", "--source-root", str(source), "--json"]

    first_exit, _first_payload, first = _run(
        cli, argv, capsysbinary, driver=_approved_driver
    )
    second_exit, _second_payload, second = _run(
        cli, argv, capsysbinary, driver=_approved_driver
    )

    assert first_exit == second_exit == 0
    assert first == second
