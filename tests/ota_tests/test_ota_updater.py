"""Tests for ota/updater.py.

The tests drive check_and_apply against a scratch directory (the ota_root
fixture) with a fake HTTP session, and always pass reset=False so the run
continues after a successful install.

Signature checking is exercised for real in test_ota_verify.py. Here it is
stubbed out in most tests so that manifest handling can be tested independently
-- except in the two tests that specifically cover a bad signature.
"""
import base64
import hashlib
import json
import os

import pytest

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from ota import recovery, state, updater, verify


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


# ---- fake HTTP ----
class FakeResponse:
    def __init__(self, data, status_code=200):
        self.content = data
        self.status_code = status_code
        self.closed = False

    def iter_content(self, size):
        for i in range(0, len(self.content), size):
            yield self.content[i:i + size]

    def close(self):
        self.closed = True


class FakeSession:
    """Serves a dict of url -> bytes. Anything else 404s."""

    def __init__(self, urls):
        self.urls = urls
        self.requested = []
        self.responses = []

    def get(self, url):
        self.requested.append(url)
        if url not in self.urls:
            r = FakeResponse(b"", status_code=404)
        else:
            r = FakeResponse(self.urls[url])
        self.responses.append(r)
        return r


BASE = "https://example.invalid/files/"


def build_session(files, version=5, base_url=BASE, signature=b"sig", extra=None):
    """files: {relative path: file contents as bytes}."""
    manifest = {
        "version": version,
        "base_url": base_url,
        "files": {p: sha256_hex(c) for p, c in files.items()},
    }
    if extra:
        manifest.update(extra)
    raw = json.dumps(manifest).encode()
    urls = {
        updater.MANIFEST_URL: raw,
        updater.SIGNATURE_URL: base64.b64encode(signature),
    }
    for p, c in files.items():
        urls[base_url + p] = c
    return FakeSession(urls), raw


@pytest.fixture
def trust_all(monkeypatch):
    """Accept any signature. Signature checking has its own test module."""
    monkeypatch.setattr(verify, "verify", lambda message, signature: True)


@pytest.fixture
def quiet():
    return lambda *a: None


def read(path):
    with open(str(path)) as f:
        return f.read()


# ---- path safety ----
@pytest.mark.parametrize("path", [
    "code.py",
    "flightlogic.py",
    "ota/updater.py",
    "ota/doorbell.py",
    "lib/adafruit_thing.py",
    "a_b-c.1.py",
])
def test_safe_paths_accepted(path):
    assert updater._safe_path(path) is True


@pytest.mark.parametrize("path", [
    "",
    "/etc/passwd",          # absolute
    "/code.py",
    "../code.py",           # traversal
    "ota/../../code.py",
    "..",
    ".hidden",              # leading dot
    ".ota_backup/code.py",
    "ota\\updater.py",      # windows separator
    "code .py",             # space
    "code;rm.py",
    "cod\x00e.py",
])
def test_unsafe_paths_rejected(path):
    assert updater._safe_path(path) is False


@pytest.mark.xfail(
    reason="CPython str.isalpha()/isdigit() accept non-ASCII; CircuitPython's "
           "do not. An explicit character allowlist in _safe_path would make "
           "the test host and the device agree. Remove this marker if fixed.",
)
@pytest.mark.parametrize("path", ["café.py", "\u0663.py", "\uff43ode.py"])
def test_non_ascii_paths_rejected(path):
    assert updater._safe_path(path) is False


def test_flatten_and_unflatten_round_trip(ota_root):
    assert recovery._unflatten(updater._flatten("ota/updater.py")) == \
        recovery.path("ota/updater.py")


# ---- protected files ----
def test_protected_tuple_covers_the_trusted_core():
    """Regression guard: these must never become OTA-updatable by accident."""
    for name in ("boot.py", "ota/verify.py", "ota/pubkey.py",
                 "ota/state.py", "ota/recovery.py"):
        assert name in updater.PROTECTED


def test_protected_local_config_is_never_overwritten():
    for name in ("settings.toml", "secrets.py", "config.py"):
        assert name in updater.PROTECTED


def test_manifest_cannot_overwrite_the_trusted_core(ota_root, trust_all, quiet):
    """The whole security model rests on this one."""
    (ota_root / "ota").mkdir()
    (ota_root / "ota" / "verify.py").write_text("trusted core")
    (ota_root / "boot.py").write_text("trusted boot")
    (ota_root / "secrets.py").write_text("my wifi password")

    session, _ = build_session({
        "ota/verify.py": b"attacker payload",
        "boot.py": b"attacker payload",
        "secrets.py": b"attacker payload",
        "code.py": b"legitimate new code",
    })

    assert updater.check_and_apply(session, log=quiet, reset=False) is True

    assert read(ota_root / "ota" / "verify.py") == "trusted core"
    assert read(ota_root / "boot.py") == "trusted boot"
    assert read(ota_root / "secrets.py") == "my wifi password"
    assert read(ota_root / "code.py") == "legitimate new code"


def test_protected_files_are_never_even_downloaded(ota_root, trust_all, quiet):
    session, _ = build_session({"ota/verify.py": b"payload", "code.py": b"new"})
    updater.check_and_apply(session, log=quiet, reset=False)
    assert BASE + "ota/verify.py" not in session.requested


# ---- manifest rejection ----
def test_rejects_unsafe_path_and_changes_nothing(ota_root, trust_all, quiet):
    (ota_root / "code.py").write_text("original")
    session, _ = build_session({"../code.py": b"payload", "code.py": b"new"})

    assert updater.check_and_apply(session, log=quiet, reset=False) is False
    assert read(ota_root / "code.py") == "original"
    assert state.version() == 0


def test_rejects_non_https_base_url(ota_root, trust_all, quiet):
    session, _ = build_session({"code.py": b"new"}, base_url="http://example.invalid/")
    assert updater.check_and_apply(session, log=quiet, reset=False) is False
    assert not (ota_root / "code.py").exists()


def test_rejects_bad_signature(ota_root, monkeypatch, quiet):
    monkeypatch.setattr(verify, "verify", lambda message, signature: False)
    (ota_root / "code.py").write_text("original")
    session, _ = build_session({"code.py": b"payload"})

    assert updater.check_and_apply(session, log=quiet, reset=False) is False
    assert read(ota_root / "code.py") == "original"


def test_bad_signature_is_logged_loudly(ota_root, monkeypatch):
    monkeypatch.setattr(verify, "verify", lambda message, signature: False)
    lines = []
    session, _ = build_session({"code.py": b"payload"})
    updater.check_and_apply(session, log=lines.append)
    assert any("SIGNATURE INVALID" in line for line in lines)


def test_rejects_signature_that_is_not_base64(ota_root, trust_all, quiet):
    session, _ = build_session({"code.py": b"new"})
    session.urls[updater.SIGNATURE_URL] = b"!!!not base64!!!"
    assert updater.check_and_apply(session, log=quiet, reset=False) is False


def test_rejects_oversized_manifest(ota_root, trust_all, quiet):
    session, _ = build_session({"code.py": b"new"})
    session.urls[updater.MANIFEST_URL] = b"x" * (updater.MAX_MANIFEST_BYTES + 1)
    assert updater.check_and_apply(session, log=quiet, reset=False) is False


def test_http_error_on_manifest_is_survivable(ota_root, trust_all, quiet):
    session = FakeSession({})  # everything 404s
    assert updater.check_and_apply(session, log=quiet, reset=False) is False


def test_malformed_manifest_is_survivable(ota_root, trust_all, quiet):
    session, _ = build_session({"code.py": b"new"})
    session.urls[updater.MANIFEST_URL] = b"{not json"
    assert updater.check_and_apply(session, log=quiet, reset=False) is False


def test_check_never_raises_even_on_a_broken_session(ota_root, trust_all, quiet):
    class Exploding:
        def get(self, url):
            raise RuntimeError("wifi fell over")

    assert updater.check_and_apply(Exploding(), log=quiet, reset=False) is False


# ---- version handling ----
@pytest.mark.parametrize("new_version", [5, 4, 0])
def test_ignores_versions_that_are_not_newer(ota_root, trust_all, quiet, new_version):
    state.set_version(5)
    (ota_root / "code.py").write_text("original")
    session, _ = build_session({"code.py": b"new"}, version=new_version)

    assert updater.check_and_apply(session, log=quiet, reset=False) is False
    assert read(ota_root / "code.py") == "original"
    assert state.version() == 5


def test_version_bumps_without_downloads_when_files_already_match(
    ota_root, trust_all, quiet
):
    """A release that only changed a protected or unchanged file."""
    (ota_root / "code.py").write_text("identical")
    session, _ = build_session({"code.py": b"identical"}, version=9)

    assert updater.check_and_apply(session, log=quiet, reset=False) is False
    assert state.version() == 9
    assert state.is_pending() is False
    assert BASE + "code.py" not in session.requested


def test_only_changed_files_are_downloaded(ota_root, trust_all, quiet):
    (ota_root / "code.py").write_text("unchanged")
    (ota_root / "flightlogic.py").write_text("old")
    session, _ = build_session({
        "code.py": b"unchanged",
        "flightlogic.py": b"new logic",
    })

    updater.check_and_apply(session, log=quiet, reset=False)
    assert BASE + "code.py" not in session.requested
    assert BASE + "flightlogic.py" in session.requested


# ---- the happy path ----
def test_installs_new_files(ota_root, trust_all, quiet):
    (ota_root / "code.py").write_text("old code")
    session, _ = build_session({"code.py": b"new code"})

    assert updater.check_and_apply(session, log=quiet, reset=False) is True
    assert read(ota_root / "code.py") == "new code"


def test_creates_nested_directories_for_new_files(ota_root, trust_all, quiet):
    session, _ = build_session({"ota/doorbell.py": b"doorbell v2"})
    assert updater.check_and_apply(session, log=quiet, reset=False) is True
    assert read(ota_root / "ota" / "doorbell.py") == "doorbell v2"


def test_backs_up_the_previous_copies(ota_root, trust_all, quiet):
    state.set_version(4)
    (ota_root / "code.py").write_text("old code")
    session, _ = build_session({"code.py": b"new code"}, version=5)

    updater.check_and_apply(session, log=quiet, reset=False)
    assert read(ota_root / ".ota_backup" / "code.py") == "old code"
    assert read(ota_root / ".ota_backup" / ".version") == "4"


def test_marks_the_update_pending_confirmation(ota_root, trust_all, quiet):
    session, _ = build_session({"code.py": b"new code"}, version=7)
    updater.check_and_apply(session, log=quiet, reset=False)
    assert state.is_pending() is True
    assert state.version() == 7
    assert state.attempts() == 0


def test_install_then_rollback_returns_the_original_file(ota_root, trust_all, quiet):
    """End to end: a bad update lands, never confirms, and boot.py undoes it."""
    state.set_version(4)
    (ota_root / "code.py").write_text("working code")
    session, _ = build_session({"code.py": b"broken code"}, version=5)

    updater.check_and_apply(session, log=quiet, reset=False)
    assert read(ota_root / "code.py") == "broken code"

    for _ in range(3):
        recovery.check(log=quiet)

    assert read(ota_root / "code.py") == "working code"
    assert state.version() == 4
    assert state.is_pending() is False


def test_staging_directory_is_emptied_after_a_successful_install(
    ota_root, trust_all, quiet
):
    session, _ = build_session({"code.py": b"new code"})
    updater.check_and_apply(session, log=quiet, reset=False)
    assert os.listdir(str(ota_root / ".ota_stage")) == []


def test_every_response_is_closed(ota_root, trust_all, quiet):
    session, _ = build_session({"code.py": b"new code"})
    updater.check_and_apply(session, log=quiet, reset=False)
    assert all(r.closed for r in session.responses), "leaked socket"


def test_resets_the_board_on_success(ota_root, trust_all, quiet, monkeypatch):
    import microcontroller
    calls = []
    monkeypatch.setattr(microcontroller, "reset", lambda: calls.append(1))

    session, _ = build_session({"code.py": b"new code"})
    updater.check_and_apply(session, log=quiet, reset=True)
    assert calls == [1]


def test_does_not_reset_when_nothing_was_applied(ota_root, trust_all, quiet):
    """conftest's stub reset() raises, so a stray reset fails the test."""
    state.set_version(9)
    session, _ = build_session({"code.py": b"new"}, version=9)
    assert updater.check_and_apply(session, log=quiet, reset=True) is False


# ---- download integrity ----
def test_hash_mismatch_leaves_live_files_untouched(ota_root, trust_all, quiet):
    """A file that hashes wrong must not reach the filesystem root."""
    (ota_root / "code.py").write_text("original")
    session, _ = build_session({"code.py": b"new code"})
    session.urls[BASE + "code.py"] = b"substituted content"

    assert updater.check_and_apply(session, log=quiet, reset=False) is False
    assert read(ota_root / "code.py") == "original"
    assert state.is_pending() is False


def test_failure_partway_through_installs_nothing(ota_root, trust_all, quiet):
    """Two files, the second 404s. The first must not be swapped in alone."""
    (ota_root / "code.py").write_text("original code")
    (ota_root / "flightlogic.py").write_text("original logic")
    session, _ = build_session({
        "code.py": b"new code",
        "flightlogic.py": b"new logic",
    })
    del session.urls[BASE + "flightlogic.py"]

    assert updater.check_and_apply(session, log=quiet, reset=False) is False
    assert read(ota_root / "code.py") == "original code"
    assert read(ota_root / "flightlogic.py") == "original logic"


def test_download_larger_than_the_chunk_size(ota_root, trust_all, quiet):
    blob = bytes(range(256)) * 30  # several 1024-byte chunks
    session, _ = build_session({"code.py": blob})
    updater.check_and_apply(session, log=quiet, reset=False)
    with open(str(ota_root / "code.py"), "rb") as f:
        assert f.read() == blob


# ---- the display callback ----
def test_on_installing_fires_once_for_a_real_install(ota_root, trust_all, quiet):
    calls = []
    session, _ = build_session({"code.py": b"new code", "ota/doorbell.py": b"new"})
    updater.check_and_apply(
        session, log=quiet, reset=False, on_installing=lambda: calls.append(1)
    )
    assert calls == [1]


def test_on_installing_does_not_fire_when_up_to_date(ota_root, trust_all, quiet):
    state.set_version(9)
    calls = []
    session, _ = build_session({"code.py": b"new"}, version=9)
    updater.check_and_apply(
        session, log=quiet, reset=False, on_installing=lambda: calls.append(1)
    )
    assert calls == []


def test_on_installing_does_not_fire_when_there_are_no_file_changes(
    ota_root, trust_all, quiet
):
    (ota_root / "code.py").write_text("identical")
    calls = []
    session, _ = build_session({"code.py": b"identical"}, version=9)
    updater.check_and_apply(
        session, log=quiet, reset=False, on_installing=lambda: calls.append(1)
    )
    assert calls == []


def test_a_broken_display_callback_does_not_abort_the_update(
    ota_root, trust_all, quiet
):
    def boom():
        raise RuntimeError("display is on fire")

    session, _ = build_session({"code.py": b"new code"})
    assert updater.check_and_apply(
        session, log=quiet, reset=False, on_installing=boom
    ) is True
    assert read(ota_root / "code.py") == "new code"


# ---- real signature, end to end ----
def test_real_signature_accepted_and_applied(ota_root, monkeypatch, quiet):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = key.public_key().public_numbers()
    monkeypatch.setattr(verify, "N", pub.n)
    monkeypatch.setattr(verify, "E", pub.e)

    session, raw = build_session({"code.py": b"signed code"})
    session.urls[updater.SIGNATURE_URL] = base64.b64encode(
        key.sign(raw, padding.PKCS1v15(), hashes.SHA256())
    )

    assert updater.check_and_apply(session, log=quiet, reset=False) is True
    assert read(ota_root / "code.py") == "signed code"


def test_manifest_tampered_after_signing_is_rejected(ota_root, monkeypatch, quiet):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = key.public_key().public_numbers()
    monkeypatch.setattr(verify, "N", pub.n)
    monkeypatch.setattr(verify, "E", pub.e)

    session, raw = build_session({"code.py": b"signed code"})
    session.urls[updater.SIGNATURE_URL] = base64.b64encode(
        key.sign(raw, padding.PKCS1v15(), hashes.SHA256())
    )
    # Bump the version in the manifest without re-signing.
    tampered = json.loads(raw)
    tampered["version"] = 999
    session.urls[updater.MANIFEST_URL] = json.dumps(tampered).encode()

    assert updater.check_and_apply(session, log=quiet, reset=False) is False
    assert not (ota_root / "code.py").exists()
