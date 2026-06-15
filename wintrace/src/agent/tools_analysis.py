"""포렌식 분석 도구 — 로그온 분석/고위험 이벤트 탐지. DESIGN.md §6.1.

집계·휴리스틱으로 침해 정황을 결정적으로 산출. LLM은 해석만(환각 차단).
첫 인자는 항상 conn(sqlite3.Connection).
"""
from __future__ import annotations

# 무차별대입 의심 임계치: 한 주체(계정/IP)의 4625 실패 건수
_BRUTE_FORCE_FAIL_THRESHOLD = 5

# find_security_events 기본 대상 category (증거인멸·백도어·권한상승·자격증명공격)
_DEFAULT_RISK_CATEGORIES = [
    "log_cleared", "account", "service", "priv", "group_add", "kerberos", "ntlm",
]


def analyze_logons(conn, start=None, end=None):
    """구간 로그온 성공(4624)/실패(4625) 통계 + 무차별대입 의심 주체.

    반환:
      {"success_total", "fail_total",
       "by_account": {acct: {"ok", "fail"}},
       "by_source_ip": {ip: {"ok", "fail"}},
       "brute_force_suspects": [ {"account", "source_ip", "fail_count"} ]}
    휴리스틱: (account 또는 source_ip)별 4625 실패 >= 5 → suspect, fail_count 내림차순.
    """
    where, params = ["event_id IN (4624, 4625)"], []
    if start:
        where.append("time_utc >= ?"); params.append(start)
    if end:
        where.append("time_utc <= ?"); params.append(end)
    clause = "WHERE " + " AND ".join(where)
    cur = conn.execute(
        f"SELECT pk, time_kst, event_id, category, account, source_ip, logon_type "
        f"FROM events {clause} ORDER BY time_utc", params
    )

    by_account: dict[str, dict[str, int]] = {}
    by_source_ip: dict[str, dict[str, int]] = {}
    success_total = fail_total = 0
    # 실패 다발 탐지용 카운터
    fail_by_account: dict[str, int] = {}
    fail_by_ip: dict[str, int] = {}
    events: list[dict] = []  # 근거용 샘플(최대 50)

    rows = cur.fetchall()
    for r in rows:
        if len(events) < 50:
            events.append({
                "pk": r["pk"], "time_kst": r["time_kst"], "event_id": r["event_id"],
                "category": r["category"], "account": r["account"],
                "source_ip": r["source_ip"], "logon_type": r["logon_type"],
            })
        is_ok = r["event_id"] == 4624
        key = "ok" if is_ok else "fail"
        if is_ok:
            success_total += 1
        else:
            fail_total += 1
        acct = r["account"]
        ip = r["source_ip"]
        if acct is not None:
            by_account.setdefault(acct, {"ok": 0, "fail": 0})[key] += 1
            if not is_ok:
                fail_by_account[acct] = fail_by_account.get(acct, 0) + 1
        if ip is not None:
            by_source_ip.setdefault(ip, {"ok": 0, "fail": 0})[key] += 1
            if not is_ok:
                fail_by_ip[ip] = fail_by_ip.get(ip, 0) + 1

    suspects = []
    for acct, n in fail_by_account.items():
        if n >= _BRUTE_FORCE_FAIL_THRESHOLD:
            suspects.append({"account": acct, "source_ip": None, "fail_count": n})
    for ip, n in fail_by_ip.items():
        if n >= _BRUTE_FORCE_FAIL_THRESHOLD:
            suspects.append({"account": None, "source_ip": ip, "fail_count": n})
    suspects.sort(key=lambda s: s["fail_count"], reverse=True)

    return {
        "success_total": success_total,
        "fail_total": fail_total,
        "by_account": by_account,
        "by_source_ip": by_source_ip,
        "brute_force_suspects": suspects,
        "events": events,
    }


def find_security_events(conn, categories=None):
    """고위험 이벤트(로그삭제/계정생성/서비스설치/권한/그룹추가) 발생 위치를 탐지한다.

    반환:
      {"findings": [ {"category", "event_ids", "count",
                      "first_time_kst", "last_time_kst", "sample_pks"(<=5)} ],
       "high_risk": bool}   # log_cleared 1건이라도 있으면 True(증거 인멸 정황)
    findings 는 count 내림차순.
    """
    cats = categories or _DEFAULT_RISK_CATEGORIES
    findings = []
    for cat in cats:
        cur = conn.execute(
            "SELECT pk, event_id, time_kst FROM events "
            "WHERE category = ? ORDER BY time_utc",
            (cat,),
        )
        rows = cur.fetchall()
        if not rows:
            continue
        event_ids = sorted({r["event_id"] for r in rows if r["event_id"] is not None})
        findings.append({
            "category": cat,
            "event_ids": event_ids,
            "count": len(rows),
            "first_time_kst": rows[0]["time_kst"],
            "last_time_kst": rows[-1]["time_kst"],
            "sample_pks": [r["pk"] for r in rows[:5]],
        })
    findings.sort(key=lambda f: f["count"], reverse=True)
    high_risk = any(f["category"] == "log_cleared" for f in findings)
    return {"findings": findings, "high_risk": high_risk}
