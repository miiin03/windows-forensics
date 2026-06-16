"""Isolation Forest 이상탐지 + 스토어 반영. DESIGN.md §3.4, §4.4.

윈도우 피처(features.build_features) → IsolationForest 로 윈도우별 비정상 점수화 →
events.window_id / anomaly_score / is_anomaly 에 반영. anomaly_score 는 IsolationForest
score_samples 원값(낮을수록 비정상, schema 주석과 일치).
"""
from __future__ import annotations

# pandas / scikit-learn 은 무거운 선택 의존 → 모듈 top 에서 import 하지 않고 detect_anomalies
# 안에서 지연 import. 이 모듈 import 자체는 ML 스택 없이도 성공해야 pipeline/server 가 살아남는다.
# (타입 힌트의 pd.DataFrame 은 `from __future__ import annotations` 로 평가되지 않으므로 안전.)
from .features import FEATURE_COLUMNS, build_features, window_key

# IsolationForest 가 통계적으로 의미를 가지려면 최소 윈도우 수 필요.
# 이보다 적으면 학습을 건너뛰고 전부 정상 처리(소량 데모 데이터 보호).
MIN_WINDOWS = 8


def _reason(f) -> str:
    """윈도우 피처 행 → 한 줄 한국어 사유(UI 표시용)."""
    parts = []
    if int(f["n_logon_fail"]) > 0:
        parts.append(f"로그온 실패 {int(f['n_logon_fail'])}회")
    if int(f["n_log_cleared"]) > 0:
        parts.append("감사 로그 삭제(1102)")
    if int(f["n_new_account"]) > 0:
        parts.append(f"계정 생성 {int(f['n_new_account'])}건")
    if int(f["n_service"]) > 0:
        parts.append(f"서비스 설치 {int(f['n_service'])}건")
    if int(f["n_group_add"]) > 0:
        parts.append("권한 그룹 변경")
    if int(f["n_priv"]) > 0:
        parts.append(f"특수권한 부여 {int(f['n_priv'])}건")
    if int(f["n_kerb_fail"]) > 0:
        parts.append(f"Kerberos 사전인증 실패 {int(f['n_kerb_fail'])}회")
    if int(f["is_off_hours"]) == 1:
        parts.append("야간 시간대")
    if not parts:
        parts.append(f"이벤트 {int(f['n_events'])}건 (평소와 다른 패턴)")
    return ", ".join(parts)


def detect_anomalies(features: pd.DataFrame, contamination: float = 0.02) -> pd.DataFrame:
    """피처 행렬(index=window_id) → anomaly_score / is_anomaly 컬럼을 가진 DataFrame.

    윈도우 수 < MIN_WINDOWS 면 학습하지 않고 score=0.0, is_anomaly=0 으로 반환.
    """
    import pandas as pd  # 지연 import (무거운 선택 의존)
    from sklearn.ensemble import IsolationForest

    out = pd.DataFrame(index=features.index.copy())
    if len(features) < MIN_WINDOWS:
        out["anomaly_score"] = 0.0
        out["is_anomaly"] = 0
        out.attrs["fitted"] = False
        return out

    X = features[FEATURE_COLUMNS].to_numpy(dtype="float64")
    model = IsolationForest(
        n_estimators=200,
        contamination=contamination,
        random_state=42,
    )
    pred = model.fit_predict(X)              # -1 = 비정상, 1 = 정상
    scores = model.score_samples(X)          # 낮을수록 비정상
    out["anomaly_score"] = scores
    out["is_anomaly"] = (pred == -1).astype(int)
    out.attrs["fitted"] = True
    return out


def run_anomaly_detection(conn, window_minutes: int = 60, contamination: float = 0.02) -> dict:
    """전체 파이프라인: 피처 생성 → 탐지 → events 테이블에 window_id/점수 반영.

    반환:
      {"ok", "fitted", "windows", "anomaly_windows",
       "anomalies": [{window_id, start_kst, n_events, anomaly_score}], "note"?}
    """
    features = build_features(conn, window_minutes=window_minutes)
    if features.empty:
        return {"ok": False, "fitted": False, "high_risk": False, "windows": 0,
                "anomaly_windows": 0, "anomalies": [],
                "note": "분석할 이벤트가 없습니다. 먼저 EVTX 를 적재하세요."}

    scored = detect_anomalies(features, contamination=contamination)

    # 모든 이벤트에 window_id 부여 (재현적: time_utc 기반 재계산)
    rows = conn.execute("SELECT pk, time_utc FROM events").fetchall()
    win_updates = [(window_key(r["time_utc"], window_minutes), r["pk"]) for r in rows]
    conn.executemany("UPDATE events SET window_id = ? WHERE pk = ?", win_updates)

    # 윈도우 점수를 해당 윈도우의 모든 이벤트에 반영
    score_updates = [
        (float(row.anomaly_score), int(row.is_anomaly), wid)
        for wid, row in scored.iterrows()
    ]
    conn.executemany(
        "UPDATE events SET anomaly_score = ?, is_anomaly = ? WHERE window_id = ?",
        score_updates,
    )
    conn.commit()

    fitted = bool(scored.attrs.get("fitted", False))
    flagged = scored[scored["is_anomaly"] == 1].sort_values("anomaly_score")

    # 윈도우별 시작 KST(표시용) 조회
    kst_by_win = {
        r["window_id"]: r["lo"]
        for r in conn.execute(
            "SELECT window_id, MIN(time_kst) AS lo FROM events "
            "WHERE window_id IS NOT NULL GROUP BY window_id"
        ).fetchall()
    }

    anomalies = []
    high_risk = False
    for wid, row in flagged.iterrows():
        f = features.loc[wid]
        if int(f["n_log_cleared"]) > 0:
            high_risk = True
        anomalies.append({
            "window_id": wid,
            "time": kst_by_win.get(wid),                       # UI 표시용 KST
            "n_events": int(f["n_events"]),
            "anomaly_score": round(float(row.anomaly_score), 4),  # 원값(낮을수록 비정상)
            "score": round(min(1.0, max(0.0, -float(row.anomaly_score))), 2),  # UI 강도 0~1
            "reason": _reason(f),
        })

    out = {
        "ok": True,
        "fitted": fitted,
        "high_risk": high_risk,
        "windows": int(len(features)),
        "anomaly_windows": len(anomalies),
        "anomalies": anomalies,
    }
    if not fitted:
        out["note"] = (
            f"윈도우 수({len(features)})가 적어({MIN_WINDOWS}개 미만) IsolationForest 학습을 "
            "생략했습니다. 더 많은 로그를 적재하면 이상탐지가 활성화됩니다."
        )
    return out
