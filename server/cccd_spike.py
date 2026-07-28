"""Local-only orchestration and aggregate reporting for the CCCD spike."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Literal

from cccd_matching import resolve_candidates
from cccd_ocr import analyze_drawing
from cccd_pairing import AnalyzedDrawing, CardCandidate, pair_drawings
from cccd_workbook import ExtractionResult, extract_drawings
import pipeline


detect_packets = pipeline.dp


Decision = Literal["proceed", "revise", "stop"]

THRESHOLDS: dict[str, float | int] = {
    "extraction_rate": 1.0,
    "false_pairs": 0,
    "false_exact_matches": 0,
    "exact_rate": .85,
    "assisted_rate": .95,
    "manual_search_rate": .05,
}


class InvalidSpikeInput(ValueError):
    """Raised when private inputs or audit coverage are incomplete or invalid."""


@dataclass(frozen=True)
class TruthCard:
    front_drawing_id: str
    back_drawing_id: str
    roster_cccd: str


@dataclass(frozen=True)
class SpikeMetrics:
    expected_mappable_identities: int
    supported_drawing_instances: int
    extracted_drawings: int
    proposed_pairs: int
    false_pairs: int
    exact_matches: int
    false_exact_matches: int
    unique_name_suggestions: int
    manual_search: int
    extraction_rate: float
    exact_rate: float
    assisted_rate: float
    manual_search_rate: float


@dataclass(frozen=True)
class SpikeReport:
    iteration: int
    decision: Decision
    metrics: SpikeMetrics
    thresholds: dict[str, float | int]


def _load_ground_truth(
    path: str,
    *,
    known_drawing_ids: set[str],
    required_audit_ids: set[str],
) -> list[TruthCard]:
    """Load the private audit file and fail closed on incomplete coverage."""
    try:
        with open(path, encoding="utf-8") as source:
            raw = json.load(source)
    except (OSError, json.JSONDecodeError, UnicodeError) as error:
        raise InvalidSpikeInput("invalid private ground truth") from error

    if not isinstance(raw, dict) or set(raw) != {"cards"}:
        raise InvalidSpikeInput("invalid private ground-truth schema")
    raw_cards = raw["cards"]
    if not isinstance(raw_cards, list):
        raise InvalidSpikeInput("invalid private ground-truth schema")

    cards = []
    seen_drawings: set[str] = set()
    seen_cccds: set[str] = set()
    required_fields = {"frontDrawingId", "backDrawingId", "rosterCccd"}
    for raw_card in raw_cards:
        if not isinstance(raw_card, dict) or set(raw_card) != required_fields:
            raise InvalidSpikeInput("invalid private ground-truth schema")
        front = raw_card["frontDrawingId"]
        back = raw_card["backDrawingId"]
        cccd = raw_card["rosterCccd"]
        if not isinstance(front, str) or not front:
            raise InvalidSpikeInput("invalid drawing ID")
        if not isinstance(back, str) or not back:
            raise InvalidSpikeInput("invalid drawing ID")
        if front == back or front in seen_drawings or back in seen_drawings:
            raise InvalidSpikeInput("duplicate drawing ID")
        if front not in known_drawing_ids or back not in known_drawing_ids:
            raise InvalidSpikeInput("unknown drawing ID")
        if not isinstance(cccd, str) or len(cccd) != 12 or not cccd.isdigit():
            raise InvalidSpikeInput("truth CCCD must be exactly 12-digit")
        if cccd in seen_cccds:
            raise InvalidSpikeInput("duplicate truth CCCD")
        cards.append(TruthCard(front, back, cccd))
        seen_drawings.update((front, back))
        seen_cccds.add(cccd)

    if not required_audit_ids <= seen_drawings:
        raise InvalidSpikeInput("missing audit coverage")
    return cards


def decide(metrics: SpikeMetrics, iteration: int) -> Decision:
    """Apply the safety gates and the single permitted revision."""
    if iteration not in {1, 2}:
        raise InvalidSpikeInput("iteration must be 1 or 2")
    if metrics.false_pairs > 0 or metrics.false_exact_matches > 0:
        return "stop"
    passes = (
        metrics.extraction_rate >= THRESHOLDS["extraction_rate"]
        and metrics.exact_rate >= THRESHOLDS["exact_rate"]
        and metrics.assisted_rate >= THRESHOLDS["assisted_rate"]
        and metrics.manual_search_rate <= THRESHOLDS["manual_search_rate"]
    )
    if passes:
        return "proceed"
    return "revise" if iteration == 1 else "stop"


def run_spike(
    workbook_path: str,
    roster_path: str,
    ground_truth_path: str,
    output_dir: str,
    iteration: int,
) -> SpikeReport:
    """Run the local spike and persist exactly one aggregate JSON report."""
    decide(_empty_metrics(), iteration)
    _validate_private_input_paths(workbook_path, roster_path, ground_truth_path)
    os.makedirs(output_dir, exist_ok=True)

    with tempfile.TemporaryDirectory(
        prefix=".cccd-extraction-",
        dir=output_dir,
    ) as extraction_dir:
        try:
            extraction = extract_drawings(workbook_path, extraction_dir)
            _validate_extraction(extraction)
            analyzed = [
                AnalyzedDrawing(drawing, analyze_drawing(drawing))
                for drawing in extraction.drawings
            ]
            candidates = pair_drawings(analyzed)
            _validate_candidates(candidates, {drawing.id for drawing in extraction.drawings})
            roster_rows = pipeline.all_roster_rows(
                detect_packets._roster_rows(roster_path)
            )
            resolution_result = resolve_candidates(candidates, roster_rows)
        except InvalidSpikeInput:
            raise
        except (OSError, ValueError, TypeError, KeyError) as error:
            raise InvalidSpikeInput(str(error)) from error

        candidate_by_id = {candidate.id: candidate for candidate in candidates}
        resolution_by_id = {
            resolution.candidate_id: resolution
            for resolution in resolution_result.resolutions
        }
        if (
            len(resolution_by_id) != len(resolution_result.resolutions)
            or set(resolution_by_id) != set(candidate_by_id)
        ):
            raise InvalidSpikeInput("invalid resolution coverage")

        proposed = [
            candidate
            for candidate in candidates
            if candidate.front is not None and candidate.back is not None
        ]
        exact = [
            resolution
            for resolution in resolution_result.resolutions
            if resolution.state == "exact"
        ]
        required_audit_ids = {
            drawing.drawing.id
            for candidate in proposed
            for drawing in (candidate.front, candidate.back)
            if drawing is not None
        }
        required_audit_ids.update(
            candidate_by_id[resolution.candidate_id].front.drawing.id
            for resolution in exact
        )
        truth_cards = _load_ground_truth(
            ground_truth_path,
            known_drawing_ids={drawing.id for drawing in extraction.drawings},
            required_audit_ids=required_audit_ids,
        )

        metrics = _evaluate(
            extraction,
            candidates,
            roster_rows,
            resolution_result.expected_mappable_identities,
            resolution_result.resolutions,
            truth_cards,
        )

    report = SpikeReport(
        iteration=iteration,
        decision=decide(metrics, iteration),
        metrics=metrics,
        thresholds=dict(THRESHOLDS),
    )
    _write_report(report, output_dir)
    return report


def _empty_metrics() -> SpikeMetrics:
    return SpikeMetrics(0, 0, 0, 0, 0, 0, 0, 0, 0, 0.0, 0.0, 0.0, 0.0)


def _validate_private_input_paths(
    workbook_path: str,
    roster_path: str,
    ground_truth_path: str,
) -> None:
    for path in (workbook_path, roster_path, ground_truth_path):
        if not path or not os.path.isfile(path):
            raise InvalidSpikeInput("missing private input")
    repository = Path(__file__).resolve().parent.parent
    try:
        Path(ground_truth_path).resolve().relative_to(repository)
    except ValueError:
        return
    raise InvalidSpikeInput("private ground truth must live outside the repository")


def _validate_extraction(extraction: ExtractionResult) -> None:
    drawing_ids = [drawing.id for drawing in extraction.drawings]
    if len(drawing_ids) != len(set(drawing_ids)):
        raise InvalidSpikeInput("duplicate extracted drawing ID")
    issue_ids = [issue.drawing_id for issue in extraction.issues]
    if any(drawing_id is None for drawing_id in issue_ids):
        raise InvalidSpikeInput("unaccounted extraction issue")
    if (
        len(issue_ids) != len(set(issue_ids))
        or not set(drawing_ids).isdisjoint(issue_ids)
        or len(drawing_ids) + len(issue_ids) != extraction.drawing_instances
    ):
        raise InvalidSpikeInput("invalid extraction issue coverage")
    if (
        extraction.drawing_instances < 0
        or len(extraction.drawings) > extraction.drawing_instances
    ):
        raise InvalidSpikeInput("invalid extraction counts")


def _validate_candidates(
    candidates: list[CardCandidate],
    known_drawing_ids: set[str],
) -> None:
    candidate_ids = [candidate.id for candidate in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise InvalidSpikeInput("duplicate candidate ID")
    used_drawings = []
    for candidate in candidates:
        for analyzed, expected_side in (
            (candidate.front, "front"),
            (candidate.back, "back"),
        ):
            if analyzed is None:
                continue
            if analyzed.drawing.id not in known_drawing_ids:
                raise InvalidSpikeInput("unknown candidate drawing ID")
            if analyzed.ocr.side != expected_side:
                raise InvalidSpikeInput("invalid candidate side")
            used_drawings.append(analyzed.drawing.id)
    if len(used_drawings) != len(set(used_drawings)):
        raise InvalidSpikeInput("duplicate candidate drawing ID")


def _evaluate(
    extraction,
    candidates,
    roster_rows,
    expected_mappable_identities,
    resolutions,
    truth_cards,
) -> SpikeMetrics:
    if expected_mappable_identities <= 0:
        raise InvalidSpikeInput("at least one eligible roster identity is required")
    proposed = [
        candidate
        for candidate in candidates
        if candidate.front is not None and candidate.back is not None
    ]
    true_pairs = {
        (card.front_drawing_id, card.back_drawing_id)
        for card in truth_cards
    }
    false_pairs = sum(
        (
            candidate.front.drawing.id,
            candidate.back.drawing.id,
        ) not in true_pairs
        for candidate in proposed
    )

    truth_by_front = {
        card.front_drawing_id: card
        for card in truth_cards
    }
    candidate_by_id = {candidate.id: candidate for candidate in candidates}
    roster_cccd_by_key = {
        f"roster-{index}": _digits(row.get("cccd", ""))
        for index, row in enumerate(roster_rows)
    }
    exact = [resolution for resolution in resolutions if resolution.state == "exact"]
    suggested = [
        resolution for resolution in resolutions if resolution.state == "suggested"
    ]
    false_exact_matches = 0
    for resolution in exact:
        candidate = candidate_by_id[resolution.candidate_id]
        if candidate.front is None:
            raise InvalidSpikeInput("exact resolution without a front drawing")
        truth = truth_by_front.get(candidate.front.drawing.id)
        resolved_cccd = roster_cccd_by_key.get(resolution.roster_key or "")
        if truth is None or resolved_cccd != truth.roster_cccd:
            false_exact_matches += 1

    exact_matches = len(exact)
    unique_name_suggestions = len(suggested)
    covered = exact_matches + unique_name_suggestions
    if covered > expected_mappable_identities:
        raise InvalidSpikeInput("placement counts exceed eligible roster denominator")
    manual_search = expected_mappable_identities - covered
    supported = extraction.drawing_instances
    extracted = len(extraction.drawings)
    return SpikeMetrics(
        expected_mappable_identities=expected_mappable_identities,
        supported_drawing_instances=supported,
        extracted_drawings=extracted,
        proposed_pairs=len(proposed),
        false_pairs=false_pairs,
        exact_matches=exact_matches,
        false_exact_matches=false_exact_matches,
        unique_name_suggestions=unique_name_suggestions,
        manual_search=manual_search,
        extraction_rate=extracted / supported if supported else 0.0,
        exact_rate=exact_matches / expected_mappable_identities,
        assisted_rate=covered / expected_mappable_identities,
        manual_search_rate=manual_search / expected_mappable_identities,
    )


def _digits(value: object) -> str:
    return "".join(character for character in str(value or "") if character.isdigit())


def _write_report(report: SpikeReport, output_dir: str) -> None:
    path = os.path.join(output_dir, "cccd-spike-report.json")
    descriptor, temporary_path = tempfile.mkstemp(
        dir=output_dir,
        prefix=".cccd-spike-report-",
        suffix=".tmp",
        text=True,
    )
    try:
        destination = os.fdopen(descriptor, "w", encoding="utf-8")
        descriptor = -1
        with destination:
            json.dump(asdict(report), destination, indent=2, sort_keys=True)
            destination.write("\n")
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary_path, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass


class _PrivateArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise InvalidSpikeInput("invalid command line")


def main(argv: list[str] | None = None) -> int:
    parser = _PrivateArgumentParser(
        description="Run the local-only CCCD mapping viability spike.",
    )
    parser.add_argument("--workbook", required=True)
    parser.add_argument("--roster", required=True)
    parser.add_argument("--ground-truth", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--iteration", required=True, type=int)
    try:
        args = parser.parse_args(argv)
        report = run_spike(
            args.workbook,
            args.roster,
            args.ground_truth,
            args.output_dir,
            args.iteration,
        )
    except Exception:
        return 4

    print(json.dumps({
        "decision": report.decision,
        "metrics": asdict(report.metrics),
    }, sort_keys=True))
    return {"proceed": 0, "revise": 2, "stop": 3}[report.decision]


if __name__ == "__main__":
    sys.exit(main())
