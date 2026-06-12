"""피처 엔지니어링: 시간 윈도우/계정 단위 집계. DESIGN.md §3.3."""
from __future__ import annotations


def build_features(conn, window_minutes: int = 60):
    """events 테이블 → 윈도우별 피처 행렬(DataFrame) 생성.

    피처(예):
        - logon_fail_count(4625), fail_success_ratio
        - distinct_source_ip, logon_type 분포
        - hour, is_off_hours, is_weekend
        - priv_logon(4672), new_account(4720), service_install(7045)
        - log_cleared(1102) 플래그
    """
    raise NotImplementedError("M3에서 구현")
