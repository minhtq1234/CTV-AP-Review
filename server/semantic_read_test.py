"""Tests for `semantic_read.locate_quote`. No model, no network, no key.

Every quote below crosses a line break, because that is the case the existing
per-line machinery cannot do at all and it is what a real clause looks like: on
12 real contracts a twelve-word quote spans a line 71.8% of the time.
"""
from __future__ import annotations

import semantic_read as sr


def word(text: str, x: int, y: int) -> dict:
    """A word in the shape the pipeline actually produces.

    Six keys and no `page` -- `ocr_extract.ocr_words` and
    `idp_words.parse_words` both build exactly this, and `scale_words` rebuilds
    it from exactly these, so an invented `page` key would be dropped in
    transit. Reading a page off a word is the defect
    `signature_anchors.find_anchors` exists to avoid.
    """
    return {"text": text, "x": x, "y": y, "w": len(text) * 8, "h": 12,
            "conf": 90.0}


def line(texts: list[str], y: int, x0: int = 10) -> list[dict]:
    out, x = [], x0
    for text in texts:
        out.append(word(text, x, y))
        x += len(text) * 8 + 6
    return out


#: Two lines of a payment clause, so a clause-length quote must span them.
CLAUSE = {
    0: line(["Thời", "hạn", "thanh", "toán", "là", "15"], 10)
       + line(["ngày", "kể", "từ", "ngày", "nghiệm", "thu"], 30),
}


class TestLocatesAClause:
    def test_a_quote_spanning_a_line_break_is_located(self):
        got = sr.locate_quote("là 15 ngày kể từ ngày", CLAUSE, 0)
        assert got is not None
        assert got["exact"] is True
        assert got["page"] == 0

    def test_the_box_encloses_both_lines_and_is_not_expanded(self):
        got = sr.locate_quote("là 15 ngày kể từ ngày", CLAUSE, 0)
        box = got["bbox"]
        # {x, y, width, height} -- every bbox in this codebase. A {w, h} box is
        # truthy and renders as a zero-size highlight: located-looking, useless.
        assert set(box) == {"x", "y", "width", "height"}
        # Spans the two lines, and no further: 10 -> 30 + 12.
        assert box["y"] == 10
        assert box["height"] == 32

    def test_a_newline_in_the_quote_does_not_stop_it(self):
        # The model is handed `_page_text`, which joins lines with "\n", so it
        # may quote the break back. Under `norm` alone this matched nothing.
        got = sr.locate_quote("là 15\nngày kể từ ngày", CLAUSE, 0)
        assert got is not None and got["exact"] is True

    def test_stripped_diacritics_cost_nothing(self):
        got = sr.locate_quote("la 15 ngay ke tu ngay", CLAUSE, 0)
        assert got is not None and got["exact"] is True

    def test_added_punctuation_costs_nothing(self):
        got = sr.locate_quote('"là 15 ngày, kể từ ngày."', CLAUSE, 0)
        assert got is not None and got["exact"] is True


class TestFuzzyFallback:
    def test_one_changed_character_still_locates(self):
        # Exact substring matching makes this 100% unlocatable, which is the
        # single largest risk to a model-supplied quote.
        got = sr.locate_quote("là 16 ngày kể từ ngày", CLAUSE, 0)
        assert got is not None
        assert got["exact"] is False
        assert got["ratio"] >= sr.MIN_RATIO

    def test_a_dropped_word_still_locates(self):
        got = sr.locate_quote("là 15 ngày từ ngày nghiệm", CLAUSE, 0)
        assert got is not None and got["exact"] is False

    def test_an_exact_hit_is_preferred_over_a_near_miss(self):
        got = sr.locate_quote("là 15 ngày kể từ ngày", CLAUSE, 0)
        assert got["exact"] is True and got["ratio"] == 1.0

    def test_unrelated_text_is_refused_rather_than_boxed(self):
        # A quote that locates but does not support its value is worse than an
        # unlocatable one: it puts a highlight on the page vouching for
        # something the page does not say.
        assert sr.locate_quote(
            "hai bên thống nhất chấm dứt hợp đồng trước hạn", CLAUSE, 0,
        ) is None

    def test_the_window_cannot_grow_to_swallow_a_paragraph(self):
        long_page = {0: line(["một"] * 40, 10) + line(["hai"] * 40, 30)}
        got = sr.locate_quote("một một một một một một", long_page, 0)
        assert got is not None
        # Six words wide, not eighty: a window free to grow would box the lot.
        assert got["bbox"]["height"] == 12


class TestRefusesWhatItCannotVouchFor:
    def test_a_short_quote_is_refused(self):
        # Below six words a quote lands on the wrong occurrence of itself
        # (7.2% at four words), so there is nothing to point at honestly.
        assert sr.locate_quote("15 ngày", CLAUSE, 0) is None
        assert len(sr.fold("15 ngày").split()) < sr.MIN_WORDS

    def test_an_empty_quote_is_refused(self):
        assert sr.locate_quote("", CLAUSE, 0) is None
        assert sr.locate_quote("   ", CLAUSE, 0) is None

    def test_a_quote_of_pure_punctuation_is_refused(self):
        assert sr.locate_quote('"""" ---- ....', CLAUSE, 0) is None

    def test_no_pages_locates_nothing(self):
        assert sr.locate_quote("là 15 ngày kể từ ngày", {}, 0) is None


class TestThePageIsAHintNotAContract:
    def test_a_wrong_claimed_page_still_locates(self):
        # At eight words or more a whole-document search lands on the wrong
        # occurrence 0% of the time, so honouring a model's page slip strictly
        # would lose a locatable quote for no accuracy gain.
        got = sr.locate_quote("là 15 ngày kể từ ngày", CLAUSE, 7)
        assert got is not None and got["page"] == 0

    def test_no_claimed_page_still_locates(self):
        got = sr.locate_quote("là 15 ngày kể từ ngày", CLAUSE, None)
        assert got is not None and got["page"] == 0

    def test_the_claimed_page_wins_a_tie(self):
        pages = {
            0: line(["Thời", "hạn", "thanh", "toán", "là", "15", "ngày"], 10),
            1: line(["Thời", "hạn", "thanh", "toán", "là", "15", "ngày"], 10),
        }
        assert sr.locate_quote("Thời hạn thanh toán là 15 ngày", pages, 1)["page"] == 1
        assert sr.locate_quote("Thời hạn thanh toán là 15 ngày", pages, 0)["page"] == 0


class TestFold:
    def test_it_folds_case_diacritics_punctuation_and_whitespace(self):
        assert sr.fold("Thời  HẠN, thanh-toán!") == "thoi han thanh toan"

    def test_punctuation_becomes_a_space_so_both_sides_agree(self):
        # Only one side may carry the hyphen. Deleting it would give
        # "thanhtoan" against the page's "thanh toan" and match nothing.
        assert sr.fold("thanh-toán") == sr.fold("thanh toán")
        pages = {0: line(["Thời", "hạn", "thanh", "toán", "là", "15", "ngày"], 10)}
        got = sr.locate_quote("Thời hạn thanh-toán là 15 ngày", pages, 0)
        assert got is not None and got["exact"] is True

    def test_a_token_folding_to_nothing_is_dropped_not_joined(self):
        # A table rule reads as a lone dash between two halves of a cell. Joined
        # in, it would leave a double space and stop an otherwise exact match.
        pages = {0: line(["là", "15", "-", "ngày", "kể", "từ", "ngày"], 10)}
        got = sr.locate_quote("là 15 ngày kể từ ngày", pages, 0)
        assert got is not None and got["exact"] is True


# --- the reader half ---------------------------------------------------------

class TestReadDocument:
    """`read_document` is the gate every reader answer passes through.

    The rule it enforces -- a value carries a verbatim quote or it is dropped --
    is the tool's whole premise: it points and a person decides, so a value
    with nothing to check it against converts a `?` the reviewer distrusts into
    a claim they cannot falsify.
    """

    def test_the_fake_returns_what_it_was_given(self):
        reader = sr.FakeReader({
            "term": sr.SemanticField(
                value="15 ngày", quote="trong vòng 15 ngày kể từ", page=2),
        })
        out = sr.read_document(
            reader, doc_kind="contract", pages_text=["", "", "..."],
            want=("term",))
        assert out["term"].value == "15 ngày"
        assert out["term"].page == 2

    def test_a_field_without_a_quote_is_dropped(self):
        reader = sr.FakeReader({
            "term": sr.SemanticField(value="15 ngày", quote="", page=1),
        })
        out = sr.read_document(reader, doc_kind="contract", pages_text=["a"],
                               want=("term",))
        assert "term" not in out

    def test_a_field_without_a_value_is_dropped(self):
        reader = sr.FakeReader({
            "term": sr.SemanticField(value="", quote="trong vòng 15 ngày", page=1),
        })
        assert sr.read_document(reader, doc_kind="contract", pages_text=["a"],
                                want=("term",)) == {}

    def test_a_field_the_caller_did_not_ask_for_is_dropped(self):
        # A model volunteers things, and an unrequested field would land in the
        # manifest with no criterion to validate it.
        reader = sr.FakeReader({
            "term": sr.SemanticField("15 ngày", "trong vòng 15", 1),
            "mood": sr.SemanticField("cheerful", "quite cheerful", 1),
        })
        out = sr.read_document(reader, doc_kind="contract", pages_text=["x"],
                               want=("term",))
        assert set(out) == {"term"}

    def test_a_reader_that_raises_yields_nothing_rather_than_failing(self):
        # OCR has already spent minutes by this point. Losing that because a
        # model timed out is a bad trade for cells that degrade to `pending`.
        class Boom:
            def read(self, **kwargs):
                raise RuntimeError("timeout")

        assert sr.read_document(Boom(), doc_kind="contract", pages_text=["x"],
                                want=("term",)) == {}

    def test_a_reader_that_returns_nonsense_yields_nothing(self):
        class Nonsense:
            def read(self, **kwargs):
                return ["not", "a", "dict"]

        assert sr.read_document(Nonsense(), doc_kind="contract",
                                pages_text=["x"], want=("term",)) == {}

    def test_a_value_that_is_not_a_SemanticField_is_dropped(self):
        # The real adapter parses JSON off a wire; a bare string arriving here
        # would otherwise reach the manifest with no quote and no page.
        class Loose:
            def read(self, **kwargs):
                return {"term": "15 ngày"}

        assert sr.read_document(Loose(), doc_kind="contract", pages_text=["x"],
                                want=("term",)) == {}

    def test_the_reader_is_told_what_it_was_asked(self):
        reader = sr.FakeReader({})
        sr.read_document(reader, doc_kind="bbnt", pages_text=["a", "b"],
                         want=("term", "account"))
        assert reader.calls == [
            {"doc_kind": "bbnt", "pages": 2, "want": ("term", "account")},
        ]


class TestLocateFields:
    def test_a_located_quote_gets_its_box_and_its_page(self):
        fields = {"term": sr.SemanticField("15 ngày", "là 15 ngày kể từ ngày", 0)}
        out = sr.locate_fields(fields, CLAUSE)
        assert out["term"].located is True
        assert out["term"].exact is True
        assert out["term"].bbox["height"] == 32

    def test_an_unlocatable_quote_is_KEPT_and_marked(self):
        """Not dropped, and this is the load-bearing decision in this module.

        The fraction of quotes that cannot be located is the gate the real
        adapter is judged by. Dropping them would make that number
        unmeasurable -- the approach would look perfect precisely when it was
        failing.
        """
        fields = {"term": sr.SemanticField(
            "15 ngày", "hoàn toàn không có nội dung nào như thế", 0)}
        out = sr.locate_fields(fields, CLAUSE)
        assert "term" in out
        assert out["term"].located is False
        assert out["term"].bbox is None
        assert out["term"].value == "15 ngày"

    def test_a_fuzzy_hit_is_marked_as_not_exact(self):
        fields = {"term": sr.SemanticField("16 ngày", "là 16 ngày kể từ ngày", 0)}
        out = sr.locate_fields(fields, CLAUSE)
        assert out["term"].located is True
        assert out["term"].exact is False

    def test_a_wrong_claimed_page_is_corrected_to_where_it_was_found(self):
        fields = {"term": sr.SemanticField("15 ngày", "là 15 ngày kể từ ngày", 7)}
        out = sr.locate_fields(fields, CLAUSE)
        assert out["term"].page == 0

    def test_nobody_looked_is_distinct_from_looked_and_missed(self):
        unlooked = sr.SemanticField("15 ngày", "là 15 ngày kể từ ngày", 0)
        assert unlooked.located is None
        looked = sr.locate_fields({"term": unlooked}, {})["term"]
        assert looked.located is False
