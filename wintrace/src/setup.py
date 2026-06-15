"""첫 실행 셋업 — Ollama 설치 + qwen2.5 모델 다운로드(download-on-first-run). DESIGN.md §8.3.

.exe 첫 실행 시 로컬 LLM 런타임이 없으면 한 번만 준비한다:
  1) Ollama 바이너리 확인 → 없으면 번들 인스톨러(or 공식 URL) 설치
  2) ollama 서버 기동 확인
  3) qwen2.5:7b 모델 pull (진행률 %)
완료 후엔 항상 스킵(모델/바이너리 상주). 진행률은 폴링 방식(stdlib http.server 친화).

엔드포인트(server.py):
  GET  /setup/status   → {ollama_installed, server_running, model_ready, needs_setup, model}
  POST /setup/start    → 백그라운드 셋업 시작(멱등) → {started, already_running?}
  GET  /setup/progress → {phase, status, completed, total, pct, done, ok, error}
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading

from .agent.investigator import MODEL  # "qwen2.5:7b"
from .paths import bundled_installer, download_dir

# Ollama Windows 공식 인스톨러(번들 부재 시 폴백 다운로드). 버전은 배포 시 갱신.
OLLAMA_INSTALLER_URL = "https://ollama.com/download/OllamaSetup.exe"

# Ollama 바이너리 후보 경로(PATH 외 — Windows .exe 설치 위치 / WSL 사용자 설치).
_OLLAMA_CANDIDATES = [
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe"),
    os.path.expanduser("~/.local/ollama/bin/ollama"),
    "/usr/local/bin/ollama",
]

# 셋업 진행 상태(스레드 공유). 단일 클라이언트 localhost 가정.
_STATE: dict = {
    "phase": "idle",      # idle | install | serve | pull | done | error
    "status": "",         # 사람이 읽는 현재 작업
    "completed": 0,
    "total": 0,
    "pct": 0.0,
    "done": False,
    "ok": False,
    "error": None,
}
_LOCK = threading.Lock()
_THREAD: threading.Thread | None = None


# ---------- 탐지 ----------

def _ollama_bin() -> str | None:
    """Ollama 실행 파일 경로(없으면 None)."""
    found = shutil.which("ollama")
    if found:
        return found
    for p in _OLLAMA_CANDIDATES:
        if p and os.path.exists(p):
            return p
    return None


def _server_running() -> bool:
    """로컬 ollama 서버(11434) 응답 여부."""
    try:
        import ollama
        ollama.list()
        return True
    except Exception:
        return False


def _model_ready() -> bool:
    """qwen2.5 모델이 이미 받아져 있는지(서버 응답 필요)."""
    try:
        import ollama
        data = ollama.list()
        names = [m.get("model") or m.get("name") or "" for m in data.get("models", [])]
        base = MODEL.split(":")[0]
        return any(n == MODEL or n.split(":")[0] == base for n in names)
    except Exception:
        return False


def setup_status() -> dict:
    """현재 환경 점검. needs_setup=True 면 UI 가 셋업 화면을 띄운다."""
    installed = _ollama_bin() is not None
    running = _server_running()
    ready = running and _model_ready()
    return {
        "ollama_installed": installed,
        "server_running": running,
        "model_ready": ready,
        "needs_setup": not ready,
        "model": MODEL,
    }


# ---------- 진행 상태 헬퍼 ----------

def _set(**kw) -> None:
    with _LOCK:
        _STATE.update(kw)
        tot = _STATE["total"]
        _STATE["pct"] = round(_STATE["completed"] / tot * 100, 1) if tot else _STATE["pct"]


def setup_progress() -> dict:
    with _LOCK:
        return dict(_STATE)


# ---------- 단계 ----------

def _ensure_ollama() -> str:
    """Ollama 바이너리 확보(설치). 경로 반환. 실패 시 RuntimeError."""
    found = _ollama_bin()
    if found:
        return found

    installer = bundled_installer()
    if not os.path.exists(installer):
        # 번들 없음 → 공식 URL 다운로드(Windows 한정)
        if os.name != "nt":
            raise RuntimeError(
                "Ollama 미설치. 수동 설치 필요: https://ollama.com (Linux/WSL: curl 설치 스크립트)"
            )
        _set(phase="install", status="Ollama 인스톨러 다운로드 중…", total=0, completed=0)
        installer = os.path.join(download_dir(), "OllamaSetup.exe")
        _download(OLLAMA_INSTALLER_URL, installer)

    _set(phase="install", status="Ollama 설치 중…")
    # Ollama Windows 인스톨러 무인 설치. (코드사인/인스톨러 옵션은 배포 시 검증)
    subprocess.run([installer, "/VERYSILENT", "/SUPPRESSMSGBOXES"], check=True)

    found = _ollama_bin()
    if not found:
        raise RuntimeError("Ollama 설치 후에도 실행 파일을 찾지 못했습니다.")
    return found


def _download(url: str, dest: str) -> None:
    """진행률 갱신하며 파일 다운로드."""
    import urllib.request

    with urllib.request.urlopen(url) as resp:  # noqa: S310 (신뢰 URL)
        total = int(resp.headers.get("Content-Length") or 0)
        _set(total=total, completed=0)
        got = 0
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(1 << 20)  # 1MB
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                _set(completed=got, total=total)


def _ensure_server(ollama_bin: str) -> None:
    """ollama 서버 기동 보장(미응답 시 `ollama serve` 백그라운드 실행)."""
    if _server_running():
        return
    _set(phase="serve", status="Ollama 서버 시작 중…")
    creationflags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
    subprocess.Popen(
        [ollama_bin, "serve"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    import time
    for _ in range(30):  # 최대 ~15초 대기
        if _server_running():
            return
        time.sleep(0.5)
    raise RuntimeError("Ollama 서버가 시작되지 않았습니다.")


def _pull_model() -> None:
    """qwen2.5 모델 다운로드(스트리밍 진행률)."""
    import ollama

    if _model_ready():
        return
    _set(phase="pull", status=f"{MODEL} 모델 다운로드 중…", total=0, completed=0)
    for p in ollama.pull(MODEL, stream=True):
        # p: {status, completed?, total?, digest?}
        status = p.get("status", "")
        total = p.get("total") or 0
        completed = p.get("completed") or 0
        if total:
            _set(status=f"{MODEL} 다운로드: {status}", completed=completed, total=total)
        else:
            _set(status=f"{MODEL}: {status}")


def _run() -> None:
    try:
        ollama_bin = _ensure_ollama()
        _ensure_server(ollama_bin)
        _pull_model()
        _set(phase="done", status="셋업 완료", done=True, ok=True, error=None,
             completed=_STATE["total"] or 1, total=_STATE["total"] or 1)
        _set(pct=100.0)
    except Exception as e:  # 어떤 단계든 실패 → UI 에 표시
        _set(phase="error", status="셋업 실패", done=True, ok=False,
             error=f"{type(e).__name__}: {e}")


def start_setup() -> dict:
    """백그라운드 셋업 시작(멱등). 이미 진행 중이면 already_running."""
    global _THREAD
    with _LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return {"started": False, "already_running": True}
        # 상태 초기화
        _STATE.update({"phase": "idle", "status": "시작 중…", "completed": 0,
                       "total": 0, "pct": 0.0, "done": False, "ok": False, "error": None})
        _THREAD = threading.Thread(target=_run, daemon=True)
        _THREAD.start()
    return {"started": True, "already_running": False}
