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

#: Tokens that each fold to SEVERAL words, so a token count and a folded word
#: count diverge sharply. `15/07/2026` and `15.000.000` fold to three words
#: apiece and `thanh-toán` to two, which is what makes this fixture able to
#: tell the two units apart: 20 of these tokens are 20 norm words but 60
#: folded ones.
LONG = {
    0: line(["15/07/2026"] * 10, 10)
       + line(["15.000.000"] * 10 + ["đồng"], 30)
       + line(["thanh-toán"] * 8, 50),
}

#: A page that states a bare date range verbatim -- the shape #13's `term`
#: invites a model to quote back on its own, with no clause around it.
DATES = {
    0: line("Kỳ hạn 15/07/2026 - 15/08/2026 - 15/09/2026 và các kỳ sau".split(),
            10),
}

#: A clause whose value-bearing tokens each occupy one span but several folded
#: words. Real contracts put dates, money and hyphenated terms exactly here,
#: and they are over-represented among multi-word-folding tokens (1.5% of
#: tokens overall).
WIDE = {
    0: line(["Tổng", "giá", "trị", "hợp", "đồng", "là", "15.000.000",
             "đồng"], 10)
       + line(["thanh-toán", "một", "lần", "trước", "15/07/2026", "theo",
               "biên", "bản"], 30)
       + line(["nghiệm", "thu", "được", "hai", "bên", "ký", "đầy", "đủ"], 50),
}

#: Spans WIDE's first two lines: 16 tokens, but 21 folded words. The gap of 5
#: is the whole point -- it is wider than WIDTH_SLACK, so a sweep that walks
#: token counts against a folded word count can never build this window.
WIDE_QUOTE = ("Tổng giá trị hợp đồng là 15.000.000 đồng "
              "thanh-toán một lần trước 15/07/2026 theo biên bản")


class TestLocatesAClause:
    def test_a_quote_spanning_a_line_break_is_located(self):
        got = sr.locate_quote("thanh toán là 15 ngày kể từ ngày", CLAUSE, 0)
        assert got is not None
        assert got["exact"] is True
        assert got["page"] == 0

    def test_the_box_encloses_both_lines_and_is_not_expanded(self):
        got = sr.locate_quote("thanh toán là 15 ngày kể từ ngày", CLAUSE, 0)
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
        got = sr.locate_quote("thanh toán là 15\nngày kể từ ngày", CLAUSE, 0)
        assert got is not None and got["exact"] is True

    def test_stripped_diacritics_cost_nothing(self):
        got = sr.locate_quote("thanh toan la 15 ngay ke tu ngay", CLAUSE, 0)
        assert got is not None and got["exact"] is True

    def test_added_punctuation_costs_nothing(self):
        got = sr.locate_quote('"thanh toán là 15 ngày, kể từ ngày."', CLAUSE, 0)
        assert got is not None and got["exact"] is True


class TestFuzzyFallback:
    def test_one_changed_character_still_locates(self):
        # Exact substring matching makes this 100% unlocatable, which is the
        # single largest risk to a model-supplied quote.
        got = sr.locate_quote("thanh toan la 15 ngayx kể từ ngày", CLAUSE, 0)
        assert got is not None
        assert got["exact"] is False
        assert got["ratio"] >= sr.MIN_RATIO

    def test_a_dropped_word_still_locates(self):
        got = sr.locate_quote("thanh toán là 15 ngày từ ngày nghiệm", CLAUSE, 0)
        assert got is not None and got["exact"] is False

    def test_an_exact_hit_is_preferred_over_a_near_miss(self):
        got = sr.locate_quote("thanh toán là 15 ngày kể từ ngày", CLAUSE, 0)
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
        got = sr.locate_quote("một một một một một một một một", long_page, 0)
        assert got is not None
        # Six words wide, not eighty: a window free to grow would box the lot.
        assert got["bbox"]["height"] == 12


class TestRefusesWhatItCannotVouchFor:
    def test_a_short_quote_is_refused(self):
        # Below six words a quote lands on the wrong occurrence of itself
        # (7.2% at four words), so there is nothing to point at honestly.
        assert sr.locate_quote("là 15 ngày kể từ", CLAUSE, 0) is None
        assert len(sr.norm("là 15 ngày kể từ").split()) < sr.MIN_WORDS

    def test_an_empty_quote_is_refused(self):
        assert sr.locate_quote("", CLAUSE, 0) is None
        assert sr.locate_quote("   ", CLAUSE, 0) is None

    def test_a_quote_of_pure_punctuation_is_refused(self):
        assert sr.locate_quote('"""" ---- ....', CLAUSE, 0) is None

    def test_no_pages_locates_nothing(self):
        assert sr.locate_quote("thanh toán là 15 ngày kể từ ngày", {}, 0) is None


class TestThePageIsAHintNotAContract:
    def test_a_wrong_claimed_page_still_locates(self):
        # At eight words or more a whole-document search lands on the wrong
        # occurrence 0% of the time, so honouring a model's page slip strictly
        # would lose a locatable quote for no accuracy gain.
        got = sr.locate_quote("thanh toán là 15 ngày kể từ ngày", CLAUSE, 7)
        assert got is not None and got["page"] == 0

    def test_no_claimed_page_still_locates(self):
        got = sr.locate_quote("thanh toán là 15 ngày kể từ ngày", CLAUSE, None)
        assert got is not None and got["page"] == 0

    def test_the_claimed_page_wins_a_tie(self):
        pages = {
            0: line(["Thời", "hạn", "thanh", "toán", "là", "15", "ngày", "kể", "từ"], 10),
            1: line(["Thời", "hạn", "thanh", "toán", "là", "15", "ngày", "kể", "từ"], 10),
        }
        assert sr.locate_quote("Thời hạn thanh toán là 15 ngày kể từ", pages, 1)["page"] == 1
        assert sr.locate_quote("Thời hạn thanh toán là 15 ngày kể từ", pages, 0)["page"] == 0


class TestFold:
    def test_it_folds_case_diacritics_punctuation_and_whitespace(self):
        assert sr.fold("Thời  HẠN, thanh-toán!") == "thoi han thanh toan"

    def test_punctuation_becomes_a_space_so_both_sides_agree(self):
        # Only one side may carry the hyphen. Deleting it would give
        # "thanhtoan" against the page's "thanh toan" and match nothing.
        assert sr.fold("thanh-toán") == sr.fold("thanh toán")
        pages = {0: line(["Thời", "hạn", "thanh", "toán", "là", "15", "ngày", "kể", "từ"], 10)}
        got = sr.locate_quote("Thời hạn thanh-toán là 15 ngày kể từ", pages, 0)
        assert got is not None and got["exact"] is True

    def test_a_token_folding_to_nothing_is_dropped_not_joined(self):
        # A table rule reads as a lone dash between two halves of a cell. Joined
        # in, it would leave a double space and stop an otherwise exact match.
        pages = {0: line(["thanh", "toán", "là", "15", "-", "ngày", "kể", "từ", "ngày"], 10)}
        got = sr.locate_quote("thanh toán là 15 ngày kể từ ngày", pages, 0)
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
        fields = {"term": sr.SemanticField("15 ngày", "thanh toán là 15 ngày kể từ ngày", 0)}
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
        fields = {"term": sr.SemanticField("16 ngày", "thanh toan la 15 ngayx kể từ ngày", 0)}
        out = sr.locate_fields(fields, CLAUSE)
        assert out["term"].located is True
        assert out["term"].exact is False

    def test_a_wrong_claimed_page_is_corrected_to_where_it_was_found(self):
        fields = {"term": sr.SemanticField("15 ngày", "thanh toán là 15 ngày kể từ ngày", 7)}
        out = sr.locate_fields(fields, CLAUSE)
        assert out["term"].page == 0

    def test_nobody_looked_is_distinct_from_looked_and_missed(self):
        unlooked = sr.SemanticField("15 ngày", "thanh toán là 15 ngày kể từ ngày", 0)
        assert unlooked.located is None
        looked = sr.locate_fields({"term": unlooked}, {})["term"]
        assert looked.located is False


class TestRefusesWhatItCannotVouchFor2:
    """Guards added after an independent review measured them failing."""

    def test_a_quote_starting_inside_a_token_is_not_an_exact_hit(self):
        """`str.find` has no word boundary, and `_index` flattens the page.

        A quote starting or ending INSIDE a token matched and was stamped
        `exact: True, ratio: 1.0` -- the strongest claim this makes -- while
        the box widened to the whole straddled token. Measured on real
        contract pages, 15,499 of 15,499 deliberately mid-token quotes came
        back exact. The tokens it lands on are the value-bearing ones: an
        amount, a date and an account number are each a single token, so the
        highlight sat on a different number than the value claimed.
        """
        pages = {0: line(
            ["Tổng", "cộng", "15.000.000", "đồng", "chẵn", "cho", "cả",
             "hợp", "đồng"], 10)}
        # Starts mid-amount. The page never says "000.000", only "15.000.000",
        # so boxing this would vouch for a number the document does not state.
        assert sr.locate_quote("000 000 đồng chẵn cho cả hợp đồng",
                               pages, 0) is None
        # the same span on whole tokens does match
        got = sr.locate_quote("Tổng cộng 15.000.000 đồng chẵn cho cả hợp đồng",
                              pages, 0)
        assert got is not None and got["exact"] is True

    def test_a_fuzzy_hit_may_not_disagree_on_digits(self):
        """MIN_RATIO scores characters, so a substituted digit is nearly free.

        One altered digit in a ~55-character clause costs about 0.02 of a 0.10
        budget: measured, 95.9% of such quotes were boxed. An amount, a date
        and an account number are precisely what these criteria are about.
        """
        assert sr.locate_quote("thanh toán là 16 ngày kể từ ngày",
                               CLAUSE, 0) is None
        # the same distance, but in letters rather than digits, still locates
        got = sr.locate_quote("thanh toan la 15 ngayx kể từ ngày", CLAUSE, 0)
        assert got is not None and got["exact"] is False

    def test_a_quote_longer_than_a_clause_is_refused(self):
        # The fuzzy sweep is O(window x quote) over a model-controlled string:
        # measured on one real page, 320 words took 105s and 480 had not
        # returned after 8 minutes. ocr_packet runs on a daemon thread, so
        # that is a case stuck in `processing` for ever with no error.
        assert sr.locate_quote(" ".join(["ngày"] * 200), CLAUSE, 0) is None

    def test_the_length_gate_counts_words_not_punctuation(self):
        """`fold` expands punctuation into spaces, so counting after it made
        the gate depend on how much punctuation a value carries.

        `15/07/2026 - 15/08/2026` inflated to six folded words and passed --
        and that is #13's `term`, the very case the module says it refuses.
        """
        assert len(sr.fold("15/07/2026 - 15/08/2026").split()) >= 6
        assert len(sr.norm("15/07/2026 - 15/08/2026").split()) < sr.MIN_WORDS
        assert sr.locate_quote("15/07/2026 - 15/08/2026", CLAUSE, 0) is None

    def test_the_ceiling_counts_the_words_the_sweep_actually_walks(self):
        """MAX_WORDS is a cost control, so it must count what costs.

        `_best_window` sets `wanted = len(quote.split())` on the FOLDED string
        and sweeps windows in folded words, so the O(window x quote) sweep is
        driven by folded words and by nothing else. Counted on `norm` the gate
        did not bind where it mattered: 60 tokens of hyphenated triples passed
        at 60 norm words, folded to 180, and took ~52s to return None -- on
        `ocr_packet`'s daemon thread, once per requested part per document.
        """
        wide = " ".join(["15/07/2026"] * 10 + ["15.000.000"] * 10)
        assert len(wide.split()) == 20                      # 20 tokens
        assert len(sr.fold(wide).split()) == sr.MAX_WORDS   # but 60 words
        got = sr.locate_quote(wide, LONG, 0)
        assert got is not None and got["exact"] is True

        # One more single-word token: still only 21 norm words, so a gate
        # counted on `norm` would wave it through, but 61 folded words.
        over = wide + " đồng"
        assert len(sr.norm(over).split()) < sr.MAX_WORDS
        assert len(sr.fold(over).split()) == sr.MAX_WORDS + 1
        assert sr.locate_quote(over, LONG, 0) is None

    def test_a_refused_quote_never_reaches_the_sweep(self, monkeypatch):
        """The point of the ceiling is that the expensive path is not entered.

        Asserted structurally rather than on wall-clock, which would flake in
        CI: `_best_window` is replaced with something that cannot be called
        quietly. This quote is 30 norm words -- comfortably under MAX_WORDS in
        the old unit -- and 90 folded ones.
        """
        def explode(*args, **kwargs):
            raise AssertionError("swept")

        monkeypatch.setattr(sr, "_best_window", explode)
        quote = " ".join(["15/07/2026"] * 30)
        assert len(sr.norm(quote).split()) < sr.MAX_WORDS
        assert len(sr.fold(quote).split()) == 90
        assert sr.locate_quote(quote, LONG, 0) is None

    def test_the_floor_counts_folded_words_too(self):
        """`fold` deflates as well as inflating, and the floor must see it.

        Three lone dashes fold to nothing and `_index` drops them, so this is
        9 norm words but 6 folded -- two under the floor MIN_WORDS was
        measured to buy (0.95% wrong-occurrence at 8 words against 2.74% at
        6). Counted on `norm` alone it passed the gate and came back
        `exact: True, ratio: 1.0` on a six-token box, which is the strongest
        claim this module makes. It is refused on the EXACT path, not merely
        kept out of the fuzzy sweep, which is why both gates sit above both
        passes.
        """
        quote = "là 15 ngày kể từ ngày - - -"
        assert len(sr.norm(quote).split()) >= sr.MIN_WORDS
        assert len(sr.fold(quote).split()) < sr.MIN_WORDS
        assert sr.locate_quote(quote, CLAUSE, 0) is None

    def test_the_floor_still_counts_norm_words_too(self):
        """And the mirror case, which a fold-only floor would re-open.

        A bare date range is 5 norm words but 9 folded, so a floor counted on
        `fold` alone admits it -- and DATES states it verbatim, so it boxes as
        an exact hit on one of several date occurrences. That is #13's `term`
        with no clause around it: precisely what MIN_WORDS exists to refuse.
        The floor therefore takes the smaller of the two counts.
        """
        quote = "15/07/2026 - 15/08/2026 - 15/09/2026"
        assert len(sr.norm(quote).split()) < sr.MIN_WORDS
        assert len(sr.fold(quote).split()) >= sr.MIN_WORDS
        # Nothing but the floor can refuse this: the page says it, verbatim,
        # on whole token boundaries.
        text, _, _ = sr._index(sr.reading_order(DATES[0]))
        assert sr.fold(quote) in text
        assert sr.locate_quote(quote, DATES, 0) is None


class TestWindowsAreMeasuredInWordsNotTokens:
    """`_best_window` sweeps WORDS; nothing in this file used to prove it.

    The rewrite was justified by "43.6% unlocatable against 0.0%", and it was
    exercised by nothing: reverting it to the old width-in-tokens loop left
    the whole file green, because the only multi-word-folding token in the
    suite sat on the exact path, which is character-based and never had the
    hole. The mechanism: the old loop swept widths in TOKENS over
    [wanted - WIDTH_SLACK, wanted + WIDTH_SLACK] where `wanted` is in folded
    WORDS, so a window was reachable only if its tokens expanded by 2 folded
    words or fewer, and the correct window was never a candidate at all.

    That has two outcomes, not one, and which one appears depends on the page
    rather than the quote -- so both are covered here. On a page with room to
    overshoot, a wider WRONG window clears MIN_RATIO and the quote is boxed
    over text it does not mention. On a page trimmed to the quote's own lines,
    no candidate is built and the quote comes back unlocatable, which is the
    outcome the measured rate is about.
    """

    def test_the_fixture_really_has_multiword_tokens(self):
        # Guards the fixture itself. This coverage went missing precisely by a
        # page having no such token, so the property is asserted rather than
        # assumed: silently normalising WIDE would make the test below pass
        # for the wrong reason.
        tokens = sr.reading_order(WIDE[0])
        text, spans, kept = sr._index(tokens)
        widths = {
            tokens[kept[i]]["text"]: len(text[start:end].split())
            for i, (start, end) in enumerate(spans)
        }
        assert widths["15.000.000"] == 3
        assert widths["15/07/2026"] == 3
        assert widths["thanh-toán"] == 2

    def test_a_fuzzy_hit_over_multiword_tokens_is_reachable(self):
        # 16 tokens, 21 folded words: the true width is 5 outside the swept
        # token range, so the old loop could not build the correct window.
        #
        # What it DID build, measured: `(0, 18, 0.9137)` -- a 19-token window
        # running into the third line, i.e. a hit whose box is 52px tall and
        # covers `nghiệm thu được`, text this quote never mentions. So the
        # failure the old loop produced on THIS page is an over-boxed
        # highlight, not a refusal, and the assertions below are ordered by
        # what actually discriminates: the ratio (0.9945 against the old
        # 0.9137) and the extent (32 against 52). `is not None` alone does not
        # -- see the sibling test for the page shape where the old loop really
        # does come back empty.
        #
        # The alteration is in LETTERS, not digits, deliberately -- a changed
        # digit is refused by the `_digits` guard in either version, and the
        # test would pass for the wrong reason.
        assert len(WIDE_QUOTE.split()) == 16
        assert len(sr.fold(WIDE_QUOTE).split()) == 21
        got = sr.locate_quote(WIDE_QUOTE.replace("biên", "biênx"), WIDE, 0)
        assert got is not None
        assert got["exact"] is False
        # Above MIN_RATIO is not the claim: the token loop cleared that too.
        # Only the right window scores this well.
        assert got["ratio"] >= 0.95
        # The first two lines, and no further: 10 -> 30 + 12. The token loop's
        # window reached 52 here.
        assert got["bbox"]["y"] == 10
        assert got["bbox"]["height"] == 32

    def test_a_quote_whose_window_is_unreachable_is_simply_unlocatable(self):
        """The refusal half, on the page shape that produces it.

        The class's justification is an unlocatable RATE (43.6% against 0.0%),
        and no test demonstrated an unlocatable outcome: on the three-line
        WIDE the old loop over-boxed instead of refusing, because a 19-token
        window still fits a 24-token page. Trim the page to the two lines the
        quote actually spans and there is no room to overshoot -- `wanted` is
        21 folded words, `low` is 19, and 19 > 16 spans, so the old loop's
        `if width > len(spans): break` fires on the first iteration and
        nothing is ever compared. Verified: it returns None there.
        """
        page = {0: WIDE[0][:16]}          # WIDE's first two lines only
        assert len(page[0]) == 16
        got = sr.locate_quote(WIDE_QUOTE.replace("biên", "biênx"), page, 0)
        assert got is not None, "the word sweep finds it"
        assert got["exact"] is False
        assert got["ratio"] >= 0.95
        assert got["bbox"]["height"] == 32

    def test_exact_over_multiword_tokens_still_works(self):
        # The exact path is character-based and never had the hole; pinned so
        # a future change to the sweep cannot quietly cost the verbatim case.
        got = sr.locate_quote(WIDE_QUOTE, WIDE, 0)
        assert got is not None and got["exact"] is True
        assert got["bbox"]["height"] == 32
