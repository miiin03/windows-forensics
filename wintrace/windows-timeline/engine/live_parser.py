"""Read allocated (live) records via the stdlib sqlite3 engine, read-only.

This is the ONLY module that imports sqlite3. The carver never depends on it.
``immutable=1`` opens the on-disk image without locks and without applying the
WAL — so live counts reflect the committed main file. Pass ``immutable=False``
for a ``mode=ro`` open that DOES apply the WAL (used for the WAL-vs-disk diff).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field


@dataclass
class LiveRecord:
    table: str
    rowid: int
    values: dict
    source: str = "live"
    sources: list = field(default_factory=lambda: ["live"])


def open_ro(path: str, immutable: bool = True) -> sqlite3.Connection:
    """Open ``path`` strictly read-only (never modifies the evidence file)."""
    flag = "immutable=1" if immutable else "mode=ro"
    return sqlite3.connect(f"file:{path}?{flag}", uri=True)


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    cur = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    )
    return cur.fetchone() is not None


def read_activity(path: str, immutable: bool = True) -> list[LiveRecord]:
    """Read every row of the Activity table as LiveRecords."""
    con = open_ro(path, immutable)
    try:
        if not _table_exists(con, "Activity"):
            return []
        cur = con.execute('SELECT rowid AS _rowid, * FROM "Activity"')
        col_names = [d[0] for d in cur.description]
        records = []
        for row in cur:
            mapping = dict(zip(col_names, row))
            rowid = mapping.pop("_rowid")
            records.append(LiveRecord(table="Activity", rowid=rowid, values=mapping))
        return records
    finally:
        con.close()
