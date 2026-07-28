"""Pure builder: per-packet OCR fields + match key + segmented docs -> the coded,
two-tier review checklist (CheckItem dicts). No IO/OCR here; unit tested. The
pipeline calls this and writes the result into each packet's manifest under `checks`."""
from __future__ import annotations
import re, unicodedata

_DIACRITIC_SPECIAL = {"đ": "d", "Đ": "D"}

def _norm(s: str) -> str:
    s = "".join(_DIACRITIC_SPECIAL.get(ch, ch) for ch in (s or ""))
    s = unicodedata.normalize("NFD", s)
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

def _doc_obj_by_kind(docs: list[dict], kind: str) -> dict | None:
    for d in docs:
        if d.get("kind") == kind:
            return d
    return None

_D3_REFERENCE_ASSET = "/reference/mau-08-ck-tncn-2026.svg"   # blank current-year Mẫu 08/CK-TNCN (PII-free)

def _bbnt_for_c2(docs: list[dict]) -> dict | None:
    """C2 focuses the thanh-lý BBNT when a packet has both (nghiệm thu + thanh
    lý); else the only/first BBNT. Distinguished by label (the type enum shares
    'bbnt' for both)."""
    bbnts = [d for d in docs if d.get("kind") == "bbnt"]
    if not bbnts:
        return None
    for d in bbnts:
        if "thanh ly" in _norm(d.get("label", "")):
            return d
    return bbnts[0]

_VALUE = [
    ("B1", "Họ tên khớp bảng kê", "contract", "hoten"),
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
    for code, label, kind_doc in _CONFIRM_GATES:
        if code == "C2":
            doc = _bbnt_for_c2(docs)
        elif kind_doc == "contract":
            doc = _doc_obj_by_kind(docs, "contract") or (docs[0] if docs else None)
        else:
            doc = _doc_obj_by_kind(docs, kind_doc)
        if doc is None:
            continue   # #5: routed doc absent -> no dead row
        check = {"code": code, "label": label, "tier": "gate", "kind": "confirm",
                 "evidenceDocId": doc["id"],
                 "reference": None, "source": None, "autostatus": None}
        if code == "D3":
            check["referenceAsset"] = _D3_REFERENCE_ASSET
        checks.append(check)

    for code, label, kind_doc, fkey in _VALUE:
        f = by_key.get(fkey)
        if not f:
            continue
        sources = f.get("sources") or []
        routed = contract if kind_doc == "contract" else _doc_by_kind(docs, kind_doc)
        mapped_cccd = (
            next(
                (
                    source
                    for source in sources
                    if (source or {}).get("docId", "").startswith("cccd-excel-")
                ),
                None,
            )
            if code == "A1"
            else None
        )
        src = mapped_cccd or next(
            (source for source in sources if source and source.get("docId") == routed),
            None,
        ) or (sources[0] if sources else None)
        autostatus = (
            "review"
            if code == "A1" and mapped_cccd is not None
            else _autostatus(f.get("expected", ""), src)
        )
        checks.append({"code": code, "label": label, "tier": "detail", "kind": "value",
                       "evidenceDocId": (src or {}).get("docId") or routed,
                       "reference": f.get("expected", ""), "source": src,
                       "autostatus": autostatus})
    for code, label, kind_doc in _CONFIRM_DETAIL:
        doc_id = _doc_by_kind(docs, kind_doc)
        if code == "C1":
            # Content lives in the Phụ lục (typed SOW/KPI/Actual) when present;
            # fall back to the BBNT body otherwise. One check either way (no split).
            doc_id = _doc_by_kind(docs, "appendix") or doc_id
        if doc_id is None:
            continue   # #5: document-routed check with no evidence doc -> no dead row
        checks.append({"code": code, "label": label, "tier": "detail", "kind": "confirm",
                       "evidenceDocId": doc_id,
                       "reference": None, "source": None, "autostatus": None})
    return checks
