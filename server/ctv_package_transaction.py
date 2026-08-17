"""Capability-owned staging and atomic publication for CTV v2 packages."""

from __future__ import annotations

import ctypes
import errno
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import secrets
import stat

from intake_contract_v2 import MAX_PACKAGE_BYTES
from intake_package_validator import _PackageReader


RENAME_EXCL = 0x00000004
_MAX_DIRECTORY_DEPTH = 256
_CREATE_ATTEMPTS = 32
_FINAL_NAME = re.compile(r"^ctv-package-[0-9a-f]{24}$")
_EVIDENCE_PATH = re.compile(r"^evidence/evidence-[0-9]{4}\.(?:png|xlsx)$")
_TOP_LEVEL_PATHS = frozenset(
    {
        "case-manifest.json",
        "input.pdf",
        "roster.xlsx",
        "assignments.json",
        "exceptions.json",
        "validation-report.json",
    }
)
_UNAVAILABLE_ERRNOS = frozenset(
    value
    for value in (
        getattr(errno, "ENOSYS", None),
        getattr(errno, "ENOTSUP", None),
        getattr(errno, "EOPNOTSUPP", None),
    )
    if value is not None
)


class PackageTransactionError(RuntimeError):
    """A fixed, path-free transaction failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class PackageCollisionError(PackageTransactionError):
    """The deterministic final package name already exists."""

    def __init__(self) -> None:
        super().__init__("package-output-collision")


@dataclass(frozen=True)
class WrittenFile:
    path: str
    size: int
    sha256: str


def _directory_flags() -> int:
    required = ("O_DIRECTORY", "O_NOFOLLOW", "O_CLOEXEC")
    if not all(hasattr(os, name) for name in required) or os.open not in os.supports_dir_fd:
        raise PackageTransactionError("secure-output-unavailable")
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _write_flags() -> int:
    if not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd:
        raise PackageTransactionError("secure-output-unavailable")
    return os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _close(descriptor: int | None) -> None:
    if descriptor is None:
        return
    try:
        os.close(descriptor)
    except OSError:
        pass


def _normalize_components(path: Path) -> tuple[str, ...]:
    try:
        raw = os.fspath(path)
    except TypeError:
        raise PackageTransactionError("output-root-unsafe") from None
    if type(raw) is not str or not raw or "\x00" in raw:
        raise PackageTransactionError("output-root-unsafe")
    lexical = raw.split(os.sep)
    if raw.startswith(os.sep):
        lexical = lexical[1:]
    if any(component in {"", ".", ".."} for component in lexical):
        raise PackageTransactionError("output-root-unsafe")
    try:
        absolute = os.path.abspath(raw)
    except (OSError, ValueError):
        raise PackageTransactionError("output-root-unsafe") from None
    if absolute == os.sep:
        return ()
    if not absolute.startswith(os.sep):
        raise PackageTransactionError("output-root-unsafe")
    components = tuple(absolute[len(os.sep) :].split(os.sep))
    if any(component in {"", ".", ".."} for component in components):
        raise PackageTransactionError("output-root-unsafe")
    return components


def _open_output_components(components: tuple[str, ...]) -> int:
    current = None
    try:
        current = os.open(os.sep, _directory_flags())
        for index, component in enumerate(components):
            next_descriptor = None
            try:
                next_descriptor = os.open(component, _directory_flags(), dir_fd=current)
                metadata = os.fstat(next_descriptor)
                if not stat.S_ISDIR(metadata.st_mode):
                    raise OSError(errno.ENOTDIR, "not directory")
            except PackageTransactionError:
                _close(next_descriptor)
                raise
            except (NotImplementedError, TypeError):
                _close(next_descriptor)
                raise PackageTransactionError("secure-output-unavailable") from None
            except OSError as error:
                _close(next_descriptor)
                if index == len(components) - 1 and error.errno == errno.ENOENT:
                    raise PackageTransactionError("output-root-missing") from None
                if error.errno in _UNAVAILABLE_ERRNOS:
                    raise PackageTransactionError("secure-output-unavailable") from None
                raise PackageTransactionError("output-root-unsafe") from None
            _close(current)
            current = next_descriptor
        result = current
        current = None
        return result
    except PackageTransactionError:
        raise
    except (NotImplementedError, TypeError):
        raise PackageTransactionError("secure-output-unavailable") from None
    except OSError as error:
        if error.errno in _UNAVAILABLE_ERRNOS:
            raise PackageTransactionError("secure-output-unavailable") from None
        raise PackageTransactionError("output-root-unsafe") from None
    finally:
        _close(current)


def _identity_chain(descriptor: int) -> tuple[tuple[int, int], ...]:
    current = None
    try:
        current = os.dup(descriptor)
        chain: list[tuple[int, int]] = []
        for _depth in range(_MAX_DIRECTORY_DEPTH):
            metadata = os.fstat(current)
            if not stat.S_ISDIR(metadata.st_mode):
                raise PackageTransactionError("output-root-unsafe")
            identity = (metadata.st_dev, metadata.st_ino)
            chain.append(identity)
            parent = os.open("..", _directory_flags(), dir_fd=current)
            parent_metadata = os.fstat(parent)
            if (parent_metadata.st_dev, parent_metadata.st_ino) == identity:
                _close(parent)
                return tuple(chain)
            _close(current)
            current = parent
        raise PackageTransactionError("output-root-unsafe")
    except PackageTransactionError:
        raise
    except (OSError, NotImplementedError, TypeError):
        raise PackageTransactionError("output-root-unsafe") from None
    finally:
        _close(current)


def _safe_final_name(name: str) -> bool:
    return type(name) is str and _FINAL_NAME.fullmatch(name) is not None


def _safe_package_path(path: str) -> bool:
    return type(path) is str and (
        path in _TOP_LEVEL_PATHS or _EVIDENCE_PATH.fullmatch(path) is not None
    )


def _stat_at(parent_fd: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except (NotImplementedError, TypeError):
        raise PackageTransactionError("secure-output-unavailable") from None
    except OSError:
        raise PackageTransactionError("output-root-unsafe") from None


def _load_renameatx_np():
    try:
        operation = ctypes.CDLL(None, use_errno=True).renameatx_np
    except (AttributeError, OSError):
        return None
    operation.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    operation.restype = ctypes.c_int
    return operation


class OutputParent:
    """One retained output directory descriptor; never exposes its path."""

    __slots__ = ("_descriptor", "_identity", "_closed")

    def __init__(self, *_args, **_kwargs) -> None:
        raise TypeError("output parents are created by OutputParent.open")

    @classmethod
    def open(cls, path: Path) -> "OutputParent":
        components = _normalize_components(path)
        descriptor = _open_output_components(components)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISDIR(metadata.st_mode):
                raise PackageTransactionError("output-root-unsafe")
            result = object.__new__(cls)
            result._descriptor = descriptor
            result._identity = (metadata.st_dev, metadata.st_ino)
            result._closed = False
            descriptor = None
            return result
        finally:
            _close(descriptor)

    def __enter__(self) -> "OutputParent":
        self._require_open()
        return self

    def __exit__(self, _type, _value, _traceback) -> bool:
        self.close()
        return False

    def __repr__(self) -> str:
        return "OutputParent(open=True)" if not self._closed else "OutputParent(open=False)"

    def _require_open(self) -> int:
        if self._closed or self._descriptor is None:
            raise PackageTransactionError("output-root-closed")
        try:
            metadata = os.fstat(self._descriptor)
        except OSError:
            raise PackageTransactionError("output-root-closed") from None
        if not stat.S_ISDIR(metadata.st_mode) or (
            metadata.st_dev,
            metadata.st_ino,
        ) != self._identity:
            raise PackageTransactionError("output-root-changed")
        return self._descriptor

    @property
    def descriptor(self) -> int:
        return self._require_open()

    def close(self) -> None:
        if self._closed:
            return
        descriptor = self._descriptor
        self._descriptor = None
        self._closed = True
        _close(descriptor)

    def require_disjoint(
        self, source_identity_chain: tuple[tuple[int, int], ...]
    ) -> None:
        descriptor = self._require_open()
        if (
            type(source_identity_chain) is not tuple
            or not source_identity_chain
            or any(
                type(identity) is not tuple
                or len(identity) != 2
                or any(type(value) is not int for value in identity)
                for identity in source_identity_chain
            )
        ):
            raise PackageTransactionError("source-output-identity-invalid")
        output_chain = _identity_chain(descriptor)
        source_root = source_identity_chain[0]
        output_root = output_chain[0]
        if source_root in output_chain or output_root in source_identity_chain:
            raise PackageTransactionError("source-output-overlap")

    def require_final_absent(self, final_name: str) -> None:
        descriptor = self._require_open()
        if not _safe_final_name(final_name):
            raise PackageTransactionError("package-final-name-invalid")
        if _stat_at(descriptor, final_name) is not None:
            raise PackageCollisionError()

    def create_staging(self) -> "StagingTransaction":
        descriptor = self._require_open()
        for _attempt in range(_CREATE_ATTEMPTS):
            name = ".ctv-staging-" + secrets.token_hex(16)
            try:
                os.mkdir(name, 0o700, dir_fd=descriptor)
            except FileExistsError:
                continue
            except (NotImplementedError, TypeError):
                raise PackageTransactionError("secure-output-unavailable") from None
            except OSError:
                raise PackageTransactionError("package-staging-create-failed") from None
            staging_fd = None
            parent_fd = None
            try:
                staging_fd = os.open(name, _directory_flags(), dir_fd=descriptor)
                os.fchmod(staging_fd, 0o700)
                metadata = os.fstat(staging_fd)
                parent_fd = os.dup(descriptor)
                return StagingTransaction._create(
                    parent_fd,
                    name,
                    staging_fd,
                    (metadata.st_dev, metadata.st_ino),
                )
            except PackageTransactionError:
                _close(parent_fd)
                _close(staging_fd)
                try:
                    os.rmdir(name, dir_fd=descriptor)
                except OSError:
                    pass
                raise
            except (OSError, NotImplementedError, TypeError):
                _close(parent_fd)
                _close(staging_fd)
                try:
                    os.rmdir(name, dir_fd=descriptor)
                except OSError:
                    pass
                raise PackageTransactionError(
                    "package-staging-create-failed"
                ) from None
        raise PackageTransactionError("package-staging-collision")


class StagingTransaction:
    """One private staging inode and only the files written by this run."""

    __slots__ = (
        "_parent_fd",
        "_staging_name",
        "_staging_fd",
        "_identity",
        "_evidence_fd",
        "_evidence_identity",
        "_written",
        "_charged_bytes",
        "_published",
        "_closed",
    )

    def __init__(self, *_args, **_kwargs) -> None:
        raise TypeError("staging transactions are created by OutputParent")

    @classmethod
    def _create(
        cls,
        parent_fd: int,
        staging_name: str,
        staging_fd: int,
        identity: tuple[int, int],
    ) -> "StagingTransaction":
        result = object.__new__(cls)
        result._parent_fd = parent_fd
        result._staging_name = staging_name
        result._staging_fd = staging_fd
        result._identity = identity
        result._evidence_fd = None
        result._evidence_identity = None
        result._written = {}
        result._charged_bytes = 0
        result._published = False
        result._closed = False
        return result

    def __enter__(self) -> "StagingTransaction":
        self._require_identity()
        return self

    def __exit__(self, _type, _value, _traceback) -> bool:
        self.close()
        return False

    def __repr__(self) -> str:
        return (
            "StagingTransaction(published=True)"
            if self._published
            else "StagingTransaction(published=False)"
        )

    @property
    def staging_name(self) -> str:
        return self._staging_name

    @property
    def identity(self) -> tuple[int, int]:
        return self._identity

    def _require_identity(self) -> None:
        if self._closed or self._staging_fd is None or self._parent_fd is None:
            raise PackageTransactionError("package-staging-closed")
        try:
            retained = os.fstat(self._staging_fd)
            named = os.stat(
                self._staging_name,
                dir_fd=self._parent_fd,
                follow_symlinks=False,
            )
        except (OSError, NotImplementedError, TypeError):
            raise PackageTransactionError("package-staging-changed") from None
        if (
            not stat.S_ISDIR(retained.st_mode)
            or not stat.S_ISDIR(named.st_mode)
            or (retained.st_dev, retained.st_ino) != self._identity
            or (named.st_dev, named.st_ino) != self._identity
        ):
            raise PackageTransactionError("package-staging-changed")

    def _directory_for_path(self, path: str) -> tuple[int, str]:
        if path in _TOP_LEVEL_PATHS:
            return self._staging_fd, path
        if _EVIDENCE_PATH.fullmatch(path) is None:
            raise PackageTransactionError("package-path-unsafe")
        if self._evidence_fd is None:
            try:
                os.mkdir("evidence", 0o700, dir_fd=self._staging_fd)
                evidence_fd = os.open("evidence", _directory_flags(), dir_fd=self._staging_fd)
                os.fchmod(evidence_fd, 0o700)
                metadata = os.fstat(evidence_fd)
            except (OSError, NotImplementedError, TypeError):
                _close(locals().get("evidence_fd"))
                raise PackageTransactionError("package-write-failed") from None
            self._evidence_fd = evidence_fd
            self._evidence_identity = (metadata.st_dev, metadata.st_ino)
            try:
                os.fsync(self._staging_fd)
            except OSError:
                raise PackageTransactionError("package-write-failed") from None
        return self._evidence_fd, path.split("/", 1)[1]

    @staticmethod
    def _temporary_name() -> str:
        return ".tmp-" + secrets.token_hex(16)

    def write_bytes(self, path: str, content: bytes) -> WrittenFile:
        self._require_identity()
        if not _safe_package_path(path):
            raise PackageTransactionError("package-path-unsafe")
        if type(content) is not bytes:
            raise TypeError("package content must be bytes")
        if path in self._written:
            raise PackageTransactionError("package-path-collision")
        next_total = self._charged_bytes + len(content)
        if next_total > MAX_PACKAGE_BYTES:
            self._charged_bytes = next_total
            raise PackageTransactionError("package-aggregate-over-limit")
        self._charged_bytes = next_total
        directory_fd, final_component = self._directory_for_path(path)
        temporary = None
        temporary_identity = None
        file_descriptor = None
        try:
            for _attempt in range(_CREATE_ATTEMPTS):
                temporary = self._temporary_name()
                try:
                    file_descriptor = os.open(
                        temporary,
                        _write_flags(),
                        0o600,
                        dir_fd=directory_fd,
                    )
                    break
                except FileExistsError:
                    temporary = None
                    continue
            if file_descriptor is None or temporary is None:
                raise PackageTransactionError("package-temporary-collision")
            os.fchmod(file_descriptor, 0o600)
            metadata = os.fstat(file_descriptor)
            temporary_identity = (metadata.st_dev, metadata.st_ino)
            view = memoryview(content)
            offset = 0
            while offset < len(view):
                written = os.write(file_descriptor, view[offset:])
                if type(written) is not int or written <= 0:
                    raise PackageTransactionError("package-write-failed")
                offset += written
            os.fsync(file_descriptor)
            metadata = os.fstat(file_descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != len(content):
                raise PackageTransactionError("package-write-failed")
            _close(file_descriptor)
            file_descriptor = None
            if _stat_at(directory_fd, final_component) is not None:
                raise PackageTransactionError("package-path-collision")
            os.rename(
                temporary,
                final_component,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
            )
            temporary = None
            installed = os.stat(
                final_component, dir_fd=directory_fd, follow_symlinks=False
            )
            installed_identity = (installed.st_dev, installed.st_ino)
            if installed_identity != temporary_identity or not stat.S_ISREG(installed.st_mode):
                raise PackageTransactionError("package-write-failed")
            self._written[path] = installed_identity
            os.fsync(directory_fd)
            return WrittenFile(
                path=path,
                size=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
            )
        except PackageTransactionError:
            installed_identity = self._written.pop(path, None)
            if installed_identity is not None:
                self._unlink_if_identity(
                    directory_fd, final_component, installed_identity
                )
            elif temporary is None and temporary_identity is not None:
                self._unlink_if_identity(
                    directory_fd, final_component, temporary_identity
                )
            raise
        except (OSError, NotImplementedError, TypeError):
            installed_identity = self._written.pop(path, None)
            if installed_identity is not None:
                self._unlink_if_identity(
                    directory_fd, final_component, installed_identity
                )
            elif temporary is None and temporary_identity is not None:
                self._unlink_if_identity(
                    directory_fd, final_component, temporary_identity
                )
            raise PackageTransactionError("package-write-failed") from None
        finally:
            _close(file_descriptor)
            if temporary is not None and temporary_identity is not None:
                self._unlink_if_identity(directory_fd, temporary, temporary_identity)

    @staticmethod
    def _unlink_if_identity(
        parent_fd: int, name: str, expected_identity: tuple[int, int]
    ) -> None:
        try:
            metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if (metadata.st_dev, metadata.st_ino) == expected_identity:
                os.unlink(name, dir_fd=parent_fd)
        except OSError:
            pass

    def open_reader(self):
        self._require_identity()
        return _PackageReader.open_at(
            self._parent_fd,
            self._staging_name,
            expected_identity=self._identity,
        )

    def publish(self, final_name: str) -> None:
        self._require_identity()
        if not _safe_final_name(final_name):
            raise PackageTransactionError("package-final-name-invalid")
        operation = _load_renameatx_np()
        if operation is None:
            raise PackageTransactionError("atomic-publish-unavailable")
        ctypes.set_errno(0)
        result = operation(
            self._parent_fd,
            self._staging_name.encode("utf-8"),
            self._parent_fd,
            final_name.encode("utf-8"),
            RENAME_EXCL,
        )
        if result != 0:
            error_number = ctypes.get_errno()
            if error_number in {errno.EEXIST, getattr(errno, "ENOTEMPTY", errno.EEXIST)}:
                raise PackageCollisionError()
            if error_number in _UNAVAILABLE_ERRNOS:
                raise PackageTransactionError("atomic-publish-unavailable")
            raise PackageTransactionError("package-publish-failed")
        self._published = True
        try:
            os.fsync(self._parent_fd)
        except OSError:
            raise PackageTransactionError("package-publication-sync-failed") from None

    def _cleanup_written(self) -> None:
        for path, identity in reversed(tuple(self._written.items())):
            if path.startswith("evidence/"):
                if self._evidence_fd is not None:
                    self._unlink_if_identity(
                        self._evidence_fd, path.split("/", 1)[1], identity
                    )
            else:
                self._unlink_if_identity(self._staging_fd, path, identity)
        if self._evidence_fd is not None:
            _close(self._evidence_fd)
            self._evidence_fd = None
            try:
                metadata = os.stat(
                    "evidence", dir_fd=self._staging_fd, follow_symlinks=False
                )
                if (metadata.st_dev, metadata.st_ino) == self._evidence_identity:
                    os.rmdir("evidence", dir_fd=self._staging_fd)
            except FileNotFoundError:
                pass
            except OSError:
                raise PackageTransactionError("package-cleanup-failed") from None

    def close(self) -> None:
        if self._closed:
            return
        cleanup_error = None
        if not self._published:
            try:
                named = os.stat(
                    self._staging_name,
                    dir_fd=self._parent_fd,
                    follow_symlinks=False,
                )
                name_matches = (
                    stat.S_ISDIR(named.st_mode)
                    and (named.st_dev, named.st_ino) == self._identity
                )
            except OSError:
                name_matches = False
            if name_matches:
                try:
                    self._cleanup_written()
                    os.rmdir(self._staging_name, dir_fd=self._parent_fd)
                    os.fsync(self._parent_fd)
                except PackageTransactionError as error:
                    cleanup_error = error
                except OSError:
                    cleanup_error = PackageTransactionError("package-cleanup-failed")
        _close(self._evidence_fd)
        _close(self._staging_fd)
        _close(self._parent_fd)
        self._evidence_fd = None
        self._staging_fd = None
        self._parent_fd = None
        self._closed = True
        if cleanup_error is not None:
            raise cleanup_error
