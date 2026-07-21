"""FastAPI backend: accepts an uploaded scanned PDF (+ optional roster), runs
split -> OCR/extract on a background thread with progress, and serves the
per-packet CtvFolder manifests + rendered page PNGs the frontend consumes.

Binds 127.0.0.1 only (run via `uvicorn app:app --host 127.0.0.1`); job data
lives under a per-job `tempfile.mkdtemp()` directory — never inside the repo,
never committed. See server/README.md for the full PII note.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from copy import deepcopy

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from jobs import JobStore, start_job
from pipeline import run_pipeline  # noqa: F401 - referenced as `run_pipeline` at call
                                    # time below so tests can monkeypatch this name.

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

store = JobStore()

_PAGE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+\.png$")


def rewrite_manifest_urls(manifest: dict, base: str) -> dict:
    """Point every page's `src` at `{base}/page/{basename}`.

    `ocr_extract.render_pages` writes `src` as an absolute on-disk path (fine
    for the offline/no-server use case); the server instead exposes pages
    under the job/packet-scoped page endpoint, keyed by basename only.
    """
    out = deepcopy(manifest)
    for doc in out.get("docs", []):
        for page in doc.get("pages", []):
            page["src"] = f"{base}/page/{os.path.basename(page['src'])}"
    return out


@app.post("/api/jobs")
async def post_job(pdf: UploadFile = File(...), roster: UploadFile | None = File(None)):
    job_dir = tempfile.mkdtemp(prefix="ap-review-job-")
    pdf_path = os.path.join(job_dir, "input.pdf")
    with open(pdf_path, "wb") as f:
        shutil.copyfileobj(pdf.file, f)

    roster_path = None
    if roster is not None:
        roster_path = os.path.join(job_dir, "roster.xlsx")
        with open(roster_path, "wb") as f:
            shutil.copyfileobj(roster.file, f)

    jid = store.create(job_dir)
    start_job(store, jid, pdf_path, roster_path, run=run_pipeline)
    return {"job_id": jid}


@app.get("/api/jobs/{jid}")
async def get_job(jid: str):
    job = store.get(jid)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return {
        "id": job["id"],
        "status": job["status"],
        "progress": job["progress"],
        "result": job["result"],
        "error": job["error"],
    }


@app.get("/api/jobs/{jid}/packets/{i}/manifest.json")
async def get_manifest(jid: str, i: int):
    job = store.get(jid)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    path = os.path.join(job["dir"], "packets", str(i), "manifest.json")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="manifest not found")
    with open(path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    base = f"/api/jobs/{jid}/packets/{i}"
    return JSONResponse(rewrite_manifest_urls(manifest, base))


@app.get("/api/jobs/{jid}/packets/{i}/page/{name}")
async def get_page(jid: str, i: int, name: str):
    if not _PAGE_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="invalid page name")
    job = store.get(jid)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    path = os.path.join(job["dir"], "packets", str(i), name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="page not found")
    return FileResponse(path)
