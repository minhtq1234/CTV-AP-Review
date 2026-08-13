"""Pure conversion of private document text into fixed CTV inspection signals."""

import dataclasses
import re
import unicodedata

from ctv_inspection_model import (
    ConfidenceBand,
    INSPECTION_ISSUE_ORDER,
    InspectionMethod,
    SIGNAL_ORDER,
    SuggestedRole,
    UnitKind,
)


_UNIT_KINDS = frozenset({"pdf-page", "worksheet", "image"})
_METHODS = frozenset({
    "embedded-text", "local-ocr", "worksheet-structure", "image-structure", "none",
})
_SIGNALS = frozenset(SIGNAL_ORDER)
_ISSUES = frozenset(INSPECTION_ISSUE_ORDER)
_SIGNAL_POSITIONS = {code: index for index, code in enumerate(SIGNAL_ORDER)}
_ISSUE_POSITIONS = {code: index for index, code in enumerate(INSPECTION_ISSUE_ORDER)}
_ALLOWED_ROLES = {
    "pdf-page": frozenset({
        "payment-roster", "service-contract", "acceptance-record", "payment-tax-form",
        "identity-front", "identity-back", "shared-supporting-evidence",
        "other-supporting-evidence",
    }),
    "worksheet": frozenset({"payment-roster", "other-supporting-evidence"}),
    "image": frozenset({
        "identity-front", "identity-back", "shared-supporting-evidence",
        "other-supporting-evidence",
    }),
}
_OCR_FAILURE_ISSUES = frozenset({"ocr-failed", "ocr-timeout"})
_STRUCTURAL_SIGNALS = frozenset({
    "roster-column-pattern", "roster-row-pattern", "identity-front-layout",
    "identity-back-layout", "embedded-media-present", "worksheet-hidden",
    "mostly-image-page", "mostly-text-page",
})

_SERVICE_CONTRACT = re.compile(r"\bhop\s+dong\s+dich\s+vu\b")
_PARTIES = re.compile(r"\bben\s+a\b.*?\bben\s+b\b")
_SERVICE_SCOPE = re.compile(r"\bnoi\s+dung\s+(?:cong\s+viec|dich\s+vu)\b")
_SIGNATURE = re.compile(r"\b(?:dai\s+dien\s+ky|chu\s+ky)\b")
_ACCEPTANCE = re.compile(r"\bbien\s+ban\s+nghiem\s+thu\b")
_ACCEPTANCE_PERIOD = re.compile(r"\b(?:thoi\s+gian|ky)\s+nghiem\s+thu\b")
_PAYMENT_REQUEST = re.compile(r"\bde\s+nghi\s+thanh\s+toan\b")
_TAX_FORM = re.compile(r"\b(?:chung\s+tu|to\s+khai)\s+thue\b")
_ROSTER_HEADER_NAME = re.compile(
    r"^(?:ho\s+ten|ten\s+(?:ctv|nhan\s+vien|nguoi\s+nhan))$"
)
_ROSTER_HEADER_IDENTITY = re.compile(
    r"^(?:cccd|cmnd|so\s+(?:cccd|cmnd)|ma\s+(?:so\s+)?(?:ctv|nhan\s+vien))$"
)
_ROSTER_HEADER_PAYMENT = re.compile(
    r"^(?:so\s+tien|thanh\s+tien|tien\s+(?:chi\s+tra|thanh\s+toan)|gross|net)$"
)
_IDENTITY_FRONT_HEADING = re.compile(r"\b(?:can\s+cuoc\s+cong\s+dan|chung\s+minh\s+nhan\s+dan)\b")
_IDENTITY_FRONT_LAYOUT = re.compile(r"\bmat\s+truoc\b")
_IDENTITY_BACK_LAYOUT = re.compile(r"\bmat\s+sau\b")
_IDENTITY_NUMBER = re.compile(r"\b(?:\d[ .-]?){11}\d\b")
_IDENTITY_ISSUE = re.compile(r"\b(?:ngay\s+cap|noi\s+cap|co\s+quan\s+cap)\b")
_CASE_LEVEL = re.compile(r"\b(?:ho\s+so\s+vu\s+viec|ho\s+so\s+chung)\b")
_MULTI_PARTY = re.compile(r"\b(?:nhieu\s+nguoi\s+lien\s+quan|nhieu\s+ben)\b")
_SUPPORTING_DOCUMENT = re.compile(r"\b(?:tai\s+lieu\s+kem\s+theo|chung\s+tu\s+kem\s+theo)\b")


@dataclasses.dataclass(frozen=True)
class TextSignalContext:
    unit_kind: UnitKind
    mostly_image: bool
    embedded_media: bool
    worksheet_hidden: bool
    row_pattern: bool
    roster_column_pattern: bool = False

    def __post_init__(self) -> None:
        if type(self.unit_kind) is not str or self.unit_kind not in _UNIT_KINDS:
            raise ValueError("unit_kind must be supported")
        if not all(type(value) is bool for value in (
            self.mostly_image,
            self.embedded_media,
            self.worksheet_hidden,
            self.row_pattern,
            self.roster_column_pattern,
        )):
            raise ValueError("text signal context flags must be Boolean")


@dataclasses.dataclass(frozen=True)
class Classification:
    suggested_role: SuggestedRole
    confidence_band: ConfidenceBand
    needs_user_review: bool
    issue_codes: tuple[str, ...]
    signal_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            type(self.suggested_role) is not str
            or self.suggested_role not in _ALLOWED_ROLES["pdf-page"] | {"unknown"}
        ):
            raise ValueError("suggested_role must be supported")
        if (
            type(self.confidence_band) is not str
            or self.confidence_band not in {"high", "medium", "low", "none"}
        ):
            raise ValueError("confidence_band must be supported")
        if (
            (self.suggested_role == "unknown") != (self.confidence_band == "none")
            or type(self.needs_user_review) is not bool
        ):
            raise ValueError("classification fields must agree")
        issue_codes = _canonical_codes(
            self.issue_codes, _ISSUES, _ISSUE_POSITIONS, "issue_codes"
        )
        signal_codes = _canonical_codes(
            self.signal_codes, _SIGNALS, _SIGNAL_POSITIONS, "signal_codes"
        )
        expected_review = (
            self.confidence_band != "high"
            or self.suggested_role == "unknown"
            or bool(issue_codes)
            or "multiple-role-signals" in signal_codes
            or "worksheet-hidden" in signal_codes
        )
        if self.needs_user_review != expected_review:
            raise ValueError("needs_user_review must agree with the review contract")
        object.__setattr__(self, "issue_codes", issue_codes)
        object.__setattr__(self, "signal_codes", signal_codes)


def _canonical_codes(values, allowed, positions, field_name):
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{field_name} must use approved codes")
    try:
        copied = tuple(values)
    except Exception:
        raise ValueError(f"{field_name} must use approved codes") from None
    if any(type(value) is not str or value not in allowed for value in copied):
        raise ValueError(f"{field_name} must use approved codes")
    return tuple(sorted(set(copied), key=positions.__getitem__))


def _normalized_private_text(text):
    if type(text) is not str:
        raise ValueError("private text must be a string")
    normalized = unicodedata.normalize("NFD", text.casefold())
    normalized = normalized.replace("đ", "d")
    normalized = "".join(character for character in normalized if not unicodedata.combining(character))
    return re.sub(r"\s+", " ", normalized).strip()


def roster_header_categories_from_private_text(text: str) -> tuple[str, ...]:
    """Reduce one bounded cell to fixed header categories, never a roster signal."""
    normalized = _normalized_private_text(text)
    categories = []
    for category, pattern in (
        ("name", _ROSTER_HEADER_NAME),
        ("identity", _ROSTER_HEADER_IDENTITY),
        ("payment", _ROSTER_HEADER_PAYMENT),
    ):
        if pattern.fullmatch(normalized):
            categories.append(category)
    normalized = ""
    return tuple(categories)


def signals_from_private_text(text: str, context: TextSignalContext) -> tuple[str, ...]:
    """Reduce bounded private text immediately to ordered fixed signal codes."""
    if type(context) is not TextSignalContext:
        raise ValueError("text signal context must be valid")
    normalized = _normalized_private_text(text)
    signals = set()
    patterns = (
        ("service-contract-heading", _SERVICE_CONTRACT),
        ("party-section-present", _PARTIES),
        ("service-scope-section-present", _SERVICE_SCOPE),
        ("signature-section-present", _SIGNATURE),
        ("acceptance-heading", _ACCEPTANCE),
        ("acceptance-period-present", _ACCEPTANCE_PERIOD),
        ("payment-request-heading", _PAYMENT_REQUEST),
        ("tax-form-heading", _TAX_FORM),
        ("identity-front-heading", _IDENTITY_FRONT_HEADING),
        ("identity-front-layout", _IDENTITY_FRONT_LAYOUT),
        ("identity-back-layout", _IDENTITY_BACK_LAYOUT),
        ("identity-number-pattern-present", _IDENTITY_NUMBER),
        ("identity-issue-section-present", _IDENTITY_ISSUE),
        ("case-level-heading", _CASE_LEVEL),
        ("multi-party-reference-present", _MULTI_PARTY),
        ("supporting-document-heading", _SUPPORTING_DOCUMENT),
    )
    for code, pattern in patterns:
        if pattern.search(normalized):
            signals.add(code)
    if context.roster_column_pattern:
        signals.add("roster-column-pattern")
    if context.row_pattern:
        signals.add("roster-row-pattern")
    if context.embedded_media:
        signals.add("embedded-media-present")
    if context.worksheet_hidden:
        signals.add("worksheet-hidden")
    signals.add("mostly-image-page" if context.mostly_image else "mostly-text-page")
    heading_signals = {
        "service-contract-heading", "acceptance-heading", "payment-request-heading",
        "tax-form-heading", "identity-front-heading", "identity-back-layout",
        "case-level-heading", "supporting-document-heading",
    }
    if len(signals & heading_signals) > 1:
        signals.add("multiple-role-signals")
    ordered = tuple(code for code in SIGNAL_ORDER if code in signals)
    normalized = ""
    return ordered


def _candidate_bands(unit_kind, signals):
    candidates = {}
    allowed = _ALLOWED_ROLES[unit_kind]
    if unit_kind == "worksheet" and "payment-roster" in allowed:
        if {"roster-column-pattern", "roster-row-pattern"} <= signals:
            candidates["payment-roster"] = "high"
        elif "roster-column-pattern" in signals:
            candidates["payment-roster"] = "medium"
    if "service-contract" in allowed and "service-contract-heading" in signals:
        support = signals & {
            "party-section-present", "service-scope-section-present", "signature-section-present",
        }
        if "party-section-present" in support and (
            "service-scope-section-present" in support or "signature-section-present" in support
        ):
            candidates["service-contract"] = "high"
        elif len(support) == 1:
            candidates["service-contract"] = "medium"
        elif not support:
            candidates["service-contract"] = "low"
    if "acceptance-record" in allowed and "acceptance-heading" in signals:
        support = signals & {
            "acceptance-period-present", "party-section-present", "signature-section-present",
        }
        if len(support) >= 2:
            candidates["acceptance-record"] = "high"
        elif len(support) == 1:
            candidates["acceptance-record"] = "medium"
        else:
            candidates["acceptance-record"] = "low"
    if "payment-tax-form" in allowed and signals & {"payment-request-heading", "tax-form-heading"}:
        support = signals & {
            "party-section-present", "signature-section-present", "roster-column-pattern",
        }
        if len(support) >= 2:
            candidates["payment-tax-form"] = "high"
        elif len(support) == 1:
            candidates["payment-tax-form"] = "medium"
        else:
            candidates["payment-tax-form"] = "low"
    if "identity-front" in allowed:
        front = signals & {
            "identity-front-heading", "identity-front-layout", "identity-number-pattern-present",
        }
        if len(front) == 3:
            candidates["identity-front"] = "high"
        elif len(front) == 2:
            candidates["identity-front"] = "medium"
        elif front == {"identity-front-layout"}:
            candidates["identity-front"] = "low"
    if "identity-back" in allowed:
        back = signals & {"identity-back-layout", "identity-issue-section-present"}
        front = signals & {
            "identity-front-heading", "identity-front-layout", "identity-number-pattern-present",
        }
        if len(back) == 2:
            candidates["identity-back"] = "high"
        elif len(back) == 1 and not front:
            candidates["identity-back"] = "medium"
    if "shared-supporting-evidence" in allowed and {
        "case-level-heading", "multi-party-reference-present",
    } <= signals:
        candidates["shared-supporting-evidence"] = "medium"
    if "other-supporting-evidence" in allowed and "supporting-document-heading" in signals:
        if signals & {"mostly-text-page", "mostly-image-page", "embedded-media-present"}:
            candidates["other-supporting-evidence"] = "medium"
        else:
            candidates["other-supporting-evidence"] = "low"
    return candidates


def classify(
    unit_kind: UnitKind,
    inspection_method: InspectionMethod,
    signal_codes,
    acquisition_issue_codes,
) -> Classification:
    """Classify only fixed safe codes, with no precedence tie-breaking."""
    if type(unit_kind) is not str or unit_kind not in _UNIT_KINDS:
        raise ValueError("unit_kind must be supported")
    if type(inspection_method) is not str or inspection_method not in _METHODS:
        raise ValueError("inspection_method must be supported")
    signals = set(_canonical_codes(signal_codes, _SIGNALS, _SIGNAL_POSITIONS, "signal_codes"))
    issues = set(_canonical_codes(
        acquisition_issue_codes, _ISSUES, _ISSUE_POSITIONS, "acquisition_issue_codes"
    ))
    if inspection_method == "local-ocr" and issues & _OCR_FAILURE_ISSUES:
        signals.intersection_update(_STRUCTURAL_SIGNALS)
    candidates = _candidate_bands(unit_kind, signals)
    high = [role for role, band in candidates.items() if band == "high"]
    medium = [role for role, band in candidates.items() if band == "medium"]
    low = [role for role, band in candidates.items() if band == "low"]
    if len(high) >= 2 or (len(high) == 1 and medium):
        role, band = "unknown", "none"
        issues.add("classification-conflict")
        signals.add("multiple-role-signals")
    elif len(high) == 1:
        role, band = high[0], "high"
    elif len(medium) >= 2:
        role, band = "unknown", "none"
        issues.add("classification-conflict")
        signals.add("multiple-role-signals")
    elif len(medium) == 1:
        role, band = medium[0], "medium"
    elif len(low) >= 2:
        role, band = "unknown", "none"
        issues.add("classification-ambiguous")
        signals.add("multiple-role-signals")
    elif len(low) == 1:
        role, band = low[0], "low"
    else:
        role, band = "unknown", "none"
        issues.add("classification-ambiguous")
    ordered_issues = tuple(code for code in INSPECTION_ISSUE_ORDER if code in issues)
    ordered_signals = tuple(code for code in SIGNAL_ORDER if code in signals)
    needs_review = band != "high" or role == "unknown" or bool(ordered_issues)
    needs_review = needs_review or "multiple-role-signals" in ordered_signals
    needs_review = needs_review or "worksheet-hidden" in ordered_signals
    return Classification(role, band, needs_review, ordered_issues, ordered_signals)
