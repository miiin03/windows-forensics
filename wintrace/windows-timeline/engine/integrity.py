"""Evidence integrity: hashing + chain-of-custody records (read-only)."""

from __future__ import annotations

import hashlib

_CHUNK = 1 << 20  # 1 MiB


def hash_file(path: str) -> dict | None:
    """Return {md5, sha256, size} streaming the file, or None if unreadable."""
    try:
        md5, sha = hashlib.md5(), hashlib.sha256()
        size = 0
        with open(path, "rb") as f:
            while True:
                chunk = f.read(_CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                md5.update(chunk)
                sha.update(chunk)
        return {"md5": md5.hexdigest(), "sha256": sha.hexdigest(), "size": size}
    except OSError:
        return None


def custody_record(path: str, *, stage: str) -> dict:
    """One chain-of-custody entry for an evidence file at a stage."""
    h = hash_file(path) or {"md5": None, "sha256": None, "size": None}
    return {"path": path, "stage": stage, **h}
