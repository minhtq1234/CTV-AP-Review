"""Export the versioned CTV intake contract artifacts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from intake_contract import (
    EXCEPTION_CODES,
    CanonicalRosterRow,
    ExceptionsDocument,
    PackageManifest,
    ValidationReport,
)


_JSON_ARTIFACTS = {
    "package.schema.json": PackageManifest,
    "exceptions.schema.json": ExceptionsDocument,
    "validation-report.schema.json": ValidationReport,
    "canonical-roster.schema.json": CanonicalRosterRow,
}

_COMPATIBILITY = """# CTV Intake Contract v1 compatibility

Producers and consumers must match major version `1`.

Consumers may accept added optional fields only after the contract tests pass.
Removing or renaming fields, changing enum meaning, or weakening coverage is a
major change.

Exception codes are append-only within v1.

WP records the exact CTV commit and tree digest in `SOURCE.json`.
"""


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def export_contract_artifacts(output: Path) -> None:
    """Write the CTV intake contract v1 artifacts to *output*."""
    output.mkdir(parents=True, exist_ok=True)
    for filename, model in _JSON_ARTIFACTS.items():
        (output / filename).write_text(_canonical_json(model.model_json_schema()), encoding="utf-8")
    (output / "exception-codes.json").write_text(
        _canonical_json(EXCEPTION_CODES), encoding="utf-8"
    )
    (output / "compatibility.md").write_text(_COMPATIBILITY, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    export_contract_artifacts(args.output)


if __name__ == "__main__":
    main()
