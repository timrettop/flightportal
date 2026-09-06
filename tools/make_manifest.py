#!/usr/bin/env python3
"""Build and sign the OTA manifest.

    python3 tools/make_manifest.py --key ota-private.pem --repo timrettop/flightportal \
        --sha "$GITHUB_SHA" --out dist

Writes dist/manifest.json and dist/manifest.sig (base64). The signature covers
the exact bytes of manifest.json, so the device hashes what it received and
never has to re-serialise anything.
"""
import argparse
import base64
import hashlib
import json
import pathlib
import subprocess
import sys

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

# Files the updater will never install, whatever this script produces. Kept in
# sync with PROTECTED in ota/updater.py.
NEVER_SHIP = {
    "boot.py",
    "ota/verify.py",
    "ota/pubkey.py",
    "ota/state.py",
    "ota/recovery.py",
    "settings.toml",
    "secrets.py",
}


def included_paths(listfile, root):
    paths = []
    for line in pathlib.Path(listfile).read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        matches = sorted(root.glob(line))
        if not matches:
            sys.exit(f"pattern matched nothing: {line}")
        for m in matches:
            if m.is_file():
                paths.append(m.relative_to(root).as_posix())
    return sorted(set(paths))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--sha", required=True)
    ap.add_argument("--version", type=int)
    ap.add_argument("--list", default="ota-files.txt")
    ap.add_argument("--out", default="dist")
    ap.add_argument("--root", default=".", help="directory to package (default: cwd)")
    args = ap.parse_args()
    root = pathlib.Path(args.root).resolve()

    version = args.version
    if version is None:
        # Commit count is monotonic and needs no bookkeeping.
        version = int(
            subprocess.check_output(
                ["git", "rev-list", "--count", "HEAD"], cwd=root
            ).strip()
        )

    files = {}
    for rel in included_paths(args.list, root):
        if rel in NEVER_SHIP:
            sys.exit(f"{rel} is in the trusted core and must not be shipped OTA")
        files[rel] = hashlib.sha256((root / rel).read_bytes()).hexdigest()

    if not files:
        sys.exit("manifest would be empty")

    manifest = {
        "version": version,
        "base_url": f"https://raw.githubusercontent.com/{args.repo}/{args.sha}/",
        "files": files,
    }

    # sort_keys makes the output reproducible; the device does not depend on it.
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()

    key = serialization.load_pem_private_key(
        pathlib.Path(args.key).read_bytes(), password=None
    )
    if not isinstance(key, rsa.RSAPrivateKey):
        sys.exit(f"{args.key} is not an RSA key (got {type(key).__name__})")
    sig = key.sign(raw, padding.PKCS1v15(), hashes.SHA256())

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_bytes(raw)
    (out / "manifest.sig").write_text(base64.b64encode(sig).decode())

    print(f"version {version}, {len(files)} file(s)")
    for k in files:
        print(f"  {k}")


if __name__ == "__main__":
    main()