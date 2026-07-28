"""Orchestrate split (splitter/detect_packets) + per-packet OCR/extract
(server/ocr_extract) into one `run_pipeline(pdf_path, roster_path, job_dir,
progress_cb)` call, with progress reported through stages the frontend can
show live ("splitting" -> "ocr n/N").

No unit test here (by design — this wires together already-tested modules
around real PDF/OCR I/O); verified by running the real file end-to-end
(see docs/superpowers/plans/2026-07-13-stage-b-backend.md, Task B4). The
`app.py` tests instead monkeypatch this module's `run_pipeline` entirely.
"""
from __future__ import annotations

import json
import os
import re
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPLITTER_DIR = os.path.join(_REPO_ROOT, "splitter")
if _SPLITTER_DIR not in sys.path:
    sys.path.insert(0, _SPLITTER_DIR)

import checklist  # noqa: E402
from cccd_ingest import ingest_cccd_workbook  # noqa: E402
import detect_packets as dp  # noqa: E402
import ocr_extract as oc  # noqa: E402
from roster_workbook import load_roster_rows  # noqa: E402

# ---------------------------------------------------------------------------
# Roster -> field mapping
# ---------------------------------------------------------------------------

# Vietnamese column header (casefold+stripped) -> the roster_row/product key
# it feeds. The real roster (BẢNG KÊ THANH TOÁN CTV) has its header row
# preceded by decorative rows (title, "Sản phẩm:", "Mã Plan:") and followed
# by one merged sub-header row (Gross/Bản cam kết/Thuế PIT/Thực Nhận under
# "Chi Phí (+ PIT)") before the real data starts.
_ROSTER_HEADER_MAP = {
    "họ và tên": "name",
    "số cccd": "cccd",
    "mst": "mst",
    "ngày tháng năm sinh": "ngaysinh",
    "số tk": "tk",
    "phí dịch vụ": "phi",
    "note": "note",
}


def _find_roster_header(rows: list[list]) -> tuple[int, dict[str, int]] | None:
    """Locate the header row + a {field: column_index} map.

    A row only counts as the header once it has both a name and a cccd
    column, so the decorative title/"Sản phẩm:"/"Mã Plan:" rows above it
    (which could otherwise stray-match a lone keyword) are skipped.
    """
    for r, row in enumerate(rows):
        cols: dict[str, int] = {}
        for c, cell in enumerate(row):
            if not cell:
                continue
            field = _ROSTER_HEADER_MAP.get(str(cell).strip().casefold())
            if field:
                cols[field] = c
        if "name" in cols and "cccd" in cols:
            return r, cols
    return None


def _roster_data_rows(rows: list[list], header_row: int, name_col: int) -> list[list]:
    """Data rows after the header, in order.

    Mirrors `detect_packets.extract_roster_names`'s blank-row handling
    exactly (a row with *no* value in the name column doesn't count as data
    -- this is what skips the merged sub-header row below the header --
    while a fully blank row stops collection once data has started), so a
    packet's roster row lines up with `reconcile`'s by-order name matching.
    """
    data: list[list] = []
    started = False
    for row in rows[header_row + 1:]:
        blank = all(cell is None or str(cell).strip() == "" for cell in row)
        if blank:
            if started:
                break
            continue
        started = True
        val = row[name_col] if name_col < len(row) else None
        if val and str(val).strip():
            data.append(row)
    return data


def _product_from_note(note: str) -> str:
    """Product name is the text before " - " in the Note column
    (e.g. "Danh Tướng 3Q - 381" -> "Danh Tướng 3Q"); no/blank Note -> "".
    """
    text = (note or "").strip()
    if not text:
        return ""
    return text.split(" - ", 1)[0].strip()


def all_roster_rows(rows: list[list]) -> list[dict[str, str]]:
    """Every roster data row (in file order) as a `roster_row` dict
    (`ocr_extract.extract_fields`'s expected shape: name/cccd/mst/ngaysinh/
    tk/phi, plus `product` parsed from its Note column). `[]` if there's no
    header.

    Replaces the old by-position `roster_row_for(rows, packet_index)`: a
    packet is no longer assumed to align with the i-th roster row (see
    `match_roster`) — instead every row is indexed once, up front, by CCCD
    and by name.
    """
    header = _find_roster_header(rows)
    if header is None:
        return []
    header_row, cols = header
    data_rows = _roster_data_rows(rows, header_row, cols["name"])

    def cell(row: list, field: str) -> str:
        idx = cols.get(field)
        if idx is None or idx >= len(row):
            return ""
        val = row[idx]
        return "" if val is None else str(val).strip()

    out = []
    for row in data_rows:
        out.append({
            "name": cell(row, "name"),
            "cccd": cell(row, "cccd"),
            "mst": cell(row, "mst"),
            "ngaysinh": cell(row, "ngaysinh"),
            "tk": cell(row, "tk"),
            "phi": cell(row, "phi"),
            "product": _product_from_note(cell(row, "note")),
        })
    return out


def digits(s: str | None) -> str:
    """Strip everything but digits (spaces, dashes, dots) for CCCD matching."""
    return re.sub(r"\D", "", s or "")


def build_roster_index(rows: list[list]) -> tuple[dict[str, dict], dict[str, dict]]:
    """Build `{digits(cccd): row}` and `{norm(name): row}` indexes once from
    the roster, for `match_roster` to look packets up in (by identity,
    instead of by position)."""
    by_cccd: dict[str, dict] = {}
    by_name: dict[str, dict] = {}
    for row in all_roster_rows(rows):
        c = digits(row["cccd"])
        if c and c not in by_cccd:
            by_cccd[c] = row
        n = oc.norm(row["name"]) if row["name"] else ""
        if n and n not in by_name:
            by_name[n] = row
    return by_cccd, by_name


def match_roster(
    cccd: str, name: str, by_cccd: dict[str, dict], by_name: dict[str, dict],
) -> tuple[dict | None, str]:
    """Align a packet to its roster row by identity (#002 fix).

    1. exact CCCD match (reliable, unique per person) -> (row, "cccd")
    2. else name match (fallback -- needed so a roster row with a
       deliberately-typo'd CCCD still aligns by name, and then correctly
       shows the CCCD field as a mismatch rather than failing to match at
       all) -> (row, "name")
    3. else -> (None, "unmatched")
    """
    key = digits(cccd)
    if key and key in by_cccd:
        return by_cccd[key], "cccd"
    nkey = oc.norm(name) if name else ""
    if nkey and nkey in by_name:
        return by_name[nkey], "name"
    return None, "unmatched"


_ROSTER_KEY_BY_FIELD = {spec["key"]: spec["roster_key"] for spec in oc.FIELD_SPECS}


def fill_expected(fields: list[dict], row: dict[str, str] | None) -> list[dict]:
    """Fill each field's `expected` from the matched roster `row` (or leave
    it empty if `row` is None, i.e. the packet didn't match anyone)."""
    row = row or {}
    filled = []
    for f in fields:
        g = dict(f)
        g["expected"] = row.get(_ROSTER_KEY_BY_FIELD.get(f["key"], ""), "")
        filled.append(g)
    return filled


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    pdf_path: str,
    roster_path: str | None,
    job_dir: str,
    progress_cb,
    cccd_xlsx_path: str | None = None,
) -> dict:
    """Split `pdf_path` into packets, OCR/extract each into a manifest under
    `job_dir/packets/{i}/`, reporting progress via `progress_cb(stage, done,
    total, detail)`. A supplied `cccd_xlsx_path` is ingested after all packet
    manifests have been created. Returns `{"summary": {...}, "packets": [...],
    "cccdWorkbook": ...}`.
    """
    progress_cb("splitting", 0, 0, "")

    bands, aspects, inks, n = dp.load_page_bands(pdf_path)
    scores, seed = dp.seed_scores(bands)
    threshold = dp.derive_threshold(scores)
    cover_pages = dp.covers_from_scores(scores, threshold)

    roster_rows_raw = None
    roster_rows: list[dict[str, str]] = []
    roster_names = None
    by_cccd: dict[str, dict] = {}
    by_name: dict[str, dict] = {}
    if roster_path:
        roster_rows_raw = load_roster_rows(roster_path)
        roster_rows = all_roster_rows(roster_rows_raw)
        roster_names = dp.extract_roster_names(roster_rows_raw)
        by_cccd, by_name = build_roster_index(roster_rows_raw)
    roster_n = len(roster_names) if roster_names is not None else None

    kept_covers, merged_covers = dp.prune_excess_covers(cover_pages, scores, roster_n)
    bounds = dp.packets_from_covers(kept_covers, n)
    packets = dp.reconcile(bounds, scores, roster_names, threshold)

    for merged_page in merged_covers:
        for p in packets:
            if p.start <= merged_page <= p.end:
                if "auto-merged" not in p.flags:
                    p.flags.append("auto-merged")
                break

    cover_set = set(kept_covers)
    for p in packets:
        p.labels = [
            dp.coarse_label(aspects[pg], inks[pg], is_cover=(pg in cover_set))
            for pg in range(p.start, p.end + 1)
        ]

    progress_cb("ocr", 0, len(packets), "")
    packets_out = []
    matched = 0
    for p in packets:
        out_dir = os.path.join(job_dir, "packets", str(p.index))
        result = oc.ocr_packet(pdf_path, p.start, p.end, out_dir)
        identity = result["identity"]

        # Align by OCR'd identity (CCCD, name fallback), not by packet
        # position (#002) -- a single swap or boundary shift in the PDF vs.
        # roster order used to mispair a packet and cascade to the rest.
        if roster_rows_raw is not None:
            row, how = match_roster(identity["cccd"], identity["name"], by_cccd, by_name)
        else:
            row, how = None, "no-roster"

        if row is not None:
            matched += 1
            p.name = row["name"]
            product = row["product"]
        else:
            p.name = identity["name"] or None
            product = ""
            if roster_rows_raw is not None and "roster-unmatched" not in p.flags:
                p.flags.append("roster-unmatched")

        fields = fill_expected(result["folder"]["fields"], row)
        folder_id = oc._slug(p.name or f"packet-{p.index}")
        manifest = oc.build_manifest(folder_id, p.name or "", product, result["folder"]["docs"], fields)
        manifest["checks"] = checklist.build_checklist(
            fields,
            {"matchedBy": how,
             "ocrIdentity": {"cccd": identity.get("cccd", ""), "name": identity.get("name", "")},
             "rosterIdentity": ({"cccd": row.get("cccd", ""), "name": row.get("name", "")} if row is not None else None)},
            result["folder"]["docs"],
        )
        with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        progress_cb("ocr", p.index + 1, len(packets), p.name or "")

        packets_out.append({
            "index": p.index,
            "name": p.name,
            "pages": [p.start, p.end],
            "n_pages": p.n_pages,
            "confidence": p.confidence,
            "flags": p.flags,
            "labels": p.labels,
            "matchedBy": how,
            "ocrIdentity": {"cccd": identity.get("cccd", ""), "name": identity.get("name", "")},
            "rosterIdentity": (
                {"cccd": row.get("cccd", ""), "name": row.get("name", "")}
                if row is not None else None
            ),
        })

    summary = {
        "found": len(packets),
        "roster_n": roster_n,
        "matched": matched,
        "auto_merged": len(merged_covers),
    }
    cccd_workbook = None
    if cccd_xlsx_path is not None:
        progress_cb("cccd", 0, 0, "")
        packet_manifest_paths = {
            packet["index"]: os.path.join(
                job_dir, "packets", str(packet["index"]), "manifest.json",
            )
            for packet in packets_out
        }
        ingest_result = ingest_cccd_workbook(
            cccd_xlsx_path,
            roster_rows,
            packets_out,
            job_dir,
            packet_manifest_paths,
            os.path.join(job_dir, "cccd-assets"),
            progress_cb,
        )
        packets_out = ingest_result["packets"]
        cccd_workbook = ingest_result["cccdWorkbook"]
    return {"summary": summary, "packets": packets_out, "cccdWorkbook": cccd_workbook}
