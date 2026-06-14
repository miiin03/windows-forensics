# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 빌드 스펙 — EVTX AI 조사관 단일 .exe.

빌드(Windows, 프로젝트 루트에서):
    pip install -r requirements.txt
    pyinstaller app.spec            # → dist/app.exe

왜 .spec 인가(명령행 옵션 대신):
  - 다수 라이브러리(sklearn/scipy/pandas/Evtx)가 동적 import → hiddenimports 로 명시.
  - 우리 코드가 ollama/webview/Evtx 를 '함수 안에서' lazy import → 정적분석이 못 잡음 → 명시.
  - ui/, vendor/ 데이터 동봉.
디버깅 팁: 창 없이 죽으면 아래 console=False → True 로 바꿔 콘솔 로그 확인.
"""
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = [
    ("ui", "ui"),                          # 대시보드 뷰어
    ("vendor", "vendor"),                  # 번들 인스톨러(있으면)
    ("sample", "sample"),                  # part-1 타임라인 샘플(폴백)
    ("windows-timeline", "windows-timeline"),  # vendored part-1 엔진(런타임 sys.path import)
]
binaries = []
hiddenimports = [
    # 우리 코드의 lazy import (함수 내부 import → 정적분석 누락 방지)
    "ollama",          # investigator/setup 에서 런타임 import
    "webview",         # app.main 에서 import (pywebview)
    "Evtx", "Evtx.Evtx",  # pipeline → parser 가 사용
    "lxml", "lxml.etree",
    "sklearn.ensemble", "sklearn.utils._typedefs", "sklearn.neighbors",
]

# 동적 import 가 많은 패키지는 통째로 수집(서브모듈+데이터+동적 lib)
for pkg in ("sklearn", "scipy", "Evtx"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

hiddenimports += collect_submodules("numpy")
hiddenimports += collect_submodules("pandas")


a = Analysis(
    ["src/app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PyQt5", "PySide6"],  # 미사용 → 용량 절감
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="app",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    console=False,       # 데스크톱 앱(창). 빌드 디버깅 시 True 로.
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
