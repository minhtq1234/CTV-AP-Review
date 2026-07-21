"""Split a scanned multi-CTV PDF into per-collaborator packets and report the cuts.

Boundaries are the recurring contract-cover pages, discovered from the file
(no hardcoded page numbers, threshold, or reference layout). Pure logic here is
unit-tested; the I/O layer below is verified by running on a real PDF.
"""
from __future__ import annotations

import argparse
import base64
import html as _html
import os
import re
import sys
from dataclasses import dataclass, field

import fitz          # PyMuPDF
import numpy as np
import openpyxl
from PIL import Image


def derive_threshold(scores: list[float]) -> float:
    """Threshold = midpoint of the largest gap between consecutive sorted scores.

    Cover pages cluster high, everything else low; the biggest gap separates them.
    """
    s = sorted(scores)
    if len(s) < 2:
        return s[0] if s else 0.0
    best_gap, best_i = -1.0, 0
    for i in range(len(s) - 1):
        gap = s[i + 1] - s[i]
        if gap > best_gap:
            best_gap, best_i = gap, i
    return (s[best_i] + s[best_i + 1]) / 2


def covers_from_scores(scores: list[float], threshold: float) -> list[int]:
    """Page indices whose score exceeds the threshold (the recurring covers)."""
    return [i for i, sc in enumerate(scores) if sc > threshold]


def packets_from_covers(cover_pages: list[int], total_pages: int) -> list[tuple[int, int]]:
    """Inclusive (start, end) page range per packet.

    Preamble (pages before the first cover) is dropped. Each packet runs from its
    cover to the page before the next cover; the last runs to the final page.
    """
    if not cover_pages:
        return []
    cov = sorted(cover_pages)
    bounds = []
    for k, start in enumerate(cov):
        end = cov[k + 1] - 1 if k + 1 < len(cov) else total_pages - 1
        bounds.append((start, end))
    return bounds


@dataclass
class Packet:
    index: int              # 0-based packet number
    start: int              # 0-based first page (the cover)
    end: int                # 0-based last page, inclusive
    cover_score: float
    name: str | None = None
    flags: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)  # coarse type per page

    @property
    def n_pages(self) -> int:
        return self.end - self.start + 1

    @property
    def confidence(self) -> str:
        return "amber" if self.flags else "green"


def reconcile(
    bounds: list[tuple[int, int]],
    page_scores: list[float],
    roster_names: list[str] | None,
    threshold: float,
    len_range: tuple[int, int] = (5, 12),
    near_margin: float = 0.05,
) -> list[Packet]:
    """Build Packets, align to the roster by order, attach confidence flags."""
    packets: list[Packet] = []
    for i, (start, end) in enumerate(bounds):
        p = Packet(index=i, start=start, end=end, cover_score=page_scores[start])
        if roster_names is not None:
            # Only a roster-relative fact: an excess packet beyond the roster's
            # length. With no roster at all, there's nothing to mismatch against,
            # so no packet should be penalized for an absent name.
            if i < len(roster_names):
                p.name = roster_names[i]
            else:
                p.flags.append("no-roster-match")
        if not (len_range[0] <= p.n_pages <= len_range[1]):
            p.flags.append("length-out-of-range")
        if p.cover_score - threshold < near_margin:
            p.flags.append("near-threshold")
        packets.append(p)
    # Count mismatch is a whole-batch fact, not a per-packet defect — it belongs
    # in the report banner (build_report_html), not stamped on every card.
    return packets


def implausible_structure(n_covers: int, total_pages: int, roster_n: int | None) -> bool:
    """True if the detected covers don't look like a real repeating-packet
    structure — e.g. the wrong document type, or the recurring-cover
    heuristic simply failed to find anything sensible.

    A handful of stray false positives is expected and handled elsewhere
    (prune_excess_covers); this is a coarse sanity guard for gross failure.
    With a roster, more than double the expected count is implausible.
    Without one, fall back to a page-count ratio.
    """
    if roster_n is not None:
        return n_covers > 2 * roster_n
    return n_covers > total_pages / 4


def prune_excess_covers(
    cover_pages: list[int],
    page_scores: list[float],
    roster_n: int | None,
    min_len: int = 5,
) -> tuple[list[int], list[int]]:
    """Drop the weakest excess covers (mid-packet false positives) until the
    count matches the roster.

    A cover is only a pruning candidate if its gap to the *previous* cover is
    below `min_len` pages — too close together to be a real packet boundary
    (e.g. a "BIÊN BẢN NGHIỆM THU" cover that visually mimics the real contract
    cover a few pages into the same packet). Among candidates, the weakest is
    dropped first, one at a time, until the count reaches roster_n:

      1. smallest gap-to-previous wins (most obviously "too close");
      2. tie-break: whichever removal better restores the document's normal
         cadence — i.e. the merged gap it produces (previous-surviving-cover
         to next-surviving-cover) lands closest to the median of the already
         "normal" (>= min_len) gaps. Two candidates can tie on gap alone (a
         false-positive cover sandwiched between two real ones creates two
         equally-short gaps either side of it); this resolves that
         ambiguity from the document's own spacing, not a coin flip;
      3. final tie-break: lowest cover_score (least convincing as a cover).

    If no candidate remains but the count is still too high, stop — a
    legitimately short packet is never force-pruned; it is left for
    reconcile()'s length-out-of-range flag.

    Returns (kept_covers, merged_cover_pages): the surviving cover pages, and
    the ones dropped (their pages merge into the previous packet).
    """
    cov = sorted(cover_pages)
    if roster_n is None:
        return cov, []
    merged: list[int] = []
    while len(cov) > roster_n:
        gaps = [cov[i] - cov[i - 1] for i in range(1, len(cov))]
        candidate_idx = [i for i in range(1, len(cov)) if gaps[i - 1] < min_len]
        if not candidate_idx:
            break
        normal_gaps = [g for g in gaps if g >= min_len]
        typical = _median(normal_gaps) if normal_gaps else min_len

        def _rank(i: int) -> tuple[int, float, float]:
            gap = cov[i] - cov[i - 1]
            if i + 1 < len(cov):
                merged_gap = cov[i + 1] - cov[i - 1]
            else:
                merged_gap = gap  # no next cover to validate the merge against
            return (gap, abs(merged_gap - typical), page_scores[cov[i]])

        candidate_idx.sort(key=_rank)
        drop_i = candidate_idx[0]
        merged.append(cov.pop(drop_i))
    return cov, sorted(merged)


def _median(values: list[float]) -> float:
    s = sorted(values)
    mid = len(s) // 2
    if len(s) % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2


def extract_roster_names(
    rows: list[list],
    keywords: tuple[str, ...] = ("họ và tên", "họ tên", "tên", "name"),
) -> list[str]:
    """Find the name column by header keyword; return non-empty names below it.

    Skips any title/blank rows above the table. Stops collecting at the first
    fully blank row after data has begun.
    """
    header_row = name_col = None
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            if cell and any(k in str(cell).strip().casefold() for k in keywords):
                header_row, name_col = r, c
                break
        if header_row is not None:
            break
    if header_row is None:
        return []
    names: list[str] = []
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
            names.append(str(val).strip())
    return names


def coarse_label(aspect: float, ink: float, is_cover: bool) -> str:
    """Best-effort page type from cheap visual features.

    `aspect` is width/height (so a landscape/rotated page is > 1); `ink` is the
    fraction of dark pixels over the *whole page*. Order matters: cover first,
    then rotated, then dense-text vs sparse-form.

    The ink threshold is calibrated to real low-DPI scans, not a naive guess:
    at dpi=40 a full scanned page's dark-pixel fraction lands nowhere near the
    10%+ one might assume for "dense text" — on a real 262-page CTV submission
    it ranged ~0.00001-0.0051 (median ~0.0014). 0.002 sits above the median,
    separating denser contract/biên-bản body text from sparser forms, tables,
    signature pages, and photocopied ID cards.
    """
    if is_cover:
        return "Hợp đồng (bìa)"
    if aspect > 1.15:
        return "Phụ lục (xoay)"
    if ink >= 0.002:
        return "Văn bản"
    return "Biểu mẫu"


def build_report_html(
    packets: list[Packet],
    roster_n: int | None,
    thumbs: dict[int, str],
    title: str,
    warning: str | None = None,
) -> str:
    """Self-contained HTML: summary banner + one card per packet."""
    amber = sum(1 for p in packets if p.confidence == "amber")
    merged = sum(1 for p in packets if "auto-merged" in p.flags)
    roster_txt = "—" if roster_n is None else str(roster_n)
    if roster_n is None:
        aligned = "(không có bảng kê để đối chiếu)"
    elif roster_n == len(packets):
        aligned = "✓ khớp"
    else:
        aligned = "⚠ lệch số lượng"
    merged_txt = (
        f" · {merged} ranh giới gộp tự động — cần xác nhận" if merged else ""
    )
    warn_txt = f" · ⚠ {_html.escape(warning)}" if warning else ""
    banner = (
        f'<div class="banner"><b>{_html.escape(title)}</b>'
        f'<span>{len(packets)} / {roster_txt} gói (tìm thấy / bảng kê) · {aligned}'
        f' · {amber} ranh giới cần xem lại{merged_txt}{warn_txt}</span></div>'
    )
    cards = []
    for p in packets:
        rng = f"p{p.start + 1}–{p.end + 1}"
        name = _html.escape(p.name) if p.name else "<i>chưa khớp tên</i>"
        thumb = thumbs.get(p.start) or thumbs.get(p.index) or ""
        img = f'<img src="{thumb}" alt="">' if thumb else '<div class="noimg">—</div>'
        chips = "".join(f'<span class="chip">{_html.escape(l)}</span>' for l in p.labels)
        flags = "".join(f'<span class="flag">{_html.escape(f)}</span>' for f in p.flags)
        cards.append(
            f'<div class="card {p.confidence}">{img}'
            f'<div class="meta"><div class="nm">{name}</div>'
            f'<div class="rng">{rng} · {p.n_pages} trang · score {p.cover_score:.2f}</div>'
            f'<div class="chips">{chips}</div><div class="flags">{flags}</div>'
            f'</div></div>'
        )
    style = (
        "body{font:14px system-ui;margin:24px;color:#1a1a1a}"
        ".banner{padding:12px 16px;background:#f4f6f8;border-radius:8px;margin-bottom:16px}"
        ".banner span{margin-left:12px;color:#555}"
        ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px}"
        ".card{border:1px solid #e2e2e2;border-radius:8px;overflow:hidden;background:#fff}"
        ".card.green{border-left:4px solid #2e7d32}.card.amber{border-left:4px solid #e0a300}"
        ".card img{width:100%;height:150px;object-fit:cover;object-position:top;background:#fafafa}"
        ".noimg{height:150px;display:flex;align-items:center;justify-content:center;color:#bbb}"
        ".meta{padding:10px}.nm{font-weight:600}.rng{color:#666;font-size:12px;margin:4px 0}"
        ".chip{display:inline-block;font-size:11px;background:#eef;border-radius:10px;padding:1px 7px;margin:2px 2px 0 0}"
        ".flag{display:inline-block;font-size:11px;background:#fdeaea;color:#a11;border-radius:10px;padding:1px 7px;margin:4px 2px 0 0}"
    )
    return (
        f"<!doctype html><html lang='vi'><head><meta charset='utf-8'>"
        f"<title>{_html.escape(title)}</title><style>{style}</style></head><body>"
        f"{banner}<div class='grid'>{''.join(cards)}</div></body></html>"
    )


_PATH_ILLEGAL_CHARS = re.compile(r'[/\\:*?"<>|]')
_WHITESPACE_RUN = re.compile(r"\s+")


def packet_filename(
    index: int,
    name: str | None,
    start: int,
    end: int,
    auto_merged: bool,
) -> str:
    """Build a filesystem-safe filename for one packet's exported PDF.

    `index` is 0-based; the file uses a 1-based, zero-padded 2-digit order
    (01, 02, ...). Pages in the name are 1-based inclusive (start+1..end+1),
    matching the HTML report's `p{a}-{b}` ranges.

    `name` is slugified: surrounding whitespace stripped, internal whitespace
    runs collapsed to a single '-', and path-illegal characters
    (/ \\ : * ? " < > |) removed outright. Vietnamese diacritics are kept —
    macOS handles UTF-8 filenames fine. A missing/empty name becomes
    CHUA-KHOP-TEN. An auto-merged boundary gets a _can-xac-nhan suffix before
    .pdf, so it's visibly flagged for review from the filename alone.
    """
    order = f"{index + 1:02d}"
    if name is None or not name.strip():
        slug = "CHUA-KHOP-TEN"
    else:
        slug = name.strip()
        slug = _WHITESPACE_RUN.sub("-", slug)
        slug = _PATH_ILLEGAL_CHARS.sub("", slug)
    rng = f"p{start + 1}-{end + 1}"
    suffix = "_can-xac-nhan" if auto_merged else ""
    return f"{order}_{slug}_{rng}{suffix}.pdf"


def load_page_bands(
    pdf_path: str,
    dpi: int = 40,
    band_frac: float = 0.28,
    band_size: tuple[int, int] = (160, 64),
) -> tuple[list[np.ndarray], list[float], list[float], int]:
    """Render each page grayscale at low DPI; return the resized top band, the
    page aspect (width/height), and ink density (fraction of dark pixels) per page.
    """
    doc = fitz.open(pdf_path)
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    bands, aspects, inks = [], [], []
    bw, bh = band_size
    for page in doc:
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
        img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
        aspects.append(pix.width / pix.height if pix.height else 1.0)
        arr = np.asarray(img)
        inks.append(float((arr < 128).mean()))
        top = img.crop((0, 0, img.width, max(1, int(img.height * band_frac))))
        top = top.resize((bw, bh))
        bands.append(np.asarray(top, dtype=np.float32))
    n = doc.page_count
    doc.close()
    return bands, aspects, inks, n


def _unit(band: np.ndarray) -> np.ndarray:
    v = band.ravel().astype(np.float32)
    v = v - v.mean()
    norm = np.linalg.norm(v)
    return v / norm if norm else v


def seed_scores(bands: list[np.ndarray]) -> tuple[list[float], int]:
    """NumPy normalized cross-correlation between all top-bands.

    Seed = the most-recurrent band (highest summed similarity to its nearest
    neighbours) — i.e. the cover, which repeats once per packet. Returns each
    page's similarity to the seed, and the seed index.
    """
    if not bands:
        return [], -1
    M = np.stack([_unit(b) for b in bands])   # (n, d), zero-mean unit rows
    sim = M @ M.T                              # (n, n) NCC in [-1, 1]
    # Recurrence (for seed selection) must ignore self-match, or every page
    # would look maximally "recurrent" with itself. Mask a *copy* for that —
    # the returned per-page scores must keep the true self-similarity (~1.0)
    # so the seed's own entry correctly reads as a cover, not as a forced
    # -1.0 outlier that would blow up derive_threshold's gap search.
    masked = sim.copy()
    np.fill_diagonal(masked, -1.0)
    k = max(3, len(bands) // 20)
    recurrence = np.sort(masked, axis=1)[:, -k:].sum(axis=1)
    seed = int(np.argmax(recurrence))
    return sim[seed].tolist(), seed


def render_thumb_datauri(pdf_path: str, page_index: int, width: int = 220) -> str:
    """Render one page to a small PNG data: URI (for the report)."""
    doc = fitz.open(pdf_path)
    page = doc[page_index]
    zoom = width / page.rect.width
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    png = pix.tobytes("png")
    doc.close()
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def _roster_rows(xlsx_path: str) -> list[list]:
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb.active
    return [list(row) for row in ws.iter_rows(values_only=True)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Detect per-CTV packets in a scanned PDF.")
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--roster", help="path to the roster .xlsx (optional)")
    ap.add_argument("--out", required=True, help="output HTML report path")
    ap.add_argument("--dpi", type=int, default=40)
    args = ap.parse_args(argv)

    bands, aspects, inks, n = load_page_bands(args.pdf, dpi=args.dpi)
    scores, seed = seed_scores(bands)
    threshold = derive_threshold(scores)
    cover_pages = covers_from_scores(scores, threshold)

    roster_names = None
    if args.roster:
        roster_names = extract_roster_names(_roster_rows(args.roster))
    roster_n = len(roster_names) if roster_names is not None else None

    warning = None
    if implausible_structure(len(cover_pages), n, roster_n):
        warning = (
            "Không phát hiện cấu trúc hồ sơ lặp lại — "
            "có thể không phải tập hồ sơ đồng dạng"
        )

    kept_covers, merged_covers = prune_excess_covers(cover_pages, scores, roster_n)
    bounds = packets_from_covers(kept_covers, n)

    packets = reconcile(bounds, scores, roster_names, threshold)
    for merged_page in merged_covers:
        for p in packets:
            if p.start <= merged_page <= p.end:
                if "auto-merged" not in p.flags:
                    p.flags.append("auto-merged")
                break

    cover_set = set(kept_covers)
    for p in packets:
        p.labels = [
            coarse_label(aspects[pg], inks[pg], is_cover=(pg in cover_set))
            for pg in range(p.start, p.end + 1)
        ]

    thumbs = {p.start: render_thumb_datauri(args.pdf, p.start) for p in packets}
    html = build_report_html(
        packets, roster_n=roster_n,
        thumbs=thumbs, title="Tách hồ sơ CTV — báo cáo ranh giới",
        warning=warning,
    )
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"pages={n} seed_page={seed + 1} threshold={threshold:.3f} "
          f"covers={len(kept_covers)} roster={roster_n if roster_n is not None else '—'}")
    if merged_covers:
        print(f"auto-merged {len(merged_covers)} cover(s) at page(s) "
              f"{[c + 1 for c in merged_covers]} (raw covers detected: {len(cover_pages)})")
    if warning:
        print(f"WARNING: {warning}")
    print(f"report -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
