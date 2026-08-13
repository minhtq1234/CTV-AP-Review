"""Secure, bounded, private-safe inventory of one explicit local folder."""

import errno
import hashlib
import json
import os
import stat
import weakref
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Literal

from ctv_inventory_detection import detect_type, safe_extension, type_issue_codes
from ctv_inventory_model import (
    DEFAULT_LIMITS,
    InventoryItemDraft,
    InventoryLimits,
    InventoryResult,
    InventoryTotals,
    assign_evidence_and_duplicate_ids,
)


_READ_CHUNK = 64 * 1024
_UNAVAILABLE_ERRNOS = frozenset(
    value
    for value in (
        getattr(errno, "ENOSYS", None),
        getattr(errno, "ENOTSUP", None),
        getattr(errno, "EOPNOTSUPP", None),
    )
    if value is not None
)
_PERMISSION_ERRNOS = frozenset(
    value
    for value in (getattr(errno, "EACCES", None), getattr(errno, "EPERM", None))
    if value is not None
)


class InventoryError(RuntimeError):
    """A controlled operation failure containing only a stable public code."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class _EntryFact:
    components: tuple[str, ...]
    private_sort_key: bytes
    depth: int
    kind: Literal["regular", "directory", "symlink", "special"]
    device: int
    inode: int
    mode: int
    size: int | None
    modified_ns: int
    changed_ns: int


class _SampleReadFailed(Exception):
    pass


class _HashReadFailed(Exception):
    pass


@dataclass(frozen=True)
class ObservedInventorySource:
    """Public-safe source metadata bound to one retained observation."""

    evidence_id: str
    extension: str
    detected_type: str
    size: int | None
    hash_status: str
    issue_codes: tuple[str, ...]


class InventoryObservation:
    """A public-safe handle to one live descriptor-bound observation."""

    __slots__ = ("__observation_id", "__result", "__sources", "__weakref__")

    def __new__(cls, *args, **kwargs):
        raise TypeError("inventory observations are created by their context")

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("inventory observation properties are read-only")

    @property
    def result(self) -> InventoryResult:
        return self.__result

    @property
    def observation_id(self) -> str:
        return self.__observation_id

    @property
    def sources(self) -> tuple[ObservedInventorySource, ...]:
        return self.__sources

    def snapshot(self, evidence_id: str, *, max_bytes: int) -> bytes:
        return _snapshot_observed_source(self, evidence_id, max_bytes=max_bytes)

    def __repr__(self) -> str:
        return (
            "InventoryObservation("
            f"observation_id={self.__observation_id!r}, "
            f"sources={len(self.__sources)})"
        )


@dataclass
class _ObservationState:
    root_descriptor: int | None
    source_components: tuple[str, ...]
    root_fact: _EntryFact
    authoritative_facts: tuple[_EntryFact, ...]
    directory_facts: dict[tuple[str, ...], _EntryFact]
    evidence_facts: dict[str, _EntryFact]
    limits: InventoryLimits


_OBSERVATION_STATES: dict[
    int, tuple[weakref.ReferenceType[InventoryObservation], _ObservationState]
] = {}


def _require_secure_open() -> None:
    required_flags = ("O_NOFOLLOW", "O_DIRECTORY", "O_NONBLOCK", "O_CLOEXEC")
    supported = (
        all(hasattr(os, name) for name in required_flags)
        and os.open in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.stat in os.supports_follow_symlinks
        and os.scandir in os.supports_fd
    )
    if not supported:
        raise InventoryError("secure-open-unavailable")


def _directory_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _regular_flags() -> int:
    return os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


def _close(descriptor: int | None) -> None:
    if descriptor is None:
        return
    try:
        os.close(descriptor)
    except OSError:
        pass


def _new_inventory_observation(
    result: InventoryResult,
    observation_id: str,
    sources: tuple[ObservedInventorySource, ...],
) -> InventoryObservation:
    observation = object.__new__(InventoryObservation)
    object.__setattr__(
        observation, "_InventoryObservation__observation_id", observation_id
    )
    object.__setattr__(observation, "_InventoryObservation__result", result)
    object.__setattr__(observation, "_InventoryObservation__sources", sources)
    return observation


def _register_observation(
    observation: InventoryObservation, state: _ObservationState
) -> None:
    key = id(observation)

    def release_abandoned(
        reference: weakref.ReferenceType[InventoryObservation], *, key: int = key
    ) -> None:
        current = _OBSERVATION_STATES.get(key)
        if current is None or current[0] is not reference:
            return
        _, abandoned = _OBSERVATION_STATES.pop(key)
        descriptor = abandoned.root_descriptor
        abandoned.root_descriptor = None
        _close(descriptor)

    reference = weakref.ref(observation, release_abandoned)
    if key in _OBSERVATION_STATES:
        raise InventoryError("inventory-tree-changed")
    _OBSERVATION_STATES[key] = (reference, state)


def _observation_state(observation: InventoryObservation) -> _ObservationState:
    if type(observation) is not InventoryObservation:
        raise RuntimeError("inventory observation is closed")
    current = _OBSERVATION_STATES.get(id(observation))
    if (
        current is None
        or current[0]() is not observation
        or current[1].root_descriptor is None
    ):
        raise RuntimeError("inventory observation is closed")
    return current[1]


def _release_observation(observation: InventoryObservation) -> None:
    key = id(observation)
    current = _OBSERVATION_STATES.get(key)
    if current is None or current[0]() is not observation:
        return
    _, state = _OBSERVATION_STATES.pop(key)
    descriptor = state.root_descriptor
    state.root_descriptor = None
    _close(descriptor)


def _unavailable(error: OSError) -> bool:
    return error.errno in _UNAVAILABLE_ERRNOS


def _normalize_source(source_root: Path) -> tuple[str, ...]:
    try:
        raw_path = os.fspath(source_root)
    except TypeError:
        raise InventoryError("source-root-unsafe") from None
    if not isinstance(raw_path, str) or not raw_path or "\0" in raw_path:
        raise InventoryError("source-root-unsafe")
    if raw_path == os.sep:
        return ()
    lexical_components = raw_path.split(os.sep)
    if raw_path.startswith(os.sep):
        lexical_components = lexical_components[1:]
    if not lexical_components or any(
        component in {"", ".", ".."} for component in lexical_components
    ):
        raise InventoryError("source-root-unsafe")
    try:
        normalized = os.path.abspath(raw_path)
    except (OSError, ValueError):
        raise InventoryError("source-root-unsafe") from None
    if not normalized.startswith(os.sep):
        raise InventoryError("source-root-unsafe")
    if normalized == os.sep:
        return ()
    components = tuple(normalized[len(os.sep) :].split(os.sep))
    if any(component in {"", ".", ".."} for component in components):
        raise InventoryError("source-root-unsafe")
    return components


def _open_root_components(
    components: tuple[str, ...], *, initial: bool
) -> int:
    current = None
    try:
        current = os.open(os.sep, _directory_flags())
        opened = os.fstat(current)
        if not stat.S_ISDIR(opened.st_mode):
            raise InventoryError(
                "source-root-unsafe" if initial else "inventory-tree-changed"
            )
        for component in components:
            next_descriptor = None
            try:
                next_descriptor = os.open(
                    component, _directory_flags(), dir_fd=current
                )
                opened = os.fstat(next_descriptor)
                if not stat.S_ISDIR(opened.st_mode):
                    raise InventoryError(
                        "source-root-unsafe"
                        if initial
                        else "inventory-tree-changed"
                    )
            except InventoryError:
                _close(next_descriptor)
                raise
            except (NotImplementedError, TypeError):
                _close(next_descriptor)
                raise InventoryError("secure-open-unavailable") from None
            except OSError as error:
                _close(next_descriptor)
                if _unavailable(error):
                    raise InventoryError("secure-open-unavailable") from None
                if initial and error.errno == errno.ENOENT:
                    raise InventoryError("source-root-missing") from None
                raise InventoryError(
                    "source-root-unsafe" if initial else "inventory-tree-changed"
                ) from None
            _close(current)
            current = next_descriptor
        result = current
        current = None
        return result
    except InventoryError:
        raise
    except (NotImplementedError, TypeError):
        raise InventoryError("secure-open-unavailable") from None
    except OSError as error:
        if _unavailable(error):
            raise InventoryError("secure-open-unavailable") from None
        if initial and error.errno == errno.ENOENT:
            raise InventoryError("source-root-missing") from None
        raise InventoryError(
            "source-root-unsafe" if initial else "inventory-tree-changed"
        ) from None
    finally:
        _close(current)


def _entry_kind(mode: int) -> Literal["regular", "directory", "symlink", "special"]:
    if stat.S_ISREG(mode):
        return "regular"
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISLNK(mode):
        return "symlink"
    return "special"


def _sort_key(components: tuple[str, ...]) -> bytes:
    try:
        return b"/".join(component.encode("utf-8") for component in components)
    except UnicodeEncodeError:
        raise InventoryError("inventory-entry-unsafe") from None


def _fact_from_metadata(
    components: tuple[str, ...], metadata: os.stat_result
) -> _EntryFact:
    return _EntryFact(
        components=components,
        private_sort_key=_sort_key(components),
        depth=len(components),
        kind=_entry_kind(metadata.st_mode),
        device=metadata.st_dev,
        inode=metadata.st_ino,
        mode=metadata.st_mode,
        size=metadata.st_size,
        modified_ns=metadata.st_mtime_ns,
        changed_ns=metadata.st_ctime_ns,
    )


def _fact_matches_metadata(fact: _EntryFact, metadata: os.stat_result) -> bool:
    return (
        _entry_kind(metadata.st_mode) == fact.kind
        and (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )
        == (
            fact.device,
            fact.inode,
            fact.mode,
            fact.size,
            fact.modified_ns,
            fact.changed_ns,
        )
    )


def _same_directory_observation(before: os.stat_result, after: os.stat_result) -> bool:
    return (
        stat.S_ISDIR(before.st_mode)
        and stat.S_ISDIR(after.st_mode)
        and (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        == (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
    )


def _open_directory_path(
    root_descriptor: int,
    components: tuple[str, ...],
    directory_facts: dict[tuple[str, ...], _EntryFact],
) -> tuple[int, bool]:
    current = root_descriptor
    owned = False
    prefix: tuple[str, ...] = ()
    try:
        for component in components:
            prefix += (component,)
            expected = directory_facts.get(prefix)
            if expected is None or expected.kind != "directory":
                raise InventoryError("inventory-tree-changed")
            next_descriptor = None
            try:
                next_descriptor = os.open(
                    component, _directory_flags(), dir_fd=current
                )
                opened = os.fstat(next_descriptor)
            except (NotImplementedError, TypeError):
                _close(next_descriptor)
                raise InventoryError("secure-open-unavailable") from None
            except OSError as error:
                _close(next_descriptor)
                if _unavailable(error):
                    raise InventoryError("secure-open-unavailable") from None
                raise InventoryError("inventory-tree-changed") from None
            if not _fact_matches_metadata(expected, opened):
                _close(next_descriptor)
                raise InventoryError("inventory-tree-changed")
            if owned:
                _close(current)
            current = next_descriptor
            owned = True
        return current, owned
    except Exception:
        if owned:
            _close(current)
        raise


def _stat_child(directory_descriptor: int, name: str) -> os.stat_result:
    try:
        return os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
    except (NotImplementedError, TypeError):
        raise InventoryError("secure-open-unavailable") from None
    except OSError as error:
        if _unavailable(error):
            raise InventoryError("secure-open-unavailable") from None
        if error.errno == errno.ENOENT:
            raise InventoryError("inventory-tree-changed") from None
        raise InventoryError("inventory-directory-unreadable") from None


def _scan_directory(
    directory_descriptor: int,
    parent_components: tuple[str, ...],
    limits: InventoryLimits,
    counters: dict[str, int],
) -> tuple[_EntryFact, ...]:
    try:
        before = os.fstat(directory_descriptor)
        entries: list[_EntryFact] = []
        with os.scandir(directory_descriptor) as iterator:
            for entry in iterator:
                if not isinstance(entry.name, str) or entry.name in {"", ".", ".."}:
                    raise InventoryError("inventory-entry-unsafe")
                components = parent_components + (entry.name,)
                depth = len(components)
                if depth > limits.max_depth:
                    raise InventoryError("inventory-depth-exceeded")
                counters["entries"] += 1
                if counters["entries"] > limits.max_entries:
                    raise InventoryError("inventory-entry-count-exceeded")

                metadata = _stat_child(directory_descriptor, entry.name)
                fact = _fact_from_metadata(components, metadata)
                if fact.kind == "directory":
                    counters["directories"] += 1
                    if counters["directories"] > limits.max_directories:
                        raise InventoryError("inventory-directory-count-exceeded")
                else:
                    counters["items"] += 1
                    if counters["items"] > limits.max_items:
                        raise InventoryError("inventory-item-count-exceeded")
                    if fact.kind == "regular":
                        counters["regular_files"] += 1
                        if counters["regular_files"] > limits.max_regular_files:
                            raise InventoryError(
                                "inventory-regular-file-count-exceeded"
                            )
                entries.append(fact)
        after = os.fstat(directory_descriptor)
    except InventoryError:
        raise
    except (NotImplementedError, TypeError):
        raise InventoryError("secure-open-unavailable") from None
    except OSError as error:
        if _unavailable(error):
            raise InventoryError("secure-open-unavailable") from None
        raise InventoryError("inventory-directory-unreadable") from None
    if not _same_directory_observation(before, after):
        raise InventoryError("inventory-tree-changed")
    return tuple(entries)


def _enumerate_tree(
    root_descriptor: int, limits: InventoryLimits
) -> tuple[_EntryFact, ...]:
    counters = {"entries": 0, "directories": 0, "items": 0, "regular_files": 0}
    facts: list[_EntryFact] = []
    directory_facts: dict[tuple[str, ...], _EntryFact] = {}
    pending: list[tuple[str, ...]] = [()]

    while pending:
        components = pending.pop()
        descriptor = root_descriptor
        owned = False
        try:
            if components:
                descriptor, owned = _open_directory_path(
                    root_descriptor, components, directory_facts
                )
            found = _scan_directory(descriptor, components, limits, counters)
        finally:
            if owned:
                _close(descriptor)
        for fact in found:
            facts.append(fact)
            if fact.kind == "directory":
                directory_facts[fact.components] = fact
                pending.append(fact.components)

    return tuple(sorted(facts, key=lambda fact: fact.private_sort_key))


def _directory_fact_map(
    facts: tuple[_EntryFact, ...],
) -> dict[tuple[str, ...], _EntryFact]:
    return {fact.components: fact for fact in facts if fact.kind == "directory"}


def _open_regular(
    root_descriptor: int,
    fact: _EntryFact,
    directory_facts: dict[tuple[str, ...], _EntryFact],
) -> int | None:
    parent_descriptor = root_descriptor
    parent_owned = False
    file_descriptor = None
    try:
        parent_descriptor, parent_owned = _open_directory_path(
            root_descriptor, fact.components[:-1], directory_facts
        )
        try:
            file_descriptor = os.open(
                fact.components[-1],
                _regular_flags(),
                dir_fd=parent_descriptor,
            )
            opened = os.fstat(file_descriptor)
        except PermissionError:
            return None
        except (NotImplementedError, TypeError):
            raise InventoryError("secure-open-unavailable") from None
        except OSError as error:
            if _unavailable(error):
                raise InventoryError("secure-open-unavailable") from None
            if error.errno in _PERMISSION_ERRNOS:
                return None
            raise InventoryError("inventory-tree-changed") from None
        if not _fact_matches_metadata(fact, opened):
            raise InventoryError("inventory-tree-changed")
        result = file_descriptor
        file_descriptor = None
        return result
    finally:
        _close(file_descriptor)
        if parent_owned:
            _close(parent_descriptor)


def _read_sample(file_descriptor: int, expected_size: int, limit: int) -> tuple[bytes, bool]:
    target = min(expected_size, limit)
    remaining = target
    chunks: list[bytes] = []
    try:
        while remaining:
            chunk = os.read(file_descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
    except OSError:
        raise _SampleReadFailed from None
    return b"".join(chunks), remaining != 0


def _stream_hash(file_descriptor: int, expected_size: int) -> tuple[str | None, bool]:
    try:
        os.lseek(file_descriptor, 0, os.SEEK_SET)
        digest = hashlib.sha256()
        remaining = expected_size
        while remaining:
            chunk = os.read(file_descriptor, min(_READ_CHUNK, remaining))
            if not chunk:
                break
            digest.update(chunk)
            remaining -= len(chunk)
    except OSError:
        raise _HashReadFailed from None
    if remaining:
        return None, True
    return digest.hexdigest(), False


def _current_regular_metadata(
    root_descriptor: int,
    fact: _EntryFact,
    directory_facts: dict[tuple[str, ...], _EntryFact],
) -> os.stat_result:
    parent_descriptor = root_descriptor
    parent_owned = False
    try:
        parent_descriptor, parent_owned = _open_directory_path(
            root_descriptor, fact.components[:-1], directory_facts
        )
        try:
            return os.stat(
                fact.components[-1],
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except (NotImplementedError, TypeError):
            raise InventoryError("secure-open-unavailable") from None
        except OSError as error:
            if _unavailable(error):
                raise InventoryError("secure-open-unavailable") from None
            raise InventoryError("inventory-tree-changed") from None
    finally:
        if parent_owned:
            _close(parent_descriptor)


def _read_observation_is_stable(
    root_descriptor: int,
    file_descriptor: int,
    fact: _EntryFact,
    directory_facts: dict[tuple[str, ...], _EntryFact],
) -> bool:
    try:
        descriptor_metadata = os.fstat(file_descriptor)
    except OSError:
        raise InventoryError("inventory-tree-changed") from None
    path_metadata = _current_regular_metadata(
        root_descriptor, fact, directory_facts
    )
    return (
        _fact_matches_metadata(fact, descriptor_metadata)
        and _fact_matches_metadata(fact, path_metadata)
        and stat.S_ISREG(descriptor_metadata.st_mode)
        and stat.S_ISREG(path_metadata.st_mode)
    )


def _snapshot_observed_source(
    observation: InventoryObservation,
    evidence_id: str,
    *,
    max_bytes: int,
) -> bytes:
    state = _observation_state(observation)
    if type(evidence_id) is not str:
        raise ValueError("evidence_id is not bound to this observation")
    fact = state.evidence_facts.get(evidence_id)
    if fact is None:
        raise ValueError("evidence_id is not bound to this observation")
    if fact.kind != "regular" or fact.size is None:
        raise ValueError("evidence_id does not identify a regular source")
    if type(max_bytes) is not int or max_bytes < 0:
        raise TypeError("max_bytes must be a non-negative integer")
    if fact.size > max_bytes:
        raise ValueError("source exceeds max_bytes")

    root_descriptor = state.root_descriptor
    if root_descriptor is None:
        raise RuntimeError("inventory observation is closed")
    descriptor = _open_regular(
        root_descriptor,
        fact,
        state.directory_facts,
    )
    if descriptor is None:
        raise InventoryError("inventory-tree-changed")

    try:
        remaining = fact.size
        snapshot = bytearray()
        while remaining:
            try:
                chunk = os.read(descriptor, min(_READ_CHUNK, remaining))
            except OSError:
                raise InventoryError("inventory-tree-changed") from None
            if not chunk or len(chunk) > remaining:
                raise InventoryError("inventory-tree-changed")
            snapshot.extend(chunk)
            remaining -= len(chunk)
        if not _read_observation_is_stable(
            root_descriptor,
            descriptor,
            fact,
            state.directory_facts,
        ):
            raise InventoryError("inventory-tree-changed")
        return bytes(snapshot)
    finally:
        _close(descriptor)


def _refresh_regular_fact(
    root_descriptor: int,
    fact: _EntryFact,
    directory_facts: dict[tuple[str, ...], _EntryFact],
) -> _EntryFact:
    parent_descriptor = root_descriptor
    parent_owned = False
    file_descriptor = None
    try:
        parent_descriptor, parent_owned = _open_directory_path(
            root_descriptor, fact.components[:-1], directory_facts
        )
        try:
            refreshed_metadata = os.stat(
                fact.components[-1],
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except (NotImplementedError, TypeError):
            raise InventoryError("secure-open-unavailable") from None
        except OSError as error:
            if _unavailable(error):
                raise InventoryError("secure-open-unavailable") from None
            raise InventoryError("inventory-tree-changed") from None
        if not stat.S_ISREG(refreshed_metadata.st_mode):
            raise InventoryError("inventory-tree-changed")
        refreshed = _fact_from_metadata(fact.components, refreshed_metadata)
        if refreshed.kind != "regular":
            raise InventoryError("inventory-tree-changed")
        try:
            file_descriptor = os.open(
                fact.components[-1], _regular_flags(), dir_fd=parent_descriptor
            )
            first = os.fstat(file_descriptor)
            second = os.fstat(file_descriptor)
        except (NotImplementedError, TypeError):
            raise InventoryError("secure-open-unavailable") from None
        except OSError as error:
            if _unavailable(error):
                raise InventoryError("secure-open-unavailable") from None
            raise InventoryError("inventory-tree-changed") from None
        if (
            not _fact_matches_metadata(refreshed, first)
            or not _fact_matches_metadata(refreshed, second)
        ):
            raise InventoryError("inventory-tree-changed")
        return refreshed
    finally:
        _close(file_descriptor)
        if parent_owned:
            _close(parent_descriptor)


def _changed_draft(fact: _EntryFact) -> InventoryItemDraft:
    return InventoryItemDraft(
        depth=fact.depth,
        extension=safe_extension(fact.components[-1]),
        detected_type="unknown",
        size=fact.size,
        sha256=None,
        hash_status="not-applicable",
        issue_codes=("changed-during-read",),
    )


def _unreadable_draft(fact: _EntryFact) -> InventoryItemDraft:
    return InventoryItemDraft(
        depth=fact.depth,
        extension=safe_extension(fact.components[-1]),
        detected_type="unknown",
        size=fact.size,
        sha256=None,
        hash_status="not-applicable",
        issue_codes=("unreadable",),
    )


def _process_regular(
    root_descriptor: int,
    fact: _EntryFact,
    directory_facts: dict[tuple[str, ...], _EntryFact],
    limits: InventoryLimits,
    hashed_bytes: int,
) -> tuple[InventoryItemDraft, _EntryFact, int]:
    if fact.size is None:
        raise InventoryError("inventory-tree-changed")
    descriptor = _open_regular(root_descriptor, fact, directory_facts)
    if descriptor is None:
        return _unreadable_draft(fact), fact, hashed_bytes

    try:
        sample_failed = False
        sample_short = False
        try:
            sample, sample_short = _read_sample(
                descriptor, fact.size, limits.sample_bytes
            )
        except _SampleReadFailed:
            sample = b""
            sample_failed = True

        if sample_short or not _read_observation_is_stable(
            root_descriptor, descriptor, fact, directory_facts
        ):
            refreshed = _refresh_regular_fact(
                root_descriptor, fact, directory_facts
            )
            return _changed_draft(refreshed), refreshed, hashed_bytes

        extension = safe_extension(fact.components[-1])
        if sample_failed:
            return (
                InventoryItemDraft(
                    depth=fact.depth,
                    extension=extension,
                    detected_type="unknown",
                    size=fact.size,
                    sha256=None,
                    hash_status="not-applicable",
                    issue_codes=type_issue_codes(
                        extension, "unknown", sample_failed=True
                    ),
                ),
                fact,
                hashed_bytes,
            )

        detected_type = detect_type(sample)
        detected_issues = type_issue_codes(extension, detected_type)
        if fact.size > limits.max_hash_file_bytes:
            return (
                InventoryItemDraft(
                    depth=fact.depth,
                    extension=extension,
                    detected_type=detected_type,
                    size=fact.size,
                    sha256=None,
                    hash_status="skipped-too-large",
                    issue_codes=detected_issues + ("hash-skipped-too-large",),
                ),
                fact,
                hashed_bytes,
            )
        if hashed_bytes + fact.size > limits.max_hash_total_bytes:
            return (
                InventoryItemDraft(
                    depth=fact.depth,
                    extension=extension,
                    detected_type=detected_type,
                    size=fact.size,
                    sha256=None,
                    hash_status="budget-exhausted",
                    issue_codes=detected_issues + ("hash-budget-exhausted",),
                ),
                fact,
                hashed_bytes,
            )

        reserved_hashed_bytes = hashed_bytes + fact.size
        hash_failed = False
        hash_short = False
        try:
            digest, hash_short = _stream_hash(descriptor, fact.size)
        except _HashReadFailed:
            digest = None
            hash_failed = True

        if hash_short or not _read_observation_is_stable(
            root_descriptor, descriptor, fact, directory_facts
        ):
            refreshed = _refresh_regular_fact(
                root_descriptor, fact, directory_facts
            )
            return _changed_draft(refreshed), refreshed, reserved_hashed_bytes
        if hash_failed or digest is None:
            return _unreadable_draft(fact), fact, reserved_hashed_bytes
        return (
            InventoryItemDraft(
                depth=fact.depth,
                extension=extension,
                detected_type=detected_type,
                size=fact.size,
                sha256=digest,
                hash_status="computed",
                issue_codes=detected_issues,
            ),
            fact,
            reserved_hashed_bytes,
        )
    finally:
        _close(descriptor)


def _minimal_draft(fact: _EntryFact) -> InventoryItemDraft:
    issue = "symlink" if fact.kind == "symlink" else "special-file"
    return InventoryItemDraft(
        depth=fact.depth,
        extension="unknown",
        detected_type="unknown",
        size=None,
        sha256=None,
        hash_status="not-applicable",
        issue_codes=(issue,),
    )


def _revalidate_tree(
    root_descriptor: int,
    source_components: tuple[str, ...],
    root_fact: _EntryFact,
    authoritative: tuple[_EntryFact, ...],
    limits: InventoryLimits,
) -> None:
    final_facts = _enumerate_tree(root_descriptor, limits)
    if final_facts != authoritative:
        raise InventoryError("inventory-tree-changed")
    reopened = None
    try:
        reopened = _open_root_components(source_components, initial=False)
        reopened_metadata = os.fstat(reopened)
        retained_metadata = os.fstat(root_descriptor)
    except InventoryError:
        raise
    except OSError:
        raise InventoryError("inventory-tree-changed") from None
    finally:
        _close(reopened)
    if (
        root_fact.kind != "directory"
        or not _fact_matches_metadata(root_fact, reopened_metadata)
        or not _fact_matches_metadata(root_fact, retained_metadata)
    ):
        raise InventoryError("inventory-tree-changed")
    post_reopen_facts = _enumerate_tree(root_descriptor, limits)
    if post_reopen_facts != authoritative:
        raise InventoryError("inventory-tree-changed")


def _canonical_result_bytes(result: InventoryResult) -> bytes:
    return (
        json.dumps(
            result.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ).encode("utf-8")
        + b"\n"
    )


def _bounded_limits(limits: InventoryLimits) -> InventoryLimits:
    """Permit lower test/runtime bounds without allowing hard-limit relaxation."""
    return InventoryLimits(
        max_depth=min(limits.max_depth, DEFAULT_LIMITS.max_depth),
        max_directories=min(
            limits.max_directories, DEFAULT_LIMITS.max_directories
        ),
        max_regular_files=min(
            limits.max_regular_files, DEFAULT_LIMITS.max_regular_files
        ),
        max_items=min(limits.max_items, DEFAULT_LIMITS.max_items),
        max_entries=min(limits.max_entries, DEFAULT_LIMITS.max_entries),
        sample_bytes=min(limits.sample_bytes, DEFAULT_LIMITS.sample_bytes),
        max_hash_file_bytes=min(
            limits.max_hash_file_bytes, DEFAULT_LIMITS.max_hash_file_bytes
        ),
        max_hash_total_bytes=min(
            limits.max_hash_total_bytes, DEFAULT_LIMITS.max_hash_total_bytes
        ),
        max_json_bytes=min(limits.max_json_bytes, DEFAULT_LIMITS.max_json_bytes),
    )


def _update_observation_digest(digest, value: bytes) -> None:
    digest.update(len(value).to_bytes(8, "big"))
    digest.update(value)


def _observation_id(
    root_fact: _EntryFact,
    authoritative_facts: tuple[_EntryFact, ...],
) -> str:
    digest = hashlib.sha256()
    _update_observation_digest(digest, b"ctv-inventory-observation-v1")
    facts = (root_fact,) + authoritative_facts
    _update_observation_digest(digest, str(len(facts)).encode("ascii"))
    for fact in facts:
        _update_observation_digest(digest, fact.private_sort_key)
        _update_observation_digest(digest, fact.kind.encode("ascii"))
        for value in (
            fact.device,
            fact.inode,
            fact.mode,
            fact.size,
            fact.modified_ns,
            fact.changed_ns,
        ):
            encoded = b"none" if value is None else str(value).encode("ascii")
            _update_observation_digest(digest, encoded)
    return f"observation-{digest.hexdigest()}"


def _create_inventory_observation(
    source_root: Path, *, limits: InventoryLimits = DEFAULT_LIMITS
) -> InventoryObservation:
    _require_secure_open()
    if not isinstance(limits, InventoryLimits):
        raise TypeError("limits must be InventoryLimits")
    limits = _bounded_limits(limits)
    source_components = _normalize_source(source_root)
    root_descriptor = None
    try:
        root_descriptor = _open_root_components(source_components, initial=True)
        try:
            root_metadata = os.fstat(root_descriptor)
        except OSError:
            raise InventoryError("source-root-unsafe") from None
        if not stat.S_ISDIR(root_metadata.st_mode):
            raise InventoryError("source-root-unsafe")
        root_fact = _fact_from_metadata((), root_metadata)

        initial_facts = _enumerate_tree(root_descriptor, limits)
        authoritative = list(initial_facts)
        positions = {
            fact.components: index for index, fact in enumerate(authoritative)
        }
        directory_facts = _directory_fact_map(initial_facts)
        drafts: list[InventoryItemDraft] = []
        hashed_bytes = 0

        for fact in initial_facts:
            if fact.kind == "directory":
                continue
            if fact.kind in {"symlink", "special"}:
                drafts.append(_minimal_draft(fact))
                continue
            draft, final_fact, hashed_bytes = _process_regular(
                root_descriptor,
                fact,
                directory_facts,
                limits,
                hashed_bytes,
            )
            authoritative[positions[fact.components]] = final_fact
            drafts.append(draft)

        authoritative_facts = tuple(authoritative)
        items = assign_evidence_and_duplicate_ids(tuple(drafts))
        issue_count = sum(len(item.issue_codes) for item in items)
        totals = InventoryTotals(
            regular_files=sum(item.size is not None for item in items),
            directories=sum(
                fact.kind == "directory" for fact in authoritative_facts
            ),
            issues=issue_count,
            total_bytes=sum(item.size or 0 for item in items),
        )
        result = InventoryResult(
            inventory_version="1.0",
            inventory_status=(
                "complete-with-issues" if issue_count else "complete"
            ),
            totals=totals,
            items=items,
        )
        if len(_canonical_result_bytes(result)) > limits.max_json_bytes:
            raise InventoryError("inventory-output-too-large")

        item_facts = tuple(
            fact for fact in authoritative_facts if fact.kind != "directory"
        )
        if len(item_facts) != len(items):
            raise InventoryError("inventory-tree-changed")
        sources = tuple(
            ObservedInventorySource(
                evidence_id=item.evidence_id,
                extension=item.extension,
                detected_type=item.detected_type,
                size=item.size,
                hash_status=item.hash_status,
                issue_codes=tuple(item.issue_codes),
            )
            for item in items
        )
        evidence_facts = {
            item.evidence_id: fact for item, fact in zip(items, item_facts)
        }
        state = _ObservationState(
            root_descriptor=root_descriptor,
            source_components=source_components,
            root_fact=root_fact,
            authoritative_facts=authoritative_facts,
            directory_facts=_directory_fact_map(authoritative_facts),
            evidence_facts=evidence_facts,
            limits=limits,
        )
        observation = _new_inventory_observation(
            result,
            _observation_id(root_fact, authoritative_facts),
            sources,
        )
        _register_observation(observation, state)
        root_descriptor = None
        return observation
    except InventoryError:
        raise
    except OSError:
        raise InventoryError("inventory-tree-changed") from None
    finally:
        _close(root_descriptor)


@contextmanager
def open_inventory_observation(
    source_root: Path, *, limits: InventoryLimits = DEFAULT_LIMITS
) -> Iterator[InventoryObservation]:
    """Retain one secure inventory observation until final tree validation."""
    observation = _create_inventory_observation(source_root, limits=limits)
    try:
        yield observation
    finally:
        try:
            state = _observation_state(observation)
            root_descriptor = state.root_descriptor
            if root_descriptor is None:
                raise RuntimeError("inventory observation is closed")
            _revalidate_tree(
                root_descriptor,
                state.source_components,
                state.root_fact,
                state.authoritative_facts,
                state.limits,
            )
        finally:
            _release_observation(observation)


def inventory_source(
    source_root: Path, *, limits: InventoryLimits = DEFAULT_LIMITS
) -> InventoryResult:
    """Inventory one explicit source root without exposing private source names."""
    with open_inventory_observation(source_root, limits=limits) as observation:
        return observation.result
