"""시연용 합성 ActivitiesCache.db 생성기.

part-1 엔진(windows-timeline)이 실제로 파싱하는 Activity 테이블을 만들어, EVTX 1102 샘플
(2019-03-20 08:35 감사로그 삭제)과 시각이 맞물리는 사용자 활동 스토리를 심는다.
→ "🎬 데모"가 JSON 주입이 아니라 진짜 엔진으로 이 db 를 파싱하게 한다.

실행:  python sample/build_demo_db.py   →  sample/demo_ActivitiesCache.db
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

_KST = timezone(timedelta(hours=9))
_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo_ActivitiesCache.db")

# schema.py ACTIVITY_COLUMNS 선언 순서(31)
_COLS = [
    "Id", "AppId", "PackageIdHash", "AppActivityId", "ActivityType", "ActivityStatus",
    "ParentActivityId", "Tag", "Group", "MatchId", "LastModifiedTime", "ExpirationTime",
    "Payload", "Priority", "IsLocalOnly", "PlatformDeviceId", "DdsDeviceId", "CreatedInCloud",
    "StartTime", "EndTime", "LastModifiedOnClient", "GroupAppActivityId", "ClipboardPayload",
    "EnterpriseId", "OriginalPayload", "UserActionState", "IsRead",
    "OriginalLastModifiedOnClient", "GroupItems", "LocalExpirationTime", "ETag",
]


def _appid(exe_path: str) -> str:
    return json.dumps([{"platform": "windows_win32", "application": exe_path}])


def _payload(display: str, uri: str | None = None) -> bytes:
    d = {"displayText": display}
    if uri:
        d["activationUri"] = uri  # _url 정규식이 payload 문자열에서 URL 추출
    return json.dumps(d, ensure_ascii=False).encode("utf-8")


def _epoch(kst_hms: str) -> int:
    """'2019-03-20 08:01:00' (KST) → unix epoch seconds."""
    dt = datetime.strptime(kst_hms, "%Y-%m-%d %H:%M:%S").replace(tzinfo=_KST)
    return int(dt.timestamp())


# (시각KST, exe경로, ActivityType, displayText, activationUri)
_STORY = [
    ("2019-03-20 08:01:00", r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE",
     5, "분기보고서.docx", None),
    ("2019-03-20 08:12:00", r"C:\Program Files\Google\Chrome\Application\chrome.exe",
     5, "사내 위키 - 분기 일정", "https://wiki.corp.local/q1"),
    ("2019-03-20 08:20:00", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
     5, "검색: how to clear windows security event log",
     "https://www.bing.com/search?q=clear+windows+security+event+log"),
    ("2019-03-20 08:24:00", r"C:\Program Files\Google\Chrome\Application\chrome.exe",
     5, "DefenderControl.zip 다운로드", "https://files.example.net/tools/DefenderControl.zip"),
    ("2019-03-20 08:26:30", r"C:\Windows\System32\cmd.exe",
     5, "cmd.exe /c wevtutil cl Security", None),
    ("2019-03-20 08:34:40", r"C:\Windows\explorer.exe",
     5, "급여명세_전직원.xlsx", "file:///C:/HR/급여명세_전직원.xlsx"),
]


def build(path: str = _OUT) -> str:
    if os.path.exists(path):
        os.remove(path)
    con = sqlite3.connect(path)
    try:
        cols_ddl = ", ".join(f'"{c}"' for c in _COLS)
        con.execute(f'CREATE TABLE "Activity" ({cols_ddl})')
        placeholders = ", ".join("?" * len(_COLS))
        ins = f'INSERT INTO "Activity" ({", ".join(chr(34)+c+chr(34) for c in _COLS)}) VALUES ({placeholders})'
        for i, (kst, exe, atype, disp, uri) in enumerate(_STORY, 1):
            ts = _epoch(kst)
            row = {c: None for c in _COLS}
            row["Id"] = bytes([i]) + b"\x00" * 15           # 16바이트 GUID
            row["AppId"] = _appid(exe)
            row["ActivityType"] = atype
            row["ActivityStatus"] = 1
            row["Payload"] = _payload(disp, uri)
            row["StartTime"] = ts
            row["EndTime"] = ts + 300
            row["LastModifiedTime"] = ts + 300
            row["LastModifiedOnClient"] = ts
            row["ETag"] = i
            con.execute(ins, [row[c] for c in _COLS])
        con.commit()
    finally:
        con.close()
    return path


if __name__ == "__main__":
    out = build()
    print(f"생성됨: {out}")
