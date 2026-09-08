"""Tests for ota/verify.py -- the root of trust.

A test keypair is generated here and verify.N / verify.E are patched to match.
Patching ota.pubkey would not work: verify.py does `from ota.pubkey import N, E`
at import time, so the values are already bound as module attributes of verify.
"""
import hashlib

import pytest

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from ota import verify

MANIFEST = b'{"version": 7, "base_url": "https://example.invalid/", "files": {}}'


@pytest.fixture(scope="module")
def keypair():
    """RSA-2048 keypair. Module-scoped: generation is slow."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key, key.public_key().public_numbers()


@pytest.fixture
def signer(keypair, monkeypatch):
    key, pub = keypair
    monkeypatch.setattr(verify, "N", pub.n)
    monkeypatch.setattr(verify, "E", pub.e)

    def sign(message):
        return key.sign(message, padding.PKCS1v15(), hashes.SHA256())

    return sign


def flip_bit(data, index=0):
    b = bytearray(data)
    b[index] ^= 0x01
    return bytes(b)


# ---- hashing ----
def test_sha256_matches_stdlib():
    assert verify.sha256(MANIFEST) == hashlib.sha256(MANIFEST).digest()


def test_stream_hash_matches_whole_file_hash():
    """Chunked hashing is what _download and _local_hash rely on."""
    blob = bytes(range(256)) * 40
    h = verify.Sha256Stream()
    for i in range(0, len(blob), 1024):
        h.update(blob[i:i + 1024])
    assert h.hexdigest() == hashlib.sha256(blob).hexdigest()


def test_stream_hash_of_empty_input():
    assert verify.Sha256Stream().hexdigest() == hashlib.sha256(b"").hexdigest()


# ---- constant-time compare ----
@pytest.mark.parametrize("a,b,expected", [
    (b"", b"", True),
    (b"abc", b"abc", True),
    (b"abc", b"abd", False),
    (b"abc", b"ab", False),
    (b"ab", b"abc", False),
])
def test_const_eq(a, b, expected):
    assert verify._const_eq(a, b) is expected


# ---- signature verification ----
def test_valid_signature_verifies(signer):
    assert verify.verify(MANIFEST, signer(MANIFEST)) is True


def test_empty_message_verifies(signer):
    assert verify.verify(b"", signer(b"")) is True


def test_rejects_tampered_message(signer):
    sig = signer(MANIFEST)
    assert verify.verify(flip_bit(MANIFEST), sig) is False


def test_rejects_message_with_trailing_byte(signer):
    """Whitespace appended by a proxy or editor must not slip through."""
    sig = signer(MANIFEST)
    assert verify.verify(MANIFEST + b"\n", sig) is False


def test_rejects_tampered_signature(signer):
    sig = signer(MANIFEST)
    assert verify.verify(MANIFEST, flip_bit(sig, 200)) is False


def test_rejects_signature_from_a_different_key(signer):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    sig = other.sign(MANIFEST, padding.PKCS1v15(), hashes.SHA256())
    assert verify.verify(MANIFEST, sig) is False


@pytest.mark.parametrize("length", [0, 1, 255, 257, 512])
def test_rejects_wrong_length_signature(signer, length):
    assert verify.verify(MANIFEST, b"\x00" * length) is False


def test_rejects_signature_not_less_than_modulus(signer):
    """s >= N is outside the group; pow() would still return something."""
    assert verify.verify(MANIFEST, b"\xff" * 256) is False


def test_rejects_all_zero_signature(signer):
    assert verify.verify(MANIFEST, b"\x00" * 256) is False


def test_signature_is_not_transferable_between_messages(signer):
    """A valid signature over one manifest must not validate another."""
    other = b'{"version": 99, "base_url": "https://evil.invalid/", "files": {}}'
    assert verify.verify(other, signer(MANIFEST)) is False
