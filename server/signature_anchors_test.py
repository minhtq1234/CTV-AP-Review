from signature_anchors import find_anchors


def W(text, x, y, w=60, h=20, conf=90):
    """One OCR word, in the shape the pipeline actually produces.

    Six keys and no `page`: see `ocr_extract.ocr_words` and
    `idp_words.parse_words`. A fixture that invents a `page` key would let a
    locator read it and pass, while producing page 0 on real data.
    """
    return {"text": text, "x": x, "y": y, "w": w, "h": h, "conf": conf}


def _header(y, *, prefix="", x=600):
    """The CTV signature header as one line of words."""
    return [
        W(prefix, x - 120, y) if prefix else W("", x - 120, y),
        W("BÊN", x, y), W("CUNG", x + 70, y),
        W("ỨNG", x + 150, y), W("DỊCH", x + 220, y), W("VỤ", x + 290, y),
    ]


def test_the_page_comes_from_the_document_map_not_from_a_word():
    """The defect this replaces: evidence was built with a hard-coded page 0.
    A word carries no page, so the only honest source is the map's key."""
    anchors = find_anchors({
        0: [W("Điều", 100, 200), W("1.", 160, 200)],
        3: _header(973),
    })

    assert anchors["ctv"]["page"] == 3


def test_the_box_uses_this_codebase_s_bbox_keys():
    """Every bbox here is {x, y, width, height}. A {w, h} box is truthy and
    renders as a zero-size highlight, which looks like a located value and is
    not one."""
    box = find_anchors({0: _header(500)})["ctv"]["bbox"]

    assert set(box) == {"x", "y", "width", "height"}
    assert box["width"] > 0 and box["height"] > 0


def test_the_box_reaches_below_the_header_to_the_signing_space():
    """The point of the box is the signature and the printed name under it, not
    the label. On real contracts the name sits about nine line-heights down."""
    line_height = 20
    box = find_anchors({0: _header(500)})["ctv"]["bbox"]

    assert box["height"] > line_height * 5


def test_the_box_is_clipped_to_the_page():
    """A block anchored near the foot must not claim space past the paper."""
    box = find_anchors({0: _header(1000)}, {0: 1100})["ctv"]["bbox"]

    assert box["y"] + box["height"] <= 1100


def test_the_last_occurrence_down_the_page_wins():
    """A phrase can occur several times on one page -- five, on one real
    contract -- and only the last is the signature header rather than a mention
    in the body."""
    anchors = find_anchors({0: _header(200) + _header(900)})

    assert anchors["ctv"]["bbox"]["y"] == 900


def test_bare_ben_b_prose_does_not_masquerade_as_a_header():
    """`Bên B` runs through the prose of a real BBNT. Anchoring on the bare form
    matches body text, and being assigned last it would overwrite the header."""
    prose = [W("Bên", 100, 300), W("B", 160, 300), W("thanh", 200, 300),
             W("toán", 280, 300)]
    header = [W("Đại", 600, 900), W("diện", 660, 900), W("Bên", 730, 900),
              W("B", 800, 900)]

    anchors = find_anchors({0: prose + header})

    assert anchors["ctv"]["bbox"]["y"] == 900


def test_a_document_with_no_signature_block_yields_nothing():
    """Which is a real answer: the right document, and no false box. One real
    appendix ends `Approved` and carries no signature phrase at all."""
    assert find_anchors({0: [W("KPI", 100, 100), W("Approved", 200, 100)]}) == {}


def test_the_two_parties_are_told_apart_by_phrase_not_by_position():
    """On a contract the CTV column is on the right; on a real BBNT it is on the
    left. Position cannot decide which block belongs to whom."""
    left = [W("Bên", 100, 900), W("Cung", 170, 900), W("Ứng", 250, 900),
            W("Dịch", 320, 900), W("Vụ", 390, 900)]
    right = [W("Bên", 700, 900), W("Sử", 770, 900), W("Dụng", 830, 900),
             W("Dịch", 910, 900), W("Vụ", 980, 900)]

    anchors = find_anchors({0: left + right})

    assert anchors["ctv"]["bbox"]["x"] < anchors["vng"]["bbox"]["x"]
