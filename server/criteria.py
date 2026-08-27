"""Acc's 25 per-CTV criteria, the status model, and the rollup.

This is the registry and the arithmetic -- no extraction, no comparators. Those
arrive as evaluators (see docs/superpowers/specs/2026-08-26-validation-flow-design.md
step 3); this module defines what they are asked to produce and how the answers
add up.

Two things it deliberately gets right that the prototype could not:

  * A cell is `ok` only when a comparator ran and matched. The prototype defaults
    to `ok` whenever a value exists and nobody overrode it, and its own §6.2
    warns that this "không đồng nghĩa với 'đã được xác minh khớp'". Here silence
    resolves to `pending`, never agreement.

  * The summary is computed. The prototype's header pills and section counts are
    hand-typed text that has already drifted once in its history (adding #28
    meant editing "22 Khớp" to "23 Khớp" by hand).

Source of the criteria: Checklist_Binhnt10.xlsx, sheet "Requirement CTV Remove"
-- 24 criteria at Từng CTV level plus #28, added at Acc's request. `how` is
carried verbatim because it is what a reviewer follows when the tool abstains.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass
from enum import Enum
from typing import Literal

# --- documents ---------------------------------------------------------------
# Names exactly as the criteria reference them. EXCEL is the reference column:
# the prototype shows its value verbatim rather than a tick, so the reviewer has
# something to read instead of something to trust.
EXCEL = "Excel"
CCCD = "CCCD/Passport"
CONTRACT = "Hợp đồng"
BBNT = "BBNT"
PURCHASE = "Bảng Kê Thu Mua"
APPENDIX = "Phụ lục/KPI"
MST_LOOKUP = "Website tra cứu MST"
COMMITMENT = "Cam kết PIT"


class Status(str, Enum):
    """The prototype's five-state vocabulary, plus the unevaluated state.

    Better than this repo's previous verdict set because it separates *not
    applicable* from *document absent* from *needs a human* -- distinctions that
    `review`/`unread` collapsed into one.
    """

    OK = "ok"            # a comparator ran and matched
    NO = "no"            # a comparator ran and disagreed
    REVIEW = "rv"        # ambiguous, or a judgement only a person can make
    NOT_APPLICABLE = "na"
    MISSING = "missing"  # a document that should be here is not
    PENDING = "pending"  # nothing evaluated this yet


#: Worst-wins order for rolling cells up to a criterion. `missing` outranks `rv`
#: because an absent document is a gate failure, not a question. `na` is absent
#: from this order -- it is excluded from the rollup and counted separately,
#: since "not applicable" is sometimes itself the finding (24 of 32 February
#: packets legitimately have no cam kết).
_SEVERITY: tuple[Status, ...] = (
    Status.NO,
    Status.MISSING,
    Status.REVIEW,
    Status.PENDING,
    Status.OK,
)


class Kind(str, Enum):
    """Which evaluator answers a criterion. Five cover all 25."""

    COMPARE = "compare"          # a value must agree across documents
    COMPUTE = "compute"          # recompute from named inputs
    PRESENCE = "presence"        # signature/seal/content -- a person decides
    EXTERNAL = "external"        # an artefact the reviewer supplies answers it
    CONDITIONAL = "conditional"  # applies only if a document exists


Render = Literal["matrix", "card"]

GROUPS = {
    "01": "Thông tin cá nhân",
    "02": "Thông tin công ty",
    "03": "Thông tin dịch vụ và thời hạn",
    "04": "Số tiền và thuế",
    "05": "Chứng từ và ký dấu",
}


@dataclass(frozen=True)
class Criterion:
    stt: int
    label: str
    group: str
    docs: tuple[str, ...]
    how: str
    kind: Kind
    render: Render
    params: dict | None = None

    @property
    def code(self) -> str:
        """Two-digit form, as Acc and the prototype both write it."""
        return f"{self.stt:02d}"


def _c(stt, label, group, docs, kind, render, how, **params) -> Criterion:
    return Criterion(stt, label, group, tuple(docs), how, kind, render,
                     params or None)


# --- the registry ------------------------------------------------------------
# `render` is stored rather than derived. The prototype made editorial calls no
# rule reproduces -- lifting #06 and #12 out of the matrix, folding #19 into #14
# and #29 into #09 -- and those calls are good, so they are data.

CRITERIA: tuple[Criterion, ...] = (
    # -- 01. Thông tin cá nhân (8) -------------------------------------------
    _c(1, "Họ và tên", "01",
       [EXCEL, CCCD, CONTRACT, BBNT, PURCHASE], Kind.COMPARE, "matrix",
       "Kiểm tra họ tên đầy đủ, không viết tắt; đối chiếu chính xác giữa các "
       "chứng từ. Cho phép khác biệt chữ hoa/thường hoặc có/không dấu nếu vẫn "
       "xác định được cùng một người.",
       compare="person"),
    _c(2, "Số CCCD/Passport", "01",
       [EXCEL, CCCD, CONTRACT, BBNT, PURCHASE], Kind.COMPARE, "matrix",
       "Người Việt Nam: CCCD đúng số (12 ký tự) và chỉ gồm chữ số. Người nước "
       "ngoài: Passport (8 ký tự) phải khớp đúng chuỗi ký tự trên bản scan.",
       compare="digits", formats=("cccd12", "passport8")),
    _c(3, "Ngày sinh", "01",
       [EXCEL, CCCD, CONTRACT], Kind.COMPARE, "matrix",
       "Đối chiếu ngày sinh với CCCD/Passport. Dữ liệu Excel phải ở dạng text "
       '"dd/mm/yyyy" để không bị Excel tự đổi định dạng.',
       compare="date", formats=("dd/mm/yyyy",)),
    _c(4, "Giới tính Nam/Nữ", "01",
       [EXCEL, CCCD], Kind.COMPARE, "matrix",
       'Kiểm tra giá trị là "Nam" hoặc "Nữ" hoặc khác, khớp với giấy tờ định '
       "danh.",
       compare="enum", allowed=("Nam", "Nữ")),
    _c(5, "MST cá nhân", "01",
       [EXCEL, CONTRACT], Kind.COMPARE, "matrix",
       "Kiểm tra MST có 10 hoặc 12 số, chỉ gồm chữ số và lưu dạng text. Đối "
       "chiếu MST giữa các chứng từ và khớp với tra cứu MST.",
       compare="digits", formats=("mst10", "mst12")),
    _c(6, "Trạng thái MST", "01",
       [MST_LOOKUP], Kind.EXTERNAL, "card",
       "Tra cứu MST thuộc đúng CTV và kiểm tra trạng thái đang hoạt động tại "
       "thời điểm kiểm tra (tracuunnt.gdt.gov.vn).",
       source="tracuunnt.gdt.gov.vn"),
    _c(7, "Số tài khoản", "01",
       [EXCEL, CONTRACT, BBNT], Kind.COMPARE, "matrix",
       "Kiểm tra đúng cấu trúc tài khoản ngân hàng; lưu dạng text để không mất "
       "số 0 đầu. Đối chiếu số tài khoản giữa các chứng từ.",
       compare="digits", keep_leading_zeros=True),
    _c(8, "Thông tin ngân hàng", "01",
       [EXCEL, CONTRACT, BBNT], Kind.COMPARE, "matrix",
       "Kiểm tra có đủ 3 nội dung: Tên ngân hàng – Chi nhánh – Tỉnh/TP.",
       compare="text", parts=("bank", "branch", "province")),

    # -- 02. Thông tin công ty (1) -------------------------------------------
    _c(27, "Thông tin công ty VNG khớp Hợp đồng ↔ BBNT ↔ Bảng Kê Thu Mua", "02",
       [CONTRACT, BBNT, PURCHASE], Kind.COMPARE, "matrix",
       "Đối chiếu tên pháp nhân, MST, địa chỉ, người đại diện và chức danh của "
       "VNG giữa Hợp đồng, BBNT và Bảng Kê Thu Mua. Nếu MST user điền là VNG "
       "thì đối chiếu với thông tin của VNG; nếu MST là công ty Adtima thì đối "
       "chiếu với thông tin của Adtima.",
       compare="organisation",
       parts=("legal_name", "mst", "address", "representative", "title")),

    # -- 03. Thông tin dịch vụ và thời hạn (5) -------------------------------
    _c(9, "Nội dung dịch vụ", "03",
       [EXCEL, CONTRACT, BBNT, APPENDIX], Kind.COMPARE, "matrix",
       "Kiểm tra mô tả rõ CTV thực hiện công việc gì, cho chương trình/dự án "
       "nào và trong kỳ nào.",
       compare="text"),
    _c(10, "Ngày bắt đầu thực hiện", "03",
       [EXCEL, CONTRACT, APPENDIX], Kind.COMPARE, "matrix",
       "Trích xuất và đối chiếu ngày bắt đầu giữa Excel với Hợp đồng/Phụ lục. "
       "Ngày bắt đầu không trước ngày hợp đồng có hiệu lực, trừ khi hồ sơ có "
       "căn cứ phù hợp.",
       compare="date"),
    _c(11, "Ngày kết thúc thực hiện", "03",
       [EXCEL, CONTRACT, BBNT, APPENDIX], Kind.COMPARE, "matrix",
       "Đối chiếu ngày kết thúc giữa các chứng từ; ngày kết thúc phải bằng hoặc "
       "sau ngày bắt đầu và không vượt phạm vi Hợp đồng/Phụ lục.",
       compare="date", not_before=10),
    _c(12, "Thời hạn dịch vụ", "03",
       [CONTRACT, APPENDIX], Kind.COMPUTE, "card",
       "Tính số ngày từ ngày bắt đầu (10) đến ngày kết thúc (11) — gộp thành 1 "
       "con số thời hạn duy nhất, không tách theo từng chứng từ. Nếu thời hạn "
       "từ 1 tháng trở lên, phát cảnh báo để xem xét theo quy định nội bộ; "
       "không tự kết luận hồ sơ không hợp lệ.",
       formula="day_span", inputs=(10, 11), warn_at_days=31),
    _c(13, "Thời hạn & phương thức thanh toán", "03",
       [CONTRACT, APPENDIX, BBNT], Kind.COMPARE, "matrix",
       "Kiểm tra có đủ: số tiền hoặc căn cứ tính phí, thời hạn thanh toán, mốc "
       "bắt đầu tính hạn, phương thức thanh toán và tài khoản nhận tiền. Cảnh "
       "báo nếu các chứng từ ghi thời hạn khác nhau.",
       compare="text",
       parts=("amount_basis", "term", "term_start", "method", "account")),

    # -- 04. Số tiền và thuế (5) ---------------------------------------------
    _c(14, "Gross (Hợp đồng/BBNT/Bảng Kê Thu Mua = Gross Excel)", "04",
       [EXCEL, CONTRACT, BBNT, PURCHASE, APPENDIX], Kind.COMPUTE, "card",
       "Kiểm tra Gross là tổng thu nhập/phí dịch vụ trước PIT, là số dương và "
       "đúng định dạng tiền tệ. Đối chiếu giá trị trên Hợp đồng/BBNT/Bảng Kê "
       "Thu Mua với Gross trên Excel.",
       formula="money_agreement", reference=EXCEL),
    _c(15, "PIT", "04",
       [EXCEL], Kind.COMPUTE, "card",
       "PIT là tính toán theo rule (ngưỡng áp dụng + tình trạng cam kết), không "
       "đối chiếu trực tiếp giữa các chứng từ. Nếu PIT bằng 0, phải xác định có "
       "cam kết hoặc căn cứ miễn/không khấu trừ phù hợp.",
       # No rate here on purpose. The checklist asserts only that zero PIT needs
       # a stated basis; the applicable rate lives in the file, not in this code.
       formula="pit_basis", inputs=(18,)),
    _c(16, "Net", "04",
       [EXCEL], Kind.COMPUTE, "card",
       "Kiểm tra Net là số tiền thực trả cho CTV, là số dương và khớp với số "
       "tiền đề nghị thanh toán.",
       formula="positive"),
    _c(17, "Công thức Gross − PIT = Net", "04",
       [EXCEL], Kind.COMPUTE, "card",
       "Tính lại cho từng CTV, không chỉ kiểm tra công thức hiển thị trong "
       "Excel. Đây là điểm đối chiếu thật sự của nhóm Số tiền — xác định rõ số "
       "tiền chênh lệch nếu có.",
       formula="gross_minus_pit_equals_net", inputs=(14, 15, 16)),
    _c(18, "Cam kết không khấu trừ PIT (Mẫu 08/CK-TNCN)", "04",
       [COMMITMENT, EXCEL, CCCD], Kind.CONDITIONAL, "card",
       "Kiểm tra đúng mẫu áp dụng; có họ tên, MST, CCCD, năm cam kết, ngày ký "
       "và chữ ký CTV; thông tin khớp hồ sơ. Trạng thái Có/Không của cam kết "
       "này là đầu vào để tính PIT theo rule ở trên.",
       gates=(15,), requires_document=COMMITMENT),

    # -- 05. Chứng từ và ký dấu (6) ------------------------------------------
    # Every one is locate-and-look: the tool navigates to the block, the human
    # decides. None of them may resolve automatically.
    _c(21, "Hợp đồng có chữ ký CTV", "05",
       [CONTRACT], Kind.PRESENCE, "matrix",
       "Kiểm tra có chữ ký của đúng CTV tại vị trí dành cho bên cung cấp dịch "
       "vụ; không chấp nhận trang ký bị thiếu hoặc không xác định được người ký."),
    _c(22, "Hợp đồng có chữ ký và dấu/giáp lai VNG", "05",
       [CONTRACT], Kind.PRESENCE, "matrix",
       "Kiểm tra có chữ ký đúng thẩm quyền hoặc đúng luồng phê duyệt; có dấu "
       "công ty và giáp lai/đóng dấu theo yêu cầu đối với hồ sơ nhiều trang."),
    _c(23, "BBNT có chữ ký CTV", "05",
       [BBNT], Kind.PRESENCE, "matrix",
       "Kiểm tra có chữ ký đúng CTV và thông tin người ký khớp với Hợp đồng."),
    _c(24, "BBNT có chữ ký và dấu/giáp lai VNG", "05",
       [BBNT], Kind.PRESENCE, "matrix",
       "Kiểm tra có chữ ký người đại diện/người phê duyệt phía VNG; có dấu và "
       "giáp lai theo yêu cầu."),
    _c(25, "Phụ lục/KPI có ký, dấu đầy đủ (nếu có)", "05",
       [APPENDIX], Kind.PRESENCE, "matrix",
       "Kiểm tra Phụ lục/KPI có đủ chữ ký các bên, dấu/giáp lai và dẫn chiếu "
       "đúng Hợp đồng. Nội dung, kỳ thực hiện và mức phí phải thống nhất với "
       "hồ sơ.",
       optional=True),
    _c(28, "Bảng Kê Thu Mua có chữ ký người lập & dấu doanh nghiệp", "05",
       [PURCHASE], Kind.PRESENCE, "matrix",
       "Bảng Kê Thu Mua (mẫu 02/TNDN) là chứng từ hợp lý hoá chi phí không hoá "
       "đơn nên bắt buộc phải có chữ ký người lập bảng kê và dấu tròn của doanh "
       "nghiệp ở cuối bảng kê mới hợp lệ."),
)

BY_STT: dict[int, Criterion] = {c.stt: c for c in CRITERIA}

#: The five criteria that apply to the whole bảng kê rather than one CTV, and so
#: belong to the Tổng hợp tab. Their STTs were unknown to the prototype (its
#: Open Question #2); the other checklist's `Cấp độ` column resolves them, and
#: they match its .scope-note list in order. #19 is NOT one of them -- it is
#: "Phí dịch vụ khớp giữa các chứng từ", folded into #14's card.
ROSTER_LEVEL_STT: tuple[int, ...] = (20, 26, 30, 31, 32)


def in_group(group: str) -> tuple[Criterion, ...]:
    return tuple(c for c in CRITERIA if c.group == group)


def group_counts() -> dict[str, int]:
    """Criteria per display section -- computed, not typed."""
    return dict(collections.Counter(c.group for c in CRITERIA))


# --- cells and rollup --------------------------------------------------------

@dataclass(frozen=True)
class Cell:
    """One (criterion, document) result."""

    stt: int
    document: str
    status: Status
    #: why, in Acc's terms; shown in the evidence panel. Required for anything
    #: that is not OK, so an abstention is never a dead end.
    reason: str = ""


def override_key(stt: int, document: str) -> str:
    """Address one cell of the matrix: `"01:Hợp đồng"`.

    Two-digit STT so keys sort the way Acc writes them, and the document name
    verbatim from the module constants -- not an index, which would silently
    re-point if the criteria registry were ever reordered.
    """
    return f"{stt:02d}:{document}"


@dataclass(frozen=True)
class Override:
    """A reviewer's decision on one cell, with what the engine thought.

    `from_status` is retained deliberately. An override of `ok -> no` says the
    engine was wrong in the dangerous direction; `pending -> ok` says a human
    supplied coverage the engine lacked. Recorded from day one these accumulate
    into the labelled corpus this project does not otherwise have, at no
    marginal cost -- see the spec's §6.

    `by` stays empty until there is auth to fill it. That is the spec's own
    allowance, and it means every record made before then is unattributable;
    worth knowing rather than pretending otherwise.
    """

    stt: int
    document: str
    from_status: Status
    to_status: Status
    at: str
    #: Optional. Acc's call: a decision is one click, so requiring a written
    #: reason on each of 322 `rv` cells would be a different product. The field
    #: stays for a reviewer who wants to say why.
    reason: str = ""
    by: str = ""

    def __post_init__(self) -> None:
        if self.stt in ROSTER_LEVEL_STT or self.stt not in BY_STT:
            # The roster-level five hang off no packet and have no document
            # axis, so they cannot be addressed this way at all.
            raise ValueError(
                f"stt {self.stt} is not a per-CTV criterion")
        if not applies(BY_STT[self.stt], self.document):
            raise ValueError(
                f"document {self.document!r} is not in criterion "
                f"#{self.stt:02d}'s scope")
        if Status.NOT_APPLICABLE in (self.from_status, self.to_status):
            # `na` says the document is outside the criterion -- a fact about
            # the checklist, not a judgment, so there is nothing to decide.
            raise ValueError("na is not a decidable status")

    @property
    def key(self) -> str:
        return override_key(self.stt, self.document)

    @property
    def confirms(self) -> bool:
        """A decision that agrees with the engine.

        Recording one is not a no-op: it is a person putting their name and a
        timestamp to the machine's finding, which is what lets `cần gửi lại`
        count conclusions rather than candidates. Without it a reviewer who
        agrees with a computed `no` has no way to say so, and the count that is
        supposed to be the primary number would sit at zero forever.
        """
        return self.from_status is self.to_status

    def as_dict(self) -> dict:
        return {
            "stt": self.stt,
            "document": self.document,
            "fromStatus": self.from_status.value,
            "toStatus": self.to_status.value,
            "reason": self.reason,
            "at": self.at,
            "by": self.by,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "Override":
        return cls(
            stt=int(raw["stt"]),
            document=raw["document"],
            from_status=Status(raw["fromStatus"]),
            to_status=Status(raw["toStatus"]),
            reason=raw["reason"],
            at=raw["at"],
            by=raw.get("by", ""),
        )


def applies(criterion: Criterion, document: str) -> bool:
    """Whether this document is in scope for this criterion.

    A document outside `docs` renders as a static dash and is not clickable --
    distinct from a clickable `na`, which can explain itself.
    """
    return document in criterion.docs


def cell_status(
    criterion: Criterion,
    document: str,
    computed: Status | None,
    override: Status | None = None,
) -> Status:
    """Resolve one cell. Overrides win; absence never becomes agreement.

    `computed` is what an evaluator produced, or None if none ran. The
    prototype returns `ok` in that case; we return `pending`, which is the whole
    point of this design.
    """
    if not applies(criterion, document):
        return Status.NOT_APPLICABLE
    if override is not None:
        return override
    if computed is not None:
        return computed
    if criterion.kind is Kind.PRESENCE:
        # The tool cannot judge a signature, so it asks. Six of 25 criteria
        # therefore open amber on every packet -- correct, not a defect.
        return Status.REVIEW
    return Status.PENDING


def roll_up(statuses) -> Status:
    """One status for a criterion from its cells: worst wins.

    `na` is excluded -- a criterion every one of whose cells is `na` is itself
    `na`, but a single applicable cell decides otherwise.
    """
    considered = [s for s in statuses if s is not Status.NOT_APPLICABLE]
    if not considered:
        return Status.NOT_APPLICABLE
    for status in _SEVERITY:
        if status in considered:
            return status
    return Status.PENDING


def summarise(criterion_statuses: dict[int, Status]) -> dict[str, int]:
    """Header counts, by criterion rather than by cell.

    The prototype's own header settles the unit: 23 Khớp + 1 Cần review +
    1 Không áp dụng = 25, its criterion count. Counting cells would make a
    criterion spanning five documents five times as important as one spanning
    a single document.
    """
    counts = collections.Counter(criterion_statuses.values())
    return {status.value: counts.get(status, 0) for status in Status}
