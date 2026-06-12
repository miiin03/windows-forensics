# ui/ — 대시보드 UI 번들 위치

이 디렉토리의 UI는 **다른 팀원이 제작해 GitHub에 올린다.** (이 파트에서 직접 만들지 않음)

- `.exe` 빌드 시 팀원이 만든 대시보드 HTML/JS/CSS를 여기에 두고 `app.py`가 로드·번들한다.
- UI는 `window.pywebview.api.<메서드>`로 Python 엔진을 호출한다 — 호출 규약은
  `../DESIGN.md` §6.2 (JS API 계약) 및 `../src/app.py` 의 `Api` 클래스 참조.
