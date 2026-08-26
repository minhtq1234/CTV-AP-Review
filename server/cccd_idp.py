"""Read a CCCD card with GreenNode IDP, and decide whether it may auto-attach.

Why this exists: local Tesseract resolves 26 of 41 people on a real batch and
only 8 of those actually attach. IDP is a purpose-built Vietnamese ID reader --
it classifies the card, returns ~30 named fields with per-field confidence and
bounding boxes, and yields only the fields a given face actually carries, so a
card BACK produces no identity number rather than a guess.

Two things learned the hard way against the live API, both encoded below:

  * ``/v1/ocr/ingest`` is an async submit. It returns a ``request_id``; the SAME
    path with GET returns the extraction. The envelope's ``status`` goes
    terminal BEFORE ``ocr_data`` is populated, so polling must wait for content,
    not for status.

  * ``is_correct`` is NOT a read-quality signal. It is False even on a perfect
    front whose number and name both match the roster -- most likely because a
    real card never populates all 33 schema fields. Gating on it would attach
    nothing. ``is_correct_classification`` is reliable; ``is_correct`` is not.

The transport is injected so the decision logic is testable without a network
or a credential.
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

from ocr_extract import norm

# A CCCD is exactly 12 digits. A legacy CMND is 9 and is deliberately NOT
# accepted here: the roster keys on the 12-digit form, so a 9-digit read has
# nothing to match against and must go to a human.
_CCCD_DIGITS = 12

# Terminal states that mean "this job will never produce fields".
_DEAD_STATES = frozenset({"FAILED", "ERROR", "CANCELLED"})


class IdpError(Exception):
    """IDP could not be reached or refused the request."""


@dataclass(frozen=True)
class IdpRead:
    """One card as IDP saw it."""

    id_number: str
    name: str
    dob: str
    classification_ok: bool
    document_title: str
    #: field name -> (value, probability), everything IDP returned
    fields: dict[str, tuple[str, float | None]] = field(default_factory=dict)
    #: field name -> the raw item, which also carries `coordinates`
    raw: dict[str, dict] = field(default_factory=dict)

    @property
    def has_identity(self) -> bool:
        """Whether this face carries a usable identity number at all."""
        return len(self.id_number) == _CCCD_DIGITS


def digits(value: str | None) -> str:
    return "".join(c for c in (value or "") if c.isdigit())


def parse_result(payload: dict) -> IdpRead:
    """Turn an IDP result envelope into an :class:`IdpRead`."""
    document = ((payload.get("data") or {}).get("documents") or [{}])[0]
    values: dict[str, tuple[str, float | None]] = {}
    raw: dict[str, dict] = {}
    for group in document.get("ocr_data") or []:
        for item in group.get("value") or []:
            if isinstance(item, dict) and item.get("name"):
                values[item["name"]] = (
                    str(item.get("extracted_value") or "").strip(),
                    item.get("extracted_prob"),
                )
                raw[item["name"]] = item
    number = digits(values.get("id_number", ("", None))[0])
    return IdpRead(
        id_number=number if len(number) == _CCCD_DIGITS else "",
        name=values.get("name", ("", None))[0],
        dob=values.get("dob", ("", None))[0],
        classification_ok=bool(document.get("is_correct_classification")),
        document_title=str(document.get("document_type_title") or ""),
        fields=values,
        raw=raw,
    )


def read_card(
    image_bytes: bytes,
    filename: str,
    submit: Callable[[bytes, str], dict],
    fetch: Callable[[str], dict],
    *,
    settle: float = 3.0,
    pause: float = 2.0,
    attempts: int = 25,
    sleep: Callable[[float], None] = time.sleep,
) -> IdpRead:
    """Submit one card and poll until its fields appear.

    `submit` and `fetch` are injected so this is testable without a network.
    """
    submitted = submit(image_bytes, filename)
    request_id = str((submitted.get("data") or {}).get("request_id") or "")
    if not request_id:
        raise IdpError("submit returned no request_id")

    sleep(settle)
    payload: dict = {}
    for _ in range(attempts):
        payload = fetch(request_id)
        data = payload.get("data") or {}
        documents = data.get("documents") or []
        populated = any(
            (group.get("value") or [])
            for document in documents
            for group in (document.get("ocr_data") or [])
        )
        if populated:
            return parse_result(payload)
        if str(data.get("status") or "").upper() in _DEAD_STATES:
            break
        sleep(pause)
    # A blank or unreadable face legitimately yields nothing; that is a result,
    # not a failure, and parse_result renders it as an empty read.
    return parse_result(payload)


# --- deciding what to do with a read ----------------------------------------

@dataclass(frozen=True)
class IdpDecision:
    """What may be done with a card, and why."""

    action: str  # "attach" | "review"
    roster_index: int | None
    reason: str


def decide(read: IdpRead, roster_rows: list[dict]) -> IdpDecision:
    """Auto-attach only on two independent fields agreeing.

    The number must resolve to exactly one roster row AND the name printed on
    the card must match that row's name. One signal is not enough: a 12-digit
    string that happens to hit a roster row is exactly how a misread becomes a
    wrong payment. Everything short of both goes to the reviewer's picker,
    which is cheap -- a person recognises a card in seconds.
    """
    if not read.classification_ok:
        return IdpDecision("review", None, "not-recognised-as-id")
    if not read.has_identity:
        return IdpDecision("review", None, "no-identity-number")

    matches = [
        index
        for index, row in enumerate(roster_rows)
        if digits(row.get("cccd")) == read.id_number
    ]
    if not matches:
        return IdpDecision("review", None, "no-roster-match")
    if len(matches) > 1:
        return IdpDecision("review", None, "duplicate-roster-cccd")

    index = matches[0]
    if not read.name:
        return IdpDecision("review", index, "no-name-to-corroborate")
    if norm(read.name) != norm(roster_rows[index].get("name", "")):
        # Two fields off one document disagreeing is the most informative
        # signal available -- never resolve it automatically.
        return IdpDecision("review", index, "name-disagrees")
    return IdpDecision("attach", index, "number-and-name-agree")


# --- live transport ---------------------------------------------------------

def http_transport(base_url: str, api_key: str):
    """(submit, fetch) bound to a live IDP endpoint."""
    ingest = f"{base_url.rstrip('/')}/ocr/ingest"

    def submit(image_bytes: bytes, filename: str) -> dict:
        boundary = "----ctvapreview-boundary"
        parts = []
        for name, value in (
            ("model", "idp"),
            ("flow", "single"),
            ("doc_type", "ID"),
            ("file_type", "IMAGE"),
        ):
            parts.append(
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n".encode()
            )
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; '
            f'filename="{filename}"\r\nContent-Type: image/jpeg\r\n\r\n'.encode()
        )
        parts.append(image_bytes)
        parts.append(f"\r\n--{boundary}--\r\n".encode())
        request = urllib.request.Request(
            ingest, data=b"".join(parts), method="POST"
        )
        request.add_header("Authorization", f"Bearer {api_key}")
        request.add_header(
            "Content-Type", f"multipart/form-data; boundary={boundary}"
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8", "replace"))

    def fetch(request_id: str) -> dict:
        request = urllib.request.Request(
            f"{ingest}/{request_id}", method="GET"
        )
        request.add_header("Authorization", f"Bearer {api_key}")
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8", "replace"))

    return submit, fetch


# --- adapting an IDP read into the existing pipeline -------------------------
#
# The ingest already knows how to pair front/back, resolve a candidate to a
# unique roster row, detect competing claims and attach evidence atomically.
# None of that needs to change to use a better reader -- IDP just has to speak
# the same shape the local reader speaks, so it is expressed as a drop-in
# replacement for `cccd_ocr.analyze_drawing`.

from cccd_ocr import CccdImageOcr  # noqa: E402

#: fields that only ever appear on the reverse face of a card
_BACK_ONLY = frozenset({"doi", "poi", "features", "signer"})


def _bbox_from(coordinates) -> dict[str, int] | None:
    """IDP's 4-number box as the pipeline's {x, y, width, height}.

    Accepts either corner form (x1, y1, x2, y2) or origin-plus-size
    (x, y, w, h): if the last two values exceed the first two they are read as
    the opposite corner. Downstream this box is used for presence and for
    drawing a highlight, so the two readings degrade gracefully into each other.
    """
    if not isinstance(coordinates, (list, tuple)) or len(coordinates) != 4:
        return None
    try:
        a, b, c, d = (float(value) for value in coordinates)
    except (TypeError, ValueError):
        return None
    width, height = (c - a, d - b) if c > a and d > b else (c, d)
    if width <= 0 or height <= 0:
        return None
    return {
        "x": int(a),
        "y": int(b),
        "width": int(width),
        "height": int(height),
    }


def as_image_ocr(read: IdpRead) -> CccdImageOcr:
    """An IdpRead in the shape the rest of the ingest expects.

    Side is derived from the fields actually present rather than from keyword
    matching on blurry printed labels -- a face carrying an identity number is a
    front, and one carrying only issue/authority/features/signer is a back.
    That is why IDP never invents a number on a reverse face.
    """
    number, number_prob = read.fields.get("id_number", ("", None))
    name, name_prob = read.fields.get("name", ("", None))
    if read.has_identity:
        side, side_confidence = "front", 1.0
    elif _BACK_ONLY & set(read.fields):
        side, side_confidence = "back", 1.0
    else:
        side, side_confidence = "unknown", 0.0

    item = read.raw.get("id_number")
    bbox = _bbox_from(item.get("coordinates")) if isinstance(item, dict) else None
    return CccdImageOcr(
        side=side,
        side_confidence=side_confidence,
        cccd=read.id_number,
        cccd_confidence=float(number_prob or 0.0) if read.has_identity else 0.0,
        name=name,
        name_confidence=float(name_prob or 0.0),
        number_bbox=bbox,
    )


def reader(base_url: str, api_key: str, **kwargs):
    """A callable with `analyze_drawing`'s signature, backed by IDP."""
    submit, fetch = http_transport(base_url, api_key)

    def analyze(drawing, evidence_budget=None):  # noqa: ARG001
        with open(drawing.stored_path, "rb") as handle:
            image_bytes = handle.read()
        read = read_card(
            image_bytes,
            f"{drawing.id}.{drawing.extension}",
            submit,
            fetch,
            **kwargs,
        )
        return as_image_ocr(read)

    return analyze
