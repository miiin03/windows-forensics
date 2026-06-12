"""데스크톱 앱 진입점 — 팀원이 만든 HTML 대시보드를 pywebview 창으로 띄우고
Python 엔진(파서/스토어/ML/조사관)을 JS API로 노출한다. → PyInstaller로 .exe 빌드.

UI는 별도 팀원이 제작해 GitHub에 올린다(이 디렉토리에서 만들지 않음). 빌드 시 그 UI를
`ui/` 에 두고 번들한다. UI ↔ 엔진 연결 규약은 아래 Api 클래스(= DESIGN.md §6.2 JS API 계약).

흐름: app.py 실행 → webview 창 → 사용자가 .evtx 선택/질의 → window.pywebview.api.* 호출.
"""
from __future__ import annotations

import os


class Api:
    """JS ↔ Python 브리지. ui/index.html에서 window.pywebview.api.<메서드>로 호출."""

    def load_evtx(self, path: str) -> dict:
        """선택한 .evtx 파싱 → 스토어 적재 → 통계 반환. (M1~M2)"""
        raise NotImplementedError

    def run_anomaly(self) -> dict:
        """Isolation Forest 이상탐지 실행 → 비정상 윈도우 반환. (M3)"""
        raise NotImplementedError

    def ask(self, question: str) -> dict:
        """자연어 질의 → AI 조사관 답변. (M4)"""
        from .agent.investigator import ask
        return ask(question)


def main() -> None:
    import webview  # pywebview

    ui = os.path.join(os.path.dirname(__file__), "..", "ui", "index.html")
    webview.create_window(
        "EVTX AI 이상행위 조사관",
        ui,
        js_api=Api(),
        width=1280,
        height=820,
    )
    webview.start()


if __name__ == "__main__":
    main()
