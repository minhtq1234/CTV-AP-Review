"""Seam for the GreenNode (VNG cloud) summariser. The recap endpoint calls
summarize() with ONLY the typed content region (see recap.content_region_for);
this module is the single place the live HTTP call drops in.

Until creds are wired (or the live call is implemented) summarize() raises
NotConfigured, which the endpoint surfaces as HTTP 503. The offline export never
reaches this path — it uses the canned recap baked into the synthetic packets."""
from __future__ import annotations

import os


class NotConfigured(Exception):
    """GreenNode isn't wired (no creds) or the live call isn't implemented yet."""


def is_configured() -> bool:
    return bool(os.environ.get("GREENNODE_API_URL") and os.environ.get("GREENNODE_API_KEY"))


def summarize(content: str) -> dict:
    """Summarise the typed content region into {"bullets": [...], "nhanDinh": "..."}.

    Raises NotConfigured until the live call is wired."""
    if not is_configured():
        raise NotConfigured(
            "GreenNode chưa cấu hình (đặt GREENNODE_API_URL + GREENNODE_API_KEY)."
        )
    # TODO(greennode): POST `content` to os.environ["GREENNODE_API_URL"] with a
    # Bearer os.environ["GREENNODE_API_KEY"] header, instructing the model to return
    # Vietnamese JSON {"bullets": [<2-3 strings>], "nhanDinh": "<one line>"} for a
    # payment-document recap; parse and return it. `content` (the typed content
    # region) is the ONLY thing sent — never the image or any other packet data.
    raise NotConfigured("GreenNode: lời gọi trực tiếp chưa được nối (TODO).")
