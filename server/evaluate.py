"""The evaluator engine: one packet's manifest in, Acc's 25-criterion matrix out.

This is the point at which the matrix stops being hand-typed. `criteria.py`
defines what the criteria are and how answers add up; `compare_values.py` holds
the comparison rules; this walks a packet and produces a `Cell` per
(criterion, document) pair with the evidence behind it.

Two rules run through the whole module:

  * A cell is `ok` only when a comparator actually ran and matched. Anything
    else is `pending`, `missing`, `rv` or `na` -- never a quiet pass.
  * Every non-`na` cell can answer "where did you get that?". `Evidence` carries
    the document, page, box, value, confidence and provenance, because a value
    read by IDP at 0.97 and one read by Tesseract at 0.0-with-a-box are
    different kinds of claim.

Coverage is bounded by extraction, not by this code. Six fields are extracted
today (`hoten`, `cccd`, `mst`, `tk`, `ngaysinh`, `phi`), so the criteria that
depend on service descriptions, dates, bank branches or VNG's own particulars
report `pending` with a stated reason. That is the honest state, and the matrix
fills in as extraction grows rather than as this file grows.
"""
from __future__ import annotations

from dataclasses import dataclass

import compare_values as cv
import criteria as cr
from criteria import Criterion, Status

# --- how criterion documents map onto what a packet actually contains ---------

#: Manifest `doc.kind` values behind each criterion document name. `EXCEL` is
#: the roster row, not a scanned document, and `PURCHASE` is batch-level -- one
#: listing covers every CTV and sits outside every packet -- so neither appears
#: here.
DOC_KINDS: dict[str, tuple[str, ...]] = {
    cr.CCCD: ("id_front", "id_back"),
    cr.CONTRACT: ("contract",),
    cr.BBNT: ("bbnt",),
    cr.APPENDIX: ("appendix",),
    cr.MST_LOOKUP: ("pit",),
    cr.COMMITMENT: ("commitment",),
}

#: Which extracted field answers each criterion. The gaps are the extraction
#: backlog, not missing logic here.
FIELD_BY_STT: dict[int, str] = {
    1: "hoten",
    2: "cccd",
    3: "ngaysinh",
    5: "mst",
    7: "tk",
    14: "phi",
}

#: Roster keys the reference column reads, by criterion.
ROSTER_KEY_BY_STT: dict[int, str] = {
    1: "name",
    2: "cccd",
    3: "dob",
    4: "gender",
    5: "mst",
    7: "account",
    14: "gross",
    15: "pit",
    16: "net",
}


@dataclass(frozen=True)
class Evidence:
    """Where a value came from, and how much of a claim it is."""

    document_id: str
    page: int
    bbox: dict | None
    value: str
    confidence: float | None
    #: "ocr" | "idp" | "roster" | "override"
    provenance: str


@dataclass(frozen=True)
class Cell:
    document: str
    status: Status
    #: What was read here, verbatim -- the reviewer reads it rather than
    #: trusting a tick.
    value: str
    note: str
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True)
class CriterionResult:
    stt: int
    status: Status
    cells: tuple[Cell, ...]
    note: str = ""

    @property
    def code(self) -> str:
        return f"{self.stt:02d}"


def evaluate_packet(manifest: dict, roster_row: dict | None) -> list[CriterionResult]:
    """Every criterion's status for one packet, with the evidence behind it."""
    context = _Context(manifest, roster_row)
    return [_evaluate(criterion, context) for criterion in cr.CRITERIA]


def summarise(results: list[CriterionResult]) -> dict[str, int]:
    """Counts by criterion, not by cell -- see the spec's §4.1."""
    return cr.summarise({r.stt: r.status for r in results})


class _Context:
    """One packet's documents, extracted fields and roster row."""

    def __init__(self, manifest: dict, roster_row: dict | None) -> None:
        self.roster = roster_row or {}
        self.docs = manifest.get("docs") or []
        self.by_kind: dict[str, list[dict]] = {}
        for document in self.docs:
            self.by_kind.setdefault(document.get("kind", ""), []).append(document)
        self.sources: dict[str, dict[str, list[dict]]] = {}
        for field in manifest.get("fields") or []:
            per_doc: dict[str, list[dict]] = {}
            for src in field.get("sources") or []:
                per_doc.setdefault(src.get("docId", ""), []).append(src)
            self.sources[field.get("key", "")] = per_doc

    def documents_for(self, name: str) -> list[dict]:
        return [d for kind in DOC_KINDS.get(name, ())
                for d in self.by_kind.get(kind, [])]

    def has(self, name: str) -> bool:
        return bool(self.documents_for(name))

    def sources_for(self, field_key: str, document: dict) -> list[dict]:
        return self.sources.get(field_key, {}).get(document.get("id", ""), [])

    def reference(self, stt: int) -> str:
        key = ROSTER_KEY_BY_STT.get(stt)
        return str(self.roster.get(key, "") or "").strip() if key else ""

    def money(self, key: str) -> int | None:
        import roster_checks
        return roster_checks.money(self.roster.get(key))


# --- dispatch ----------------------------------------------------------------

def _evaluate(criterion: Criterion, ctx: _Context) -> CriterionResult:
    if criterion.kind is cr.Kind.CONDITIONAL:
        return _conditional(criterion, ctx)
    if criterion.kind is cr.Kind.COMPUTE:
        return _compute(criterion, ctx)
    if criterion.kind is cr.Kind.PRESENCE:
        return _presence(criterion, ctx)
    if criterion.kind is cr.Kind.EXTERNAL:
        return _external(criterion, ctx)
    return _compare(criterion, ctx)


def _result(criterion: Criterion, cells: list[Cell], note: str = "") -> CriterionResult:
    return CriterionResult(
        criterion.stt, cr.roll_up([c.status for c in cells]), tuple(cells), note,
    )


# --- compare -----------------------------------------------------------------

def _compare(criterion: Criterion, ctx: _Context) -> CriterionResult:
    cells = [_document_cell(criterion, name, ctx) for name in criterion.docs]
    return _result(criterion, cells)


def _document_cell(criterion: Criterion, name: str, ctx: _Context) -> Cell:
    if name == cr.EXCEL:
        return _reference_cell(criterion, ctx)
    if name == cr.PURCHASE:
        return _batch_level_cell(criterion, name)
    return _scanned_cell(criterion, name, ctx)


def _reference_cell(criterion: Criterion, ctx: _Context) -> Cell:
    """The Excel column: the value the other documents are checked against.

    Shown verbatim rather than as a tick, and its own status is Acc's format
    rule for the field -- #02 twelve digits, #03 text `dd/mm/yyyy`, #07 digits
    keeping the leading zero.
    """
    if not ctx.roster:
        return Cell(cr.EXCEL, Status.PENDING, "",
                    "Gói hồ sơ chưa khớp được dòng nào trên bảng kê.")
    value = ctx.reference(criterion.stt)
    if not value:
        return Cell(cr.EXCEL, Status.PENDING, "",
                    "Bảng kê không có giá trị cho tiêu chí này.")
    evidence = (Evidence("roster", 0, None, value, None, "roster"),)
    formats = (criterion.params or {}).get("formats", ())
    if formats and not cv.matches_format(value, formats):
        return Cell(cr.EXCEL, Status.NO, value,
                    f"Sai định dạng: cần {_format_note(formats)}.", evidence)
    return Cell(cr.EXCEL, Status.OK, value,
                "Giá trị tham chiếu trên bảng kê"
                + (f", đúng định dạng {_format_note(formats)}." if formats
                   else "."),
                evidence)


_FORMAT_NOTES = {
    "cccd12": "12 chữ số",
    "passport8": "hộ chiếu 8 ký tự",
    "mst10": "10 chữ số",
    "mst12": "12 chữ số",
    "dd/mm/yyyy": "dạng text dd/mm/yyyy",
}


def _format_note(formats: tuple[str, ...]) -> str:
    return " hoặc ".join(_FORMAT_NOTES.get(f, f) for f in formats)


def _batch_level_cell(criterion: Criterion, name: str) -> Cell:
    """One Bảng Kê Thu Mua covers every CTV, so a packet not holding it is not
    a missing document. Its own checks live on the Tổng hợp tab."""
    return Cell(name, Status.PENDING, "",
                "Chứng từ toàn bảng kê — kiểm tra ở tab Tổng hợp, "
                "chưa đối chiếu theo từng CTV.")


def _scanned_cell(criterion: Criterion, name: str, ctx: _Context) -> Cell:
    documents = ctx.documents_for(name)
    if not documents:
        if (criterion.params or {}).get("optional"):
            return Cell(name, Status.NOT_APPLICABLE, "",
                        f"Hồ sơ không có {name} — tiêu chí ghi \"nếu có\".")
        return Cell(name, Status.MISSING, "",
                    f"Hồ sơ thiếu {name}.")

    field_key = FIELD_BY_STT.get(criterion.stt)
    if field_key is None:
        return Cell(name, Status.PENDING, "",
                    f"Chưa trích xuất được nội dung cần đối chiếu từ {name}.")

    reads = [
        (document, src)
        for document in documents
        for src in ctx.sources_for(field_key, document)
    ]
    if not reads:
        return Cell(name, Status.PENDING, "",
                    f"Có {name} trong hồ sơ nhưng chưa trích xuất được giá trị.")

    reference = ctx.reference(criterion.stt)
    if not reference:
        return Cell(name, Status.PENDING, "",
                    "Chưa có giá trị tham chiếu trên bảng kê để đối chiếu.")

    kind = (criterion.params or {}).get("compare") or _COMPUTED_KIND.get(
        (criterion.params or {}).get("formula", ""), "text")
    return _compare_reads(criterion, name, reads, reference, len(documents), kind)


#: `compute` criteria have no `compare` param, but their document cells still
#: need a comparison rule -- #14 checks Gross on each scan against the Excel,
#: which is money, not text.
_COMPUTED_KIND = {"money_agreement": "money"}


def _compare_reads(
    criterion: Criterion,
    name: str,
    reads: list[tuple[dict, dict]],
    reference: str,
    copies: int,
    kind: str,
) -> Cell:
    """Compare every copy of `name` in the packet against the reference.

    An unreadable copy is excluded rather than counted as disagreement -- that
    is what a reviewer does with an illegible page. Only when every copy is
    unreadable does the cell go `pending`. Among the readable ones, worst wins:
    a packet holding two contracts where one names a different CTV is a
    mis-split, and must not look clean because the other copy agrees.
    """
    allowed = (criterion.params or {}).get("allowed", ())

    readable, evidence, blank = [], [], 0
    for document, src in reads:
        value = str(src.get("value", "") or "").strip()
        confidence = src.get("confidence")
        evidence.append(Evidence(
            document.get("id", ""), int(src.get("page", 0) or 0),
            src.get("bbox"), value, confidence, "ocr",
        ))
        if not value:
            blank += 1
            continue
        readable.append((
            cv.compare(reference, value, kind, confidence, allowed),
            value, confidence, src.get("bbox"),
        ))

    if not readable:
        return Cell(name, Status.PENDING, "",
                    f"Đọc được {name} nhưng không lấy được giá trị "
                    f"({blank}/{len(reads)} bản không đọc được).",
                    tuple(evidence))

    worst = min(readable, key=lambda r: _VERDICT_RANK[r[0]])
    verdict, value, confidence, bbox = worst
    values = sorted({v for _, v, _, _ in readable})
    return Cell(
        name, cv.to_status(verdict),
        " · ".join(values),
        _compare_note(verdict, reference, values, confidence, bbox, copies,
                      len(readable), kind),
        tuple(evidence),
    )


_VERDICT_RANK = {
    cv.Verdict.MISMATCH: 0,
    cv.Verdict.FUZZY: 1,
    cv.Verdict.LOW_CONF: 2,
    cv.Verdict.MATCH: 3,
}


#: Up to this many differing digits reads as a misread rather than a different
#: number. Measured on the real July packets: of 22 disagreeing account and
#: CCCD reads, 2 sat at one digit and 20 were entirely different numbers -- so
#: this only ever annotates, it never changes the status.
_MISREAD_DIGITS = 2


def _digit_gap(kind: str, reference: str, values: list[str]) -> str:
    """How far a numeric disagreement is from the reference, when it is close.

    Never softens the status: a bank account that differs is a finding either
    way. It tells the reviewer whether to expect a misread or a wrong number.
    """
    if kind not in ("digits", "money") or len(values) != 1:
        return ""
    a, b = cv._digits(reference), cv._digits(values[0])
    if not a or not b:
        return ""
    gap = cv._levenshtein(a, b)
    if not 0 < gap <= _MISREAD_DIGITS:
        return ""
    return (f"Chênh {gap} chữ số — có thể do đọc sai, cần đối chiếu trên bản "
            "scan.")


def _compare_note(
    verdict, reference, values, confidence, bbox, copies, readable, kind,
) -> str:
    """Acc's rule: never just "không khớp" -- name the value and the reference."""
    coverage = f"{readable}/{copies} bản" if copies > 1 else ""
    parts: list[str] = []

    if verdict is cv.Verdict.MISMATCH:
        parts.append(f"Không khớp bảng kê ({reference}).")
        if len(values) > 1:
            parts.append(f"{copies} bản ghi khác nhau: {', '.join(values)}.")
        hint = _digit_gap(kind, reference, values)
        if hint:
            parts.append(hint)
    elif verdict is cv.Verdict.FUZZY:
        parts.append(
            "Chỉ khác dấu hoặc chữ hoa/thường so với bảng kê "
            f"({reference}) — cần người xác nhận đúng một người."
            if kind in ("person", "organisation", "enum")
            else f"Gần khớp bảng kê ({reference}) — cần người xác nhận."
        )
    elif verdict is cv.Verdict.LOW_CONF:
        shown = f"{confidence:.2f}" if isinstance(confidence, (int, float)) else "?"
        parts.append(f"Khớp bảng kê nhưng độ tin cậy đọc thấp ({shown}) — "
                     "cần người xác nhận.")
    else:
        parts.append(f"Khớp bảng kê ({reference}).")
        if coverage:
            parts.append(f"Đối chiếu được {coverage}.")

    if bbox is None:
        parts.append("Chưa định vị được vị trí trên trang.")
    return " ".join(parts)


# --- presence ----------------------------------------------------------------

def _presence(criterion: Criterion, ctx: _Context) -> CriterionResult:
    """Locate and look. The tool navigates to the block; the person decides.

    A `presence` cell never resolves automatically -- not to `ok` and not to
    `no`. It does resolve to `missing` when the document itself is absent,
    because there is then nothing to look at.
    """
    cells = []
    for name in criterion.docs:
        if name == cr.PURCHASE:
            cells.append(Cell(
                name, Status.REVIEW, "",
                "Cần người kiểm tra chữ ký người lập và dấu doanh nghiệp trên "
                "Bảng Kê Thu Mua — chứng từ toàn bảng kê, dùng chung cho mọi "
                "CTV.",
            ))
            continue
        if not ctx.has(name):
            if (criterion.params or {}).get("optional"):
                cells.append(Cell(name, Status.NOT_APPLICABLE, "",
                                  f"Hồ sơ không có {name} — tiêu chí ghi "
                                  '"nếu có".'))
            else:
                cells.append(Cell(name, Status.MISSING, "",
                                  f"Hồ sơ thiếu {name} nên không có chữ ký để "
                                  "kiểm tra."))
            continue
        cells.append(Cell(
            name, Status.REVIEW, "",
            f"Cần người kiểm tra chữ ký/dấu trên {name} — công cụ chỉ dẫn đến "
            "vị trí, không tự kết luận.",
            tuple(Evidence(d.get("id", ""), 0, None, "", None, "ocr")
                  for d in ctx.documents_for(name)),
        ))
    return _result(criterion, cells)


# --- external ----------------------------------------------------------------

def _external(criterion: Criterion, ctx: _Context) -> CriterionResult:
    """#06 reads an artefact the reviewer supplies -- no live lookup."""
    cells = []
    for name in criterion.docs:
        if not ctx.has(name):
            cells.append(Cell(name, Status.MISSING, "",
                              f"Hồ sơ thiếu {name} nên chưa xác định được "
                              "trạng thái MST."))
            continue
        cells.append(Cell(
            name, Status.REVIEW, "",
            "Cần người đọc kết quả tra cứu MST: đúng CTV và đang hoạt động "
            "tại thời điểm kiểm tra.",
            tuple(Evidence(d.get("id", ""), 0, None, "", None, "ocr")
                  for d in ctx.documents_for(name)),
        ))
    return _result(criterion, cells)


# --- conditional -------------------------------------------------------------

def _conditional(criterion: Criterion, ctx: _Context) -> CriterionResult:
    """#18: its absence is an answer, and that answer is an input to #15."""
    required = (criterion.params or {}).get("requires_document", "")
    if not ctx.has(required):
        note = (f"Không có {required} trong hồ sơ — trạng thái này là đầu vào "
                "của tiêu chí PIT (#15).")
        cells = [Cell(name, Status.NOT_APPLICABLE, "", note)
                 for name in criterion.docs]
        return _result(criterion, cells, note)
    note = (f"Có {required} trong hồ sơ — cần người kiểm tra đúng mẫu, họ tên, "
            "MST, CCCD, năm cam kết, ngày ký và chữ ký CTV.")
    cells = [Cell(name, Status.REVIEW, "", note) for name in criterion.docs]
    return _result(criterion, cells, note)


# --- compute -----------------------------------------------------------------

def _compute(criterion: Criterion, ctx: _Context) -> CriterionResult:
    formula = (criterion.params or {}).get("formula", "")
    handler = _FORMULAS.get(formula)
    if handler is None:
        return _pending_compute(criterion, f"Chưa hỗ trợ công thức {formula}.")
    return handler(criterion, ctx)


def _pending_compute(criterion: Criterion, note: str) -> CriterionResult:
    cells = [Cell(name, Status.PENDING, "", note) for name in criterion.docs]
    return _result(criterion, cells, note)


def _computed(criterion: Criterion, status: Status, note: str,
              value: str = "") -> CriterionResult:
    cells = [Cell(name, status, value, note) for name in criterion.docs]
    return _result(criterion, cells, note)


def _gross_minus_pit_equals_net(criterion: Criterion, ctx: _Context) -> CriterionResult:
    """#17 — recomputed, never read off the sheet. Acc: "Tính lại cho từng CTV,
    không chỉ kiểm tra công thức hiển thị trong Excel."."""
    gross, pit, net = (ctx.money(k) for k in ("gross", "pit", "net"))
    if None in (gross, pit, net):
        missing = [label for label, v in
                   (("Gross", gross), ("PIT", pit), ("Net", net)) if v is None]
        return _pending_compute(
            criterion, f"Bảng kê thiếu {', '.join(missing)} để tính lại.")
    gap = gross - pit - net
    if gap:
        return _computed(
            criterion, Status.NO,
            f"Tính lại: {gross:,} − {pit:,} = {gross - pit:,}, "
            f"bảng kê ghi Net {net:,}, lệch {gap:,}.",
            f"{net:,}",
        )
    return _computed(
        criterion, Status.OK,
        f"Tính lại đúng: {gross:,} − {pit:,} = {net:,}.", f"{net:,}",
    )


def _positive(criterion: Criterion, ctx: _Context) -> CriterionResult:
    """#16 — Net must be a positive amount actually paid to the CTV."""
    net = ctx.money("net")
    if net is None:
        return _pending_compute(criterion, "Bảng kê không có Net để kiểm tra.")
    if net <= 0:
        return _computed(criterion, Status.NO,
                         f"Net phải là số dương, bảng kê ghi {net:,}.",
                         f"{net:,}")
    return _computed(criterion, Status.OK,
                     f"Net dương: {net:,}. Còn cần đối chiếu với số tiền đề "
                     "nghị thanh toán.", f"{net:,}")


def _pit_basis(criterion: Criterion, ctx: _Context) -> CriterionResult:
    """#15 — the rule, not the rate. §7: the applicable rate is Acc's to state."""
    pit = ctx.money("pit")
    if pit is None:
        return _pending_compute(criterion, "Bảng kê không có PIT để kiểm tra.")
    if pit == 0:
        if ctx.has(cr.COMMITMENT):
            return _computed(
                criterion, Status.OK,
                "PIT bằng 0 và hồ sơ có cam kết (Mẫu 08/CK-TNCN) làm căn cứ.",
                "0",
            )
        return _computed(
            criterion, Status.NO,
            "PIT bằng 0 nhưng hồ sơ không có cam kết hoặc căn cứ miễn/không "
            "khấu trừ.", "0",
        )
    return _computed(
        criterion, Status.PENDING,
        f"PIT {pit:,} — chưa kiểm tra tự động: thuế suất và ngưỡng áp dụng "
        "thuộc quy định trong checklist, không hard-code trong công cụ.",
        f"{pit:,}",
    )


def _money_agreement(criterion: Criterion, ctx: _Context) -> CriterionResult:
    """#14 — Gross on each document against Gross on the Excel."""
    cells = [_document_cell(criterion, name, ctx) for name in criterion.docs]
    gross = ctx.money("gross")
    note = (f"Gross bảng kê: {gross:,}." if gross is not None
            else "Bảng kê không có Gross.")
    if gross is not None and gross <= 0:
        cells = [Cell(c.document, Status.NO, c.value,
                      f"Gross phải là số dương, bảng kê ghi {gross:,}.",
                      c.evidence) for c in cells]
        note = f"Gross không dương: {gross:,}."
    return _result(criterion, cells, note)


def _day_span(criterion: Criterion, ctx: _Context) -> CriterionResult:
    """#12 — needs the start and end dates, which nothing extracts yet."""
    return _pending_compute(
        criterion,
        "Chưa tính được thời hạn: cần ngày bắt đầu (#10) và ngày kết thúc "
        "(#11) trích xuất từ Hợp đồng/Phụ lục.",
    )


_FORMULAS = {
    "gross_minus_pit_equals_net": _gross_minus_pit_equals_net,
    "positive": _positive,
    "pit_basis": _pit_basis,
    "money_agreement": _money_agreement,
    "day_span": _day_span,
}
