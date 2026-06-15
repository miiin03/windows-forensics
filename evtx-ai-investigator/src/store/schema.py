"""통합 이벤트 스토어 스키마 (SQLite). DESIGN.md §7 참조."""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS events (
    pk             INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id       INTEGER,            -- 4625, 4624, 1102 ...
    channel        TEXT,               -- Security / System / Microsoft-Windows-Sysmon
    provider       TEXT,
    level          TEXT,               -- Information / Warning / Error
    computer       TEXT,
    time_utc       TEXT,               -- 원본 UTC ISO-8601
    time_kst       TEXT,               -- KST(UTC+9) ISO-8601
    category       TEXT,               -- logon_fail / logon_ok / priv / proc / account / service / log_cleared ...
    account        TEXT,               -- 대상/주체 계정 (TargetUserName 등)
    source_ip      TEXT,               -- IpAddress (있으면)
    logon_type     INTEGER,            -- 2/3/10 ... (해당 시)
    event_data     TEXT,               -- EventData 전체 (JSON 문자열, 감사용)
    window_id      TEXT,               -- 소속 시간 윈도우 키 (ML)
    anomaly_score  REAL,               -- IsolationForest 점수 (낮을수록 비정상)
    is_anomaly     INTEGER             -- 0/1
);
CREATE INDEX IF NOT EXISTS idx_time ON events(time_utc);
CREATE INDEX IF NOT EXISTS idx_evid ON events(event_id);
CREATE INDEX IF NOT EXISTS idx_acct ON events(account);
CREATE INDEX IF NOT EXISTS idx_anom ON events(is_anomaly);
"""
