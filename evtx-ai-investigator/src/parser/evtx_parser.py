"""EVTX 파싱 → 정규화 레코드.

python-evtx로 .evtx의 각 레코드를 읽어 공통 필드 + EventData(dict)로 정규화한다.
보안 이벤트 ID를 category로 매핑하고, 시각을 UTC/KST로 변환한다.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from Evtx.Evtx import Evtx
from lxml import etree

# Windows 이벤트 XML 네임스페이스
_NS = "http://schemas.microsoft.com/win/2004/08/events/event"
_KST = timezone(timedelta(hours=9))

# 포렌식 핵심 이벤트 ID → category 매핑 (DESIGN.md §4.1)
SECURITY_EVENT_CATEGORY: dict[int, str] = {
    4624: "logon_ok",        # 로그온 성공
    4625: "logon_fail",      # 로그온 실패
    4634: "logoff",
    4647: "logoff",
    4672: "priv",            # 특수 권한 부여(관리자)
    4688: "proc",            # 프로세스 생성
    4720: "account",         # 계정 생성
    4722: "account",         # 계정 활성화
    4724: "account",         # 비밀번호 재설정
    4728: "group_add",       # 권한 그룹 멤버 추가
    4732: "group_add",
    4756: "group_add",
    4768: "kerberos",        # TGT 요청
    4769: "kerberos",        # TGS 요청
    4771: "kerberos",        # 사전인증 실패
    4776: "ntlm",            # 자격증명 검증
    1102: "log_cleared",     # 감사 로그 삭제 (안티포렌식)
    7045: "service",         # 서비스 설치
    7034: "service",         # 서비스 비정상 종료
}

_LEVEL_NAME = {0: "Information", 1: "Critical", 2: "Error", 3: "Warning",
               4: "Information", 5: "Verbose"}


def _q(tag: str) -> str:
    """네임스페이스 수식 태그명."""
    return f"{{{_NS}}}{tag}"


def _text(el):
    return el.text if el is not None else None


def _to_times(system_time: str | None):
    """SystemTime(UTC) → (utc_iso, kst_iso). 실패 시 (None, None)."""
    if not system_time:
        return None, None
    try:
        dt = datetime.fromisoformat(system_time.replace("Z", "+00:00"))
        utc = dt.astimezone(timezone.utc)
        return utc.isoformat(), utc.astimezone(_KST).isoformat()
    except ValueError:
        return None, None


def _norm(value: str | None) -> str | None:
    """'-' / 빈 문자열 → None."""
    if value is None:
        return None
    v = value.strip()
    return None if v in ("", "-") else v


def _parse_record_xml(xml: str) -> dict | None:
    """단일 레코드 XML → 정규화 dict. 파싱 불가 시 None."""
    root = etree.fromstring(xml.encode("utf-8"))
    system = root.find(_q("System"))
    if system is None:
        return None

    eid_el = system.find(_q("EventID"))
    try:
        event_id = int(_text(eid_el)) if eid_el is not None else None
    except (TypeError, ValueError):
        event_id = None

    prov = system.find(_q("Provider"))
    tc = system.find(_q("TimeCreated"))
    system_time = tc.get("SystemTime") if tc is not None else None
    time_utc, time_kst = _to_times(system_time)

    level_el = system.find(_q("Level"))
    try:
        level = _LEVEL_NAME.get(int(_text(level_el)), _text(level_el))
    except (TypeError, ValueError):
        level = _text(level_el)

    # EventData → {Name: value}
    data: dict[str, str] = {}
    ed = root.find(_q("EventData"))
    if ed is not None:
        for d in ed.findall(_q("Data")):
            name = d.get("Name")
            if name:
                data[name] = d.text

    account = _norm(data.get("TargetUserName")) or _norm(data.get("SubjectUserName"))
    source_ip = _norm(data.get("IpAddress"))
    try:
        logon_type = int(data["LogonType"]) if data.get("LogonType") else None
    except (TypeError, ValueError):
        logon_type = None

    return {
        "event_id": event_id,
        "channel": _text(system.find(_q("Channel"))),
        "provider": prov.get("Name") if prov is not None else None,
        "level": level,
        "computer": _text(system.find(_q("Computer"))),
        "time_utc": time_utc,
        "time_kst": time_kst,
        "category": SECURITY_EVENT_CATEGORY.get(event_id),
        "account": account,
        "source_ip": source_ip,
        "logon_type": logon_type,
        "event_data": json.dumps(data, ensure_ascii=False) if data else None,
        "window_id": None,
        "anomaly_score": None,
        "is_anomaly": None,
    }


def parse_evtx(path: str) -> list[dict]:
    """단일 .evtx 파일을 정규화된 이벤트 레코드 리스트로 반환한다.

    손상되어 파싱 불가한 레코드는 건너뛴다(포렌식 best-effort).
    """
    records: list[dict] = []
    with Evtx(path) as log:
        for rec in log.records():
            try:
                row = _parse_record_xml(rec.xml())
            except (etree.XMLSyntaxError, ValueError, KeyError):
                continue
            if row is not None:
                records.append(row)
    return records
