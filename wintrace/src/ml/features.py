"""피처 엔지니어링: 시간 윈도우 단위 집계. DESIGN.md §3.3, §4.3.

events 테이블을 고정 폭 시간 윈도우(기본 60분)로 묶어 윈도우별 피처 행렬을 만든다.
Isolation Forest(anomaly.py)의 입력이 된다. 윈도우 키는 time_utc 를 윈도우 폭으로
내림(floor)한 UTC ISO-8601 문자열 → 결정적(재현 가능), events.window_id 로도 그대로 적재.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

# 피처에 쓰는 이벤트ID (DESIGN.md §4.1)
_EID_FAIL = 4625        # 로그온 실패
_EID_OK = 4624          # 로그온 성공
_EID_PRIV = 4672        # 특수권한(관리자)
_EID_NEW_ACCOUNT = 4720  # 계정 생성
_EID_SERVICE = 7045     # 서비스 설치
_EID_LOG_CLEARED = 1102  # 감사 로그 삭제(안티포렌식)
_EID_KERB_FAIL = 4771   # Kerberos 사전인증 실패
_GROUP_ADD = (4728, 4732, 4756)  # 권한 그룹 멤버 추가

# 윈도우 단위로 집계해 만드는 수치 피처 컬럼(IsolationForest 입력 순서)
FEATURE_COLUMNS = [
    "n_events",
    "n_logon_fail",
    "n_logon_ok",
    "fail_ratio",
    "distinct_account",
    "distinct_source_ip",
    "n_priv",
    "n_new_account",
    "n_service",
    "n_group_add",
    "n_log_cleared",
    "n_kerb_fail",
    "hour",
    "is_off_hours",
    "is_weekend",
]


def window_key(time_utc: str | None, window_minutes: int = 60) -> str | None:
    """time_utc(UTC ISO-8601) → 윈도우 시작 시각 ISO-8601(윈도우 폭으로 내림). 실패 시 None."""
    if not time_utc:
        return None
    try:
        dt = datetime.fromisoformat(time_utc.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None
    width = window_minutes * 60
    epoch = int(dt.timestamp())
    floored = epoch - (epoch % width)
    return datetime.fromtimestamp(floored, tz=timezone.utc).isoformat()


def build_features(conn, window_minutes: int = 60) -> pd.DataFrame:
    """events 테이블 → 윈도우별 피처 행렬(DataFrame, index=window_id).

    각 행은 한 시간 윈도우. 컬럼은 FEATURE_COLUMNS(수치). 이벤트가 없으면 빈 DataFrame.
    """
    cur = conn.execute(
        "SELECT event_id, time_utc, account, source_ip FROM events WHERE time_utc IS NOT NULL"
    )
    rows = cur.fetchall()
    if not rows:
        return pd.DataFrame(columns=FEATURE_COLUMNS)

    buckets: dict[str, dict] = {}
    for r in rows:
        wid = window_key(r["time_utc"], window_minutes)
        if wid is None:
            continue
        b = buckets.get(wid)
        if b is None:
            b = buckets[wid] = {
                "n_events": 0, "n_logon_fail": 0, "n_logon_ok": 0,
                "n_priv": 0, "n_new_account": 0, "n_service": 0,
                "n_group_add": 0, "n_log_cleared": 0, "n_kerb_fail": 0,
                "accounts": set(), "ips": set(),
            }
        eid = r["event_id"]
        b["n_events"] += 1
        if eid == _EID_FAIL:
            b["n_logon_fail"] += 1
        elif eid == _EID_OK:
            b["n_logon_ok"] += 1
        if eid == _EID_PRIV:
            b["n_priv"] += 1
        elif eid == _EID_NEW_ACCOUNT:
            b["n_new_account"] += 1
        elif eid == _EID_SERVICE:
            b["n_service"] += 1
        elif eid in _GROUP_ADD:
            b["n_group_add"] += 1
        elif eid == _EID_LOG_CLEARED:
            b["n_log_cleared"] += 1
        elif eid == _EID_KERB_FAIL:
            b["n_kerb_fail"] += 1
        if r["account"]:
            b["accounts"].add(r["account"])
        if r["source_ip"]:
            b["ips"].add(r["source_ip"])

    records = {}
    for wid, b in buckets.items():
        logon_total = b["n_logon_ok"] + b["n_logon_fail"]
        start = datetime.fromisoformat(wid)
        records[wid] = {
            "n_events": b["n_events"],
            "n_logon_fail": b["n_logon_fail"],
            "n_logon_ok": b["n_logon_ok"],
            "fail_ratio": b["n_logon_fail"] / logon_total if logon_total else 0.0,
            "distinct_account": len(b["accounts"]),
            "distinct_source_ip": len(b["ips"]),
            "n_priv": b["n_priv"],
            "n_new_account": b["n_new_account"],
            "n_service": b["n_service"],
            "n_group_add": b["n_group_add"],
            "n_log_cleared": b["n_log_cleared"],
            "n_kerb_fail": b["n_kerb_fail"],
            "hour": start.hour,
            "is_off_hours": int(start.hour < 6 or start.hour >= 22),
            "is_weekend": int(start.weekday() >= 5),
        }

    df = pd.DataFrame.from_dict(records, orient="index")
    df.index.name = "window_id"
    return df[FEATURE_COLUMNS].sort_index()
