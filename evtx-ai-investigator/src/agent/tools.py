"""AI 조사관 도구 레지스트리 + 스키마. DESIGN.md §6.1.

실제 조회/집계는 tools_query / tools_analysis 에 구현(결정적).
여기서는 (1) conn 을 바인딩한 호출 레지스트리, (2) LLM tool-calling 용 JSON 스키마를 제공.
LLM 은 '어떤 도구를 언제 쓸지'만 선택 → 환각 차단, 감사 추적 가능.
"""
from __future__ import annotations

import functools

from .tools_query import (
    search_events,
    get_event_detail,
    get_timeline,
    summarize_stats,
)
from .tools_analysis import analyze_logons, find_security_events


def get_anomalies(conn, threshold=None, top_n=10):
    """ML(Isolation Forest)이 비정상으로 플래그한 시간 윈도우 목록.

    ml.anomaly.run_anomaly_detection 이 events.window_id/anomaly_score/is_anomaly 를
    채운다. 윈도우 단위로 묶어 비정상 점수 오름차순(낮을수록 비정상)으로 반환.
    아직 탐지 미실행(전부 NULL)이면 빈 결과 + note.
    """
    cur = conn.execute(
        "SELECT window_id, MIN(time_kst) AS start_kst, MAX(time_kst) AS end_kst, "
        "       COUNT(*) AS n_events, MIN(anomaly_score) AS anomaly_score "
        "FROM events WHERE is_anomaly = 1 AND window_id IS NOT NULL "
        "GROUP BY window_id ORDER BY anomaly_score ASC LIMIT ?",
        (top_n,),
    )
    windows = [dict(r) for r in cur.fetchall()]

    # 각 비정상 윈도우의 주요 이벤트(category) 분포를 덧붙임 (조사 단서)
    for w in windows:
        cat = conn.execute(
            "SELECT category, COUNT(*) c FROM events "
            "WHERE window_id = ? AND category IS NOT NULL "
            "GROUP BY category ORDER BY c DESC",
            (w["window_id"],),
        ).fetchall()
        w["categories"] = {r["category"]: r["c"] for r in cat}

    out = {"count": len(windows), "anomalies": windows}
    if not windows:
        flagged = conn.execute(
            "SELECT COUNT(*) FROM events WHERE is_anomaly IS NOT NULL"
        ).fetchone()[0]
        out["note"] = (
            "비정상 윈도우 없음" if flagged
            else "ML 이상탐지 미실행 — 먼저 /anomaly(또는 /analyze)로 탐지를 수행하세요"
        )
    return out


# conn 미바인딩 원본(첫 인자 conn). investigator 가 build_registry 로 바인딩.
_TOOLS = {
    "search_events": search_events,
    "analyze_logons": analyze_logons,
    "get_anomalies": get_anomalies,
    "get_event_detail": get_event_detail,
    "get_timeline": get_timeline,
    "summarize_stats": summarize_stats,
    "find_security_events": find_security_events,
}


def build_registry(conn):
    """conn 을 1번째 인자로 바인딩한 {name: callable(**kwargs)} 반환.

    investigator 가 LLM 의 도구 호출(name, arguments)을 받아 이 레지스트리로 실행.
    """
    return {name: functools.partial(fn, conn) for name, fn in _TOOLS.items()}


# Ollama tool-calling 에 넘길 도구 스펙(§9 단순 스키마 원칙: 인자 최소화 + 호출 조건 명시).
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_events",
            "description": "조건(시간범위·EventID·계정)으로 이벤트를 검색. 특정 로그를 찾아달라 할 때.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start": {"type": "string", "description": "시작 시각 UTC ISO-8601"},
                    "end": {"type": "string", "description": "끝 시각 UTC ISO-8601"},
                    "event_id": {"type": "integer", "description": "Windows EventID 예:4625"},
                    "account": {"type": "string", "description": "계정명"},
                    "limit": {"type": "integer", "description": "최대 건수(기본 100)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_logons",
            "description": "구간 로그온 성공/실패(4624/4625) 통계 + 무차별대입 의심. 로그인 시도/실패/브루트포스를 물으면.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start": {"type": "string", "description": "시작 시각 UTC ISO-8601"},
                    "end": {"type": "string", "description": "끝 시각 UTC ISO-8601"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_anomalies",
            "description": "ML이 비정상으로 플래그한 시간 윈도우 목록. '이상한 점/의심 구간'을 물으면.",
            "parameters": {
                "type": "object",
                "properties": {
                    "top_n": {"type": "integer", "description": "상위 N개(기본 10)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_event_detail",
            "description": "단일 이벤트의 전체 원본 필드(EventData 포함). 특정 이벤트 상세를 물으면.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_pk": {"type": "integer", "description": "이벤트 기본키 pk"},
                },
                "required": ["event_pk"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_timeline",
            "description": "구간 이벤트를 시간순으로 요약. 사건 흐름/타임라인을 물으면.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start": {"type": "string", "description": "시작 시각 UTC ISO-8601"},
                    "end": {"type": "string", "description": "끝 시각 UTC ISO-8601"},
                    "event_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "포함할 EventID 목록(옵션)",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "summarize_stats",
            "description": "전체/구간 통계(EventID·category·계정 분포). 전반 요약/개요를 물으면.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start": {"type": "string", "description": "시작 시각 UTC ISO-8601"},
                    "end": {"type": "string", "description": "끝 시각 UTC ISO-8601"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_security_events",
            "description": "고위험 이벤트(1102 로그삭제/4720 계정생성/7045 서비스설치/4672 권한 등) 발생 위치. 침해/이상 흔적을 물으면.",
            "parameters": {
                "type": "object",
                "properties": {
                    "categories": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "대상 category(옵션). 예:['log_cleared','account']",
                    },
                },
            },
        },
    },
]
