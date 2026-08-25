from fastapi.testclient import TestClient
import fitz
import hashlib
import io
import json
import os
from pathlib import Path
import time

import openpyxl
import pytest

import app as appmod
from app import app, rewrite_manifest_urls

def test_rewrite_manifest_urls_points_pages_at_api():
    m = {"docs": [{"pages": [{"src": "/abs/whatever/pg0.png", "width": 10, "height": 20}]}]}
    out = rewrite_manifest_urls(m, "/api/cases/C/packets/0")
    assert out["docs"][0]["pages"][0]["src"] == "/api/cases/C/packets/0/page/pg0.png"

def test_post_requires_pdf():
    assert TestClient(app).post("/api/cases").status_code == 422

def test_page_endpoint_rejects_traversal():
    c = TestClient(app)
    assert c.get("/api/cases/nope/packets/0/page/..%2f..%2fetc%2fpasswd").status_code in (400, 404)


def test_page_endpoint_serves_attached_jpeg(tmp_path, monkeypatch):
    client, cid = _ready_case(monkeypatch, tmp_path)
    packet_dir = tmp_path / cid / "packets" / "0"
    packet_dir.mkdir(parents=True, exist_ok=True)
    (packet_dir / "cccd-front.jpg").write_bytes(b"\xff\xd8\xff\xd9")

    response = client.get(
        f"/api/cases/{cid}/packets/0/page/cccd-front.jpg",
    )

    assert response.status_code == 200

def _fake_pipeline(
    pdf, roster, out_dir, cb, cccd_xlsx_path=None, confirmed_starts=None,
):
    cb("done", 1, 1, "")
    return {"summary": {"found": 1, "rosterN": 1, "autoMerged": 0},
            "packets": [{"index": 0, "name": "P0", "pages": [8, 15],
                         "confidence": "green", "flags": [], "labels": []}],
            "cccdWorkbook": None}


def _roster_bytes():
    content = io.BytesIO()
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.append(["Họ và tên", "Số CCCD"])
    worksheet.append(["Synthetic A", "000000000001"])
    workbook.save(content)
    workbook.close()
    return content.getvalue()

def _ready_case(monkeypatch, tmp_path):
    """Mirror the app's real flow: monkeypatch the pipeline to a fake that
    returns one packet, POST a case, and poll until it leaves `processing`."""
    monkeypatch.setattr(appmod, "run_pipeline", _fake_pipeline)
    monkeypatch.setattr(appmod, "store", appmod.CaseStore(str(tmp_path)))
    c = TestClient(app)
    r = c.post("/api/cases", files={"pdf": ("feb.pdf", b"%PDF-1.4 x", "application/pdf")})
    cid = r.json()["case_id"]; assert r.status_code == 200
    import time
    for _ in range(100):
        d = c.get(f"/api/cases/{cid}").json()
        if d["status"] in ("ready", "in_review", "done", "error"): break
        time.sleep(0.02)
    assert d["status"] == "ready" and len(d["packets"]) == 1
    return c, cid

def test_case_create_list_detail_review(tmp_path, monkeypatch):
    c, cid = _ready_case(monkeypatch, tmp_path)
    assert c.get("/api/cases").json()[0]["id"] == cid
    # review persists + flips status
    r = c.put(f"/api/cases/{cid}/packets/0/review", json={"done": True, "fields": {}})
    assert r.status_code == 200
    data = r.json()
    assert data["packet"]["review"]["done"] is True
    assert data["progress"]["done"] == 1
    assert c.get(f"/api/cases/{cid}").json()["status"] == "done"
    # delete
    assert c.delete(f"/api/cases/{cid}").status_code == 200
    assert c.get("/api/cases").json() == []

def test_case_and_review_responses_derive_field_count_without_persisting(
        tmp_path, monkeypatch):
    c, cid = _ready_case(monkeypatch, tmp_path)
    stored = appmod.store.get(cid)
    packet = {
        **stored["packets"][0],
        "pages": [8, 23],
        "n_pages": 16,
        "flags": ["length-out-of-range"],
    }
    appmod.store.set_result(
        cid,
        stored["summary"],
        [packet],
        stored.get("cccdWorkbook"),
    )
    packet_dir = tmp_path / cid / "packets" / "0"
    packet_dir.mkdir(parents=True)
    (packet_dir / "manifest.json").write_text(json.dumps({
        "fields": [{"key": "synthetic-a"}, {"key": "synthetic-b"}],
        "docs": [
            {"kind": "contract", "pages": [{"src": "/local/pg5.png"}]},
            {"kind": "contract", "pages": [{"src": "/local/pg13.png"}]},
            {"kind": "commitment", "pages": [{"src": "/local/pg15.png"}]},
        ],
    }), encoding="utf-8")

    detail = c.get(f"/api/cases/{cid}").json()
    assert detail["packets"][0]["reviewFieldCount"] == 2
    assert detail["packets"][0]["taxCommitmentDetected"] is True
    assert detail["packets"][0]["boundaryAssessment"] == {
        "status": "review",
        "suspectedMultiplePackets": True,
        "reasons": ["length-out-of-range", "multiple-contract-starts"],
        "candidateStarts": [13, 21],
    }

    updated = c.put(
        f"/api/cases/{cid}/packets/0/review",
        json={"done": False, "fields": {}, "rejection": None},
    ).json()
    assert updated["packet"]["reviewFieldCount"] == 2
    assert updated["packet"]["taxCommitmentDetected"] is True
    assert updated["packet"]["boundaryAssessment"] == (
        detail["packets"][0]["boundaryAssessment"]
    )
    assert "reviewFieldCount" not in appmod.store.get(cid)["packets"][0]
    assert "taxCommitmentDetected" not in appmod.store.get(cid)["packets"][0]
    assert "boundaryAssessment" not in appmod.store.get(cid)["packets"][0]

def test_case_response_uses_zero_field_count_when_manifest_is_missing(
        tmp_path, monkeypatch):
    c, cid = _ready_case(monkeypatch, tmp_path)
    detail = c.get(f"/api/cases/{cid}").json()
    assert detail["packets"][0]["reviewFieldCount"] == 0
    assert detail["packets"][0]["taxCommitmentDetected"] is False

def test_case_response_uses_zero_field_count_for_non_object_manifest(
        tmp_path, monkeypatch):
    c, cid = _ready_case(monkeypatch, tmp_path)
    packet_dir = tmp_path / cid / "packets" / "0"
    packet_dir.mkdir(parents=True)
    (packet_dir / "manifest.json").write_text("[]", encoding="utf-8")

    detail = c.get(f"/api/cases/{cid}")
    assert detail.status_code == 200
    assert detail.json()["packets"][0]["reviewFieldCount"] == 0


def test_case_response_tolerates_corrupt_legacy_manifest(tmp_path, monkeypatch):
    c, cid = _ready_case(monkeypatch, tmp_path)
    packet_dir = tmp_path / cid / "packets" / "0"
    packet_dir.mkdir(parents=True)
    (packet_dir / "manifest.json").write_text("{not-json", encoding="utf-8")

    detail = c.get(f"/api/cases/{cid}")

    assert detail.status_code == 200
    assert detail.json()["packets"][0]["reviewFieldCount"] == 0
    assert detail.json()["boundaryStatus"] == {
        "status": "clear", "packetIndexes": [], "reasons": [],
    }

def test_get_unknown_case_404():
    assert TestClient(app).get("/api/cases/nope").status_code == 404

def test_review_unknown_case_404():
    body = {"done": True, "fields": {}}
    assert TestClient(app).put("/api/cases/nope/packets/0/review", json=body).status_code == 404

def test_put_review_persists_and_updates_status(tmp_path, monkeypatch):
    c, cid = _ready_case(monkeypatch, tmp_path)
    body = {"done": True, "fields": {"cccd": {"seen": True,
            "flag": {"reason": "sai", "note": "x"}}}}
    r = c.put(f"/api/cases/{cid}/packets/0/review", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["packet"]["review"]["done"] is True
    assert data["progress"]["done"] >= 1

def test_put_review_defaults_rejection_to_null(tmp_path, monkeypatch):
    c, cid = _ready_case(monkeypatch, tmp_path)
    r = c.put(f"/api/cases/{cid}/packets/0/review",
              json={"done": False, "fields": {}})
    assert r.status_code == 200
    assert r.json()["packet"]["review"]["rejection"] is None

def test_put_review_validates_and_roundtrips_multiple_rejection_reasons(
        tmp_path, monkeypatch):
    c, cid = _ready_case(monkeypatch, tmp_path)
    url = f"/api/cases/{cid}/packets/0/review"
    assert c.put(url, json={
        "done": False, "fields": {},
        "rejection": {"reasons": [], "note": ""},
    }).status_code == 422
    assert c.put(url, json={
        "done": False, "fields": {},
        "rejection": {"reasons": ["not_a_reason"], "note": ""},
    }).status_code == 422

    r = c.put(url, json={
        "done": False,
        "fields": {"name": {"seen": True, "flag": None}},
        "rejection": {
            "reasons": ["missing_signature", "missing_documents"],
            "note": "  bổ sung  ",
        },
    })
    assert r.status_code == 200
    assert r.json()["packet"]["review"] == {
        "done": True,
        "fields": {"name": {"seen": True, "flag": None}},
        "rejection": {
            "reasons": ["missing_documents", "missing_signature"],
            "note": "bổ sung",
        },
    }

def test_report_endpoint_generates_and_persists(tmp_path, monkeypatch):
    c, cid = _ready_case(monkeypatch, tmp_path)
    c.put(f"/api/cases/{cid}/packets/0/review",
          json={"done": True, "fields": {"cccd": {"seen": True,
                "flag": {"reason": "sai", "note": "x"}}}})
    r = c.post(f"/api/cases/{cid}/report")
    assert r.status_code == 200
    assert "markdown" in r.json()
    md = c.get(f"/api/cases/{cid}/report.md")
    assert md.status_code == 200 and "Báo cáo" in md.text
    csv = c.get(f"/api/cases/{cid}/report.csv")
    assert csv.status_code == 200 and csv.text.startswith("CTV,CCCD,")


def test_case_boundary_review_blocks_publication_without_participant_resubmission(
        tmp_path, monkeypatch):
    c, cid = _ready_case(monkeypatch, tmp_path)
    stored = appmod.store.get(cid)
    packet = {
        **stored["packets"][0],
        "pages": [8, 23],
        "n_pages": 16,
        "flags": ["length-out-of-range"],
    }
    appmod.store.set_result(
        cid,
        stored["summary"],
        [packet],
        stored.get("cccdWorkbook"),
    )
    packet_dir = tmp_path / cid / "packets" / "0"
    packet_dir.mkdir(parents=True)
    (packet_dir / "manifest.json").write_text(json.dumps({
        "docs": [
            {"kind": "contract", "pages": [{"src": "/local/pg0.png"}]},
            {"kind": "contract", "pages": [{"src": "/local/pg8.png"}]},
        ],
    }), encoding="utf-8")

    detail = c.get(f"/api/cases/{cid}").json()
    assert detail["boundaryStatus"] == {
        "status": "review",
        "packetIndexes": [0],
        "reasons": ["length-out-of-range", "multiple-contract-starts"],
    }
    assert detail["publicationBlocked"] is True

    report = c.post(f"/api/cases/{cid}/report").json()
    assert report["groups"] == []
    assert report["boundaryWarnings"] == [{
        "packetIndex": 0,
        "packetNumber": 1,
        "reasons": ["length-out-of-range", "multiple-contract-starts"],
    }]


def _write_pdf(path, page_count=6):
    document = fitz.open()
    for _ in range(page_count):
        document.new_page()
    document.save(path)
    document.close()


def _ready_ambiguous_case(monkeypatch, tmp_path, *, with_workbooks=False):
    monkeypatch.setattr(appmod, "store", appmod.CaseStore(str(tmp_path)))
    cid = appmod.store.create(
        "synthetic.pdf",
        "synthetic.pdf",
        "synthetic-roster.xlsx" if with_workbooks else None,
        "2026-08-25T00:00:00+00:00",
        cccd_name="synthetic-cccd.xlsx" if with_workbooks else None,
    )
    appmod.store.set_result(
        cid,
        {"found": 1, "roster_n": 2},
        [{
            "index": 0,
            "name": "Synthetic A",
            "pages": [0, 5],
            "n_pages": 6,
            "confidence": "yellow",
            "flags": ["length-out-of-range"],
            "labels": [],
        }],
    )
    appmod.store.set_review(
        cid,
        0,
        {"done": True, "fields": {"amount": {"seen": True, "flag": None}}},
    )
    case_dir = tmp_path / cid
    _write_pdf(case_dir / "input.pdf")
    if with_workbooks:
        (case_dir / "roster.xlsx").write_bytes(b"synthetic-roster")
        (case_dir / "cccd.xlsx").write_bytes(b"synthetic-cccd")
    packet_dir = case_dir / "packets" / "0"
    packet_dir.mkdir(parents=True)
    (packet_dir / "manifest.json").write_text(json.dumps({
        "docs": [
            {"kind": "contract", "pages": [{"src": "/private/pg0.png"}]},
            {"kind": "contract", "pages": [{"src": "/private/pg3.png"}]},
        ],
        "fields": [{"key": "amount", "observed": "private-value"}],
    }), encoding="utf-8")
    return TestClient(app), cid


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, False), ("", False), ("true", False), ("01", False), ("1 ", False), ("1", True)],
)
def test_boundary_correction_startup_flag_accepts_only_exact_one(value, expected):
    assert appmod._boundary_correction_enabled(value) is expected


def test_boundary_proposal_get_remains_available_in_shadow_mode(tmp_path, monkeypatch):
    client, cid = _ready_ambiguous_case(monkeypatch, tmp_path)
    monkeypatch.setattr(appmod, "BOUNDARY_CORRECTION_ENABLED", False, raising=False)

    response = client.get(f"/api/cases/{cid}/boundary-proposal")

    assert response.status_code == 200
    assert response.json() == {
        "status": "review_required",
        "sourceCaseId": cid,
        "expectedPacketCount": 2,
        "currentPacketCount": 1,
        "candidateStarts": [
            {
                "page": 0,
                "signals": ["contract-title", "visual"],
                "confidence": "medium",
                "packetIndex": 0,
                "relativePage": 0,
            },
            {
                "page": 3,
                "signals": ["contract-title", "cadence"],
                "confidence": "high",
                "packetIndex": 0,
                "relativePage": 3,
            },
        ],
        "affectedPacketIndexes": [0],
        "affectedRanges": [{
            "packetIndex": 0,
            "startPage": 0,
            "endPage": 5,
        }],
        "correctionEnabled": False,
    }
    assert "private-value" not in response.text
    assert "/private/" not in response.text


def test_boundary_proposal_unknown_case_returns_404(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "store", appmod.CaseStore(str(tmp_path)))
    response = TestClient(app).get("/api/cases/missing/boundary-proposal")
    assert response.status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"action": "keep-current"},
        {"action": "create-revision", "starts": [0, 3]},
    ],
)
def test_disabled_boundary_resolution_returns_409_before_store_or_file_mutation(
    tmp_path, monkeypatch, body,
):
    client, cid = _ready_ambiguous_case(monkeypatch, tmp_path)
    monkeypatch.setattr(appmod, "BOUNDARY_CORRECTION_ENABLED", False, raising=False)
    monkeypatch.setattr(
        appmod.store,
        "get",
        lambda *_: (_ for _ in ()).throw(AssertionError("store read after disabled gate")),
    )
    monkeypatch.setattr(
        appmod.shutil,
        "copy2",
        lambda *_: (_ for _ in ()).throw(AssertionError("copy after disabled gate")),
    )

    response = client.post(
        f"/api/cases/{cid}/boundary-proposal/resolve",
        json=body,
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "boundary-correction-disabled"}


@pytest.mark.parametrize(
    "body",
    [
        {"action": "create-revision"},
        {"action": "keep-current", "starts": [0, 3]},
        {"action": "create-revision", "starts": [0, True]},
        {"action": "create-revision", "starts": [0, "3"]},
        {"action": "create-revision", "starts": [0, 3.0]},
    ],
)
def test_boundary_resolution_body_rejects_action_start_mismatches_and_non_integers(
    tmp_path, monkeypatch, body,
):
    client, cid = _ready_ambiguous_case(monkeypatch, tmp_path)
    monkeypatch.setattr(appmod, "BOUNDARY_CORRECTION_ENABLED", True, raising=False)

    response = client.post(
        f"/api/cases/{cid}/boundary-proposal/resolve",
        json=body,
    )

    assert response.status_code == 422
    assert appmod.store.get(cid)["boundaryResolution"] is None


@pytest.mark.parametrize(
    ("starts", "code"),
    [
        ([0, 3, 3], "boundary-starts-invalid"),
        ([0, 4, 3], "boundary-starts-invalid"),
        ([1, 3], "boundary-preamble-invalid"),
        ([0, 6], "boundary-starts-out-of-range"),
    ],
)
def test_create_revision_maps_invalid_starts_to_stable_422(
    tmp_path, monkeypatch, starts, code,
):
    client, cid = _ready_ambiguous_case(monkeypatch, tmp_path)
    monkeypatch.setattr(appmod, "BOUNDARY_CORRECTION_ENABLED", True, raising=False)

    response = client.post(
        f"/api/cases/{cid}/boundary-proposal/resolve",
        json={"action": "create-revision", "starts": starts},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {"code": code}
    assert appmod.store.get(cid)["revisionIds"] == []


def test_boundary_resolution_unknown_case_returns_404_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "store", appmod.CaseStore(str(tmp_path)))
    monkeypatch.setattr(appmod, "BOUNDARY_CORRECTION_ENABLED", True, raising=False)
    response = TestClient(app).post(
        "/api/cases/missing/boundary-proposal/resolve",
        json={"action": "keep-current"},
    )
    assert response.status_code == 404


@pytest.mark.parametrize("lifecycle_status", ["processing", "error"])
def test_unfinished_case_cannot_record_a_first_keep_current_resolution(
    tmp_path, monkeypatch, lifecycle_status,
):
    client, cid = _ready_ambiguous_case(monkeypatch, tmp_path)
    monkeypatch.setattr(appmod, "BOUNDARY_CORRECTION_ENABLED", True, raising=False)
    stored = appmod.store.get(cid)
    stored["status"] = lifecycle_status
    if lifecycle_status == "error":
        stored["error"] = "synthetic-processing-error"
    appmod.store._write(stored)

    assert appmod.store.get(cid)["status"] == lifecycle_status

    response = client.post(
        f"/api/cases/{cid}/boundary-proposal/resolve",
        json={"action": "keep-current"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "boundary-resolution-not-reviewable",
    }
    assert appmod.store.get(cid)["boundaryResolution"] is None
    assert appmod.store.get(cid)["revisionIds"] == []


def test_clear_ready_case_cannot_record_a_first_boundary_resolution(
    tmp_path, monkeypatch,
):
    client, cid = _ready_ambiguous_case(monkeypatch, tmp_path)
    monkeypatch.setattr(appmod, "BOUNDARY_CORRECTION_ENABLED", True, raising=False)
    stored = appmod.store.get(cid)
    appmod.store.set_result(
        cid,
        {"found": 1, "roster_n": 1},
        [{
            **stored["packets"][0],
            "flags": [],
            "n_pages": 6,
        }],
    )
    appmod.store.set_review(
        cid,
        0,
        {"done": False, "fields": {}, "rejection": None},
    )
    manifest_path = tmp_path / cid / "packets" / "0" / "manifest.json"
    manifest_path.write_text(json.dumps({
        "docs": [{
            "kind": "contract",
            "pages": [{"src": "/private/pg0.png"}],
        }],
    }), encoding="utf-8")

    assert appmod.store.get(cid)["status"] == "ready"

    response = client.post(
        f"/api/cases/{cid}/boundary-proposal/resolve",
        json={"action": "keep-current"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "boundary-resolution-not-reviewable",
    }
    assert appmod.store.get(cid)["boundaryResolution"] is None
    assert appmod.store.get(cid)["revisionIds"] == []


def test_review_required_ready_case_remains_eligible_for_first_resolution(
    tmp_path, monkeypatch,
):
    client, cid = _ready_ambiguous_case(monkeypatch, tmp_path)
    monkeypatch.setattr(appmod, "BOUNDARY_CORRECTION_ENABLED", True, raising=False)
    appmod.store.set_review(
        cid,
        0,
        {"done": False, "fields": {}, "rejection": None},
    )

    assert appmod.store.get(cid)["status"] == "ready"

    response = client.post(
        f"/api/cases/{cid}/boundary-proposal/resolve",
        json={"action": "keep-current"},
    )

    assert appmod.store.get(cid)["status"] == "ready"
    assert response.status_code == 200
    assert response.json()["status"] == "accepted_current"
    assert appmod.store.get(cid)["boundaryResolution"]["action"] == "keep-current"


def test_keep_current_records_resolution_without_reprocessing(tmp_path, monkeypatch):
    client, cid = _ready_ambiguous_case(monkeypatch, tmp_path)
    monkeypatch.setattr(appmod, "BOUNDARY_CORRECTION_ENABLED", True, raising=False)
    monkeypatch.setattr(
        appmod,
        "run_pipeline",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("pipeline reran")),
    )
    before_review = json.dumps(appmod.store.get(cid)["packets"][0]["review"], sort_keys=True)

    response = client.post(
        f"/api/cases/{cid}/boundary-proposal/resolve",
        json={"action": "keep-current"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "caseId": cid,
        "sourceCaseId": cid,
        "status": "accepted_current",
    }
    resolution = appmod.store.get(cid)["boundaryResolution"]
    assert resolution["action"] == "keep-current"
    assert resolution["starts"] == [0, 3]
    assert resolution["reasons"] == [
        "length-out-of-range", "multiple-contract-starts", "batch-count-mismatch",
    ]
    assert resolution["resolvedAt"].endswith("+00:00")
    assert json.dumps(appmod.store.get(cid)["packets"][0]["review"], sort_keys=True) == before_review
    proposal = client.get(f"/api/cases/{cid}/boundary-proposal").json()
    assert proposal["status"] == "accepted_current"
    detail = client.get(f"/api/cases/{cid}").json()
    assert detail["boundaryStatus"]["status"] == "accepted"
    assert detail["publicationBlocked"] is False
    assert detail["packets"][0]["boundaryAssessment"]["status"] == "accepted"


def test_create_revision_copies_only_inputs_reprocesses_exact_starts_and_stamps_revision(
    tmp_path, monkeypatch,
):
    client, cid = _ready_ambiguous_case(monkeypatch, tmp_path, with_workbooks=True)
    monkeypatch.setattr(appmod, "BOUNDARY_CORRECTION_ENABLED", True, raising=False)
    source_dir = tmp_path / cid
    source_hashes = {
        name: hashlib.sha256((source_dir / name).read_bytes()).hexdigest()
        for name in ("input.pdf", "roster.xlsx", "cccd.xlsx")
    }
    source_review = json.dumps(appmod.store.get(cid)["packets"][0]["review"], sort_keys=True)
    seen = {}

    def fake_pipeline(
        pdf, roster, out_dir, cb, cccd_xlsx_path=None, confirmed_starts=None,
    ):
        seen["paths"] = (
            os.path.basename(pdf),
            os.path.basename(roster),
            os.path.basename(cccd_xlsx_path),
        )
        seen["starts"] = confirmed_starts
        seen["initial_files"] = sorted(
            str(path.relative_to(out_dir))
            for path in Path(out_dir).rglob("*")
            if path.is_file()
        )
        packets = []
        for index, (start, end) in enumerate(((0, 2), (3, 5))):
            packet_dir = Path(out_dir) / "packets" / str(index)
            packet_dir.mkdir(parents=True)
            (packet_dir / "manifest.json").write_text(
                json.dumps({"docs": [], "fields": [{"key": "synthetic"}]}),
                encoding="utf-8",
            )
            packets.append({
                "index": index,
                "name": f"Synthetic {index}",
                "pages": [start, end],
                "n_pages": end - start + 1,
                "confidence": "green",
                "flags": [],
                "labels": [],
            })
        cb("done", 2, 2, "")
        return {
            "summary": {"found": 2, "boundary_source": "reviewer-confirmed"},
            "packets": packets,
            "cccdWorkbook": None,
        }

    monkeypatch.setattr(appmod, "run_pipeline", fake_pipeline)
    response = client.post(
        f"/api/cases/{cid}/boundary-proposal/resolve",
        json={"action": "create-revision", "starts": [0, 3]},
    )

    assert response.status_code == 200
    revision_id = response.json()["caseId"]
    assert response.json() == {
        "caseId": revision_id,
        "sourceCaseId": cid,
        "status": "processing",
    }
    for _ in range(100):
        revised = appmod.store.get(revision_id)
        if revised["status"] != "processing":
            break
        time.sleep(0.02)
    assert revised["status"] == "ready"
    assert revised["sourceCaseId"] == cid
    assert revised["revisionNumber"] == 1
    assert appmod.store.get(cid)["revisionIds"] == [revision_id]
    assert seen["starts"] == (0, 3)
    assert seen["paths"] == ("input.pdf", "roster.xlsx", "cccd.xlsx")
    assert seen["initial_files"] == ["case.json", "cccd.xlsx", "input.pdf", "roster.xlsx"]
    assert all(packet["packetRevision"] == 1 for packet in revised["packets"])
    assert all(packet["review"] == {
        "done": False, "fields": {}, "rejection": None,
    } for packet in revised["packets"])
    for packet in revised["packets"]:
        manifest = json.loads(
            (tmp_path / revision_id / "packets" / str(packet["index"]) / "manifest.json")
            .read_text(encoding="utf-8")
        )
        assert manifest["packetRevision"] == 1
    assert json.dumps(appmod.store.get(cid)["packets"][0]["review"], sort_keys=True) == source_review
    assert {
        name: hashlib.sha256((source_dir / name).read_bytes()).hexdigest()
        for name in source_hashes
    } == source_hashes
    assert client.get(f"/api/cases/{cid}/boundary-proposal").json()["status"] == "superseded"


def test_repeat_create_revision_returns_recorded_revision_without_copy_or_pipeline(
    tmp_path, monkeypatch,
):
    client, cid = _ready_ambiguous_case(monkeypatch, tmp_path)
    monkeypatch.setattr(appmod, "BOUNDARY_CORRECTION_ENABLED", True, raising=False)
    calls = {"pipeline": 0}

    def fake_pipeline(pdf, roster, out_dir, cb, cccd_xlsx_path=None, confirmed_starts=None):
        calls["pipeline"] += 1
        cb("done", 1, 1, "")
        return {"summary": {"found": 0}, "packets": [], "cccdWorkbook": None}

    monkeypatch.setattr(appmod, "run_pipeline", fake_pipeline)
    first = client.post(
        f"/api/cases/{cid}/boundary-proposal/resolve",
        json={"action": "create-revision", "starts": [0, 3]},
    )
    assert first.status_code == 200
    revision_id = first.json()["caseId"]
    for _ in range(100):
        if appmod.store.get(revision_id)["status"] != "processing":
            break
        time.sleep(0.02)
    case_path = tmp_path / cid / "case.json"
    recorded_bytes = case_path.read_bytes()
    monkeypatch.setattr(
        appmod.shutil,
        "copy2",
        lambda *_: (_ for _ in ()).throw(AssertionError("idempotent retry copied")),
    )

    second = client.post(
        f"/api/cases/{cid}/boundary-proposal/resolve",
        json={"action": "create-revision", "starts": [0, 3]},
    )

    assert second.status_code == 200
    assert second.json() == {
        "caseId": revision_id,
        "sourceCaseId": cid,
        "status": "processing",
    }
    assert case_path.read_bytes() == recorded_bytes
    assert appmod.store.get(cid)["revisionIds"] == [revision_id]
    assert calls["pipeline"] == 1


def _install_empty_revision_pipeline(monkeypatch):
    calls = {"pipeline": 0}

    def fake_pipeline(pdf, roster, out_dir, cb, cccd_xlsx_path=None, confirmed_starts=None):
        calls["pipeline"] += 1
        cb("done", 1, 1, "")
        return {"summary": {"found": 0}, "packets": [], "cccdWorkbook": None}

    monkeypatch.setattr(appmod, "run_pipeline", fake_pipeline)
    return calls


def test_create_then_keep_current_conflict_preserves_recorded_revision(tmp_path, monkeypatch):
    client, cid = _ready_ambiguous_case(monkeypatch, tmp_path)
    monkeypatch.setattr(appmod, "BOUNDARY_CORRECTION_ENABLED", True, raising=False)
    calls = _install_empty_revision_pipeline(monkeypatch)
    created = client.post(
        f"/api/cases/{cid}/boundary-proposal/resolve",
        json={"action": "create-revision", "starts": [0, 3]},
    )
    assert created.status_code == 200
    revision_id = created.json()["caseId"]
    recorded = json.dumps(appmod.store.get(cid)["boundaryResolution"], sort_keys=True)

    conflict = client.post(
        f"/api/cases/{cid}/boundary-proposal/resolve",
        json={"action": "keep-current"},
    )

    assert conflict.status_code == 409
    assert conflict.json()["detail"] == {"code": "boundary-resolution-conflict"}
    assert json.dumps(appmod.store.get(cid)["boundaryResolution"], sort_keys=True) == recorded
    assert appmod.store.get(cid)["revisionIds"] == [revision_id]
    assert calls["pipeline"] == 1


def test_keep_current_then_create_conflict_creates_no_revision(tmp_path, monkeypatch):
    client, cid = _ready_ambiguous_case(monkeypatch, tmp_path)
    monkeypatch.setattr(appmod, "BOUNDARY_CORRECTION_ENABLED", True, raising=False)
    calls = _install_empty_revision_pipeline(monkeypatch)
    kept = client.post(
        f"/api/cases/{cid}/boundary-proposal/resolve",
        json={"action": "keep-current"},
    )
    assert kept.status_code == 200
    recorded = json.dumps(appmod.store.get(cid)["boundaryResolution"], sort_keys=True)

    conflict = client.post(
        f"/api/cases/{cid}/boundary-proposal/resolve",
        json={"action": "create-revision", "starts": [0, 3]},
    )

    assert conflict.status_code == 409
    assert conflict.json()["detail"] == {"code": "boundary-resolution-conflict"}
    assert json.dumps(appmod.store.get(cid)["boundaryResolution"], sort_keys=True) == recorded
    assert appmod.store.get(cid)["revisionIds"] == []
    assert calls["pipeline"] == 0


def test_malformed_repeated_create_is_validated_before_idempotent_return(tmp_path, monkeypatch):
    client, cid = _ready_ambiguous_case(monkeypatch, tmp_path)
    monkeypatch.setattr(appmod, "BOUNDARY_CORRECTION_ENABLED", True, raising=False)
    calls = _install_empty_revision_pipeline(monkeypatch)
    created = client.post(
        f"/api/cases/{cid}/boundary-proposal/resolve",
        json={"action": "create-revision", "starts": [0, 3]},
    )
    revision_id = created.json()["caseId"]
    recorded = json.dumps(appmod.store.get(cid)["boundaryResolution"], sort_keys=True)

    malformed = client.post(
        f"/api/cases/{cid}/boundary-proposal/resolve",
        json={"action": "create-revision", "starts": [0, 3, 3]},
    )

    assert malformed.status_code == 422
    assert malformed.json()["detail"] == {"code": "boundary-starts-invalid"}
    assert json.dumps(appmod.store.get(cid)["boundaryResolution"], sort_keys=True) == recorded
    assert appmod.store.get(cid)["revisionIds"] == [revision_id]
    assert calls["pipeline"] == 1


def test_different_valid_starts_conflict_with_recorded_create(tmp_path, monkeypatch):
    client, cid = _ready_ambiguous_case(monkeypatch, tmp_path)
    monkeypatch.setattr(appmod, "BOUNDARY_CORRECTION_ENABLED", True, raising=False)
    calls = _install_empty_revision_pipeline(monkeypatch)
    created = client.post(
        f"/api/cases/{cid}/boundary-proposal/resolve",
        json={"action": "create-revision", "starts": [0, 3]},
    )
    revision_id = created.json()["caseId"]
    recorded = json.dumps(appmod.store.get(cid)["boundaryResolution"], sort_keys=True)

    conflict = client.post(
        f"/api/cases/{cid}/boundary-proposal/resolve",
        json={"action": "create-revision", "starts": [0, 2, 4]},
    )

    assert conflict.status_code == 409
    assert conflict.json()["detail"] == {"code": "boundary-resolution-conflict"}
    assert json.dumps(appmod.store.get(cid)["boundaryResolution"], sort_keys=True) == recorded
    assert appmod.store.get(cid)["revisionIds"] == [revision_id]
    assert calls["pipeline"] == 1


def test_exact_keep_current_retry_returns_recorded_result_without_rewriting(tmp_path, monkeypatch):
    client, cid = _ready_ambiguous_case(monkeypatch, tmp_path)
    monkeypatch.setattr(appmod, "BOUNDARY_CORRECTION_ENABLED", True, raising=False)
    first = client.post(
        f"/api/cases/{cid}/boundary-proposal/resolve",
        json={"action": "keep-current"},
    )
    assert first.status_code == 200
    case_path = tmp_path / cid / "case.json"
    recorded_bytes = case_path.read_bytes()

    repeated = client.post(
        f"/api/cases/{cid}/boundary-proposal/resolve",
        json={"action": "keep-current"},
    )

    assert repeated.status_code == 200
    assert repeated.json() == first.json() == {
        "caseId": cid,
        "sourceCaseId": cid,
        "status": "accepted_current",
    }
    assert case_path.read_bytes() == recorded_bytes
    assert appmod.store.get(cid)["revisionIds"] == []


def test_revision_copy_failure_marks_revision_only_with_safe_error(tmp_path, monkeypatch):
    client, cid = _ready_ambiguous_case(monkeypatch, tmp_path)
    monkeypatch.setattr(appmod, "BOUNDARY_CORRECTION_ENABLED", True, raising=False)
    source_before = json.dumps(appmod.store.get(cid)["packets"], sort_keys=True)
    source_pdf_hash = hashlib.sha256((tmp_path / cid / "input.pdf").read_bytes()).hexdigest()
    monkeypatch.setattr(
        appmod.shutil,
        "copy2",
        lambda *_: (_ for _ in ()).throw(OSError("/private/path and identity")),
    )

    response = client.post(
        f"/api/cases/{cid}/boundary-proposal/resolve",
        json={"action": "create-revision", "starts": [0, 3]},
    )

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "boundary-revision-copy-failed"
    revision_id = appmod.store.get(cid)["revisionIds"][0]
    revision = appmod.store.get(revision_id)
    assert revision["status"] == "error"
    assert revision["error"] == "boundary-revision-copy-failed"
    assert appmod.store.get(cid)["boundaryResolution"] is None
    assert json.dumps(appmod.store.get(cid)["packets"], sort_keys=True) == source_before
    assert hashlib.sha256((tmp_path / cid / "input.pdf").read_bytes()).hexdigest() == source_pdf_hash
    assert "/private/path" not in response.text


def test_revision_pipeline_failure_is_sanitized_without_changing_source(tmp_path, monkeypatch):
    client, cid = _ready_ambiguous_case(monkeypatch, tmp_path)
    monkeypatch.setattr(appmod, "BOUNDARY_CORRECTION_ENABLED", True, raising=False)
    source_before = json.dumps(appmod.store.get(cid)["packets"], sort_keys=True)

    def failing_pipeline(*_args, **_kwargs):
        raise RuntimeError("/private/path Synthetic Person 000000000001")

    monkeypatch.setattr(appmod, "run_pipeline", failing_pipeline)
    response = client.post(
        f"/api/cases/{cid}/boundary-proposal/resolve",
        json={"action": "create-revision", "starts": [0, 3]},
    )
    assert response.status_code == 200
    revision_id = response.json()["caseId"]
    for _ in range(100):
        revision = appmod.store.get(revision_id)
        if revision["status"] != "processing":
            break
        time.sleep(0.02)

    assert revision["status"] == "error"
    assert revision["error"] == "boundary-revision-processing-failed"
    assert "/private/path" not in json.dumps(revision)
    assert "000000000001" not in json.dumps(revision)
    assert json.dumps(appmod.store.get(cid)["packets"], sort_keys=True) == source_before

def test_report_404_before_generation(tmp_path, monkeypatch):
    c, cid = _ready_case(monkeypatch, tmp_path)
    assert c.get(f"/api/cases/{cid}/report.md").status_code == 404
    assert c.get(f"/api/cases/{cid}/report.csv").status_code == 404


def test_cccd_without_roster_returns_422_and_creates_no_case(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(appmod, "store", appmod.CaseStore(str(tmp_path)))

    response = TestClient(app).post(
        "/api/cases",
        files={
            "pdf": ("packet.pdf", b"%PDF-1.4 synthetic", "application/pdf"),
            "cccd": (
                "cards.xlsx",
                b"synthetic-not-read",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "cccd-requires-roster"
    assert list(tmp_path.iterdir()) == []


def test_invalid_cccd_extension_is_rejected_before_case_creation(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(appmod, "store", appmod.CaseStore(str(tmp_path)))

    response = TestClient(app).post(
        "/api/cases",
        files={
            "pdf": ("packet.pdf", b"%PDF-1.4 synthetic", "application/pdf"),
            "roster": (
                "roster.xlsx",
                _roster_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
            "cccd": ("cards.xls", b"synthetic", "application/octet-stream"),
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid-cccd-workbook"
    assert list(tmp_path.iterdir()) == []


def test_valid_cccd_upload_is_saved_passed_to_pipeline_and_redacted(
    tmp_path,
    monkeypatch,
):
    seen = {}
    workbook = {
        "status": "ready",
        "summary": {"candidates": 3, "attached": 2, "unresolved": 1},
        "mappings": [{
            "candidateId": "card-private",
            "ocrIdentity": {"cccd": "000000000001"},
        }],
    }

    def fake_pipeline(
        pdf, roster, out_dir, cb, cccd_xlsx_path=None, confirmed_starts=None,
    ):
        seen["cccd"] = cccd_xlsx_path
        seen["cccd_exists"] = os.path.isfile(cccd_xlsx_path)
        cb("done", 1, 1, "")
        return {
            "summary": {"found": 1, "rosterN": 1, "autoMerged": 0},
            "packets": [{
                "index": 0,
                "name": "P0",
                "pages": [0, 1],
                "confidence": "green",
                "flags": [],
                "labels": [],
            }],
            "cccdWorkbook": workbook,
        }

    monkeypatch.setattr(appmod, "run_pipeline", fake_pipeline)
    monkeypatch.setattr(appmod, "store", appmod.CaseStore(str(tmp_path)))
    client = TestClient(app)
    response = client.post(
        "/api/cases",
        files={
            "pdf": ("packet.pdf", b"%PDF-1.4 synthetic", "application/pdf"),
            "roster": (
                "roster.xlsx",
                _roster_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
            "cccd": (
                "cards.xlsx",
                b"synthetic-workbook",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        },
    )
    assert response.status_code == 200
    cid = response.json()["case_id"]
    for _ in range(100):
        detail = client.get(f"/api/cases/{cid}").json()
        if detail["status"] != "processing":
            break
        time.sleep(.02)

    assert detail["status"] == "ready"
    assert seen["cccd_exists"] is True
    assert seen["cccd"].endswith("/cccd.xlsx")
    assert detail["cccdName"] == "cards.xlsx"
    assert detail["cccdSummary"] == {
        "status": "ready",
        "candidates": 3,
        "attached": 2,
        "unresolved": 1,
    }
    assert "cccdWorkbook" not in detail
    assert "card-private" not in json.dumps(detail)

if __name__ == "__main__":
    # minimal manual runner (monkeypatch/tmp_path tests need pytest; run those with: python3 -m pytest server/app_test.py)
    test_rewrite_manifest_urls_points_pages_at_api(); print("  ok rewrite")
    test_post_requires_pdf(); print("  ok requires-pdf")
    test_page_endpoint_rejects_traversal(); print("  ok traversal")
    test_get_unknown_case_404(); print("  ok get-unknown-404")
    test_review_unknown_case_404(); print("  ok review-unknown-404")
    print("BASIC OK (run monkeypatch tests via pytest)")
