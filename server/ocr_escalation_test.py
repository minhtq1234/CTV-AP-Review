"""`_escalate_weak_fields` — the re-read loop, with an injected fake reader.

No network, no credential, no PDF: the loop, the fallbacks and the coordinate
space are all verifiable from words alone.
"""
import os

from ocr_extract import _escalate_weak_fields, PATTERNS


def W(text, x, y, w, h, conf=90):
    return {"text": text, "x": x, "y": y, "w": w, "h": h, "conf": conf}


def fee_page(readable):
    """A contract fee page: the anchor heading, then the clause."""
    lines = [W("ĐIỀU", 10, 50, 40, 18), W("2.", 55, 50, 20, 18),
             W("PHÍ", 80, 50, 30, 18), W("DỊCH", 115, 50, 35, 18),
             W("VỤ", 155, 50, 25, 18)]
    lines += [W("2.1.", 10, 80, 30, 18), W("Phí", 45, 80, 25, 18),
              W("dịch", 75, 80, 30, 18)]
    if readable:
        lines.append(W("8.888.889", 110, 80, 90, 18, conf=93))
    else:
        lines.append(W("~~~~", 110, 80, 90, 18, conf=12))
    return lines


def setup_pages(tmp_path, n=2):
    pages = []
    for i in range(n):
        p = tmp_path / f"pg{i}.png"
        p.write_bytes(b"\x89PNG-fake-" + str(i).encode())
        pages.append({"src": str(p), "width": 1241, "height": 1755})
    return pages


def local_state(readable=False):
    words_by_doc = {"contract-0": {0: [W("preamble", 10, 10, 60, 18)],
                                  1: fee_page(readable)}}
    page_of = {("contract-0", 0): 0, ("contract-0", 1): 1}
    return words_by_doc, page_of


def fields_for(words_by_doc):
    from ocr_extract import extract_fields
    return extract_fields(words_by_doc, {})


def test_a_fully_read_packet_never_calls_the_reader(tmp_path):
    words_by_doc, page_of = local_state(readable=True)
    fields = fields_for(words_by_doc)
    calls = []
    def reader(data, name):
        calls.append(name)
        return []
    out = _escalate_weak_fields(fields, reader, words_by_doc, page_of,
                               setup_pages(tmp_path))
    # phi reads locally here, so phi contributes no page. Other fields are
    # absent from this synthetic page entirely and so are unlocated -- which
    # by design contributes no page either.
    assert calls == []
    assert out == fields


def test_the_reader_is_sent_the_display_png_already_on_disk(tmp_path):
    # Display space, so the returned boxes need no scale factor and line up
    # with the reviewer's highlight.
    words_by_doc, page_of = local_state(readable=False)
    pages = setup_pages(tmp_path)
    seen = {}
    def reader(data, name):
        seen["bytes"], seen["name"] = data, name
        return fee_page(readable=True)
    _escalate_weak_fields(fields_for(words_by_doc), reader, words_by_doc,
                          page_of, pages)
    assert seen["name"] == "pg1.png"
    assert seen["bytes"] == open(pages[1]["src"], "rb").read()


def test_an_escalated_page_replaces_its_own_unreadable_source(tmp_path):
    words_by_doc, page_of = local_state(readable=False)
    before = fields_for(words_by_doc)
    assert [s.get("value") for f in before if f["key"] == "phi"
            for s in f["sources"]] == [""]
    out = _escalate_weak_fields(before, lambda d, n: fee_page(readable=True),
                                words_by_doc, page_of, setup_pages(tmp_path))
    phi = next(f for f in out if f["key"] == "phi")
    assert [s["value"] for s in phi["sources"]] == ["8.888.889"]


def test_a_reader_that_raises_leaves_the_local_read_in_place(tmp_path):
    # A network problem must never make an ingest worse than not calling.
    words_by_doc, page_of = local_state(readable=False)
    before = fields_for(words_by_doc)
    def boom(data, name):
        raise RuntimeError("connection reset")
    out = _escalate_weak_fields(before, boom, words_by_doc, page_of,
                                setup_pages(tmp_path))
    assert out == before


def test_a_reader_that_returns_nothing_leaves_the_local_read_in_place(tmp_path):
    words_by_doc, page_of = local_state(readable=False)
    before = fields_for(words_by_doc)
    out = _escalate_weak_fields(before, lambda d, n: [], words_by_doc, page_of,
                                setup_pages(tmp_path))
    assert out == before


def test_a_missing_page_file_is_skipped_not_raised(tmp_path):
    words_by_doc, page_of = local_state(readable=False)
    pages = setup_pages(tmp_path)
    os.remove(pages[1]["src"])
    calls = []
    out = _escalate_weak_fields(fields_for(words_by_doc),
                               lambda d, n: calls.append(n) or [], words_by_doc,
                               page_of, pages)
    assert calls == []
    assert out == fields_for(words_by_doc)


def test_a_page_with_no_mapping_is_skipped(tmp_path):
    words_by_doc, page_of = local_state(readable=False)
    out = _escalate_weak_fields(fields_for(words_by_doc),
                                lambda d, n: fee_page(True), words_by_doc,
                                {}, setup_pages(tmp_path))
    assert out == fields_for(words_by_doc)


def test_only_the_escalated_page_is_re_read(tmp_path):
    # Page 0 reads fine and carries no weak field, so it must not be sent.
    words_by_doc, page_of = local_state(readable=False)
    names = []
    def reader(data, name):
        names.append(name)
        return fee_page(readable=True)
    _escalate_weak_fields(fields_for(words_by_doc), reader, words_by_doc,
                          page_of, setup_pages(tmp_path))
    assert names == ["pg1.png"]


def test_the_local_words_are_not_mutated_by_an_escalation(tmp_path):
    words_by_doc, page_of = local_state(readable=False)
    snapshot = {d: {p: list(w) for p, w in bp.items()}
                for d, bp in words_by_doc.items()}
    _escalate_weak_fields(fields_for(words_by_doc), lambda d, n: fee_page(True),
                          words_by_doc, page_of, setup_pages(tmp_path))
    assert words_by_doc == snapshot
