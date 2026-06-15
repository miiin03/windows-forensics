"""분석 파이프라인 오케스트레이션 — UI '분석 시작'(/analyze) · 산출물 출력(/export).

server.py(로컬 HTTP) 와 app.py(pywebview JS API) 가 공통으로 호출한다.
parser(python-evtx)는 무거운 선택 의존이라 함수 안에서 지연 import → server import 안전.
"""
from __future__ import annotations

import json
import os

import sys

from .store.store import open_db, insert_events
from .agent.tools_query import summarize_stats
from .agent.tools_analysis import find_security_events
from .ml.anomaly import run_anomaly_detection
from .paths import default_db_path, resource_base


def analyze_evtx(
    path: str,
    db_path: str | None = None,
    replace: bool = True,
    window_minutes: int = 60,
    contamination: float = 0.02,
    run_ml: bool = True,
) -> dict:
    """.evtx 파싱 → SQLite 적재 → (옵션) 이상탐지. UI '분석 시작' 버튼 백엔드.

    replace=True 면 기존 events 를 비우고 새로 적재(단일 사건 조사 기본값).
    반환: {"ok", "file", "records", "replaced", "stats", "anomaly"} 또는 {"ok":False,"error"}.
    """
    db_path = db_path or default_db_path()
    if not path or not os.path.exists(path):
        return {"ok": False, "error": f"파일을 찾을 수 없습니다: {path}"}

    from .parser.evtx_parser import parse_evtx  # 지연 import (python-evtx)

    try:
        records = parse_evtx(path)
    except Exception as e:  # 손상 파일 등
        return {"ok": False, "error": f"EVTX 파싱 실패: {type(e).__name__}: {e}"}

    os.makedirs(os.path.dirname(os.path.abspath(db_path)) or ".", exist_ok=True)
    conn = open_db(db_path)
    try:
        if replace:
            conn.execute("DELETE FROM events")
            conn.commit()
        inserted = insert_events(conn, records)

        anomaly = None
        if run_ml and inserted:
            anomaly = run_anomaly_detection(
                conn, window_minutes=window_minutes, contamination=contamination
            )
        # 규칙 기반 고위험 탐지(1102 로그삭제/4720 계정생성/7045 서비스 등)는 ML 학습 여부와
        # 무관하게 항상 수행 — 데이터가 적어 ML이 쉬어도 고위험 정황은 놓치지 않는다.
        sec = find_security_events(conn)
        if anomaly is None:
            anomaly = {"ok": True, "fitted": False, "high_risk": False,
                       "windows": 0, "anomaly_windows": 0, "anomalies": []}
        anomaly["high_risk"] = bool(anomaly.get("high_risk")) or sec["high_risk"]
        anomaly["security_findings"] = sec["findings"]

        stats = summarize_stats(conn)
    finally:
        conn.close()

    return {
        "ok": True,
        "file": os.path.basename(path),
        "records": inserted,
        "replaced": replace,
        "stats": stats,
        "anomaly": anomaly,
    }


def analyze_auto(channel: str = "Security", db_path: str | None = None, **kw) -> dict:
    """내 PC 이벤트 로그를 자동 수집·분석. 라이브 로그는 잠겨 있어 wevtutil 로 복사본을 내보낸 뒤 파싱.

    Windows 전용. Security 채널 내보내기는 보통 관리자 권한 필요 → 실패 시 안내.
    """
    if os.name != "nt":
        return {"ok": False, "error": "자동 분석은 Windows 에서만 가능합니다(WSL/Linux 불가). 경로 분석을 쓰세요."}

    import subprocess
    import tempfile

    tmp = os.path.join(tempfile.gettempdir(), f"_evtx_auto_{channel}.evtx")
    try:
        if os.path.exists(tmp):
            os.remove(tmp)
    except OSError:
        pass
    try:
        # 라이브 채널은 EventLog 서비스가 잠금 → 복사본 내보내기(epl)
        subprocess.run(
            ["wevtutil", "epl", channel, tmp, "/ow:true"],
            check=True, capture_output=True, timeout=180,
        )
    except FileNotFoundError:
        return {"ok": False, "error": "wevtutil 을 찾을 수 없습니다(Windows 도구)."}
    except subprocess.CalledProcessError as e:
        # 한국어 Windows 의 wevtutil 출력은 cp949(mbcs) → utf-8 로 디코드하면 깨짐
        raw = e.stderr or b""
        for enc in ("mbcs", "cp949", "utf-8"):
            try:
                msg = raw.decode(enc).strip()
                break
            except (LookupError, UnicodeDecodeError):
                msg = raw.decode("utf-8", "replace").strip()
        msg = msg or str(e)
        return {"ok": False,
                "error": "내 PC 보안 로그 수집 실패 — 관리자 권한으로 서버를 실행하세요. "
                         f"(wevtutil: {msg})"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "이벤트 로그 내보내기 시간 초과."}

    if not os.path.exists(tmp):
        return {"ok": False, "error": "내보낸 로그 파일이 생성되지 않았습니다."}

    result = analyze_evtx(tmp, db_path=db_path, **kw)
    if result.get("ok"):
        result["file"] = f"{channel}.evtx (내 PC 자동 수집)"
    return result


def run_anomaly(
    db_path: str | None = None,
    window_minutes: int = 60,
    contamination: float = 0.02,
) -> dict:
    """이미 적재된 events 에 대해 이상탐지만 재실행. UI run_anomaly()/POST /anomaly."""
    db_path = db_path or default_db_path()
    if not os.path.exists(db_path):
        return {"ok": False, "error": "이벤트 DB가 없습니다. 먼저 EVTX를 분석(적재)하세요."}
    conn = open_db(db_path)
    try:
        return run_anomaly_detection(
            conn, window_minutes=window_minutes, contamination=contamination
        )
    finally:
        conn.close()


def export_events(db_path: str | None = None, limit: int | None = None) -> dict:
    """정규화 이벤트 최종 산출물(JSON 직렬화 가능 dict). UI 다운로드/공유용.

    event_data 는 원본 dict 로 파싱해 실어 보낸다(감사 추적).
    반환: {"ok", "count", "stats", "events": [...]}.
    """
    db_path = db_path or default_db_path()
    if not os.path.exists(db_path):
        return {"ok": False, "error": "이벤트 DB가 없습니다.", "count": 0, "events": []}

    conn = open_db(db_path)
    try:
        sql = "SELECT * FROM events ORDER BY time_utc"
        params: tuple = ()
        if limit:
            sql += " LIMIT ?"
            params = (limit,)
        rows = conn.execute(sql, params).fetchall()
        stats = summarize_stats(conn)
    finally:
        conn.close()

    events = []
    for r in rows:
        e = dict(r)
        raw = e.get("event_data")
        if raw:
            try:
                e["event_data"] = json.loads(raw)
            except (ValueError, TypeError):
                pass  # 원본 문자열 유지
        events.append(e)

    return {"ok": True, "count": len(events), "stats": stats, "events": events}


# EventID → 사람이 읽는 라벨(통합 타임라인 표시용)
_EVTX_LABEL = {
    4624: "로그온 성공", 4625: "로그온 실패", 4634: "로그오프", 4647: "로그오프",
    4672: "특수권한 부여", 4688: "프로세스 생성", 4720: "계정 생성",
    4722: "계정 활성화", 4724: "비밀번호 재설정", 4728: "관리자그룹 추가",
    4732: "관리자그룹 추가", 4756: "관리자그룹 추가", 4768: "Kerberos TGT",
    4769: "Kerberos TGS", 4771: "Kerberos 사전인증 실패", 4776: "NTLM 자격증명 검증",
    1102: "감사 로그 삭제", 7045: "서비스 설치", 7034: "서비스 비정상 종료",
    4663: "개체 접근", 4656: "핸들 요청", 5140: "공유 접근", 5145: "공유 접근",
    5156: "네트워크 연결 허용",
}
_LOGON_TYPE = {
    2: "대화형", 3: "네트워크", 4: "배치", 5: "서비스", 7: "잠금해제",
    8: "네트워크(평문)", 9: "새자격증명", 10: "원격데스크톱(RDP)", 11: "캐시된대화형",
}


def export_timeline(db_path: str | None = None) -> dict:
    """EVTX 이벤트를 part-1 타임라인 스키마(activities[], artifact="evtx")로 변환.

    뷰어가 part-1 활동과 같은 타임라인/24시계에 시간순으로 합쳐 렌더하기 위함(통합 타임라인 B).
    반환: {"ok", "meta": {...}, "activities": [...]}.
    """
    db_path = db_path or default_db_path()
    if not os.path.exists(db_path):
        return {"ok": False, "error": "이벤트 DB가 없습니다.", "activities": []}

    conn = open_db(db_path)
    try:
        rows = conn.execute(
            "SELECT pk, event_id, provider, category, account, source_ip, logon_type, "
            "time_kst, is_anomaly FROM events WHERE time_kst IS NOT NULL ORDER BY time_utc"
        ).fetchall()
        stats = summarize_stats(conn)
    finally:
        conn.close()

    activities = []
    carved = 0  # 여기선 '비정상(ML)'을 carved 자리로 매핑해 뷰어가 강조하도록
    for r in rows:
        eid = r["event_id"]
        label = _EVTX_LABEL.get(eid, f"이벤트 {eid}")
        acct = r["account"]
        lt = r["logon_type"]
        title = label + (f" — {acct}" if acct else "")
        if lt is not None:
            title += f" (타입{lt} {_LOGON_TYPE.get(lt, '')})".rstrip()

        detail = [f"EventID {eid}"]
        if r["source_ip"]:
            detail.append(f"출발지 {r['source_ip']}")
        is_anom = r["is_anomaly"] == 1
        if is_anom:
            detail.append("⚠ ML 이상구간")
            carved += 1

        activities.append({
            "id": f"evtx_{r['pk']}",
            "artifact": "evtx",
            # 매핑 안 된 EventID 는 evtx_other 로(뷰어가 회색 처리)
            "category": r["category"] or "evtx_other",
            "source": "carved" if is_anom else "normal",  # 이상=점선/강조 재사용
            "source_browser": None,
            "payload_format": "evtx",
            "confidence": "high",
            "decrypted": None,
            "app_id": r["provider"],
            "app_name": r["provider"] or "Windows Security",
            "title": title,
            "url": None,
            "detail": " · ".join(detail),
            "secret_value": None,
            "start_time_kst": r["time_kst"],
            "end_time_kst": None,
            "last_modified_kst": r["time_kst"],
            "raw_payload_b64": None,
        })

    meta = {
        "tool": "EVTX AI Investigator",
        "version": "0.3",
        "sources": [{"artifact": "evtx", "path": db_path, "records": len(activities)}],
        "timezone": "Asia/Seoul (UTC+9)",
        "stats": {
            "total": len(activities), "normal": len(activities) - carved,
            "carved": carved, "encrypted_skipped": 0, "decrypted_ok": 0,
            "by_artifact": {"evtx": len(activities)},
            "by_event_id": stats.get("by_event_id", {}),
        },
    }
    return {"ok": True, "meta": meta, "activities": activities}


def _timeline_engine_root() -> str:
    """vendored part-1 엔진(windows-timeline) 루트."""
    return os.path.join(resource_base(), "windows-timeline")


def run_timeline(db_path: str | None = None) -> dict:
    """part-1 엔진(windows-timeline)을 실행해 사용자 활동 타임라인을 생성. '분석 시작'(part-1).

    `python -m engine --ui` 와 동일(ActivitiesCache.db 자동탐색 또는 db_path 지정).
    엔진이 없거나 실패하면 동봉 샘플(timeline_result.sample.json)로 폴백 → 데모 항상 동작.
    반환: part-1 UI 계약 {meta, activities:[...]} + {"ok", "source": "engine"|"sample"|...}.
    """
    # 시연용: db="demo" → 동봉 합성 ActivitiesCache.db 를 실제 엔진으로 파싱(JSON 주입 아님)
    if db_path == "demo":
        demo = os.path.join(resource_base(), "sample", "demo_ActivitiesCache.db")
        if os.path.exists(demo):
            db_path = demo
        else:
            return demo_timeline()  # db 없으면 JSON 샘플 폴백

    eng_root = _timeline_engine_root()
    if os.path.isdir(eng_root):
        if eng_root not in sys.path:
            sys.path.insert(0, eng_root)
        try:
            from engine.cli import build_parser, run  # vendored part-1 엔진
            argv = ["--ui"] + ([db_path] if db_path else [])
            args = build_parser().parse_args(argv)
            obj = run(args)
            if obj and obj.get("activities"):
                return {"ok": True, "source": "engine", **obj}
        except Exception as e:
            # 엔진 크래시/미발견 → 샘플 폴백(데모 보호). 사유 첨부.
            fallback = _timeline_sample()
            if fallback:
                fallback["ok"] = True
                fallback["source"] = "sample"
                fallback["engine_error"] = f"{type(e).__name__}: {e}"
                return fallback
            return {"ok": False, "error": f"타임라인 엔진 오류: {e}", "activities": []}

    fb = _timeline_sample()
    if fb:
        fb["ok"] = True
        fb["source"] = "sample"
        return fb
    return {"ok": False, "error": "part-1 타임라인 엔진/샘플을 찾을 수 없습니다.", "activities": []}


def demo_timeline() -> dict:
    """시연용 part-1 타임라인 샘플(EVTX 샘플과 시각 정합)을 강제로 반환. 실제 엔진 우회."""
    s = _timeline_sample()
    if s:
        s["ok"] = True
        s["source"] = "demo"
        return s
    return {"ok": False, "error": "데모 샘플(sample/timeline_result.sample.json)을 찾을 수 없습니다.",
            "activities": []}


def _timeline_sample() -> dict | None:
    """동봉 part-1 샘플 JSON 로드(폴백용)."""
    for p in (
        os.path.join(resource_base(), "sample", "timeline_result.sample.json"),
        os.path.join(_timeline_engine_root(), "sample", "timeline_result.sample.json"),
    ):
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    return json.load(f)
            except (ValueError, OSError):
                continue
    return None
