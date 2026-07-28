"""PII-free browser fixture for the CCCD upload thin slice."""
from __future__ import annotations

import json
import os
import time


ROOT = os.environ["CTV_CCCD_SMOKE_ROOT"]
SMOKE_CCCD_DELAY_SECONDS = 3.2

from PIL import Image

import app as appmod
import checklist
from cases import CaseStore


appmod.store = CaseStore(ROOT)


def _page(path: str, color: str) -> dict:
    Image.new("RGB", (1000, 630), color).save(path, format="PNG")
    return {"src": path, "width": 1000, "height": 630}


def _fake_pipeline(
    pdf_path,
    roster_path,
    job_dir,
    progress_cb,
    cccd_xlsx_path=None,
):
    packet_dir = os.path.join(job_dir, "packets", "0")
    os.makedirs(packet_dir, exist_ok=True)
    progress_cb("splitting", 1, 1, "")
    progress_cb("ocr", 1, 1, "")

    front_id = "cccd-excel-card-drawing-0001-drawing-0002-front"
    back_id = "cccd-excel-card-drawing-0001-drawing-0002-back"
    contract_path = os.path.join(packet_dir, "synthetic-contract.png")
    front_path = os.path.join(packet_dir, "synthetic-cccd-front.png")
    back_path = os.path.join(packet_dir, "synthetic-cccd-back.png")
    docs = [
        {
            "id": "contract",
            "kind": "contract",
            "label": "Hợp đồng dịch vụ",
            "pages": [_page(contract_path, "white")],
        },
        {
            "id": front_id,
            "kind": "id_front",
            "label": "CCCD (Excel) · Mặt trước",
            "pages": [_page(front_path, "lightblue")],
        },
        {
            "id": back_id,
            "kind": "id_back",
            "label": "CCCD (Excel) · Mặt sau",
            "pages": [_page(back_path, "lightgray")],
        },
    ]
    fields = [{
        "key": "cccd",
        "label": "Số CCCD",
        "group": "Danh tính",
        "check": "compare",
        "kind": "text",
        "expected": "000000000001",
        "sources": [{
            "docId": front_id,
            "page": 0,
            "value": "000000000001",
            "bbox": {"x": 160, "y": 260, "width": 360, "height": 70},
            "confidence": .95,
        }],
    }]
    packet = {
        "index": 0,
        "name": "Synthetic Reviewer",
        "pages": [0, 0],
        "n_pages": 1,
        "confidence": "green",
        "flags": [],
        "labels": [],
        "matchedBy": "cccd",
        "ocrIdentity": {"cccd": "000000000001", "name": "Synthetic Reviewer"},
        "rosterIdentity": {"cccd": "000000000001", "name": "Synthetic Reviewer"},
    }
    manifest = {
        "id": "synthetic-reviewer",
        "name": "Synthetic Reviewer",
        "product": "",
        "heading": "Hồ sơ CTV",
        "status": "pending",
        "exempt": False,
        "docs": docs,
        "fields": fields,
        "checks": checklist.build_checklist(fields, packet, docs),
    }
    with open(
        os.path.join(packet_dir, "manifest.json"),
        "w",
        encoding="utf-8",
    ) as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)

    if cccd_xlsx_path:
        progress_cb("cccd", 1, 1, "")
        time.sleep(SMOKE_CCCD_DELAY_SECONDS)
        workbook = {
            "status": "ready",
            "summary": {"candidates": 1, "attached": 1, "unresolved": 0},
            "mappings": [{"candidateId": "synthetic-candidate"}],
        }
    else:
        workbook = None
    return {
        "summary": {
            "found": 1,
            "roster_n": 1,
            "matched": 1,
            "auto_merged": 0,
        },
        "packets": [packet],
        "cccdWorkbook": workbook,
    }


appmod.run_pipeline = _fake_pipeline
app = appmod.app
