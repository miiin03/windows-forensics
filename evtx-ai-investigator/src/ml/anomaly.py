"""Isolation Forest 이상탐지. DESIGN.md §3.4."""
from __future__ import annotations


def detect_anomalies(features, contamination: float = 0.02):
    """피처 행렬 → 윈도우별 anomaly_score / is_anomaly.

    sklearn.ensemble.IsolationForest 사용.
    결과는 store의 events.window_id 기준으로 anomaly_score/is_anomaly에 반영.
    """
    raise NotImplementedError("M3에서 구현")
