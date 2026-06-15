# 진행 상황 정리 — WinTrace AI (윈도우 포렌식 3번 파트)

> **앱 이름:** **WinTrace AI** — 윈도우 통합 포렌식 (구 "EVTX AI 이상행위 조사관")
> **기준일:** 2026-06-15
> **담당:** 윈도우 포렌식 프로젝트 3번 (EVTX AI 이상 행위 프로파일링) + part-1 타임라인 통합
> **레포:** `github.com/miiin03/windows-forensics` → `evtx-ai-investigator/`
> 설계 전문은 [`DESIGN.md`](./DESIGN.md), 본 문서는 **현재까지 구현·검증된 것** 정리.

---

## 1. 한 줄 요약

**WinTrace AI**: 윈도우 PC의 **사용자 활동 타임라인(part-1, ActivitiesCache.db 파싱+카빙)**과
**보안 이벤트 로그(part-3, EVTX)**를 한 화면에서 분석하고, ML(Isolation Forest)로 비정상 시점을 탐지,
**AI 조사관**(claude CLI / 로컬 Ollama / fallback 3-tier)이 자연어 질의로 두 데이터를 교차 분석해
침해 정황을 설명한다. 단일 `.exe`(첫 실행 자동 셋업) · 완전 오프라인 가능.

---

## 2. 전체 파이프라인 (현재 구현 범위)

```
*.evtx
  │  [M1] parser/evtx_parser.py — XML 파싱, 보안 이벤트ID 매핑, UTC→KST
  ▼
정규화 레코드(dict)
  │  [M1] store/store.py — SQLite events 테이블 적재
  ▼
db/events.sqlite  ──────────────┐
  │                              │
  │  [M2] agent/tools_*.py       │  [M3 ✅] ml/ — Isolation Forest
  │      포렌식 도구 7종          │      → is_anomaly / anomaly_score
  ▼                              ▼
[질의] agent/investigator.py — ask(question)
  │   ├─ Ollama 있음 → qwen2.5 tool-calling (진짜 LLM)
  │   └─ Ollama 없음 → fallback 자동 트리아지
  ▼
server.py  (로컬 HTTP /ask, /health) ── CORS ──▶ 팀원 copilot UI (fetch)
```

---

## 3. 구현·검증 완료 항목

### 3.1 M1 — 파서 + 스토어 ✅
- `src/parser/evtx_parser.py` : `python-evtx`+`lxml`로 각 레코드 XML 추출 → 공통 필드 + `EventData(dict)`.
  - 보안 이벤트ID → category 매핑 (4624 logon_ok, 4625 logon_fail, 4672 priv, 4720 account,
    7045 service, 1102 log_cleared 등).
  - 시각 UTC→KST(+9) 변환, 계정/출발지 IP/로그온 타입 추출, 손상 레코드 skip.
- `src/store/schema.py` / `store.py` : SQLite `events` 테이블(+인덱스). 적재·조회 함수.
- **검증:** 공개 샘플(EVTX-ATTACK-SAMPLES, 4624×3/4625×1) 파싱→적재→조회 정상.

### 3.2 M2 — 포렌식 도구 7종 ✅
LLM이 호출하는 **결정적** 도구. 실제 조회/집계는 Python이, LLM은 선택·해석만 → 환각 차단.

| 도구 | 기능 | 파일 |
|---|---|---|
| `search_events` | 조건(시간·EventID·계정) 검색 | tools_query.py |
| `get_event_detail` | 단일 이벤트 전체 원본(EventData 파싱) | tools_query.py |
| `get_timeline` | 구간 이벤트 시간순 요약 | tools_query.py |
| `summarize_stats` | EventID·category·계정 분포, 시간범위 | tools_query.py |
| `analyze_logons` | 로그온 성공/실패 + 무차별대입 의심 | tools_analysis.py |
| `find_security_events` | 고위험(로그삭제/계정생성/서비스 등) 탐지 | tools_analysis.py |
| `get_anomalies` | ML 비정상 윈도우 (M3 연동 대기) | tools.py |

- `tools.py` : `build_registry(conn)`(conn 바인딩) + `TOOL_SCHEMAS`(Ollama tool-calling용).
- **검증:** `tests/test_tools_smoke.py` — 7개 도구 호출 + 레지스트리/스키마 정합성 통과.

### 3.3 AI 조사관 질의부 (`ask`) ✅
- `src/agent/investigator.py` : `ask(question) → {answer, tool_calls, evidence, llm}`.
- **두 경로:**
  - **Ollama 있음:** qwen2.5가 도구 자동 선택 → 실행 → 결과 되돌림 → 최종 자연어 답변 (`llm:true`).
  - **Ollama 없음:** 핵심 도구 3개 직접 실행 → 고정 양식 요약 (`llm:false`, fallback).
    → Ollama 설치 전에도 팀원이 통합 테스트 가능 + 데모 안전망.
- **안정화(§9) 반영:**
  - 시간범위 인자 환각 차단(사용자 미명시 시 start/end 생략 지시).
  - 이벤트ID 범례 주입(4624/4625 등 의미 혼동 방지).
  - 도구 호출 한도(MAX_STEPS=5), 도구 오류는 모델에 되돌려 재시도.

### 3.4 로컬 LLM 환경 ✅
- Ollama v0.30.7 + `qwen2.5:7b`(4.7GB) WSL에 **루트 없이** 설치. CPU 추론.
- 성능: **질의당 ~30–45초** (i5-13600K, GPU 없음).
- 구동: `~/.local/ollama/bin/ollama serve`
- **검증:** "로그인 실패한 계정?" → qwen2.5가 `analyze_logons` 호출 → "IEUser, 1회 실패" 정답.

### 3.5 UI 연동부 (로컬 서버) ✅
- `src/server.py` : Python **표준 라이브러리만**(설치 불필요)으로 로컬 HTTP 서버.
  - `GET /health` → `{ok, db, events}`
  - `POST /ask {question}` → `{answer, tool_calls, evidence, llm}`
  - CORS/OPTIONS 처리 → 팀원 copilot이 다른 출처에서 `fetch` 가능.
- **검증:** `/health`, `/ask`(fallback·LLM 양쪽), CORS preflight 정상.

### 3.6 문서 (팀원 전달용)
- `ui/UI_DESIGN.md` — 우측 패널 디자인 요구사항(화면/UX).
- `ui/COPILOT_INTEGRATION.md` — copilot의 Anthropic fetch를 우리 `/ask`로 교체하는 법 + 응답 스키마.
- `ui/REQUIREMENTS.md` — JS API 계약(데이터 포함).

---

## 4. 디렉토리 현황

```
evtx-ai-investigator/
├─ DESIGN.md / PROGRESS.md(본 문서) / README.md / requirements.txt / .gitignore
├─ src/
│  ├─ parser/evtx_parser.py        # M1 ✅
│  ├─ store/{schema,store}.py       # M1 ✅
│  ├─ agent/
│  │   ├─ tools_query.py            # M2 ✅ 검색/상세/타임라인/통계
│  │   ├─ tools_analysis.py         # M2 ✅ 로그온/고위험
│  │   ├─ tools.py                  # M2 ✅ 레지스트리+스키마
│  │   └─ investigator.py           # ✅ ask() LLM+fallback
│  ├─ server.py                     # ✅ 로컬 /ask 서버
│  └─ ml/{features,anomaly}.py      # M3 ⬜ 스텁
├─ ui/  (UI_DESIGN / COPILOT_INTEGRATION / REQUIREMENTS .md)  # 문서만, UI는 팀원
├─ tests/test_tools_smoke.py        # ✅
├─ data/  *.evtx (git 제외)
└─ db/    events.sqlite (git 제외)
```

---

## 5. 구동 방법 (개발/데모)

```bash
# 1) 로컬 LLM 서버 (선택 — 없으면 fallback 동작)
~/.local/ollama/bin/ollama serve &

# 2) 질의 서버
cd evtx-ai-investigator
python -m src.server                 # http://127.0.0.1:8765

# 3) 테스트
curl http://127.0.0.1:8765/health
curl -X POST http://127.0.0.1:8765/ask -H "Content-Type: application/json" \
     -d '{"question":"로그인 실패한 계정 있어?"}'

# 도구 단독 검증
python -m tests.test_tools_smoke
```

---

## 6. 팀 협업 인터페이스 (역할 경계)

- **3번(본인):** EVTX 분석 엔진 + AI 조사관 + 로컬 서버. EVTX 보안/시스템 이벤트를 `/ask`로 답함.
- **1번 팀원:** 사용자 활동 타임라인(별도 JSON, activities[]).
- **UI 팀원:** 대시보드 + copilot. 1번/3번 결과를 UI에 통합.
- **데이터 도메인 2개 분리:** (1) 타임라인=1번, (2) EVTX 포렌식=3번(`/ask`).
  EVTX·로그온·침해 질문은 `/ask`로 라우팅.
- **"분석 시작" 버튼:** UI 팀원 제작 → 우리 분석 파이프라인 트리거(엔드포인트 `/analyze` 예정).

---

## 7. 남은 작업

| 항목 | 내용 | 상태 |
|---|---|---|
| `/analyze` | "분석 시작" 버튼 연동 — EVTX 파싱→적재→이상탐지 파이프라인 | ✅ (2026-06-14) |
| `/export` | 이벤트 정규화 **최종 산출물(JSON)** 출력 | ✅ (2026-06-14) |
| M3 | 피처 엔지니어링 + Isolation Forest → `get_anomalies` 실값 | ✅ (2026-06-14) |
| M5a | 첫 실행 셋업(download-on-first-run) — Ollama 설치+모델 pull 진행률 | ✅ (2026-06-14) |
| M5b | .exe 패키징(PyInstaller) — **빌드 준비 완료**, 실빌드는 Windows 네이티브에서 | 🟡 준비됨 |
| M6 | 대형 공격 샘플로 brute-force/1102 탐지 실증 | ⬜ 다음 |

### 7.1 이번 추가분 (2026-06-14) — UI 통합 언락 + M3

- **`src/pipeline.py`** (신규): 오케스트레이션. `analyze_evtx`(파싱→적재→이상탐지),
  `run_anomaly`(재탐지), `export_events`(정규화 산출물). parser 는 함수 안 지연 import → server import 안전.
- **`src/ml/features.py`**: `build_features(conn, window_minutes=60)` — 60분 윈도우 단위 15개 수치 피처
  (로그온실패/성공/비율, 고유계정·IP, 권한·계정생성·서비스·그룹·로그삭제·Kerberos실패, 시간대 플래그). 윈도우키=time_utc 내림(결정적).
- **`src/ml/anomaly.py`**: `detect_anomalies`(IsolationForest, `random_state=42`),
  `run_anomaly_detection`(피처→탐지→events.window_id/anomaly_score/is_anomaly 반영).
  소량 데이터 보호: 윈도우 < 8개면 학습 생략(`fitted:false`). 반환에 `high_risk`·윈도우별 `time/score/reason` 포함(UI 계약).
- **`get_anomalies`**(tools.py): 윈도우 단위로 묶어 점수 오름차순(낮을수록 비정상) + category 분포 반환.
- **`src/server.py`** 엔드포인트 추가: `POST /analyze`, `POST /anomaly`, `GET /export[?limit=N]`.
- **`src/app.py`** JS API: `load_evtx`/`run_anomaly`/`export_events` 를 pipeline 에 연결(.exe 경로도 동작).
- **검증:** 합성 데이터(정상 30윈도우 + brute-force 50회+1102 1윈도우)에서 해당 윈도우 정확 플래그
  (score 0.86, high_risk=true). 소량 실DB(4건)는 가드 작동. smoke 테스트 통과. 라이브 서버 `/health·/anomaly·/export·/analyze` 정상.

### 7.2 첫 실행 셋업 (M5a, 2026-06-14) — download-on-first-run

로컬 LLM(Ollama+qwen2.5:7b 4.7GB)은 .exe 미포함 → **첫 실행 1회 다운로드** 방식(C안).
- **`src/setup.py`** (신규): `setup_status`(Ollama/서버/모델 점검), `start_setup`(백그라운드 스레드:
  Ollama 설치→`serve` 기동→`ollama.pull` 진행률), `setup_progress`(폴링 스냅샷).
  - Ollama 바이너리 탐지(PATH + Windows/WSL 설치 경로). 미설치 시 `vendor/OllamaSetup.exe` 무인 설치,
    번들 없으면 공식 URL 다운로드 폴백. 모델 pull 은 stream 진행률(% 바).
- **`src/server.py`**: `GET /setup/status`, `POST /setup/start`, `GET /setup/progress` 추가.
- **`src/app.py`** JS API: `setup_status`/`setup_start`/`setup_progress`.
- **`vendor/`** (gitignore): 패키징 시 `OllamaSetup.exe` 배치(README 안내). 모델은 항상 첫 실행 pull.
- **UI 문서**: `ui/COPILOT_INTEGRATION.md §4.5` 셋업 화면/진행률 폴링 예제 추가.
- **검증:** 실 머신에서 `setup_status` → Ollama 바이너리 자동 탐지(`...\Programs\Ollama\ollama.exe`),
  `needs_setup` 판정·진행 상태 폴링 정상. (실제 설치/4.7GB pull 은 배포 환경에서 1회 수행.)

### 7.4 part-1 통합 (2026-06-14) — 통합 타임라인 + 교차 분석

part-1(사용자 활동 타임라인)과 part-3(EVTX 보안 이벤트)가 한 화면/한 AI에서 만나도록 연결.
- **B 통합 타임라인**: `pipeline.export_timeline()` + `GET /export_timeline` — events 를 part-1
  `activities[]` 스키마(artifact="evtx", EventID→사람이 읽는 title/detail, ML이상=carved 강조)로 변환.
  뷰어가 `/export_timeline` fetch → `DATA.activities` 에 병합 → 같은 타임라인/24시계에 시간순 표시.
  CAT 에 EVTX 카테고리 색/아이콘(logon_fail 빨강, log_cleared 등) + ART 에 evtx 추가.
- **A 교차 분석**: `POST /ask` 에 선택 인자 `timeline:[...]` → `investigator.ask(timeline=)` 가
  사용자 활동을 컨텍스트로 주입 → "의심 로그온 시각 전후 사용자가 뭐 했나" 같은 교차 질의 가능.
  뷰어 cpSendMsg 가 현재 part-1 활동을 함께 전송.
- **part-1 샘플**: `sample/timeline_result.sample.json`(스키마 확정본, 6건) — 뷰어 기본 로드.
- 스키마 출처: github miiin03/windows-forensics `feature/windows-timeline` 의 `UI-연동-안내.md`/sample 확인.
- **검증**: /export_timeline 112건 변환, /ask+timeline llm:true 정상, 뷰어 JS 균형 OK.
- ⚠ 뷰어(ui/index.html)는 팀원과 공유 파일 — 현재는 우리 데모 사본. 실제 병합은 팀 합의 필요.

### 7.5 part-1 엔진 완전 통합 (2026-06-14)

팀원 part-1 엔진(`windows-timeline/engine`)을 레포 `feature/windows-timeline`에서 **vendoring**해 통합.
- `windows-timeline/` (프로젝트 내 복사본, 팀원 코드 — 출처 명시) + `sample/timeline_result.sample.json`.
- **`pipeline.run_timeline()`** + `GET /timeline` — `python -m engine --ui`와 동일(ActivitiesCache.db
  자동탐색 또는 db 지정) → part-1 UI 계약 `{meta, activities}` 반환. 엔진 크래시/미발견 시 동봉 샘플로 폴백(`source` 표기).
- **UI "▶ 분석 시작"** 버튼 → `/timeline` 호출 → 사용자 타임라인 로드(+기존 EVTX 유지 병합).
  ".evtx 경로 + 보안분석"(part-3)은 그 위에 EVTX 합침.
- `app.spec` datas 에 `windows-timeline/`·`sample/` 추가(런타임 sys.path import).
- **검증**: /timeline 라이브 ok(샌드박스=샘플 폴백 6건, 실 윈도우=엔진 자동탐색). JS 균형 OK.
- ⚠ 실 윈도우에서 part-1 엔진이 자기 PC ActivitiesCache.db 파싱 — 일부 레코드서 OSError 가능(엔진측 버그) → 폴백 안전망 있음.

### 7.8 브랜딩·자동셋업·실빌드 (2026-06-15)

- **앱 이름 → WinTrace AI**: 창 제목·`<title>`·헤더 h1(🛡️ WinTrace AI)·AI 드로어("WinTrace AI 조사관") 전부 교체.
  소개 3문장: ①타임라인+EVTX 통합 분석·삭제흔적 카빙 복구 ②ML 탐지 + AI 교차분석 ③단일 .exe·오프라인.
- **셋업 완전 자동화**: '설치/다운로드' 버튼 제거 → 첫 실행 시 `needs_setup`이면 자동으로 Ollama 설치+모델
  다운로드 시작(`setupStarted` 1회 가드). 엔진 부팅 중이면 2초 간격 자동 재시도.
- **PyInstaller 실빌드 성공**: `launch.py`(진입점) 추가 → `src/app.py` 직접 진입 시 상대 import 에러
  (`attempted relative import with no known parent package`) 해결. `app.spec` 진입점 launch.py +
  `collect_submodules("src")`. `dist\app.exe` 정상 구동 확인(전용 `.venv-win`에서 빌드, anaconda pathlib 충돌 회피).
- **빌드 LLM 분기**: frozen(.exe)이면 `_use_claude()`→False → 항상 로컬 Ollama(배포본은 오프라인). 개발 실행은 claude CLI 우선.
- **UI 정리**: JSON 로드·내보내기 버튼 제거, 암호화/복호화 통계·필터칩 숨김, 자동탐색 버튼명 "🖥️ 내 PC 자동"으로 통일.
- **GitHub**: `develop` 브랜치에 커밋(d34fabd). samples/(67MB)·db·data 는 .gitignore 로 제외(증거 비유출). push 는 계정 권한 확인 후.

### 7.7 claude CLI 백엔드 (2026-06-14) — 구독으로 고속·고품질

API 키(유료) 없이도 설치된 `claude` CLI(Claude Code)를 headless(`-p`)로 호출해 답변 품질↑.
- **`investigator._ask_claude_cli`**: 결정적 도구(summarize_stats/analyze_logons/find_security_events/
  get_anomalies)로 집계를 먼저 계산 → `[분석 데이터]`로 stdin 주입 → `claude -p --system-prompt <포렌식규칙>`
  로 자연어 답변만 받음(tool-calling 대신 데이터 주입 → 안정적·환각 차단).
- 입력은 UTF-8 바이트로 전달(PS 파이프 인코딩 깨짐 회피). `_CLI_SYSTEM`이 한국어·결론형·데이터덤프 금지 규칙.
- **백엔드 우선순위**(ask): claude CLI(있으면) → Ollama → fallback. `EVTX_NO_CLAUDE=1` 로 끄면 Ollama.
- **검증**: 실DB 질의 ~18초, 전문가급 한국어 결론(1102 맥락화·4672 정상수치·이상징후=부팅폭증 정확 해석).
- ⚠ **한계**: 이 PC 의 claude 로그인에 의존 → 배포 .exe/타 PC 에선 동작 안 함(그땐 Ollama). 개발·데모 머신 전용 고속 옵션.
  Claude Code 는 개발용 CLI — 앱 백엔드로 자동 호출은 그레이존(학교 데모 수준엔 무방).

### 7.6 LLM 모델 경량화 (2026-06-14) — 속도

로컬 LLM 질의당 30~45초(qwen2.5:7b, CPU) → 발표/데모용으로 느림.
- **`MODEL` 을 `qwen2.5:3b` 로 변경** (7b 대비 2~3배 빠름, 품질 소폭↓). 오프라인·무료 유지.
- `_timeline_note`/`_precheck_note` 헬퍼로 컨텍스트 주입 로직 정리(리팩터).
- 모델 받기: `ollama pull qwen2.5:3b`. 더 빠르게: `qwen2.5:1.5b`. 품질 우선: `qwen2.5:7b` 로 `MODEL` 되돌림.
- (클라우드 백엔드 옵션은 비용 발생으로 미채택 — 오프라인 로컬 유지가 설계 핵심.)

### 7.3 PyInstaller 빌드 준비 (M5b, 2026-06-14) — 코드는 frozen-ready, 실빌드만 남음

- **`src/paths.py`** (신규): 개발/`.exe`(frozen) 경로 분기.
  - 읽기전용 리소스(ui/·vendor/) = `sys._MEIPASS`, 쓰기 데이터(db/) = exe 옆 폴더 → frozen 에서 DB 영속.
  - server/pipeline/investigator/setup/app 의 하드코딩 경로(`db/events.sqlite`, ui, vendor)를 전부 이 모듈로 교체.
- **`src/app.py`** `main()`: pywebview 창 + **내장 HTTP 엔진(127.0.0.1:8765)을 백그라운드 스레드로 기동**.
  → 번들 UI(copilot)의 `fetch(localhost)` 가 exe 안에서 그대로 동작(엔진 자체 내장).
- **`app.spec`** (신규): `ui/`·`vendor/` 동봉 + lazy/동적 import(ollama·webview·Evtx·sklearn·scipy) hiddenimports.
- **`vendor/`** + `.gitignore`: 인스톨러 동봉 위치(커밋 제외). `README.md` 빌드 가이드 갱신.
- **검증(개발모드):** 전 모듈 import·paths 해석·default db 경유 export·smoke 통과. **실 .exe 빌드는 Windows 네이티브 Python 필요**(WSL 불가) → 다음 단계 사용자 머신에서.

---

## 8. 설계 결정 메모

- **로컬 LLM(Qwen2.5/Ollama, CPU):** 무료·오프라인·증거 비유출(포렌식 무결성).
- **Tool-calling 구조:** 정확한 시간·횟수·ID가 핵심 → 검증·재현(감사 추적) 가능, 환각 차단.
- **연동은 로컬 HTTP(`/ask`):** 샘플 copilot이 `fetch(URL)` 구조라 드롭인. 팀원 독립 통합 유리.
- **Ollama 번들:** 엔진과 분리된 패키징 문제. 엔진은 미설치 시 fallback이라 항상 동작.
