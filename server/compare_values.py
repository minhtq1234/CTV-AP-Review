"""The comparators the `compare` criteria run on, and Acc's format rules.

Mirrors `src/logic/verdict.ts`, which the frontend has used since the prototype
and which was extended on 2026-08-25 with the `person` rule. The rules are
stated once here in the language the engine runs in; the tests pin the same
cases both sides pin, so a divergence shows up as a failure rather than as
quietly different answers on two screens.

One deliberate departure from `verdict.ts`: identity numbers compare as digit
*strings*, not as integers. `verdict.ts` normalises its `number` kind through
`parseInt`, which is right for a quantity and wrong for a bank account -- it
would pass `81001142415` against `0081001142415`. Money keeps the integer rule
under its own kind.
"""
from __future__ import annotations

import re
from enum import Enum

from criteria import Status
from ocr_extract import norm

#: Below this, a matching read still needs a human -- the value agreed but the
#: reader was not sure it read it right.
LOW_CONF = 0.7

#: Edit-ratio at or above which a non-exact name is a near miss rather than a
#: different name.
NAME_SIM = 0.8


class Verdict(str, Enum):
    MATCH = "match"
    FUZZY = "fuzzy"          # near miss -- a person must look
    LOW_CONF = "low_conf"    # agreed, but the read was unsure
    MISMATCH = "mismatch"


_TO_STATUS = {
    Verdict.MATCH: Status.OK,
    Verdict.MISMATCH: Status.NO,
    # Both mean the same thing to a reviewer: look at it. The distinction
    # between them lives in the cell's note, not in its glyph.
    Verdict.FUZZY: Status.REVIEW,
    Verdict.LOW_CONF: Status.REVIEW,
}


def to_status(verdict: Verdict) -> Status:
    return _TO_STATUS[verdict]


# --- normalisation -----------------------------------------------------------

_COMPANY_WORDS = re.compile(
    r"\b(cong ty|cty|tnhh|cp|co|ltd|jsc|corporation|corp|tap doan)\b")


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _person(value: str) -> str:
    """Accent-folded, punctuation-free. No suffix stripping, no containment."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", norm(value or ""))).strip()


def _organisation(value: str) -> str:
    folded = _COMPANY_WORDS.sub(" ", norm(value or ""))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", folded)).strip()


_DMY = re.compile(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$")
_YMD = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$")


def _date(value: str) -> str:
    """`d-m-yyyy`, or the trimmed literal when it is not a date at all."""
    text = (value or "").strip()
    match = _YMD.match(text)
    if match:
        return f"{int(match[3])}-{int(match[2])}-{int(match[1])}"
    match = _DMY.match(text)
    if match:
        return f"{int(match[1])}-{int(match[2])}-{int(match[3])}"
    return text


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                               previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def _edit_ratio(a: str, b: str) -> float:
    longer = max(len(a), len(b))
    return 1.0 if longer == 0 else 1 - _levenshtein(a, b) / longer


def _contained_ratio(a: str, b: str) -> float:
    """Edit ratio, floored at 0.9 when one token set contains the other.

    Organisations only: `VNG` inside `Cong ty Co phan Tap doan VNG` is the same
    company written short. A person's name is never treated this way.
    """
    at, bt = a.split(" "), b.split(" ")
    contained = all(t in bt for t in at) or all(t in at for t in bt)
    ratio = _edit_ratio(a, b)
    return max(ratio, 0.9) if contained else ratio


# --- comparison --------------------------------------------------------------

def compare(
    expected: str,
    value: str,
    kind: str,
    confidence: float | None = None,
    allowed: tuple[str, ...] = (),
) -> Verdict:
    """How `value` stands against `expected` under the rule for `kind`.

    `confidence` downgrades an outright match to `low_conf`; it never softens a
    mismatch, because that would hide a disagreement behind "unsure", and it
    never touches `fuzzy`, which already says a person must look.
    """
    base = _base(expected, value, kind, allowed)
    if base is not Verdict.MATCH:
        return base
    if confidence is not None and confidence < LOW_CONF:
        return Verdict.LOW_CONF
    return base


def _base(expected: str, value: str, kind: str, allowed: tuple[str, ...]) -> Verdict:
    if kind == "digits":
        a, b = _digits(expected), _digits(value)
        # digit strings, not integers: a bank account's leading zero is data
        return Verdict.MATCH if a and b and a == b else Verdict.MISMATCH

    if kind == "money":
        a, b = _digits(expected), _digits(value)
        if not a or not b:
            return Verdict.MISMATCH
        return Verdict.MATCH if int(a) == int(b) else Verdict.MISMATCH

    if kind == "date":
        if not (expected or "").strip() or not (value or "").strip():
            return Verdict.MISMATCH
        return Verdict.MATCH if _date(expected) == _date(value) else Verdict.MISMATCH

    if kind == "enum":
        return _enum(expected, value, allowed)

    if kind == "person":
        return _person_verdict(expected, value)

    if kind in ("organisation", "name"):
        return _organisation_verdict(expected, value)

    if kind == "text":
        a, b = (expected or "").strip(), (value or "").strip()
        return Verdict.MATCH if a and a == b else Verdict.MISMATCH

    raise KeyError(f"no comparator for kind {kind!r}")


def _enum(expected: str, value: str, allowed: tuple[str, ...]) -> Verdict:
    """#04's rule is that the value *is* Nam or Nữ, not merely that the
    documents agree with each other."""
    folded = {norm(option) for option in allowed}
    a, b = norm(expected or ""), norm(value or "")
    if not a or not b or a not in folded or b not in folded:
        return Verdict.MISMATCH
    if a != b:
        return Verdict.MISMATCH
    return Verdict.MATCH if (expected or "").strip() == (value or "").strip() \
        else Verdict.FUZZY


def _person_verdict(expected: str, value: str) -> Verdict:
    if (expected or "").strip() and (expected or "").strip() == (value or "").strip():
        return Verdict.MATCH
    a, b = _person(expected), _person(value)
    if not a or not b:
        return Verdict.MISMATCH
    if a == b:
        # Same letters, different tone marks or case. Never a pass: Anh and Ánh,
        # Hùng and Hưng are different people.
        return Verdict.FUZZY
    if len(a.split(" ")) != len(b.split(" ")):
        # A person's name is not a prefix of another person's.
        return Verdict.MISMATCH
    return Verdict.FUZZY if _edit_ratio(a, b) >= NAME_SIM else Verdict.MISMATCH


def _organisation_verdict(expected: str, value: str) -> Verdict:
    if (expected or "").strip() and (expected or "").strip() == (value or "").strip():
        return Verdict.MATCH
    a, b = _organisation(expected), _organisation(value)
    if not a or not b:
        return Verdict.MISMATCH
    return Verdict.FUZZY if _contained_ratio(a, b) >= NAME_SIM else Verdict.MISMATCH


# --- Acc's format rules ------------------------------------------------------

def _digit_count(value: str, count: int) -> bool:
    return len(_digits(value)) == count


#: `params.formats` names, from the criteria registry.
FORMATS = {
    "cccd12": lambda v: _digit_count(v, 12),
    "mst10": lambda v: _digit_count(v, 10),
    "mst12": lambda v: _digit_count(v, 12),
    # A passport number is alphanumeric, so it is measured on the raw string
    # rather than on its digits.
    "passport8": lambda v: len((v or "").strip()) == 8
    and (v or "").strip().isalnum(),
    # Acc asks for text `dd/mm/yyyy` specifically, so that Excel cannot reformat
    # it -- an ISO date is a finding here, not an equivalent.
    "dd/mm/yyyy": lambda v: bool(_DMY.match((v or "").strip())),
}


def matches_format(value: str, formats: tuple[str, ...]) -> bool:
    """Whether `value` satisfies any one of `formats`. No rule accepts anything.

    Raises KeyError on an unknown format name rather than passing it: a typo in
    the registry must not silently disable a check.
    """
    if not formats:
        return True
    return any(FORMATS[name](value) for name in formats)
