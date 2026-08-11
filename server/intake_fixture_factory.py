"""Materialize synthetic CTV intake-contract fixtures for tests."""
from __future__ import annotations

import json
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
    manifest = PackageManifest.model_validate(_read_json(fixture_root / "case-manifest.json"))
    exceptions_path = fixture_root / "exceptions.json"
    exceptions = ExceptionsDocument.model_validate(
        _read_json(exceptions_path) if exceptions_path.exists() else {
            "schemaVersion": "1.0", "items": [],
        }
    )
    output.mkdir(parents=True, exist_ok=True)
    input_pdf = output / "synthetic-input.pdf"
    roster_workbook = output / "synthetic-roster.xlsx"
    _write_synthetic_pdf(input_pdf)
    _write_synthetic_roster(roster_workbook)
    return MaterializedFixture(manifest, exceptions, input_pdf, roster_workbook)


def validate_materialized_fixture(fixture: MaterializedFixture) -> None:
    """Ensure every generated PDF page is represented by fixture coverage."""
    pdf_sources = [
        source for source in fixture.manifest.sources
        if source.media_type == "application/pdf"
    ]
    with fitz.open(fixture.input_pdf) as document:
        uncovered_pages = [
            (source.source_id, page_number)
            for source in pdf_sources
            for page_number in range(1, document.page_count + 1)
            if not _page_is_covered(fixture.manifest, source.source_id, page_number)
        ]

    if not uncovered_pages:
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
        worksheet.append(["FA code"])
        worksheet.append(["FA-SYNTH-001"])
        workbook.save(path)
    finally:
        workbook.close()
