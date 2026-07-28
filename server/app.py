"""FastAPI backend: accepts an uploaded scanned PDF (+ optional roster), runs
split -> OCR/extract on a background thread with progress, and serves the
per-packet CtvFolder manifests + rendered page PNGs the frontend consumes.

Binds 127.0.0.1 only (run via `uvicorn app:app --host 127.0.0.1`). Each
upload becomes a durable **case** under `server/data/cases/<id>/` (see
`cases.py`) — unlike the old temp-dir job store, this survives a backend
restart: `case.json` holds the metadata + per-packet reviews, and
`packets/<i>/` holds that packet's manifest + rendered pages. Never commit
`server/data` — see server/README.md for the full PII note.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import zipfile
from copy import deepcopy
from datetime import datetime, timezone

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import threading

import checklist
import greennode
import recap
from cases import CaseStore, compact_cccd_summary, progress_of
from cccd_workbook import MAX_WORKBOOK_BYTES as MAX_CCCD_WORKBOOK_BYTES
from pipeline import run_pipeline  # noqa: F401 - referenced as `run_pipeline` at call
                                    # time below so tests can monkeypatch this name.
from report import build_report

app = FastAPI()

# Dev origins only: the Vite dev server's default port plus its usual
# fallbacks when 5173 is taken, on both localhost and 127.0.0.1.
_DEV_ORIGINS = [
    f"http://{host}:{port}"
    for host in ("localhost", "127.0.0.1")
    for port in (5173, 5174, 5175)
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_DEV_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

store = CaseStore(os.path.join(os.path.dirname(__file__), "data", "cases"))

# Live progress while a case is `processing` (not persisted — it's transient
# and only meaningful for the in-flight run); keyed by case id.
_progress: dict[str, dict] = {}

_PAGE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+\.png$")


def rewrite_manifest_urls(manifest: dict, base: str) -> dict:
    """Point every page's `src` at `{base}/page/{basename}`.

    `ocr_extract.render_pages` writes `src` as an absolute on-disk path (fine
    for the offline/no-server use case); the server instead exposes pages
    under the case/packet-scoped page endpoint, keyed by basename only.
    """
    out = deepcopy(manifest)
    for doc in out.get("docs", []):
        for page in doc.get("pages", []):
            page["src"] = f"{base}/page/{os.path.basename(page['src'])}"
    return out


def _upload_size(upload: UploadFile) -> int:
    upload.file.seek(0, os.SEEK_END)
    size = upload.file.tell()
    upload.file.seek(0)
    return size


def _validate_cccd_upload(
    roster: UploadFile | None,
    cccd: UploadFile | None,
) -> None:
    if cccd is None:
        return
    if roster is None:
        raise HTTPException(
            status_code=422,
            detail={"code": "cccd-requires-roster"},
        )
    if not _is_xlsx_upload(roster):
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid-roster-workbook"},
        )
    if not (cccd.filename or "").casefold().endswith(".xlsx"):
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid-cccd-workbook"},
        )
    if _upload_size(cccd) > MAX_CCCD_WORKBOOK_BYTES:
        raise HTTPException(
            status_code=413,
            detail={"code": "cccd-workbook-too-large"},
        )


def _is_xlsx_upload(upload: UploadFile) -> bool:
    if not (upload.filename or "").casefold().endswith(".xlsx"):
        return False
    try:
        upload.file.seek(0)
        with zipfile.ZipFile(upload.file) as archive:
            archive.getinfo("[Content_Types].xml")
            archive.getinfo("xl/workbook.xml")
        return True
    except (KeyError, OSError, zipfile.BadZipFile, zipfile.LargeZipFile):
        return False
    finally:
        upload.file.seek(0)


def _run_case(
    cid: str,
    pdf_path: str,
    roster_path: str | None,
    cccd_path: str | None = None,
) -> None:
    case_dir = store.case_dir(cid)

    def cb(stage: str, done: int, total: int, detail: str) -> None:
        _progress[cid] = {"stage": stage, "done": done, "total": total, "detail": detail}

    try:
        result = run_pipeline(
            pdf_path,
            roster_path,
            case_dir,
            cb,
            cccd_xlsx_path=cccd_path,
        )
        store.set_result(
            cid,
            summary=result.get("summary"),
            packets=result.get("packets", []),
            cccd_workbook=result.get("cccdWorkbook"),
        )
    except Exception as error:  # noqa: BLE001 - surfaced to the caller via case["error"]
        store.set_error(cid, str(error))
    finally:
        _progress.pop(cid, None)


@app.post("/api/cases")
async def post_case(
    pdf: UploadFile = File(...),
    roster: UploadFile | None = File(None),
    cccd: UploadFile | None = File(None),
):
    _validate_cccd_upload(roster, cccd)
    now = datetime.now(timezone.utc).isoformat()
    cid = store.create(name=pdf.filename or "case", pdf_name=pdf.filename or "input.pdf",
                        roster_name=roster.filename if roster is not None else None, now=now,
                        cccd_name=cccd.filename if cccd is not None else None)
    case_dir = store.case_dir(cid)

    pdf_path = os.path.join(case_dir, "input.pdf")
    with open(pdf_path, "wb") as f:
        shutil.copyfileobj(pdf.file, f)

    roster_path = None
    if roster is not None:
        roster_path = os.path.join(case_dir, "roster.xlsx")
        with open(roster_path, "wb") as f:
            shutil.copyfileobj(roster.file, f)

    cccd_path = None
    if cccd is not None:
        cccd_path = os.path.join(case_dir, "cccd.xlsx")
        with open(cccd_path, "wb") as f:
            shutil.copyfileobj(cccd.file, f)

    t = threading.Thread(target=_run_case, args=(cid, pdf_path, roster_path, cccd_path), daemon=True)
    t.start()
    return {"case_id": cid}


@app.get("/api/cases")
async def list_cases():
    return store.list()


@app.get("/api/cases/{cid}")
async def get_case(cid: str):
    case = store.get(cid)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    out = dict(case)
    out.pop("cccdWorkbook", None)
    out["cccdSummary"] = compact_cccd_summary(case.get("cccdWorkbook"))
    out["progress"] = progress_of(case["packets"])
    if case["status"] == "processing" and cid in _progress:
        out["liveProgress"] = _progress[cid]
    return out


class ReviewBody(BaseModel):
    done: bool = False
    items: dict = {}


@app.put("/api/cases/{cid}/packets/{i}/review")
async def put_review(cid: str, i: int, body: ReviewBody):
    updated = store.set_review(cid, i, {"done": body.done, "items": body.items})
    if updated is None:
        raise HTTPException(status_code=404, detail="case or packet not found")
    packet = next((p for p in updated["packets"] if p["index"] == i), None)
    return {"packet": packet, "progress": progress_of(updated["packets"]),
            "status": updated["status"]}


class RecapBody(BaseModel):
    docId: str


@app.post("/api/cases/{cid}/packets/{i}/recap")
async def post_recap(cid: str, i: int, body: RecapBody):
    """AI recap of one content-bearing doc. Sends ONLY that doc's typed content
    region to GreenNode (see recap.content_region_for); caches the result in the
    manifest so repeat views are instant. 503 when GreenNode isn't wired — the
    offline export uses the canned recap instead."""
    case = store.get(cid)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    path = os.path.join(store.case_dir(cid), "packets", str(i), "manifest.json")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="manifest not found")
    with open(path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    cached = (manifest.get("recaps") or {}).get(body.docId)
    if cached:
        return cached

    region = recap.content_region_for(manifest, body.docId)
    if region is None:
        raise HTTPException(status_code=404, detail="no typed content region for this doc")

    try:
        out = greennode.summarize(region)  # ONLY the typed content region is sent
    except greennode.NotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    result = {"bullets": out.get("bullets", []),
              "nhanDinh": out.get("nhanDinh", ""),
              "disclaimer": recap.DISCLAIMER}
    manifest.setdefault("recaps", {})[body.docId] = result
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return result


def _load_manifests(cid: str, packets: list[dict]) -> dict:
    out = {}
    for p in packets:
        path = os.path.join(store.case_dir(cid), "packets", str(p["index"]), "manifest.json")
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                out[p["index"]] = json.load(f)
    return out


@app.post("/api/cases/{cid}/report")
async def post_report(cid: str):
    case = store.get(cid)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    manifests = _load_manifests(cid, case["packets"])
    now = datetime.now(timezone.utc).isoformat()
    report = build_report(case, manifests, generated_at=now)
    case_dir = store.case_dir(cid)
    with open(os.path.join(case_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write(report["markdown"])
    with open(os.path.join(case_dir, "report.csv"), "w", encoding="utf-8") as f:
        f.write(report["csv"])
    return report


@app.get("/api/cases/{cid}/report.md")
async def get_report_md(cid: str):
    path = os.path.join(store.case_dir(cid), "report.md")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="report not generated")
    return FileResponse(path, media_type="text/markdown", filename="bao-cao.md")


@app.get("/api/cases/{cid}/report.csv")
async def get_report_csv(cid: str):
    path = os.path.join(store.case_dir(cid), "report.csv")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="report not generated")
    return FileResponse(path, media_type="text/csv", filename="bao-cao.csv")


@app.delete("/api/cases/{cid}")
async def delete_case(cid: str):
    store.delete(cid)
    return {"ok": True}


@app.get("/api/cases/{cid}/packets/{i}/manifest.json")
async def get_manifest(cid: str, i: int):
    case = store.get(cid)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    path = os.path.join(store.case_dir(cid), "packets", str(i), "manifest.json")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="manifest not found")
    with open(path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    if not manifest.get("checks"):
        # Pre-v2 manifest (OCR'd before the coded checklist existed) --
        # build it on the fly from this manifest's own fields/docs + the
        # packet's match meta rather than serving (and having the reviewer
        # render) an empty checklist. Not persisted back to disk: cheap
        # + pure, so recomputing per GET is simpler than a migration.
        packet = next((p for p in case["packets"] if p["index"] == i), {})
        manifest["checks"] = checklist.build_checklist(
            manifest.get("fields", []),
            {"matchedBy": packet.get("matchedBy", "no-roster"),
             "ocrIdentity": packet.get("ocrIdentity") or {"cccd": "", "name": ""},
             "rosterIdentity": packet.get("rosterIdentity")},
            manifest.get("docs", []),
        )
    base = f"/api/cases/{cid}/packets/{i}"
    return JSONResponse(rewrite_manifest_urls(manifest, base))


@app.get("/api/cases/{cid}/packets/{i}/page/{name}")
async def get_page(cid: str, i: int, name: str):
    if not _PAGE_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="invalid page name")
    case = store.get(cid)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    path = os.path.join(store.case_dir(cid), "packets", str(i), name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="page not found")
    return FileResponse(path)
