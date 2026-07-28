from dataclasses import replace
import json
from pathlib import Path

import pytest

from cccd_spike import (
    InvalidSpikeInput,
    SpikeMetrics,
    SpikeReport,
    _load_ground_truth,
    decide,
    main,
    run_spike,
)
import cccd_spike as spike
from cccd_ocr import CccdImageOcr
from cccd_workbook import Anchor, EmbeddedDrawing, ExtractionIssue, ExtractionResult


def metric_fixture(**changes) -> SpikeMetrics:
    metrics = SpikeMetrics(
        expected_mappable_identities=100,
        supported_drawing_instances=200,
        extracted_drawings=200,
        proposed_pairs=100,
        false_pairs=0,
        exact_matches=87,
        false_exact_matches=0,
        unique_name_suggestions=10,
        manual_search=3,
        extraction_rate=1.0,
        exact_rate=.87,
        assisted_rate=.97,
        manual_search_rate=.03,
    )
    return replace(metrics, **changes)


def test_passing_metrics_proceed():
    metrics = metric_fixture(
        extraction_rate=1.0,
        false_pairs=0,
        false_exact_matches=0,
        exact_rate=.87,
        assisted_rate=.97,
        manual_search_rate=.03,
    )

    assert decide(metrics, iteration=1) == "proceed"


def test_threshold_boundaries_are_inclusive():
    metrics = metric_fixture(
        extraction_rate=1.0,
        exact_rate=.85,
        assisted_rate=.95,
        manual_search_rate=.05,
    )

    assert decide(metrics, iteration=1) == "proceed"


@pytest.mark.parametrize(("field", "value"), [
    ("extraction_rate", .999999),
    ("exact_rate", .849999),
    ("assisted_rate", .949999),
    ("manual_search_rate", .050001),
])
def test_each_coverage_threshold_failure_requests_revision(field, value):
    assert decide(metric_fixture(**{field: value}), iteration=1) == "revise"


def test_first_failed_safe_run_requests_one_revision():
    metrics = metric_fixture(
        extraction_rate=1.0,
        false_pairs=0,
        false_exact_matches=0,
        exact_rate=.80,
        assisted_rate=.96,
        manual_search_rate=.04,
    )

    assert decide(metrics, iteration=1) == "revise"
    assert decide(metrics, iteration=2) == "stop"


def test_any_false_auto_match_stops_even_on_iteration_one():
    metrics = metric_fixture(false_exact_matches=1)

    assert decide(metrics, iteration=1) == "stop"


def test_any_false_pair_stops_even_on_iteration_one():
    metrics = metric_fixture(false_pairs=1)

    assert decide(metrics, iteration=1) == "stop"


@pytest.mark.parametrize("iteration", [0, 3])
def test_decision_rejects_iterations_outside_one_revision_rule(iteration):
    with pytest.raises(InvalidSpikeInput, match="iteration"):
        decide(metric_fixture(), iteration=iteration)


def write_truth(tmp_path, cards):
    path = tmp_path / "private-ground-truth.json"
    path.write_text(json.dumps({"cards": cards}), encoding="utf-8")
    return path


def truth_card(front, back, cccd):
    return {
        "frontDrawingId": front,
        "backDrawingId": back,
        "rosterCccd": cccd,
    }


@pytest.mark.parametrize("cards", [
    [
        truth_card("drawing-001", "drawing-002", "000000000001"),
        truth_card("drawing-001", "drawing-003", "000000000002"),
    ],
    [truth_card("drawing-001", "drawing-001", "000000000001")],
])
def test_ground_truth_rejects_duplicate_drawing_ids(tmp_path, cards):
    path = write_truth(tmp_path, cards)

    with pytest.raises(InvalidSpikeInput, match="duplicate drawing"):
        _load_ground_truth(
            str(path),
            known_drawing_ids={"drawing-001", "drawing-002", "drawing-003"},
            required_audit_ids=set(),
        )


def test_ground_truth_rejects_unknown_drawing_ids(tmp_path):
    path = write_truth(
        tmp_path,
        [truth_card("drawing-001", "drawing-unknown", "000000000001")],
    )

    with pytest.raises(InvalidSpikeInput, match="unknown drawing"):
        _load_ground_truth(
            str(path),
            known_drawing_ids={"drawing-001", "drawing-002"},
            required_audit_ids=set(),
        )


def test_ground_truth_rejects_duplicate_truth_cccds(tmp_path):
    path = write_truth(tmp_path, [
        truth_card("drawing-001", "drawing-002", "000000000001"),
        truth_card("drawing-003", "drawing-004", "000000000001"),
    ])

    with pytest.raises(InvalidSpikeInput, match="duplicate truth CCCD"):
        _load_ground_truth(
            str(path),
            known_drawing_ids={
                "drawing-001", "drawing-002", "drawing-003", "drawing-004",
            },
            required_audit_ids=set(),
        )


@pytest.mark.parametrize("value", ["000000001", "00000000000A", 1, None])
def test_ground_truth_rejects_non_12_digit_truth_values(tmp_path, value):
    path = write_truth(
        tmp_path,
        [truth_card("drawing-001", "drawing-002", value)],
    )

    with pytest.raises(InvalidSpikeInput, match="12-digit"):
        _load_ground_truth(
            str(path),
            known_drawing_ids={"drawing-001", "drawing-002"},
            required_audit_ids=set(),
        )


def test_ground_truth_rejects_missing_audit_coverage(tmp_path):
    path = write_truth(
        tmp_path,
        [truth_card("drawing-001", "drawing-002", "000000000001")],
    )

    with pytest.raises(InvalidSpikeInput, match="missing audit coverage"):
        _load_ground_truth(
            str(path),
            known_drawing_ids={"drawing-001", "drawing-002", "drawing-003"},
            required_audit_ids={"drawing-001", "drawing-003"},
        )


def synthetic_drawing(drawing_id, row, column):
    return EmbeddedDrawing(
        id=drawing_id,
        anchor=Anchor("Synthetic private sheet", row, column, row + 10, column + 5),
        media_type="image/png",
        extension="png",
        width=100,
        height=60,
        sha256=drawing_id[-1] * 64,
        stored_path=f"/private/synthetic/{drawing_id}.png",
    )


def setup_synthetic_run(
    tmp_path,
    monkeypatch,
    *,
    truth_cards=None,
    extra_roster_rows=(),
):
    workbook = tmp_path / "private-workbook.xlsx"
    roster = tmp_path / "private-roster.xlsx"
    workbook.write_bytes(b"synthetic")
    roster.write_bytes(b"synthetic")
    output = tmp_path / "report"

    drawings = [
        synthetic_drawing("drawing-001", 0, 0),
        synthetic_drawing("drawing-002", 0, 6),
        synthetic_drawing("drawing-003", 20, 0),
        synthetic_drawing("drawing-004", 20, 6),
    ]
    ocr_by_id = {
        "drawing-001": CccdImageOcr(
            "front", .99, "000000000001", .99, "Synthetic Alpha", .99,
            {"x": 1, "y": 1, "width": 10, "height": 5},
        ),
        "drawing-002": CccdImageOcr(
            "back", .99, "", 0, "", 0, None,
        ),
        "drawing-003": CccdImageOcr(
            "front", .99, "", 0, "Nguyen Synthetic", .99, None,
        ),
        "drawing-004": CccdImageOcr(
            "back", .99, "", 0, "", 0, None,
        ),
    }
    extraction_dirs = []

    def fake_extract(_workbook_path, extraction_dir):
        extraction_dirs.append(extraction_dir)
        assert str(output) in extraction_dir
        return ExtractionResult(4, drawings, [])

    monkeypatch.setattr(spike, "extract_drawings", fake_extract)
    monkeypatch.setattr(
        spike, "analyze_drawing", lambda drawing: ocr_by_id[drawing.id],
    )
    monkeypatch.setattr(
        spike.pipeline, "load_roster_rows", lambda _path: [["private raw row"]],
    )
    roster_rows = [
        {"name": "Synthetic Alpha", "cccd": "000000000001"},
        {"name": "Nguyen Synthetic", "cccd": "000000000002"},
        *extra_roster_rows,
    ]
    monkeypatch.setattr(
        spike.pipeline, "all_roster_rows", lambda _rows: roster_rows,
    )

    truth = truth_cards or [
        truth_card("drawing-001", "drawing-002", "000000000001"),
        truth_card("drawing-003", "drawing-004", "000000000002"),
    ]
    ground_truth = write_truth(tmp_path, truth)
    return workbook, roster, ground_truth, output, extraction_dirs


def test_run_spike_orchestrates_and_uses_fixed_roster_denominator(
    tmp_path, monkeypatch,
):
    extra = ({"name": "Synthetic Missing", "cccd": "000000000003"},)
    workbook, roster, truth, output, extraction_dirs = setup_synthetic_run(
        tmp_path, monkeypatch, extra_roster_rows=extra,
    )

    report = run_spike(
        str(workbook), str(roster), str(truth), str(output), iteration=1,
    )

    assert report.metrics.expected_mappable_identities == 3
    assert report.metrics.supported_drawing_instances == 4
    assert report.metrics.extracted_drawings == 4
    assert report.metrics.proposed_pairs == 2
    assert report.metrics.exact_matches == 1
    assert report.metrics.unique_name_suggestions == 1
    assert report.metrics.manual_search == 1
    assert report.metrics.extraction_rate == 1.0
    assert report.metrics.exact_rate == pytest.approx(1 / 3)
    assert report.metrics.assisted_rate == pytest.approx(2 / 3)
    assert report.metrics.manual_search_rate == pytest.approx(1 / 3)
    assert report.decision == "revise"
    assert len(extraction_dirs) == 1
    assert not Path(extraction_dirs[0]).exists()


def test_unaccounted_extraction_issue_cannot_coexist_with_proceed(
    tmp_path, monkeypatch,
):
    workbook, roster, truth, output, _ = setup_synthetic_run(
        tmp_path, monkeypatch,
    )
    drawings = [
        synthetic_drawing("drawing-001", 0, 0),
        synthetic_drawing("drawing-002", 0, 6),
        synthetic_drawing("drawing-003", 20, 0),
        synthetic_drawing("drawing-004", 20, 6),
    ]
    original_analyze = spike.analyze_drawing
    second_exact = CccdImageOcr(
        "front", .99, "000000000002", .99, "Nguyen Synthetic", .99,
        {"x": 1, "y": 1, "width": 10, "height": 5},
    )
    monkeypatch.setattr(
        spike,
        "extract_drawings",
        lambda _path, _output: ExtractionResult(
            4,
            drawings,
            [ExtractionIssue("malformed-drawing", None)],
        ),
    )
    monkeypatch.setattr(
        spike,
        "analyze_drawing",
        lambda drawing: (
            second_exact
            if drawing.id == "drawing-003"
            else original_analyze(drawing)
        ),
    )

    with pytest.raises(InvalidSpikeInput, match="unaccounted extraction"):
        run_spike(
            str(workbook), str(roster), str(truth), str(output), iteration=1,
        )
    assert not (output / "cccd-spike-report.json").exists()


def test_incorrect_proposed_pair_and_exact_match_are_counted_and_stop(
    tmp_path, monkeypatch,
):
    crossed_truth = [
        truth_card("drawing-001", "drawing-004", "000000000002"),
        truth_card("drawing-003", "drawing-002", "000000000001"),
    ]
    workbook, roster, truth, output, _ = setup_synthetic_run(
        tmp_path, monkeypatch, truth_cards=crossed_truth,
    )

    report = run_spike(
        str(workbook), str(roster), str(truth), str(output), iteration=1,
    )

    assert report.metrics.false_pairs == 2
    assert report.metrics.false_exact_matches == 1
    assert report.decision == "stop"


def test_exact_match_against_a_truth_back_drawing_is_false(
    tmp_path, monkeypatch,
):
    reversed_truth_side = [
        truth_card("drawing-002", "drawing-001", "000000000001"),
        truth_card("drawing-003", "drawing-004", "000000000002"),
    ]
    workbook, roster, truth, output, _ = setup_synthetic_run(
        tmp_path, monkeypatch, truth_cards=reversed_truth_side,
    )

    report = run_spike(
        str(workbook), str(roster), str(truth), str(output), iteration=1,
    )

    assert report.metrics.false_exact_matches == 1
    assert report.decision == "stop"


def test_written_report_contains_only_aggregate_schema(tmp_path, monkeypatch):
    workbook, roster, truth, output, _ = setup_synthetic_run(
        tmp_path, monkeypatch,
    )

    report = run_spike(
        str(workbook), str(roster), str(truth), str(output), iteration=1,
    )

    raw = (output / "cccd-spike-report.json").read_text(encoding="utf-8")
    payload = json.loads(raw)
    assert report.metrics.exact_matches == 1
    assert "Nguyen" not in raw
    assert "000000000001" not in raw
    assert "drawing-001" not in raw
    assert "Synthetic private sheet" not in raw
    assert set(payload) == {"iteration", "decision", "metrics", "thresholds"}
    assert set(payload["metrics"]) == set(SpikeMetrics.__dataclass_fields__)
    assert set(payload["thresholds"]) == {
        "extraction_rate",
        "false_pairs",
        "false_exact_matches",
        "exact_rate",
        "assisted_rate",
        "manual_search_rate",
    }


def test_mid_write_failure_preserves_prior_report_and_removes_temp(
    tmp_path, monkeypatch,
):
    output = tmp_path / "report"
    output.mkdir()
    prior_report = SpikeReport(
        iteration=1,
        decision="proceed",
        metrics=metric_fixture(),
        thresholds=dict(spike.THRESHOLDS),
    )
    spike._write_report(prior_report, str(output))
    final_path = output / "cccd-spike-report.json"
    prior_raw = final_path.read_bytes()

    def fail_after_partial_write(_payload, destination, **_options):
        destination.write('{"forbidden-partial":')
        raise OSError("synthetic mid-write failure")

    monkeypatch.setattr(spike.json, "dump", fail_after_partial_write)

    with pytest.raises(OSError, match="synthetic mid-write failure"):
        spike._write_report(
            replace(prior_report, iteration=2, decision="stop"),
            str(output),
        )

    assert final_path.read_bytes() == prior_raw
    assert [path.name for path in output.iterdir()] == [
        "cccd-spike-report.json",
    ]


def test_report_atomically_replaces_final_path_instead_of_following_it(tmp_path):
    output = tmp_path / "report"
    output.mkdir()
    prior_target = tmp_path / "prior-valid-report.json"
    prior_target.write_text("prior valid aggregate report\n", encoding="utf-8")
    final_path = output / "cccd-spike-report.json"
    final_path.symlink_to(prior_target)
    report = SpikeReport(
        iteration=1,
        decision="proceed",
        metrics=metric_fixture(),
        thresholds=dict(spike.THRESHOLDS),
    )

    spike._write_report(report, str(output))

    assert not final_path.is_symlink()
    assert json.loads(final_path.read_text(encoding="utf-8"))["decision"] == "proceed"
    assert prior_target.read_text(encoding="utf-8") == "prior valid aggregate report\n"
    assert [path.name for path in output.iterdir()] == [
        "cccd-spike-report.json",
    ]


def test_duplicate_candidate_ids_surface_as_invalid_without_partial_report(
    tmp_path, monkeypatch,
):
    workbook, roster, truth, output, _ = setup_synthetic_run(
        tmp_path, monkeypatch,
    )
    real_pair_drawings = spike.pair_drawings

    def duplicate_candidates(images):
        candidate = real_pair_drawings(images)[0]
        return [candidate, candidate]

    monkeypatch.setattr(spike, "pair_drawings", duplicate_candidates)

    with pytest.raises(InvalidSpikeInput, match="duplicate candidate"):
        run_spike(
            str(workbook), str(roster), str(truth), str(output), iteration=1,
        )
    assert not (output / "cccd-spike-report.json").exists()


def test_zero_eligible_roster_denominator_is_invalid(tmp_path, monkeypatch):
    workbook, roster, truth, output, _ = setup_synthetic_run(
        tmp_path, monkeypatch,
    )
    monkeypatch.setattr(
        spike.pipeline,
        "all_roster_rows",
        lambda _rows: [{"name": "Legacy", "cccd": "123456789"}],
    )

    with pytest.raises(InvalidSpikeInput, match="eligible roster identity"):
        run_spike(
            str(workbook), str(roster), str(truth), str(output), iteration=1,
        )
    assert not (output / "cccd-spike-report.json").exists()


@pytest.mark.parametrize(("decision", "exit_code"), [
    ("proceed", 0),
    ("revise", 2),
    ("stop", 3),
])
def test_cli_prints_only_aggregate_decision_and_metrics(
    tmp_path, monkeypatch, capsys, decision, exit_code,
):
    secret_path = tmp_path / "secret-private-input.xlsx"
    argv = [
        "--workbook", str(secret_path),
        "--roster", str(secret_path),
        "--ground-truth", str(secret_path),
        "--output-dir", str(tmp_path / "output"),
        "--iteration", "1",
    ]
    monkeypatch.setattr(
        spike,
        "run_spike",
        lambda *_args, **_kwargs: SpikeReport(
            iteration=1,
            decision=decision,
            metrics=metric_fixture(),
            thresholds=dict(spike.THRESHOLDS),
        ),
    )

    result = main(argv)

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert result == exit_code
    assert set(payload) == {"decision", "metrics"}
    assert payload["decision"] == decision
    assert set(payload["metrics"]) == set(SpikeMetrics.__dataclass_fields__)
    assert "secret-private-input" not in captured.out
    assert captured.err == ""


def test_cli_returns_four_without_printing_private_invalid_input(
    tmp_path, monkeypatch, capsys,
):
    secret_path = tmp_path / "secret-Nguyen-000000000001.xlsx"
    monkeypatch.setattr(
        spike,
        "run_spike",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            InvalidSpikeInput(str(secret_path))
        ),
    )

    result = main([
        "--workbook", str(secret_path),
        "--roster", str(secret_path),
        "--ground-truth", str(secret_path),
        "--output-dir", str(tmp_path / "output"),
        "--iteration", "1",
    ])

    captured = capsys.readouterr()
    assert result == 4
    assert captured.out == ""
    assert captured.err == ""


def test_cli_missing_arguments_return_four(capsys):
    assert main([]) == 4
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
