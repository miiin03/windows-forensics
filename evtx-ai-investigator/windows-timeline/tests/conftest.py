"""Synthetic ActivitiesCache.db fixture builder for TDD.

Builds tiny databases with a real-shaped ``Activity`` table, inserts N rows
with deterministic GUIDs, deletes M of them, and reports ground truth so a
carver test can assert "the deleted GUIDs were recovered".
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from engine.schema import ACTIVITY_COLUMNS

# Build a CREATE TABLE matching the real Activity column names/types.
_COLDEFS = ", ".join(f'"{c.name}" {c.decl_type}' for c in ACTIVITY_COLUMNS)
ACTIVITY_DDL = f'CREATE TABLE "Activity" ({_COLDEFS})'


def make_guid(i: int) -> bytes:
    """Deterministic 16-byte GUID blob (stored as serial type 44)."""
    return b"GUID" + i.to_bytes(12, "big")


def _row(i: int, payload_pad: int = 0):
    appid = json.dumps([{"application": f"app{i}.exe", "platform": "windows_win32"}])
    payload = json.dumps(
        {"displayText": f"item {i}", "activeDurationSeconds": i, "pad": "x" * payload_pad}
    ).encode("utf-8")
    base_epoch = 1_600_000_000 + i
    values = {
        "Id": make_guid(i),
        "AppId": appid,
        "PackageIdHash": f"hash{i}",
        "AppActivityId": f"act{i}",
        "ActivityType": 5,
        "ActivityStatus": 1,
        "ParentActivityId": None,
        "Tag": None,
        "Group": None,
        "MatchId": None,
        "LastModifiedTime": base_epoch + 100,
        "ExpirationTime": base_epoch + 99999,
        "Payload": payload,
        "Priority": 1,
        "IsLocalOnly": 0,
        "PlatformDeviceId": None,
        "DdsDeviceId": None,
        "CreatedInCloud": 0,
        "StartTime": base_epoch,
        "EndTime": base_epoch + 50,
        "LastModifiedOnClient": base_epoch + 100,
        "GroupAppActivityId": None,
        "ClipboardPayload": None,
        "EnterpriseId": None,
        "OriginalPayload": None,
        "UserActionState": 0,
        "IsRead": 1,
        "OriginalLastModifiedOnClient": 0,
        "GroupItems": None,
        "LocalExpirationTime": base_epoch + 99999,
        "ETag": i,
    }
    return [values[c.name] for c in ACTIVITY_COLUMNS]


def build_activity_db(
    path: str,
    n_insert: int,
    m_delete: int = 0,
    *,
    delete_indices=None,
    vacuum: bool = False,
    secure_delete: bool = False,
    wal: bool = False,
    payload_pad: int = 0,
    checkpoint: bool = True,
) -> dict:
    """Create a synthetic Activity DB and return ground truth.

    Returns dict with: db_path, wal_path, inserted (guids), deleted (guids),
    live (guids), updated (list of (guid, old_etag, new_etag)).
    """
    con = sqlite3.connect(path)
    con.execute("PRAGMA page_size=4096")
    # This SQLite build defaults secure_delete=ON (zeroes freed content), which
    # would erase every carving target. Force OFF unless a test wants ON.
    con.execute("PRAGMA secure_delete=" + ("ON" if secure_delete else "OFF"))
    if wal:
        con.execute("PRAGMA journal_mode=WAL")
    con.execute(ACTIVITY_DDL)
    placeholders = ", ".join(["?"] * len(ACTIVITY_COLUMNS))
    con.executemany(
        f'INSERT INTO "Activity" VALUES ({placeholders})',
        [_row(i, payload_pad) for i in range(n_insert)],
    )
    con.commit()

    inserted = [make_guid(i) for i in range(n_insert)]

    if delete_indices is None:
        # delete a spread-out subset to scatter free blocks across pages
        delete_indices = list(range(0, n_insert, max(1, n_insert // m_delete))) if m_delete else []
        delete_indices = delete_indices[:m_delete]
    deleted = [make_guid(i) for i in delete_indices]
    for i in delete_indices:
        con.execute('DELETE FROM "Activity" WHERE "Id"=?', (make_guid(i),))
    con.commit()

    if vacuum:
        con.execute("VACUUM")
        con.commit()

    if wal and checkpoint:
        con.execute("PRAGMA wal_checkpoint(FULL)")

    con.close()

    live = [g for g in inserted if g not in set(deleted)]
    return {
        "db_path": path,
        "wal_path": path + "-wal",
        "inserted": inserted,
        "deleted": deleted,
        "live": live,
        "delete_indices": delete_indices,
    }


@pytest.fixture
def make_activity_db(tmp_path):
    """Factory fixture: build a synthetic DB under a temp dir."""

    def factory(name="ActivitiesCache.db", **kwargs):
        path = str(tmp_path / name)
        return build_activity_db(path, **kwargs)

    return factory
