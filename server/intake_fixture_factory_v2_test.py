"""Generated fixture coverage for the production-backed intake v2 package."""

from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path

from ctv_inventory import open_inventory_observation
from intake_contract_v2 import AssignmentsDocumentV2, PackageManifestV2
from intake_fixture_factory_v2 import materialize_v2_fixture
from intake_package_validator import _PackageReader
from intake_package_validator_v2 import (
    V2ValidationExpectation,
    validate_v2_publication_reader,
)


def _tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@contextmanager
def _reader(path: Path):
    reader, failure = _PackageReader.open(path)
    assert failure is None and reader is not None
    try:
        yield reader
    finally:
        reader.close()


def test_complete_fixture_uses_production_outputs_and_is_deterministic(tmp_path):
    first = materialize_v2_fixture("complete", tmp_path / "first")

    assert isinstance(first.manifest, PackageManifestV2)
    assert isinstance(first.assignments, AssignmentsDocumentV2)
    assert first.observation_id == first.manifest.source_observation_id
    assert first.proposal_digest == first.manifest.proposal_digest
    assert first.manifest_sha256 == sha256(
        (first.package_dir / "case-manifest.json").read_bytes()
    ).hexdigest()
    package = _tree(first.package_dir)
    for artifact in first.manifest.artifacts:
        assert sha256(package[artifact.path]).hexdigest() == artifact.sha256
        assert len(package[artifact.path]) == artifact.size
    assert not (first.package_dir / "validation-report.json").exists()
    assert {path.name for path in tmp_path.iterdir()} == {"first"}
    joined = b"".join(_tree(first.source_dir).values())
    assert b"Synthetic" in joined or b"SYNTHETIC" in joined


def test_invalid_assignment_fixture_has_one_digest_bound_cross_reference_failure(
    tmp_path,
):
    fixture = materialize_v2_fixture("invalid-assignment", tmp_path / "fixture")
    assignment_bytes = (fixture.package_dir / "assignments.json").read_bytes()
    assignment_artifact = next(
        item for item in fixture.manifest.artifacts if item.kind == "assignments"
    )

    assert sha256(assignment_bytes).hexdigest() == assignment_artifact.sha256
    assert len(assignment_bytes) == assignment_artifact.size
    assert fixture.assignments.units[0].decision_id not in {
        item.decision_id for item in fixture.manifest.decisions
    }


def test_receipt_is_created_only_from_a_valid_content_result(tmp_path):
    fixture = materialize_v2_fixture(
        "complete", tmp_path / "fixture", include_receipt=True
    )
    receipt = json.loads((fixture.package_dir / "validation-report.json").read_bytes())

    assert receipt["outcome"] == "valid"
    assert receipt["checks"]
    with open_inventory_observation(fixture.source_dir) as observation:
        with _reader(fixture.package_dir) as reader:
            publication = validate_v2_publication_reader(
                reader,
                observation,
                V2ValidationExpectation(
                    observation_id=fixture.observation_id,
                    proposal_digest=fixture.proposal_digest,
                    expected_manifest_sha256=fixture.manifest_sha256,
                ),
            )
    assert publication.report.outcome == "valid"
    assert publication.report.checks[-1].code == "validation-report-consistent"
