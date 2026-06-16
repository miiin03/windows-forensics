"""Tests for common live/carved record normalization."""

import json

from engine.carver.base import CarvedCell
from engine.live_parser import LiveRecord
from engine.normalize import _timestamp, normalize_record
from engine.schema import ACTIVITY_COLUMN_NAMES, column_index


GUID = bytes.fromhex("00112233445566778899aabbccddeeff")


def _activity_dict():
    values = {name: None for name in ACTIVITY_COLUMN_NAMES}
    values.update(
        {
            "Id": GUID,
            "AppId": json.dumps(
                [{"application": "Calculator.exe", "platform": "windows_win32"}]
            ),
            "ActivityType": 5,
            "LastModifiedTime": 1_600_000_100,
            "Payload": b'{"displayText":"hello","activeDurationSeconds":9}',
            "ClipboardPayload": b"not json",
            "ETag": 7,
        }
    )
    return values


def _activity_list():
    values = [None] * len(ACTIVITY_COLUMN_NAMES)
    for name, value in _activity_dict().items():
        values[column_index(name)] = value
    return values


def test_normalize_live_record_converts_core_activity_fields():
    record = LiveRecord(table="Activity", rowid=42, values=_activity_dict())

    normalized = normalize_record(record)

    assert normalized["table"] == "Activity"
    assert normalized["source"] == "live"
    assert normalized["sources"] == ["live"]
    assert normalized["is_deleted"] is False
    assert normalized["confidence"] == 1.0
    assert normalized["Id"] == "00112233445566778899aabbccddeeff"
    assert normalized["app_name"] == "Calculator.exe"
    assert normalized["ActivityType"] == 5
    assert normalized["activity_type_label"] == "Open app / foreground (UserEngaged)"
    assert normalized["timestamps"]["LastModifiedTime"] == {
        "epoch": 1_600_000_100,
        "iso8601": "2020-09-13T12:28:20Z",
    }
    assert normalized["Payload"]["parse_ok"] is True
    assert normalized["Payload"]["parsed"]["displayText"] == "hello"
    assert normalized["ClipboardPayload"]["parse_ok"] is False
    assert normalized["provenance"] == {"rowid": 42}


def test_normalize_carved_cell_maps_column_indexes_and_preserves_provenance():
    cell = CarvedCell(
        source="freeblock",
        table="Activity",
        page_no=9,
        cell_offset=256,
        rowid=None,
        serial_types=[0] * len(ACTIVITY_COLUMN_NAMES),
        values=_activity_list(),
        payload_truncated=True,
        signals={"guid_serial_ok": True},
        confidence=0.55,
        confidence_label="medium",
        byte_range=(33024, 33120),
        decode_errors=["tail truncated"],
    )

    normalized = normalize_record(cell)

    assert normalized["source"] == "freeblock"
    assert normalized["sources"] == ["freeblock"]
    assert normalized["is_deleted"] is True
    assert normalized["payload_truncated"] is True
    assert normalized["confidence"] == 0.55
    assert normalized["validation_signals"] == {"guid_serial_ok": True}
    assert normalized["Id"] == "00112233445566778899aabbccddeeff"
    assert normalized["provenance"] == {
        "page_no": 9,
        "cell_offset": 256,
        "rowid": None,
        "byte_range": [33024, 33120],
        "serial_types": [0] * len(ACTIVITY_COLUMN_NAMES),
        "decode_errors": ["tail truncated"],
    }


# --- Windows-safe timestamp conversion (no datetime.fromtimestamp OS call) ----
# fromtimestamp raises OSError(Errno 22) on Windows for negative / out-of-range
# epochs; carved garbage routinely produces those. Conversion must never raise.

def test_timestamp_epoch_zero():
    assert _timestamp(0) == {"epoch": 0, "iso8601": "1970-01-01T00:00:00Z"}


def test_timestamp_negative_epoch_no_raise():
    ts = _timestamp(-1)
    assert ts["epoch"] == -1
    assert ts["iso8601"] == "1969-12-31T23:59:59Z"


def test_timestamp_out_of_range_keeps_epoch_iso_none():
    # ~3.17 million years: timedelta overflows datetime. Preserve epoch, iso=None.
    ts = _timestamp(99999999999999)
    assert ts == {"epoch": 99999999999999, "iso8601": None}


def test_timestamp_negative_out_of_range_keeps_epoch_iso_none():
    ts = _timestamp(-99999999999999)
    assert ts == {"epoch": -99999999999999, "iso8601": None}
