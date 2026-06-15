"""Tests for engine.confidence (carved-record scoring policy)."""

from engine.confidence import score_confidence, label_for

FULL_SIGNALS = {"guid_serial_ok": True, "ts_in_range": True, "appid_text": True}


def test_label_thresholds():
    assert label_for(0.9) == "high"
    assert label_for(0.75) == "high"
    assert label_for(0.6) == "medium"
    assert label_for(0.3) == "low"
    assert label_for(0.1) == "very_low"


def test_source_ordering():
    fl, _ = score_confidence("freelist", FULL_SIGNALS, completeness=1.0)
    fb, _ = score_confidence("freeblock", FULL_SIGNALS, completeness=1.0)
    sl, _ = score_confidence("slack", FULL_SIGNALS, completeness=1.0)
    assert fl > fb > sl


def test_truncation_lowers_score():
    base, _ = score_confidence("freelist", FULL_SIGNALS, completeness=1.0)
    trunc, _ = score_confidence(
        "freelist", FULL_SIGNALS, completeness=1.0, payload_truncated=True
    )
    assert trunc < base


def test_completeness_scales_score():
    full, _ = score_confidence("freelist", FULL_SIGNALS, completeness=1.0)
    half, _ = score_confidence("freelist", FULL_SIGNALS, completeness=0.5)
    assert half < full


def test_score_clamped_to_unit_interval():
    v, lbl = score_confidence("wal", FULL_SIGNALS, completeness=1.0)
    assert 0.0 <= v <= 1.0
    assert lbl in ("high", "medium", "low", "very_low")


def test_returns_label_consistent_with_value():
    v, lbl = score_confidence("freeblock", FULL_SIGNALS, completeness=1.0)
    assert lbl == label_for(v)
