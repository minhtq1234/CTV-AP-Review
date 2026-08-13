import builtins
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import stat
import sys
from types import SimpleNamespace

import pytest

import ctv_inventory as inventory_module
from ctv_inventory import InventoryError, inventory_source
from ctv_inventory_model import InventoryLimits


def _small_limits(**overrides):
    values = dict(
        max_depth=4,
        max_directories=8,
        max_regular_files=16,
        max_items=16,
        max_entries=24,
        sample_bytes=16 * 1024,
        max_hash_file_bytes=1024,
        max_hash_total_bytes=4096,
        max_json_bytes=64 * 1024,
    )
    values.update(overrides)
    return InventoryLimits(**values)


def _assert_inventory_error(expected, operation, *, private_path=None):
    with pytest.raises(InventoryError) as raised:
        operation()
    assert raised.value.code == expected
    assert str(raised.value) == expected
    assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", str(raised.value))
    if private_path is not None:
        assert str(private_path) not in str(raised.value)
    return raised.value


def _tree_snapshot(root):
    snapshot = []
    for current, directory_names, file_names in os.walk(root, followlinks=False):
        directory_names.sort()
        file_names.sort()
        current_path = Path(current)
        for name in (*directory_names, *file_names):
            path = current_path / name
            metadata = os.lstat(path)
            relative = os.path.relpath(path, root)
            content = path.read_bytes() if stat.S_ISREG(metadata.st_mode) else None
            link_target = os.readlink(path) if stat.S_ISLNK(metadata.st_mode) else None
            snapshot.append(
                (
                    relative,
                    stat.S_IFMT(metadata.st_mode),
                    stat.S_IMODE(metadata.st_mode),
                    metadata.st_size,
                    metadata.st_mtime_ns,
                    content,
                    link_target,
                )
            )
    return tuple(snapshot)


def _stat_copy(metadata, **overrides):
    values = {
        "st_dev": metadata.st_dev,
        "st_ino": metadata.st_ino,
        "st_mode": metadata.st_mode,
        "st_size": metadata.st_size,
        "st_mtime_ns": metadata.st_mtime_ns,
        "st_ctime_ns": metadata.st_ctime_ns,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _inject_one_read_metadata_mutation(monkeypatch, path, *, phase, field):
    target = path.stat()
    original_read = os.read
    original_fstat = os.fstat
    original_lseek = os.lseek
    state = {"phase": "sample", "inject": False, "returned": False}

    def tracked_read(descriptor, count):
        content = original_read(descriptor, count)
        opened = original_fstat(descriptor)
        if (opened.st_dev, opened.st_ino) == (target.st_dev, target.st_ino):
            if state["phase"] == phase:
                state["inject"] = True
        return content

    def tracked_lseek(descriptor, offset, whence):
        opened = original_fstat(descriptor)
        if (
            (opened.st_dev, opened.st_ino) == (target.st_dev, target.st_ino)
            and offset == 0
            and whence == os.SEEK_SET
        ):
            state["phase"] = "hash"
        return original_lseek(descriptor, offset, whence)

    def mutated_fstat(descriptor):
        metadata = original_fstat(descriptor)
        if (
            (metadata.st_dev, metadata.st_ino) == (target.st_dev, target.st_ino)
            and state["inject"]
            and not state["returned"]
        ):
            state["returned"] = True
            if field == "identity":
                return _stat_copy(metadata, st_ino=metadata.st_ino + 1)
            if field == "size":
                return _stat_copy(metadata, st_size=metadata.st_size + 1)
            if field == "time":
                return _stat_copy(metadata, st_mtime_ns=metadata.st_mtime_ns + 1)
            raise AssertionError(field)
        return metadata

    monkeypatch.setattr(os, "read", tracked_read)
    monkeypatch.setattr(os, "lseek", tracked_lseek)
    monkeypatch.setattr(os, "fstat", mutated_fstat)
    return state


def test_nested_files_are_deterministic_private_and_fully_hashed(tmp_path):
    source = tmp_path / "Khách hàng tuyệt mật"
    nested = source / "Tên người A"
    nested.mkdir(parents=True)
    first = source / "CCCD-012345678901.pdf"
    second = nested / "Bảng kê.xlsx"
    first.write_bytes(b"%PDF-1.7\nprivate")
    second.write_bytes(b"PK\x03\x04[Content_Types].xml xl/workbook.xml")

    one = inventory_source(source, limits=_small_limits())
    two = inventory_source(source, limits=_small_limits())

    assert one.to_dict() == two.to_dict()
    assert one.inventory_status == "complete"
    assert one.totals.regular_files == 2
    assert one.totals.directories == 1
    assert [item.evidence_id for item in one.items] == [
        "evidence-0001", "evidence-0002"
    ]
    serialized = json.dumps(one.to_dict(), ensure_ascii=False)
    for private in (str(tmp_path), source.name, nested.name, first.name, second.name):
        assert private not in serialized
    assert {item.detected_type for item in one.items} == {"pdf", "xlsx"}
    assert all(item.hash_status == "computed" for item in one.items)


def test_exact_duplicate_bytes_receive_one_group(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    content = b"%PDF-1.7\nsame"
    (source / "one.pdf").write_bytes(content)
    (source / "two.pdf").write_bytes(content)

    result = inventory_source(source, limits=_small_limits())

    assert [item.sha256 for item in result.items] == [
        hashlib.sha256(content).hexdigest(),
        hashlib.sha256(content).hexdigest(),
    ]
    assert {item.duplicate_group_id for item in result.items} == {
        "duplicate-0001"
    }


def test_symlink_is_minimal_and_target_is_never_read(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    target = tmp_path / "outside-private.pdf"
    target.write_bytes(b"%PDF-1.7\nsecret target")
    (source / "link-with-private.pdf").symlink_to(target)
    safe = source / "safe.pdf"
    safe.write_bytes(b"%PDF-1.7\nsafe")
    target_identity = (target.stat().st_dev, target.stat().st_ino)
    original_read = os.read

    def reject_target_read(descriptor, count):
        opened = os.fstat(descriptor)
        assert (opened.st_dev, opened.st_ino) != target_identity
        return original_read(descriptor, count)

    monkeypatch.setattr(os, "read", reject_target_read)

    result = inventory_source(source, limits=_small_limits())

    symlink = next(item for item in result.items if "symlink" in item.issue_codes)
    assert (symlink.extension, symlink.detected_type, symlink.size) == (
        "unknown", "unknown", None
    )
    assert symlink.sha256 is None
    assert symlink.hash_status == "not-applicable"
    assert symlink.duplicate_group_id is None
    assert result.totals.regular_files == 1
    assert result.inventory_status == "complete-with-issues"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are unavailable")
def test_fifo_and_unix_socket_are_special_without_blocking(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    os.mkfifo(source / "private-fifo.pdf")
    socket_boundary = source / "private-socket.xlsx"
    socket_boundary.write_bytes(b"boundary placeholder")
    original_stat = os.stat

    def expose_synthetic_socket_mode(path, *args, **kwargs):
        metadata = original_stat(path, *args, **kwargs)
        if path == socket_boundary.name and kwargs.get("dir_fd") is not None:
            return _stat_copy(
                metadata,
                st_mode=stat.S_IFSOCK | stat.S_IMODE(metadata.st_mode),
            )
        return metadata

    monkeypatch.setattr(os, "stat", expose_synthetic_socket_mode)
    monkeypatch.setattr(inventory_module, "_require_secure_open", lambda: None)

    result = inventory_source(source, limits=_small_limits())

    assert len(result.items) == 2
    for item in result.items:
        assert item.extension == "unknown"
        assert item.detected_type == "unknown"
        assert item.size is None
        assert item.hash_status == "not-applicable"
        assert item.issue_codes == ("special-file",)
    assert result.totals.issues == 2
    assert result.inventory_status == "complete-with-issues"


def test_unreadable_regular_file_retains_safe_known_facts(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    denied = source / "private-client.pdf"
    denied.write_bytes(b"%PDF-1.7\nprivate")
    sibling = source / "safe.zip"
    sibling.write_bytes(b"PK\x03\x04safe")
    original_open = os.open

    def deny_regular_open(path, flags, *args, **kwargs):
        if path == denied.name and kwargs.get("dir_fd") is not None:
            raise PermissionError("private path must not escape")
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", deny_regular_open)
    monkeypatch.setattr(inventory_module, "_require_secure_open", lambda: None)

    result = inventory_source(source, limits=_small_limits())

    unreadable = next(item for item in result.items if "unreadable" in item.issue_codes)
    assert unreadable.extension == ".pdf"
    assert unreadable.detected_type == "unknown"
    assert unreadable.size == len(b"%PDF-1.7\nprivate")
    assert unreadable.sha256 is None
    assert unreadable.hash_status == "not-applicable"
    assert unreadable.duplicate_group_id is None
    assert result.totals.regular_files == 2
    assert result.totals.total_bytes == denied.stat().st_size + sibling.stat().st_size
    assert result.inventory_status == "complete-with-issues"


def test_sample_read_failure_is_an_item_issue_with_no_digest(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    failed = source / "private.pdf"
    failed.write_bytes(b"%PDF-1.7\nprivate")
    target = (failed.stat().st_dev, failed.stat().st_ino)
    original_read = os.read

    def fail_target_read(descriptor, count):
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) == target:
            raise OSError("private read failure")
        return original_read(descriptor, count)

    monkeypatch.setattr(os, "read", fail_target_read)

    result = inventory_source(source, limits=_small_limits())

    item = result.items[0]
    assert item.extension == ".pdf"
    assert item.detected_type == "unknown"
    assert item.size == failed.stat().st_size
    assert item.sha256 is None
    assert item.hash_status == "not-applicable"
    assert item.issue_codes == ("type-detection-failed",)
    assert item.duplicate_group_id is None


def test_file_over_injected_limit_is_sampled_but_not_fully_hashed(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    content = b"%PDF-1.7\nprivate larger content"
    (source / "large.pdf").write_bytes(content)

    result = inventory_source(
        source,
        limits=_small_limits(sample_bytes=12, max_hash_file_bytes=8),
    )

    item = result.items[0]
    assert item.detected_type == "pdf"
    assert item.sha256 is None
    assert item.hash_status == "skipped-too-large"
    assert item.issue_codes == ("hash-skipped-too-large",)
    assert item.duplicate_group_id is None


def test_sorted_files_consume_aggregate_hash_budget_deterministically(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    first = b"%PDF-1.7"
    second = b"%PDF-1.6"
    (source / "z-last.pdf").write_bytes(second)
    (source / "a-first.pdf").write_bytes(first)

    result = inventory_source(
        source,
        limits=_small_limits(max_hash_file_bytes=64, max_hash_total_bytes=len(first)),
    )

    assert result.items[0].sha256 == hashlib.sha256(first).hexdigest()
    assert result.items[0].hash_status == "computed"
    assert result.items[1].sha256 is None
    assert result.items[1].hash_status == "budget-exhausted"
    assert result.items[1].issue_codes == ("hash-budget-exhausted",)
    assert result.items[1].duplicate_group_id is None
    assert result.totals.regular_files == 2
    assert result.totals.total_bytes == len(first) + len(second)
    assert result.totals.issues == 1
    assert result.inventory_status == "complete-with-issues"


def test_late_mutation_still_consumes_the_reserved_hash_budget(
    tmp_path, monkeypatch
):
    source = tmp_path / "source"
    source.mkdir()
    changed = source / "a-changed.bin"
    changed.write_bytes(b"12345678")
    (source / "b-later.bin").write_bytes(b"abcdefgh")
    _inject_one_read_metadata_mutation(
        monkeypatch, changed, phase="hash", field="time"
    )

    result = inventory_source(
        source,
        limits=_small_limits(
            sample_bytes=4,
            max_hash_file_bytes=8,
            max_hash_total_bytes=8,
        ),
    )

    assert result.items[0].issue_codes == ("changed-during-read",)
    assert result.items[0].hash_status == "not-applicable"
    assert result.items[1].issue_codes == ("hash-budget-exhausted",)
    assert result.items[1].hash_status == "budget-exhausted"
    assert result.items[1].sha256 is None


def test_partial_hash_read_failure_still_consumes_the_reserved_budget(
    tmp_path, monkeypatch
):
    source = tmp_path / "source"
    source.mkdir()
    failed = source / "a-failed.bin"
    failed.write_bytes(b"12345678")
    (source / "b-later.bin").write_bytes(b"abcdefgh")
    target = (failed.stat().st_dev, failed.stat().st_ino)
    original_read = os.read
    original_lseek = os.lseek
    phase = "sample"
    hash_reads = 0

    def track_hash_start(descriptor, offset, whence):
        nonlocal phase
        opened = os.fstat(descriptor)
        if (
            (opened.st_dev, opened.st_ino) == target
            and offset == 0
            and whence == os.SEEK_SET
        ):
            phase = "hash"
        return original_lseek(descriptor, offset, whence)

    def fail_after_partial_hash_read(descriptor, count):
        nonlocal hash_reads
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) == target and phase == "hash":
            hash_reads += 1
            if hash_reads == 1:
                return original_read(descriptor, min(count, 4))
            raise OSError("private hash read failure")
        return original_read(descriptor, count)

    monkeypatch.setattr(os, "lseek", track_hash_start)
    monkeypatch.setattr(os, "read", fail_after_partial_hash_read)

    result = inventory_source(
        source,
        limits=_small_limits(
            sample_bytes=4,
            max_hash_file_bytes=8,
            max_hash_total_bytes=8,
        ),
    )

    assert hash_reads == 2
    assert result.items[0].issue_codes == ("unreadable",)
    assert result.items[0].hash_status == "not-applicable"
    assert result.items[1].issue_codes == ("hash-budget-exhausted",)
    assert result.items[1].hash_status == "budget-exhausted"
    assert result.items[1].sha256 is None


def test_same_digest_with_different_sizes_never_forms_duplicate_group(
    tmp_path, monkeypatch
):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.bin").write_bytes(b"one")
    (source / "b.bin").write_bytes(b"different-size")

    class FixedDigest:
        def update(self, content):
            pass

        def hexdigest(self):
            return "a" * 64

    monkeypatch.setattr(inventory_module.hashlib, "sha256", FixedDigest)

    result = inventory_source(source, limits=_small_limits())

    assert {item.sha256 for item in result.items} == {"a" * 64}
    assert {item.size for item in result.items} == {3, 14}
    assert all(item.duplicate_group_id is None for item in result.items)


@pytest.mark.parametrize(
    ("root_kind", "expected"),
    [
        ("missing", "source-root-missing"),
        ("file", "source-root-unsafe"),
        ("symlink", "source-root-unsafe"),
        ("fifo", "source-root-unsafe"),
    ],
)
def test_invalid_source_roots_fail_with_opaque_stable_codes(
    tmp_path, root_kind, expected
):
    source = tmp_path / "private-root-012345678901"
    if root_kind == "file":
        source.write_bytes(b"private")
    elif root_kind == "symlink":
        target = tmp_path / "target"
        target.mkdir()
        source.symlink_to(target, target_is_directory=True)
    elif root_kind == "fifo":
        if not hasattr(os, "mkfifo"):
            pytest.skip("FIFOs are unavailable")
        os.mkfifo(source)

    _assert_inventory_error(
        expected,
        lambda: inventory_source(source, limits=_small_limits()),
        private_path=source,
    )


@pytest.mark.parametrize("private_input", ["", ".", "..", "source/../source"])
def test_empty_or_dot_source_components_are_rejected(
    tmp_path, monkeypatch, private_input
):
    (tmp_path / "source").mkdir()
    monkeypatch.chdir(tmp_path)

    _assert_inventory_error(
        "source-root-unsafe",
        lambda: inventory_source(private_input, limits=_small_limits()),
    )


@pytest.mark.parametrize("spelling", ["trailing", "repeated", "all-separator"])
def test_raw_empty_source_components_are_rejected(tmp_path, spelling):
    source = tmp_path / "source"
    source.mkdir()
    if spelling == "trailing":
        raw_source = f"{source}{os.sep}"
    elif spelling == "repeated":
        raw_source = f"{source.parent}{os.sep}{os.sep}{source.name}"
    else:
        raw_source = os.sep * 4

    _assert_inventory_error(
        "source-root-unsafe",
        lambda: inventory_source(raw_source, limits=_small_limits()),
    )


def test_path_caller_normalization_cannot_be_reconstructed_by_inventory(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    raw_spelling = f"{source}{os.sep}{os.sep}"
    caller_normalized = Path(raw_spelling)
    assert os.fspath(caller_normalized) == str(source)

    result = inventory_source(caller_normalized, limits=_small_limits())

    assert result.inventory_status == "complete"


def test_intermediate_source_symlink_is_rejected(tmp_path):
    actual_parent = tmp_path / "actual-parent"
    source = actual_parent / "source"
    source.mkdir(parents=True)
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(actual_parent, target_is_directory=True)

    _assert_inventory_error(
        "source-root-unsafe",
        lambda: inventory_source(linked_parent / "source", limits=_small_limits()),
        private_path=linked_parent,
    )


def test_replaced_selected_root_is_rejected_at_final_observation(
    tmp_path, monkeypatch
):
    source = tmp_path / "selected-private-root"
    source.mkdir()
    (source / "safe.pdf").write_bytes(b"%PDF-1.7\nsafe")
    moved = tmp_path / "moved-original"
    original_open = os.open
    source_component_opens = 0

    def replace_before_final_open(path, flags, *args, **kwargs):
        nonlocal source_component_opens
        if path == source.name and kwargs.get("dir_fd") is not None:
            source_component_opens += 1
            if source_component_opens == 2:
                source.rename(moved)
                source.mkdir()
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", replace_before_final_open)
    monkeypatch.setattr(inventory_module, "_require_secure_open", lambda: None)

    _assert_inventory_error(
        "inventory-tree-changed",
        lambda: inventory_source(source, limits=_small_limits()),
        private_path=source,
    )
    assert source_component_opens == 2


@pytest.mark.parametrize("primitive", ["O_NOFOLLOW", "O_DIRECTORY", "O_NONBLOCK", "O_CLOEXEC"])
def test_missing_secure_open_primitive_fails_closed(tmp_path, monkeypatch, primitive):
    source = tmp_path / "source"
    source.mkdir()
    monkeypatch.delattr(os, primitive)

    _assert_inventory_error(
        "secure-open-unavailable",
        lambda: inventory_source(source, limits=_small_limits()),
        private_path=source,
    )


def test_depth_limit_is_enforced_before_appending_fact(tmp_path):
    source = tmp_path / "source"
    current = source
    for _ in range(5):
        current = current / "d"
        current.mkdir(parents=True)

    _assert_inventory_error(
        "inventory-depth-exceeded",
        lambda: inventory_source(source, limits=_small_limits(max_depth=4)),
    )


def test_injected_limits_cannot_relax_the_hard_depth_cap(tmp_path):
    source = tmp_path / "source"
    current = source
    for _ in range(33):
        current = current / "d"
        current.mkdir(parents=True)

    _assert_inventory_error(
        "inventory-depth-exceeded",
        lambda: inventory_source(source, limits=InventoryLimits(max_depth=40)),
    )


@pytest.mark.parametrize(
    "field",
    [
        "max_depth",
        "max_directories",
        "max_regular_files",
        "max_items",
        "max_entries",
        "sample_bytes",
        "max_hash_file_bytes",
        "max_hash_total_bytes",
        "max_json_bytes",
    ],
)
def test_every_injected_limit_is_capped_by_its_hard_ceiling(monkeypatch, field):
    hard_values = {
        name: 2 for name in InventoryLimits.__dataclass_fields__
    }
    injected_values = {
        name: 1 for name in InventoryLimits.__dataclass_fields__
    }
    injected_values[field] = 3
    monkeypatch.setattr(
        inventory_module, "DEFAULT_LIMITS", InventoryLimits(**hard_values)
    )

    bounded = inventory_module._bounded_limits(InventoryLimits(**injected_values))

    assert getattr(bounded, field) == 2
    assert all(
        getattr(bounded, name) == (2 if name == field else 1)
        for name in InventoryLimits.__dataclass_fields__
    )


def test_directory_limit_is_enforced_before_appending_fact(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for index in range(9):
        (source / f"d-{index}").mkdir()

    _assert_inventory_error(
        "inventory-directory-count-exceeded",
        lambda: inventory_source(source, limits=_small_limits(max_directories=8)),
    )


def test_regular_file_limit_is_enforced_before_appending_fact(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for index in range(17):
        (source / f"f-{index:02d}.bin").write_bytes(b"x")

    _assert_inventory_error(
        "inventory-regular-file-count-exceeded",
        lambda: inventory_source(
            source,
            limits=_small_limits(
                max_regular_files=16, max_items=20, max_entries=20
            ),
        ),
    )


def test_total_item_limit_counts_non_regular_records(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    target = tmp_path / "target"
    target.write_bytes(b"target")
    for index in range(17):
        (source / f"link-{index:02d}").symlink_to(target)

    _assert_inventory_error(
        "inventory-item-count-exceeded",
        lambda: inventory_source(
            source,
            limits=_small_limits(max_items=16, max_entries=20),
        ),
    )


def test_combined_entry_limit_cannot_be_bypassed_by_directories(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for index in range(25):
        (source / f"d-{index:02d}").mkdir()

    _assert_inventory_error(
        "inventory-entry-count-exceeded",
        lambda: inventory_source(
            source,
            limits=_small_limits(
                max_directories=30, max_items=30, max_entries=24
            ),
        ),
    )


def test_unreadable_directory_enumeration_is_a_controlled_failure(
    tmp_path, monkeypatch
):
    source = tmp_path / "source"
    nested = source / "private-nested"
    nested.mkdir(parents=True)
    nested_identity = (nested.stat().st_dev, nested.stat().st_ino)
    original_scandir = os.scandir

    def deny_nested_scan(descriptor):
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) == nested_identity:
            raise PermissionError("private directory")
        return original_scandir(descriptor)

    monkeypatch.setattr(os, "scandir", deny_nested_scan)
    monkeypatch.setattr(inventory_module, "_require_secure_open", lambda: None)

    _assert_inventory_error(
        "inventory-directory-unreadable",
        lambda: inventory_source(source, limits=_small_limits()),
        private_path=nested,
    )


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are unavailable")
def test_regular_candidate_raced_to_fifo_is_opened_nonblocking(
    tmp_path, monkeypatch
):
    source = tmp_path / "source"
    source.mkdir()
    candidate = source / "candidate.pdf"
    candidate.write_bytes(b"%PDF-1.7\nsafe")
    original_open = os.open
    original_close = os.close
    replaced = False
    open_descriptors = set()

    def replace_with_fifo(path, flags, *args, **kwargs):
        nonlocal replaced
        if path == candidate.name and kwargs.get("dir_fd") is not None and not replaced:
            replaced = True
            candidate.unlink()
            os.mkfifo(candidate)
            assert flags & os.O_NONBLOCK
        descriptor = original_open(path, flags, *args, **kwargs)
        assert descriptor not in open_descriptors
        open_descriptors.add(descriptor)
        return descriptor

    def close_exactly_once(descriptor):
        assert descriptor in open_descriptors
        open_descriptors.remove(descriptor)
        return original_close(descriptor)

    monkeypatch.setattr(os, "open", replace_with_fifo)
    monkeypatch.setattr(os, "close", close_exactly_once)
    monkeypatch.setattr(inventory_module, "_require_secure_open", lambda: None)

    _assert_inventory_error(
        "inventory-tree-changed",
        lambda: inventory_source(source, limits=_small_limits()),
        private_path=candidate,
    )
    assert replaced is True
    assert open_descriptors == set()


@pytest.mark.parametrize(
    ("phase", "field"),
    [("sample", "identity"), ("sample", "size"), ("hash", "time")],
)
def test_first_file_metadata_mutation_gets_one_refreshed_opaque_record(
    tmp_path, monkeypatch, phase, field
):
    source = tmp_path / "source"
    source.mkdir()
    private_file = source / "private-client.pdf"
    content = b"%PDF-1.7\nprivate-content-for-hashing"
    private_file.write_bytes(content)
    state = _inject_one_read_metadata_mutation(
        monkeypatch, private_file, phase=phase, field=field
    )

    result = inventory_source(
        source,
        limits=_small_limits(sample_bytes=12, max_hash_file_bytes=1024),
    )

    assert state["returned"] is True
    item = result.items[0]
    assert item.extension == ".pdf"
    assert item.detected_type == "unknown"
    assert item.size == len(content)
    assert item.sha256 is None
    assert item.hash_status == "not-applicable"
    assert item.issue_codes == ("changed-during-read",)
    assert item.duplicate_group_id is None
    assert result.inventory_status == "complete-with-issues"


def test_changed_file_and_stable_match_never_form_duplicate_group(
    tmp_path, monkeypatch
):
    source = tmp_path / "source"
    source.mkdir()
    content = b"%PDF-1.7\nsame private content"
    changed = source / "a-changed.pdf"
    changed.write_bytes(content)
    (source / "b-stable.pdf").write_bytes(content)
    _inject_one_read_metadata_mutation(
        monkeypatch, changed, phase="hash", field="time"
    )

    result = inventory_source(
        source, limits=_small_limits(sample_bytes=8, max_hash_file_bytes=1024)
    )

    assert result.items[0].issue_codes == ("changed-during-read",)
    assert result.items[0].duplicate_group_id is None
    assert result.items[1].hash_status == "computed"
    assert result.items[1].duplicate_group_id is None


@pytest.mark.parametrize("later_change", ["second-mutation", "missing", "type-change"])
def test_mutation_after_the_single_refresh_fails_complete_accounting(
    tmp_path, monkeypatch, later_change
):
    source = tmp_path / "source"
    source.mkdir()
    private_file = source / "private.pdf"
    private_file.write_bytes(b"%PDF-1.7\nprivate-content")
    _inject_one_read_metadata_mutation(
        monkeypatch, private_file, phase="sample", field="size"
    )
    original_stat = os.stat
    target_name_stats = 0

    def mutate_at_boundary(path, *args, **kwargs):
        nonlocal target_name_stats
        if path == private_file.name and kwargs.get("dir_fd") is not None:
            target_name_stats += 1
            mutation_count = 4 if later_change == "second-mutation" else 3
            if target_name_stats == mutation_count:
                if later_change == "second-mutation":
                    private_file.write_bytes(b"second mutation is different")
                elif later_change == "missing":
                    private_file.unlink()
                else:
                    private_file.unlink()
                    os.mkfifo(private_file)
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", mutate_at_boundary)
    monkeypatch.setattr(inventory_module, "_require_secure_open", lambda: None)

    _assert_inventory_error(
        "inventory-tree-changed",
        lambda: inventory_source(source, limits=_small_limits(sample_bytes=8)),
        private_path=private_file,
    )


def test_directory_substitution_is_detected_during_final_revalidation(
    tmp_path, monkeypatch
):
    source = tmp_path / "source"
    nested = source / "nested"
    nested.mkdir(parents=True)
    moved = source / "moved"
    original_open = os.open
    nested_opens = 0

    def substitute_directory(path, flags, *args, **kwargs):
        nonlocal nested_opens
        if path == nested.name and kwargs.get("dir_fd") is not None:
            nested_opens += 1
            if nested_opens == 2:
                nested.rename(moved)
                nested.mkdir()
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", substitute_directory)
    monkeypatch.setattr(inventory_module, "_require_secure_open", lambda: None)

    _assert_inventory_error(
        "inventory-tree-changed",
        lambda: inventory_source(source, limits=_small_limits()),
    )


def test_descendant_mutation_before_final_observation_is_detected(
    tmp_path, monkeypatch
):
    source = tmp_path / "source"
    nested = source / "nested"
    nested.mkdir(parents=True)
    descendant = nested / "private.bin"
    descendant.write_bytes(b"approved")
    root_identity = (source.stat().st_dev, source.stat().st_ino)
    original_scandir = os.scandir
    root_scans = 0

    def mutate_before_final_tree_scan(descriptor):
        nonlocal root_scans
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) == root_identity:
            root_scans += 1
            if root_scans == 2:
                descendant.write_bytes(b"tampered")
        return original_scandir(descriptor)

    monkeypatch.setattr(os, "scandir", mutate_before_final_tree_scan)
    monkeypatch.setattr(inventory_module, "_require_secure_open", lambda: None)

    _assert_inventory_error(
        "inventory-tree-changed",
        lambda: inventory_source(source, limits=_small_limits()),
        private_path=descendant,
    )


def test_descendant_mutation_from_final_root_reopen_is_detected(
    tmp_path, monkeypatch
):
    source = tmp_path / "source"
    source.mkdir()
    descendant = source / "private.bin"
    original_content = b"approved"
    changed_content = b"tampered"
    descendant.write_bytes(original_content)
    original_open = os.open
    source_component_opens = 0

    def mutate_during_final_root_reopen(path, flags, *args, **kwargs):
        nonlocal source_component_opens
        if path == source.name and kwargs.get("dir_fd") is not None:
            source_component_opens += 1
            if source_component_opens == 2:
                descendant.write_bytes(changed_content)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", mutate_during_final_root_reopen)
    monkeypatch.setattr(inventory_module, "_require_secure_open", lambda: None)

    _assert_inventory_error(
        "inventory-tree-changed",
        lambda: inventory_source(source, limits=_small_limits()),
        private_path=descendant,
    )
    assert source_component_opens == 2
    assert descendant.read_bytes() == changed_content
    assert hashlib.sha256(descendant.read_bytes()).hexdigest() != hashlib.sha256(
        original_content
    ).hexdigest()


def test_serialized_result_limit_fails_instead_of_truncating(tmp_path):
    source = tmp_path / "source"
    source.mkdir()

    _assert_inventory_error(
        "inventory-output-too-large",
        lambda: inventory_source(source, limits=_small_limits(max_json_bytes=1)),
    )


def test_success_and_controlled_failure_do_not_mutate_source_tree(tmp_path):
    successful = tmp_path / "successful"
    nested = successful / "nested"
    nested.mkdir(parents=True)
    (successful / "safe.pdf").write_bytes(b"%PDF-1.7\nsafe")
    (nested / "safe.xlsx").write_bytes(
        b"PK\x03\x04[Content_Types].xml xl/workbook.xml"
    )
    target = tmp_path / "outside"
    target.write_bytes(b"outside")
    (successful / "link").symlink_to(target)
    before_success = _tree_snapshot(successful)

    inventory_source(successful, limits=_small_limits())

    assert _tree_snapshot(successful) == before_success

    failing = tmp_path / "failing"
    failing.mkdir()
    for index in range(3):
        (failing / f"file-{index}.bin").write_bytes(bytes([index]))
    before_failure = _tree_snapshot(failing)

    _assert_inventory_error(
        "inventory-regular-file-count-exceeded",
        lambda: inventory_source(
            failing,
            limits=_small_limits(
                max_regular_files=2, max_items=4, max_entries=4
            ),
        ),
    )

    assert _tree_snapshot(failing) == before_failure


def test_engine_never_calls_write_capable_filesystem_primitives(
    tmp_path, monkeypatch
):
    source = tmp_path / "source"
    source.mkdir()
    (source / "safe.pdf").write_bytes(b"%PDF-1.7\nsafe")
    original_open = os.open
    write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND

    def read_only_open(path, flags, *args, **kwargs):
        assert flags & write_flags == 0
        return original_open(path, flags, *args, **kwargs)

    def forbidden_write(*args, **kwargs):
        raise AssertionError("inventory invoked a write-capable primitive")

    monkeypatch.setattr(os, "open", read_only_open)
    monkeypatch.setattr(os, "write", forbidden_write)
    monkeypatch.setattr(os, "mkdir", forbidden_write)
    monkeypatch.setattr(os, "makedirs", forbidden_write)
    monkeypatch.setattr(os, "rename", forbidden_write)
    monkeypatch.setattr(os, "replace", forbidden_write)
    monkeypatch.setattr(os, "unlink", forbidden_write)
    monkeypatch.setattr(inventory_module, "_require_secure_open", lambda: None)

    result = inventory_source(source, limits=_small_limits())

    assert result.inventory_status == "complete"


def test_module_import_and_inventory_do_not_invoke_parser_network_or_process_modules(
    tmp_path, monkeypatch
):
    source = tmp_path / "source"
    source.mkdir()
    (source / "opaque.zip").write_bytes(b"PK\x03\x04private member strings")
    forbidden = {
        "zipfile", "tarfile", "fitz", "openpyxl", "PIL", "pytesseract",
        "socket", "subprocess",
    }
    original_import = builtins.__import__
    attempted = []

    def reject_forbidden_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.split(".", 1)[0] in forbidden:
            attempted.append(name)
            raise AssertionError(f"forbidden import: {name}")
        return original_import(name, globals, locals, fromlist, level)

    module_name = "_ctv_inventory_boundary_probe"
    module_path = Path(inventory_module.__file__)
    specification = importlib.util.spec_from_file_location(module_name, module_path)
    assert specification is not None and specification.loader is not None
    probe = importlib.util.module_from_spec(specification)
    sys.modules[module_name] = probe
    monkeypatch.setattr(builtins, "__import__", reject_forbidden_import)
    try:
        specification.loader.exec_module(probe)
        result = probe.inventory_source(source, limits=_small_limits())
    finally:
        sys.modules.pop(module_name, None)

    assert attempted == []
    assert result.inventory_status == "complete"


def test_private_names_and_container_contents_never_appear_in_result(tmp_path):
    source = tmp_path / "Hồ sơ khách hàng 012345678901"
    source.mkdir()
    names_and_content = {
        "Tên người có khoảng trắng 012345678901.pdf": (
            b"%PDF-1.7\nPDF-INNER-PRIVATE-TITLE"
        ),
        "control-\n-private.zip": b"PK\x03\x04ZIP-MEMBER-PRIVATE-NAME",
        "bí mật.địnhdạng": b"UNUSUAL-SUFFIX-PRIVATE",
        "workbook.xlsx": (
            b"PK\x03\x04[Content_Types].xml xl/workbook.xml PRIVATE-SHEET-NAME"
        ),
        "archive.rar": b"Rar!\x1a\x07\x01\x00RAR-MEMBER-PRIVATE-NAME",
    }
    for name, content in names_and_content.items():
        (source / name).write_bytes(content)

    result = inventory_source(source, limits=_small_limits())
    serialized = json.dumps(result.to_dict(), ensure_ascii=False)

    assert str(tmp_path) not in serialized
    assert source.name not in serialized
    for name in names_and_content:
        assert name not in serialized
    for private_fragment in (
        "012345678901", "Tên người", "control-", "bí mật",
        "PDF-INNER-PRIVATE-TITLE", "ZIP-MEMBER-PRIVATE-NAME",
        "UNUSUAL-SUFFIX-PRIVATE", "PRIVATE-SHEET-NAME",
        "RAR-MEMBER-PRIVATE-NAME",
    ):
        assert private_fragment not in serialized
    assert [item.extension for item in result.items].count("unknown") >= 1
