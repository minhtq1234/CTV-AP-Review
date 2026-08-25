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
from copy import deepcopy
from datetime import datetime, timezone

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
import fitz
from pydantic import BaseModel, Field, field_validator, model_validator
from starlette.concurrency import run_in_threadpool
from typing import Literal
import threading

from boundary_assessment import assess_case_boundaries, assess_packet_boundary
from boundary_proposal import build_boundary_proposal, validate_revision_starts
from cases import CaseStore, compact_cccd_summary, progress_of
from cccd_workbook import MAX_WORKBOOK_BYTES as MAX_CCCD_WORKBOOK_BYTES
from pipeline import run_pipeline  # noqa: F401 - referenced as `run_pipeline` at call
                                    # time below so tests can monkeypatch this name.
from report import build_report
from roster_workbook import preflight_roster_workbook

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


def _boundary_correction_enabled(value: str | None) -> bool:
    return value == "1"


BOUNDARY_CORRECTION_ENABLED = _boundary_correction_enabled(
    os.environ.get("CTV_BOUNDARY_CORRECTION_ENABLED")
)

# Live progress while a case is `processing` (not persisted — it's transient
# and only meaningful for the in-flight run); keyed by case id.
_progress: dict[str, dict] = {}

_PAGE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+\.(?:png|jpe?g)$")


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


def _packet_manifest(cid: str, index: int) -> dict | None:
    path = os.path.join(
        store.case_dir(cid), "packets", str(index), "manifest.json",
    )
    try:
        with open(path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        return manifest if isinstance(manifest, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def _packet_for_response(
    cid: str,
    packet: dict,
    case_summary: dict | None = None,
    boundary_resolution: dict | None = None,
) -> dict:
    manifest = _packet_manifest(cid, packet["index"])
    fields = manifest.get("fields") if isinstance(manifest, dict) else None
    docs = manifest.get("docs") if isinstance(manifest, dict) else None
    tax_commitment_detected = isinstance(docs, list) and any(
        isinstance(doc, dict) and doc.get("kind") == "commitment"
        for doc in docs
    )
    return {
        **packet,
        "reviewFieldCount": len(fields) if isinstance(fields, list) else 0,
        "taxCommitmentDetected": tax_commitment_detected,
        "boundaryAssessment": assess_packet_boundary(
            packet,
            manifest,
            case_summary,
            boundary_resolution,
        ),
    }


def _upload_size(upload: UploadFile) -> int:
    upload.file.seek(0, os.SEEK_END)
    size = upload.file.tell()
    upload.file.seek(0)
    return size


def _is_valid_roster(upload: UploadFile) -> bool:
    if not (upload.filename or "").casefold().endswith(".xlsx"):
        return False
    try:
        upload.file.seek(0)
        preflight_roster_workbook(upload.file)
        return True
    except Exception:
        return False
    finally:
        upload.file.seek(0)


async def _validate_uploads(
    roster: UploadFile | None,
    cccd: UploadFile | None,
) -> None:
    if cccd is not None and roster is None:
        raise HTTPException(
            status_code=422,
            detail={"code": "cccd-requires-roster"},
        )
    if roster is not None and not await run_in_threadpool(
        _is_valid_roster,
        roster,
    ):
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid-roster-workbook"},
        )
    if cccd is None:
        return
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


def _run_case(
    cid: str,
    pdf_path: str,
    roster_path: str | None,
    cccd_path: str | None = None,
    confirmed_starts: tuple[int, ...] | None = None,
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
            confirmed_starts=confirmed_starts,
        )
        case = store.get(cid)
        revision_number = case.get("revisionNumber", 0) if case else 0
        packets = []
        for packet in result.get("packets", []):
            stamped = {**packet, "packetRevision": revision_number}
            packets.append(stamped)
            manifest_path = os.path.join(
                case_dir, "packets", str(stamped["index"]), "manifest.json",
            )
            if os.path.isfile(manifest_path):
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                if not isinstance(manifest, dict):
                    raise ValueError("boundary-manifest-invalid")
                manifest["packetRevision"] = revision_number
                with open(manifest_path, "w", encoding="utf-8") as f:
                    json.dump(manifest, f, ensure_ascii=False, indent=2)
        store.set_result(
            cid,
            summary=result.get("summary"),
            packets=packets,
            cccd_workbook=result.get("cccdWorkbook"),
        )
    except Exception as e:  # noqa: BLE001 - surfaced to the caller via case["error"]
        failed_case = store.get(cid)
        error = (
            "boundary-revision-processing-failed"
            if failed_case and failed_case.get("revisionNumber", 0) > 0
            else str(e)
        )
        store.set_error(cid, error)
    finally:
        _progress.pop(cid, None)


@app.post("/api/cases")
async def post_case(
    pdf: UploadFile = File(...),
    roster: UploadFile | None = File(None),
    cccd: UploadFile | None = File(None),
):
    await _validate_uploads(roster, cccd)
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

    t = threading.Thread(
        target=_run_case,
        args=(cid, pdf_path, roster_path, cccd_path),
        daemon=True,
    )
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
    out["cccdSummary"] = compact_cccd_summary(
        case.get("cccdWorkbook"),
    )
    manifests = _load_manifests(cid, case["packets"])
    boundary_status = assess_case_boundaries(case, manifests)
    out["packets"] = [
        _packet_for_response(
            cid,
            packet,
            case.get("summary"),
            case.get("boundaryResolution"),
        )
        for packet in case["packets"]
    ]
    out["boundaryStatus"] = boundary_status
    out["publicationBlocked"] = boundary_status["status"] == "review"
    out["progress"] = progress_of(case["packets"])
    if case["status"] == "processing" and cid in _progress:
        out["liveProgress"] = _progress[cid]
    return out


PacketRejectionReason = Literal[
    "missing_documents",
    "wrong_template",
    "missing_signature",
]


class PacketRejectionBody(BaseModel):
    reasons: list[PacketRejectionReason] = Field(min_length=1)
    note: str = ""

    @field_validator("reasons")
    @classmethod
    def reasons_must_be_unique(cls, reasons):
        if len(reasons) != len(set(reasons)):
            raise ValueError("rejection reasons must be unique")
        return reasons


class ReviewBody(BaseModel):
    done: bool = False
    fields: dict = Field(default_factory=dict)
    rejection: PacketRejectionBody | None = None


class BoundaryResolutionBody(BaseModel):
    action: Literal["keep-current", "create-revision"]
    starts: list[int] | None = None

    @field_validator("starts", mode="before")
    @classmethod
    def starts_are_plain_integers(cls, starts):
        if starts is not None and (
            not isinstance(starts, list)
            or any(type(page) is not int for page in starts)
        ):
            raise ValueError("boundary-starts-invalid")
        return starts

    @model_validator(mode="after")
    def starts_match_action(self):
        if self.action == "create-revision" and self.starts is None:
            raise ValueError("boundary-starts-required")
        if self.action == "keep-current" and self.starts is not None:
            raise ValueError("boundary-starts-not-allowed")
        return self


@app.put("/api/cases/{cid}/packets/{i}/review")
async def put_review(cid: str, i: int, body: ReviewBody):
    updated = store.set_review(cid, i, body.model_dump())
    if updated is None:
        raise HTTPException(status_code=404, detail="case or packet not found")
    packet = next((p for p in updated["packets"] if p["index"] == i), None)
    return {"packet": _packet_for_response(
                cid,
                packet,
                updated.get("summary"),
                updated.get("boundaryResolution"),
            ),
            "progress": progress_of(updated["packets"]),
            "status": updated["status"]}


def _load_manifests(cid: str, packets: list[dict]) -> dict:
    out = {}
    for p in packets:
        manifest = _packet_manifest(cid, p["index"])
        if manifest is not None:
            out[p["index"]] = manifest
    return out


def _source_pdf_page_count(cid: str) -> int:
    path = os.path.join(store.case_dir(cid), "input.pdf")
    try:
        with fitz.open(path) as document:
            return document.page_count
    except Exception as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "boundary-source-pdf-invalid"},
        ) from exc


def _proposal_for_case(case: dict) -> dict:
    proposal = build_boundary_proposal(
        case,
        _load_manifests(case["id"], case.get("packets") or []),
        _source_pdf_page_count(case["id"]),
    )
    resolution = case.get("boundaryResolution") or {}
    if resolution.get("action") == "keep-current":
        proposal["status"] = "accepted_current"
    elif resolution.get("action") == "create-revision":
        proposal["status"] = "superseded"
    proposal["correctionEnabled"] = BOUNDARY_CORRECTION_ENABLED
    return proposal


def _copy_revision_inputs(
    source_dir: str,
    revision_dir: str,
) -> tuple[str, str | None, str | None]:
    copied: list[str | None] = []
    for name in ("input.pdf", "roster.xlsx", "cccd.xlsx"):
        source = os.path.join(source_dir, name)
        if os.path.isfile(source):
            target = os.path.join(revision_dir, name)
            shutil.copy2(source, target)
            copied.append(target)
        else:
            copied.append(None)
    if copied[0] is None:
        raise ValueError("boundary-source-pdf-missing")
    return copied[0], copied[1], copied[2]


@app.get("/api/cases/{cid}/boundary-proposal")
async def get_boundary_proposal(cid: str):
    case = store.get(cid)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    return _proposal_for_case(case)


@app.post("/api/cases/{cid}/boundary-proposal/resolve")
async def resolve_boundary_proposal(cid: str, body: BoundaryResolutionBody):
    if not BOUNDARY_CORRECTION_ENABLED:
        raise HTTPException(
            status_code=409,
            detail={"code": "boundary-correction-disabled"},
        )
    case = store.get(cid)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")

    existing_resolution = case.get("boundaryResolution") or {}
    confirmed_starts = None
    if body.action == "create-revision":
        packet_starts = [
            packet.get("pages", [None])[0]
            for packet in case.get("packets") or []
            if packet.get("pages")
        ]
        first_packet_start = min(
            (page for page in packet_starts if type(page) is int),
            default=None,
        )
        if first_packet_start is None:
            raise HTTPException(
                status_code=422,
                detail={"code": "boundary-source-packets-invalid"},
            )
        try:
            confirmed_starts = validate_revision_starts(
                body.starts,
                _source_pdf_page_count(cid),
                first_packet_start,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": str(exc)},
            ) from exc

    if existing_resolution:
        if existing_resolution.get("action") != body.action:
            raise HTTPException(
                status_code=409,
                detail={"code": "boundary-resolution-conflict"},
            )
        if body.action == "keep-current":
            return {
                "caseId": cid,
                "sourceCaseId": cid,
                "status": "accepted_current",
            }
        existing_revision_id = existing_resolution.get("revisionCaseId")
        if (
            tuple(existing_resolution.get("starts") or ()) != confirmed_starts
            or not isinstance(existing_revision_id, str)
        ):
            raise HTTPException(
                status_code=409,
                detail={"code": "boundary-resolution-conflict"},
            )
        return {
            "caseId": existing_revision_id,
            "sourceCaseId": cid,
            "status": "processing",
        }

    now = datetime.now(timezone.utc).isoformat()
    proposal = _proposal_for_case(case)
    reasons = assess_case_boundaries(
        case,
        _load_manifests(cid, case.get("packets") or []),
    )["reasons"]
    if body.action == "keep-current":
        store.set_boundary_resolution(cid, {
            "action": "keep-current",
            "starts": [candidate["page"] for candidate in proposal["candidateStarts"]],
            "reasons": reasons,
            "resolvedAt": now,
        })
        return {
            "caseId": cid,
            "sourceCaseId": cid,
            "status": "accepted_current",
        }

    try:
        revision_id = store.create_revision(cid, now)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="case not found") from exc
    try:
        pdf_path, roster_path, cccd_path = _copy_revision_inputs(
            store.case_dir(cid),
            store.case_dir(revision_id),
        )
    except Exception as exc:
        store.set_error(revision_id, "boundary-revision-copy-failed")
        raise HTTPException(
            status_code=500,
            detail={"code": "boundary-revision-copy-failed"},
        ) from exc

    store.set_boundary_resolution(cid, {
        "action": "create-revision",
        "starts": list(confirmed_starts),
        "reasons": reasons,
        "revisionCaseId": revision_id,
        "resolvedAt": now,
    })
    threading.Thread(
        target=_run_case,
        args=(revision_id, pdf_path, roster_path, cccd_path, confirmed_starts),
        daemon=True,
    ).start()
    return {
        "caseId": revision_id,
        "sourceCaseId": cid,
        "status": "processing",
    }


@app.post("/api/cases/{cid}/report")
async def post_report(cid: str):
    case = store.get(cid)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    manifests = _load_manifests(cid, case["packets"])
    now = datetime.now(timezone.utc).isoformat()
    report = build_report(
        case,
        manifests,
        generated_at=now,
        boundary_status=assess_case_boundaries(case, manifests),
    )
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
