import importlib
import json
import re
from pathlib import Path


CONTRACT_ROOT = Path(__file__).resolve().parents[1] / "contracts" / "ctv-intake" / "v1"
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
