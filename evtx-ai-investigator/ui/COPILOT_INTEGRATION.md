# AI 코파일럿 ↔ 우리 엔진 연동 가이드 (UI 담당용)

> 샘플 HTML의 copilot은 지금 **클라우드 Anthropic API**로 직접 fetch 한다.
> 우리(3번) 기능은 **로컬 엔진**(EVTX 이벤트 + 로컬 LLM)이다. copilot의 fetch 한 곳만
> 우리 로컬 서버로 바꾸면 연동 끝. **HTML 구조·디자인은 그대로 둬도 됨.**

---

## 0. 우리가 제공하는 것

`evtx-ai-investigator/` 안:
- `src/server.py` — **로컬 질의 서버**(Python 표준 라이브러리만, 설치 불필요)
  - 실행: `cd evtx-ai-investigator && python -m src.server`  → `http://127.0.0.1:8765`
- 엔드포인트
  - `GET  /health` → `{ ok, db, events }` (적재된 이벤트 수)
  - `POST /ask  { "question": "..." }` → `{ answer, tool_calls, evidence, llm }`
  - `POST /analyze { "path": ".evtx 경로" }` → `{ ok, records, stats, anomaly }` (**"분석 시작" 버튼**: 파싱→적재→이상탐지)
  - `POST /anomaly {}` → `{ ok, high_risk, anomalies:[{time,score,reason}] }` (이상탐지 재실행)
  - `GET  /export[?limit=N]` → `{ ok, count, stats, events:[...] }` (정규화 이벤트 최종 산출물 JSON)
  - `GET  /export_timeline` → `{ ok, meta, activities:[...] }` (EVTX를 part-1 타임라인 스키마로 변환 — 통합 타임라인용)
  - `POST /ask` 는 선택 인자 `timeline:[...activities]` 를 받음 → EVTX + part-1 사용자 활동 교차 분석
  - `GET  /setup/status` → `{ ollama_installed, server_running, model_ready, needs_setup, model }` (첫 실행 셋업 필요 여부)
  - `POST /setup/start` → `{ started }` (Ollama 설치 + 모델 다운로드 백그라운드 시작)
  - `GET  /setup/progress` → `{ phase, status, pct, done, ok, error }` (진행률 폴링)

> Ollama(qwen2.5) 미설치 상태에서도 동작한다(도구 직접 실행 fallback → 근거 포함 응답).
> Ollama 설치 시 자동으로 로컬 LLM 자연어 해석으로 전환(`llm:true`).

---

## 1. copilot 연결 방법 (fetch 한 블록만 교체)

샘플 `cpSendMsg()` 안의 **Anthropic fetch 부분**을 아래로 교체:

```js
const ENGINE_URL = "http://127.0.0.1:8765/ask";   // 우리 로컬 엔진

const res = await fetch(ENGINE_URL, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ question: q })            // q = 사용자 질문 텍스트
});
const data = await res.json();   // { answer, tool_calls, evidence, llm }
cpTypingOff();

if (data && data.answer) {
  cpAdd("ai", data.answer);
  cpHistory.push({ role: "assistant", content: data.answer });
  // (옵션) 근거 펼치기: data.tool_calls(호출한 도구), data.evidence(근거 이벤트)
} else {
  cpAdd("err", "응답이 비어 있습니다. 다시 시도해주세요.");
}
```

- 시스템 프롬프트/데이터 컨텍스트 직렬화(`cpDataContext`, `sys`) **불필요** — 우리 엔진이
  DB의 EVTX 이벤트를 도구로 직접 조회한다. 그 부분은 지워도 됨.
- `cpHistory`는 화면 표시용으로만 유지. (현재 엔진은 질의 1건씩 독립 처리 — 대화 맥락 미사용. 필요하면 추가 가능.)
- 로딩 표시(`cpTypingOn`/`cpTypingOff`)는 **그대로 유지** — 로컬 LLM은 응답이 수~수십초.

---

## 2. 응답 스키마

```jsonc
{
  "answer": "사람이 읽는 한국어 분석 텍스트",
  "tool_calls": [ { "name": "analyze_logons", "arguments": { } } ],  // 감사 추적(어떤 도구 썼는지)
  "evidence":  [ { "pk":1, "time_kst":"...", "event_id":4625,
                   "category":"logon_fail", "account":"IEUser",
                   "source_ip":null, "logon_type":2, "computer":"..." } ],
  "llm": false   // true=로컬 LLM 해석, false=Ollama 미설치 자동 트리아지
}
```

- `tool_calls` / `evidence`는 copilot 답변 버블의 **"근거 보기" 접이식**에 그대로 뿌리면 됨.
- `evidence`는 길 수 있음(최대 50). 스크롤/펼치기 처리.

---

## 3. 데이터 출처 구분 (중요)

- 샘플 copilot은 **part-1 타임라인 JSON**(activities[])을 컨텍스트로 썼음.
- **우리 `/ask`는 그 JSON을 안 본다.** EVTX 보안/시스템 이벤트(로그온·권한·계정·서비스·로그삭제 등)를
  우리 DB(`db/events.sqlite`)에서 조회해 답한다.
- 즉 두 데이터 도메인이 있다:
  - (1) 사용자 활동 타임라인 = 1번 팀원
  - (2) EVTX 이벤트 포렌식 = 우리(3번) → `/ask`
- copilot이 어느 쪽에 물을지는 팀에서 결정. **EVTX/로그온/침해 질문은 우리 `/ask`로** 라우팅 권장.

---

## 4. DB가 비어있을 때

`/ask`는 DB에 이벤트가 없으면 `"먼저 EVTX를 분석(적재)하세요"` 안내를 반환한다.
**"분석 시작" 버튼**(UI 팀원 제작)에서 아래를 호출하면 파이프라인(파싱→적재→이상탐지)이 돈다:

```js
// 분석 시작 — .evtx 경로를 넘긴다(파일 선택은 UI/메인앱 담당)
const r = await fetch("http://127.0.0.1:8765/analyze", {
  method:"POST", headers:{"Content-Type":"application/json"},
  body: JSON.stringify({ path: evtxPath })
}).then(x=>x.json());
// r = { ok, records, stats:{total,by_event_id,...}, anomaly:{high_risk,anomalies:[...]} }
```

- 적재 후 `/ask`·`/anomaly`·`/export` 가 바로 동작한다.
- **이상탐지 알림 패널**은 `/anomaly`(또는 `/analyze` 응답의 `anomaly`)의 `high_risk` / `anomalies[{time,score,reason}]` 사용.
- **정규화 산출물 다운로드**는 `GET /export` → `events[]`(원본 `event_data` dict 포함)를 파일로 저장.
- ⚠ 윈도우(60분 단위) 수가 8개 미만이면 IsolationForest 학습을 생략(`fitted:false`) — 소량 샘플 보호. `note` 표시.

---

## 4.5 첫 실행 셋업 화면 (download-on-first-run) — UI 필요

로컬 LLM(Ollama + qwen2.5:7b, 4.7GB)은 .exe 에 미포함 → **첫 실행 때 1회 다운로드**. 흐름:

```js
// (1) 앱 시작 시 점검
const st = await fetch("http://127.0.0.1:8765/setup/status").then(r=>r.json());
if (st.needs_setup) {
  showSetupScreen();                          // 셋업 화면 표시(질의창 잠금)
  await fetch("http://127.0.0.1:8765/setup/start", {method:"POST"});
  // (2) 진행률 폴링(1~2초 간격)
  const timer = setInterval(async () => {
    const p = await fetch("http://127.0.0.1:8765/setup/progress").then(r=>r.json());
    setProgressBar(p.pct, p.status);          // 예: "qwen2.5:7b 다운로드: pulling… 63%"
    if (p.done) {
      clearInterval(timer);
      if (p.ok) hideSetupScreen();            // 완료 → 도구 시작
      else showError(p.error);                // 실패 → 안내/재시도 버튼
    }
  }, 1500);
}
// st.needs_setup === false → 셋업 스킵, 바로 도구 사용
```

- `phase`: `idle → install → serve → pull → done`(또는 `error`). 사람이 읽는 현재 작업은 `status`.
- `pct`: 0~100(현재 단계 기준). 모델 pull 단계가 대부분(4.7GB). 인터넷 1회 필요.
- 완료 후 재실행은 `needs_setup:false` → 셋업 스킵.
- **발표 데모가 오프라인이면**: 미리 1회 실행해 모델 받아두면 현장에선 셋업 안 뜸.

> 패키징 시 `vendor/OllamaSetup.exe` 를 동봉하면 Ollama 자체도 다운로드 없이 무인 설치(권장).

---

## 5. 지금 바로 테스트(엔진만 단독)

```bash
cd evtx-ai-investigator
python -m src.server            # 서버 기동
# 다른 터미널:
curl http://127.0.0.1:8765/health
curl -X POST http://127.0.0.1:8765/ask -H "Content-Type: application/json" -d "{\"question\":\"로그인 실패 있었어?\"}"
```

스키마 변경/추가 필요하면 엔진 담당(나)에게 요청.
