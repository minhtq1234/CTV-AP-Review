import json
import os

import pytest
from fastapi.testclient import TestClient

import app as appmod
import recap
import greennode
from app import app

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


def _case_with_manifest(monkeypatch, tmp_path, manifest):
    monkeypatch.setattr(appmod, "store", appmod.CaseStore(str(tmp_path)))
    cid = appmod.store.create(name="c", pdf_name="c.pdf", roster_name=None,
                              now="2026-01-01T00:00:00Z")
    appmod.store.set_result(cid, summary=None, packets=[
        {"index": 0, "name": "P0", "pages": [0, 1],
         "confidence": "green", "flags": [], "labels": []}])
    d = os.path.join(appmod.store.case_dir(cid), "packets", "0")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False)
    return TestClient(app), cid


def test_recap_503_when_greennode_unconfigured(tmp_path, monkeypatch):
    monkeypatch.delenv("GREENNODE_API_URL", raising=False)
    monkeypatch.delenv("GREENNODE_API_KEY", raising=False)
    c, cid = _case_with_manifest(monkeypatch, tmp_path, MANIFEST)
    r = c.post(f"/api/cases/{cid}/packets/0/recap", json={"docId": "contract"})
    assert r.status_code == 503


def test_recap_returns_and_caches_when_wired(tmp_path, monkeypatch):
    calls = {"n": 0}

    def fake_summarize(content):
        calls["n"] += 1
        assert "Hợp đồng dịch vụ" in content       # only the typed region reaches GreenNode
        assert "Nguyễn Văn A" not in content       # no other doc's data leaks
        return {"bullets": ["a", "b"], "nhanDinh": "ổn"}

    monkeypatch.setattr(appmod.greennode, "summarize", fake_summarize)
    c, cid = _case_with_manifest(monkeypatch, tmp_path, MANIFEST)
    r = c.post(f"/api/cases/{cid}/packets/0/recap", json={"docId": "contract"})
    assert r.status_code == 200
    body = r.json()
    assert body["bullets"] == ["a", "b"] and body["nhanDinh"] == "ổn"
    assert "quyết định cuối cùng do bạn" in body["disclaimer"]
    # cached: a second call returns the same recap without re-summarising
    r2 = c.post(f"/api/cases/{cid}/packets/0/recap", json={"docId": "contract"})
    assert r2.status_code == 200 and r2.json()["bullets"] == ["a", "b"]
    assert calls["n"] == 1


def test_recap_404_for_non_content_bearing_doc(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod.greennode, "summarize",
                        lambda content: {"bullets": [], "nhanDinh": ""})
    c, cid = _case_with_manifest(monkeypatch, tmp_path, MANIFEST)
    r = c.post(f"/api/cases/{cid}/packets/0/recap", json={"docId": "idf"})
    assert r.status_code == 404


def test_recap_404_for_unknown_case(monkeypatch):
    monkeypatch.setattr(appmod.greennode, "summarize",
                        lambda content: {"bullets": [], "nhanDinh": ""})
    r = TestClient(app).post("/api/cases/nope/packets/0/recap", json={"docId": "contract"})
    assert r.status_code == 404
