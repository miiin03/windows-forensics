# UI 담당자 안내 — Windows Timeline(OS Timeline) 연동

## 결론 먼저
**UI 담당자가 html에서 바꿀 건 없습니다.** 기존 "JSON 불러오기" 기능 그대로 쓰면 됩니다.
우리 엔진이 `timeline_result.json`을 만들고, 그 파일을 뷰어가 불러오면 끝입니다.

---

## 전체 동작 (사용자 입장)
```
[도구 실행 → "분석 시작"]
        ↓
엔진이 이 PC의 ActivitiesCache.db 경로를 자동으로 찾음   ← 구현 완료(우리)
        ↓
파싱(정상 기록) + 비할당 영역 삭제 기록 복구(carving)     ← 구현 완료(우리)
        ↓
timeline_result.json 생성                               ← 구현 완료(우리)
        ↓
뷰어(index.html)가 그 JSON을 불러와 화면 표시            ← 기존 "JSON 불러오기" 그대로
```

---

## 역할 분담 (헷갈리지 않게)
| 레이어 | 하는 일 | 담당 |
|---|---|---|
| **엔진** | db 자동탐색 + 파싱 + 복구 → `timeline_result.json` | 우리(완료) |
| **런처(exe/도구)** | "분석 시작" 버튼 → 엔진 실행 → json을 html 옆에 두고 브라우저 열기 | 패키징/팀 |
| **뷰어(html)** | json 불러와 표시 | UI 담당자 = **손 안 댐** |

> ⚠ 중요: "분석 시작" 버튼은 **html 안이 아니라 도구(런처/exe) 쪽**에 둡니다.
> 브라우저는 보안상 로컬 프로그램(엔진)을 직접 실행할 수 없기 때문입니다.
> 런처가 엔진을 돌린 뒤 결과 json을 뷰어에 넘깁니다.

---

## UI 담당자가 확인할 것 (사실상 끝)
1. 기존 **"JSON 불러오기"** 기능 유지 → 사용자가 `timeline_result.json` 선택하면 표시됨. (이게 기본)
2. (선택) 더 매끄럽게: html과 **같은 폴더**에 `timeline_result.json`이 있으면 자동 로드.
   현재 html이 이미 `./timeline_result.json`을 fetch 시도하므로, 런처가 그 위치에 파일을 두면 자동 표시됨
   (단 file:// 더블클릭이 아니라 로컬 서버로 띄울 때 자동 fetch 동작 — 더블클릭이면 "JSON 불러오기" 버튼 사용).
3. 챗봇 칸/색상 추가분은 우리와 무관. 그대로 두세요.

---

## 우리 데이터가 화면에 어떻게 뜨나
`artifact: "timeline"` (= "OS Timeline" 칩)으로 들어갑니다.
- **삭제 복구 기록** → 노란 **"카빙" 배지 + 점선 카드** + `conf` 표시, 상단 "카빙 복원" 카운트.
- **정상 기록** → 초록 "정상" 배지.
- 정상·삭제가 한 타임라인에 시간순으로 섞여 표시 + 24시간 시계 반영.
- 카드 클릭 → 상세 패널에 복구 출처(`detail`) + 시각.

기존 칩·배지·시계·상세패널이 그대로 동작 → **추가 구현 불필요.**

---

## JSON 형식 (참고 — 엔진이 보장)
```jsonc
{ "meta": { tool, version, sources, analyzed_at_kst, timezone, stats:{total,normal,carved,...} },
  "activities": [ { id, artifact:"timeline", category, source:"normal"|"carved",
                    payload_format, confidence, app_id, app_name, title, url, detail,
                    start_time_kst, end_time_kst, last_modified_kst, raw_payload_b64 }, ... ] }
```
시각은 모두 **KST(+09:00)**. `decrypted`/`source_browser`/`secret_value`는 우리 쪽 항상 null.
