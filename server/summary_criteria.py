"""The five roster-level criteria — Acc's Tổng hợp tab.

These apply to the whole bảng kê rather than one CTV, which is why the prototype
defers them: "5 tiêu chí ở cấp độ Toàn bảng kê … không thuộc hồ sơ riêng của
từng CTV — sẽ đưa vào Tab Tổng hợp". That tab does not exist in the prototype;
this module is its backend.

Their STTs were unknown to the prototype (its Open Question #2). The other
checklist's `Cấp độ` column resolves them, and they match its .scope-note list
in order: #20 totals, #26 the two bảng kê signatures, #30 duplicate identity
values, #31 duplicate payment, #32 document date sequence. #19 is *not* one of
them — it is "Phí dịch vụ khớp giữa các chứng từ", folded into #14's card.

Three are already implemented elsewhere and are wired up here rather than
rewritten: #20 and #30 by `roster_checks`, #31 by
`pipeline.flag_duplicate_identities`. #26 is a signature check and belongs to a
person. #32 is not built.
"""

from __future__ import annotations

from dataclasses import dataclass

import roster_checks
from criteria import Criterion, Kind, Status

EXCEL = "Bảng kê"
PURCHASE = "Bảng Kê Thu Mua"
CONTRACT = "Hợp đồng"
BBNT = "BBNT"
APPENDIX = "Phụ lục"


def _c(stt, label, docs, kind, how, **params) -> Criterion:
    return Criterion(stt, label, "TH", tuple(docs), how, kind, "card",
                     params or None)


ROSTER_CRITERIA: tuple[Criterion, ...] = (
    _c(20, "Tổng Gross/PIT/Net toàn bảng kê", [EXCEL, PURCHASE], Kind.COMPUTE,
       "Cộng lại toàn bộ các dòng CTV; đối chiếu với dòng tổng trên Excel.",
       formula="column_totals"),
    _c(26, "2 Bảng kê có ký người lập, người phê duyệt và dấu/giáp lai",
       [EXCEL, PURCHASE], Kind.PRESENCE,
       "Kiểm tra có chữ ký người lập, người phê duyệt và dấu/giáp lai công ty "
       "theo mẫu. Không chấp nhận chữ ký/dấu bị mất, mờ hoặc nằm ngoài vùng "
       "scan."),
    _c(30, "Không trùng CCCD/MST/tài khoản", [EXCEL], Kind.COMPARE,
       "Kiểm tra toàn bảng kê: một CCCD không gắn với nhiều tên/MST; một MST "
       "không gắn với nhiều CCCD; một tài khoản không gắn với nhiều CTV, trừ "
       "trường hợp có căn cứ được duyệt."),
    _c(31, "Không trùng thanh toán cùng CTV + số tiền + kỳ thanh toán",
       [EXCEL, CONTRACT, BBNT], Kind.COMPARE,
       "Tìm các dòng có cùng CTV hoặc CCCD/MST, cùng số tiền, nội dung dịch vụ "
       "và kỳ thanh toán trong một bộ hồ sơ. Chỉ cảnh báo trùng, không tự động "
       "xóa dòng."),
    _c(32, "Ngày ký chứng từ hợp lý",
       [CONTRACT, APPENDIX, BBNT, EXCEL], Kind.COMPUTE,
       "Kiểm tra trình tự: Hợp đồng/Phụ lục được ký trước hoặc tại thời điểm "
       "bắt đầu dịch vụ → hoàn thành dịch vụ → ký BBNT → lập bảng kê/đề nghị "
       "thanh toán. Không có ngày tương lai, ngày kết thúc trước ngày bắt đầu "
       "hoặc BBNT ký trước khi hoàn thành.",
       formula="date_sequence"),
)

BY_STT = {c.stt: c for c in ROSTER_CRITERIA}

#: `roster_checks` finds both roster-level and per-CTV problems in one pass over
#: the Excel. Only these codes belong to the Tổng hợp tab; the rest are per-CTV
#: findings that feed the individual matrices' Excel column, and are routed by
#: PER_CTV_CODES below so neither view silently drops a finding.
_SUMMARY_CODES = {
    "duplicate-cccd": 30,
    "duplicate-mst": 30,
    "duplicate-account": 30,
    "no-total-row": 20,
    "total-missing-gross": 20,
    "total-missing-pit": 20,
    "total-missing-net": 20,
    "total-mismatch-gross": 20,
    "total-mismatch-pit": 20,
    "total-mismatch-net": 20,
}

#: Which per-CTV criterion each remaining roster_checks code belongs to. The
#: Excel is one of the documents those criteria compare across, so a problem
#: found here is that criterion's Excel cell.
PER_CTV_CODES = {
    "formula-mismatch": 17,
    "pit-zero-without-basis": 15,
    "amount-missing": 14,
    "cccd-format": 2,
    "dob-format": 3,
    "account-missing": 7,
    "missing-columns": 0,  # structural: no criterion can run
}


@dataclass(frozen=True)
class SummaryCell:
    """One roster-level criterion's result."""

    stt: int
    label: str
    status: Status
    message: str
    #: rows or documents the reviewer should look at, in Acc's own phrasing
    detail: tuple[str, ...] = ()

    @property
    def code(self) -> str:
        return f"{self.stt:02d}"


def _cell(stt, status, message, detail=()) -> SummaryCell:
    return SummaryCell(stt, BY_STT[stt].label, status, message, tuple(detail))


def assess(
    rows: list[tuple],
    packets: list[dict] | None = None,
    purchase_total: dict[str, int] | None = None,
) -> list[SummaryCell]:
    """Evaluate the five roster-level criteria.

    `rows` is the bảng kê sheet. `packets` carries the duplicate-identity flags
    already computed by the pipeline. `purchase_total` optionally supplies the
    totals printed on the Bảng Kê Thu Mua, keyed `gross`/`pit`/`net`.

    On the real July submission no roster carries a total row -- the total is
    printed on page 8 of the Bảng Kê Thu Mua instead (240.305.556 VNĐ, which
    reconciles exactly with the 41 Gross values). So #20 spans two documents,
    and passing `purchase_total` is what lets it resolve rather than sit
    pending.
    """
    report = roster_checks.check(rows)
    by_code = {f.code: f for f in report.findings}
    cells: list[SummaryCell] = []

    # -- #20 totals ---------------------------------------------------------
    cells.append(_total_cell(rows, report, by_code, purchase_total))

    # -- #26 signatures on the two bảng kê: a person decides ----------------
    cells.append(_cell(
        26, Status.REVIEW,
        "Cần người kiểm tra: chữ ký người lập, người phê duyệt và dấu/giáp lai "
        "trên cả hai bảng kê.",
    ))

    # -- #30 nothing shared between CTVs ------------------------------------
    # An unreadable roster must not read as a clean one: with no rows or no
    # identity columns there is nothing to compare, which is not the same as
    # nothing colliding.
    identity = [k for k in ("cccd", "mst", "account") if k in report.columns]
    if not report.people or not identity:
        cells.append(_cell(
            30, Status.PENDING,
            "Không đọc được dòng CTV hoặc cột CCCD/MST/tài khoản trên bảng kê "
            "để đối chiếu trùng.",
        ))
        cells.append(_duplicate_payment_cell(packets))
        cells.append(_date_sequence_cell())
        return cells

    shared = [
        by_code[code] for code in
        ("duplicate-cccd", "duplicate-mst", "duplicate-account")
        if code in by_code
    ]
    if shared:
        cells.append(_cell(
            30, Status.NO,
            "Có dấu hiệu trùng: " + "; ".join(f.message for f in shared),
            tuple(row for f in shared for row in f.rows),
        ))
    else:
        cells.append(_cell(
            30, Status.OK,
            f"Không trùng CCCD/MST/tài khoản trên {report.people} dòng.",
        ))

    # -- #31 duplicate payment ----------------------------------------------
    cells.append(_duplicate_payment_cell(packets))

    # -- #32 document date sequence: not built ------------------------------
    cells.append(_date_sequence_cell())

    return cells


def _date_sequence_cell() -> SummaryCell:
    """#32 — no signing dates are extracted yet, so say so rather than pass."""
    return _cell(
        32, Status.PENDING,
        "Chưa kiểm tra tự động: cần ngày ký trích xuất từ Hợp đồng, Phụ lục, "
        "BBNT và bảng kê.",
    )


def _total_cell(rows, report, by_code, purchase_total) -> SummaryCell:
    """#20 — sum the rows, then find something to compare the sum against."""
    if "missing-columns" in by_code:
        return _cell(20, Status.PENDING, by_code["missing-columns"].message)

    mismatches = [
        by_code[f"total-mismatch-{key}"]
        for key in ("gross", "pit", "net")
        if f"total-mismatch-{key}" in by_code
    ]
    if mismatches:
        return _cell(
            20, Status.NO,
            "; ".join(f.message for f in mismatches),
            ("dòng tổng",),
        )

    if "no-total-row" not in by_code:
        return _cell(
            20, Status.OK,
            f"Tổng Gross/PIT/Net khớp dòng tổng trên bảng kê "
            f"({report.people} dòng).",
        )

    # No total row in the Excel -- fall back to the purchase listing's printed
    # total, which is where it actually lives on real submissions.
    sums = _column_sums(rows, report)
    if not purchase_total:
        return _cell(
            20, Status.PENDING,
            "Bảng kê không có dòng tổng. Cần tổng trên Bảng Kê Thu Mua để đối "
            f"chiếu (tổng Gross cộng được: {sums.get('gross', 0):,} đ).",
        )

    gaps = [
        f"{label}: cộng dòng = {sums.get(key, 0):,}, "
        f"{PURCHASE} = {purchase_total[key]:,}, "
        f"lệch {sums.get(key, 0) - purchase_total[key]:,}"
        for key, label in (("gross", "Gross"), ("pit", "PIT"), ("net", "Net"))
        if key in purchase_total and sums.get(key, 0) != purchase_total[key]
    ]
    if gaps:
        return _cell(20, Status.NO, "; ".join(gaps))
    checked = ", ".join(
        label for key, label in
        (("gross", "Gross"), ("pit", "PIT"), ("net", "Net"))
        if key in purchase_total
    )
    return _cell(
        20, Status.OK,
        f"{checked} khớp giữa bảng kê ({report.people} dòng) và "
        f"{PURCHASE}."
    )


def _column_sums(rows, report) -> dict[str, int]:
    columns, first_data = roster_checks.locate_columns(rows)
    people, _ = roster_checks.read_people(rows, columns, first_data)
    return {
        key: sum(roster_checks.money(p.get(key)) or 0 for p in people)
        for key in ("gross", "pit", "net")
        if key in columns
    }


def _duplicate_payment_cell(packets) -> SummaryCell:
    """#31 — warn only. Acc's rule: "Chỉ cảnh báo trùng, không tự động xóa dòng.

    The collision is recomputed from the packets' roster identities rather than
    read off `flags`: cases ingested before `pipeline.flag_duplicate_identities`
    existed carry no flag, and the stored July submission is one of them -- nine
    CCCDs on two packets each, not one flagged. A criterion whose answer depends
    on when a case was ingested is not a criterion.
    """
    if not packets:
        return _cell(
            31, Status.PENDING,
            "Chưa có gói hồ sơ nào để đối chiếu trùng thanh toán.",
        )

    identified = [p for p in packets if p.get("rosterIdentity")]
    if not identified:
        # A packet that matched nobody has no identity to collide with, so a
        # set of unmatched packets is not evidence of no duplicate payment.
        return _cell(
            31, Status.PENDING,
            f"{len(packets)} gói chưa khớp được với dòng nào trên bảng kê, "
            "chưa đối chiếu được trùng thanh toán.",
        )

    groups = _identity_groups(identified)
    if not groups:
        unmatched = len(packets) - len(identified)
        return _cell(
            31, Status.OK,
            f"Không có gói nào trùng danh tính trên {len(identified)} gói đã "
            f"khớp bảng kê"
            + (f" ({unmatched} gói chưa khớp)." if unmatched else "."),
        )

    detail = tuple(
        "gói " + " + ".join(str(i + 1) for i in group) for group in groups
    )
    involved = sum(len(group) for group in groups)
    return _cell(
        31, Status.NO,
        f"Có dấu hiệu thanh toán trùng: {len(groups)} CTV có nhiều hơn một gói "
        f"({involved} gói liên quan). Chỉ cảnh báo — cần người xác minh.",
        detail,
    )


def _identity_groups(packets) -> list[tuple[int, ...]]:
    """Packet indexes grouped by the roster row they resolve to.

    Keyed the same way `pipeline.flag_duplicate_identities` keys it -- CCCD
    digits, falling back to the accent-folded name -- so both agree on what
    counts as the same person.
    """
    from ocr_extract import norm  # lazy: keeps this module free of OCR deps

    by_key: dict[str, list[int]] = {}
    for packet in packets:
        identity = packet.get("rosterIdentity") or {}
        key = (roster_checks.digits(identity.get("cccd", ""))
               or norm(identity.get("name", "") or ""))
        if key:
            by_key.setdefault(key, []).append(packet["index"])
    # honour a flag the pipeline already set, even if the identity is gone
    for packet in packets:
        if "duplicate-roster-identity" in (packet.get("flags") or []):
            group = sorted(
                {packet["index"], *(packet.get("duplicateOf") or [])}
            )
            if len(group) > 1:
                by_key.setdefault(f"flagged:{group[0]}", list(group))
    return sorted(
        {tuple(sorted(indexes)) for indexes in by_key.values()
         if len(indexes) > 1}
    )


def summarise(cells: list[SummaryCell]) -> dict[str, int]:
    """Counts for the tab header, by criterion."""
    counts = {status.value: 0 for status in Status}
    for cell in cells:
        counts[cell.status.value] += 1
    return counts


def as_dict(cell: SummaryCell) -> dict:
    """One cell, plus the criterion metadata the reviewer acts on.

    `how` travels with every cell on purpose: when the tool abstains the
    reviewer still needs Acc's instruction to hand, or an abstention becomes a
    dead end.
    """
    criterion = BY_STT[cell.stt]
    return {
        "stt": cell.stt,
        "code": cell.code,
        "label": cell.label,
        "group": criterion.group,
        "kind": criterion.kind.value,
        "docs": list(criterion.docs),
        "how": criterion.how,
        "status": cell.status.value,
        "message": cell.message,
        "detail": list(cell.detail),
    }


def as_payload(
    rows: list[tuple],
    packets: list[dict] | None = None,
    purchase_total: dict[str, int] | None = None,
) -> dict:
    """The whole Tổng hợp tab, ready to serve.

    `missing` names the inputs that were not available, so the tab can say why
    a criterion is pending instead of leaving the reviewer to guess.
    """
    cells = assess(rows, packets, purchase_total)
    report = roster_checks.check(rows)
    missing = [
        name for name, present in (
            ("rosterRows", bool(report.people)),
            ("purchaseTotal", bool(purchase_total)),
            ("packets", bool(packets)),
        )
        if not present
    ]
    return {
        "criteria": [as_dict(cell) for cell in cells],
        "counts": summarise(cells),
        "people": report.people,
        "missing": missing,
    }
