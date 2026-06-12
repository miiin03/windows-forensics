"""AI 조사관이 호출하는 포렌식 도구. DESIGN.md §6.

각 도구는 (1) 실제 데이터 조회/계산을 결정적으로 수행하고 (2) 구조화된 dict를 반환한다.
LLM은 '어떤 도구를 언제 쓸지'만 결정 → 환각 차단, 감사 추적 가능.
"""
from __future__ import annotations


def search_events(start=None, end=None, event_id=None, account=None, limit=100):
    """조건(시간범위·EventID·계정·채널)으로 이벤트를 검색한다.
    사용자가 특정 조건의 로그를 찾아달라고 할 때 호출."""
    raise NotImplementedError("M4")


def analyze_logons(start=None, end=None):
    """구간 내 로그온 성공/실패(4624/4625) 통계와 무차별대입 의심 구간을 반환한다.
    사용자가 로그인 시도/실패/무차별 대입을 물으면 호출."""
    raise NotImplementedError("M4")


def get_anomalies(threshold=None, top_n=10):
    """ML(Isolation Forest)이 비정상으로 플래그한 시간 윈도우 목록을 반환한다.
    사용자가 '이상한 점/의심스러운 구간'을 물으면 호출."""
    raise NotImplementedError("M4")


def get_event_detail(event_pk):
    """단일 이벤트의 전체 원본 필드(EventData 포함)를 반환한다."""
    raise NotImplementedError("M4")


def get_timeline(start=None, end=None, event_ids=None):
    """특정 구간의 이벤트를 시간순으로 요약해 반환한다."""
    raise NotImplementedError("M4")


def summarize_stats(start=None, end=None):
    """전체/구간 통계(이벤트 ID 분포, 계정별 활동 등)를 반환한다."""
    raise NotImplementedError("M4")


def find_security_events(categories=None):
    """고위험 이벤트(1102 로그삭제 / 4720 계정생성 / 7045 서비스설치 / 4672 권한 등)
    발생 여부·위치를 반환한다."""
    raise NotImplementedError("M4")


# Ollama tool-calling에 넘길 도구 스펙(이름·설명·파라미터)은 investigator.py에서 구성.
TOOL_REGISTRY = {
    "search_events": search_events,
    "analyze_logons": analyze_logons,
    "get_anomalies": get_anomalies,
    "get_event_detail": get_event_detail,
    "get_timeline": get_timeline,
    "summarize_stats": summarize_stats,
    "find_security_events": find_security_events,
}
