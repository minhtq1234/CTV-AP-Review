import pytest

import recap
import greennode

MANIFEST = {
    "id": "p0",
    "docs": [
        {"id": "contract", "kind": "contract", "label": "Hợp đồng dịch vụ", "pages": []},
        {"id": "bbnt", "kind": "bbnt", "label": "Biên bản nghiệm thu", "pages": []},
        {"id": "idf", "kind": "id_front", "label": "CCCD", "pages": []},
    ],
    "fields": [
        {"label": "Phí dịch vụ", "sources": [{"docId": "contract", "value": "10.000.000", "page": 0}]},
        {"label": "Họ tên", "sources": [{"docId": "bbnt", "value": "Nguyễn Văn A", "page": 0}]},
    ],
}


def test_content_region_is_only_that_docs_typed_content():
    r = recap.content_region_for(MANIFEST, "contract")
    assert "Hợp đồng dịch vụ" in r
    assert "Phí dịch vụ: 10.000.000" in r
    assert "Nguyễn Văn A" not in r  # the bbnt field must not leak into the contract region


def test_content_region_none_for_non_content_bearing():
    assert recap.content_region_for(MANIFEST, "idf") is None


def test_content_region_none_for_unknown_doc():
    assert recap.content_region_for(MANIFEST, "nope") is None


def test_disclaimer_frames_as_assist():
    assert "Bản xem thử" in recap.DISCLAIMER
    assert "quyết định cuối cùng do bạn" in recap.DISCLAIMER


def test_greennode_unconfigured_by_default(monkeypatch):
    monkeypatch.delenv("GREENNODE_API_URL", raising=False)
    monkeypatch.delenv("GREENNODE_API_KEY", raising=False)
    assert greennode.is_configured() is False
    with pytest.raises(greennode.NotConfigured):
        greennode.summarize("bất kỳ nội dung nào")


def test_greennode_configured_but_live_call_not_wired(monkeypatch):
    # Both creds set → is_configured() is True, but the live call is still a TODO,
    # so summarize() must keep raising NotConfigured (the endpoint maps that to 503).
    monkeypatch.setenv("GREENNODE_API_URL", "https://greennode.example/api")
    monkeypatch.setenv("GREENNODE_API_KEY", "test-key")
    assert greennode.is_configured() is True
    with pytest.raises(greennode.NotConfigured):
        greennode.summarize("nội dung vùng đã gõ")
