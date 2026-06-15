"""SQLite 통합 이벤트 스토어 적재/조회. DESIGN.md §4.2, §7."""
from __future__ import annotations

import sqlite3

from .schema import SCHEMA_SQL

# events 테이블 적재 컬럼 순서 (parser 출력 dict 키와 일치)
_COLUMNS = [
    "event_id", "channel", "provider", "level", "computer",
    "time_utc", "time_kst", "category", "account", "source_ip",
    "logon_type", "event_data", "window_id", "anomaly_score", "is_anomaly",
]


def open_db(db_path: str = "db/events.sqlite") -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    return conn


def insert_events(conn: sqlite3.Connection, records: list[dict]) -> int:
    """정규화 레코드 일괄 적재. 반환: 적재 건수."""
    if not records:
        return 0
    placeholders = ", ".join("?" * len(_COLUMNS))
    sql = f"INSERT INTO events ({', '.join(_COLUMNS)}) VALUES ({placeholders})"
    rows = [[r.get(c) for c in _COLUMNS] for r in records]
    conn.executemany(sql, rows)
    conn.commit()
    return len(rows)


def query_events(
    conn: sqlite3.Connection,
    start: str | None = None,
    end: str | None = None,
    event_id: int | None = None,
    account: str | None = None,
    channel: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """시간범위·event_id·account·channel 조건으로 조회 (도구 계층이 사용).

    start/end 는 UTC ISO-8601 문자열 (time_utc 기준 비교).
    """
    where, params = [], []
    if start:
        where.append("time_utc >= ?"); params.append(start)
    if end:
        where.append("time_utc <= ?"); params.append(end)
    if event_id is not None:
        where.append("event_id = ?"); params.append(event_id)
    if account:
        where.append("account = ?"); params.append(account)
    if channel:
        where.append("channel = ?"); params.append(channel)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    params.append(limit)
    cur = conn.execute(
        f"SELECT * FROM events {clause} ORDER BY time_utc LIMIT ?", params
    )
    return [dict(r) for r in cur.fetchall()]


def event_id_distribution(conn: sqlite3.Connection) -> dict[int, int]:
    """event_id별 건수 (통계용)."""
    cur = conn.execute(
        "SELECT event_id, COUNT(*) c FROM events GROUP BY event_id ORDER BY c DESC"
    )
    return {row["event_id"]: row["c"] for row in cur.fetchall()}
