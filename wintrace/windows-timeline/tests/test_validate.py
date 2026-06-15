"""Tests for engine.validate (Activity record plausibility gate)."""

from engine.validate import is_plausible_activity, TS_MIN, TS_MAX


def _good():
    # 31 serial types resembling a real Activity record
    serials = [44, 101, 13, 13, 1, 9, 0, 0, 0, 0, 4, 4, 101, 1, 8, 0, 0, 8,
               4, 4, 4, 0, 0, 0, 0, 8, 9, 8, 0, 4, 1]
    values = [b"\x00" * 16, "[{", "p", "a", 5, 1, None, None, None, None,
              1_600_000_100, 1_600_099_999, b"{}", 1, 0, None, None, 0,
              1_600_000_000, 1_600_000_050, 1_600_000_100, None, None, None,
              None, 0, 1, 0, None, 1_600_099_999, 7]
    return serials, values


def test_good_record_is_plausible():
    serials, values = _good()
    ok, signals = is_plausible_activity(serials, values)
    assert ok is True
    assert signals["col_count_ok"] is True
    assert signals["guid_serial_ok"] is True
    assert signals["ts_in_range"] is True


def test_wrong_column_count_rejected():
    serials, values = _good()
    ok, signals = is_plausible_activity(serials[:20], values[:20])
    assert ok is False
    assert signals["col_count_ok"] is False


def test_non_guid_first_column_rejected():
    serials, values = _good()
    serials[0] = 13          # text, not a 16-byte GUID blob
    values[0] = "x"
    ok, signals = is_plausible_activity(serials, values)
    assert ok is False
    assert signals["guid_serial_ok"] is False


def test_guid_serial_but_wrong_length_rejected():
    serials, values = _good()
    values[0] = b"\x00" * 8  # serial 44 promises 16 bytes; only 8 present
    ok, signals = is_plausible_activity(serials, values)
    assert signals["guid_serial_ok"] is False
    assert ok is False


def test_null_id_allowed_as_guid_serial():
    serials, values = _good()
    serials[0] = 0
    values[0] = None
    ok, signals = is_plausible_activity(serials, values)
    assert signals["guid_serial_ok"] is True


def test_timestamp_out_of_range_lowers_signal():
    serials, values = _good()
    values[10] = 5             # absurd epoch
    values[18] = 5
    values[19] = 5
    values[20] = 5
    values[29] = 5
    ok, signals = is_plausible_activity(serials, values)
    assert signals["ts_in_range"] is False


def test_ts_bounds_constants_sane():
    assert TS_MIN < TS_MAX
    assert TS_MIN >= 1_400_000_000
