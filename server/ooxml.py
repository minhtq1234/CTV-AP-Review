"""Shared safe helpers for resolving OOXML package relationships."""
from __future__ import annotations

import posixpath
from pathlib import PurePosixPath


class OoxmlRelationshipError(ValueError):
    """Raised when a relationship target cannot be resolved inside a package."""


def resolve_internal_relationship_target(
    source_part: str,
    target: str,
    *,
    external: bool = False,
) -> str:
    """Resolve a relationship target to a normalized package member path."""
    if external:
        raise OoxmlRelationshipError("external-relationship")
    if not target or "\\" in target or "\x00" in target or target.startswith("//"):
        raise OoxmlRelationshipError("invalid-target")
    candidate = (
        target[1:]
        if target.startswith("/")
        else str(PurePosixPath(source_part).parent / target)
    )
    normalized = PurePosixPath(posixpath.normpath(candidate))
    if (
        str(normalized) in {"", "."}
        or normalized.is_absolute()
        or ".." in normalized.parts
    ):
        raise OoxmlRelationshipError("invalid-target")
    return str(normalized)
