"""SQLite 통합 이벤트 스토어 적재/조회. DESIGN.md §3.2, §7."""
from __future__ import annotations

import sqlite3

from .schema import SCHEMA_SQL


def open_db(db_path: str = "db/events.sqlite") -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    return conn


def insert_events(conn: sqlite3.Connection, records: list[dict]) -> int:
    """정규화 레코드 일괄 적재. 반환: 적재 건수."""
    raise NotImplementedError("M1에서 구현")


def query_events(conn: sqlite3.Connection, **filters) -> list[dict]:
    """시간범위·event_id·account·channel 등 조건으로 조회 (도구 계층이 사용)."""
    raise NotImplementedError("M2에서 구현")
