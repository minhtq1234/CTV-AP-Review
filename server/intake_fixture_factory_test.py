import fitz
import openpyxl
import pytest

from intake_fixture_factory import (
    FixtureValidationError,
    MaterializedFixture,
    materialize_fixture,
    validate_materialized_fixture,
)
from intake_package_validator import validate_package


def test_complete_fixture_materializes_synthetic_files_with_full_coverage(tmp_path):
    fixture = materialize_fixture("complete", tmp_path)

    assert fixture.manifest.status == "prepared"
    assert {source.coverage_state for source in fixture.manifest.sources} == {"assigned"}
    assert [
        source.page_count
        for source in fixture.manifest.sources
        if source.media_type == "application/pdf"
    ] == [2]
    assert {page.coverage_state for page in fixture.manifest.pdf_pages} == {"assigned"}
    assert fixture.exceptions.items == []
    with fitz.open(fixture.input_pdf) as document:
        assert document.page_count == 2
    workbook = openpyxl.load_workbook(fixture.roster_workbook, read_only=True)
    try:
        assert list(workbook.active.values) == [
            ("Name", "Identity", "FA code"),
            ("SUBJECT-ALPHA", "SYNTHETIC-IDENTITY-A", "FA-SYNTH-001"),
        ]
    finally:
        workbook.close()

    validate_materialized_fixture(fixture)


def test_fixture_validation_uses_declared_source_page_count_as_authority(tmp_path):
    fixture = materialize_fixture("complete", tmp_path)
    manifest = fixture.manifest.model_copy(deep=True)
    pdf_source = next(
        source for source in manifest.sources if source.media_type == "application/pdf"
    )
    pdf_source.page_count = 3
    altered = MaterializedFixture(
        manifest=manifest,
        exceptions=fixture.exceptions,
        input_pdf=fixture.input_pdf,
        roster_workbook=fixture.roster_workbook,
        source_root=fixture.source_root,
    )

    with pytest.raises(FixtureValidationError, match="unassigned-page"):
        validate_materialized_fixture(altered)


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


@pytest.mark.parametrize(
    ("fixture_name", "outcome", "status", "required_error"),
    [
        ("complete", "valid", "prepared", None),
        ("partial", "invalid", "partially_prepared", "blocking-exception"),
        (
            "invalid-hidden-page",
            "invalid",
            "partially_prepared",
            "page-coverage-missing",
        ),
    ],
)
def test_materialized_fixture_is_a_real_package_validated_through_public_api(
    tmp_path, fixture_name, outcome, status, required_error
):
    package_dir = tmp_path / fixture_name
    fixture = materialize_fixture(fixture_name, package_dir)

    assert (package_dir / "case-manifest.json").is_file()
    assert (package_dir / "input.pdf").is_file()
    assert (package_dir / "roster.xlsx").is_file()
    assert (package_dir / "exceptions.json").is_file()

    assert fixture.source_root != package_dir
    report = validate_package(package_dir, source_root=fixture.source_root)

    assert report.outcome == outcome
    assert report.package_status == status
    if required_error is None:
        assert report.errors == []
    else:
        assert required_error in report.errors
