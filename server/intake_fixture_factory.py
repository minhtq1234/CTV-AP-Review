"""Materialize synthetic CTV intake-contract fixtures for tests."""
from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from pathlib import Path

import fitz
import openpyxl

from intake_contract import ExceptionsDocument, PackageManifest


_FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "contracts" / "ctv-intake" / "v1" / "fixtures"


class FixtureValidationError(ValueError):
    """A synthetic fixture fails a stable contract-facing validation code."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class MaterializedFixture:
    manifest: PackageManifest
    exceptions: ExceptionsDocument
    input_pdf: Path
    roster_workbook: Path


def materialize_fixture(name: str, output: Path) -> MaterializedFixture:
    """Parse checked-in fixture documents and generate their binary inputs."""
    fixture_root = _FIXTURES_ROOT / name
    manifest_document = _read_json(fixture_root / "case-manifest.json")
    exceptions_path = fixture_root / "exceptions.json"
    exceptions = ExceptionsDocument.model_validate(
        _read_json(exceptions_path) if exceptions_path.exists() else {
            "schemaVersion": "1.0", "items": [],
        }
    )
    output.mkdir(parents=True, exist_ok=True)
    input_pdf = output / "input.pdf"
    roster_workbook = output / "roster.xlsx"
    exceptions_output = output / "exceptions.json"
    _write_synthetic_pdf(input_pdf)
    _write_synthetic_roster(roster_workbook)
    exceptions_output.write_text(
        _canonical_json(exceptions.model_dump(by_alias=True, mode="json")),
        encoding="utf-8",
    )

    if not isinstance(manifest_document, dict):
        raise ValueError("fixture manifest must be an object")
    sources = manifest_document["sources"]
    pdf_source = next(
        source for source in sources if source["mediaType"] == "application/pdf"
    )
    roster_source = next(
        source for source in sources if source["mediaType"] != "application/pdf"
    )
    _set_size_and_digest(pdf_source, input_pdf)
    _set_size_and_digest(roster_source, roster_workbook)
    manifest_document["artifacts"] = [
        _artifact("artifact-input-pdf", "input-pdf", input_pdf, [pdf_source["sourceId"]]),
        _artifact("artifact-roster", "roster", roster_workbook, [roster_source["sourceId"]]),
        _artifact("artifact-exceptions", "exceptions", exceptions_output, []),
    ]
    manifest = PackageManifest.model_validate(manifest_document)
    (output / "case-manifest.json").write_text(
        _canonical_json(manifest.model_dump(by_alias=True, mode="json")),
        encoding="utf-8",
    )
    return MaterializedFixture(manifest, exceptions, input_pdf, roster_workbook)


def validate_materialized_fixture(fixture: MaterializedFixture) -> None:
    """Ensure every declared source PDF page is represented by fixture coverage."""
    pdf_sources = [
        source for source in fixture.manifest.sources
        if source.media_type == "application/pdf"
    ]
    uncovered_pages = [
        (source.source_id, page_number)
        for source in pdf_sources
        for page_number in range(1, (source.page_count or 0) + 1)
        if not _page_is_covered(fixture.manifest, source.source_id, page_number)
    ]
    missing_page_counts = [
        source.source_id for source in pdf_sources if source.page_count is None
    ]

    if not uncovered_pages and not missing_page_counts:
        return
    if fixture.manifest.status == "prepared":
        raise FixtureValidationError("unassigned-page")
    if not any(
        item.code == "unassigned-page" and item.severity == "blocking"
        for item in fixture.exceptions.items
    ):
        raise FixtureValidationError("unassigned-page")


def _page_is_covered(manifest: PackageManifest, source_id: str, source_page: int) -> bool:
    return any(
        page.source_id == source_id
        and page.source_page == source_page
        and page.coverage_state != "unresolved"
        for page in manifest.pdf_pages
    )


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_synthetic_pdf(path: Path) -> None:
    document = fitz.open()
    try:
        for page_number in (1, 2):
            page = document.new_page()
            page.insert_text((72, 72), f"Synthetic fixture page {page_number}")
        document.save(path)
    finally:
        document.close()


def _write_synthetic_roster(path: Path) -> None:
    workbook = openpyxl.Workbook()
    try:
        worksheet = workbook.active
        worksheet.title = "Roster"
        worksheet.append(["Name", "Identity", "FA code"])
        worksheet.append(["SUBJECT-ALPHA", "SYNTHETIC-IDENTITY-A", "FA-SYNTH-001"])
        workbook.save(path)
    finally:
        workbook.close()


def _set_size_and_digest(document: dict, path: Path) -> None:
    content = path.read_bytes()
    document["size"] = len(content)
    document["sha256"] = hashlib.sha256(content).hexdigest()


def _artifact(
    artifact_id: str, kind: str, path: Path, source_ids: list[str]
) -> dict:
    content = path.read_bytes()
    return {
        "artifactId": artifact_id,
        "kind": kind,
        "path": path.name,
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "sourceIds": source_ids,
    }


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
