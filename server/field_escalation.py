"""Decide which pages are worth a second, more expensive read.

Local Tesseract already reads most fields: measured 235/246 (96%) on the July
batch and 149/192 (78%) on February. Sending every page to a network reader to
win the remainder would be poor value and would put far more packet data on the
wire than necessary, so IDP is an ESCALATION -- called only where the local read
is unusable.

Two things make the targeting precise:

  * `locate_field` returns a located-but-unread hit rather than nothing when it
    finds a label whose value it cannot read, so a weak field still carries the
    `docId`/`page`/`bbox` of the slot the value sits in. Measured over both
    batches, 192 of 192 value checks had a bbox even when only 17 had a value --
    position is known essentially always. So escalation re-reads exactly the
    pages a weak field points at, not the whole packet.

  * A read below `LOW_CONF` is treated as unusable, not merely uncertain.

    BUT THE CONVERSE IS FALSE, and an earlier version of this comment claimed
    it. Confidence does NOT mean correct. Hand-checked against the scans on the
    July batch: 8 of the 14 disagreements are at or above 0.7, and packet 34
    read the same digits on the same page two ways -- CCCD `001100000151` at
    0.93 and 0.90 (wrong) while MST read `001100000101` at 0.86 (right).
    Packet 39 read a date correctly at 0.06.

    So this threshold is a floor on what is CLEARLY unusable, not a boundary
    between good and bad reads. Escalation deliberately does not see a
    confidently-wrong read; catching those needs a different signal (a
    digit-level disagreement against an otherwise-consistent roster value is a
    better one) and is not solved here.

Pure: no IO, no network, no OCR. `ocr_packet` owns the actual re-read.

Identifiers in this file -- CCCDs, tax codes, bank accounts and person
names, in fixtures and in the comments recording what was measured -- are
synthetic stand-ins. The observations are real; the values are not, because
this branch is published to a public remote. Substituted stand-ins preserve
the shape the observation depended on: digit count, a one-digit misread, an
accent-only difference, a truncation.
"""

from __future__ import annotations

from dataclasses import dataclass

from compare_values import LOW_CONF


@dataclass(frozen=True)
class FieldVerdict:
    """How usable a field's best local read is."""

    key: str
    value: str
    confidence: float | None
    #: why this field is weak, or "" when it is fine
    reason: str

    @property
    def weak(self) -> bool:
        return bool(self.reason)


def best_read(field: dict) -> tuple[str, float | None]:
    """The field's most confident non-empty read, as `(value, confidence)`.

    `("", None)` when nothing was read. Confidence decides rather than source
    order: a field can be read on several documents and the pipeline should
    escalate on the strength of the best evidence it actually has.
    """
    readable = [
        s for s in (field.get("sources") or [])
        if str(s.get("value") or "").strip()
    ]
    if not readable:
        return "", None
    best = max(readable, key=lambda s: s.get("confidence") or 0.0)
    return str(best.get("value") or "").strip(), best.get("confidence")


def judge(field: dict, low_conf: float = LOW_CONF) -> FieldVerdict:
    """Classify one field's best local read."""
    value, confidence = best_read(field)
    key = str(field.get("key") or "")
    if not value:
        return FieldVerdict(key, "", confidence, "unread")
    if confidence is not None and confidence < low_conf:
        return FieldVerdict(key, value, confidence, "low-confidence")
    return FieldVerdict(key, value, confidence, "")


def weak_fields(fields: list[dict], low_conf: float = LOW_CONF) -> list[FieldVerdict]:
    """Every field whose best local read is unusable, in `fields` order."""
    verdicts = [judge(f, low_conf) for f in fields]
    return [v for v in verdicts if v.weak]


def pages_to_reread(
    fields: list[dict],
    low_conf: float = LOW_CONF,
) -> set[tuple[str, int]]:
    """`(docId, page)` pairs the weak fields point at -- the pages worth a
    second read, and nothing else.

    A field with no located source at all contributes no page: there is nowhere
    to aim a re-read, so escalating it would be a blind scan of the packet.
    """
    weak = {v.key for v in weak_fields(fields, low_conf)}
    targets: set[tuple[str, int]] = set()
    for f in fields:
        if str(f.get("key") or "") not in weak:
            continue
        for s in f.get("sources") or []:
            doc_id = str(s.get("docId") or "")
            if not doc_id:
                continue
            targets.add((doc_id, int(s.get("page", 0) or 0)))
    return targets


@dataclass(frozen=True)
class Escalation:
    """What a second read should cover, and why."""

    weak: tuple[FieldVerdict, ...]
    pages: tuple[tuple[str, int], ...]

    @property
    def worth_calling(self) -> bool:
        return bool(self.pages)

    def note(self) -> str:
        """One line for a log, so an operator can see what the calls bought."""
        if not self.weak:
            return "every field read locally; no second read needed"
        why = ", ".join(f"{v.key} ({v.reason})" for v in self.weak)
        if not self.pages:
            return f"weak but unlocated, nothing to re-read: {why}"
        return f"{len(self.pages)} page(s) to re-read for: {why}"


def plan(fields: list[dict], low_conf: float = LOW_CONF) -> Escalation:
    """The whole decision in one call, for `ocr_packet` to act on."""
    weak = tuple(weak_fields(fields, low_conf))
    pages = tuple(sorted(pages_to_reread(fields, low_conf)))
    return Escalation(weak=weak, pages=pages)


def merge_sources(
    local: list[dict],
    escalated: list[dict],
    pages: set[tuple[str, int]] | tuple[tuple[str, int], ...],
) -> list[dict]:
    """Fields with the re-read pages' sources taken from `escalated`, the rest
    from `local`.

    Replacement per page, NOT a union. A union would keep a local garbage read
    alongside a good escalated one for the same page, and two readable copies
    that disagree is exactly the "mis-split packet" signal
    `evaluate._compare_reads` treats as worst-wins -- so unioning would convert
    a field the escalation just fixed into a false mismatch. The page was
    escalated precisely because its local read was unusable, so for that page
    the better reader's answer stands alone.

    Pages that were not escalated are untouched, so a field read confidently on
    another document keeps that read.
    """
    targets = set(pages)
    by_key = {str(f.get("key") or ""): f for f in escalated}
    merged = []
    for f in local:
        key = str(f.get("key") or "")
        kept = [
            s for s in (f.get("sources") or [])
            if (str(s.get("docId") or ""), int(s.get("page", 0) or 0)) not in targets
        ]
        fresh = [
            s for s in ((by_key.get(key) or {}).get("sources") or [])
            if (str(s.get("docId") or ""), int(s.get("page", 0) or 0)) in targets
        ]
        out = dict(f)
        out["sources"] = kept + fresh
        merged.append(out)
    return merged
