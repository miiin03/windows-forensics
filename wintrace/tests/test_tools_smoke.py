"""M2 도구 스모크 테스트 — 실제 샘플 DB(db/events.sqlite)로 7개 도구 호출.

실행: 레포의 wintrace/ 에서  python -m tests.test_tools_smoke
"""
from __future__ import annotations

import json

from src.store.store import open_db
from src.agent.tools import build_registry, TOOL_SCHEMAS, _TOOLS


def _show(name, result):
    print(f"\n--- {name} ---")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def main():
    conn = open_db("db/events.sqlite")
    reg = build_registry(conn)

    # 레지스트리/스키마 정합성
    assert set(reg) == set(_TOOLS), "registry mismatch"
    assert {s["function"]["name"] for s in TOOL_SCHEMAS} == set(_TOOLS), "schema mismatch"

    _show("summarize_stats", reg["summarize_stats"]())
    _show("search_events(4625)", reg["search_events"](event_id=4625))
    _show("analyze_logons", reg["analyze_logons"]())
    _show("find_security_events", reg["find_security_events"]())
    _show("get_timeline", reg["get_timeline"]())
    _show("get_anomalies", reg["get_anomalies"]())

    # get_event_detail: 첫 이벤트 pk 로
    first_pk = conn.execute("SELECT MIN(pk) FROM events").fetchone()[0]
    _show(f"get_event_detail(pk={first_pk})", reg["get_event_detail"](first_pk))
    _show("get_event_detail(없는 pk)", reg["get_event_detail"](999999))

    print("\n[OK] 7개 도구 + 스키마 정합성 통과")


if __name__ == "__main__":
    main()
