"""Assemble the *typed content region* of one document for the AI recap — the ONLY
text ever sent to GreenNode (VNG's own cloud). No images, no packet-wide PII: just
the typed content located on that one document. Pure + unit-tested."""
from __future__ import annotations

# Docs whose typed body carries reviewable content (mirrors src/logic/recap.ts).
CONTENT_BEARING_KINDS = ("contract", "bbnt", "appendix", "commitment")

# Shown at the foot of every recap. Keep in sync with src/logic/recap.ts's RECAP_DISCLAIMER.
DISCLAIMER = (
    "Bản xem thử. AI hỗ trợ đọc nhanh hồ sơ dài/phức tạp — "
    "quyết định cuối cùng do bạn."
)


def content_region_for(manifest: dict, doc_id: str) -> str | None:
    """The typed content of one document as a plain-text block, or None when the
    doc is absent or not content-bearing.

    Today that's the doc's title plus the typed field values OCR located ON that
    doc (nothing from any other doc). TODO(greennode): when the Phụ lục / BBNT body
    text is persisted per-doc during OCR, include it here — this stays the sole
    payload sent to GreenNode."""
    doc = next((d for d in manifest.get("docs", []) if d.get("id") == doc_id), None)
    if doc is None or doc.get("kind") not in CONTENT_BEARING_KINDS:
        return None
    lines: list[str] = []
    title = (doc.get("label") or doc.get("kind") or "").strip()
    if title:
        lines.append(title)
    for field in manifest.get("fields", []):
        for src in field.get("sources", []):
            if src.get("docId") == doc_id and (src.get("value") or "").strip():
                label = (field.get("label") or "").strip()
                lines.append(f"{label}: {src['value'].strip()}")
                break
    text = "\n".join(line for line in lines if line).strip()
    return text or None
