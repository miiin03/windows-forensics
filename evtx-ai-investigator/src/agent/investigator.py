"""AI 조사관 — 자연어 질의 → 도구 호출 → 근거 기반 답변. DESIGN.md §3.5, §9.

흐름(LLM 사용 시): 질의 → Ollama(qwen2.5) tool-calling → 도구 실행 → 결과 되돌림 → 최종 답변.
Ollama 미설치/미실행 시: 핵심 도구를 직접 실행해 근거 요약을 돌려주는 fallback(데모·통합 선행 가능).

반환 계약(UI copilot 연동): {"answer": str, "tool_calls": [...], "evidence": [event...]}
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

from ..store.store import open_db
from .tools import build_registry, TOOL_SCHEMAS

# 일부 로컬 모델(qwen2.5 등)은 도구 호출을 네이티브 tool_calls 필드 대신 본문 텍스트에
# <tool_call>{...}</tool_call> 형태로 뱉는다. 이를 잡아 실행하고, 최종 답변에선 제거한다.
_TOOL_CALL_TAG = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)
_STRAY_TAGS = re.compile(r"</?tool_call>|<\|.*?\|>")
# 등록된 도구명 집합 — 본문 JSON을 도구호출로 채택할지 판별(일반 답변 오인 방지)
_KNOWN_TOOLS = {s["function"]["name"] for s in TOOL_SCHEMAS}
# 도구를 부르겠다고 '예고만' 하고 끝내는 패턴(실제 호출 없이 턴 종료) → 자동 넛지로 실행 유도
_PROMISE = re.compile(
    r"(보겠습니다|하겠습니다|확인하겠|분석하겠|찾아보겠|살펴보겠|점검하겠|조사하겠|"
    r"분석해\s*보|확인해\s*보|찾아\s*보|살펴\s*보|점검해\s*보)"
)
# 사용자에게 정보를 되묻거나 답을 미루는 패턴(한/영) → 바로 행동하도록 넛지
_DEFER = re.compile(
    r"(제공해\s*주|알려\s*주|입력해\s*주|지정해\s*주|말씀해\s*주|주시겠|할까요|괜찮을까요|"
    r"please provide|could you|provide me|let me know|specify|would you like)",
    re.IGNORECASE,
)
MAX_NUDGES = 2  # 예고-넛지 최대 횟수(무한루프 방지)


def _is_mostly_english(text: str) -> bool:
    """답변이 한국어가 아닌 영어 위주로 샜는지(언어 드리프트 감지)."""
    han = sum(1 for c in text if "가" <= c <= "힣")
    eng = sum(1 for c in text if c.isascii() and c.isalpha())
    return eng > 25 and han < eng * 0.35

MODEL = "qwen2.5:7b"   # 로컬 Ollama 모델(품질 우선; 빠른 옵션 "qwen2.5:3b"는 추론 약함)
MAX_STEPS = 7          # tool-calling 왕복 상한(무한루프 방지; 예고-넛지 여유 포함)

SYSTEM_PROMPT = (
    "당신은 윈도우 이벤트 로그를 분석하는 포렌식 조사관입니다. "
    "반드시 모든 답변을 한국어로만 작성하세요. 중국어·영어 등 다른 언어를 한 글자도 섞지 마세요.\n"
    "사용자 질문에 답하려면 제공된 도구를 호출해 실제 로그 데이터를 확인하고 근거를 들어 답하세요.\n"
    "중요: 도구를 '부르겠다/분석해보겠다/확인해보겠다'라고 예고만 하지 말고, 필요하면 그 도구를 "
    "지금 즉시 호출하세요. 더 호출할 도구가 없으면 지금까지의 결과만으로 답변을 완결하세요. "
    "다음에 무엇을 하겠다는 예고로 답을 끝내지 마세요.\n"
    "절대 사용자에게 추가 정보(시간범위 등)를 되묻지 마세요. 기간이 불명확하면 전체 기간으로 즉시 조회해 "
    "결론을 내세요. 질문으로 답을 끝내지 마세요.\n"
    "절대 금지: 도구가 돌려준 JSON 구조·필드 이름을 설명하지 마세요('event_id 필드는…', 'category로 표시된…' 식 금지). "
    "source·event_data·window_id·pk 같은 내부 필드는 언급하지 마세요. "
    "데이터를 받아쓰지 말고, 사용자 질문에 대한 결론을 일상어로 직접 답하세요. "
    "예: '로그인 실패 1회(IEUser), 성공 3회. 무차별대입 정황 없음.' 처럼 사실+판단만.\n"
    "말투: 보안 비전문가도 이해하도록 쉽고 친절한 한국어로. 어려운 전문용어는 괄호로 짧게 풀이"
    "(예: '로그온 타입 3(원격 네트워크 접속)'). 문장은 짧게.\n"
    "서식: 절대 마크다운 기호(*, **, #, 백틱 `)를 쓰지 마세요. 강조는 일반 문장으로, 목록은 불릿(•)으로.\n"
    "답변 구성 규칙:\n"
    "1) 먼저 '로그 근거'를 제시하세요 — 반드시 도구 결과(이벤트 ID·시각·횟수·계정·SID·도메인 등)에만 근거.\n"
    "2) 위험 판단은 반드시 로그(도구가 반환한 실제 이벤트·횟수·패턴)에 근거하세요. 근거가 있으면 "
    "무차별대입·ML 비정상뿐 아니라 아래 '의심 패턴'의 다른 공격 정황도 적극적으로 지적하세요. "
    "단, 로그에 아무 근거가 없는 위협(예: 막연히 '키로거가 있을 수도')은 절대 지어내지 마세요. "
    "도구로 확인했는데 해당 정황이 없으면 그 부분은 '특이사항 없음'이라고 분명히 말하세요(앞뒤 모순 금지).\n"
    "3) 로그에 없는 '계정·이벤트의 일반적 의미'만(예: SYSTEM은 윈도우 시스템 계정) 도움이 될 때 덧붙이되, "
    "줄을 바꿔 '참고(로그 외 일반 지식):' 으로 시작하세요. 이 부분에 위협 추측은 넣지 마세요. "
    "확실치 않으면 생략하세요.\n"
    "의심 패턴 → 확인 도구(여러 공격을 폭넓게 점검):\n"
    "• 무차별대입: 4625 다수 → analyze_logons\n"
    "• 자격증명 공격(Pass-the-Hash/Kerberoasting): 4776 다수·4771/4769 실패 → "
    "find_security_events(categories=['ntlm','kerberos']) 또는 search_events(event_id=4776)\n"
    "• 권한 상승: 4672 특수권한·4728/4732 관리자그룹 추가 → find_security_events(categories=['priv','group_add'])\n"
    "• 백도어/지속성: 4720 계정생성·7045 서비스설치 → find_security_events(categories=['account','service'])\n"
    "• 증거 인멸: 1102 로그삭제 → find_security_events(categories=['log_cleared'])\n"
    "• 원격 접속: 로그온 타입 10(RDP)/3(네트워크) → search_events 로 logon_type 확인\n"
    "• 이상 시간대/급증: get_anomalies\n"
    "도구 선택 가이드:\n"
    "• 특정 계정/IP 관련 이벤트를 찾을 땐 search_events(account=계정명) 또는 search_events(event_id=...) 사용. "
    "get_event_detail 은 특정 이벤트의 pk 를 이미 알 때만 사용(계정명으로 호출 금지).\n"
    "• 전반 통계·시간범위는 summarize_stats. '의심스러운 거 있어?' 같은 포괄 질문은 "
    "find_security_events 와 get_anomalies 를 먼저 호출해 폭넓게 점검하세요.\n"
    "시간범위 규칙: 도구의 start/end 는 사용자가 구체적 날짜·시간을 명시했을 때만 채우세요. "
    "사용자가 기간을 말하지 않으면 절대 날짜를 지어내지 말고 start/end 를 생략해 전체 기간을 조회하세요.\n"
    "이벤트ID 의미(혼동 금지): 4624=로그온 성공, 4625=로그온 실패, 4634/4647=로그오프, "
    "4672=특수권한(관리자), 4688=프로세스 생성, 4720=계정 생성, 4728/4732=관리자그룹 추가, "
    "4663=개체(파일/레지스트리) 접근, 4656=핸들 요청, 5140/5145=네트워크 공유 접근, "
    "5156=네트워크 연결 허용(방화벽), 4768/4769/4771=Kerberos 인증, 4776=NTLM 인증, "
    "7045=서비스 설치, 1102=감사 로그 삭제(증거 인멸). category 필드의 logon_ok=성공, logon_fail=실패.\n"
    "절대 규칙: 위 목록에 없는 EventID 는 의미를 지어내지 말고 '기타 이벤트(EventID N)'로만 표현하세요. "
    "summarize_stats 의 by_event_id 에 1102·4720·7045·4672·4728·4732 같은 고위험 ID 가 "
    "단 1건이라도 있으면 절대 무시하지 말고 반드시 의심 정황으로 보고하고 find_security_events 로 상세 확인하세요.\n"
    "다시 강조: 최종 답변은 오직 한국어로만. 다른 언어 혼용 금지."
)

# 도구 결과에서 근거 이벤트를 모을 때 볼 리스트 키
_EVIDENCE_KEYS = ("events", "items", "findings", "anomalies", "brute_force_suspects")


class _OllamaUnavailable(Exception):
    """Ollama 미설치 또는 서버 미응답."""


class _ClaudeUnavailable(Exception):
    """claude CLI 없음 또는 실행 실패."""


def _scan_json_objects(text: str) -> list[dict]:
    """텍스트 어디서든 균형 잡힌 JSON 객체를 모두 추출(접두문구·잘린 태그 무관)."""
    dec = json.JSONDecoder()
    out: list[dict] = []
    i, n = 0, len(text)
    while i < n:
        if text[i] == "{":
            try:
                obj, end = dec.raw_decode(text, i)
                out.append(obj)
                i = end
                continue
            except ValueError:
                pass
        i += 1
    return out


def _parse_text_tool_calls(content: str | None) -> list[dict]:
    """본문 텍스트에 들어온 도구 호출 추출.

    <tool_call>{...}</tool_call> 정식 형태뿐 아니라, 여는 태그 누락·접두 잡음("leton…")·
    단독 JSON 덩어리까지 잡는다(로컬 소형모델의 불완전 출력 방어, DESIGN §9).
    """
    if not content:
        return []
    candidates = [
        obj for obj in _scan_json_objects(content)
        if isinstance(obj, dict) and obj.get("name")
    ]
    # name 이 실제 등록된 도구일 때만 채택(일반 JSON 답변 오인 방지)
    return [obj for obj in candidates if obj["name"] in _KNOWN_TOOLS]


def _sanitize_answer(content: str | None) -> str:
    """최종 답변에서 도구호출 마크업·특수토큰·마크다운 기호 제거(비전문가 가독성)."""
    if not content:
        return "(빈 응답)"
    text = _TOOL_CALL_TAG.sub("", content)
    text = _STRAY_TAGS.sub("", text)
    # 마크다운 정리: 헤딩(#) → 제거, 목록 마커(*,-) → •, 강조/코드(**,__,`) → 제거
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^(\s*)[*-]\s+", r"\1• ", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    return text.strip() or "(빈 응답)"


def _normalize_args(args):
    if isinstance(args, str):
        try:
            return json.loads(args)
        except ValueError:
            return {}
    return args or {}


def _collect_evidence(result, bucket: list):
    """도구 반환 dict에서 근거가 될 이벤트들을 evidence 버킷에 누적(최대 50)."""
    if not isinstance(result, dict):
        return
    # 단일 이벤트 상세(get_event_detail)도 근거로 채택
    if "pk" in result and "event_id" in result and len(bucket) < 50:
        bucket.append(result)
        return
    for k in _EVIDENCE_KEYS:
        v = result.get(k)
        if isinstance(v, list):
            for item in v:
                if len(bucket) >= 50:
                    return
                bucket.append(item)


def ask(question: str, conn=None, db_path: str | None = None, timeline: list | None = None) -> dict:
    """자연어 질의에 답한다. conn 미지정 시 db_path 로 연결.

    timeline: part-1 사용자 활동 타임라인(activities[]). 주면 EVTX 도구 + 타임라인 교차 분석.
    """
    own = conn is None
    if own:
        if db_path is None:
            from ..paths import default_db_path
            db_path = default_db_path()
        conn = open_db(db_path)
    try:
        registry = build_registry(conn)
        # 백엔드: 개발 실행은 claude CLI(구독, 빠름) 우선 → 로컬 Ollama → fallback.
        # 단 빌드된 .exe(frozen)는 항상 로컬 Ollama 사용(배포본은 오프라인 로컬 LLM).
        # EVTX_NO_CLAUDE=1 로도 claude 비활성화 가능.
        if _use_claude() and _claude_exe():
            try:
                return _ask_claude_cli(question, registry, timeline)
            except _ClaudeUnavailable:
                pass
        try:
            return _ask_llm(question, registry, timeline)
        except _OllamaUnavailable:
            return _ask_fallback(question, registry)
    finally:
        if own:
            conn.close()


def _serialize_timeline(activities: list, cap: int = 80) -> str:
    """part-1 활동 타임라인(activities[])을 LLM 컨텍스트용 짧은 텍스트로 직렬화."""
    lines = []
    for a in activities[:cap]:
        t = a.get("start_time_kst") or a.get("last_modified_kst") or "시각미상"
        parts = [t, a.get("category") or "?", a.get("app_name") or "(앱미상)"]
        if a.get("title"):
            parts.append("제목:" + str(a["title"])[:60])
        if a.get("url"):
            parts.append("URL:" + str(a["url"])[:80])
        if a.get("source") == "carved":
            parts.append("(삭제복원/카빙)")
        lines.append("• " + " | ".join(parts))
    extra = f"\n…외 {len(activities) - cap}건 생략" if len(activities) > cap else ""
    return "\n".join(lines) + extra


def _timeline_note(timeline: list | None) -> str | None:
    """part-1 타임라인 컨텍스트 주입용 system 노트(없으면 None)."""
    if not timeline:
        return None
    return (
        "참고 데이터 — 사용자 활동 타임라인(part-1, 브라우저 방문/파일 열람/앱 실행 등). "
        "이것은 도구가 아니라 아래 제공된 텍스트입니다. EVTX 보안 이벤트는 도구로 조회하고, "
        "사용자 활동에 관한 질문은 아래 타임라인 텍스트를 근거로 답하세요. 두 정보를 시각 기준으로 "
        "교차 분석해도 좋습니다(예: 의심 로그온 시각 전후의 사용자 활동).\n" + _serialize_timeline(timeline)
    )


def _precheck_note(registry: dict) -> str | None:
    """고위험 이벤트 결정적 사전 점검 노트(모델이 도구 안 불러도 핵심 정황 주입)."""
    try:
        sec = registry["find_security_events"]()
    except Exception:
        return None
    if not sec.get("findings"):
        return None
    summary = ", ".join(
        f"{f['category']} {f['count']}건(EventID {f['event_ids']})" for f in sec["findings"]
    )
    note = "사전 자동 점검 결과(결정적 사실, 답변에 반드시 반영): 고위험 이벤트 발견 — " + summary
    if sec.get("high_risk"):
        note += ". 감사 로그 삭제(1102) 포함 → 증거 인멸 정황 가능."
    return note


# claude CLI(headless) 백엔드용 시스템 프롬프트 — 도구는 우리가 미리 실행해 데이터로 넘기므로
# tool-calling 지시는 빼고 '답변 규칙'만. SYSTEM_PROMPT 의 핵심 규칙과 동일 취지.
_CLI_SYSTEM = (
    "당신은 윈도우 이벤트 로그(EVTX)와 사용자 활동 타임라인을 분석하는 포렌식 조사관입니다. "
    "아래 [분석 데이터]는 결정적 도구로 이미 계산된 사실입니다. 이 데이터만 근거로 사용자 질문에 답하세요.\n"
    "규칙:\n"
    "1) 반드시 한국어로만. 영어·중국어 혼용 금지.\n"
    "2) 데이터의 JSON 구조·필드 이름을 설명하지 마세요. 결론을 일상어로 직접 말하세요. "
    "보안 비전문가도 알게 쉽게, 전문용어는 괄호로 짧게 풀이.\n"
    "3) 위험 판단은 데이터에 실제 근거가 있을 때만(무차별대입·로그삭제 1102·계정생성 4720·권한상승·서비스설치 등). "
    "근거 없으면 '특이사항 없음'이라 분명히 말하고 위협을 지어내지 마세요.\n"
    "4) 사용자에게 되묻지 말고 가진 데이터로 결론을 내세요. 마크다운 기호(*,#,`) 쓰지 말고 불릿은 •.\n"
    "5) 로그 밖 일반 지식은 도움이 될 때만 '참고:'로 시작해 짧게 덧붙이세요.\n"
    "이벤트ID: 4624=로그온 성공, 4625=실패, 4672=특수권한, 4720=계정생성, 1102=감사로그 삭제(증거인멸), 7045=서비스 설치."
)


def _use_claude() -> bool:
    """claude CLI 백엔드를 쓸지. 빌드 .exe(frozen)는 항상 로컬 Ollama → False."""
    if os.environ.get("EVTX_NO_CLAUDE"):
        return False
    try:
        from ..paths import is_frozen
        if is_frozen():
            return False   # 배포본(.exe)은 오프라인 로컬 LLM 전용
    except Exception:
        pass
    return True


def _claude_exe() -> str | None:
    """claude CLI 실행 파일 경로(없으면 None)."""
    e = shutil.which("claude")
    if e:
        return e
    for c in (os.path.expanduser(r"~\.local\bin\claude.exe"),
              os.path.expanduser("~/.local/bin/claude")):
        if os.path.exists(c):
            return c
    return None


def _ask_claude_cli(question: str, registry: dict, timeline: list | None = None) -> dict:
    """claude CLI(headless `-p`) 백엔드. 구독 인증 사용(추가 결제 없음).

    tool-calling 대신: 결정적 도구로 핵심 집계를 먼저 계산 → [분석 데이터]로 넘겨 자연어 답변만 받는다.
    ⚠ claude CLI(개발용)를 자동 호출하는 방식 — 이 PC 로그인에 의존, 배포본(.exe)에선 동작 안 함
      (그땐 Ollama 사용). 데모/개발 머신 전용 고속 옵션.
    """
    exe = _claude_exe()
    if not exe:
        raise _ClaudeUnavailable("claude CLI 없음")

    # 결정적 집계(환각 차단) + 근거 수집
    evidence: list = []
    data: dict = {}
    tool_log: list = []
    for name in ("summarize_stats", "analyze_logons", "find_security_events", "get_anomalies"):
        try:
            res = registry[name]()
            data[name] = res
            tool_log.append({"name": name, "arguments": {}})
            _collect_evidence(res, evidence)
        except Exception:
            continue

    blocks = ["[분석 데이터]", json.dumps(data, ensure_ascii=False, default=str)]
    if timeline:
        blocks.append("[사용자 활동 타임라인(part-1)]\n" + _serialize_timeline(timeline))
    blocks.append("[질문]\n" + question)
    prompt = "\n\n".join(blocks)

    try:
        proc = subprocess.run(
            [exe, "-p", "--system-prompt", _CLI_SYSTEM],
            input=prompt.encode("utf-8"),
            capture_output=True, timeout=180,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        raise _ClaudeUnavailable(f"claude 실행 실패: {e}") from e

    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace")[:200]
        raise _ClaudeUnavailable(f"claude 오류(exit {proc.returncode}): {err}")

    answer = _sanitize_answer(proc.stdout.decode("utf-8", "replace"))
    return {"answer": answer, "tool_calls": tool_log, "evidence": evidence, "llm": True}


def _ask_llm(question: str, registry: dict, timeline: list | None = None) -> dict:
    try:
        import ollama
    except ImportError as e:
        raise _OllamaUnavailable("ollama 미설치") from e

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    # part-1 타임라인 + 고위험 사전점검 컨텍스트 주입(있을 때)
    for note in (_timeline_note(timeline), _precheck_note(registry)):
        if note:
            messages.append({"role": "system", "content": note})

    tool_log: list = []
    evidence: list = []
    nudges = 0
    try:
        for _ in range(MAX_STEPS):
            resp = ollama.chat(
                model=MODEL, messages=messages, tools=TOOL_SCHEMAS,
                options={"temperature": 0},  # 결정적 출력 → 언어 드리프트·환각 감소
            )
            msg = resp["message"]
            messages.append(msg)

            # (1) 네이티브 tool_calls, 없으면 (2) 본문 텍스트에 박힌 호출을 파싱
            calls: list[tuple[str, dict]] = [
                (tc["function"]["name"], _normalize_args(tc["function"].get("arguments")))
                for tc in (msg.get("tool_calls") or [])
            ]
            if not calls:
                calls = [
                    (obj["name"], _normalize_args(obj.get("arguments")))
                    for obj in _parse_text_tool_calls(msg.get("content"))
                ]

            if not calls:  # 도구 호출 없음 → 최종 답변 후보
                answer = _sanitize_answer(msg.get("content"))
                # 예고만/사용자에게 되묻기/영어 드리프트 → 바로 행동·한국어 완결하도록 넛지
                if nudges < MAX_NUDGES and (
                    _PROMISE.search(answer) or _DEFER.search(answer)
                    or _is_mostly_english(answer)
                ):
                    nudges += 1
                    messages.append({
                        "role": "system",
                        "content": "사용자에게 추가 정보를 되묻지 말고(시간범위 등 미지정이면 전체 기간으로) "
                        "지금 가진 도구 결과만으로 분석을 즉시 완결하세요. 도구가 더 필요하면 지금 호출하고, "
                        "아니면 결론을 내세요. 반드시 한국어로만 작성하세요(영어·중국어 금지).",
                    })
                    continue
                return {
                    "answer": answer,
                    "tool_calls": tool_log,
                    "evidence": evidence,
                    "llm": True,
                }

            for name, args in calls:
                tool_log.append({"name": name, "arguments": args})
                fn = registry.get(name)
                if fn is None:
                    result = {"error": f"unknown tool: {name}"}
                else:
                    try:
                        result = fn(**args)
                    except Exception as ex:  # 도구 인자 오류 → 모델에 되돌려 재시도
                        result = {"error": f"{type(ex).__name__}: {ex}"}
                _collect_evidence(result, evidence)
                messages.append({
                    "role": "tool",
                    "name": name,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                })
        return {
            "answer": "도구 호출 한도에 도달했습니다. 질문을 더 구체적으로 해주세요.",
            "tool_calls": tool_log,
            "evidence": evidence,
            "llm": True,
        }
    except _OllamaUnavailable:
        raise
    except Exception as e:
        # 연결 거부 등 = Ollama 서버 미응답 → fallback 으로
        raise _OllamaUnavailable(str(e)) from e


def _ask_fallback(question: str, registry: dict) -> dict:
    """Ollama 없이 핵심 도구를 직접 실행해 근거 요약을 반환(LLM 해석은 생략)."""
    stats = registry["summarize_stats"]()
    logons = registry["analyze_logons"]()
    sec = registry["find_security_events"]()

    rng = stats["time_range"]
    lines = [
        "[자동 트리아지 — 로컬 LLM(Ollama qwen2.5) 미설치 상태]",
        f"• 총 이벤트 {stats['total']}건, 시간범위 {rng['min_kst']} ~ {rng['max_kst']}",
        f"• 로그온 성공 {logons['success_total']} / 실패 {logons['fail_total']}",
    ]
    if logons["brute_force_suspects"]:
        top = logons["brute_force_suspects"][0]
        lines.append(
            f"• ⚠ 무차별대입 의심: {top.get('account') or top.get('source_ip')} 실패 {top['fail_count']}회"
        )
    if sec["high_risk"]:
        lines.append("• 🔴 고위험: 감사 로그 삭제(1102) 정황 — 증거 인멸 가능")
    if sec["findings"]:
        cats = ", ".join(f"{f['category']}({f['count']})" for f in sec["findings"])
        lines.append(f"• 고위험 이벤트: {cats}")
    lines.append("→ Ollama + qwen2.5 설치 시 자연어 해석/추적이 활성화됩니다.")

    evidence: list = []
    _collect_evidence(registry["search_events"](limit=20), evidence)
    _collect_evidence(sec, evidence)

    return {
        "answer": "\n".join(lines),
        "tool_calls": [
            {"name": "summarize_stats", "arguments": {}},
            {"name": "analyze_logons", "arguments": {}},
            {"name": "find_security_events", "arguments": {}},
        ],
        "evidence": evidence,
        "llm": False,
    }
