# ota/verify.py -- TRUSTED CORE. Load via USB. Do not ship OTA updates to this
# file unless you are prepared to re-flash by hand if you get it wrong.
#
# RSA-2048 PKCS#1 v1.5 signature verification over SHA-256.
# Verification is a single modular exponentiation with e=65537, which is native
# on this board (builtins.pow3), so it costs a fraction of a second.

try:
    import hashlib

    hashlib.new("sha256")
except (ImportError, ValueError):  # pragma: no cover - device fallback
    import adafruit_hashlib as hashlib

from ota.pubkey import N, E

_KEY_BYTES = 256  # 2048-bit modulus

# DER prefix for DigestInfo(SHA-256), RFC 8017 section 9.2
_SHA256_DIGESTINFO = (
    b"\x30\x31\x30\x0d\x06\x09\x60\x86\x48\x01\x65"
    b"\x03\x04\x02\x01\x05\x00\x04\x20"
)


def sha256(data):
    """Return the raw 32-byte SHA-256 digest of a bytes-like object."""
    h = hashlib.new("sha256")
    h.update(data)
    return h.digest()


class Sha256Stream:
    """Incremental hasher, so large files never have to fit in RAM."""

    def __init__(self):
        self._h = hashlib.new("sha256")

    def update(self, chunk):
        self._h.update(chunk)

    def hexdigest(self):
        return _hexlify(self._h.digest())


def _hexlify(raw):
    return "".join("%02x" % b for b in raw)


def _const_eq(a, b):
    """Length-independent, content-constant-time comparison."""
    if len(a) != len(b):
        return False
    diff = 0
    for x, y in zip(a, b):
        diff |= x ^ y
    return diff == 0


def verify(message, signature):
    """True if `signature` is a valid RSA-PKCS1v1.5-SHA256 signature over
    `message` under the baked-in public key.

    message   -- bytes, hashed exactly as received (no re-serialisation)
    signature -- bytes, exactly 256 bytes
    """
    if len(signature) != _KEY_BYTES:
        return False

    s = int.from_bytes(signature, "big")
    if s >= N:
        return False

    em = pow(s, E, N).to_bytes(_KEY_BYTES, "big")

    expected = (
        b"\x00\x01"
        + b"\xff" * (_KEY_BYTES - len(_SHA256_DIGESTINFO) - 32 - 3)
        + b"\x00"
        + _SHA256_DIGESTINFO
        + sha256(message)
    )
    return _const_eq(em, expected)