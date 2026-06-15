# WinTrace AI — 윈도우 통합 포렌식

윈도우 PC의 **사용자 활동 타임라인(ActivitiesCache.db 파싱+삭제기록 카빙 복구)**과
**보안 이벤트 로그(EVTX)**를 한 화면에서 분석하고, ML(Isolation Forest)로 비정상 시점을 탐지,
**AI 조사관**이 자연어 질의로 두 데이터를 교차 분석해 침해 정황을 설명하는 포렌식 도구.

> 윈도우 포렌식 프로젝트 **3번** 파트(EVTX·AI·ML·.exe) + part-1 타임라인 엔진 통합.
> 상세 설계는 [`DESIGN.md`](./DESIGN.md), 진행 현황은 [`PROGRESS.md`](./PROGRESS.md) 참고.

---

## 기술 스택
- Python 3.12
- 파싱: `python-evtx`(EVTX) + vendored `windows-timeline` 엔진(ActivitiesCache.db 카빙)
- 저장: SQLite (통합 이벤트 스토어)
- ML: `scikit-learn` (Isolation Forest, 시간 윈도우 이상탐지)
- LLM(3-tier): 개발=claude CLI / 배포=로컬 **Ollama + Qwen2.5**(오프라인·무료) / fallback
- UI/배포: `pywebview`(HTML 대시보드) + `pyinstaller`(단일 .exe)

## 산출물
- **단일 `.exe`** (WinTrace AI): 대시보드 UI + 분석 엔진 + AI 조사관, 첫 실행 시 Ollama 자동 셋업
- 배포본은 로컬 LLM 사용 → 증거 데이터가 외부로 나가지 않음(포렌식 무결성)

---

## 개발 환경 세팅

### 1) 의존성 설치
```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate
# WSL/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

### 2) 로컬 LLM (Ollama) 준비
```bash
# https://ollama.com 에서 Ollama 설치 후
ollama pull qwen2.5:7b      # 기본 (품질↑ 원하면 qwen2.5:14b)
```

### 3) 분석 대상 로그 준비
- `data/` 에 `.evtx` 파일을 둔다. (예: 본인 PC `C:\Windows\System32\winevt\Logs\Security.evtx`)
- `data/`, `db/` 는 `.gitignore` 처리됨 — **증거 데이터는 커밋되지 않는다.**

---

## 실행 (개발 중)
```bash
# 데스크톱 앱(대시보드) 실행 — 구현 후
python -m src.app
```

## .exe 빌드 (Windows에서만)
> ⚠ **반드시 Windows 네이티브 Python**에서 빌드 (WSL/Linux venv 로 빌드하면 .exe 가 아니라 리눅스
> 실행파일이 나오고, pywebview 도 Windows GUI 라 안 됨).

```powershell
# Windows PowerShell, 프로젝트 루트에서
python -m venv .venv-win
.\.venv-win\Scripts\Activate.ps1
pip install -r requirements.txt
pyinstaller app.spec            # 빌드 스펙 사용 (hiddenimports/데이터 동봉 포함)
# → dist\app.exe
```
- `app.spec` 가 `ui/`·`vendor/` 동봉 + sklearn/scipy/Evtx 등 동적 import 를 잡아준다.
- (선택) `vendor/OllamaSetup.exe` 를 두면 첫 실행 때 Ollama 를 다운로드 없이 무인 설치(`vendor/README.md`).
- exe 는 내장 HTTP 엔진(127.0.0.1:8765)을 띄우고 번들 UI 를 pywebview 창으로 연다.
- 모델(qwen2.5:7b, 4.7GB)은 exe 미포함 → **첫 실행 시 1회 다운로드**(설치 마법사 진행률).
- 빌드가 창 없이 죽으면 `app.spec` 의 `console=False` → `True` 로 바꿔 콘솔 로그 확인.

---

## 디렉토리
```
evtx-ai-investigator/
├─ DESIGN.md           # 설계서
├─ requirements.txt
├─ src/
│  ├─ parser/          # EVTX 파싱
│  ├─ store/           # SQLite 통합 이벤트 스토어
│  ├─ ml/              # 피처 + Isolation Forest
│  ├─ agent/           # 도구 + Qwen2.5 tool-calling
│  └─ app.py           # pywebview 진입점(대시보드)
├─ ui/index.html       # 대시보드 UI
├─ data/               # 분석 대상 .evtx (git 제외)
└─ db/                 # 생성된 events.sqlite (git 제외)
```
