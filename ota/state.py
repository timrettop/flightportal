# ota/state.py -- TRUSTED CORE. Load via USB.
#
# Update state lives in microcontroller.nvm because nvm stays writable even
# when USB owns the filesystem, and it survives a reset. Falls back to a file
# if the board exposes no nvm.
#
# Layout (7 bytes):
#   0      magic 0x4F, marks the block as initialised
#   1      flags, bit0 = an update is pending confirmation
#   2      consecutive boot attempts since the update was staged
#   3..6   installed version, uint32 big-endian

import microcontroller

_MAGIC = 0x4F
_SIZE = 7
_PENDING = 0x01
_FALLBACK = "/.ota_state.bin"

MAX_ATTEMPTS = 2  # after this many unconfirmed boots, roll back


def _read():
    nvm = microcontroller.nvm
    if nvm is not None:
        buf = bytearray(nvm[0:_SIZE])
    else:
        try:
            with open(_FALLBACK, "rb") as f:
                buf = bytearray(f.read(_SIZE))
        except OSError:
            buf = bytearray(_SIZE)
    if len(buf) < _SIZE or buf[0] != _MAGIC:
        buf = bytearray(_SIZE)
        buf[0] = _MAGIC
    return buf


def _write(buf):
    nvm = microcontroller.nvm
    if nvm is not None:
        nvm[0:_SIZE] = buf
    else:
        with open(_FALLBACK, "wb") as f:
            f.write(buf)


def version():
    """Installed version number. 0 on a fresh device."""
    b = _read()
    return int.from_bytes(bytes(b[3:7]), "big")


def set_version(v):
    b = _read()
    b[3:7] = v.to_bytes(4, "big")
    _write(b)


def is_pending():
    return bool(_read()[1] & _PENDING)


def attempts():
    return _read()[2]


def mark_pending(new_version):
    """Called after files are swapped in, immediately before the reset."""
    b = _read()
    b[1] |= _PENDING
    b[2] = 0
    b[3:7] = new_version.to_bytes(4, "big")
    _write(b)


def note_attempt():
    """Called from boot.py on every boot while an update is unconfirmed."""
    b = _read()
    b[2] = min(255, b[2] + 1)
    _write(b)
    return b[2]


def confirm():
    """Called by the application once it is satisfied the update works."""
    b = _read()
    b[1] &= ~_PENDING
    b[2] = 0
    _write(b)


def clear_pending(rolled_back_to):
    """Called from boot.py after a rollback."""
    b = _read()
    b[1] &= ~_PENDING
    b[2] = 0
    b[3:7] = rolled_back_to.to_bytes(4, "big")
    _write(b)