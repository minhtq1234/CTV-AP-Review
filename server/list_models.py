#!/usr/bin/env python3
"""List the models the MaaS LLM endpoint offers, and flag vision candidates.

A script rather than a curl one-liner because the one-liners were long enough
that pasting them into a terminal truncated them, and a broken Authorization
header returns an error body that then fails with a confusing KeyError instead
of saying "auth failed".

    export GREENNODE_API_KEY=...        # already exported if you ran the probe
    python3 list_models.py

Reads the key from the environment only -- never pass it as an argument, or it
lands in your shell history.

Why this matters: if GreenNode IDP turns out to be provisioned for ID cards
only, a vision model on this same host is the alternative route for the
handwritten fees (see docs/ver2-scope.md §2.1). `model_type` does not say
whether a model takes images, so names are only a hint -- the real test is
sending one an image.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_BASE = "https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1"

#: Families whose names commonly indicate image input. A hint for what to TEST,
#: never a claim that the model is multimodal. Keep frontier families in here --
#: an earlier version listed only the obvious "-vl"/"vision" suffixes and so
#: missed `openai/gpt-5`, which is exactly the model worth trying.
VISION_HINTS = ("vl", "vision", "multimodal", "omni", "image",
                "gpt-5", "gpt-4", "gemini", "claude", "gemma", "pixtral",
                "llava", "internvl", "qwen2-vl", "qwen2.5-vl", "glm-4v", "glm-5")

#: `model_type` is the reliable signal for the OCR service; names are not.
OCR_TYPES = ("ocr",)


def main() -> int:
    api_key = os.environ.get("GREENNODE_API_KEY", "").strip()
    if not api_key:
        print("set GREENNODE_API_KEY first (export it; do not pass it as an "
              "argument)", file=sys.stderr)
        return 2
    base = os.environ.get("GREENNODE_API_URL", "").strip() or DEFAULT_BASE
    url = base.rstrip("/") + "/models"

    request = urllib.request.Request(url, method="GET")
    request.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", "replace")[:400]
        except Exception:
            pass
        print(f"HTTP {exc.code} from {url}\n{body}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    models = payload.get("data")
    if not isinstance(models, list):
        print("unexpected response shape:\n"
              + json.dumps(payload, ensure_ascii=False, indent=2)[:800],
              file=sys.stderr)
        return 1

    chat = [m for m in models if m.get("model_type") == "messages"]
    other = [m for m in models if m.get("model_type") != "messages"]
    print(f"{len(models)} models — {len(chat)} chat, {len(other)} other\n")
    for m in sorted(models, key=lambda x: str(x.get("id"))):
        mid = str(m.get("id") or "")
        hint = "  <- possible vision, worth testing" if any(
            h in mid.lower() for h in VISION_HINTS) else ""
        print(f"  {mid:<44} {str(m.get('model_type') or ''):<10}"
              f"{str(m.get('status') or '')}{hint}")

    ocr_models = [str(m.get("id")) for m in models
                  if str(m.get("model_type") or "").lower() in OCR_TYPES]
    if ocr_models:
        print()
        print("OCR service provisioned on this account:")
        for mid in ocr_models:
            print(f"  {mid}   <- this is IDP; use it as the `model` form field")
        print("  So a 500 from /ocr/ingest is about the doc_type VALUE, not")
        print("  about whether IDP is available.")

    flagged = [str(m.get("id")) for m in chat
               if any(h in str(m.get("id")).lower() for h in VISION_HINTS)]
    print()
    if flagged:
        print("Candidates to test with an image:")
        for mid in flagged:
            print(f"  {mid}")
        print("\nNames only hint at it. Confirm by sending one an image — a model "
              "that cannot\ntake images returns an error on an image content part.")
    else:
        print("No model name suggests image input. If none of these accept an "
              "image, the\nvision route is closed and §2.1 needs GreenNode to "
              "provision a document\nOCR model instead.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
