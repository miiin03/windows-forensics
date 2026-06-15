"""Confidence scoring for recovered records — a single place to tune policy.

score = base(source) x completeness x validation_bonus, then penalties.
"""

from __future__ import annotations

_BASE = {
    "live": 1.00,
    "wal": 0.92,
    "freelist": 0.85,        # whole stale leaf page, full cell
    "freelist_brute": 0.70,  # cell recovered by scanning a freed page
    "freeblock": 0.55,       # first 4 bytes clobbered by the freeblock header
    "wal_stale": 0.40,       # frame from a previous WAL generation
    "slack": 0.30,           # fragment from compacted cell-content slack
}

_STRONG_SIGNALS = ("guid_serial_ok", "ts_in_range", "appid_text")


def label_for(value: float) -> str:
    if value >= 0.75:
        return "high"
    if value >= 0.5:
        return "medium"
    if value >= 0.25:
        return "low"
    return "very_low"


def score_confidence(
    source: str,
    signals: dict,
    completeness: float,
    *,
    payload_truncated: bool = False,
    checksum_ok: bool = True,
) -> tuple[float, str]:
    """Return ``(confidence, label)`` in [0, 1]."""
    base = _BASE.get(source, 0.30)
    strong = sum(1 for k in _STRONG_SIGNALS if signals.get(k))
    bonus = 1.0 + 0.05 * strong

    value = base * completeness * bonus
    if payload_truncated:
        value *= 0.8
    if not checksum_ok:
        value *= 0.85

    value = max(0.0, min(1.0, value))
    return round(value, 3), label_for(value)
