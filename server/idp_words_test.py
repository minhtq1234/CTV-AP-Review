import pytest

from cccd_idp import IdpError
from idp_words import as_jpeg, http_transport, parse_words, read_page, reader


def envelope(items, status="SUCCESS"):
    return {"data": {"status": status,
                     "documents": [{"ocr_data": [{"value": items}]}]}}


def item(text, box, prob=0.9, key="extracted_value", probkey="extracted_prob"):
    return {"name": "x", key: text, probkey: prob, "coordinates": box}


# --- parse_words ------------------------------------------------------------

def test_words_come_out_in_the_pipelines_word_shape():
    # Same keys and the same OCR-pixel space as ocr_extract.ocr_words, so the
    # output drops straight into group_lines/locate_field.
    words = parse_words(envelope([item("8.888.889", [10, 20, 110, 40])]))
    assert words == [{"text": "8.888.889", "x": 10, "y": 20, "w": 100, "h": 20,
                      "conf": 90.0}]

def test_confidence_is_scaled_to_tesseracts_0_100_range():
    # _search_line divides conf by 100; a 0-1 probability left unscaled would
    # make every escalated read look like 0.009 confidence.
    assert parse_words(envelope([item("x", [0, 0, 10, 10], prob=0.84)]))[0]["conf"] == 84.0

def test_an_item_with_no_box_is_skipped_not_guessed_at():
    # A word with no position cannot be highlighted, and "locate & look" is the
    # point of the pipeline.
    assert parse_words(envelope([item("x", None)])) == []
    assert parse_words(envelope([item("x", [1, 2])])) == []
    assert parse_words(envelope([item("x", [0, 0, 0, 0])])) == []

def test_an_empty_or_whitespace_value_is_skipped():
    assert parse_words(envelope([item("", [0, 0, 10, 10])])) == []
    assert parse_words(envelope([item("   ", [0, 0, 10, 10])])) == []

def test_a_missing_probability_reads_as_confident_not_as_garbage():
    # An absent score is unknown, not bad. Scoring it 0 would send every
    # escalated field straight back into "low-confidence" and re-escalate it.
    words = parse_words(envelope([{"name": "x", "extracted_value": "y",
                                   "coordinates": [0, 0, 10, 10]}]))
    assert words[0]["conf"] == 100.0

def test_the_alternate_field_names_are_accepted():
    # The generic-read item shape is unverified (see the module header), so
    # `text`/`confidence` are accepted alongside `extracted_value`/`extracted_prob`.
    words = parse_words(envelope([item("z", [0, 0, 10, 10], prob=0.5,
                                       key="text", probkey="confidence")]))
    assert words[0]["text"] == "z" and words[0]["conf"] == 50.0

def test_origin_plus_size_boxes_are_accepted_as_well_as_corners():
    # _bbox_from reads (x, y, w, h) when the last two don't exceed the first two.
    assert parse_words(envelope([item("x", [50, 60, 20, 10])]))[0] == {
        "text": "x", "x": 50, "y": 60, "w": 20, "h": 10, "conf": 90.0}

def test_every_document_and_group_contributes():
    payload = {"data": {"documents": [
        {"ocr_data": [{"value": [item("a", [0, 0, 10, 10])]},
                      {"value": [item("b", [0, 20, 10, 10])]}]},
        {"ocr_data": [{"value": [item("c", [0, 40, 10, 10])]}]},
    ]}}
    assert [w["text"] for w in parse_words(payload)] == ["a", "b", "c"]

def test_an_empty_or_malformed_envelope_yields_no_words():
    for payload in ({}, {"data": None}, {"data": {}}, {"data": {"documents": []}},
                    {"data": {"documents": [{}]}},
                    {"data": {"documents": [{"ocr_data": [{"value": ["not-a-dict"]}]}]}}):
        assert parse_words(payload) == []


# --- read_page: the polling contract ---------------------------------------

def test_read_page_polls_for_content_not_for_status():
    # The envelope's status goes terminal BEFORE ocr_data fills, so a reader
    # that stops at "SUCCESS" gets nothing. Two empty-but-SUCCESS replies here.
    replies = [envelope([], status="SUCCESS"),
               envelope([], status="SUCCESS"),
               envelope([item("8.888.889", [0, 0, 90, 20])], status="SUCCESS")]
    calls = {"n": 0}
    def fetch(_):
        payload = replies[min(calls["n"], len(replies) - 1)]
        calls["n"] += 1
        return payload
    words = read_page(b"png", "pg1.png",
                      submit=lambda *_: {"data": {"request_id": "r1"}},
                      fetch=fetch, sleep=lambda _: None)
    assert [w["text"] for w in words] == ["8.888.889"]
    assert calls["n"] == 3

def test_read_page_gives_up_on_a_dead_state_without_exhausting_attempts():
    calls = {"n": 0}
    def fetch(_):
        calls["n"] += 1
        return {"data": {"status": "FAILED", "documents": []}}
    assert read_page(b"png", "p.png",
                     submit=lambda *_: {"data": {"request_id": "r"}},
                     fetch=fetch, sleep=lambda _: None) == []
    assert calls["n"] == 1

def test_read_page_raises_when_submit_returns_no_request_id():
    with pytest.raises(IdpError):
        read_page(b"png", "p.png", submit=lambda *_: {"data": {}},
                  fetch=lambda _: {}, sleep=lambda _: None)

def test_an_unreadable_page_is_a_result_not_a_failure():
    # The caller keeps its local words and the field stays "cần xem".
    assert read_page(b"png", "p.png",
                     submit=lambda *_: {"data": {"request_id": "r"}},
                     fetch=lambda _: envelope([]), attempts=2,
                     sleep=lambda _: None) == []

def test_reader_binds_a_two_argument_callable():
    read = reader("http://idp.example/v1", "key-not-used-offline")
    assert callable(read)


# --- transport shape --------------------------------------------------------

def test_the_transport_sends_the_configured_doc_type():
    # doc_type is the one parameter that selects a general page read instead of
    # the CCCD model, and the only value known to work live is "ID".
    sent = {}
    import urllib.request as u
    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"data":{"request_id":"r"}}'
    def fake_urlopen(request, timeout=0):
        sent["body"] = request.data
        sent["auth"] = request.get_header("Authorization")
        sent["url"] = request.full_url
        return FakeResponse()
    original, u.urlopen = u.urlopen, fake_urlopen
    try:
        submit, _ = http_transport("http://idp.example/v1", "secret", "CONTRACT")
        submit(b"imagebytes", "pg1.png")
    finally:
        u.urlopen = original
    body = sent["body"].decode("utf-8", "replace")
    assert 'name="doc_type"\r\n\r\nCONTRACT' in body
    assert 'name="model"\r\n\r\nidp' in body
    assert "imagebytes" in body
    assert sent["auth"] == "Bearer secret"
    assert sent["url"] == "http://idp.example/v1/ocr/ingest"


def test_the_file_part_matches_the_one_shape_known_to_work(tmp_path):
    """JPEG bytes, .jpg name, Content-Type image/jpeg.

    cccd_idp -- the transport verified against the live API -- sends image/jpeg,
    and the endpoint's own curl example posts a .jpg. The pipeline renders pages
    as PNG, so declaring image/png would send a type this service has never been
    observed to accept.
    """
    from PIL import Image
    png = tmp_path / "pg1.png"
    Image.new("RGB", (12, 8), (255, 255, 255)).save(png, format="PNG")

    sent = {}
    import urllib.request as u
    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"data":{"request_id":"r"}}'
    def fake_urlopen(request, timeout=0):
        sent["body"] = request.data
        return FakeResponse()
    original, u.urlopen = u.urlopen, fake_urlopen
    try:
        submit, _ = http_transport("http://idp.example/v1", "k", "ID")
        submit(png.read_bytes(), "pg1.png")
    finally:
        u.urlopen = original
    body = sent["body"]
    assert b"Content-Type: image/jpeg" in body
    assert b'filename="pg1.jpg"' in body
    assert b"\xff\xd8\xff" in body            # JPEG SOI, i.e. it really converted
    assert b"\x89PNG" not in body


def test_as_jpeg_converts_a_png_and_leaves_a_jpeg_alone(tmp_path):
    from PIL import Image
    import io
    png = io.BytesIO(); Image.new("RGB", (8, 8), (1, 2, 3)).save(png, format="PNG")
    jpg = io.BytesIO(); Image.new("RGB", (8, 8), (1, 2, 3)).save(jpg, format="JPEG")
    converted = as_jpeg(png.getvalue())
    assert converted.startswith(b"\xff\xd8\xff")
    assert as_jpeg(jpg.getvalue()) == jpg.getvalue()      # already JPEG: untouched


def test_as_jpeg_passes_undecodable_bytes_through():
    # A transport must not be the thing that fails an ingest.
    assert as_jpeg(b"not-an-image") == b"not-an-image"


def test_document_field_idp_needs_an_explicit_doc_type(monkeypatch):
    """The doc_type is a third gate, not a defaulted guess.

    doc_type=ID works for CCCD cards, but every candidate for a general page
    read returns HTTP 500 on this account. Without this gate, enabling IDP for
    cards -- worth doing today -- would also fire one doomed request per
    escalated page (~50 on July, ~81 on February).
    """
    from idp_words import page_reader_from_env
    monkeypatch.setenv("GREENNODE_IDP_URL", "http://idp.example/v1")
    monkeypatch.setenv("GREENNODE_API_KEY", "not-a-real-key")

    monkeypatch.delenv("IDP_DOC_TYPE", raising=False)
    assert page_reader_from_env() is None, "must stay off without an explicit doc_type"

    monkeypatch.setenv("IDP_DOC_TYPE", "   ")
    assert page_reader_from_env() is None, "whitespace is not a doc_type"

    monkeypatch.setenv("IDP_DOC_TYPE", "GENERAL")
    assert callable(page_reader_from_env()), "explicit doc_type turns it on"


def test_cccd_idp_is_unaffected_by_the_doc_type_gate(monkeypatch):
    # The card reader must still enable on the two variables alone -- that path
    # is proven and is the one worth switching on now.
    import pipeline as pl
    monkeypatch.setenv("GREENNODE_IDP_URL", "http://idp.example/v1")
    monkeypatch.setenv("GREENNODE_API_KEY", "not-a-real-key")
    monkeypatch.delenv("IDP_DOC_TYPE", raising=False)
    assert callable(pl._card_reader())
    assert pl._page_reader() is None
