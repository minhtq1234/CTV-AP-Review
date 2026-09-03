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

import detect_packets as dp  # noqa: E402
import ocr_extract as oc  # noqa: E402
from cccd_ingest import ingest_cccd_workbook  # noqa: E402
from purchase_listing import read_total  # noqa: E402
from roster_workbook import load_roster_rows  # noqa: E402

# ---------------------------------------------------------------------------
# Roster -> field mapping
# ---------------------------------------------------------------------------

# Vietnamese column header (casefold+stripped) -> the roster_row/product key
# it feeds. The real roster (BẢNG KÊ THANH TOÁN CTV) has its header row
# preceded by decorative rows (title, "Sản phẩm:", "Mã Plan:") and followed
# by one merged sub-header row (Gross/Bản cam kết/Thuế PIT/Thực Nhận under
# "Chi Phí (+ PIT)") before the real data starts.
#: This module's field names, in terms of `roster_checks._HEADER_PATTERNS`
#: keys. There used to be a second, exact-string header table here; it wanted
#: "số cccd" and so read nothing at all from the combined template, whose column
#: is headed "CCCD/ PP" -- matching then failed on every packet while the roster
#: count still looked right, because roster_checks parsed the same sheet
#: correctly with regexes. One parser now, not two.
_FIELD_FROM_ROSTER_KEY = {
    "name": "name",
    "cccd": "cccd",
    "mst": "mst",
    "dob": "ngaysinh",
    "account": "tk",
    "note": "note",
}
#: `phi` is whichever pay column the template carries: the older sheet heads it
#: "Phí dịch vụ", the combined one "Gross". First present wins.
_PHI_KEYS = ("fee", "gross")


def _find_roster_header(rows: list[list]) -> tuple[int, dict[str, int]] | None:
    """Locate the header row + a {field: column_index} map.

    A row only counts as the header once it has both a name and a cccd
    column, so the decorative title/"Sản phẩm:"/"Mã Plan:" rows above it
    (which could otherwise stray-match a lone keyword) are skipped.
    """
    import re

    import roster_checks

    # Row-by-row, first row carrying both name and cccd wins -- as before. Only
    # the label matching changed: `roster_checks._HEADER_PATTERNS` are accent-
    # folded regexes, so "CCCD/ PP", "Số CCCD", "Số tài khoản" and "Số TK" all
    # land. Deliberately NOT `roster_checks.locate_columns`: that one finds the
    # first data row by looking for a numeric STT cell, and the older template
    # has no STT column at all.
    for r, row in enumerate(rows):
        found: dict[str, int] = {}
        for c, cell in enumerate(row):
            folded = roster_checks._fold(cell)
            if not folded:
                continue
            for key, patterns in roster_checks._HEADER_PATTERNS.items():
                if key in found:
                    continue
                if any(re.search(p, folded) for p in patterns):
                    found[key] = c
        cols = {
            field: found[key]
            for key, field in _FIELD_FROM_ROSTER_KEY.items()
            if key in found
        }
        for key in _PHI_KEYS:
            if key in found:
                cols["phi"] = found[key]
                break
        if "name" in cols and "cccd" in cols:
            # Headers can span rows: the combined template puts "Chi Phí (+ PIT)"
            # over "Gross", so the pay column is labelled a row BELOW the one
            # naming the person. Keep reading header rows for anything still
            # missing, stopping at the first row with a value in the name column
            # -- that is data.
            name_col = cols["name"]
            for extra in rows[r + 1:]:
                head = extra[name_col] if name_col < len(extra) else None
                if head and str(head).strip():
                    break
                for c, cell in enumerate(extra):
                    folded = roster_checks._fold(cell)
                    if not folded:
                        continue
                    for key, patterns in roster_checks._HEADER_PATTERNS.items():
                        if key in found:
                            continue
                        if any(re.search(pat, folded) for pat in patterns):
                            found[key] = c
                if "phi" not in cols:
                    for key in _PHI_KEYS:
                        if key in found:
                            cols["phi"] = found[key]
                            break
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


def index_roster_rows(
    parsed: list[dict[str, str]],
) -> tuple[dict[str, dict], dict[str, dict], dict[str, dict]]:
    """Index ALREADY-PARSED roster rows by CCCD, name and MST.

    Split out of `build_roster_index` so a caller holding parsed rows -- the
    CCCD ingest does, and `sheet_identity` needs the same three indexes to
    join a sheet screenshot to its person -- reuses this key logic instead of
    writing a third copy of it. First row wins on a repeated key.
    """
    by_cccd: dict[str, dict] = {}
    by_name: dict[str, dict] = {}
    by_mst: dict[str, dict] = {}
    for row in parsed:
        c = digits(row.get("cccd", ""))
        if c and c not in by_cccd:
            by_cccd[c] = row
        name = row.get("name", "")
        n = oc.norm(name) if name else ""
        if n and n not in by_name:
            by_name[n] = row
        m = digits(row.get("mst", ""))
        if m and m not in by_mst:
            by_mst[m] = row
    return by_cccd, by_name, by_mst


def build_roster_index(
    rows: list[list],
) -> tuple[dict[str, dict], dict[str, dict], dict[str, dict]]:
    """Build `{digits(cccd): row}`, `{norm(name): row}` and `{digits(mst): row}`
    indexes once from the roster, for `match_roster` to look packets up in (by
    identity, instead of by position)."""
    return index_roster_rows(all_roster_rows(rows))


def match_roster(
    cccd: str, name: str, by_cccd: dict[str, dict], by_name: dict[str, dict],
    mst: str = "", by_mst: dict[str, dict] | None = None,
) -> tuple[dict | None, str]:
    """Align a packet to its roster row by identity (#002 fix).

    Strongest key first, because the wrong-person error is the most expensive
    one this tool can make:

    1. exact CCCD match (reliable, unique per person) -> (row, "cccd")
    2. else exact personal MST match -> (row, "mst"). The July packet that
       matched nothing is row 32's: its number is printed on three of its pages
       and read cleanly at 0.95, but under the `mst` key, because the CCCD label
       was split by line grouping while `MSTTNCN` survived. A strong identifier
       already in hand should not go unused.
    3. else name match (fallback -- needed so a roster row with a
       deliberately-typo'd CCCD still aligns by name, and then correctly
       shows the CCCD field as a mismatch rather than failing to match at
       all) -> (row, "name")
    4. else -> (None, "unmatched")
    """
    key = digits(cccd)
    if key and key in by_cccd:
        return by_cccd[key], "cccd"
    mkey = digits(mst)
    if mkey and by_mst and mkey in by_mst:
        return by_mst[mkey], "mst"
    nkey = oc.norm(name) if name else ""
    if nkey and nkey in by_name:
        return by_name[nkey], "name"
    return None, "unmatched"


_ROSTER_KEY_BY_FIELD = {spec["key"]: spec["roster_key"] for spec in oc.FIELD_SPECS}


# Which reader handles CCCD cards. Local Tesseract by default; GreenNode IDP
# when both variables are set. On a real batch the difference is large --
# 26 of 41 people resolved locally versus 40 of 41 via IDP, with no false
# reads either way -- but IDP is a network call, so it stays opt-in.
# The roster carries exactly one row per person -- one payment. So two packets
# resolving to the SAME row is a double-payment risk, and it is not rare: on a
# real July batch, 9 of 41 people had two complete packets each (contract, BBNT,
# tax lookup, sometimes an appendix -- full submissions, not split fragments),
# and 16 of those 18 packets matched by CCCD, so the identity read was right.
#
# Left unflagged, both packets look clean and both can be approved. This is the
# most expensive error the tool can wave through, and it costs nothing to
# detect: it is a pure count over already-matched packets. `cccd_matching` has
# had the equivalent guard (`competing-candidate`) since the card work; the
# packet path never did.
DUPLICATE_IDENTITY_FLAG = "duplicate-roster-identity"


def flag_duplicate_identities(packets_out: list[dict]) -> list[dict]:
    """Flag every packet that shares a roster row with another packet."""
    by_row: dict[str, list[dict]] = {}
    for packet in packets_out:
        roster = packet.get("rosterIdentity") or {}
        key = digits(roster.get("cccd", "")) or oc.norm(roster.get("name", ""))
        if key:
            by_row.setdefault(key, []).append(packet)
    for group in by_row.values():
        if len(group) < 2:
            continue
        for packet in group:
            if DUPLICATE_IDENTITY_FLAG not in packet["flags"]:
                packet["flags"].append(DUPLICATE_IDENTITY_FLAG)
            # which packets it collides with, so the reviewer can compare them
            packet["duplicateOf"] = sorted(
                other["index"] for other in group if other is not packet
            )
    return packets_out


#: The Bảng Kê Thu Mua sits in the batch-level front matter, before the first
#: packet. On the real submissions that is pages 1-11 (July) and 1-7
#: (February); the PUBGm nghiệm thu submission has 32 front pages and no
#: listing at all. This bounds the scan so a pathological front matter cannot
#: stall an ingest -- and when it bites, the result says so rather than
#: reporting "no listing".
MAX_FRONT_MATTER_PAGES = 40


#: DPI and page fraction for the boundary-snapping pass. A document's title is
#: large and at the top, so this reads it reliably at a third of the cost of a
#: full-page 300-dpi read -- measured at 255ms/page against 1.2s, with zero
#: missed or false contract starts over four real packets. The packet pages are
#: OCR'd properly later; this pass only answers "does a document start here".
SNAP_DPI = 150
SNAP_BAND = 0.35


def _start_page_classifier(pdf_path: str, dpi: int = SNAP_DPI,
                           band: float = SNAP_BAND):
    """A cached `page_index -> kind` reader for `snap_covers_to_starts`.

    Reads only the top `band` of each page, so it detects the kinds whose title
    sits at the top -- which is what a *start* page has. It will miss a title
    further down (an appendix or tax-lookup heading), so this is not a general
    page classifier and must not be reused as one.

    A page that cannot be read is simply not a start: an OCR failure must not
    stop an ingest, and leaving the cover where it was is the safe answer.
    """
    cache: dict[int, str | None] = {}

    def classify(page: int) -> str | None:
        if page in cache:
            return cache[page]
        try:
            words, _ = oc.ocr_words(pdf_path, page, ocr_dpi=dpi, band_frac=band)
            found = oc.classify_page(oc._page_text(words))
        except Exception:  # noqa: BLE001 - an unreadable page is not a start
            found = None
        cache[page] = found[0] if found else None
        return cache[page]

    return classify


def read_purchase_total(
    pdf_path: str,
    front_pages: int,
    ocr=None,
    detect_rotation=None,
    progress_cb=None,
) -> dict | None:
    """The total printed on the purchase listing, for criterion #20.

    Scans the `front_pages` pages before the first packet **backwards**: the
    total is the last thing on the listing, so counting down reaches it without
    OCRing the rows above it. Returns None when there is no listing to find,
    and a result with `gross: None` plus a `reason` when a page carries a total
    it could not read -- the two are different findings for the reviewer.
    """
    if front_pages <= 0:
        return None
    ocr = ocr or oc.ocr_words
    detect_rotation = detect_rotation or oc.detect_page_rotation

    capped = min(front_pages, MAX_FRONT_MATTER_PAGES)
    scanned = 0
    for page in range(front_pages - 1, front_pages - capped - 1, -1):
        if progress_cb is not None:
            progress_cb("listing", scanned, capped, f"trang {page + 1}")
        words, _ = ocr(pdf_path, page, rotation=detect_rotation(pdf_path, page))
        scanned += 1
        read = read_total({page: words})
        if read.reason == "not-found":
            continue
        return {
            "gross": read.amount,
            "page": read.page,
            "reason": read.reason,
            "digitsRepaired": read.digits_repaired,
        }
    if capped < front_pages:
        return {"gross": None, "page": None, "reason": "front-matter-too-long",
                "digitsRepaired": False, "pagesScanned": scanned}
    return None


def _page_reader():
    """The document-field escalation reader, or None when IDP is not configured.

    Deliberately the same two variables as `_card_reader` -- enabling IDP is one
    deployment decision, not two -- plus `IDP_DOC_TYPE`, whose correct value for
    a general page read is not yet established (see `idp_words`).
    """
    from idp_words import page_reader_from_env   # lazy: only when enabled

    return page_reader_from_env()


def _card_reader():
    base_url = os.environ.get("GREENNODE_IDP_URL", "").strip()
    api_key = os.environ.get("GREENNODE_API_KEY", "").strip()
    if not base_url or not api_key:
        return None
    from cccd_idp import reader  # imported lazily: only needed when enabled

    return reader(base_url.rstrip("/").removesuffix("/ocr/ingest"), api_key)


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
    total, detail)`. Returns `{"summary": {...}, "packets": [...]}`.
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
        by_cccd, by_name, by_mst = build_roster_index(roster_rows_raw)
    roster_n = len(roster_names) if roster_names is not None else None

    kept_covers, merged_covers = dp.prune_excess_covers(cover_pages, scores, roster_n)

    # The recurring page the bands find is not necessarily a packet's first --
    # on the July submission it was the fourth, so every packet held the tail of
    # the previous CTV's documents. Move each cover back to the page that starts
    # a packet; a cover with no start in its window keeps its place.
    progress_cb("boundaries", 0, len(kept_covers), "")
    classify_start = _start_page_classifier(pdf_path)
    kept_covers, snap_report = dp.snap_covers_to_starts(
        kept_covers, classify_start,
    )
    # A cover can also be missed outright, leaving one packet holding two CTVs'
    # documents. An over-long packet with a document start inside it is that.
    kept_covers, missed_report = dp.insert_missed_starts(
        kept_covers, n, classify_start,
    )
    progress_cb("boundaries", len(kept_covers), len(kept_covers), "")

    bounds = dp.packets_from_covers(kept_covers, n)
    # `near-threshold` is about how strongly the *cover* was detected, and the
    # start page is no longer the cover, so pass the cover's score explicitly.
    # `None` marks a boundary that came from a document title, which has no
    # cover score to judge.
    cover_of = snap_report["cover_of"]
    inserted = set(missed_report["inserted"])
    cover_scores = [
        None if start in inserted else scores[cover_of.get(start, start)]
        for start, _ in bounds
    ]
    packets = dp.reconcile(bounds, scores, roster_names, threshold,
                           cover_scores=cover_scores)

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
    # Which reader re-reads a page the local OCR could not resolve. None unless
    # GreenNode IDP is configured, so the default ingest is local-only and no
    # packet page leaves the workstation. Escalation is per page, not per
    # field: measured over the real batches it covers 14% of July's doc-pages
    # and 28% of February's, so it buys the handwritten and low-confidence tail
    # without putting the other 70-86% on the wire.
    page_reader = _page_reader()
    packets_out = []
    matched = 0
    for p in packets:
        out_dir = os.path.join(job_dir, "packets", str(p.index))
        result = oc.ocr_packet(pdf_path, p.start, p.end, out_dir,
                               page_reader=page_reader)
        identity = result["identity"]

        # Align by OCR'd identity (CCCD, name fallback), not by packet
        # position (#002) -- a single swap or boundary shift in the PDF vs.
        # roster order used to mispair a packet and cascade to the rest.
        if roster_rows_raw is not None:
            row, how = match_roster(
                identity["cccd"], identity["name"], by_cccd, by_name,
                mst=identity.get("mst", ""), by_mst=by_mst,
            )
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

    flag_duplicate_identities(packets_out)

    summary = {
        "found": len(packets),
        "roster_n": roster_n,
        "matched": matched,
        "auto_merged": len(merged_covers),
        "duplicate_identities": sum(
            1 for p in packets_out
            if DUPLICATE_IDENTITY_FLAG in p["flags"]
        ),
        "boundaries_snapped": snap_report["shifted"],
        "boundaries_offset": snap_report["offset"],
        "boundaries_reason": snap_report["reason"],
        "boundaries_inferred": len(snap_report["inferred"]),
        "boundaries_inserted": len(missed_report["inserted"]),
    }
    purchase_total = read_purchase_total(
        pdf_path,
        min((p.start for p in packets), default=0),
        progress_cb=progress_cb,
    )

    cccd_workbook = None
    if cccd_xlsx_path is not None:
        progress_cb("cccd", 0, 0, "")
        manifest_paths = {
            packet["index"]: os.path.join(
                job_dir,
                "packets",
                str(packet["index"]),
                "manifest.json",
            )
            for packet in packets_out
        }
        ingest_result = ingest_cccd_workbook(
            cccd_xlsx_path,
            roster_rows,
            packets_out,
            job_dir,
            manifest_paths,
            os.path.join(job_dir, "cccd-assets"),
            progress_cb,
            analyze=_card_reader(),
        )
        packets_out = ingest_result["packets"]
        cccd_workbook = ingest_result["cccdWorkbook"]
    return {
        "summary": summary,
        "packets": packets_out,
        "cccdWorkbook": cccd_workbook,
        "purchaseTotal": purchase_total,
    }
