"""포렌식 질의 도구 — 검색/상세/타임라인/통계. DESIGN.md §6.1.

각 도구는 events 스토어를 결정적으로 조회·집계해 JSON 직렬화 가능한 dict를 반환한다.
LLM(AI 조사관)이 tool-calling으로 호출. 첫 인자는 항상 conn(sqlite3.Connection).
"""
from __future__ import annotations

import json

from ..store.store import query_events, event_id_distribution

# search_events / get_timeline 결과에 실어 보낼 요약 필드(원본 event_data는 detail에서만)
_SUMMARY_FIELDS = (
    "pk", "time_kst", "event_id", "category",
    "account", "source_ip", "logon_type", "computer",
)


def _pick(row: dict, fields) -> dict:
    return {k: row.get(k) for k in fields}


def search_events(conn, start=None, end=None, event_id=None, account=None, limit=100):
    """조건(시간범위·EventID·계정)으로 이벤트를 검색한다.

    반환: {"count": int, "events": [ {요약 필드}, ... ]}
    """
    rows = query_events(
        conn, start=start, end=end, event_id=event_id, account=account, limit=limit
    )
    return {"count": len(rows), "events": [_pick(r, _SUMMARY_FIELDS) for r in rows]}


def get_event_detail(conn, event_pk):
    """단일 이벤트의 전체 원본 필드를 반환한다(EventData는 dict로 파싱).

    못 찾으면 {"error": "not found", "pk": event_pk}.
    """
    cur = conn.execute("SELECT * FROM events WHERE pk = ?", (event_pk,))
    row = cur.fetchone()
    if row is None:
        return {"error": "not found", "pk": event_pk}
    detail = dict(row)
    raw = detail.get("event_data")
    if raw:
        try:
            detail["event_data"] = json.loads(raw)
        except (ValueError, TypeError):
            pass  # 파싱 불가 시 원본 문자열 유지
    return detail


def get_timeline(conn, start=None, end=None, event_ids=None):
    """구간 이벤트를 시간순으로 요약한다. event_ids 주어지면 해당 ID만.

    반환: {"count": int, "items": [ {time_kst, event_id, category, account}, ... ]}
    time_kst 오름차순, 최대 500건.
    """
    where, params = [], []
    if start:
        where.append("time_utc >= ?"); params.append(start)
    if end:
        where.append("time_utc <= ?"); params.append(end)
    if event_ids:
        marks = ",".join("?" * len(event_ids))
        where.append(f"event_id IN ({marks})"); params.extend(event_ids)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    cur = conn.execute(
        f"SELECT time_kst, event_id, category, account FROM events "
        f"{clause} ORDER BY time_utc LIMIT 500",
        params,
    )
    items = [dict(r) for r in cur.fetchall()]
    return {"count": len(items), "items": items}


def summarize_stats(conn, start=None, end=None):
    """전체/구간 통계(EventID·category·계정 분포, 시간 범위)를 반환한다.

    반환: {"total", "by_event_id", "by_category", "by_account"(상위 20), "time_range"}
    """
    where, params = [], []
    if start:
        where.append("time_utc >= ?"); params.append(start)
    if end:
        where.append("time_utc <= ?"); params.append(end)
    clause = ("WHERE " + " AND ".join(where)) if where else ""

    def _grouped(col, limit=None):
        lim = f" LIMIT {limit}" if limit else ""
        cur = conn.execute(
            f"SELECT {col} AS k, COUNT(*) AS c FROM events {clause} "
            f"GROUP BY {col} ORDER BY c DESC{lim}",
            params,
        )
        return {r["k"]: r["c"] for r in cur.fetchall() if r["k"] is not None}

    if clause:
        by_event_id = _grouped("event_id")
    else:
        by_event_id = event_id_distribution(conn)  # 인덱스 활용(전체)

    total = sum(by_event_id.values())
    cur = conn.execute(
        f"SELECT MIN(time_kst) AS lo, MAX(time_kst) AS hi FROM events {clause}", params
    )
    rng = cur.fetchone()
    return {
        "total": total,
        "by_event_id": by_event_id,
        "by_category": _grouped("category"),
        "by_account": _grouped("account", limit=20),
        "time_range": {"min_kst": rng["lo"], "max_kst": rng["hi"]},
    }
