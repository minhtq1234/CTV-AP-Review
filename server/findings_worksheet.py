#!/usr/bin/env python3
"""Build a worksheet of every claim the tool makes about a few packets, so a
person can check it by eye against the scan.

Why: the engine, the 25 criteria and the override loop have never been confirmed
CORRECT, only self-consistent. Everything found wrong so far -- `phi` unread
across a whole batch, a lookahead succeeding by luck, 139 discarded reads --
was found by measuring, not by the tool reporting it. This turns that into an
hour of human checking.

The point of the format: each claim is shown beside the ACTUAL PIXELS the tool
read, cropped from the page at the bbox it recorded. So a reviewer is not asked
to hunt the page -- they see what the machine looked at, what it read from it,
and what the bảng kê says, and mark whether those three agree.

    python3 findings_worksheet.py <case-id> [packet ...]

Writes a self-contained HTML file (images inlined) under
`server/data/worksheets/`, which is gitignored -- this contains REAL packet
data: names, CCCD numbers, bank accounts and scan crops. Do not commit it, do
not publish it, do not paste it anywhere outside the workstation.
"""

from __future__ import annotations

import base64
import html
import io
import json
import os
import sys
import urllib.request

API = os.environ.get("AP_API", "http://127.0.0.1:8002")

#: padding around a recorded bbox, in page pixels, so a crop shows its context
#: rather than a value floating with no label beside it
PAD_X, PAD_Y = 260, 26

STATUS_LABEL = {
    "ok": "đạt", "no": "không khớp", "rv": "cần người kiểm tra",
    "missing": "thiếu chứng từ", "pending": "chưa kiểm tra được",
    "na": "không áp dụng",
}


def get(path: str) -> dict:
    with urllib.request.urlopen(f"{API}{path}") as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def page_sources(manifest: dict, case_id: str, packet: int) -> dict[tuple[str, int], str]:
    """(documentId, page-within-doc) -> the rendered PNG path on disk.

    The manifest's own `src` is an ABSOLUTE path recorded at ingest time, so it
    points wherever the ingest happened to run -- for the re-ingested July case
    that is a /tmp directory that no longer exists. Only the basename (`pgN.png`)
    is durable, so the real path is rebuilt from the case directory.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    packet_dir = os.path.join(here, "data", "cases", case_id, "packets", str(packet))
    out = {}
    for doc in manifest.get("docs") or []:
        for j, page in enumerate(doc.get("pages") or []):
            name = os.path.basename(page.get("src") or "")
            if not name:
                continue
            rebuilt = os.path.join(packet_dir, name)
            out[(doc["id"], j)] = (
                rebuilt if os.path.exists(rebuilt) else (page.get("src") or "")
            )
    return out


def crop_data_uri(png_path: str, bbox: dict) -> tuple[str, str]:
    """A padded crop around `bbox` as a data URI, plus a note on what was done.

    bbox is in the page PNG's own pixel space (the words were scaled to display
    dpi before extraction), so it crops directly with no conversion.
    """
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return "", "Pillow unavailable"
    if not os.path.exists(png_path):
        return "", "page image missing"
    try:
        image = Image.open(png_path).convert("RGB")
    except Exception as exc:
        return "", f"unreadable page image ({exc})"

    x, y = int(bbox.get("x", 0)), int(bbox.get("y", 0))
    w, h = int(bbox.get("width", 0)), int(bbox.get("height", 0))
    left, top = max(0, x - PAD_X), max(0, y - PAD_Y)
    right, bottom = min(image.width, x + w + PAD_X), min(image.height, y + h + PAD_Y)
    if right <= left or bottom <= top:
        return "", "degenerate bbox"

    crop = image.crop((left, top, right, bottom))
    # Outline exactly what the tool claims it read, so the reviewer can see
    # whether the box is even on the right thing.
    draw = ImageDraw.Draw(crop)
    draw.rectangle([x - left, y - top, x - left + w, y - top + h],
                   outline=(200, 40, 40), width=3)
    buffer = io.BytesIO()
    crop.save(buffer, format="PNG", optimize=True)
    return ("data:image/png;base64,"
            + base64.b64encode(buffer.getvalue()).decode("ascii")), ""


def claims_for(packet: int, criteria: dict, srcs: dict) -> list[dict]:
    """Every OCR-sourced claim in a packet, flattened for the worksheet.

    Roster-provenance evidence is excluded: it is the reference being compared
    against, not something read off a scan, so there is nothing to eyeball.
    """
    claims = []
    for row in criteria.get("criteria") or []:
        for cell in row.get("cells") or []:
            for ev in cell.get("evidence") or []:
                if (ev.get("provenance") or "") == "roster":
                    continue
                if not ev.get("bbox"):
                    continue
                claims.append({
                    "stt": row.get("stt"),
                    "code": row.get("code"),
                    "criterion": row.get("label"),
                    "document": cell.get("document"),
                    "status": cell.get("status"),
                    "note": cell.get("note") or "",
                    "read": ev.get("value") or "",
                    "confidence": ev.get("confidence"),
                    "documentId": ev.get("documentId"),
                    "page": ev.get("page"),
                    "src": srcs.get((ev.get("documentId"), int(ev.get("page") or 0)), ""),
                    "bbox": ev["bbox"],
                    "reference": next(
                        (e.get("value") for c2 in row.get("cells") or []
                         for e in (c2.get("evidence") or [])
                         if (e.get("provenance") or "") == "roster" and e.get("value")),
                        "",
                    ),
                })
    return claims


def render(case_id: str, blocks: list[dict]) -> str:
    total = sum(len(b["claims"]) for b in blocks)
    parts = [f"""<!doctype html><meta charset="utf-8">
<title>Đối chiếu thủ công — {html.escape(case_id[:12])}</title>
<style>
:root {{ --bg:#f7f6f3; --surface:#fff; --border:#e5e3dd; --text:#2b2a28;
  --muted:#6b6a66; --danger:#c0392b; --warning:#b9770e; --success:#2e7d46; --accent:#2f6db3; }}
body {{ margin:0; padding:28px; background:var(--bg); color:var(--text);
  font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
h1 {{ font-size:22px; margin:0 0 4px; }}
.lede {{ color:var(--muted); max-width:74ch; margin:0 0 22px; }}
h2 {{ font-size:17px; margin:30px 0 10px; padding-top:14px; border-top:1px solid var(--border); }}
.claim {{ background:var(--surface); border:1px solid var(--border); border-radius:10px;
  padding:14px 16px; margin:0 0 14px; }}
.head {{ display:flex; gap:10px; align-items:baseline; flex-wrap:wrap; margin-bottom:8px; }}
.code {{ font-weight:700; font-variant-numeric:tabular-nums; }}
.pill {{ font-size:11.5px; padding:2px 9px; border-radius:999px; border:1px solid var(--border);
  color:var(--muted); }}
.pill.no {{ color:var(--danger); border-color:var(--danger); }}
.pill.rv, .pill.pending {{ color:var(--warning); border-color:var(--warning); }}
.pill.ok {{ color:var(--success); border-color:var(--success); }}
.pill.missing {{ color:var(--danger); border-color:var(--danger); }}
.vals {{ display:flex; gap:26px; flex-wrap:wrap; margin:8px 0; font-variant-numeric:tabular-nums; }}
.vals div {{ min-width:190px; }}
.vals .k {{ font-size:11px; letter-spacing:.05em; text-transform:uppercase; color:var(--muted); }}
.vals .v {{ font-size:16px; font-weight:600; word-break:break-word; }}
.note {{ color:var(--muted); font-size:13px; margin:6px 0 0; }}
figure {{ margin:12px 0 0; }}
figure img {{ max-width:100%; display:block; border:1px solid var(--border); border-radius:6px;
  background:#fff; }}
figcaption {{ font-size:11.5px; color:var(--muted); margin-top:5px; }}
.check {{ display:flex; gap:16px; align-items:center; margin-top:12px; padding-top:11px;
  border-top:1px dashed var(--border); flex-wrap:wrap; font-size:13.5px; }}
.check label {{ display:flex; gap:6px; align-items:center; cursor:pointer; }}
.check input[type=text] {{ flex:1; min-width:220px; padding:6px 9px; border:1px solid var(--border);
  border-radius:6px; font:inherit; }}
.missingimg {{ color:var(--danger); font-size:13px; }}
@media print {{ body {{ background:#fff; }} .claim {{ break-inside:avoid; }} }}
</style>
<h1>Đối chiếu thủ công — {total} nhận định của công cụ</h1>
<p class="lede">Mỗi khối dưới đây là <b>một điều công cụ khẳng định</b>: nó đọc được gì, ở đâu
trên bản scan (khung đỏ), và bảng kê ghi gì. Việc cần làm: nhìn khung đỏ và đánh dấu ba giá
trị đó có khớp nhau không. Nếu khung đỏ không nằm đúng chỗ, đó cũng là một phát hiện.</p>
"""]
    for block in blocks:
        parts.append(f"<h2>Gói {block['packet']} — {html.escape(block['name'] or '')}"
                     f" · {len(block['claims'])} nhận định</h2>")
        if not block["claims"]:
            parts.append('<p class="note">Không có nhận định nào kèm vị trí trên bản scan.</p>')
        for n, c in enumerate(block["claims"], 1):
            status = c["status"] or ""
            conf = ("—" if c["confidence"] is None
                    else f"{float(c['confidence']) * 100:.0f}%")
            uri, why = crop_data_uri(c["src"], c["bbox"]) if c["src"] else ("", "no page image")
            img = (f'<figure><img src="{uri}" alt="">'
                   f'<figcaption>{html.escape(str(c["documentId"]))} · trang '
                   f'{int(c["page"] or 0) + 1} — khung đỏ là chỗ công cụ nói nó đã đọc'
                   f'</figcaption></figure>'
                   if uri else f'<p class="missingimg">Không dựng được ảnh: {html.escape(why)}</p>')
            ident = f"p{block['packet']}-{n}"
            parts.append(f"""<div class="claim">
  <div class="head">
    <span class="code">#{c['stt']} {html.escape(c['code'] or '')}</span>
    <span>{html.escape(c['criterion'] or '')}</span>
    <span class="pill">{html.escape(str(c['document'] or ''))}</span>
    <span class="pill {html.escape(status)}">{html.escape(STATUS_LABEL.get(status, status))}</span>
  </div>
  <div class="vals">
    <div><div class="k">Công cụ đọc được</div><div class="v">{html.escape(c['read']) or '—'}</div></div>
    <div><div class="k">Bảng kê</div><div class="v">{html.escape(c['reference']) or '—'}</div></div>
    <div><div class="k">Độ chắc</div><div class="v">{conf}</div></div>
  </div>
  <p class="note">{html.escape(c['note'])}</p>
  {img}
  <div class="check">
    <label><input type="radio" name="{ident}"> Đúng</label>
    <label><input type="radio" name="{ident}"> Sai — đọc nhầm</label>
    <label><input type="radio" name="{ident}"> Sai — khung đỏ chỉ sai chỗ</label>
    <input type="text" placeholder="Ghi chú (tuỳ chọn)">
  </div>
</div>""")
    parts.append("<p class='note'>Dữ liệu thật — không commit, không chia sẻ ra ngoài máy.</p>")
    return "\n".join(parts)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    case_id = argv[1]
    packets = [int(a) for a in argv[2:]] or [0, 3, 24, 34, 39]

    blocks = []
    for i in packets:
        try:
            criteria = get(f"/api/cases/{case_id}/packets/{i}/criteria")
            manifest = get(f"/api/cases/{case_id}/packets/{i}/manifest.json")
        except Exception as exc:
            print(f"packet {i}: {exc}", file=sys.stderr)
            continue
        claims = claims_for(i, criteria, page_sources(manifest, case_id, i))
        blocks.append({"packet": i, "name": criteria.get("name") or "", "claims": claims})
        print(f"packet {i}: {len(claims)} claims")

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "data", "worksheets")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"worksheet-{case_id[:12]}.html")
    with open(out, "w", encoding="utf-8") as handle:
        handle.write(render(case_id, blocks))
    size = os.path.getsize(out) / 1e6
    print(f"\n{out}  ({size:.1f} MB)")
    print("REAL packet data — gitignored, keep it on this workstation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
