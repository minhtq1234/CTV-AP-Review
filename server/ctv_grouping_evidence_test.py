import pytest

from ctv_grouping_evidence import GroupingEvidence


def test_grouping_evidence_is_bounded_private_and_clearable():
    facts = GroupingEvidence(max_units=2, max_chars_per_unit=64, max_total_chars=96)
    facts.capture("evidence-0001", "pdf-page", 1, "Nguyễn Văn A 079123456789")

    assert facts.text_for("evidence-0001", "pdf-page", 1) == "NGUYEN VAN A 079123456789"
    assert facts.complete_for("evidence-0001", "pdf-page", 1) is True
    assert "Nguyễn" not in repr(facts)
    assert "079123456789" not in repr(facts)

    facts.clear()

    assert facts.text_for("evidence-0001", "pdf-page", 1) == ""
    assert facts.complete_for("evidence-0001", "pdf-page", 1) is False


def test_grouping_evidence_rejects_invalid_exact_builtin_types():
    facts = GroupingEvidence()

    for evidence_id, unit_kind, unit_index, private_text in (
        (1, "pdf-page", 1, "text"),
        ("evidence-0001", 1, 1, "text"),
        ("evidence-0001", "pdf-page", True, "text"),
        ("evidence-0001", "pdf-page", 1, b"text"),
    ):
        with pytest.raises(TypeError):
            facts.capture(evidence_id, unit_kind, unit_index, private_text)

    with pytest.raises(TypeError):
        facts.capture_source_duplicate("evidence-0001", 1)


def test_grouping_evidence_drops_an_overlong_unit_without_partial_text():
    facts = GroupingEvidence(max_chars_per_unit=8)
    facts.capture("evidence-0001", "pdf-page", 1, "Nguyễn Văn A")

    assert facts.text_for("evidence-0001", "pdf-page", 1) == ""
    assert facts.complete_for("evidence-0001", "pdf-page", 1) is False


def test_grouping_evidence_drops_a_unit_after_the_unit_count_cap():
    facts = GroupingEvidence(max_units=2)
    facts.capture("evidence-0001", "pdf-page", 1, "first")
    facts.capture("evidence-0001", "pdf-page", 2, "second")
    facts.capture("evidence-0001", "pdf-page", 3, "third")

    assert facts.text_for("evidence-0001", "pdf-page", 3) == ""
    assert facts.complete_for("evidence-0001", "pdf-page", 3) is False


def test_grouping_evidence_drops_a_unit_when_the_aggregate_cap_is_exhausted():
    facts = GroupingEvidence(max_total_chars=10)
    facts.capture("evidence-0001", "pdf-page", 1, "first")
    facts.capture("evidence-0001", "pdf-page", 2, "second")

    assert facts.text_for("evidence-0001", "pdf-page", 1) == "FIRST"
    assert facts.complete_for("evidence-0001", "pdf-page", 1) is True
    assert facts.text_for("evidence-0001", "pdf-page", 2) == ""
    assert facts.complete_for("evidence-0001", "pdf-page", 2) is False


def test_grouping_evidence_rejects_a_second_capture_for_the_same_key():
    facts = GroupingEvidence()
    facts.capture("evidence-0001", "pdf-page", 1, "first")

    with pytest.raises(ValueError):
        facts.capture("evidence-0001", "pdf-page", 1, "second")

    assert facts.text_for("evidence-0001", "pdf-page", 1) == "FIRST"


def test_grouping_evidence_retains_only_opaque_duplicate_group_ids():
    facts = GroupingEvidence()
    facts.capture_source_duplicate("evidence-0001", "duplicate-0007")

    assert facts.duplicate_group_for("evidence-0001") == "duplicate-0007"
    assert "duplicate-0007" not in repr(facts)

    with pytest.raises(ValueError):
        facts.capture_source_duplicate("evidence-0002", "duplicate-private")
