import errno
import hashlib
import os
from pathlib import Path
import stat
import threading

import pytest

import ctv_package_transaction as transaction_module
from ctv_inventory import open_inventory_observation
from ctv_package_transaction import (
    OutputParent,
    PackageCollisionError,
    PackageTransactionError,
)


def _chain(source: Path):
    with open_inventory_observation(source) as observation:
        return observation.directory_identity_chain()


def _assert_error(code, operation, *, private_path=None):
    with pytest.raises(PackageTransactionError) as raised:
        operation()
    assert raised.value.code == code
    assert str(raised.value) == code
    if private_path is not None:
        assert str(private_path) not in str(raised.value)
    return raised.value


@pytest.mark.parametrize("kind", ["missing", "file", "symlink", "fifo"])
def test_output_parent_open_rejects_unsafe_boundaries(tmp_path, kind):
    output = tmp_path / "private-output"
    if kind == "file":
        output.write_bytes(b"not a directory")
    elif kind == "symlink":
        target = tmp_path / "actual-output"
        target.mkdir()
        output.symlink_to(target, target_is_directory=True)
    elif kind == "fifo":
        os.mkfifo(output)

    expected = "output-root-missing" if kind == "missing" else "output-root-unsafe"
    _assert_error(expected, lambda: OutputParent.open(output), private_path=output)


def test_output_parent_initial_descriptor_failure_is_fixed_and_private(
    tmp_path, monkeypatch
):
    output = tmp_path / "private-output"
    output.mkdir()

    def fail_open(*_args, **_kwargs):
        raise OSError(errno.EIO, "private open diagnostic")

    monkeypatch.setattr(os, "open", fail_open)
    error = _assert_error(
        "secure-output-unavailable",
        lambda: OutputParent.open(output),
        private_path=output,
    )
    assert "diagnostic" not in str(error)


def test_output_parent_root_open_error_is_fixed_and_private(tmp_path, monkeypatch):
    output = tmp_path / "private-output"
    output.mkdir()
    real_flags = transaction_module._directory_flags()

    def fail_root_open(path, flags, *args, **kwargs):
        if path == os.sep and not kwargs:
            raise OSError(errno.EIO, "private root diagnostic")
        raise AssertionError("no later component may open")

    monkeypatch.setattr(transaction_module, "_directory_flags", lambda: real_flags)
    monkeypatch.setattr(os, "open", fail_root_open)
    error = _assert_error(
        "output-root-unsafe", lambda: OutputParent.open(output), private_path=output
    )
    assert "diagnostic" not in str(error)


def test_output_parent_rejects_source_overlap_in_either_direction(tmp_path):
    source = tmp_path / "source"
    nested_output = source / "nested-output"
    nested_output.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()

    with open_inventory_observation(source) as observation:
        source_chain = observation.directory_identity_chain()
        with OutputParent.open(nested_output) as output:
            _assert_error(
                "source-output-overlap",
                lambda: output.require_disjoint(source_chain),
            )

    nested_source = outside / "nested-source"
    nested_source.mkdir()
    with open_inventory_observation(nested_source) as observation:
        with OutputParent.open(outside) as output:
            _assert_error(
                "source-output-overlap",
                lambda: output.require_disjoint(
                    observation.directory_identity_chain()
                ),
            )


def test_output_capability_survives_lexical_component_swap(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    output = tmp_path / "output"
    output.mkdir()
    moved = tmp_path / "retained-output"

    with OutputParent.open(output) as capability:
        output.rename(moved)
        output.mkdir()
        capability.require_disjoint(_chain(source))
        with capability.create_staging() as staging:
            staging.write_bytes("input.pdf", b"one")
            retained_name = staging.staging_name
            assert (moved / retained_name / "input.pdf").read_bytes() == b"one"
            assert list(output.iterdir()) == []
        assert not (moved / retained_name).exists()
        assert list(output.iterdir()) == []


def test_staging_writes_exact_modes_nested_evidence_and_portable_tree_digest(
    tmp_path,
):
    output = tmp_path / "output"
    output.mkdir(mode=0o755)
    with OutputParent.open(output) as capability:
        with capability.create_staging() as staging:
            first = staging.write_bytes("input.pdf", b"pdf")
            second = staging.write_bytes("evidence/evidence-0001.png", b"png")
            staging.write_bytes("case-manifest.json", b"{}\n")
            reader, failure = staging.open_reader()
            assert failure is None
            assert reader is not None
            try:
                tree, failure = reader.snapshot_tree(
                    {
                        "case-manifest.json",
                        "input.pdf",
                        "evidence/evidence-0001.png",
                    },
                    max_bytes_by_path={
                        "case-manifest.json": 16,
                        "input.pdf": 16,
                        "evidence/evidence-0001.png": 16,
                    },
                    max_total_bytes=48,
                )
            finally:
                reader.close()

            root = output / staging.staging_name
            expected_lines = b"".join(
                f"{hashlib.sha256(content).hexdigest()}  {path}\n".encode()
                for path, content in sorted(
                    {
                        "case-manifest.json": b"{}\n",
                        "evidence/evidence-0001.png": b"png",
                        "input.pdf": b"pdf",
                    }.items()
                )
            )
            assert failure is None
            assert tree.tree_sha256 == hashlib.sha256(expected_lines).hexdigest()
            assert first.sha256 == hashlib.sha256(b"pdf").hexdigest()
            assert second.size == 3
            assert stat.S_IMODE(root.stat().st_mode) == 0o700
            assert stat.S_IMODE((root / "evidence").stat().st_mode) == 0o700
            assert stat.S_IMODE((root / "input.pdf").stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "mutation",
    ["root-mode", "evidence-mode", "file-mode", "identical-hardlink"],
)
def test_staging_publication_state_rejects_metadata_or_identity_mutation(
    tmp_path, mutation
):
    output = tmp_path / "output"
    output.mkdir()
    external = tmp_path / "identical-input.pdf"
    with OutputParent.open(output) as capability:
        staging = capability.create_staging()
        staging.__enter__()
        try:
            staging.write_bytes("input.pdf", b"same bytes")
            staging.write_bytes("evidence/evidence-0001.png", b"png")
            required = {"input.pdf", "evidence/evidence-0001.png"}
            baseline = staging.snapshot_publication_state(required)
            assert baseline == staging.snapshot_publication_state(required)
            root = output / staging.staging_name
            if mutation == "root-mode":
                root.chmod(0o755)
            elif mutation == "evidence-mode":
                (root / "evidence").chmod(0o755)
            elif mutation == "file-mode":
                (root / "input.pdf").chmod(0o666)
            else:
                external.write_bytes(b"same bytes")
                (root / "input.pdf").unlink()
                os.link(external, root / "input.pdf")

            _assert_error(
                "package-staging-changed",
                lambda: staging.snapshot_publication_state(required),
            )
        finally:
            try:
                staging.__exit__(None, None, None)
            except PackageTransactionError:
                pass

    leftovers = list(output.glob(".ctv-staging-*"))
    if mutation == "identical-hardlink":
        assert len(leftovers) == 1
        replacement = leftovers[0] / "input.pdf"
        assert replacement.read_bytes() == b"same bytes"
        replacement.unlink()
        leftovers[0].rmdir()
    else:
        assert leftovers == []


@pytest.mark.parametrize(
    "path",
    ["", ".", "../input.pdf", "/input.pdf", "nested/file.bin", "evidence/x/y"],
)
def test_staging_rejects_non_allowlisted_or_unsafe_paths(tmp_path, path):
    output = tmp_path / "output"
    output.mkdir()
    with OutputParent.open(output) as capability:
        with capability.create_staging() as staging:
            _assert_error("package-path-unsafe", lambda: staging.write_bytes(path, b"x"))


def test_staging_charges_aggregate_before_writing(tmp_path, monkeypatch):
    output = tmp_path / "output"
    output.mkdir()
    monkeypatch.setattr(transaction_module, "MAX_PACKAGE_BYTES", 4)
    writes = []
    real_write = os.write

    def tracked_write(descriptor, content):
        writes.append(bytes(content))
        return real_write(descriptor, content)

    monkeypatch.setattr(os, "write", tracked_write)
    with OutputParent.open(output) as capability:
        with capability.create_staging() as staging:
            staging.write_bytes("input.pdf", b"1234")
            before = len(writes)
            _assert_error(
                "package-aggregate-over-limit",
                lambda: staging.write_bytes("assignments.json", b"5"),
            )
            assert len(writes) == before


def test_staging_rejects_zero_progress_and_cleans_only_its_temporary(tmp_path, monkeypatch):
    output = tmp_path / "output"
    output.mkdir()
    real_write = os.write
    invoked = False

    def zero_once(descriptor, content):
        nonlocal invoked
        if not invoked:
            invoked = True
            return 0
        return real_write(descriptor, content)

    with OutputParent.open(output) as capability:
        with capability.create_staging() as staging:
            monkeypatch.setattr(os, "write", zero_once)
            _assert_error(
                "package-write-failed",
                lambda: staging.write_bytes("input.pdf", b"content"),
            )
            root = output / staging.staging_name
            assert list(root.iterdir()) == []


def test_staging_completes_partial_writes_without_changing_bytes(tmp_path, monkeypatch):
    output = tmp_path / "output"
    output.mkdir()
    real_write = os.write
    calls = 0

    def partial_write(descriptor, content):
        nonlocal calls
        calls += 1
        return real_write(descriptor, content[:2])

    with OutputParent.open(output) as capability:
        with capability.create_staging() as staging:
            monkeypatch.setattr(os, "write", partial_write)
            receipt = staging.write_bytes("input.pdf", b"partial-content")
            assert (
                output / staging.staging_name / "input.pdf"
            ).read_bytes() == b"partial-content"
            assert receipt.sha256 == hashlib.sha256(b"partial-content").hexdigest()

    assert calls > 1


def test_staging_retries_fresh_temporary_name_collision(tmp_path, monkeypatch):
    output = tmp_path / "output"
    output.mkdir()
    with OutputParent.open(output) as capability:
        with capability.create_staging() as staging:
            root = output / staging.staging_name
            collision = root / ".tmp-collision"
            collision.write_bytes(b"keep")
            names = iter(("collision", "fresh"))
            monkeypatch.setattr(
                transaction_module.secrets, "token_hex", lambda _size: next(names)
            )
            staging.write_bytes("input.pdf", b"content")
            assert collision.read_bytes() == b"keep"
            collision.unlink()


def test_staging_write_fsync_failure_is_private_and_does_not_install_file(
    tmp_path, monkeypatch
):
    output = tmp_path / "private-output"
    output.mkdir()
    real_fsync = os.fsync
    failed = False

    def fail_file_fsync(descriptor):
        nonlocal failed
        metadata = os.fstat(descriptor)
        if stat.S_ISREG(metadata.st_mode) and not failed:
            failed = True
            raise OSError(errno.EIO, "private diagnostic")
        return real_fsync(descriptor)

    with OutputParent.open(output) as capability:
        with capability.create_staging() as staging:
            monkeypatch.setattr(os, "fsync", fail_file_fsync)
            error = _assert_error(
                "package-write-failed",
                lambda: staging.write_bytes("input.pdf", b"content"),
                private_path=output,
            )
            assert "diagnostic" not in str(error)
            assert list((output / staging.staging_name).iterdir()) == []


def test_directory_fsync_failure_after_install_still_cleans_installed_file(
    tmp_path, monkeypatch
):
    output = tmp_path / "output"
    output.mkdir()
    real_fsync = os.fsync
    failed = False

    def fail_first_directory_fsync(descriptor):
        nonlocal failed
        metadata = os.fstat(descriptor)
        if stat.S_ISDIR(metadata.st_mode) and not failed:
            failed = True
            raise OSError(errno.EIO, "private directory diagnostic")
        return real_fsync(descriptor)

    with OutputParent.open(output) as capability:
        with capability.create_staging() as staging:
            monkeypatch.setattr(os, "fsync", fail_first_directory_fsync)
            _assert_error(
                "package-write-failed",
                lambda: staging.write_bytes("input.pdf", b"content"),
            )
            assert list((output / staging.staging_name).iterdir()) == []

    assert list(output.iterdir()) == []


def test_staging_creation_failure_is_fixed_private_and_leaves_no_child(
    tmp_path, monkeypatch
):
    output = tmp_path / "private-output"
    output.mkdir()

    def fail_fchmod(_descriptor, _mode):
        raise OSError(errno.EIO, "private chmod diagnostic")

    with OutputParent.open(output) as capability:
        monkeypatch.setattr(os, "fchmod", fail_fchmod)
        error = _assert_error(
            "package-staging-create-failed",
            capability.create_staging,
            private_path=output,
        )

    assert "diagnostic" not in str(error)
    assert list(output.iterdir()) == []


@pytest.mark.parametrize(
    "path,boundary",
    [
        ("input.pdf", "fchmod"),
        ("input.pdf", "fstat"),
        ("evidence/evidence-0001.png", "fchmod"),
        ("evidence/evidence-0001.png", "fstat"),
    ],
)
def test_staging_early_file_setup_failure_preserves_error_and_cleans_owned_objects(
    tmp_path, monkeypatch, path, boundary
):
    output = tmp_path / "private-output"
    output.mkdir()
    real_fchmod = os.fchmod
    real_fstat = os.fstat

    with OutputParent.open(output) as capability:
        with capability.create_staging() as staging:
            staging_fd = staging._staging_fd
            failed = False

            def should_fail(descriptor):
                metadata = real_fstat(descriptor)
                if path.startswith("evidence/"):
                    return stat.S_ISDIR(metadata.st_mode) and descriptor != staging_fd
                return stat.S_ISREG(metadata.st_mode)

            def fail_target_fchmod(descriptor, mode):
                nonlocal failed
                if not failed and should_fail(descriptor):
                    failed = True
                    raise OSError(errno.EIO, "private setup diagnostic")
                return real_fchmod(descriptor, mode)

            def fail_target_fstat(descriptor):
                nonlocal failed
                metadata = real_fstat(descriptor)
                if not failed and should_fail(descriptor):
                    failed = True
                    raise OSError(errno.EIO, "private setup diagnostic")
                return metadata

            monkeypatch.setattr(
                os,
                "fchmod" if boundary == "fchmod" else "fstat",
                fail_target_fchmod if boundary == "fchmod" else fail_target_fstat,
            )
            error = _assert_error(
                "package-write-failed",
                lambda: staging.write_bytes(path, b"content"),
                private_path=output,
            )
            assert "diagnostic" not in str(error)

    assert list(output.iterdir()) == []


def test_temporary_name_swap_after_open_never_deletes_foreign_replacement(
    tmp_path, monkeypatch
):
    output = tmp_path / "output"
    output.mkdir()
    real_stat = os.stat
    swapped = False

    with OutputParent.open(output) as capability:
        with capability.create_staging() as staging:
            staging_fd = staging._staging_fd
            temporary = ".tmp-raced"
            moved = ".moved-run-owned-temp"
            monkeypatch.setattr(
                transaction_module.StagingTransaction,
                "_temporary_name",
                staticmethod(lambda: temporary),
            )

            def swap_before_named_stat(path, *args, **kwargs):
                nonlocal swapped
                if (
                    not swapped
                    and path == temporary
                    and kwargs.get("dir_fd") == staging_fd
                ):
                    swapped = True
                    os.rename(
                        temporary,
                        moved,
                        src_dir_fd=staging_fd,
                        dst_dir_fd=staging_fd,
                    )
                    descriptor = os.open(
                        temporary,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                        0o600,
                        dir_fd=staging_fd,
                    )
                    try:
                        os.write(descriptor, b"foreign")
                    finally:
                        os.close(descriptor)
                return real_stat(path, *args, **kwargs)

            monkeypatch.setattr(os, "stat", swap_before_named_stat)
            _assert_error(
                "package-write-failed",
                lambda: staging.write_bytes("input.pdf", b"run-owned"),
            )
            root = output / staging.staging_name
            assert (root / temporary).read_bytes() == b"foreign"
            assert (root / moved).read_bytes() == b""
            (root / temporary).unlink()
            (root / moved).unlink()


def test_evidence_name_swap_before_open_never_chmods_foreign_replacement(
    tmp_path, monkeypatch
):
    output = tmp_path / "output"
    output.mkdir()
    real_open = os.open
    directory_flags = transaction_module._directory_flags()
    swapped = False

    with OutputParent.open(output) as capability:
        with capability.create_staging() as staging:
            staging_fd = staging._staging_fd
            moved = ".moved-run-owned-evidence"

            def swap_before_evidence_open(path, flags, *args, **kwargs):
                nonlocal swapped
                if (
                    not swapped
                    and path == "evidence"
                    and kwargs.get("dir_fd") == staging_fd
                ):
                    swapped = True
                    os.rename(
                        "evidence",
                        moved,
                        src_dir_fd=staging_fd,
                        dst_dir_fd=staging_fd,
                    )
                    os.mkdir("evidence", 0o755, dir_fd=staging_fd)
                return real_open(path, flags, *args, **kwargs)

            monkeypatch.setattr(os, "open", swap_before_evidence_open)
            monkeypatch.setattr(
                transaction_module, "_directory_flags", lambda: directory_flags
            )
            _assert_error(
                "package-write-failed",
                lambda: staging.write_bytes(
                    "evidence/evidence-0001.png", b"content"
                ),
            )
            root = output / staging.staging_name
            replacement = root / "evidence"
            assert stat.S_IMODE(replacement.stat().st_mode) == 0o755
            assert (root / moved).is_dir()
            replacement.rmdir()
            (root / moved).rmdir()


def test_deterministic_final_collision_is_checked_before_staging(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    final_name = "ctv-package-0123456789abcdef01234567"
    (output / final_name).mkdir()
    with OutputParent.open(output) as capability:
        with pytest.raises(PackageCollisionError, match="^package-output-collision$"):
            capability.require_final_absent(final_name)
        assert [entry.name for entry in output.iterdir()] == [final_name]


@pytest.mark.skipif(os.uname().sysname != "Darwin", reason="Darwin renameatx_np contract")
def test_real_darwin_publication_is_atomic_no_replace_and_fsyncs_parent(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    final_name = "ctv-package-0123456789abcdef01234567"
    with OutputParent.open(output) as capability:
        with capability.create_staging() as first:
            first.write_bytes("input.pdf", b"first")
            first.publish(final_name)
        assert (output / final_name / "input.pdf").read_bytes() == b"first"

        with capability.create_staging() as competing:
            competing.write_bytes("input.pdf", b"second")
            with pytest.raises(
                PackageCollisionError, match="^package-output-collision$"
            ):
                competing.publish(final_name)

        assert (output / final_name / "input.pdf").read_bytes() == b"first"


@pytest.mark.skipif(os.uname().sysname != "Darwin", reason="Darwin renameatx_np contract")
def test_parent_fsync_failure_after_atomic_publish_keeps_prepared_package(
    tmp_path, monkeypatch
):
    output = tmp_path / "output"
    output.mkdir()
    final_name = "ctv-package-3123456789abcdef01234567"
    parent_identity = (output.stat().st_dev, output.stat().st_ino)
    real_fsync = os.fsync
    failed = False

    def fail_parent_fsync_after_rename(descriptor):
        nonlocal failed
        metadata = os.fstat(descriptor)
        if (
            not failed
            and stat.S_ISDIR(metadata.st_mode)
            and (metadata.st_dev, metadata.st_ino) == parent_identity
            and (output / final_name).is_dir()
        ):
            failed = True
            raise OSError(errno.EIO, "private post-rename sync diagnostic")
        return real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", fail_parent_fsync_after_rename)
    with OutputParent.open(output) as capability:
        with capability.create_staging() as staging:
            staging.write_bytes("input.pdf", b"complete")
            staging.publish(final_name)
            assert repr(staging) == "StagingTransaction(published=True)"

        with capability.create_staging() as retry:
            retry.write_bytes("input.pdf", b"replacement")
            with pytest.raises(
                PackageCollisionError, match="^package-output-collision$"
            ):
                retry.publish(final_name)

    assert failed is True
    assert (output / final_name / "input.pdf").read_bytes() == b"complete"
    assert not list(output.glob(".ctv-staging-*"))


@pytest.mark.skipif(os.uname().sysname != "Darwin", reason="Darwin renameatx_np contract")
def test_real_darwin_publish_closes_creation_after_absence_precheck(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    final_name = "ctv-package-1123456789abcdef01234567"
    with OutputParent.open(output) as capability:
        capability.require_final_absent(final_name)
        with capability.create_staging() as staging:
            staging.write_bytes("input.pdf", b"ours")
            competing = output / final_name
            competing.mkdir()
            (competing / "owned.bin").write_bytes(b"competing")
            with pytest.raises(
                PackageCollisionError, match="^package-output-collision$"
            ):
                staging.publish(final_name)

    assert (output / final_name / "owned.bin").read_bytes() == b"competing"
    assert not (output / final_name / "input.pdf").exists()


@pytest.mark.skipif(os.uname().sysname != "Darwin", reason="Darwin renameatx_np contract")
def test_real_darwin_staged_file_install_does_not_replace_competing_destination(
    tmp_path, monkeypatch
):
    output = tmp_path / "output"
    output.mkdir()
    real_operation = transaction_module._load_renameatx_np()
    assert real_operation is not None
    raced = False

    def install_competitor_then_rename(
        source_fd, source_name, destination_fd, destination_name, flags
    ):
        nonlocal raced
        if not raced:
            raced = True
            descriptor = os.open(
                os.fsdecode(destination_name),
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=destination_fd,
            )
            try:
                os.write(descriptor, b"competitor")
            finally:
                os.close(descriptor)
        return real_operation(
            source_fd, source_name, destination_fd, destination_name, flags
        )

    monkeypatch.setattr(
        transaction_module, "_load_renameatx_np", lambda: install_competitor_then_rename
    )
    with OutputParent.open(output) as capability:
        with capability.create_staging() as staging:
            _assert_error(
                "package-path-collision",
                lambda: staging.write_bytes("input.pdf", b"ours"),
            )
            competitor = output / staging.staging_name / "input.pdf"
            assert competitor.read_bytes() == b"competitor"
            competitor.unlink()


def test_unavailable_atomic_staged_file_install_fails_closed(tmp_path, monkeypatch):
    output = tmp_path / "output"
    output.mkdir()
    monkeypatch.setattr(transaction_module, "_load_renameatx_np", lambda: None)
    with OutputParent.open(output) as capability:
        with capability.create_staging() as staging:
            _assert_error(
                "atomic-install-unavailable",
                lambda: staging.write_bytes("input.pdf", b"content"),
            )
            assert list((output / staging.staging_name).iterdir()) == []


@pytest.mark.skipif(os.uname().sysname != "Darwin", reason="Darwin renameatx_np contract")
def test_real_darwin_publication_has_no_partial_final_visibility(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    final_name = "ctv-package-2123456789abcdef01234567"
    partial = []
    ready = threading.Event()

    def observe():
        final = output / final_name
        ready.set()
        while True:
            if final.exists():
                paths = sorted(path.name for path in final.iterdir())
                if paths != ["case-manifest.json", "input.pdf"]:
                    partial.append(paths)
                return

    with OutputParent.open(output) as capability:
        with capability.create_staging() as staging:
            staging.write_bytes("input.pdf", b"pdf")
            staging.write_bytes("case-manifest.json", b"{}\n")
            observer = threading.Thread(target=observe)
            observer.start()
            assert ready.wait(timeout=2)
            staging.publish(final_name)
            observer.join(timeout=2)

    assert not observer.is_alive()
    assert partial == []
    assert sorted(path.name for path in (output / final_name).iterdir()) == [
        "case-manifest.json",
        "input.pdf",
    ]


def test_unavailable_atomic_publish_fails_closed_without_final_name(
    tmp_path, monkeypatch
):
    output = tmp_path / "output"
    output.mkdir()
    final_name = "ctv-package-0123456789abcdef01234567"
    with OutputParent.open(output) as capability:
        with capability.create_staging() as staging:
            staging.write_bytes("input.pdf", b"content")
            monkeypatch.setattr(transaction_module, "_load_renameatx_np", lambda: None)
            _assert_error("atomic-publish-unavailable", lambda: staging.publish(final_name))
        assert not (output / final_name).exists()


def test_cleanup_ignores_replaced_staging_name_and_crash_like_sibling(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    crash_like = output / ".ctv-staging-crash-leftover"
    crash_like.mkdir()
    (crash_like / "keep.bin").write_bytes(b"keep")

    with OutputParent.open(output) as capability:
        staging = capability.create_staging()
        staging.__enter__()
        original = output / staging.staging_name
        moved = output / ".moved-owned-staging"
        original.rename(moved)
        original.mkdir()
        (original / "replacement.bin").write_bytes(b"replacement")
        staging.__exit__(RuntimeError, RuntimeError("failure"), None)

    assert (original / "replacement.bin").read_bytes() == b"replacement"
    assert (moved).is_dir()
    assert (crash_like / "keep.bin").read_bytes() == b"keep"
