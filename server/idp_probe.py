#!/usr/bin/env python3
"""Find out which IDP doc_type gives a general page read, and what it returns.

RUN THIS YOURSELF. It needs a live credential, which is why it is a script you
run rather than something the pipeline does: nothing in this repo should be
holding your API key, and the value it prints is the one fact
`idp_words.parse_words` is currently guessing at.

    export GREENNODE_IDP_URL=...   # TENANT-NAMESPACED, ends in /v1:
                                   #   https://<maas-host>/maas/<user-id>/greennode/idp/v1
                                   # NOT <maas-host>/v1 -- that is the LLM endpoint
    export GREENNODE_API_KEY=...
    python3 idp_probe.py PAGE.png                 # try the default candidates
    python3 idp_probe.py PAGE.png GENERAL DOC OCR # or your own list

Pick a page whose content you already know -- a contract fee page is ideal,
since `2.1. Phí dịch vụ: N đồng.` is easy to spot in the output.

What to look for in the report:

  * a doc_type that returns items at all (many will simply error or come back
    empty -- that is a useful answer too);
  * whether those items are TEXT RUNS (many items, each a word or line) or
    NAMED FIELDS (a few items with schema-ish names). `parse_words` assumes text
    runs; named fields would need a small mapper instead;
  * whether `coordinates` is present. Without boxes the read is unusable for
    "locate & look" no matter how good the text is.

The output prints item names, a short value preview and the coordinates, so it
is safe to paste back for the shape -- but it is a REAL PAGE, so redact values
before sharing if the page carries personal data.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

CANDIDATES = ["GENERAL", "DOCUMENT", "DOC", "OCR", "TEXT", "FULL_TEXT", "OTHER", "ID"]


def probe(base_url: str, api_key: str, image: bytes, filename: str, doc_type: str):
    from idp_words import http_transport, parse_words

    submit, fetch = http_transport(base_url, api_key, doc_type)
    submitted = submit(image, filename)
    request_id = str((submitted.get("data") or {}).get("request_id") or "")
    if not request_id:
        return {"doc_type": doc_type, "error": "no request_id",
                "submit_reply": submitted}
    time.sleep(3.0)
    payload: dict = {}
    for _ in range(25):
        payload = fetch(request_id)
        data = payload.get("data") or {}
        docs = data.get("documents") or []
        if any((g.get("value") or []) for d in docs for g in (d.get("ocr_data") or [])):
            break
        if str(data.get("status") or "").upper() in {"FAILED", "ERROR", "CANCELLED"}:
            break
        time.sleep(2.0)

    docs = (payload.get("data") or {}).get("documents") or []
    items = [i for d in docs for g in (d.get("ocr_data") or [])
             for i in (g.get("value") or []) if isinstance(i, dict)]
    return {
        "doc_type": doc_type,
        "status": (payload.get("data") or {}).get("status"),
        "documents": len(docs),
        "items": len(items),
        "with_coordinates": sum(1 for i in items if i.get("coordinates")),
        "words_parsed": len(parse_words(payload)),
        "sample": [
            {"name": i.get("name"),
             "value": str(i.get("extracted_value") or i.get("text") or "")[:40],
             "prob": i.get("extracted_prob") if i.get("extracted_prob") is not None
                     else i.get("confidence"),
             "coordinates": i.get("coordinates")}
            for i in items[:6]
        ],
        "item_keys": sorted({k for i in items[:20] for k in i}),
    }


def main(argv: list[str]) -> int:
    base_url = os.environ.get("GREENNODE_IDP_URL", "").strip()
    api_key = os.environ.get("GREENNODE_API_KEY", "").strip()
    if not base_url or not api_key:
        print("set GREENNODE_IDP_URL and GREENNODE_API_KEY first", file=sys.stderr)
        return 2
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2

    path = argv[1]
    doc_types = argv[2:] or CANDIDATES
    with open(path, "rb") as handle:
        image = handle.read()
    base_url = base_url.rstrip("/").removesuffix("/ocr/ingest")

    print(f"probing {len(doc_types)} doc_type(s) with {os.path.basename(path)} "
          f"({len(image)} bytes)\n")
    results = []
    for doc_type in doc_types:
        try:
            result = probe(base_url, api_key, image, os.path.basename(path), doc_type)
        except Exception as exc:                      # a refused doc_type is data
            result = {"doc_type": doc_type, "error": f"{type(exc).__name__}: {exc}"}
        results.append(result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print()

    print("=" * 60)
    usable = [r for r in results if r.get("words_parsed")]
    if not usable:
        # Every doc_type failing the same way is a URL problem, not a doc_type
        # problem -- "ID" is known to work against the real IDP service, so if
        # that 404s too then this host simply has no /ocr/ingest. Distinguish
        # the two before blaming the doc_type, since the message is otherwise
        # actively misleading (it was, once).
        all_404 = results and all("404" in str(r.get("error") or "") for r in results)
        if all_404:
            print("Every doc_type returned 404 -- including ID, which is known to work")
            print("against the real IDP service. That means the URL is wrong, not the")
            print("doc_type. Checking what this host actually serves:\n")
            for probe_path in ("/ocr/ingest", "/chat/completions", "/models"):
                try:
                    with urllib.request.urlopen(base_url + probe_path, timeout=20) as r:
                        code = r.status
                except urllib.error.HTTPError as exc:
                    code = exc.code
                except Exception as exc:
                    code = f"{type(exc).__name__}"
                note = {401: "exists, needs auth", 403: "exists, needs auth",
                        404: "NOT on this host"}.get(code, "")
                print(f"    GET {probe_path:<20} -> {code}  {note}")
            print("\nIf /chat/completions answers 401 but /ocr/ingest is 404, this is the")
            print("MaaS LLM endpoint (GREENNODE_API_URL), not the IDP document reader.")
            print("GREENNODE_IDP_URL needs the IDP service's own base URL, ending in /v1.")
            return 1
        print("No doc_type returned parseable words with coordinates.")
        print("Ask GreenNode which doc_type exposes general OCR, or whether the")
        print("account is provisioned only for the ID model.")
        return 1
    best = max(usable, key=lambda r: r["words_parsed"])
    print(f"USE THIS:  export IDP_DOC_TYPE={best['doc_type']}")
    print(f"           {best['words_parsed']} words parsed, "
          f"{best['with_coordinates']}/{best['items']} items had coordinates")
    print("If the sample above shows NAMED FIELDS rather than text runs, say so —")
    print("parse_words assumes text runs and would need a mapper instead.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
