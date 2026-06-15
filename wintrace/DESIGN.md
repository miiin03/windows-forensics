# EVTX AI 이상행위 조사관 — 설계서

> **버전:** v0.2 (2026-06-12)
> **담당:** 윈도우 포렌식 프로젝트 3번 (EVTX AI 이상 행위 프로파일링)
> **레포:** `github.com/miiin03/windows-forensics` → `wintrace/` (본인 전용 디렉토리)
> **한 줄 요약:** 윈도우 이벤트 로그(EVTX)를 파싱해 통합 이벤트 스토어에 적재하고, (a) 고전 ML로 비정상 시점을 탐지한 뒤 (b) **로컬 LLM 기반 AI 조사관**이 자연어 질의로 그 근거를 분석·설명·추적하는 도구. 팀원이 만든 대시보드 UI와 묶어 **단일 `.exe`**로 배포.

---

## 0. 설계 결정 요약 (확정 사항)

| 항목 | 결정 | 이유 |
|---|---|---|
| **AI 조사관 구조** | Tool-calling(함수 호출) 에이전트 | 포렌식은 "정확한 시간·횟수·이벤트ID"가 핵심 → 검증·재현(감사 추적) 가능 |
| **ML 통합** | 하이브리드 (Isolation Forest → LLM 해석) | ML이 비정상 시점 플래그, LLM이 자연어로 근거 설명·추적. 논문성↑ |
| **LLM 환경** | 로컬 (Ollama + **Qwen2.5 7B**) | 무료 · 오프라인 · **증거 데이터가 외부로 안 나감**(포렌식 무결성/프라이버시) |
| **언어/스택** | Python 3.12 | `python-evtx`, `scikit-learn`, `ollama` 생태계 |
| **실행 하드웨어** | i5-13600K / RAM 64GB / GPU 없음 → **CPU 추론** | 강력한 CPU + 대용량 RAM이라 7B(필요시 14B)도 충분 |
| **산출물** | **단일 `.exe`** (pywebview + PyInstaller) | 팀원 대시보드 UI + 본 엔진을 하나의 데스크톱 앱으로 |
| **UI 담당** | **다른 팀원** (GitHub 업로드) | 본 파트는 엔진 + JS API 브리지 + .exe 패키징 담당 |

---

## 1. 개요 (Overview)

윈도우 **보안/시스템 이벤트 로그(EVTX)**에는 로그온 성공/실패, 권한 상승, 프로세스 생성, 계정 생성, 서비스 설치, 로그 삭제 등 침해 사고의 결정적 흔적이 남는다. 본 도구는 이 로그를:

1. **파싱·정규화**하여 질의 가능한 **통합 이벤트 스토어(SQLite)**로 만들고,
2. **고전 ML(Isolation Forest)**로 "평소와 다른 비정상 시점"을 자동 플래그하며,
3. **로컬 LLM(Qwen2.5) 기반 AI 조사관**이 *"새벽에 의심스러운 로그인 시도 있었어?"* 같은 **자연어 질의**를 받아, 정의된 포렌식 도구를 스스로 호출해 근거 데이터를 찾고 **설명·추적**한다.

엔진은 **팀원이 만든 대시보드 UI**와 결합해 단일 `.exe` 데스크톱 앱으로 배포된다(UI ↔ 엔진은 §6.2 JS API 계약).

### 차별점
- **설명 가능한(explainable) 포렌식 트리아지**: ML 단독(점수만)·LLM 단독(근거 약함)의 한계를 합쳐 "수치 근거(ML) + 자연어 해석(LLM)"을 동시 제공.
- **완전 오프라인·무료·프라이버시**: 증거 데이터가 PC 밖으로 나가지 않음 → 법적 무결성·발표 어필.
- **자연어 인터페이스**: 포렌식 비전문가도 질문만으로 침해 흔적을 조사.

---

## 2. 협업 구조 & 역할 경계

| 파트 | 담당 | 산출물 | 위치 |
|---|---|---|---|
| **3번 — 분석 엔진 + AI 조사관 + .exe 패키징** | **본인** | EVTX 파서, 이벤트 스토어, ML, 에이전트, JS API 브리지, `.exe` 빌드 | `wintrace/` |
| 대시보드 UI | 다른 팀원 | HTML/JS/CSS 대시보드 | 별도 디렉토리/레포 루트 (팀원 영역) |
| 1번 — 사용자 행위 타임라인 | 또 다른 팀원 | (독립) | 팀원 영역 |

- **디렉토리 격리 원칙**: 각자 본인 디렉토리만 수정. 본 파트는 `wintrace/` 안에서만 작업.
- **UI 연동**: 팀원이 만든 대시보드 UI를 가져와 `.exe` 빌드 시 `ui/`에 두고 번들. UI는 본 파트가 만들지 않으며, **연결은 §6.2 JS API 계약**으로만 한다.
- **증거 데이터 비커밋**: `data/`(.evtx), `db/`(생성 DB)는 `.gitignore` 처리 — 민감 데이터를 GitHub에 올리지 않음.

---

## 3. 개발 범위 및 한계

### 3.1 개발 범위
- **EVTX 파서**: Security / System 채널(+ 옵션 Sysmon). 주요 보안 이벤트 ID 매핑·디코딩.
- **통합 이벤트 스토어**: 정규화된 단일 SQLite 스키마(§7).
- **피처 엔지니어링 + ML**: 시간 윈도우/계정 단위 피처 → Isolation Forest 이상탐지.
- **Tool-calling 에이전트**: 로컬 LLM이 호출하는 포렌식 분석 도구 7종(§6.1).
- **JS API 브리지**: 팀원 UI ↔ 엔진 연결(§6.2). pywebview `js_api`.
- **.exe 패키징**: PyInstaller로 UI + 엔진을 단일 실행파일로.

### 3.2 개발 한계
- **획득(Acquisition) 제외**: 라이브 수집은 범위 밖. **이미 확보된 `.evtx` 파일**을 입력으로 가정.
- **로컬 LLM tool-calling 신뢰성**: 상용 대비 함수 호출이 덜 안정적 → 안정화 전략(§9).
- **채널 한정**: 우선 Security/System(+Sysmon 옵션). 전 채널 커버는 향후 확장.
- **탐지 한계**: ML은 "비정상" 신호일 뿐 확정 아님 → 최종 해석은 LLM 조사관 + 분석관. 오탐 가능성 명시.
- **UI 의존**: 대시보드 UI는 팀원 산출물 → 통합 일정은 팀원 진척에 의존. (엔진은 UI 없이도 CLI로 단독 검증 가능 — §6.3)

---

## 4. 핵심 기능 (Core Features)

### 4.1 EVTX 파싱 & 보안 이벤트 매핑
`python-evtx`로 각 레코드를 XML로 추출 → 핵심 필드 정규화. 포렌식 핵심 이벤트 ID:

| 분류 | EventID | 의미 | 침해 관점 |
|---|---|---|---|
| 로그온 | 4624 / 4625 | 성공 / **실패** | 무차별 대입, 비정상 접근 |
| 로그온 | 4634 / 4647 | 로그오프 | 세션 추적 |
| 권한 | 4672 | 특수 권한 부여(관리자) | 권한 상승 |
| 프로세스 | 4688 | 프로세스 생성 | 악성 실행 |
| 계정 | 4720 / 4722 / 4724 | 계정 생성 / 활성화 / 비번 재설정 | 백도어 계정 |
| 그룹 | 4728 / 4732 / 4756 | 권한 그룹 멤버 추가 | 권한 상승·지속성 |
| Kerberos | 4768 / 4769 / 4771 | TGT / TGS / 사전인증 실패 | 자격증명 공격 |
| NTLM | 4776 | 자격증명 검증 | Pass-the-Hash 정황 |
| **안티포렌식** | **1102** | **감사 로그 삭제** | 증거 인멸 |
| 서비스 | 7045 / 7034 | 서비스 설치 / 비정상 종료 | 지속성, 악성 서비스 |
| (옵션) Sysmon | 1 / 3 / 11 / 13 | 프로세스 / 네트워크 / 파일 / 레지스트리 | 정밀 행위 추적 |

### 4.2 통합 이벤트 스토어 (SQLite)
모든 파싱 결과를 단일 `events` 테이블로 정규화(§7). 인덱스(시간·EventID·계정)로 빠른 질의.

### 4.3 피처 엔지니어링
시간 윈도우(예: 1시간)/계정 단위 집계: 로그온 실패 수·비율, 고유 출발지 IP, 로그온 타입 분포, 시간대/야간/주말, 특수권한·신규계정·서비스설치 수, 로그삭제(1102) 플래그 등.

### 4.4 ML 이상탐지 (Isolation Forest)
비지도로 희소·비정상 패턴을 점수화 → 윈도우별 `anomaly_score`/`is_anomaly` 스토어 반영. 침해 시나리오(무차별대입·권한상승·지속성·로그인멸·비정상시간대) 매핑.

### 4.5 Tool-calling AI 조사관
로컬 Qwen2.5가 자연어 질의를 받아 §6.1 도구를 스스로 호출 → 근거 기반 답변. ML 플래그를 "조사 단서"로 활용.

---

## 5. 데이터 파이프라인

```
[입력]   *.evtx (Security / System / Sysmon)
   │
[Parse]  python-evtx → 레코드별 XML → 공통필드 + EventData(dict)
   │
[Normalize] 보안 이벤트 ID 매핑, 시각 정규화(UTC→KST), 계정/IP 추출
   │
[Store]  SQLite events 테이블 적재 (+ 인덱스)
   │
[Feature] 시간윈도우/계정 단위 집계 → 피처 행렬
   │
[ML]     Isolation Forest → anomaly_score / is_anomaly → 스토어 반영
   │
[Agent]  자연어 질의 → Qwen2.5(tool-calling) → 도구 호출 → 근거 수집
   │
[Bridge] pywebview JS API ← 팀원 대시보드 UI
   │
[.exe]   PyInstaller 단일 실행파일
```

---

## 6. 인터페이스

### 6.1 도구(Tool) 명세 — 에이전트가 호출하는 함수
> 각 도구는 데이터 조회/계산을 결정적으로 수행하고 구조화된 JSON을 반환. LLM은 "선택·해석"만 → 환각 차단.

| 도구 | 설명 | 주요 입력 |
|---|---|---|
| `search_events` | 조건(시간·EventID·계정·채널)으로 검색 | `start, end, event_id, account, limit` |
| `analyze_logons` | 구간 로그온 성공/실패 통계 + 무차별대입 의심 | `start, end` |
| `get_anomalies` | ML 비정상 플래그 윈도우 목록 | `threshold, top_n` |
| `get_event_detail` | 단일 이벤트 전체 원본 필드 | `event_pk` |
| `get_timeline` | 구간 이벤트 시간순 요약 | `start, end, event_ids` |
| `summarize_stats` | 전체/구간 통계 | `start, end` |
| `find_security_events` | 고위험(1102/4720/7045/4672 등) 발생 위치 | `categories` |

### 6.2 JS API 계약 (UI ↔ 엔진) — **팀원 UI 연동 규약**
팀원 대시보드는 `window.pywebview.api.<메서드>`로 아래를 호출한다. (`src/app.py`의 `Api` 클래스)

| 메서드 | 입력 | 반환(JSON) |
|---|---|---|
| `load_evtx(path)` | .evtx 경로 | `{ ok, records, stats: { total, by_event_id, ... } }` |
| `run_anomaly()` | — | `{ ok, anomalies: [ {window_id, time, score, reason} ] }` |
| `ask(question)` | 자연어 질의 | `{ answer, tool_calls: [...], evidence: [event...] }` |

> 반환 스키마는 구현하며 확정·문서화. UI는 이 계약만 알면 되고, 엔진 내부는 몰라도 됨.

### 6.3 개발용 CLI (선택)
UI 없이 엔진을 단독 검증하기 위한 CLI(`python -m src.cli "질의..."`). 발표 데모·디버깅용.

---

## 7. 통합 이벤트 스키마 (SQLite `events`)

```sql
CREATE TABLE events (
    pk             INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id       INTEGER,            -- 4625, 4624, 1102 ...
    channel        TEXT,               -- Security / System / Microsoft-Windows-Sysmon
    provider       TEXT,
    level          TEXT,
    computer       TEXT,
    time_utc       TEXT,               -- 원본 UTC ISO-8601
    time_kst       TEXT,               -- KST(UTC+9) ISO-8601
    category       TEXT,               -- logon_fail / logon_ok / priv / proc / account / service / log_cleared ...
    account        TEXT,
    source_ip      TEXT,
    logon_type     INTEGER,
    event_data     TEXT,               -- EventData 전체(JSON, 감사용)
    window_id      TEXT,               -- 소속 시간 윈도우 키(ML)
    anomaly_score  REAL,
    is_anomaly     INTEGER
);
CREATE INDEX idx_time ON events(time_utc);
CREATE INDEX idx_evid ON events(event_id);
CREATE INDEX idx_acct ON events(account);
CREATE INDEX idx_anom ON events(is_anomaly);
```
**규칙**: 추출 불가 값은 `NULL`. 시각은 UTC·KST 둘 다 보존. `event_data`에 원본 보존(감사 추적).

---

## 8. 기술 스택 & 디렉토리

### 8.1 스택
| 영역 | 도구 |
|---|---|
| 언어 | Python 3.12 |
| 파싱 | `python-evtx`, `lxml` |
| 저장 | `sqlite3` |
| 데이터 | `pandas`, `numpy` |
| ML | `scikit-learn` (IsolationForest) |
| LLM | **Ollama + `qwen2.5:7b`** (CPU, 무료, 오프라인) |
| LLM 연동 | `ollama` 파이썬 라이브러리 |
| UI/배포 | `pywebview`(팀원 UI 로드) + `pyinstaller`(.exe) |

### 8.2 디렉토리 (`wintrace/`)
```
wintrace/
├─ DESIGN.md / README.md / requirements.txt / .gitignore
├─ src/
│  ├─ parser/evtx_parser.py     # EVTX → 정규화
│  ├─ store/{schema,store}.py    # SQLite 통합 스토어
│  ├─ ml/{features,anomaly}.py   # 피처 + Isolation Forest
│  ├─ agent/{tools,investigator}.py  # 도구 + Qwen2.5 tool-calling
│  └─ app.py                     # pywebview 진입점(.exe), JS API 브리지
├─ ui/                           # 팀원 대시보드 UI 번들 위치(본 파트가 만들지 않음)
├─ data/                         # 분석 대상 .evtx (git 제외)
├─ db/                           # 생성된 events.sqlite (git 제외)
└─ tests/
```

### 8.3 .exe 빌드 (Windows)
```bash
pyinstaller --onefile --windowed --add-data "ui;ui" src/app.py   # → dist/app.exe
```
> Ollama는 별도 설치/실행이 필요한 런타임 의존(.exe에 미포함). 배포 시 "Ollama 설치 + `ollama pull qwen2.5:7b`" 안내.

---

## 9. 에이전트 안정화 전략 (로컬 LLM 보강)
1. **구조화 출력 강제**: Ollama `format=json`/도구 스키마로 JSON만 수신.
2. **호출 실패 재시도**: 잘못된 도구명·인자 시 에러를 모델에 되돌려 1~2회 재시도.
3. **단순 스키마**: 인자 최소화, enum·명확한 설명으로 오용 방지.
4. **도구 설명에 호출 조건 명시**: "사용자가 로그인 시도를 물으면 analyze_logons 호출".
5. **결정적 도구**: 실제 조회·계산은 Python 도구가 수행 → LLM은 선택·해석만(환각 차단).

---

## 10. 테스트 데이터 계획
1. **자기 PC 실물 로그**: `C:\Windows\System32\winevt\Logs\Security.evtx`, `System.evtx` → 즉시 검증.
2. **공개 침해 데이터셋**: `EVTX-ATTACK-SAMPLES` 등 공격 시나리오 EVTX → ML·에이전트 탐지력 검증.
3. **합성 시나리오(옵션)**: 정상 로그에 brute-force/로그삭제 주입 → 재현율 측정.

---

## 11. 마일스톤
| 단계 | 산출물 | 상태 |
|---|---|---|
| M0 | 설계서 + 레포 환경 세팅 | ✅ |
| M1 | EVTX 파서 + SQLite 스토어 (자기 PC 로그 검증) | ⬜ |
| M2 | 보안 이벤트 매핑·정규화 + 검색/통계 도구 | ⬜ |
| M3 | 피처 엔지니어링 + Isolation Forest | ⬜ |
| M4 | Ollama(Qwen2.5) tool-calling 에이전트 + 도구 연결 | ⬜ |
| M5 | JS API 브리지 + 팀원 UI 통합 + .exe 빌드 | ⬜ |
| M6 | 공개 침해 데이터셋 검증 · 탐지 성능 측정 | ⬜ |
| M7 | 문서화 · 발표(시나리오 데모) | ⬜ |

---

## 12. 기대 효과
- **설명 가능한 AI 포렌식**: ML 수치 근거 + LLM 자연어 해석 결합 트리아지 → 단독 기법 대비 새로운 기여(KCI/학회 어필).
- **프라이버시·무결성**: 완전 오프라인 로컬 추론으로 증거 비유출.
- **접근성**: 자연어 질의로 포렌식 진입장벽↓, 팀원 대시보드 UI와 결합한 완성형 `.exe` 도구.
