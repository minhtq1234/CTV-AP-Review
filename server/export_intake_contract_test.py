import importlib
import json
import re
from pathlib import Path

import pytest


CONTRACT_ROOT = Path(__file__).resolve().parents[1] / "contracts" / "ctv-intake" / "v1"
V2_CONTRACT_ROOT = Path(__file__).resolve().parents[1] / "contracts" / "ctv-intake" / "v2"
ARTIFACT_FILENAMES = (
    "package.schema.json",
    "exceptions.schema.json",
    "validation-report.schema.json",
    "canonical-roster.schema.json",
    "exception-codes.json",
    "compatibility.md",
)
_TIMESTAMP_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}")
_ABSOLUTE_BUILD_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9+./:-])(?:/(?!/)[^\s\"'`<>()\[\]{},;]+|[A-Za-z]:[\\/][^\s\"'`<>()\[\]{},;]+)"
)


def _artifact_string_values(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for nested_value in value.values():
            yield from _artifact_string_values(nested_value)
    elif isinstance(value, list):
        for nested_value in value:
            yield from _artifact_string_values(nested_value)


def _absolute_build_paths(artifact_text):
    try:
        values = _artifact_string_values(json.loads(artifact_text))
    except json.JSONDecodeError:
        values = [artifact_text]

    return [
        match.group(0)
        for value in values
        if not value.startswith(("#/", "http://", "https://"))
        for match in _ABSOLUTE_BUILD_PATH_RE.finditer(value)
    ]


def test_absolute_path_detector_rejects_foreign_posix_and_windows_build_paths():
    posix_path = "/tmp/build/contract.json"
    windows_path = r"C:\build\contract.json"
    foreign_artifact = json.dumps({"description": f"Built at {posix_path}; {windows_path}"})

    assert str(Path(__file__).resolve().parents[1]) not in foreign_artifact
    assert _absolute_build_paths(foreign_artifact) == [posix_path, windows_path]
    assert not _absolute_build_paths(json.dumps({
        "$ref": "#/$defs/Source",
        "$schema": "https://json-schema.org/draft/2020-12/schema",
    }))


def test_export_is_deterministic_and_matches_checked_in_artifacts(tmp_path):
    exporter = importlib.import_module("export_intake_contract").export_contract_artifacts
    first_export = tmp_path / "first"
    second_export = tmp_path / "second"

    exporter(first_export)
    exporter(second_export)

    assert {path.name for path in first_export.iterdir()} == set(ARTIFACT_FILENAMES)
    for filename in ARTIFACT_FILENAMES:
        first_bytes = (first_export / filename).read_bytes()
        assert first_bytes == (second_export / filename).read_bytes()
        assert first_bytes == (CONTRACT_ROOT / filename).read_bytes()

        text = first_bytes.decode("utf-8")
        assert not _absolute_build_paths(text)
        assert not _TIMESTAMP_RE.search(text)
        if filename.endswith(".json"):
            assert text.endswith("\n")
            assert json.loads(text)


V2_ARTIFACT_FILENAMES = {
    "package.schema.json",
    "assignments.schema.json",
    "canonical-roster.schema.json",
    "exceptions.schema.json",
    "validation-report.schema.json",
    "exception-codes.json",
    "compatibility.md",
    "fixtures/README.md",
    "fixtures/schema-example/case-manifest.json",
    "fixtures/schema-example/assignments.json",
    "fixtures/schema-example/exceptions.json",
    "fixtures/schema-example/validation-report.json",
    "fixtures/invalid-assignment/case-manifest.json",
    "fixtures/invalid-assignment/assignments.json",
    "fixtures/invalid-assignment/exceptions.json",
}


def _relative_files(root):
    return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}


def test_v2_export_requires_an_explicit_target_and_is_byte_deterministic(tmp_path):
    exporter = importlib.import_module("export_intake_contract").export_contract_artifacts
    v1_output = tmp_path / "v1"
    first_v2_output = tmp_path / "first-v2"
    second_v2_output = tmp_path / "second-v2"

    exporter(v1_output)
    exporter(first_v2_output, compatibility_target="ctv-intake-v2")
    exporter(second_v2_output, compatibility_target="ctv-intake-v2")

    assert _relative_files(v1_output) == set(ARTIFACT_FILENAMES)
    assert _relative_files(first_v2_output) == V2_ARTIFACT_FILENAMES
    assert _relative_files(second_v2_output) == V2_ARTIFACT_FILENAMES
    for relative_path in V2_ARTIFACT_FILENAMES:
        assert (first_v2_output / relative_path).read_bytes() == (second_v2_output / relative_path).read_bytes()
        assert (first_v2_output / relative_path).read_bytes() == (V2_CONTRACT_ROOT / relative_path).read_bytes()


def test_v2_exported_examples_are_closed_documents_and_invalid_assignment_has_one_reason(tmp_path):
    from intake_contract_v2 import (
        AssignmentsDocumentV2,
        ExceptionsDocumentV2,
        PackageManifestV2,
        ValidationReportV2,
    )

    exporter = importlib.import_module("export_intake_contract").export_contract_artifacts
    output = tmp_path / "only-selected-target"
    exporter(output, compatibility_target="ctv-intake-v2")
    assert {path.name for path in tmp_path.iterdir()} == {"only-selected-target"}

    schema = output / "fixtures" / "schema-example"
    manifest = PackageManifestV2.model_validate(json.loads((schema / "case-manifest.json").read_text()))
    assignments = AssignmentsDocumentV2.model_validate(json.loads((schema / "assignments.json").read_text()))
    assignments.validate_against_manifest(manifest)
    assert ExceptionsDocumentV2.model_validate(json.loads((schema / "exceptions.json").read_text())).items == []
    ValidationReportV2.model_validate(json.loads((schema / "validation-report.json").read_text()))

    invalid = output / "fixtures" / "invalid-assignment"
    invalid_manifest = PackageManifestV2.model_validate(json.loads((invalid / "case-manifest.json").read_text()))
    invalid_assignments = AssignmentsDocumentV2.model_validate(json.loads((invalid / "assignments.json").read_text()))
    assert ExceptionsDocumentV2.model_validate(json.loads((invalid / "exceptions.json").read_text())).items == []
    with pytest.raises(ValueError, match="assignment decision must resolve"):
        invalid_assignments.validate_against_manifest(invalid_manifest)
