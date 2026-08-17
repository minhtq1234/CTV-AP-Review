import pytest

import ctv_package_writer as writer_module
from ctv_inspection import inspect_observation
from ctv_inventory import InventoryError, open_inventory_observation
from ctv_package_transaction import OutputParent
from ctv_package_writer import PackageWriterError, prepare_package
from intake_fixture_factory_v2 import _approve, _write_sources
from intake_package_validator import _PackageReader


def _approved_source(tmp_path):
    source = tmp_path / "source"
    _write_sources(source)
    return source


def _assert_safe_error(code, operation):
    with pytest.raises(RuntimeError) as raised:
        operation()
    assert getattr(raised.value, "code", None) == code
    assert str(raised.value) == code
    return raised.value


def test_prepare_package_real_flow_publishes_valid_complete_tree(tmp_path):
    source = _approved_source(tmp_path)
    output_root = tmp_path / "output"
    output_root.mkdir()
    source_before = sorted(
        (path.relative_to(source).as_posix(), path.read_bytes())
        for path in source.iterdir()
        if path.is_file()
    )

    with OutputParent.open(output_root) as output:
        with open_inventory_observation(source) as observation:
            output.require_disjoint(observation.directory_identity_chain())
            inspection = inspect_observation(observation)
            approved = _approve(observation, inspection)
            result = prepare_package(
                observation, inspection, approved, output
            )

    final = output_root / result.package_directory_name
    assert final.is_dir()
    assert sorted(
        path.relative_to(final).as_posix()
        for path in final.rglob("*")
        if path.is_file()
    ) == [
        "assignments.json",
        "case-manifest.json",
        "evidence/evidence-0001.png",
        "evidence/evidence-0002.xlsx",
        "exceptions.json",
        "input.pdf",
        "roster.xlsx",
        "validation-report.json",
    ]
    assert result.ready_for_ctv_review is True
    assert result.validation.outcome == "valid"
    assert result.validation.check_codes[-1] == "validation-report-consistent"
    assert result.to_dict() == {
        "packageId": result.package_id,
        "packageDirectoryName": result.package_directory_name,
        "manifestSha256": result.manifest_sha256,
        "declaredArtifactSetSha256": result.declared_artifact_set_sha256,
        "publishedTreeSha256": result.published_tree_sha256,
        "contractVersion": "2.0",
        "counts": {
            "sources": 5,
            "participants": 2,
            "pdfPages": 4,
            "evidenceArtifacts": 2,
            "assignments": 8,
            "exclusions": 1,
        },
        "validation": {
            "outcome": "valid",
            "checkCodes": list(result.validation.check_codes),
            "warningCodes": [],
        },
        "readyForCtvReview": True,
    }
    assert sorted(
        (path.relative_to(source).as_posix(), path.read_bytes())
        for path in source.iterdir()
        if path.is_file()
    ) == source_before


def test_prepare_package_second_identical_run_collides_without_modifying_output(
    tmp_path,
):
    source = _approved_source(tmp_path)
    output_root = tmp_path / "output"
    output_root.mkdir()

    def run_once():
        with OutputParent.open(output_root) as output:
            with open_inventory_observation(source) as observation:
                output.require_disjoint(observation.directory_identity_chain())
                inspection = inspect_observation(observation)
                approved = _approve(observation, inspection)
                return prepare_package(observation, inspection, approved, output)

    first = run_once()
    before = sorted(
        (path.relative_to(output_root).as_posix(), path.read_bytes())
        for path in output_root.rglob("*")
        if path.is_file()
    )
    _assert_safe_error("package-output-collision", run_once)
    after = sorted(
        (path.relative_to(output_root).as_posix(), path.read_bytes())
        for path in output_root.rglob("*")
        if path.is_file()
    )

    assert before == after
    assert [path.name for path in output_root.iterdir()] == [
        first.package_directory_name
    ]


def test_prepare_package_build_failure_occurs_before_staging(tmp_path, monkeypatch):
    output_root = tmp_path / "output"
    output_root.mkdir()

    def fail_plan(*_args):
        raise RuntimeError("private builder diagnostic")

    monkeypatch.setattr(writer_module, "create_build_plan", fail_plan)
    with OutputParent.open(output_root) as output:
        error = _assert_safe_error(
            "package-build-failed",
            lambda: prepare_package(object(), object(), object(), output),
        )

    assert list(output_root.iterdir()) == []
    assert "diagnostic" not in str(error)


@pytest.mark.parametrize(
    "boundary,expected",
    [
        ("reader-close", "package-content-validation-failed"),
        ("receipt", "package-receipt-write-failed"),
    ],
)
def test_prepare_package_internal_io_failures_are_fixed_private_and_cleaned(
    tmp_path, monkeypatch, boundary, expected
):
    source = _approved_source(tmp_path)
    output_root = tmp_path / "output"
    output_root.mkdir()
    if boundary == "reader-close":
        monkeypatch.setattr(
            _PackageReader,
            "close",
            lambda _self: (_ for _ in ()).throw(
                OSError("private descriptor diagnostic")
            ),
        )
    else:
        monkeypatch.setattr(
            writer_module,
            "canonical_v2_receipt_bytes",
            lambda _content: (_ for _ in ()).throw(
                RuntimeError("private receipt diagnostic")
            ),
        )

    with OutputParent.open(output_root) as output:
        with pytest.raises(PackageWriterError, match=f"^{expected}$") as raised:
            with open_inventory_observation(source) as observation:
                output.require_disjoint(observation.directory_identity_chain())
                inspection = inspect_observation(observation)
                approved = _approve(observation, inspection)
                prepare_package(observation, inspection, approved, output)

    assert "diagnostic" not in str(raised.value)
    assert list(output_root.iterdir()) == []


@pytest.mark.parametrize(
    "boundary,expected",
    [
        ("content", "package-content-validation-failed"),
        ("publication", "package-publication-validation-failed"),
        ("source", "inventory-tree-changed"),
    ],
)
def test_prepare_package_failure_before_publish_cleans_staging(
    tmp_path, monkeypatch, boundary, expected
):
    source = _approved_source(tmp_path)
    output_root = tmp_path / "output"
    output_root.mkdir()

    with OutputParent.open(output_root) as output:
        with pytest.raises(RuntimeError, match=f"^{expected}$"):
            with open_inventory_observation(source) as observation:
                output.require_disjoint(observation.directory_identity_chain())
                inspection = inspect_observation(observation)
                approved = _approve(observation, inspection)
                if boundary == "content":
                    monkeypatch.setattr(
                        writer_module,
                        "validate_v2_content_reader",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(
                            PackageWriterError(expected)
                        ),
                    )
                elif boundary == "publication":
                    monkeypatch.setattr(
                        writer_module,
                        "validate_v2_publication_reader",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(
                            PackageWriterError(expected)
                        ),
                    )
                else:
                    monkeypatch.setattr(
                        type(observation),
                        "finalize_for_publication",
                        lambda _self: (_ for _ in ()).throw(
                            InventoryError(expected)
                        ),
                    )
                prepare_package(observation, inspection, approved, output)

    assert list(output_root.iterdir()) == []


def test_prepare_package_writes_declared_artifacts_in_plan_order(tmp_path, monkeypatch):
    source = _approved_source(tmp_path)
    output_root = tmp_path / "output"
    output_root.mkdir()
    writes = []
    real_write = writer_module.StagingTransaction.write_bytes

    def tracked_write(self, path, content):
        writes.append(path)
        return real_write(self, path, content)

    monkeypatch.setattr(writer_module.StagingTransaction, "write_bytes", tracked_write)
    with OutputParent.open(output_root) as output:
        with open_inventory_observation(source) as observation:
            output.require_disjoint(observation.directory_identity_chain())
            inspection = inspect_observation(observation)
            approved = _approve(observation, inspection)
            plan = writer_module.create_build_plan(observation, inspection, approved)
            prepare_package(observation, inspection, approved, output)

    assert writes == [
        *(recipe.path for recipe in plan.recipes),
        "case-manifest.json",
        "validation-report.json",
    ]
