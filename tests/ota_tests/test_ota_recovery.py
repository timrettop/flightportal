"""Tests for ota/recovery.py -- the rollback path that boot.py calls.

This is the code that has to work when everything else has already failed, so
the tests lean towards "does it survive a mess" rather than "is it tidy".
"""
import os

import pytest

from ota import recovery, state


def write(path, text):
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with open(str(path), "w") as f:
        f.write(text)


@pytest.fixture
def backup(ota_root):
    """A populated backup directory: one top-level file, one nested."""
    d = ota_root / ".ota_backup"
    d.mkdir()
    (d / "code.py").write_text("old code")
    (d / "ota~doorbell.py").write_text("old doorbell")
    (d / ".version").write_text("4")
    return d


# ---- nothing to do ----
def test_no_rollback_when_no_update_is_pending(ota_root):
    assert recovery.check(log=lambda *a: None) is False


def test_no_rollback_while_attempts_remain(ota_root):
    state.mark_pending(5)
    assert recovery.check(log=lambda *a: None) is False
    assert recovery.check(log=lambda *a: None) is False
    assert state.is_pending() is True
    assert state.attempts() == 2


def test_attempt_counter_advances_on_every_boot(ota_root):
    state.mark_pending(5)
    recovery.check(log=lambda *a: None)
    assert state.attempts() == 1


def test_confirmed_update_never_rolls_back(ota_root, backup):
    """The happy path: code.py confirmed, so later boots leave it alone."""
    write(ota_root / "code.py", "new code")
    state.mark_pending(5)
    state.confirm()
    for _ in range(5):
        assert recovery.check(log=lambda *a: None) is False
    assert (ota_root / "code.py").read_text() == "new code"
    assert state.version() == 5


# ---- the rollback ----
def test_rolls_back_after_max_attempts(ota_root, backup):
    write(ota_root / "code.py", "new code")
    state.mark_pending(5)

    assert recovery.check(log=lambda *a: None) is False  # boot 1
    assert recovery.check(log=lambda *a: None) is False  # boot 2
    assert recovery.check(log=lambda *a: None) is True   # boot 3 -> rollback


def test_rollback_restores_file_contents(ota_root, backup):
    write(ota_root / "code.py", "new code")
    write(ota_root / "ota" / "doorbell.py", "new doorbell")
    state.mark_pending(5)
    for _ in range(3):
        recovery.check(log=lambda *a: None)

    assert (ota_root / "code.py").read_text() == "old code"
    assert (ota_root / "ota" / "doorbell.py").read_text() == "old doorbell"


def test_rollback_restores_the_previous_version_number(ota_root, backup):
    state.mark_pending(5)
    for _ in range(3):
        recovery.check(log=lambda *a: None)
    assert state.version() == 4
    assert state.is_pending() is False
    assert state.attempts() == 0


def test_rollback_recreates_a_file_the_update_deleted(ota_root, backup):
    """Nothing on disk to overwrite; the backup copy still has to land."""
    state.mark_pending(5)
    for _ in range(3):
        recovery.check(log=lambda *a: None)
    assert (ota_root / "code.py").read_text() == "old code"


def test_rollback_happens_only_once(ota_root, backup):
    state.mark_pending(5)
    for _ in range(3):
        recovery.check(log=lambda *a: None)
    write(ota_root / "code.py", "hand edited after rollback")
    assert recovery.check(log=lambda *a: None) is False
    assert (ota_root / "code.py").read_text() == "hand edited after rollback"


# ---- degraded conditions ----
def test_missing_backup_directory_still_clears_pending(ota_root):
    """Worst case: pending set, backups gone. Must not loop forever."""
    state.mark_pending(5)
    for _ in range(3):
        result = recovery.check(log=lambda *a: None)
    assert result is True
    assert state.is_pending() is False
    assert state.version() == 0


def test_unreadable_version_file_falls_back_to_zero(ota_root, backup):
    (backup / ".version").write_text("not a number")
    state.mark_pending(5)
    for _ in range(3):
        recovery.check(log=lambda *a: None)
    assert state.version() == 0
    assert state.is_pending() is False


def test_check_logs_through_the_supplied_callable(ota_root):
    lines = []
    state.mark_pending(5)
    recovery.check(log=lines.append)
    assert any("boot attempt" in line for line in lines)


# ---- path helpers ----
def test_path_is_relative_to_root(ota_root):
    assert recovery.path("code.py") == str(ota_root) + "/code.py"


def test_unflatten_restores_directory_separators(ota_root):
    assert recovery._unflatten("ota~doorbell.py") == str(ota_root) + "/ota/doorbell.py"


def test_ensure_dir_creates_missing_parents(ota_root):
    target = str(ota_root) + "/a/b/c.py"
    recovery._ensure_dir(target)
    assert os.path.isdir(str(ota_root) + "/a/b")


def test_ensure_dir_is_idempotent(ota_root):
    target = str(ota_root) + "/a/b/c.py"
    recovery._ensure_dir(target)
    recovery._ensure_dir(target)  # must not raise


def test_copy_handles_files_larger_than_the_chunk_size(ota_root):
    src = ota_root / "big.bin"
    src.write_bytes(bytes(range(256)) * 30)  # 7680 bytes, several chunks
    recovery._copy(str(src), str(ota_root) + "/nested/copy.bin")
    assert (ota_root / "nested" / "copy.bin").read_bytes() == src.read_bytes()


def test_listdir_of_a_missing_directory_is_empty(ota_root):
    assert recovery._listdir(str(ota_root) + "/nope") == []
