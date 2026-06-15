# WinTrace AI — 시연 가이드

> 발표/녹화용 시나리오 모음. 구현한 기능을 **무엇으로 어떻게** 보여줄지 정리.
> 경로는 본 프로젝트 기준. 베이스: `C:\Users\irise\Desktop\kmou\4-1\디지털포렌식\windows-forensics\wintrace\`

---

## 0. 준비

- **Ollama** 실행 + 모델: `ollama pull qwen2.5:7b` (Windows는 서비스 자동 실행). exe는 첫 실행 시 자동 셋업.
- **실행 2가지**
  - 개발: `python -m src.server` → 브라우저로 `ui/index.html` (LLM = claude CLI 우선, 빠름)
  - 배포본: `dist\WinTraceAI.exe` 더블클릭 (LLM = 로컬 Ollama, 오프라인)
- **상단 분석 바**: ① 사용자 타임라인 / ② 보안 이벤트(EVTX), 각각 `📁 경로 분석` · `🖥️ 내 PC 자동`

---

## 1. 메인 시나리오 — 통합 데모 (타임라인 + 카빙 + 교차분석) ⭐

**가장 임팩트 큰 데모. 한 사건으로 기능 3개를 엮음.**

### 1-A. 사용자 타임라인 + 카빙 복구
① 경로칸에 데모 db 입력 → **📁 경로 분석**
```
...\wintrace\sample\demo_ActivitiesCache.db
```
→ 한 타임라인에:
- **초록 "정상" 4건** — 오전 정상 업무(Word·위키·검색·다운로드)
- **노란 "카빙" 점선카드 ~30건** — 공격자가 **삭제한 명령 히스토리를 복구**:
  정찰(whoami/systeminfo) → 백도어 계정(net user backup_adm /add) → Defender 무력화 →
  mimikatz·lsass 덤프 → 기밀파일 접근(급여명세/고객정보) → 외부 반출 → **로그 삭제(wevtutil cl Security)**
- 카드 클릭 → 복구 출처(`freelist p3 off…`) 표시 = 포렌식 근거

> 포인트: "공격자가 활동 기록을 지웠지만 **삭제 영역에서 복구**(SQLite 카빙)". 36건 삭제 → 30건 복구(best-effort).

### 1-B. 보안 이벤트(EVTX) 합치기
② 경로칸에 1102 샘플 → **🛡️ 경로 분석**
```
...\wintrace\samples\Defense Evasion\DE_1102_security_log_cleared.evtx
```
→ 08:35 지점에 🧹 **감사 로그 삭제(1102)** 이벤트가 같은 타임라인에 합쳐짐, 🔴 고위험 배지

### 1-C. AI 교차분석
🤖 드로어 → 질문:
- "공격자가 어떤 작업을 했고 흔적을 어떻게 지웠어?"
- "사용자가 로그를 지우려 한 정황이 있는데, 보안 로그에도 실제 삭제 기록이 있어?"

→ AI가 **복구된 명령 체인(타임라인) + 실제 1102(보안로그)**를 교차해 설명:
"08:3x 공격자가 `wevtutil cl Security`로 로그 삭제(카빙 복구) → 보안로그에 1102 감사로그 삭제 실제 발생. 증거 인멸."

---

## 2. EVTX 공격 샘플 — 단독 탐지 데모

② 경로칸에 넣고 **🛡️ 경로 분석** → 🤖 "이 로그에서 의심스러운 공격 정황 찾아줘"

| 파일(samples\ 이하) | EventID | 탐지 | 의미 |
|---|---|---|---|
| `Defense Evasion\DE_1102_security_log_cleared.evtx` | 1102 | 🔴 log_cleared | 감사로그 삭제(증거인멸) |
| `Defense Evasion\DE_Fake_ComputerAccount_4720.evtx` | 4720 | account | 계정 생성(백도어) |
| `Lateral Movement\LM_Remote_Service02_7045.evtx` | 7045 | service | 서비스 설치(지속성) |
| `Privilege Escalation\System_7045_namedpipe_privesc.evtx` | 7045 | service | 서비스 통한 권한상승 |
| `Credential Access\kerberos_pwd_spray_4771.evtx` | 4771 | kerberos | 패스워드 스프레이(자격증명 공격) |
| `Persistence\Network_Service_Guest_added_to_admins_4732.evtx` | 4732 | group_add | Guest→관리자그룹(지속성) |
| `Privilege Escalation\security_4624_4673_token_manip.evtx` | 4672/4673 | priv | 토큰 조작/특수권한 |
| `Lateral Movement\LM_4624_mimikatz_sekurlsa_pth_source_machine.evtx` | 4624 | logon_ok | Pass-the-Hash 원격 로그온 |
| `Credential Access\CA_4624_4625_LogonType2_LogonProc_chrome.evtx` | 4624/4625 | logon | 로그온 성공/실패(기본 샘플) |

> ⚠ **한 파일씩** — `📁/🛡️ 경로 분석`은 매번 DB를 덮어씀(누적 아님).
> ⚠ 매핑 밖 EventID(예: 104 System 로그삭제, Sysmon 전용)는 "기타 이벤트"로만 표시 — Security 채널 위주 매핑.

---

## 3. 실 PC 분석 — 자동 수집

### 3-A. 사용자 타임라인 (자동 탐색)
① **🖥️ 내 PC 자동** → 내 PC `ActivitiesCache.db` 자동탐색·파싱(정상기록 + 카빙) → 실제 활동 타임라인.

### 3-B. 보안 이벤트 (자동 수집)
② **🖥️ 내 PC 자동** → `wevtutil`로 내 Security 로그 복사본 수집·분석.
> **관리자 권한**으로 실행해야 함(라이브 로그 잠금). 일반 권한이면 "관리자로 실행하세요" 안내.

---

## 4. ML 이상탐지

- **실 PC 대용량 보안로그**(다일자, 수만 건)에서 잘 보임 — Isolation Forest가 시간 윈도우(60분) 단위로 비정상 시점 플래그.
- 🤖 "이상 징후 있는 시간대 보여줘" → 부팅/세션 시작 폭증 등 비정상 윈도우 + 사유.
- ⚠ 윈도우 8개 미만(소량 샘플)이면 학습 생략(`fitted:false`) — 규칙탐지(1102 등)는 그래도 동작.

---

## 5. AI 자연어 질의 예시 (🤖)

- "로그인 실패가 많았던 계정 있어? 무차별대입 의심돼?"
- "감사 로그가 삭제된 적 있어?"
- "백도어 계정이나 서비스가 설치된 적 있어?"
- "이상 징후 있는 시간대 보여줘"
- "이 로그에서 의심스러운 공격 정황 전부 찾아줘"
- (교차) "심야에 공격자가 한 일을 사용자 활동과 보안 로그로 같이 설명해줘"

> 답변 ~수초(claude)~30초(Ollama 7b). 길면 **ESC**로 취소 가능.

---

## 6. 배포/시스템 데모

- **첫 실행 셋업**: Ollama 없는 PC에서 `WinTraceAI.exe` 첫 구동 → 자동으로 Ollama 설치 + 모델 다운로드(진행률). 버튼 없이 완전 자동.
- **단일 .exe**: 더블클릭 한 번으로 UI+엔진+AI 구동. 로고 아이콘.
- **오프라인·증거 비유출**: 배포본은 로컬 LLM → 증거가 외부로 안 나감(포렌식 무결성).

---

## 7. 발표 영상 구성 제안 (4편)

1. **개요+통합 데모** — §1 (타임라인+카빙+교차분석). 가장 먼저, 가장 길게.
2. **공격 탐지** — §2 샘플 2~3개 + §4 ML.
3. **실 PC** — §3 자동 수집(타임라인+보안로그).
4. **배포** — §6 첫실행 셋업 + .exe.

---

## 부록 — 데모 db 재생성
스토리/공격명령 바꾸려면 `sample/build_demo_db.py` 의 `_NORMAL`/`_ATTACKER_CMDS` 수정 후:
```
python sample/build_demo_db.py
```
카빙 원리: `secure_delete=OFF` + INSERT→DELETE(VACUUM 안 함) → 삭제 셀이 freelist에 보존 → part-1 카버가 복원.
