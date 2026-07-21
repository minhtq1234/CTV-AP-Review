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

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPLITTER_DIR = os.path.join(_REPO_ROOT, "splitter")
if _SPLITTER_DIR not in sys.path:
    sys.path.insert(0, _SPLITTER_DIR)

import detect_packets as dp  # noqa: E402
import ocr_extract as oc  # noqa: E402

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


def roster_row_for(rows: list[list], packet_index: int) -> tuple[dict[str, str], str]:
    """Map the `packet_index`-th roster data row (0-based) to a `roster_row`
    dict (`ocr_extract.extract_fields`'s expected shape: name/cccd/mst/
    ngaysinh/tk/phi) plus the product parsed from its Note column.

    Packets align to roster rows strictly by order — packet i -> the i-th
    data row — the same convention `detect_packets.reconcile` uses to name
    packets. Returns `({}, "")` if there's no header, or no such row (an
    excess packet beyond the roster's length).
    """
    header = _find_roster_header(rows)
    if header is None:
        return {}, ""
    header_row, cols = header
    data_rows = _roster_data_rows(rows, header_row, cols["name"])
    if packet_index >= len(data_rows):
        return {}, ""
    row = data_rows[packet_index]

    def cell(field: str) -> str:
        idx = cols.get(field)
        if idx is None or idx >= len(row):
            return ""
        val = row[idx]
        return "" if val is None else str(val).strip()

    roster_row = {
        "name": cell("name"),
        "cccd": cell("cccd"),
        "mst": cell("mst"),
        "ngaysinh": cell("ngaysinh"),
        "tk": cell("tk"),
        "phi": cell("phi"),
    }
    return roster_row, _product_from_note(cell("note"))


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_pipeline(pdf_path: str, roster_path: str | None, job_dir: str, progress_cb) -> dict:
    """Split `pdf_path` into packets, OCR/extract each into a manifest under
    `job_dir/packets/{i}/`, reporting progress via `progress_cb(stage, done,
    total, detail)`. Returns `{"summary": {...}, "packets": [...]}`.
    """
    progress_cb("splitting", 0, 0, "")

    bands, aspects, inks, n = dp.load_page_bands(pdf_path)
    scores, seed = dp.seed_scores(bands)
    threshold = dp.derive_threshold(scores)
    cover_pages = dp.covers_from_scores(scores, threshold)

    roster_rows_raw = None
    roster_names = None
    if roster_path:
        roster_rows_raw = dp._roster_rows(roster_path)
        roster_names = dp.extract_roster_names(roster_rows_raw)
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
        if roster_rows_raw is not None:
            roster_row, product = roster_row_for(roster_rows_raw, p.index)
        else:
            roster_row, product = {}, ""
        if p.name:
            matched += 1
        name = p.name or ""

        out_dir = os.path.join(job_dir, "packets", str(p.index))
        oc.ocr_packet(pdf_path, p.start, p.end, roster_row, out_dir, name=name, product=product)
        progress_cb("ocr", p.index + 1, len(packets), name)

        packets_out.append({
            "index": p.index,
            "name": p.name,
            "pages": [p.start, p.end],
            "n_pages": p.n_pages,
            "confidence": p.confidence,
            "flags": p.flags,
            "labels": p.labels,
        })

    summary = {
        "found": len(packets),
        "roster_n": roster_n,
        "matched": matched,
        "auto_merged": len(merged_covers),
    }
    return {"summary": summary, "packets": packets_out}
