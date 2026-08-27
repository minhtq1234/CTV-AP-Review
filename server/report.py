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

_REJECTION_REASON_LABELS = {
    "missing_documents": "Thiếu chứng từ",
    "wrong_template": "Chứng từ không đúng mẫu",
    "missing_signature": "Thiếu chữ ký",
}


def _needs_resubmit(p: dict) -> bool:
    review = p.get("review") or {"fields": {}}
    if review.get("rejection"):
        return True
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


def _packet_rejection(packet: dict) -> dict | None:
    rejection = (packet.get("review") or {}).get("rejection")
    if not rejection:
        return None
    reasons = rejection.get("reasons") or []
    return {
        "reasons": reasons,
        "reasonLabels": [_REJECTION_REASON_LABELS[r] for r in reasons],
        "note": rejection.get("note", ""),
    }


def _criteria_for(
    packet: dict, manifest: dict | None, roster_rows: list | None,
    overrides: dict | None = None,
) -> tuple[list[dict], list[dict], dict]:
    """The engine's findings for one packet.

    Returns `(disagreements, missing_documents, counts_by_status)`. The two kinds
    of finding are separated because the CTV team acts differently on each: an
    absent document means attach the file, a disagreeing one means check the
    value. On the real July case, folding them together rendered 175 lines
    stating 40 facts -- `Hồ sơ thiếu CCCD/Passport` repeated under every
    criterion spanning that document.

    `rv` and `pending` are counted, not listed: 322 cells needing a human is a
    number, and a report that spells them all out is one nobody reads.
    """
    if roster_rows is None or manifest is None:
        return [], [], {}
    import evaluate as ev

    results = ev.evaluate_packet(manifest, _roster_row_for(packet, roster_rows),
                                 overrides)
    counts = ev.summarise(results)

    disagreements = []
    absent: dict[str, dict] = {}
    for result in results:
        item = ev.as_dict(result)
        for cell in item["cells"]:
            if cell["status"] == "missing":
                entry = absent.setdefault(
                    cell["document"],
                    {"document": cell["document"], "note": cell["note"],
                     "criteria": []},
                )
                entry["criteria"].append(result.stt)
        # A cell the reviewer cleared (`no` -> `ok`) stays in the export, marked
        # -- Acc's decision. The report is the record of what the engine found
        # and what a person did about it, not only of what is still outstanding,
        # so a cleared finding is evidence of review rather than noise to drop.
        cleared = [c for c in item["cells"]
                   if c["status"] != "no" and c["computedStatus"] == "no"]
        carrying = [c for c in item["cells"] if c["status"] == "no"]
        if carrying or cleared:
            item["cells"] = carrying + cleared
            item["clearedByReviewer"] = not carrying and bool(cleared)
            disagreements.append(item)
    return disagreements, sorted(absent.values(),
                                 key=lambda a: a["document"]), counts


def _roster_row_for(packet: dict, roster_rows: list) -> dict | None:
    import roster_checks

    identity = packet.get("rosterIdentity") or {}
    wanted = roster_checks.digits(identity.get("cccd", ""))
    if not wanted:
        return None
    columns, first_data = roster_checks.locate_columns(roster_rows)
    people, _ = roster_checks.read_people(roster_rows, columns, first_data)
    for person in people:
        if roster_checks.digits(person.get("cccd", "")) == wanted:
            return person
    return None


def _summary_section(roster_rows: list | None, packets: list,
                     purchase_total: dict | None) -> dict | None:
    """The five roster-level criteria — Acc's Tổng hợp tab, as a batch section."""
    if roster_rows is None:
        return None
    import summary_criteria as sc

    return sc.as_payload(roster_rows, packets, purchase_total)


def build_report(case: dict, manifests: dict, generated_at: str,
                 roster_rows: list | None = None,
                 purchase_total: dict | None = None,
                 overrides_by_packet: dict | None = None) -> dict:
    """The consolidated resubmission report.

    Supply `roster_rows` to include the criteria engine's own findings and the
    roster-level (Tổng hợp) section. Without it the report is exactly what it
    always was: only what a reviewer flagged by hand.
    """
    groups = []
    for p in case.get("packets", []):
        criteria, absent, counts = _criteria_for(
            p, manifests.get(p["index"]), roster_rows,
            (overrides_by_packet or {}).get(p["index"]))
        if not _needs_resubmit(p) and not criteria and not absent:
            continue
        ident = p.get("rosterIdentity") or p.get("ocrIdentity") or {}
        group = {
            "index": p["index"],
            "name": p.get("name") or ident.get("name") or f"Gói {p['index'] + 1}",
            "cccd": ident.get("cccd", ""),
            "matchedBy": p.get("matchedBy", "no-roster"),
            "identityIssue": p.get("matchedBy") in ("name", "unmatched"),
            "packetRejection": _packet_rejection(p),
            "items": _items_for(p, manifests.get(p["index"])),
        }
        if roster_rows is not None:
            group["criteria"] = criteria
            group["missingDocuments"] = absent
            group["criteriaCounts"] = counts
        groups.append(group)

    summary = _summary_section(roster_rows, case.get("packets", []),
                               purchase_total)

    md = [f"# Báo cáo cần gửi lại — {case.get('name', '')}", "",
          f"_Tạo lúc: {generated_at}_", ""]
    if summary is not None:
        md += ["## Kiểm tra toàn bảng kê", ""]
        for c in summary["criteria"]:
            md.append(f"- **#{c['stt']} {c['label']}** — {c['message']}")
            for detail in c["detail"]:
                md.append(f"  - {detail}")
        md.append("")
    for g in groups:
        md.append(f"## {g['name']} — CCCD {g['cccd']}")
        if g["packetRejection"]:
            rejection = g["packetRejection"]
            note = f" — Ghi chú: {rejection['note']}" if rejection["note"] else ""
            md.append(
                f"- **Từ chối gói hồ sơ** — "
                f"{'; '.join(rejection['reasonLabels'])}{note}"
            )
        if g["identityIssue"]:
            md.append(f"> ⚠ {_MATCH_NOTE.get(g['matchedBy'], '')}")
        for it in g["items"]:
            loc = it["document"] + (f", trang {it['page']}" if it["page"] else "")
            reason = f" — {it['reason']}" if it["reason"] else ""
            note = f": {it['note']}" if it["note"] else ""
            md.append(f"- **{it['fieldLabel']}** ({loc}): bảng kê \"{it['rosterValue']}\" "
                      f"≠ chứng từ \"{it['docValue']}\"{reason}{note}")
        for absent in g.get("missingDocuments", []):
            blocks = ", ".join(f"#{stt:02d}" for stt in absent["criteria"])
            md.append(f"- **Thiếu chứng từ: {absent['document']}** "
                      f"— chưa kiểm tra được {blocks}")
        for c in g.get("criteria", []):
            mark = (" — _người kiểm tra đã xác nhận_"
                    if c.get("clearedByReviewer") else "")
            md.append(f"- **#{c['stt']} {c['label']}**{mark}")
            for cell in c["cells"]:
                read = (f" đọc được \"{cell['value']}\" —" if cell["value"]
                        else "")
                md.append(f"  - {cell['document']}:{read} {cell['note']}")
        counts = g.get("criteriaCounts") or {}
        if counts.get("rv") or counts.get("pending"):
            md.append(f"- _Còn {counts.get('rv', 0)} tiêu chí cần người kiểm "
                      f"tra, {counts.get('pending', 0)} chưa kiểm tra được._")
        md.append("")

    buf = io.StringIO()
    w = _csv.writer(buf)
    w.writerow(["CTV", "CCCD", "Trường", "Chứng từ", "Trang",
                "Bảng kê", "Chứng từ đọc được", "Lý do", "Ghi chú"])
    for g in groups:
        if g["packetRejection"]:
            rejection = g["packetRejection"]
            w.writerow([
                g["name"], g["cccd"], "Từ chối gói hồ sơ", "", "", "", "",
                "; ".join(rejection["reasonLabels"]), rejection["note"],
            ])
        if g["identityIssue"] and not g["items"]:
            w.writerow([g["name"], g["cccd"], "Định danh", "", "", "", "",
                        g["matchedBy"], _MATCH_NOTE.get(g["matchedBy"], "")])
        for it in g["items"]:
            w.writerow([g["name"], g["cccd"], it["fieldLabel"], it["document"],
                        it["page"] or "", it["rosterValue"], it["docValue"],
                        it["reason"], it["note"]])
        for absent in g.get("missingDocuments", []):
            w.writerow([g["name"], g["cccd"], "Thiếu chứng từ",
                        absent["document"], "", "", "",
                        ", ".join(f"#{stt:02d}" for stt in absent["criteria"]),
                        absent["note"]])
        for c in g.get("criteria", []):
            for cell in c["cells"]:
                w.writerow([g["name"], g["cccd"],
                            f"#{c['stt']} {c['label']}", cell["document"], "",
                            "", cell["value"], cell["status"], cell["note"]])
    out = {"groups": groups, "markdown": "\n".join(md), "csv": buf.getvalue()}
    if summary is not None:
        out["summary"] = summary
    return out
