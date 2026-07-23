from report import build_report

CASE = {"name":"FA.pdf","packets":[
  {"index":0,"name":"Lê Thị Mai Anh","matchedBy":"cccd",
   "ocrIdentity":{"cccd":"079","name":"Lê Thị Mai Anh"},"rosterIdentity":{"cccd":"079","name":"Lê Thị Mai Anh"},
   "review":{"done":True,"items":{"A2":{"seen":True,"flag":{"reason":"sai","note":"lệch số"}}}}},
  {"index":1,"name":"Trần Minh Khoa","matchedBy":"name",
   "ocrIdentity":{"cccd":"111","name":"Trần Minh Khoa"},"rosterIdentity":{"cccd":"222","name":"Trần Minh Khoa"},
   "review":{"done":True,"items":{}}},
  {"index":2,"name":"OK","matchedBy":"cccd",
   "ocrIdentity":{"cccd":"333","name":"OK"},"rosterIdentity":{"cccd":"333","name":"OK"},
   "review":{"done":True,"items":{"A2":{"seen":True,"flag":None}}}},
]}
MANIFESTS = {
  0: {"checks":[{"code":"A2","label":"Mã số thuế khớp bảng kê","tier":"detail","kind":"value",
                 "evidenceDocId":"contract","reference":"095204007694",
                 "source":{"docId":"contract","page":0,"value":"8391246072"},"autostatus":"mismatch"}],
      "docs":[{"id":"contract","label":"Hợp đồng dịch vụ"}]},
  1: {"checks":[],"docs":[]},
}

def test_only_needs_resubmit_packets_are_grouped():
    r = build_report(CASE, MANIFESTS, generated_at="2026-07-23T00:00:00Z")
    assert [g["name"] for g in r["groups"]] == ["Lê Thị Mai Anh", "Trần Minh Khoa"]  # index 2 clean excluded

def test_flagged_item_resolves_from_checks():
    r = build_report(CASE, MANIFESTS, generated_at="2026-07-23T00:00:00Z")
    it = r["groups"][0]["items"][0]
    assert it["fieldLabel"]=="Mã số thuế khớp bảng kê" and it["document"]=="Hợp đồng dịch vụ"
    assert it["page"]==1 and it["rosterValue"]=="095204007694" and it["docValue"]=="8391246072"
    assert it["reason"]=="sai" and it["note"]=="lệch số"

def test_weak_match_becomes_identity_issue():
    r = build_report(CASE, MANIFESTS, generated_at="2026-07-23T00:00:00Z")
    assert r["groups"][1]["identityIssue"] is True and r["groups"][1]["matchedBy"]=="name"

def test_markdown_and_csv_render():
    r = build_report(CASE, MANIFESTS, generated_at="2026-07-23T00:00:00Z")
    assert "Lê Thị Mai Anh" in r["markdown"] and "Mã số thuế" in r["markdown"]
    assert "khớp theo tên" in r["markdown"].lower()
    lines = r["csv"].splitlines()
    assert lines[0].startswith("CTV,CCCD,Trường,")
    assert any("Mã số thuế" in ln for ln in lines[1:])

def test_unread_source_value_falls_back_to_can_xem():
    case = {"name":"x","packets":[{"index":0,"name":"A","matchedBy":"cccd",
        "ocrIdentity":{"cccd":"1","name":"A"},"rosterIdentity":{"cccd":"1","name":"A"},
        "review":{"done":True,"items":{"B1":{"seen":True,"flag":{"reason":"","note":""}}}}}]}
    manifests = {0:{"checks":[{"code":"B1","label":"Họ tên","evidenceDocId":"c","reference":"Ng A",
        "source":None,"autostatus":"review"}],"docs":[{"id":"c","label":"HĐ"}]}}
    r = build_report(case, manifests, generated_at="t")
    assert r["groups"][0]["items"][0]["docValue"]=="cần xem"
