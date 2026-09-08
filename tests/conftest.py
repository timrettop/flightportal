"""Fixtures shared by the ota tests."""
import hashlib
import sys

import pytest

from ota import recovery


@pytest.fixture(autouse=True)
def blank_nvm():
    """Every test starts on a device that has never seen an update."""
    nvm = sys.modules["microcontroller"].nvm
    nvm[:] = bytes(len(nvm))
    yield
    nvm[:] = bytes(len(nvm))


@pytest.fixture
def ota_root(tmp_path, monkeypatch):
    """Point the whole ota package at a scratch directory.

    ROOT, BACKUP_DIR and STAGE_DIR are all module-level constants computed at
    import time, so all three have to be patched -- setting ROOT alone leaves
    the other two pointing at the real filesystem root.
    """
    root = str(tmp_path) + "/"
    monkeypatch.setattr(recovery, "ROOT", root)
    monkeypatch.setattr(recovery, "BACKUP_DIR", root + ".ota_backup")
    monkeypatch.setattr(recovery, "STAGE_DIR", root + ".ota_stage")
    return tmp_path


def sha256_hex(data):
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()
