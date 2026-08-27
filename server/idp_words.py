"""Read a document page with GreenNode IDP, as words the existing pipeline understands.

WHY THIS SHAPE. The packet fields are already found by anchor + pattern logic over
Tesseract words (`ocr_extract.locate_field`), and that logic is well tested and
carries all the hard-won Vietnamese-contract knowledge -- the section-heading
anchor collision, the row reassembly, the located-but-unread hit. So IDP is used
here as a BETTER OCR ENGINE at the `words_by_page` seam, not as a contract
understander: it returns text with boxes, the existing logic does the rest. That
reuses everything instead of duplicating it, and it means one escalated page
serves all six fields on it rather than one call per field.

WHAT IS KNOWN vs WHAT IS NOT.

Known, and shared with `cccd_idp` (learned against the live API, see that
module's header): the endpoint is `POST {base}/ocr/ingest` as an async submit
returning `data.request_id`; GET on the same path plus the id returns the
extraction; the envelope's `status` goes terminal BEFORE `ocr_data` fills, so
polling must wait for CONTENT. The result envelope is
`data.documents[].ocr_data[].value[]`, whose items carry `extracted_value`,
`extracted_prob` and `coordinates`.

GREENNODE_IDP_URL is TENANT-NAMESPACED, and getting this wrong wastes a probe
run. IDP does not sit at the root of the MaaS host: it lives under

    https://<maas-host>/maas/<user-id>/greennode/idp/v1

so `<maas-host>/v1/ocr/ingest` is a 404 while `<maas-host>/v1/chat/completions`
answers 401 -- the same host serves the LLM endpoint at the root and IDP only
under that per-user prefix. If every doc_type 404s, the URL is wrong, not the
doc_type; `idp_probe.py` now detects and says exactly that.

NOT known, and NOT verifiable from here: which `doc_type` selects a general
document read rather than the ID model, and whether that mode's items are text
runs or named fields. `doc_type=ID` is the only value this codebase has ever
sent. `IDP_DOC_TYPE` therefore defaults to a general guess and is overridable
by environment, and `parse_words` is deliberately small and forgiving so that
correcting it is a few lines rather than a redesign. Run `idp_probe.py` against
the live endpoint to settle both; until then this module is wired but unproven,
and stays off by default.

Everything except the transport is pure and tested with an injected fake, so the
polling, the escalation and the word adaptation are all verified without a
network or a credential.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Callable

from cccd_idp import IdpError, _bbox_from

#: Which IDP document type asks for a general page read. UNVERIFIED -- the only
#: value known to work against the live API is "ID", which selects the CCCD
#: model and is wrong for a contract page. Override with IDP_DOC_TYPE.
DEFAULT_DOC_TYPE = os.environ.get("IDP_DOC_TYPE", "GENERAL").strip() or "GENERAL"

#: Terminal states that mean this job will never produce content.
_DEAD_STATES = frozenset({"FAILED", "ERROR", "CANCELLED"})


def parse_words(payload: dict) -> list[dict]:
    """Every readable item in an IDP envelope, as pipeline word dicts.

    A word is `{text, x, y, w, h, conf}` -- the same shape `ocr_extract.ocr_words`
    produces, in the same OCR-pixel space -- so the output drops straight into
    `group_lines`/`locate_field`.

    Items without a usable box are skipped rather than guessed at: a word with
    no position cannot be highlighted for the reviewer, and "locate & look" is
    the whole point of the pipeline. `conf` is scaled to 0-100 to match
    Tesseract's range, since `_search_line` divides by 100.

    Forgiving on purpose -- this is the one function whose input shape is
    unverified (see the module header), so it accepts either `extracted_value`
    or `text` for the value and either `extracted_prob` or `confidence` for the
    score, and tolerates items that carry neither.
    """
    words: list[dict] = []
    for document in (payload.get("data") or {}).get("documents") or []:
        for group in document.get("ocr_data") or []:
            for item in group.get("value") or []:
                if not isinstance(item, dict):
                    continue
                text = str(
                    item.get("extracted_value")
                    if item.get("extracted_value") is not None
                    else item.get("text") or ""
                ).strip()
                if not text:
                    continue
                bbox = _bbox_from(item.get("coordinates"))
                if bbox is None:
                    continue
                prob = item.get("extracted_prob")
                if prob is None:
                    prob = item.get("confidence")
                words.append({
                    "text": text,
                    "x": bbox["x"],
                    "y": bbox["y"],
                    "w": bbox["width"],
                    "h": bbox["height"],
                    # A reader that reports no probability is treated as
                    # confident rather than as garbage: an absent score is
                    # unknown, and scoring it 0 would send every escalated
                    # field straight back into "low-confidence".
                    "conf": 100.0 if prob is None else float(prob) * 100.0,
                })
    return words


def read_page(
    image_bytes: bytes,
    filename: str,
    submit: Callable[[bytes, str], dict],
    fetch: Callable[[str], dict],
    *,
    settle: float = 3.0,
    pause: float = 2.0,
    attempts: int = 25,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict]:
    """Submit one page image and poll until its content appears.

    `submit`/`fetch` are injected, so the polling contract is testable without a
    network. Polls for CONTENT, not for status -- see the module header.
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
        populated = any(
            (group.get("value") or [])
            for document in (data.get("documents") or [])
            for group in (document.get("ocr_data") or [])
        )
        if populated:
            return parse_words(payload)
        if str(data.get("status") or "").upper() in _DEAD_STATES:
            break
        sleep(pause)
    # A page IDP cannot read is a result, not a failure: the caller keeps its
    # local words and the field stays "cần xem", which is the honest outcome.
    return parse_words(payload)


def http_transport(base_url: str, api_key: str, doc_type: str = ""):
    """(submit, fetch) bound to a live IDP endpoint, for a page image.

    Mirrors `cccd_idp.http_transport` -- same endpoint, auth and multipart
    layout -- differing only in `doc_type`, which is the part that selects a
    general page read instead of the ID model.
    """
    ingest = f"{base_url.rstrip('/')}/ocr/ingest"
    doc_type = doc_type or DEFAULT_DOC_TYPE

    def submit(image_bytes: bytes, filename: str) -> dict:
        boundary = "----ctvapreview-boundary"
        parts = []
        for name, value in (
            ("model", "idp"),
            ("flow", "single"),
            ("doc_type", doc_type),
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
            f'filename="{filename}"\r\nContent-Type: image/png\r\n\r\n'.encode()
        )
        parts.append(image_bytes)
        parts.append(f"\r\n--{boundary}--\r\n".encode())
        request = urllib.request.Request(ingest, data=b"".join(parts), method="POST")
        request.add_header("Authorization", f"Bearer {api_key}")
        request.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8", "replace"))

    def fetch(request_id: str) -> dict:
        request = urllib.request.Request(f"{ingest}/{request_id}", method="GET")
        request.add_header("Authorization", f"Bearer {api_key}")
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8", "replace"))

    return submit, fetch


def reader(base_url: str, api_key: str, doc_type: str = "", **kwargs):
    """A `(image_bytes, filename) -> words` callable bound to the live endpoint.

    Shaped as a callable rather than a class so `ocr_packet` can take it as an
    optional argument and stay testable with a fake.
    """
    submit, fetch = http_transport(base_url, api_key, doc_type)

    def read(image_bytes: bytes, filename: str) -> list[dict]:
        return read_page(image_bytes, filename, submit, fetch, **kwargs)

    return read


def page_reader_from_env():
    """The escalation reader, or None when IDP is not configured.

    Same two variables the CCCD reader uses (`pipeline._card_reader`), plus
    `IDP_DOC_TYPE`, so enabling document-field IDP is a deployment choice and
    the default stays local-only -- no packet page leaves the workstation
    unless someone sets these.
    """
    base_url = os.environ.get("GREENNODE_IDP_URL", "").strip()
    api_key = os.environ.get("GREENNODE_API_KEY", "").strip()
    if not base_url or not api_key:
        return None
    return reader(
        base_url.rstrip("/").removesuffix("/ocr/ingest"),
        api_key,
        os.environ.get("IDP_DOC_TYPE", "").strip(),
    )
