"""Pure builder: per-packet OCR fields + match key + segmented docs -> the coded,
two-tier review checklist (CheckItem dicts). No IO/OCR here; unit tested. The
pipeline calls this and writes the result into each packet's manifest under `checks`."""
from __future__ import annotations
import re, unicodedata

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    return "".join(ch for ch in s if not unicodedata.combining(ch)).casefold().strip()

def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")

def _autostatus(reference: str, source: dict | None) -> str:
    val = (source or {}).get("value", "")
    if not source or not val:
        return "review"
    if _digits(reference) and _digits(val):
        return "match" if _digits(reference) == _digits(val) else "mismatch"
    return "match" if _norm(reference) == _norm(val) else "mismatch"

def _doc_by_kind(docs: list[dict], kind: str) -> str | None:
    for d in docs:
        if d.get("kind") == kind:
            return d["id"]
    return None

_VALUE = [
    ("B1", "Họ tên khớp bảng kê", "contract", "name"),
    ("A1", "Số CCCD khớp giữa chứng từ", "contract", "cccd"),
    ("A2", "Mã số thuế khớp bảng kê", "contract", "mst"),
    ("B2", "Phí dịch vụ khớp bảng kê", "contract", "phi"),
    ("BANK", "Số tài khoản khớp bảng kê", "contract", "tk"),
    ("INFO", "Ngày sinh khớp hồ sơ", "contract", "ngaysinh"),
]
_CONFIRM_GATES = [
    ("D3", "Cam kết TNCN đúng mẫu năm hiện hành", "commitment"),
    ("B3", "Hợp đồng đủ chữ ký & con dấu", "contract"),
    ("C2", "BBNT đủ chữ ký, con dấu & giáp lai", "bbnt"),
]
_CONFIRM_DETAIL = [
    ("C1", "Nội dung & thời gian khớp BBNT", "bbnt"),
    ("D1", "Thông tin & MST khớp cam kết", "commitment"),
]

def build_checklist(fields: list[dict], match: dict, docs: list[dict]) -> list[dict]:
    by_key = {f["key"]: f for f in fields}
    contract = _doc_by_kind(docs, "contract") or (docs[0]["id"] if docs else None)
    checks: list[dict] = []

    checks.append({"code": "G-DOC", "label": "Đủ chứng từ bắt buộc", "tier": "gate",
                   "kind": "confirm", "evidenceDocId": None,
                   "reference": None, "source": None, "autostatus": None})
    matched_by = match.get("matchedBy", "no-roster")
    checks.append({"code": "G-ID", "label": "Đúng người — CCCD & tên khớp", "tier": "gate",
                   "kind": "identity", "evidenceDocId": contract,
                   "reference": (match.get("rosterIdentity") or {}).get("cccd", ""),
                   "source": ({"docId": contract, "page": 0,
                               "value": (match.get("ocrIdentity") or {}).get("cccd", ""),
                               "bbox": None, "confidence": 1.0} if contract else None),
                   "autostatus": "match" if matched_by == "cccd" else "review"})
    for code, label, kind_doc in _CONFIRM_GATES:
        checks.append({"code": code, "label": label, "tier": "gate", "kind": "confirm",
                       "evidenceDocId": _doc_by_kind(docs, kind_doc),
                       "reference": None, "source": None, "autostatus": None})

    for code, label, kind_doc, fkey in _VALUE:
        f = by_key.get(fkey)
        if not f:
            continue
        src = (f.get("sources") or [None])[0]
        checks.append({"code": code, "label": label, "tier": "detail", "kind": "value",
                       "evidenceDocId": (src or {}).get("docId") or _doc_by_kind(docs, kind_doc),
                       "reference": f.get("expected", ""), "source": src,
                       "autostatus": _autostatus(f.get("expected", ""), src)})
    for code, label, kind_doc in _CONFIRM_DETAIL:
        checks.append({"code": code, "label": label, "tier": "detail", "kind": "confirm",
                       "evidenceDocId": _doc_by_kind(docs, kind_doc),
                       "reference": None, "source": None, "autostatus": None})
    return checks
