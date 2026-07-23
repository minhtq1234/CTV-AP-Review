"""Pure builder for the consolidated resubmission report. Given a case dict,
a {packet_index: manifest} map, and a timestamp string, produce grouped data
plus Markdown + CSV renderings. No FastAPI / disk / clock here so it is unit
testable; the app layer loads manifests + stamps the time."""
from __future__ import annotations

import csv as _csv
import io

_MATCH_NOTE = {
    "name": "Định danh khớp theo tên — CCCD chưa khớp, cần xác minh đúng người.",
    "unmatched": "Không khớp được với bảng kê — cần xác minh đúng người.",
}


def _needs_resubmit(p: dict) -> bool:
    review = p.get("review") or {"fields": {}}
    if any(f.get("flag") for f in review.get("fields", {}).values()):
        return True
    return p.get("matchedBy") in ("name", "unmatched")


def _items_for(packet: dict, manifest: dict | None) -> list[dict]:
    fields = {f["key"]: f for f in (manifest or {}).get("fields", [])}
    docs = {d["id"]: d.get("label", d["id"]) for d in (manifest or {}).get("docs", [])}
    items = []
    for key, fr in (packet.get("review") or {}).get("fields", {}).items():
        flag = fr.get("flag")
        if not flag:
            continue
        f = fields.get(key, {})
        src = (f.get("sources") or [{}])[0]
        items.append({
            "fieldKey": key,
            "fieldLabel": f.get("label", key),
            "document": docs.get(src.get("docId"), "—"),
            "page": (src["page"] + 1) if "page" in src else None,
            "rosterValue": f.get("expected", ""),
            "docValue": src.get("value") or "cần xem",
            "reason": flag.get("reason", ""),
            "note": flag.get("note", ""),
        })
    return items


def build_report(case: dict, manifests: dict, generated_at: str) -> dict:
    groups = []
    for p in case.get("packets", []):
        if not _needs_resubmit(p):
            continue
        ident = p.get("rosterIdentity") or p.get("ocrIdentity") or {}
        groups.append({
            "index": p["index"],
            "name": p.get("name") or ident.get("name") or f"Gói {p['index'] + 1}",
            "cccd": ident.get("cccd", ""),
            "matchedBy": p.get("matchedBy", "no-roster"),
            "identityIssue": p.get("matchedBy") in ("name", "unmatched"),
            "items": _items_for(p, manifests.get(p["index"])),
        })

    md = [f"# Báo cáo cần gửi lại — {case.get('name', '')}", "",
          f"_Tạo lúc: {generated_at}_", ""]
    for g in groups:
        md.append(f"## {g['name']} — CCCD {g['cccd']}")
        if g["identityIssue"]:
            md.append(f"> ⚠ {_MATCH_NOTE.get(g['matchedBy'], '')}")
        for it in g["items"]:
            loc = it["document"] + (f", trang {it['page']}" if it["page"] else "")
            reason = f" — {it['reason']}" if it["reason"] else ""
            note = f": {it['note']}" if it["note"] else ""
            md.append(f"- **{it['fieldLabel']}** ({loc}): bảng kê \"{it['rosterValue']}\" "
                      f"≠ chứng từ \"{it['docValue']}\"{reason}{note}")
        md.append("")

    buf = io.StringIO()
    w = _csv.writer(buf)
    w.writerow(["CTV", "CCCD", "Trường", "Chứng từ", "Trang",
                "Bảng kê", "Chứng từ đọc được", "Lý do", "Ghi chú"])
    for g in groups:
        if g["identityIssue"] and not g["items"]:
            w.writerow([g["name"], g["cccd"], "Định danh", "", "", "", "",
                        g["matchedBy"], _MATCH_NOTE.get(g["matchedBy"], "")])
        for it in g["items"]:
            w.writerow([g["name"], g["cccd"], it["fieldLabel"], it["document"],
                        it["page"] or "", it["rosterValue"], it["docValue"],
                        it["reason"], it["note"]])
    return {"groups": groups, "markdown": "\n".join(md), "csv": buf.getvalue()}
