from ocr_extract import scale_words, group_lines, union_bbox, norm

def W(text, x, y, w, h, conf=90): return {"text": text, "x": x, "y": y, "w": w, "h": h, "conf": conf}

def test_scale_words_halves_boxes():
    out = scale_words([W("a", 100, 200, 40, 20)], 0.5)
    assert out[0]["x"] == 50 and out[0]["y"] == 100 and out[0]["w"] == 20 and out[0]["h"] == 10
    assert out[0]["text"] == "a"

def test_group_lines_clusters_by_y():
    words = [W("Ho", 10, 100, 20, 18), W("ten", 40, 102, 20, 18), W("MST", 10, 200, 30, 18)]
    lines = group_lines(words, y_tol=8)
    assert len(lines) == 2
    assert [w["text"] for w in lines[0]] == ["Ho", "ten"]   # x-sorted, same row
    assert [w["text"] for w in lines[1]] == ["MST"]

def test_union_bbox_encloses():
    b = union_bbox([W("a", 10, 20, 30, 10), W("b", 50, 25, 20, 15)])
    assert b == {"x": 10, "y": 20, "width": 60, "height": 20}

def test_norm_strips_diacritics_and_case():
    assert norm("Mã số thuế") == "ma so thue"
    assert norm("CĂN CƯỚC") == "can cuoc"

if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f): f(); print(f"  ok {n}")
    print("ALL OK")
