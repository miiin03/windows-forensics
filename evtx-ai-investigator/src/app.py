"""데스크톱 앱 진입점 — 팀원이 만든 HTML 대시보드를 pywebview 창으로 띄우고
Python 엔진(파서/스토어/ML/조사관)을 JS API로 노출한다. → PyInstaller로 .exe 빌드.

UI는 별도 팀원이 제작해 GitHub에 올린다(이 디렉토리에서 만들지 않음). 빌드 시 그 UI를
`ui/` 에 두고 번들한다. UI ↔ 엔진 연결 규약은 아래 Api 클래스(= DESIGN.md §6.2 JS API 계약).

흐름: app.py 실행 → webview 창 → 사용자가 .evtx 선택/질의 → window.pywebview.api.* 호출.
"""
from __future__ import annotations


class Api:
    """JS ↔ Python 브리지. ui/index.html에서 window.pywebview.api.<메서드>로 호출."""

    def load_evtx(self, path: str) -> dict:
        """선택한 .evtx 파싱 → 스토어 적재 → 이상탐지 → 통계 반환. (M1~M3)"""
        from .pipeline import analyze_evtx
        return analyze_evtx(path)

    def run_anomaly(self) -> dict:
        """Isolation Forest 이상탐지 실행 → 비정상 윈도우 반환. (M3)"""
        from .pipeline import run_anomaly
        return run_anomaly()

    def export_events(self, limit: int | None = None) -> dict:
        """정규화 이벤트 최종 산출물(JSON) 반환."""
        from .pipeline import export_events
        return export_events(limit=limit)

    # ---- 첫 실행 셋업(Ollama 설치 + 모델 다운로드) ----
    def setup_status(self) -> dict:
        from .setup import setup_status
        return setup_status()

    def setup_start(self) -> dict:
        from .setup import start_setup
        return start_setup()

    def setup_progress(self) -> dict:
        from .setup import setup_progress
        return setup_progress()

    def ask(self, question: str) -> dict:
        """자연어 질의 → AI 조사관 답변. (M4)"""
        from .agent.investigator import ask
        return ask(question)


def _start_engine_server(port: int = 8765) -> None:
    """로컬 HTTP 엔진(/ask·/analyze·/export·/setup…)을 백그라운드 스레드로 기동.

    번들 UI(copilot)는 fetch(http://127.0.0.1:8765)로 엔진과 통신한다(COPILOT_INTEGRATION.md).
    pywebview js_api(Api) 와 동일 기능을 HTTP 로도 노출 → UI 가 어느 쪽이든 동작.
    """
    import threading

    from .server import serve
    from .paths import default_db_path

    threading.Thread(
        target=serve, kwargs={"port": port, "db": default_db_path()}, daemon=True
    ).start()


def main() -> None:
    import webview  # pywebview

    from .paths import ui_index

    _start_engine_server()  # 번들 UI 의 fetch 대상(localhost) 먼저 띄움

    webview.create_window(
        "EVTX AI 이상행위 조사관",
        ui_index(),
        js_api=Api(),
        width=1280,
        height=820,
    )
    webview.start()


if __name__ == "__main__":
    main()
