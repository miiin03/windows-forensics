"""Qwen2.5 tool-calling 루프 (로컬 Ollama). DESIGN.md §3.5, §9.

흐름: 자연어 질의 → Ollama(qwen2.5) → tool_call → TOOL_REGISTRY 실행 →
      결과를 모델에 되돌림 → 최종 자연어 답변.

안정화(§9): JSON 출력 강제, 도구 호출 실패 시 재시도, 단순 스키마.
"""
from __future__ import annotations

from .tools import TOOL_REGISTRY

MODEL = "qwen2.5:7b"   # 품질 옵션: "qwen2.5:14b"

SYSTEM_PROMPT = (
    "당신은 윈도우 이벤트 로그를 분석하는 포렌식 조사관입니다. "
    "사용자 질문에 답하기 위해 제공된 도구를 호출해 실제 로그 데이터를 확인하고, "
    "근거(이벤트 ID·시각·횟수)를 들어 한국어로 설명하세요. 추측하지 말고 도구 결과만 사용하세요."
)


def ask(question: str) -> dict:
    """자연어 질의 → {answer, tool_calls, evidence} 반환.

    구현 예정(M4):
        - ollama.chat(model=MODEL, messages=..., tools=<TOOL_REGISTRY 스펙>)
        - response.tool_calls 순회 → 도구 실행 → tool 메시지로 되돌림
        - stop 시 최종 answer 반환 (호출 도구·근거 레코드 동봉)
    """
    raise NotImplementedError("M4에서 구현")
