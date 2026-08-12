import errno
import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path


_PIN_LIMIT = 16 * 1024
_FILE_LIMIT = 16 * 1024 * 1024
_TREE_LIMIT = 64 * 1024 * 1024
_FILE_COUNT_LIMIT = 1_000
_DIRECTORY_COUNT_LIMIT = 1_000
_DIRECTORY_ENTRY_LIMIT = _FILE_COUNT_LIMIT + _DIRECTORY_COUNT_LIMIT
_DEPTH_LIMIT = 32
_READ_CHUNK = 64 * 1024
_PIN_FIELDS = frozenset(
    {"sourceCommit", "contractTreeSha256", "compatibilityTarget"}
)
_SHA1 = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_UNAVAILABLE_ERRNOS = frozenset(
    value
    for value in (
        getattr(errno, "ENOSYS", None),
        getattr(errno, "ENOTSUP", None),
        getattr(errno, "EOPNOTSUPP", None),
    )
    if value is not None
)


@dataclass(frozen=True)
class ContractPin:
    source_commit: str
    contract_tree_sha256: str
    compatibility_target: str


@dataclass(frozen=True)
class ContractVerification:
    pin: ContractPin
    actual_tree_sha256: str
    verified: bool


class ContractPinError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class _DuplicatePinKey(ValueError):
    pass


@dataclass
class _HashState:
    file_count: int = 0
    directory_count: int = 0
    aggregate_bytes: int = 0
    directory_snapshots: dict[bytes, tuple["_DirectoryEntry", ...]] = field(
        default_factory=dict
    )


@dataclass(frozen=True)
class _DirectoryEntry:
    name: str
    encoded_name: bytes
    kind: str
    device: int
    inode: int
    size: int | None
    modified_ns: int
    changed_ns: int


@dataclass
class _RevalidationFrame:
    descriptor: int
    relative_path: bytes
    depth: int
    owned: bool
    directories: tuple[_DirectoryEntry, ...] | None = None
    next_directory: int = 0


def _require_secure_open() -> None:
    supported = (
        hasattr(os, "O_NOFOLLOW")
        and hasattr(os, "O_DIRECTORY")
        and os.open in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.stat in os.supports_follow_symlinks
        and os.scandir in os.supports_fd
    )
    if not supported:
        raise ContractPinError("secure-open-unavailable")


def _open_flags(*, directory: bool) -> int:
    flags = os.O_RDONLY | os.O_NOFOLLOW
    flags |= getattr(os, "O_CLOEXEC", 0)
    if directory:
        flags |= os.O_DIRECTORY
    return flags


def _translate_open_error(
    error: OSError, *, missing_code: str, invalid_code: str
) -> ContractPinError:
    if error.errno in _UNAVAILABLE_ERRNOS:
        return ContractPinError("secure-open-unavailable")
    if error.errno == errno.ENOENT:
        return ContractPinError(missing_code)
    return ContractPinError(invalid_code)


def _open_root(path: Path, *, missing_code: str, invalid_code: str) -> int:
    try:
        return os.open(os.fspath(path), _open_flags(directory=True))
    except (NotImplementedError, TypeError):
        raise ContractPinError("secure-open-unavailable") from None
    except OSError as error:
        raise _translate_open_error(
            error, missing_code=missing_code, invalid_code=invalid_code
        ) from None


def _open_at(
    parent_fd: int,
    name: str,
    *,
    directory: bool,
    missing_code: str,
    invalid_code: str,
) -> int:
    try:
        return os.open(name, _open_flags(directory=directory), dir_fd=parent_fd)
    except (NotImplementedError, TypeError):
        raise ContractPinError("secure-open-unavailable") from None
    except OSError as error:
        raise _translate_open_error(
            error, missing_code=missing_code, invalid_code=invalid_code
        ) from None


def _close(fd: int | None) -> None:
    if fd is not None:
        try:
            os.close(fd)
        except OSError:
            pass


def _open_intake_directory(
    root_fd: int, *, missing_code: str, invalid_code: str
) -> int:
    contracts_fd = intake_fd = None
    try:
        contracts_fd = _open_at(
            root_fd,
            "contracts",
            directory=True,
            missing_code=missing_code,
            invalid_code=invalid_code,
        )
        intake_fd = _open_at(
            contracts_fd,
            "ctv-intake",
            directory=True,
            missing_code=missing_code,
            invalid_code=invalid_code,
        )
        result = intake_fd
        intake_fd = None
        return result
    finally:
        _close(intake_fd)
        _close(contracts_fd)


def _read_pin_bytes(pin_fd: int) -> bytes:
    try:
        before = os.fstat(pin_fd)
        if not stat.S_ISREG(before.st_mode):
            raise ContractPinError("contract-pin-invalid")
        if before.st_size > _PIN_LIMIT:
            raise ContractPinError("contract-pin-too-large")

        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(pin_fd, min(_READ_CHUNK, _PIN_LIMIT + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > _PIN_LIMIT:
                raise ContractPinError("contract-pin-too-large")

        after = os.fstat(pin_fd)
    except ContractPinError:
        raise
    except OSError:
        raise ContractPinError("contract-pin-invalid") from None

    if (
        not stat.S_ISREG(after.st_mode)
        or (before.st_dev, before.st_ino, before.st_size)
        != (after.st_dev, after.st_ino, after.st_size)
        or total != before.st_size
    ):
        raise ContractPinError("contract-pin-invalid")
    return b"".join(chunks)


def _pin_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicatePinKey
        result[key] = value
    return result


def _parse_contract_pin(raw_pin: bytes) -> ContractPin:
    try:
        payload = json.loads(raw_pin.decode("utf-8"), object_pairs_hook=_pin_object)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise ContractPinError("contract-pin-invalid") from None

    if not isinstance(payload, dict) or frozenset(payload) != _PIN_FIELDS:
        raise ContractPinError("contract-pin-invalid")

    source_commit = payload["sourceCommit"]
    tree_sha256 = payload["contractTreeSha256"]
    compatibility_target = payload["compatibilityTarget"]
    if (
        not isinstance(source_commit, str)
        or _SHA1.fullmatch(source_commit) is None
        or not isinstance(tree_sha256, str)
        or _SHA256.fullmatch(tree_sha256) is None
        or compatibility_target != "ctv-intake-v1"
    ):
        raise ContractPinError("contract-pin-invalid")

    return ContractPin(
        source_commit=source_commit,
        contract_tree_sha256=tree_sha256,
        compatibility_target=compatibility_target,
    )


def _load_contract_pin_from_intake(intake_fd: int) -> ContractPin:
    pin_fd = None
    try:
        pin_fd = _open_at(
            intake_fd,
            "PIN.json",
            directory=False,
            missing_code="contract-pin-missing",
            invalid_code="contract-pin-invalid",
        )
        raw_pin = _read_pin_bytes(pin_fd)
    finally:
        _close(pin_fd)
    return _parse_contract_pin(raw_pin)


def load_contract_pin(repository_root: Path) -> ContractPin:
    _require_secure_open()
    root_fd = intake_fd = None
    try:
        root_fd = _open_root(
            Path(repository_root),
            missing_code="contract-pin-missing",
            invalid_code="contract-pin-invalid",
        )
        intake_fd = _open_intake_directory(
            root_fd,
            missing_code="contract-pin-missing",
            invalid_code="contract-pin-invalid",
        )
        return _load_contract_pin_from_intake(intake_fd)
    finally:
        _close(intake_fd)
        _close(root_fd)


def _entry_kind(mode: int) -> str:
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISREG(mode):
        return "file"
    return "unsafe"


def _snapshot_directory(directory_fd: int) -> tuple[_DirectoryEntry, ...]:
    try:
        entries = []
        with os.scandir(directory_fd) as iterator:
            for entry in iterator:
                if len(entries) >= _DIRECTORY_ENTRY_LIMIT:
                    raise ContractPinError("contract-entry-count-exceeded")
                name = entry.name
                try:
                    encoded_name = name.encode("utf-8")
                except UnicodeEncodeError:
                    raise ContractPinError("contract-entry-unsafe") from None
                entry_stat = entry.stat(follow_symlinks=False)
                kind = _entry_kind(entry_stat.st_mode)
                entries.append(
                    _DirectoryEntry(
                        name=name,
                        encoded_name=encoded_name,
                        kind=kind,
                        device=entry_stat.st_dev,
                        inode=entry_stat.st_ino,
                        size=entry_stat.st_size if kind == "file" else None,
                        modified_ns=entry_stat.st_mtime_ns,
                        changed_ns=entry_stat.st_ctime_ns,
                    )
                )
        return tuple(sorted(entries, key=lambda entry: entry.encoded_name))
    except ContractPinError:
        raise
    except FileNotFoundError:
        raise ContractPinError("contract-tree-changed") from None
    except (NotImplementedError, TypeError):
        raise ContractPinError("secure-open-unavailable") from None
    except OSError as error:
        if error.errno in _UNAVAILABLE_ERRNOS:
            raise ContractPinError("secure-open-unavailable") from None
        raise ContractPinError("contract-entry-unsafe") from None


def _open_snapshotted_entry(
    directory_fd: int, entry: _DirectoryEntry, *, directory: bool
) -> int:
    descriptor = None
    try:
        descriptor = os.open(
            entry.name,
            _open_flags(directory=directory),
            dir_fd=directory_fd,
        )
        opened = os.fstat(descriptor)
    except (NotImplementedError, TypeError):
        _close(descriptor)
        raise ContractPinError("secure-open-unavailable") from None
    except OSError as error:
        _close(descriptor)
        if error.errno in _UNAVAILABLE_ERRNOS:
            raise ContractPinError("secure-open-unavailable") from None
        raise ContractPinError("contract-tree-changed") from None

    opened_kind = _entry_kind(opened.st_mode)
    opened_size = opened.st_size if opened_kind == "file" else None
    if (
        opened_kind != entry.kind
        or (
            opened.st_dev,
            opened.st_ino,
            opened_size,
            opened.st_mtime_ns,
            opened.st_ctime_ns,
        )
        != (
            entry.device,
            entry.inode,
            entry.size,
            entry.modified_ns,
            entry.changed_ns,
        )
    ):
        _close(descriptor)
        raise ContractPinError("contract-tree-changed")
    return descriptor


def _hash_file(
    file_fd: int,
    entry: _DirectoryEntry,
    relative_path: bytes,
    state: _HashState,
) -> bytes:
    state.file_count += 1
    if state.file_count > _FILE_COUNT_LIMIT:
        raise ContractPinError("contract-file-count-exceeded")
    if entry.size is None or entry.size > _FILE_LIMIT:
        raise ContractPinError("contract-file-too-large")
    if state.aggregate_bytes + entry.size > _TREE_LIMIT:
        raise ContractPinError("contract-tree-too-large")

    try:
        before = os.fstat(file_fd)
        digest = hashlib.sha256()
        remaining = entry.size
        while remaining:
            chunk = os.read(file_fd, min(_READ_CHUNK, remaining))
            if not chunk:
                break
            digest.update(chunk)
            remaining -= len(chunk)
        after = os.fstat(file_fd)
    except OSError:
        raise ContractPinError("contract-tree-changed") from None

    stable_identity_and_size = (
        stat.S_ISREG(after.st_mode)
        and (before.st_dev, before.st_ino, before.st_size)
        == (after.st_dev, after.st_ino, after.st_size)
        == (entry.device, entry.inode, entry.size)
        and before.st_mtime_ns == after.st_mtime_ns
        and before.st_ctime_ns == after.st_ctime_ns
    )
    if remaining or not stable_identity_and_size:
        raise ContractPinError("contract-tree-changed")

    state.aggregate_bytes += entry.size
    return digest.hexdigest().encode("ascii") + b"  " + relative_path + b"\n"


def _walk_contract_tree(
    directory_fd: int,
    relative_parent: bytes,
    state: _HashState,
    lines: list[tuple[bytes, bytes]],
    depth: int = 0,
) -> None:
    if depth > _DEPTH_LIMIT:
        raise ContractPinError("contract-depth-exceeded")
    state.directory_count += 1
    if state.directory_count > _DIRECTORY_COUNT_LIMIT:
        raise ContractPinError("contract-directory-count-exceeded")

    before = _snapshot_directory(directory_fd)
    state.directory_snapshots[relative_parent] = before
    for entry in before:
        if entry.kind == "unsafe":
            raise ContractPinError("contract-entry-unsafe")
        relative_path = (
            entry.encoded_name
            if not relative_parent
            else relative_parent + b"/" + entry.encoded_name
        )
        if entry.kind == "directory":
            child_fd = _open_snapshotted_entry(directory_fd, entry, directory=True)
            try:
                _walk_contract_tree(
                    child_fd, relative_path, state, lines, depth=depth + 1
                )
            finally:
                _close(child_fd)
        else:
            file_fd = _open_snapshotted_entry(directory_fd, entry, directory=False)
            try:
                line = _hash_file(file_fd, entry, relative_path, state)
            finally:
                _close(file_fd)
            lines.append((relative_path, line))

    after = _snapshot_directory(directory_fd)
    if before != after:
        raise ContractPinError("contract-tree-changed")


def _revalidate_contract_tree(
    version_fd: int,
    expected_snapshots: dict[bytes, tuple[_DirectoryEntry, ...]],
) -> None:
    seen: set[bytes] = set()
    stack = [
        _RevalidationFrame(
            descriptor=version_fd,
            relative_path=b"",
            depth=0,
            owned=False,
        )
    ]
    try:
        while stack:
            frame = stack[-1]
            if frame.directories is None:
                if frame.depth > _DEPTH_LIMIT:
                    raise ContractPinError("contract-depth-exceeded")
                expected = expected_snapshots.get(frame.relative_path)
                if expected is None:
                    raise ContractPinError("contract-tree-changed")
                actual = _snapshot_directory(frame.descriptor)
                if actual != expected:
                    raise ContractPinError("contract-tree-changed")
                seen.add(frame.relative_path)
                frame.directories = tuple(
                    entry for entry in actual if entry.kind == "directory"
                )
                continue

            if frame.next_directory >= len(frame.directories):
                finished = stack.pop()
                if finished.owned:
                    _close(finished.descriptor)
                continue

            entry = frame.directories[frame.next_directory]
            frame.next_directory += 1
            relative_path = (
                entry.encoded_name
                if not frame.relative_path
                else frame.relative_path + b"/" + entry.encoded_name
            )
            child_fd = _open_snapshotted_entry(
                frame.descriptor, entry, directory=True
            )
            stack.append(
                _RevalidationFrame(
                    descriptor=child_fd,
                    relative_path=relative_path,
                    depth=frame.depth + 1,
                    owned=True,
                )
            )
    finally:
        for frame in reversed(stack):
            if frame.owned:
                _close(frame.descriptor)

    if seen != expected_snapshots.keys():
        raise ContractPinError("contract-tree-changed")


def _compute_contract_tree_from_intake(intake_fd: int) -> str:
    version_fd = _open_at(
        intake_fd,
        "v1",
        directory=True,
        missing_code="contract-entry-unsafe",
        invalid_code="contract-entry-unsafe",
    )
    try:
        lines: list[tuple[bytes, bytes]] = []
        state = _HashState()
        try:
            _walk_contract_tree(version_fd, b"", state, lines)
        except RecursionError:
            raise ContractPinError("contract-depth-exceeded") from None
        _revalidate_contract_tree(version_fd, state.directory_snapshots)
    finally:
        _close(version_fd)

    tree_bytes = b"".join(line for _, line in sorted(lines, key=lambda item: item[0]))
    return hashlib.sha256(tree_bytes).hexdigest()


def compute_contract_tree_sha256(version_root: Path) -> str:
    _require_secure_open()
    version_path = Path(version_root)
    if (
        version_path.name != "v1"
        or version_path.parent.name != "ctv-intake"
        or version_path.parent.parent.name != "contracts"
    ):
        raise ContractPinError("contract-entry-unsafe")

    repository_root = version_path.parent.parent.parent
    root_fd = intake_fd = None
    try:
        root_fd = _open_root(
            repository_root,
            missing_code="contract-entry-unsafe",
            invalid_code="contract-entry-unsafe",
        )
        intake_fd = _open_intake_directory(
            root_fd,
            missing_code="contract-entry-unsafe",
            invalid_code="contract-entry-unsafe",
        )
        return _compute_contract_tree_from_intake(intake_fd)
    finally:
        _close(intake_fd)
        _close(root_fd)


def verify_contract(repository_root: Path) -> ContractVerification:
    _require_secure_open()
    root = Path(repository_root)
    root_fd = intake_fd = None
    try:
        root_fd = _open_root(
            root,
            missing_code="contract-pin-missing",
            invalid_code="contract-pin-invalid",
        )
        intake_fd = _open_intake_directory(
            root_fd,
            missing_code="contract-pin-missing",
            invalid_code="contract-pin-invalid",
        )
        pin = _load_contract_pin_from_intake(intake_fd)
        actual_tree_sha256 = _compute_contract_tree_from_intake(intake_fd)
    finally:
        _close(intake_fd)
        _close(root_fd)

    return ContractVerification(
        pin=pin,
        actual_tree_sha256=actual_tree_sha256,
        verified=actual_tree_sha256 == pin.contract_tree_sha256,
    )
