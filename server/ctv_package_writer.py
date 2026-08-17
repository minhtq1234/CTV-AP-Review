"""Build, validate, finalize, and atomically publish one CTV v2 package."""

from __future__ import annotations

from dataclasses import dataclass

from ctv_inventory import InventoryObservation
from ctv_package_builder import (
    ArtifactReceipt,
    PackageBuildError,
    PackageBuildPlan,
    build_manifest_bytes,
    create_build_plan,
    iter_rendered_artifacts,
)
from ctv_package_transaction import (
    OutputParent,
    PackageTransactionError,
    StagingTransaction,
)
from intake_contract_v2 import (
    MAX_INPUT_PDF_BYTES,
    MAX_JSON_BYTES,
    MAX_PACKAGE_BYTES,
    MAX_ROSTER_OR_EVIDENCE_BYTES,
)
from intake_package_validator import PackageTreeSnapshot
from intake_package_validator_v2 import (
    ContentValidationV2,
    V2ValidationExpectation,
    canonical_v2_receipt_bytes,
    validate_v2_content_reader,
    validate_v2_publication_reader,
)


class PackageWriterError(RuntimeError):
    """A fixed, private-data-free package preparation failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class PackagePreparationCounts:
    sources: int
    participants: int
    pdf_pages: int
    evidence_artifacts: int
    assignments: int
    exclusions: int

    def to_dict(self) -> dict[str, int]:
        return {
            "sources": self.sources,
            "participants": self.participants,
            "pdfPages": self.pdf_pages,
            "evidenceArtifacts": self.evidence_artifacts,
            "assignments": self.assignments,
            "exclusions": self.exclusions,
        }


@dataclass(frozen=True)
class PackagePreparationValidation:
    outcome: str
    check_codes: tuple[str, ...]
    warning_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "outcome": self.outcome,
            "checkCodes": list(self.check_codes),
            "warningCodes": list(self.warning_codes),
        }


@dataclass(frozen=True)
class PackagePreparationResult:
    package_id: str
    package_directory_name: str
    manifest_sha256: str
    declared_artifact_set_sha256: str
    published_tree_sha256: str
    contract_version: str
    counts: PackagePreparationCounts
    validation: PackagePreparationValidation
    ready_for_ctv_review: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "packageId": self.package_id,
            "packageDirectoryName": self.package_directory_name,
            "manifestSha256": self.manifest_sha256,
            "declaredArtifactSetSha256": self.declared_artifact_set_sha256,
            "publishedTreeSha256": self.published_tree_sha256,
            "contractVersion": self.contract_version,
            "counts": self.counts.to_dict(),
            "validation": self.validation.to_dict(),
            "readyForCtvReview": self.ready_for_ctv_review,
        }


def _artifact_limit(kind: str) -> int:
    if kind == "input-pdf":
        return MAX_INPUT_PDF_BYTES
    if kind in {"roster", "evidence"}:
        return MAX_ROSTER_OR_EVIDENCE_BYTES
    return MAX_JSON_BYTES


def _expectation(plan: PackageBuildPlan, manifest_sha256: str) -> V2ValidationExpectation:
    return V2ValidationExpectation(
        observation_id=plan.observation_id,
        proposal_digest=plan.proposal_digest,
        expected_manifest_sha256=manifest_sha256,
    )


def _open_staging_reader(staging: StagingTransaction, code: str):
    reader, failure = staging.open_reader()
    if reader is None or failure is not None:
        raise PackageWriterError(code)
    return reader


def _close_staging_reader(reader, code: str) -> None:
    try:
        reader.close()
    except Exception:
        raise PackageWriterError(code) from None


def _require_valid(result: ContentValidationV2, code: str) -> ContentValidationV2:
    if (
        type(result) is not ContentValidationV2
        or result.report.outcome != "valid"
        or result.report.errors
        or any(not check.passed for check in result.report.checks)
    ):
        raise PackageWriterError(code)
    return result


def _tree_limits(plan: PackageBuildPlan) -> tuple[set[str], dict[str, int]]:
    limits = {recipe.path: _artifact_limit(recipe.kind) for recipe in plan.recipes}
    limits["case-manifest.json"] = MAX_JSON_BYTES
    limits["validation-report.json"] = MAX_JSON_BYTES
    return set(limits), limits


def _snapshot_complete_tree(
    reader,
    plan: PackageBuildPlan,
    failure_code: str,
) -> PackageTreeSnapshot:
    required, limits = _tree_limits(plan)
    tree, failure = reader.snapshot_tree(
        required,
        max_bytes_by_path=limits,
        max_total_bytes=MAX_PACKAGE_BYTES,
    )
    if tree is None or failure is not None:
        raise PackageWriterError(failure_code)
    return tree


def _build_plan(observation, inspection, approved) -> PackageBuildPlan:
    try:
        return create_build_plan(observation, inspection, approved)
    except PackageBuildError:
        raise
    except Exception:
        raise PackageWriterError("package-build-failed") from None


def _content_validation(reader, observation, expectation) -> ContentValidationV2:
    try:
        result = validate_v2_content_reader(reader, observation, expectation)
    except PackageWriterError:
        raise
    except Exception:
        raise PackageWriterError("package-content-validation-failed") from None
    return _require_valid(result, "package-content-validation-failed")


def _publication_validation(reader, observation, expectation) -> ContentValidationV2:
    try:
        result = validate_v2_publication_reader(reader, observation, expectation)
    except PackageWriterError:
        raise
    except Exception:
        raise PackageWriterError("package-publication-validation-failed") from None
    result = _require_valid(result, "package-publication-validation-failed")
    if (
        not result.report.checks
        or result.report.checks[-1].code != "validation-report-consistent"
    ):
        raise PackageWriterError("package-publication-validation-failed")
    return result


def prepare_package(
    observation: InventoryObservation,
    inspection,
    approved,
    output: OutputParent,
) -> PackagePreparationResult:
    """Build, validate, finalize, and atomically publish one v2 package."""
    plan = _build_plan(observation, inspection, approved)
    output.require_final_absent(plan.identity.final_directory)

    with output.create_staging() as staging:
        receipts: list[ArtifactReceipt] = []
        try:
            for rendered in iter_rendered_artifacts(plan, observation):
                written = staging.write_bytes(rendered.path, rendered.content)
                receipts.append(
                    ArtifactReceipt(
                        artifact_id=rendered.artifact_id,
                        kind=rendered.kind,
                        path=rendered.path,
                        source_ids=rendered.source_ids,
                        size=written.size,
                        sha256=written.sha256,
                    )
                )
        except (PackageBuildError, PackageTransactionError):
            raise
        except Exception:
            raise PackageWriterError("package-build-failed") from None

        try:
            manifest_bytes = build_manifest_bytes(plan, tuple(receipts))
        except PackageBuildError:
            raise
        except Exception:
            raise PackageWriterError("package-build-failed") from None
        manifest_written = staging.write_bytes(
            "case-manifest.json", manifest_bytes
        )
        expectation = _expectation(plan, manifest_written.sha256)

        content_reader = _open_staging_reader(
            staging, "package-content-validation-failed"
        )
        try:
            content = _content_validation(
                content_reader, observation, expectation
            )
        finally:
            _close_staging_reader(
                content_reader, "package-content-validation-failed"
            )
        if content.manifest_sha256 != manifest_written.sha256:
            raise PackageWriterError("package-content-validation-failed")

        try:
            receipt_bytes = canonical_v2_receipt_bytes(content)
        except Exception:
            raise PackageWriterError("package-receipt-write-failed") from None
        staging.write_bytes("validation-report.json", receipt_bytes)

        publication_reader = _open_staging_reader(
            staging, "package-publication-validation-failed"
        )
        try:
            publication = _publication_validation(
                publication_reader, observation, expectation
            )
            validated_tree = _snapshot_complete_tree(
                publication_reader,
                plan,
                "package-publication-validation-failed",
            )
        finally:
            _close_staging_reader(
                publication_reader, "package-publication-validation-failed"
            )

        token = observation.finalize_for_publication()
        if token.observation_id != plan.observation_id:
            raise PackageWriterError("package-source-finalization-failed")

        final_reader = _open_staging_reader(staging, "package-staging-changed")
        try:
            final_tree = _snapshot_complete_tree(
                final_reader, plan, "package-staging-changed"
            )
        finally:
            _close_staging_reader(final_reader, "package-staging-changed")
        if final_tree != validated_tree:
            raise PackageWriterError("package-staging-changed")

        staging.publish(plan.identity.final_directory)

    assignments = plan.assignments.document
    result = PackagePreparationResult(
        package_id=plan.identity.package_id,
        package_directory_name=plan.identity.final_directory,
        manifest_sha256=publication.manifest_sha256,
        declared_artifact_set_sha256=publication.declared_artifact_set_sha256,
        published_tree_sha256=final_tree.tree_sha256,
        contract_version=plan.schema_version,
        counts=PackagePreparationCounts(
            sources=len(plan.sources),
            participants=len(assignments.participants),
            pdf_pages=len(plan.pdf_pages),
            evidence_artifacts=sum(
                recipe.kind == "evidence" for recipe in plan.recipes
            ),
            assignments=len(assignments.units),
            exclusions=len(assignments.exclusions),
        ),
        validation=PackagePreparationValidation(
            outcome=publication.report.outcome,
            check_codes=tuple(check.code for check in publication.report.checks),
            warning_codes=tuple(publication.report.warnings),
        ),
        ready_for_ctv_review=True,
    )
    return result
