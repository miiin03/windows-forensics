"""EVTX 파싱 → 정규화 레코드.

python-evtx로 .evtx의 각 레코드를 읽어 공통 필드 + EventData(dict)로 정규화한다.
보안 이벤트 ID를 category로 매핑하고, 시각을 UTC/KST로 변환한다.

구현 예정(M1):
    - Evtx(path) 순회 → 레코드 XML → lxml 파싱
    - System 노드(EventID, TimeCreated, Computer, Channel, Provider, Level)
    - EventData 노드 → {Name: value} dict
    - SECURITY_EVENT_CATEGORY 매핑, account/source_ip/logon_type 추출
"""
from __future__ import annotations

# 포렌식 핵심 이벤트 ID → category 매핑 (DESIGN.md §3.1)
SECURITY_EVENT_CATEGORY: dict[int, str] = {
    4624: "logon_ok",        # 로그온 성공
    4625: "logon_fail",      # 로그온 실패
    4634: "logoff",
    4647: "logoff",
    4672: "priv",            # 특수 권한 부여(관리자)
    4688: "proc",            # 프로세스 생성
    4720: "account",         # 계정 생성
    4722: "account",         # 계정 활성화
    4724: "account",         # 비밀번호 재설정
    4728: "group_add",       # 권한 그룹 멤버 추가
    4732: "group_add",
    4756: "group_add",
    4768: "kerberos",        # TGT 요청
    4769: "kerberos",        # TGS 요청
    4771: "kerberos",        # 사전인증 실패
    4776: "ntlm",            # 자격증명 검증
    1102: "log_cleared",     # 감사 로그 삭제 (안티포렌식)
    7045: "service",         # 서비스 설치
    7034: "service",         # 서비스 비정상 종료
}


def parse_evtx(path: str) -> list[dict]:
    """단일 .evtx 파일을 정규화된 이벤트 레코드 리스트로 반환한다.

    Returns: store.schema.events 컬럼에 대응하는 dict 리스트.
    """
    raise NotImplementedError("M1에서 구현")
