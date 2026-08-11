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
        assert str(Path(__file__).resolve().parents[1]) not in text
        assert not _TIMESTAMP_RE.search(text)
        if filename.endswith(".json"):
            assert text.endswith("\n")
            assert json.loads(text)
