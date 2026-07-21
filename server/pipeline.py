"""Placeholder for Task B3 (split + per-packet OCR orchestration).

Exists at this point in the build only so `server/app.py` has a stable
`run_pipeline` symbol to import (and tests can monkeypatch it). The real
implementation lands in a follow-up commit — see
docs/superpowers/plans/2026-07-13-stage-b-backend.md, Task B3.
"""
from __future__ import annotations


def run_pipeline(pdf_path: str, roster_path: str | None, job_dir: str, progress_cb) -> dict:
    raise NotImplementedError("pipeline.run_pipeline not yet implemented (Task B3)")
