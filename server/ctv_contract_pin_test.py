from pathlib import Path
import json
import os
import shutil
import sys
import threading

import pytest

import ctv_contract_pin as contract_pin_module
from ctv_contract_pin import (
    ContractPinError,
    compute_contract_tree_sha256,
    load_contract_pin,
    verify_contract,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _copy_contract(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    target = root / "contracts" / "ctv-intake"
    target.mkdir(parents=True)
    shutil.copy2(REPOSITORY_ROOT / "contracts/ctv-intake/PIN.json", target / "PIN.json")
    shutil.copytree(REPOSITORY_ROOT / "contracts/ctv-intake/v1", target / "v1")
    return root


def _pin_payload() -> dict[str, str]:
    return {
        "compatibilityTarget": "ctv-intake-v1",
        "contractTreeSha256": "83d0523ffdf871d79597310d2a24424c8bb17b6fcdb208d9bf28afc70da6900d",
        "sourceCommit": "75b3b3bc7e3d4edef1b24a0cfc9bb6c039320f3a",
    }


def _replace_pin(root: Path, payload: object) -> None:
    (root / "contracts/ctv-intake/PIN.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _assert_error_code(expected: str, callable_) -> ContractPinError:
    with pytest.raises(ContractPinError) as raised:
        callable_()
    assert raised.value.code == expected
    assert str(raised.value) == expected
    return raised.value


def test_approved_contract_tree_matches_reviewed_pin(tmp_path):
    verification = verify_contract(_copy_contract(tmp_path))
    assert verification.verified is True
    assert verification.pin.source_commit == "75b3b3bc7e3d4edef1b24a0cfc9bb6c039320f3a"
    assert verification.actual_tree_sha256 == "83d0523ffdf871d79597310d2a24424c8bb17b6fcdb208d9bf28afc70da6900d"


@pytest.mark.parametrize("mutation", ["modified", "missing", "added"])
def test_any_contract_tree_mutation_is_detected(tmp_path, mutation):
    root = _copy_contract(tmp_path)
    version_root = root / "contracts/ctv-intake/v1"
    if mutation == "modified":
        (version_root / "compatibility.md").write_text("modified\n", encoding="utf-8")
    elif mutation == "missing":
        (version_root / "compatibility.md").unlink()
    else:
        (version_root / "unexpected.json").write_text("{}\n", encoding="utf-8")

    verification = verify_contract(root)

    assert verification.verified is False
    assert verification.actual_tree_sha256 != verification.pin.contract_tree_sha256


@pytest.mark.parametrize(
    ("pin_bytes", "expected"),
    [
        (None, "contract-pin-missing"),
        (b"{", "contract-pin-invalid"),
        (b"[]", "contract-pin-invalid"),
        (b"\xff", "contract-pin-invalid"),
        (b"1" * 5_000, "contract-pin-invalid"),
    ],
)
def test_missing_or_malformed_pin_is_rejected(tmp_path, pin_bytes, expected):
    root = _copy_contract(tmp_path)
    pin_path = root / "contracts/ctv-intake/PIN.json"
    if pin_bytes is None:
        pin_path.unlink()
    else:
        pin_path.write_bytes(pin_bytes)

    _assert_error_code(expected, lambda: load_contract_pin(root))


def test_pin_with_extra_key_is_rejected(tmp_path):
    root = _copy_contract(tmp_path)
    payload = _pin_payload()
    payload["unreviewed"] = "value"
    _replace_pin(root, payload)

    _assert_error_code("contract-pin-invalid", lambda: load_contract_pin(root))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sourceCommit", "75B3B3BC7E3D4EDEF1B24A0CFC9BB6C039320F3A"),
        ("sourceCommit", "75b3b3bc"),
        (
            "contractTreeSha256",
            "83D0523FFDF871D79597310D2A24424C8BB17B6FCDB208D9BF28AFC70DA6900D",
        ),
        ("contractTreeSha256", "83d0523f"),
    ],
)
def test_uppercase_or_short_pin_digest_is_rejected(tmp_path, field, value):
    root = _copy_contract(tmp_path)
    payload = _pin_payload()
    payload[field] = value
    _replace_pin(root, payload)

    _assert_error_code("contract-pin-invalid", lambda: load_contract_pin(root))


def test_wrong_compatibility_target_is_rejected(tmp_path):
    root = _copy_contract(tmp_path)
    payload = _pin_payload()
    payload["compatibilityTarget"] = "ctv-intake-v2"
    _replace_pin(root, payload)

    _assert_error_code("contract-pin-invalid", lambda: load_contract_pin(root))


def test_duplicate_pin_key_is_rejected(tmp_path):
    root = _copy_contract(tmp_path)
    duplicate = (
        '{"compatibilityTarget":"ctv-intake-v1",'
        '"contractTreeSha256":"83d0523ffdf871d79597310d2a24424c8bb17b6fcdb208d9bf28afc70da6900d",'
        '"sourceCommit":"75b3b3bc7e3d4edef1b24a0cfc9bb6c039320f3a",'
        '"sourceCommit":"75b3b3bc7e3d4edef1b24a0cfc9bb6c039320f3a"}'
    )
    (root / "contracts/ctv-intake/PIN.json").write_text(duplicate, encoding="utf-8")

    _assert_error_code("contract-pin-invalid", lambda: load_contract_pin(root))


def test_pin_over_16_kib_is_rejected_before_json_parsing(tmp_path):
    root = _copy_contract(tmp_path)
    (root / "contracts/ctv-intake/PIN.json").write_bytes(b" " * (16 * 1024 + 1))

    _assert_error_code("contract-pin-too-large", lambda: load_contract_pin(root))


def test_pin_symlink_is_rejected_without_reading_its_target(tmp_path):
    root = _copy_contract(tmp_path)
    target = tmp_path / "outside-pin.json"
    target.write_text(json.dumps(_pin_payload()), encoding="utf-8")
    pin_path = root / "contracts/ctv-intake/PIN.json"
    pin_path.unlink()
    pin_path.symlink_to(target)

    _assert_error_code("contract-pin-invalid", lambda: load_contract_pin(root))


def test_symlink_anywhere_under_v1_is_rejected(tmp_path):
    root = _copy_contract(tmp_path)
    version_root = root / "contracts/ctv-intake/v1"
    (version_root / "fixtures/unsafe-link").symlink_to(version_root / "compatibility.md")

    _assert_error_code("contract-entry-unsafe", lambda: verify_contract(root))


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are unavailable")
def test_non_regular_fifo_under_v1_is_rejected(tmp_path):
    root = _copy_contract(tmp_path)
    os.mkfifo(root / "contracts/ctv-intake/v1/unsafe-fifo")

    _assert_error_code("contract-entry-unsafe", lambda: verify_contract(root))


def test_unicode_paths_use_deterministic_posix_contract_relative_names(tmp_path):
    root = tmp_path / "repository"
    version_root = root / "contracts/ctv-intake/v1"
    (version_root / "nested").mkdir(parents=True)
    (version_root / "nested/évidence.txt").write_bytes(b"unicode\n")
    (version_root / "z.txt").write_bytes(b"z\n")

    assert compute_contract_tree_sha256(version_root) == (
        "0b1eac0cda3c3f3c5541387c4e44812a125cbfdca5ee99a5e9ef6e4a333549e3"
    )
    assert compute_contract_tree_sha256(version_root) == (
        "0b1eac0cda3c3f3c5541387c4e44812a125cbfdca5ee99a5e9ef6e4a333549e3"
    )


def test_failure_message_never_exposes_temporary_absolute_path(tmp_path):
    root = _copy_contract(tmp_path)
    (root / "contracts/ctv-intake/PIN.json").unlink()

    error = _assert_error_code("contract-pin-missing", lambda: verify_contract(root))

    assert str(tmp_path) not in str(error)


def test_file_over_16_mib_is_rejected_without_reading_it(tmp_path):
    version_root = tmp_path / "repository/contracts/ctv-intake/v1"
    version_root.mkdir(parents=True)
    with (version_root / "oversized.bin").open("wb") as oversized:
        oversized.truncate(16 * 1024 * 1024 + 1)

    _assert_error_code(
        "contract-file-too-large",
        lambda: compute_contract_tree_sha256(version_root),
    )


def test_more_than_1000_contract_files_is_rejected(tmp_path):
    version_root = tmp_path / "repository/contracts/ctv-intake/v1"
    version_root.mkdir(parents=True)
    for index in range(1_001):
        (version_root / f"{index:04d}.json").touch()

    _assert_error_code(
        "contract-file-count-exceeded",
        lambda: compute_contract_tree_sha256(version_root),
    )


def test_aggregate_over_64_mib_is_rejected(tmp_path):
    version_root = tmp_path / "repository/contracts/ctv-intake/v1"
    version_root.mkdir(parents=True)
    for index in range(4):
        with (version_root / f"0{index}.bin").open("wb") as contract_file:
            contract_file.truncate(16 * 1024 * 1024)
    (version_root / "04.bin").write_bytes(b"x")

    _assert_error_code(
        "contract-tree-too-large",
        lambda: compute_contract_tree_sha256(version_root),
    )


def test_missing_secure_open_primitive_fails_closed(tmp_path, monkeypatch):
    root = _copy_contract(tmp_path)
    monkeypatch.delattr(os, "O_NOFOLLOW")

    _assert_error_code("secure-open-unavailable", lambda: verify_contract(root))


@pytest.mark.parametrize("mutation", ["renamed", "same-size-content"])
def test_descendant_mutation_after_its_final_snapshot_is_rejected(
    tmp_path, monkeypatch, mutation
):
    root = tmp_path / "repository"
    intake_root = root / "contracts/ctv-intake"
    nested = intake_root / "v1/nested"
    nested.mkdir(parents=True)
    approved_file = nested / "a.txt"
    approved_file.write_bytes(b"approved\n")

    payload = _pin_payload()
    payload["contractTreeSha256"] = compute_contract_tree_sha256(
        intake_root / "v1"
    )
    (intake_root / "PIN.json").write_text(json.dumps(payload), encoding="utf-8")

    original_snapshot = contract_pin_module._snapshot_directory
    nested_identity = (nested.stat().st_dev, nested.stat().st_ino)
    nested_snapshots = 0
    mutate_now = threading.Event()
    mutation_done = threading.Event()

    def mutate_descendant():
        if not mutate_now.wait(timeout=5):
            return
        if mutation == "renamed":
            approved_file.rename(nested / "b.txt")
        else:
            approved_file.write_bytes(b"tampered\n")
        mutation_done.set()

    def snapshot_then_mutate(directory_fd):
        nonlocal nested_snapshots
        snapshot = original_snapshot(directory_fd)
        opened = os.fstat(directory_fd)
        if (opened.st_dev, opened.st_ino) == nested_identity:
            nested_snapshots += 1
            if nested_snapshots == 2:
                mutate_now.set()
                assert mutation_done.wait(timeout=5)
        return snapshot

    mutator = threading.Thread(target=mutate_descendant)
    mutator.start()
    monkeypatch.setattr(
        contract_pin_module, "_snapshot_directory", snapshot_then_mutate
    )
    try:
        error = _assert_error_code(
            "contract-tree-changed", lambda: verify_contract(root)
        )
    finally:
        mutate_now.set()
        mutator.join(timeout=5)

    assert not mutator.is_alive()
    assert str(tmp_path) not in str(error)


def test_deep_tree_fails_with_stable_bounded_error(tmp_path):
    version_root = tmp_path / "repository/contracts/ctv-intake/v1"
    current = version_root
    for _ in range(90):
        current = current / "d"
        current.mkdir(parents=True)
    (current / "leaf.txt").write_text("leaf\n", encoding="utf-8")

    original_limit = sys.getrecursionlimit()
    sys.setrecursionlimit(80)
    try:
        error = _assert_error_code(
            "contract-depth-exceeded",
            lambda: compute_contract_tree_sha256(version_root),
        )
    finally:
        sys.setrecursionlimit(original_limit)

    assert str(tmp_path) not in str(error)


def test_more_than_1000_directories_is_rejected(tmp_path):
    version_root = tmp_path / "repository/contracts/ctv-intake/v1"
    version_root.mkdir(parents=True)
    for index in range(1_001):
        (version_root / f"directory-{index:04d}").mkdir()

    error = _assert_error_code(
        "contract-directory-count-exceeded",
        lambda: compute_contract_tree_sha256(version_root),
    )

    assert str(tmp_path) not in str(error)


def test_single_directory_enumeration_is_bounded(tmp_path):
    version_root = tmp_path / "repository/contracts/ctv-intake/v1"
    version_root.mkdir(parents=True)
    for index in range(2_001):
        (version_root / f"entry-{index:04d}").mkdir()

    error = _assert_error_code(
        "contract-entry-count-exceeded",
        lambda: compute_contract_tree_sha256(version_root),
    )

    assert str(tmp_path) not in str(error)
