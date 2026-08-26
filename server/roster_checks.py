"""Step 1 of Acc's checklist: validate the bảng kê against itself.

The roster is the reference every later check compares documents against, so its
own integrity comes first. These criteria need no scan, no OCR and no document --
only the Excel -- which means roster errors surface before a single page is read.

Implements, from `Checklist_Dich_vu_ca_nhan_CTV.xlsx` (32 tiêu chí):

    #2 #3 #5 #7  field formats (CCCD, ngày sinh, MST, số TK)
    #14          Gross present, positive, numeric
    #15          PIT: if zero, a basis must be stated
    #16          Net present and positive
    #17          Gross - PIT = Net, recomputed rather than trusted
    #20          the total row equals the sum of the rows
    #30          no CCCD / MST / bank account shared between people

Two things the checklist is deliberate about, and so is this module:

  * **No hardcoded tax rate.** #15 says PIT must match "mức/điều kiện áp dụng
    trong hồ sơ" -- the rate applicable to the file, not one this code invents.
    So a non-zero PIT is reported with its effective rate for a human to judge,
    and only PIT-of-zero-without-a-basis is called a finding. Anything else
    would be this tool asserting tax policy it does not know.

  * **Findings name the value, not just "không khớp".** The workbook's stated
    result principle: "Không chỉ báo 'Không khớp'; phải nêu trường sai, giá trị
    tại từng chứng từ, chênh lệch và nội dung cần kiểm tra lại."
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Column headers as Acc writes them, accent-insensitively and allowing the
# layout to shift: the February roster has no "Nơi cư trú" column and the July
# one does, so positions cannot be assumed.
_HEADER_PATTERNS = {
    "stt": (r"^stt$",),
    "name": (r"ho va ten", r"ho ten"),
    "cccd": (r"cccd", r"cmnd", r"can cuoc"),
    "mst": (r"^mst", r"ma so thue"),
    "dob": (r"ngay.*sinh",),
    "gender": (r"gioi tinh",),
    "account": (r"so tk", r"so tai khoan"),
    "bank": (r"ngan hang",),
    "period": (r"thoi gian lam viec",),
    "fee": (r"phi dich vu",),
    "gross": (r"^gross",),
    "commitment": (r"ban cam ket",),
    "pit": (r"thue pit", r"^pit"),
    "net": (r"thuc nhan",),
}

_DATE = re.compile(r"^\d{1,2}[/-]\d{1,2}[/-]\d{4}$")


def _fold(value: object) -> str:
    """Lowercase, accent-stripped, whitespace-collapsed."""
    import unicodedata

    text = str(value or "").replace("đ", "d").replace("Đ", "D")
    text = "".join(
        c for c in unicodedata.normalize("NFD", text)
        if not unicodedata.combining(c)
    )
    return re.sub(r"\s+", " ", text).strip().lower()


def digits(value: object) -> str:
    return re.sub(r"\D", "", str(value or ""))


def money(value: object) -> int | None:
    """A cell as whole đồng, or None when it is not a number at all."""
    if value is None or str(value).strip() == "":
        return None
    try:
        return round(float(re.sub(r"[^\d.\-]", "", str(value))))
    except ValueError:
        return None


@dataclass(frozen=True)
class Finding:
    """One problem, in the checklist's own vocabulary."""

    criterion: str  # e.g. "#17"
    code: str       # stable, machine-readable
    message: str    # Vietnamese, states the values -- never just "không khớp"
    rows: tuple[str, ...] = ()


@dataclass
class RosterReport:
    people: int = 0
    columns: dict[str, int] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings


def locate_columns(rows: list[tuple]) -> tuple[dict[str, int], int]:
    """Map field -> column index by reading headers, and the first data row.

    Headers can span two rows (Acc puts "Chi Phí (+ PIT)" above "Gross (1) /
    Bản cam kết / Thuế PIT (2) / Thực Nhận"), so every row up to the first
    numbered one contributes.
    """
    columns: dict[str, int] = {}
    first_data = len(rows)
    for index, row in enumerate(rows):
        if row and str(row[0] or "").strip().isdigit():
            first_data = index
            break
        for position, cell in enumerate(row or ()):
            folded = _fold(cell)
            if not folded:
                continue
            for name, patterns in _HEADER_PATTERNS.items():
                if name in columns:
                    continue
                if any(re.search(p, folded) for p in patterns):
                    columns[name] = position
    return columns, first_data


def read_people(rows: list[tuple], columns: dict[str, int], first_data: int):
    """Numbered rows only; a total row is returned separately."""
    people, totals = [], []
    for row in rows[first_data:]:
        if not row:
            continue
        head = str(row[0] or "").strip()
        record = {
            name: (row[i] if i < len(row) else None)
            for name, i in columns.items()
        }
        if head.isdigit():
            people.append(record)
        elif re.search(r"tong|total", _fold(head)):
            totals.append(record)
    return people, totals


def check(rows: list[tuple]) -> RosterReport:
    """Run every roster-level criterion over a loaded sheet."""
    columns, first_data = locate_columns(rows)
    people, totals = read_people(rows, columns, first_data)
    report = RosterReport(people=len(people), columns=columns)
    add = report.findings.append

    def stt(person) -> str:
        return str(person.get("stt") or "?")

    missing_columns = [
        name for name in ("cccd", "gross", "pit", "net")
        if name not in columns
    ]
    if missing_columns:
        add(Finding(
            "—", "missing-columns",
            "Không tìm thấy cột: " + ", ".join(missing_columns),
        ))
        return report

    # --- #14 #16 #17 amounts, recomputed ---------------------------------
    formula, zero_pit, absent = [], [], []
    for person in people:
        gross, pit, net = (money(person.get(k)) for k in ("gross", "pit", "net"))
        if None in (gross, pit, net):
            absent.append(stt(person))
            continue
        if gross - pit != net:
            formula.append(f"{stt(person)} (Gross {gross:,} − PIT {pit:,} "
                           f"≠ Net {net:,}, lệch {gross - pit - net:,})")
        # #15: zero PIT is only acceptable with a stated basis
        if pit == 0:
            basis = _fold(person.get("commitment"))
            if not basis or basis.startswith("khong"):
                zero_pit.append(f"{stt(person)} (Gross {gross:,})")

    if absent:
        add(Finding("#14/#16", "amount-missing",
                    "Thiếu Gross/PIT/Net", tuple(absent)))
    if formula:
        add(Finding("#17", "formula-mismatch",
                    "Gross − PIT ≠ Net", tuple(formula)))
    if zero_pit:
        add(Finding(
            "#15", "pit-zero-without-basis",
            "PIT bằng 0 nhưng thiếu căn cứ (cột Bản cam kết không ghi 'có')",
            tuple(zero_pit),
        ))

    # --- #30 nothing may be shared between people -------------------------
    for label, key in (("CCCD", "cccd"), ("MST", "mst"),
                       ("số tài khoản", "account")):
        if key not in columns:
            continue
        seen: dict[str, list[str]] = {}
        for person in people:
            value = digits(person.get(key))
            if value:
                seen.setdefault(value, []).append(stt(person))
        shared = tuple(
            f"dòng {'+'.join(rows_)}" for value, rows_ in seen.items()
            if len(rows_) > 1
        )
        if shared:
            add(Finding("#30", f"duplicate-{key}",
                        f"Trùng {label} giữa nhiều CTV", shared))

    # --- #2 #3 #5 #7 formats ---------------------------------------------
    bad_cccd, bad_dob, no_account = [], [], []
    for person in people:
        cccd = digits(person.get("cccd"))
        if len(cccd) != 12:
            bad_cccd.append(f"{stt(person)} ({len(cccd)} chữ số)")
        if "dob" in columns and not _DATE.match(str(person.get("dob") or "").strip()):
            bad_dob.append(stt(person))
        if "account" in columns and not digits(person.get("account")):
            no_account.append(stt(person))
    if bad_cccd:
        add(Finding("#2", "cccd-format",
                    "Số CCCD không đủ 12 chữ số", tuple(bad_cccd)))
    if bad_dob:
        add(Finding("#3", "dob-format",
                    "Ngày sinh không đúng dd/mm/yyyy", tuple(bad_dob)))
    if no_account:
        add(Finding("#7", "account-missing",
                    "Thiếu số tài khoản", tuple(no_account)))

    # --- #20 the total row must equal the sum ------------------------------
    if not totals:
        add(Finding("#20", "no-total-row",
                    "Không có dòng tổng để đối chiếu"))
    else:
        for key, label in (("gross", "Gross"), ("pit", "PIT"), ("net", "Net")):
            summed = sum(money(p.get(key)) or 0 for p in people)
            stated = money(totals[0].get(key))
            if stated is None:
                add(Finding("#20", f"total-missing-{key}",
                            f"Dòng tổng thiếu {label}"))
            elif summed != stated:
                add(Finding(
                    "#20", f"total-mismatch-{key}",
                    f"Tổng {label}: cộng dòng = {summed:,}, "
                    f"dòng tổng = {stated:,}, lệch {summed - stated:,}",
                ))
    return report
