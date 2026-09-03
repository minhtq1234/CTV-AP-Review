from compare_values import LOW_CONF
from field_escalation import (
    best_read,
    merge_sources,
    judge,
    pages_to_reread,
    plan,
    weak_fields,
)


def S(doc_id, page, value, confidence, bbox=True):
    return {
        "docId": doc_id, "page": page, "value": value,
        "bbox": {"x": 1, "y": 2, "width": 3, "height": 4} if bbox else None,
        "confidence": confidence,
    }


def F(key, sources):
    return {"key": key, "label": key, "expected": "", "sources": sources}


# --- best_read --------------------------------------------------------------

def test_best_read_is_empty_when_nothing_was_read():
    # The dominant February shape: located everywhere, readable nowhere.
    assert best_read(F("phi", [S("contract-0", 1, "", 0.0)])) == ("", None)

def test_best_read_ignores_empty_sources_entirely():
    f = F("cccd", [S("contract-0", 0, "", 0.0), S("bbnt-0", 1, "001100000051", 0.91)])
    assert best_read(f) == ("001100000051", 0.91)

def test_best_read_picks_the_most_confident_not_the_first():
    # A field read on several documents should be judged on its best evidence,
    # not on whichever source happened to sort first.
    f = F("hoten", [S("contract-0", 0, "NujI Van", 0.10),
                    S("bbnt-0", 1, "Cao Thị Mỹ Duyên", 0.95)])
    assert best_read(f) == ("Cao Thị Mỹ Duyên", 0.95)

def test_best_read_handles_a_field_with_no_sources_at_all():
    assert best_read(F("phi", [])) == ("", None)
    assert best_read({"key": "phi"}) == ("", None)


# --- judge ------------------------------------------------------------------

def test_a_confident_read_is_not_weak():
    v = judge(F("cccd", [S("contract-0", 0, "001100000051", 0.96)]))
    assert not v.weak and v.reason == ""

def test_an_unread_field_is_weak_as_unread():
    v = judge(F("phi", [S("contract-0", 1, "", 0.0)]))
    assert v.weak and v.reason == "unread"

def test_a_read_below_the_threshold_is_weak_as_low_confidence():
    # The real February/July garbage reads sat at 0.00-0.16.
    v = judge(F("cccd", [S("contract-0", 0, "0033000011", 0.16)]))
    assert v.weak and v.reason == "low-confidence"
    assert v.value == "0033000011"

def test_the_threshold_itself_counts_as_usable():
    assert not judge(F("cccd", [S("contract-0", 0, "x", LOW_CONF)])).weak
    assert judge(F("cccd", [S("contract-0", 0, "x", LOW_CONF - 0.01)])).weak

def test_a_missing_confidence_does_not_make_a_read_weak():
    # Absent confidence is unknown, not bad; only a value below the threshold
    # is treated as unusable, so a reader that reports no confidence is not
    # escalated on every field forever.
    v = judge({"key": "mst", "sources": [{"docId": "d", "page": 0, "value": "123"}]})
    assert not v.weak

def test_the_threshold_is_overridable():
    f = F("cccd", [S("contract-0", 0, "x", 0.8)])
    assert not judge(f).weak
    assert judge(f, low_conf=0.9).weak


# --- which pages to re-read -------------------------------------------------

def test_only_weak_fields_contribute_pages():
    fields = [
        F("cccd", [S("contract-0", 0, "001100000051", 0.96)]),   # fine
        F("phi",  [S("contract-0", 1, "", 0.0)]),                # weak
    ]
    assert pages_to_reread(fields) == {("contract-0", 1)}

def test_a_weak_field_contributes_every_page_it_is_located_on():
    fields = [F("phi", [S("contract-0", 1, "", 0.0), S("appendix-0", 0, "", 0.0)])]
    assert pages_to_reread(fields) == {("contract-0", 1), ("appendix-0", 0)}

def test_pages_are_deduplicated_across_fields():
    # Six fields on one contract page must cost one re-read, not six.
    fields = [F(k, [S("contract-0", 0, "", 0.0)])
              for k in ("hoten", "cccd", "mst", "tk", "ngaysinh", "phi")]
    assert pages_to_reread(fields) == {("contract-0", 0)}

def test_a_weak_but_unlocated_field_contributes_no_page():
    # Nowhere to aim a re-read, so escalating it would be a blind rescan.
    assert pages_to_reread([F("phi", [])]) == set()

def test_a_source_without_a_docid_is_skipped():
    assert pages_to_reread([F("phi", [S("", 0, "", 0.0)])]) == set()


# --- the whole plan ---------------------------------------------------------

def test_a_fully_read_packet_needs_no_second_read():
    fields = [F("cccd", [S("contract-0", 0, "001100000051", 0.96)]),
              F("phi",  [S("contract-0", 1, "8.888.889", 0.84)])]
    p = plan(fields)
    assert p.weak == ()
    assert p.pages == ()
    assert not p.worth_calling
    assert "no second read needed" in p.note()

def test_the_february_shape_escalates_one_page_for_all_six_fields():
    # All six located on the same contract page, none readable: one call.
    fields = [F(k, [S("contract-0", 1, "", 0.0)])
              for k in ("hoten", "cccd", "mst", "tk", "ngaysinh", "phi")]
    p = plan(fields)
    assert len(p.weak) == 6
    assert p.pages == (("contract-0", 1),)
    assert p.worth_calling

def test_pages_come_out_sorted_so_the_plan_is_deterministic():
    fields = [F("phi", [S("contract-0", 2, "", 0.0), S("appendix-0", 1, "", 0.0),
                        S("contract-0", 0, "", 0.0)])]
    assert plan(fields).pages == (("appendix-0", 1), ("contract-0", 0), ("contract-0", 2))

def test_the_note_says_what_the_calls_would_buy():
    fields = [F("phi", [S("contract-0", 1, "", 0.0)]),
              F("cccd", [S("contract-0", 1, "0033000011", 0.16)])]
    note = plan(fields).note()
    assert "phi (unread)" in note
    assert "cccd (low-confidence)" in note
    assert "1 page(s)" in note

def test_the_note_distinguishes_weak_from_unlocated():
    p = plan([F("phi", [])])
    assert not p.worth_calling
    assert "nothing to re-read" in p.note()


# --- merging a re-read back in ----------------------------------------------

def test_merge_replaces_only_the_escalated_pages_source():
    local = [F("phi", [S("contract-0", 1, "", 0.0)])]
    idp   = [F("phi", [S("contract-0", 1, "8.888.889", 0.93)])]
    out = merge_sources(local, idp, {("contract-0", 1)})
    assert [(s["value"], s["confidence"]) for s in out[0]["sources"]] == [("8.888.889", 0.93)]

def test_merge_does_not_union_a_local_garbage_read_with_a_good_one():
    # Unioning would leave two readable copies disagreeing on the same page,
    # which _compare_reads treats as worst-wins -- turning a field the
    # escalation just fixed into a false mismatch.
    local = [F("cccd", [S("contract-0", 0, "0033000011", 0.16)])]
    idp   = [F("cccd", [S("contract-0", 0, "001100000091", 0.95)])]
    out = merge_sources(local, idp, {("contract-0", 0)})
    assert [s["value"] for s in out[0]["sources"]] == ["001100000091"]

def test_merge_keeps_a_confident_read_on_a_page_that_was_not_escalated():
    local = [F("cccd", [S("bbnt-0", 1, "001100000051", 0.91),
                        S("contract-0", 0, "", 0.0)])]
    idp   = [F("cccd", [S("contract-0", 0, "001100000051", 0.94)])]
    out = merge_sources(local, idp, {("contract-0", 0)})
    vals = sorted((s["docId"], s["value"]) for s in out[0]["sources"])
    assert vals == [("bbnt-0", "001100000051"), ("contract-0", "001100000051")]

def test_merge_leaves_untouched_fields_alone():
    local = [F("mst", [S("contract-0", 0, "001100000051", 0.96)])]
    out = merge_sources(local, [], {("contract-0", 9)})
    assert out[0]["sources"] == local[0]["sources"]

def test_merge_drops_an_escalated_page_that_the_reader_could_not_read():
    # IDP returned nothing for the page: the old unusable source goes, and the
    # field is left with no source there rather than a stale blank.
    local = [F("phi", [S("contract-0", 1, "", 0.0)])]
    out = merge_sources(local, [F("phi", [])], {("contract-0", 1)})
    assert out[0]["sources"] == []

def test_merge_preserves_field_metadata():
    local = [{"key": "phi", "label": "Phí dịch vụ", "expected": "8888889",
              "sources": [S("contract-0", 1, "", 0.0)]}]
    out = merge_sources(local, [F("phi", [S("contract-0", 1, "8.888.889", 0.9)])],
                        {("contract-0", 1)})
    assert out[0]["label"] == "Phí dịch vụ" and out[0]["expected"] == "8888889"

def test_merge_does_not_mutate_its_input():
    local = [F("phi", [S("contract-0", 1, "", 0.0)])]
    before = [dict(s) for s in local[0]["sources"]]
    merge_sources(local, [F("phi", [S("contract-0", 1, "9.999.999", 0.9)])],
                  {("contract-0", 1)})
    assert local[0]["sources"] == before
