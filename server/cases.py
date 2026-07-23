"""Persistent case store: JSON-on-disk under `<root>/<case_id>/case.json`,
replacing the in-memory `JobStore`. A case is one uploaded submission (a
batch of CTV packets); its `packets[]` carry per-packet review decisions
that must survive a backend restart, so every mutation writes through to
disk and the index is rebuilt from disk on startup.

Kept deliberately simple (no database): one JSON file per case, an
in-memory index for fast listing, `shutil.rmtree` for delete. Corrupt or
unreadable `case.json` files are skipped on load rather than crashing the
index (a partially-written file from a killed process shouldn't take down
the whole store).
"""
from __future__ import annotations

import json
import os
import shutil
import uuid


def needs_resubmit(packet: dict) -> bool:
    """A packet needs resubmission if any checklist item is flagged, or its
    roster match is weak (matched by name only, or unmatched)."""
    review = packet.get("review") or {"items": {}}
    if any(i.get("flag") for i in review.get("items", {}).values()):
        return True
    return packet.get("matchedBy") in ("name", "unmatched")


def case_status(base_status: str, packets: list[dict]) -> str:
    """Recompute a case's status from its base lifecycle state + packet
    review state. `base_status` short-circuits while the pipeline is still
    running or failed; otherwise status is derived from how many packets
    have `review.done` set.
    """
    if base_status in ("processing", "error"):
        return base_status
    if not packets:
        return "ready"
    done = sum(1 for p in packets if (p.get("review") or {}).get("done"))
    if done == 0:
        return "ready"
    if done == len(packets):
        return "done"
    return "in_review"


def progress_of(packets: list[dict]) -> dict:
    """`{done, total, flagged}` — done = packets marked Done,
    flagged = packets needing resubmission."""
    return {
        "done": sum(1 for p in packets if (p.get("review") or {}).get("done")),
        "total": len(packets),
        "flagged": sum(1 for p in packets if needs_resubmit(p)),
    }


def _ensure_packet_defaults(packet: dict) -> dict:
    """Fill review/match defaults if the pipeline (or a fake test pipeline)
    didn't set them."""
    out = dict(packet)
    out.setdefault("review", {"done": False, "items": {}})
    out.setdefault("matchedBy", "no-roster")
    out.setdefault("ocrIdentity", {"cccd": "", "name": ""})
    out.setdefault("rosterIdentity", None)
    return out


class CaseStore:
    """Registry of case dicts, persisted one-JSON-file-per-case under `root`.

    Case shape: `{id, name, createdAt, status, pdfName, rosterName, summary,
    error, packets}` — see the spec's data model. The in-memory `self._idx`
    mirrors disk for fast `list()`/`get()`; every mutating method writes the
    updated case back to disk before returning.
    """

    def __init__(self, root: str) -> None:
        self.root = root
        os.makedirs(root, exist_ok=True)
        self._idx: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.isdir(self.root):
            return
        for cid in os.listdir(self.root):
            path = self._path(cid)
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    case = json.load(f)
            except Exception:  # noqa: BLE001 - skip corrupt/partial files, don't crash startup
                continue
            if case.get("status") == "processing":
                # #007: a case still "processing" on disk has no live worker --
                # the process that was running its pipeline is gone (this is a
                # startup index rebuild, not a resume). Reconcile it to a
                # stale/error state so the list offers delete/retry instead of
                # showing a perpetual "Đang xử lý…" spinner. Persist it so the
                # reconciled state survives (not just patched in memory).
                case["status"] = "error"
                case["error"] = "Xử lý bị gián đoạn — vui lòng xoá và tải lại."
                self._write(case)
            else:
                # #Task2/#Task3: migrate legacy packets so cases persisted
                # before the review model settled don't crash the new code.
                # Two generations of legacy shape are handled:
                #  - pre-review-model packets (before `decision`/
                #    `rejectReason`/`reviewedAt` were replaced by
                #    `review={"done", ...}` + match meta): missing `review`
                #    entirely.
                #  - field-keyed review (`review={"done","fields"}`, from
                #    before the checklist rework): has `review` but it still
                #    carries `fields` instead of `items`. Old field-keys
                #    don't map to check-codes, so this resets to an empty
                #    checklist rather than trying to translate keys.
                # Idempotent — a second load is a no-op either way.
                changed = False
                for p in case.get("packets", []):
                    if "review" not in p:
                        p["review"] = {"done": False, "items": {}}
                        for k in ("decision", "rejectReason", "reviewedAt"):
                            p.pop(k, None)
                        p.setdefault("matchedBy", "no-roster")
                        p.setdefault("ocrIdentity", {"cccd": "", "name": ""})
                        p.setdefault("rosterIdentity", None)
                        changed = True
                    elif "fields" in p["review"] or "items" not in p["review"]:
                        p["review"] = {"done": p["review"].get("done", False), "items": {}}
                        changed = True
                if changed:
                    self._write(case)   # persist migration (also indexes)
                else:
                    self._idx[cid] = case

    def _path(self, cid: str) -> str:
        return os.path.join(self.root, cid, "case.json")

    def _write(self, case: dict) -> None:
        path = self._path(case["id"])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(case, f, ensure_ascii=False, indent=2)
        self._idx[case["id"]] = case

    def create(self, name: str, pdf_name: str, roster_name: str | None, now: str | None = None) -> str:
        cid = uuid.uuid4().hex
        case = {
            "id": cid,
            "name": name,
            "createdAt": now,
            "status": "processing",
            "pdfName": pdf_name,
            "rosterName": roster_name,
            "summary": None,
            "error": None,
            "packets": [],
        }
        os.makedirs(os.path.join(self.root, cid), exist_ok=True)
        self._write(case)
        return cid

    def get(self, cid: str) -> dict | None:
        return self._idx.get(cid)

    def list(self) -> list[dict]:
        # Newest first by createdAt; cases with no createdAt (shouldn't
        # normally happen — the app always stamps one — but tests may
        # create one without) sort last.
        with_date = sorted(
            (c for c in self._idx.values() if c["createdAt"] is not None),
            key=lambda c: c["createdAt"],
            reverse=True,
        )
        without_date = [c for c in self._idx.values() if c["createdAt"] is None]
        ordered = with_date + without_date
        return [
            {
                "id": c["id"],
                "name": c["name"],
                "createdAt": c["createdAt"],
                "status": c["status"],
                "pdfName": c["pdfName"],
                "progress": progress_of(c["packets"]),
            }
            for c in ordered
        ]

    def set_result(self, cid: str, summary: dict | None, packets: list[dict]) -> None:
        case = self._idx.get(cid)
        if case is None:
            return
        filled = [_ensure_packet_defaults(p) for p in packets]
        case["summary"] = summary
        case["packets"] = filled
        case["status"] = case_status("ready", filled)
        self._write(case)

    def set_error(self, cid: str, msg: str) -> None:
        case = self._idx.get(cid)
        if case is None:
            return
        case["status"] = "error"
        case["error"] = msg
        self._write(case)

    def set_review(self, cid: str, index: int, review: dict) -> dict | None:
        case = self._idx.get(cid)
        if case is None:
            return None
        for p in case["packets"]:
            if p["index"] == index:
                p["review"] = {
                    "done": bool(review.get("done", False)),
                    "items": review.get("items", {}) or {},
                }
                break
        else:
            return None
        base = case["status"] if case["status"] in ("processing", "error") else "ready"
        case["status"] = case_status(base, case["packets"])
        self._write(case)
        return case

    def delete(self, cid: str) -> None:
        case_dir = os.path.join(self.root, cid)
        if os.path.isdir(case_dir):
            shutil.rmtree(case_dir)
        self._idx.pop(cid, None)

    def case_dir(self, cid: str) -> str:
        return os.path.join(self.root, cid)
