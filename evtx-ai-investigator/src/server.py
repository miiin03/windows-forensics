"""로컬 질의 브리지 서버 — 팀원 UI(copilot)가 fetch 로 호출. DESIGN.md §6.2.

의존성 0 (Python 표준 라이브러리 http.server). 127.0.0.1 단일 클라이언트 localhost 전용.
copilot 의 Anthropic fetch 를 이 서버 `/ask` 로 바꾸면 로컬 엔진(EVTX + 로컬 LLM)에 연결된다.

엔드포인트:
  GET  /health             → {"ok": true, "db": "<경로>", "events": <건수>}
  POST /ask {question}     → {"answer", "tool_calls", "evidence", "llm"}
  POST /analyze {path}     → .evtx 파싱→적재→이상탐지 ('분석 시작' 버튼). {"ok","records","stats","anomaly"}
  POST /anomaly {window_minutes?, contamination?} → 이상탐지 재실행. {"ok","windows","anomalies"}
  GET  /export[?limit=N]   → 정규화 이벤트 최종 산출물 JSON. {"ok","count","stats","events"}
  GET  /setup/status       → 첫 실행 셋업 필요 여부. {"ollama_installed","server_running","model_ready","needs_setup"}
  POST /setup/start        → Ollama 설치+모델 다운로드 백그라운드 시작. {"started"}
  GET  /setup/progress     → 셋업 진행률(폴링). {"phase","status","pct","done","ok","error"}

실행: evtx-ai-investigator/ 에서  python -m src.server   (옵션: --port 8765 --db db/events.sqlite)
"""
from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .agent.investigator import ask
from .store.store import open_db
from .paths import default_db_path

# 기본 DB 경로(작업 디렉토리/frozen 무관하게 해석)
DEFAULT_DB = default_db_path()

_CONFIG = {"db": DEFAULT_DB}


def _db_event_count(db_path: str) -> int | None:
    if not os.path.exists(db_path):
        return None
    try:
        conn = open_db(db_path)
        try:
            return conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        finally:
            conn.close()
    except Exception:
        return None


class _Handler(BaseHTTPRequestHandler):
    server_version = "EvtxInvestigator/0.1"

    # ---- CORS / 응답 헬퍼 ----
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send(self, code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    # ---- 라우팅 ----
    def do_OPTIONS(self):  # CORS preflight
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        from urllib.parse import urlsplit, parse_qs

        parts = urlsplit(self.path)
        path = parts.path
        if path == "/health":
            db = _CONFIG["db"]
            self._send(200, {"ok": True, "db": db, "events": _db_event_count(db)})
        elif path == "/export":
            from .pipeline import export_events

            qs = parse_qs(parts.query)
            try:
                limit = int(qs["limit"][0]) if qs.get("limit") else None
            except (ValueError, IndexError):
                limit = None
            try:
                self._send(200, export_events(_CONFIG["db"], limit=limit))
            except Exception as e:
                self._send(200, {"ok": False, "error": f"export 오류: {e}"})
        elif path == "/export_timeline":
            from .pipeline import export_timeline
            try:
                self._send(200, export_timeline(_CONFIG["db"]))
            except Exception as e:
                self._send(200, {"ok": False, "error": f"timeline 오류: {e}", "activities": []})
        elif path == "/timeline":
            # part-1 엔진(windows-timeline) 실행 → 사용자 활동 타임라인(없으면 샘플 폴백)
            from .pipeline import run_timeline
            from urllib.parse import parse_qs
            qs = parse_qs(parts.query)
            db = qs["db"][0] if qs.get("db") else None
            try:
                self._send(200, run_timeline(db))
            except Exception as e:
                self._send(200, {"ok": False, "error": f"timeline 엔진 오류: {e}", "activities": []})
        elif path == "/demo_timeline":
            # 시연용 정합 샘플(실제 엔진 우회) — file:// 에서도 서버 경유로 로드
            from .pipeline import demo_timeline
            try:
                self._send(200, demo_timeline())
            except Exception as e:
                self._send(200, {"ok": False, "error": f"데모 오류: {e}", "activities": []})
        elif path == "/setup/status":
            from .setup import setup_status
            self._send(200, setup_status())
        elif path == "/setup/progress":
            from .setup import setup_progress
            self._send(200, setup_progress())
        else:
            self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/analyze":
            self._handle_analyze()
            return
        if path == "/anomaly":
            self._handle_anomaly()
            return
        if path == "/analyze_auto":
            from .pipeline import analyze_auto
            data = self._read_json()
            channel = (data.get("channel") or "Security").strip()
            try:
                self._send(200, analyze_auto(channel, db_path=_CONFIG["db"]))
            except Exception as e:
                self._send(200, {"ok": False, "error": f"자동 분석 오류: {e}"})
            return
        if path == "/setup/start":
            from .setup import start_setup
            try:
                self._send(200, start_setup())
            except Exception as e:
                self._send(200, {"started": False, "error": f"셋업 시작 오류: {e}"})
            return
        if path != "/ask":
            self._send(404, {"ok": False, "error": "not found"})
            return
        data = self._read_json()
        question = (data.get("question") or "").strip()
        if not question:
            self._send(400, {"answer": "질문이 비어 있습니다.", "tool_calls": [], "evidence": []})
            return
        db = _CONFIG["db"]
        if not os.path.exists(db):
            self._send(200, {
                "answer": "분석할 이벤트 DB가 없습니다. 먼저 EVTX를 분석(적재)하세요.",
                "tool_calls": [], "evidence": [], "llm": False,
            })
            return
        # part-1 사용자 활동 타임라인이 함께 오면 교차 분석에 사용(선택)
        timeline = data.get("timeline")
        if not isinstance(timeline, list):
            timeline = None
        try:
            result = ask(question, db_path=db, timeline=timeline)
        except Exception as e:  # 엔진 예외도 200 으로 감싸 UI 가 표시
            result = {"answer": f"조사 중 오류: {e}", "tool_calls": [], "evidence": [], "llm": False}
        self._send(200, result)

    def _handle_analyze(self):
        """POST /analyze {path, replace?, window_minutes?, contamination?} — '분석 시작'."""
        from .pipeline import analyze_evtx

        data = self._read_json()
        path = (data.get("path") or "").strip()
        if not path:
            self._send(400, {"ok": False, "error": "path 가 필요합니다(.evtx 경로)."})
            return
        kwargs = {"db_path": _CONFIG["db"]}
        if "replace" in data:
            kwargs["replace"] = bool(data["replace"])
        if data.get("window_minutes"):
            kwargs["window_minutes"] = int(data["window_minutes"])
        if data.get("contamination"):
            kwargs["contamination"] = float(data["contamination"])
        try:
            self._send(200, analyze_evtx(path, **kwargs))
        except Exception as e:
            self._send(200, {"ok": False, "error": f"분석 오류: {e}"})

    def _handle_anomaly(self):
        """POST /anomaly {window_minutes?, contamination?} — 적재된 events 에 이상탐지 재실행."""
        from .pipeline import run_anomaly

        data = self._read_json()
        kwargs = {"db_path": _CONFIG["db"]}
        if data.get("window_minutes"):
            kwargs["window_minutes"] = int(data["window_minutes"])
        if data.get("contamination"):
            kwargs["contamination"] = float(data["contamination"])
        try:
            self._send(200, run_anomaly(**kwargs))
        except Exception as e:
            self._send(200, {"ok": False, "error": f"이상탐지 오류: {e}"})

    def log_message(self, fmt, *args):  # 콘솔 잡음 줄임
        print(f"[server] {self.address_string()} {fmt % args}")


def serve(port: int = 8765, db: str = DEFAULT_DB):
    _CONFIG["db"] = os.path.abspath(db)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    n = _db_event_count(_CONFIG["db"])
    print(f"[server] http://127.0.0.1:{port}  db={_CONFIG['db']} events={n}")
    print("[server] POST /ask {\"question\": \"...\"}  ·  GET /health  ·  Ctrl+C 종료")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[server] 종료")
        httpd.shutdown()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="EVTX AI 조사관 로컬 질의 서버")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--db", default=DEFAULT_DB)
    args = ap.parse_args()
    serve(port=args.port, db=args.db)
