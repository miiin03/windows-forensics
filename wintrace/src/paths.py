"""경로 해석 — 개발 실행 / PyInstaller .exe(frozen) 양쪽 대응.

frozen(.exe) 에서는 두 종류의 경로가 갈린다:
  - **읽기전용 번들 리소스**(ui/, vendor/): PyInstaller 가 임시폴더 sys._MEIPASS 에 푼다.
  - **쓰기 가능 데이터**(db/): _MEIPASS 는 재실행 시 삭제·읽기전용 → exe 옆 폴더에 둬야 영속.

개발 모드(스크립트 실행)에서는 둘 다 프로젝트 루트 기준이라 동일하게 동작한다.
"""
from __future__ import annotations

import os
import sys


def is_frozen() -> bool:
    """PyInstaller 등으로 묶인 .exe 로 실행 중인가."""
    return getattr(sys, "frozen", False)


def resource_base() -> str:
    """읽기전용 번들 리소스 루트(ui/, vendor/)."""
    if is_frozen():
        return sys._MEIPASS  # type: ignore[attr-defined]
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 프로젝트 루트


def writable_base() -> str:
    """쓰기 가능 데이터 루트(db/). frozen 이면 exe 가 있는 폴더."""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(*parts: str) -> str:
    return os.path.join(resource_base(), *parts)


def data_dir() -> str:
    """events.sqlite 등을 두는 쓰기 가능 디렉토리(없으면 생성)."""
    d = os.path.join(writable_base(), "db")
    os.makedirs(d, exist_ok=True)
    return d


def default_db_path() -> str:
    return os.path.join(data_dir(), "events.sqlite")


def ui_index() -> str:
    """팀원 대시보드 진입 HTML."""
    return resource_path("ui", "index.html")


def bundled_installer() -> str:
    """번들된 Ollama 무인 인스톨러(읽기전용 리소스)."""
    return resource_path("vendor", "OllamaSetup.exe")


def download_dir() -> str:
    """런타임 다운로드(인스톨러 폴백)를 두는 쓰기 가능 디렉토리."""
    d = os.path.join(writable_base(), "vendor")
    os.makedirs(d, exist_ok=True)
    return d
