# ota/updater.py
#
# Fetches a signed manifest, verifies it against the baked-in public key,
# downloads only the files whose hashes differ, stages them, swaps them in,
# and resets. Safe to update over the air itself: recovery.py will restore the
# previous copy if a new version fails to confirm.

import json
import os

import microcontroller

from ota import state, verify
from ota import recovery
from ota.recovery import _copy, _ensure_dir, _listdir

REPO = "timrettop/flightportal"
MANIFEST_URL = "https://github.com/%s/releases/latest/download/manifest.json" % REPO
SIGNATURE_URL = "https://github.com/%s/releases/latest/download/manifest.sig" % REPO

# Never written by an update, whatever a manifest claims. The first group is
# the trusted core; the second is your local configuration.
PROTECTED = (
    "boot.py",
    "ota/verify.py",
    "ota/pubkey.py",
    "ota/state.py",
    "ota/recovery.py",
    "settings.toml",
    "secrets.py",
)

MAX_MANIFEST_BYTES = 8192


class UpdateError(Exception):
    pass


def _flatten(path):
    return path.replace("/", "~")


def _safe_path(path):
    if not path or path.startswith("/") or path.startswith("."):
        return False
    if ".." in path or "\\" in path:
        return False
    for ch in path:
        if not (ch.isalpha() or ch.isdigit() or ch in "._-/"):
            return False
    return True


def _get_bytes(session, url, limit):
    r = session.get(url)
    try:
        if r.status_code != 200:
            raise UpdateError("HTTP %d for %s" % (r.status_code, url))
        data = r.content
    finally:
        r.close()
    if len(data) > limit:
        raise UpdateError("response too large: %s" % url)
    return data


def _local_hash(path):
    try:
        h = verify.Sha256Stream()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(1024)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _clear(dirname):
    for name in _listdir(dirname):
        try:
            os.remove(dirname + "/" + name)
        except OSError:
            pass
    try:
        os.mkdir(dirname)
    except OSError:
        pass


def _download(session, url, dest, expected_hash, log):
    h = verify.Sha256Stream()
    r = session.get(url)
    try:
        if r.status_code != 200:
            raise UpdateError("HTTP %d for %s" % (r.status_code, url))
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1024):
                h.update(chunk)
                f.write(chunk)
    finally:
        r.close()

    actual = h.hexdigest()
    if actual != expected_hash:
        try:
            os.remove(dest)
        except OSError:
            pass
        raise UpdateError("hash mismatch for %s" % url)
    log("ota: verified %s" % url.rsplit("/", 1)[-1])


def fetch_manifest(session):
    """Return the parsed manifest, or raise UpdateError.

    The signature is checked over the exact bytes received. Nothing is
    re-serialised, so there is no canonicalisation to get wrong.
    """
    raw = _get_bytes(session, MANIFEST_URL, MAX_MANIFEST_BYTES)
    sig_b64 = _get_bytes(session, SIGNATURE_URL, 1024)

    import binascii

    try:
        sig = binascii.a2b_base64(sig_b64)
    except (ValueError, TypeError):
        raise UpdateError("signature is not valid base64")

    if not verify.verify(raw, sig):
        raise UpdateError("SIGNATURE INVALID -- refusing update")

    return json.loads(raw)


def check_and_apply(session, log=print, reset=True):
    """Check for an update and apply it. Resets the board on success.

    Returns False if nothing was applied. Never raises: a failed update
    check should not take down the display.
    """
    try:
        return _check_and_apply(session, log, reset)
    except UpdateError as e:
        log("ota: %s" % e)
    except Exception as e:  # network hiccups, JSON errors, full filesystem
        log("ota: unexpected error: %r" % e)
    return False


def _check_and_apply(session, log, reset):
    manifest = fetch_manifest(session)

    new_version = int(manifest["version"])
    current = state.version()
    if new_version <= current:
        log("ota: up to date (v%d)" % current)
        return False

    base = manifest["base_url"]
    if not base.startswith("https://"):
        raise UpdateError("base_url is not https")
    if not base.endswith("/"):
        base += "/"

    files = manifest["files"]
    pending = []
    for path, want in files.items():
        if not _safe_path(path):
            raise UpdateError("manifest contains unsafe path: %s" % path)
        if path in PROTECTED:
            log("ota: refusing to overwrite protected file %s" % path)
            continue
        if _local_hash(recovery.path(path)) != want:
            pending.append((path, want))

    if not pending:
        log("ota: v%d contains no file changes" % new_version)
        state.set_version(new_version)
        return False

    log("ota: v%d -> %d, %d file(s)" % (current, new_version, len(pending)))

    _clear(recovery.STAGE_DIR)
    for path, want in pending:
        _download(session, base + path, recovery.STAGE_DIR + "/" + _flatten(path), want, log)

    # Everything downloaded and verified. Only now do we touch live files.
    _clear(recovery.BACKUP_DIR)
    with open(recovery.BACKUP_DIR + "/.version", "w") as f:
        f.write(str(current))
    for path, _ in pending:
        try:
            _copy(recovery.path(path), recovery.BACKUP_DIR + "/" + _flatten(path))
        except OSError:
            pass  # file did not exist yet; nothing to restore

    for path, _ in pending:
        src = recovery.STAGE_DIR + "/" + _flatten(path)
        dst = recovery.path(path)
        _ensure_dir(dst)
        try:
            os.remove(dst)
        except OSError:
            pass
        os.rename(src, dst)
        log("ota: installed %s" % path)

    state.mark_pending(new_version)
    try:
        os.sync()
    except AttributeError:
        pass

    log("ota: applied v%d, resetting" % new_version)
    if reset:
        microcontroller.reset()
    return True