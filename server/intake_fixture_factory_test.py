import fitz
import openpyxl
import pytest

from intake_fixture_factory import (
    FixtureValidationError,
    materialize_fixture,
    validate_materialized_fixture,
)


def test_complete_fixture_materializes_synthetic_files_with_full_coverage(tmp_path):
    fixture = materialize_fixture("complete", tmp_path)

    assert fixture.manifest.status == "prepared"
    assert {source.coverage_state for source in fixture.manifest.sources} == {"assigned"}
    assert {page.coverage_state for page in fixture.manifest.pdf_pages} == {"assigned"}
    assert fixture.exceptions.items == []
    with fitz.open(fixture.input_pdf) as document:
        assert document.page_count == 2
    workbook = openpyxl.load_workbook(fixture.roster_workbook, read_only=True)
    try:
        assert list(workbook.active.values) == [("FA code",), ("FA-SYNTH-001",)]
    finally:
        workbook.close()

    validate_materialized_fixture(fixture)


def test_partial_fixture_exposes_unassigned_page_as_a_blocking_exception(tmp_path):
    fixture = materialize_fixture("partial", tmp_path)

    assert fixture.manifest.status == "partially_prepared"
    assert fixture.manifest.pdf_pages[-1].coverage_state == "unresolved"
    assert [(item.code, item.severity) for item in fixture.exceptions.items] == [
        ("unassigned-page", "blocking"),
    ]

    validate_materialized_fixture(fixture)


def test_invalid_hidden_page_fixture_is_rejected_with_stable_unassigned_page_code(tmp_path):
    fixture = materialize_fixture("invalid-hidden-page", tmp_path)

    with pytest.raises(FixtureValidationError) as error:
        validate_materialized_fixture(fixture)

    assert error.value.code == "unassigned-page"
