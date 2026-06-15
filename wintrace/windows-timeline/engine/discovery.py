"""Locate local Windows Timeline ActivitiesCache.db files."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ActivityDbCandidate:
    db_path: str
    wal_path: str | None
    shm_path: str | None
    account: str


def _connected_devices_platform_dir(root: str | os.PathLike | None) -> Path | None:
    if root is not None:
        base = Path(root)
    elif os.environ.get("WT_CDP_DIR"):
        base = Path(os.environ["WT_CDP_DIR"])
    elif os.environ.get("LOCALAPPDATA"):
        base = Path(os.environ["LOCALAPPDATA"]) / "ConnectedDevicesPlatform"
    else:
        return None

    if base.name.lower() == "connecteddevicesplatform":
        return base
    return base / "ConnectedDevicesPlatform"


def _candidate_for(db_path: Path) -> ActivityDbCandidate:
    wal = db_path.with_name(db_path.name + "-wal")
    shm = db_path.with_name(db_path.name + "-shm")
    return ActivityDbCandidate(
        db_path=str(db_path),
        wal_path=str(wal) if wal.exists() else None,
        shm_path=str(shm) if shm.exists() else None,
        account=db_path.parent.name,
    )


def find_activitiescache_dbs(root: str | os.PathLike | None = None) -> list[ActivityDbCandidate]:
    """Find ``ConnectedDevicesPlatform/<account>/ActivitiesCache.db`` files."""
    cdp_dir = _connected_devices_platform_dir(root)
    if cdp_dir is None or not cdp_dir.is_dir():
        return []

    found = []
    for account_dir in sorted(cdp_dir.iterdir(), key=lambda p: p.name.lower()):
        if not account_dir.is_dir():
            continue
        db_path = account_dir / "ActivitiesCache.db"
        if db_path.is_file():
            found.append(_candidate_for(db_path))
    return found
