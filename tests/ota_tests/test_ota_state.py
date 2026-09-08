"""Tests for ota/state.py.

State lives in microcontroller.nvm, which the root conftest stubs with a
bytearray. The blank_nvm fixture zeroes it before every test, so each test
starts from a device that has never been updated.
"""
import sys

import pytest

from ota import state


@pytest.fixture
def nvm():
    return sys.modules["microcontroller"].nvm


# ---- fresh device ----
def test_fresh_device_has_version_zero():
    assert state.version() == 0


def test_fresh_device_has_nothing_pending():
    assert state.is_pending() is False
    assert state.attempts() == 0


def test_uninitialised_nvm_is_treated_as_fresh(nvm):
    """Garbage in nvm must not be read as a version number."""
    nvm[:] = b"\xa5" * len(nvm)
    assert state.version() == 0
    assert state.is_pending() is False


def test_first_write_stamps_the_magic_byte(nvm):
    state.set_version(3)
    assert nvm[0] == 0x4F


# ---- version ----
@pytest.mark.parametrize("v", [0, 1, 42, 65535, 2 ** 32 - 1])
def test_version_roundtrips(v):
    state.set_version(v)
    assert state.version() == v


def test_set_version_does_not_disturb_pending_flag():
    state.mark_pending(5)
    state.set_version(6)
    assert state.is_pending() is True
    assert state.version() == 6


# ---- the update lifecycle ----
def test_mark_pending_records_version_and_resets_attempts():
    state.set_version(4)
    state.note_attempt()
    state.mark_pending(5)
    assert state.version() == 5
    assert state.is_pending() is True
    assert state.attempts() == 0


def test_note_attempt_increments_and_returns_the_count():
    state.mark_pending(5)
    assert state.note_attempt() == 1
    assert state.note_attempt() == 2
    assert state.attempts() == 2


def test_note_attempt_saturates_rather_than_wrapping():
    """Byte 2 must never wrap to 0, or a stuck device would retry forever."""
    state.mark_pending(5)
    for _ in range(260):
        n = state.note_attempt()
    assert n == 255
    assert state.attempts() == 255


def test_confirm_clears_pending_and_keeps_the_new_version():
    state.mark_pending(5)
    state.note_attempt()
    state.confirm()
    assert state.is_pending() is False
    assert state.attempts() == 0
    assert state.version() == 5


def test_clear_pending_rolls_the_version_back():
    state.set_version(4)
    state.mark_pending(5)
    state.note_attempt()
    state.clear_pending(4)
    assert state.is_pending() is False
    assert state.attempts() == 0
    assert state.version() == 4


def test_state_survives_a_reset():
    """nvm is not re-read from a cache; every call hits the buffer."""
    state.mark_pending(9)
    state.note_attempt()
    # Nothing to simulate: a reset loses RAM, not nvm. Re-reading is the test.
    assert state.version() == 9
    assert state.is_pending() is True
    assert state.attempts() == 1


def test_state_fits_in_the_documented_seven_bytes(nvm):
    state.mark_pending(2 ** 32 - 1)
    state.note_attempt()
    assert all(b == 0 for b in nvm[7:]), "state must not spill past byte 6"
