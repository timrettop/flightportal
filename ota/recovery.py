# ota/recovery.py -- TRUSTED CORE. Load via USB.
#
# Imported by boot.py. 

import os

from ota import state

# ROOT is "/" on the device. It exists as a constant so the update flow can be
# exercised against a scratch directory on a laptop before you trust it.
ROOT = "/"
BACKUP_DIR = ROOT + ".ota_backup"
STAGE_DIR = ROOT + ".ota_stage"


def path(rel):
    """Absolute path of a manifest-relative file."""
    return ROOT + rel


def _unflatten(name):
    return path(name.replace("~", "/"))


def _ensure_dir(path):
    parts = path.strip("/").split("/")[:-1]
    cur = ""
    for p in parts:
        cur += "/" + p
        try:
            os.mkdir(cur)
        except OSError:
            pass


def _copy(src, dst):
    _ensure_dir(dst)
    with open(src, "rb") as fin:
        with open(dst, "wb") as fout:
            while True:
                chunk = fin.read(1024)
                if not chunk:
                    break
                fout.write(chunk)


def _listdir(path):
    try:
        return os.listdir(path)
    except OSError:
        return []


def check(log=print):
    """Run early in boot.py, after the filesystem is remounted writable.

    Returns True if a rollback was performed.
    """
    if not state.is_pending():
        return False

    n = state.note_attempt()
    if n <= state.MAX_ATTEMPTS:
        log("ota: update pending, boot attempt %d" % n)
        return False

    log("ota: update failed to confirm after %d boots, rolling back" % n)

    prev_version = 0
    names = _listdir(BACKUP_DIR)
    for name in names:
        src = BACKUP_DIR + "/" + name
        if name == ".version":
            try:
                with open(src) as f:
                    prev_version = int(f.read().strip())
            except (OSError, ValueError):
                pass
            continue
        try:
            _copy(src, _unflatten(name))
            log("ota: restored %s" % _unflatten(name))
        except OSError as e:
            log("ota: restore failed for %s: %s" % (name, e))

    state.clear_pending(prev_version)
    try:
        os.sync()
    except AttributeError:
        pass
    return True