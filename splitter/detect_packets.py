"""Split a scanned multi-CTV PDF into per-collaborator packets and report the cuts.

Boundaries are the recurring contract-cover pages, discovered from the file
(no hardcoded page numbers, threshold, or reference layout). Pure logic here is
unit-tested; the I/O layer below is verified by running on a real PDF.
"""
from __future__ import annotations

from dataclasses import dataclass, field


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
        if roster_names is not None and i < len(roster_names):
            p.name = roster_names[i]
        if p.name is None:
            p.flags.append("no-roster-match")
        if not (len_range[0] <= p.n_pages <= len_range[1]):
            p.flags.append("length-out-of-range")
        if p.cover_score - threshold < near_margin:
            p.flags.append("near-threshold")
        packets.append(p)
    if roster_names is not None and len(bounds) != len(roster_names):
        for p in packets:
            p.flags.append("count-mismatch")
    return packets


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
