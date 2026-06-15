"""Plausibility gate: is a decoded record actually an Activity row?

This is the heart of false-positive control for carving. Random bytes rarely
decode into 31 serial types whose first column is a 16-byte GUID blob and whose
LastModifiedTime lands in a sane epoch window. Hard gates: column count and the
GUID fingerprint. Soft signals raise confidence and must reach a quorum.
"""

from __future__ import annotations

from engine.schema import ACTIVITY_COLUMN_COUNT, column_index

# Epoch sanity window for ActivitiesCache timestamps (Unix seconds).
TS_MIN = 1_420_070_400          # 2015-01-01
TS_MAX = 1_893_456_000          # 2030-01-01

_ID = column_index("Id")                 # 0
_APPID = column_index("AppId")           # 1
_TYPE = column_index("ActivityType")     # 4
_STATUS = column_index("ActivityStatus") # 5
_LMT = column_index("LastModifiedTime")  # 10

_TS_COLUMN_INDICES = (
    column_index("LastModifiedTime"),
    column_index("StartTime"),
    column_index("EndTime"),
    column_index("LastModifiedOnClient"),
    column_index("LocalExpirationTime"),
)


def _is_text_serial(s: int) -> bool:
    return s == 0 or (s >= 13 and s % 2 == 1)


def _in_ts_window(v) -> bool:
    return isinstance(v, int) and TS_MIN <= v <= TS_MAX


def is_plausible_activity(serial_types, values, *, min_soft: int = 2):
    """Return ``(is_plausible, signals)`` for a decoded record.

    Hard gates: 31 columns and a GUID-shaped Id. Then at least ``min_soft`` of
    the soft signals (type/status small int, a sane timestamp, text AppId).
    """
    signals = {
        "col_count_ok": False,
        "guid_serial_ok": False,
        "type_small_int": False,
        "status_small_int": False,
        "ts_in_range": False,
        "appid_text": False,
    }

    signals["col_count_ok"] = len(serial_types) == ACTIVITY_COLUMN_COUNT
    if not signals["col_count_ok"]:
        return False, signals

    id_serial = serial_types[_ID]
    if id_serial == 0:
        signals["guid_serial_ok"] = True
    elif id_serial == 44:  # 16-byte BLOB
        v = values[_ID]
        signals["guid_serial_ok"] = isinstance(v, (bytes, bytearray)) and len(v) == 16

    signals["type_small_int"] = serial_types[_TYPE] in (0, 1, 2, 8, 9)
    signals["status_small_int"] = serial_types[_STATUS] in (0, 1, 8, 9)
    signals["ts_in_range"] = any(_in_ts_window(values[i]) for i in _TS_COLUMN_INDICES)
    signals["appid_text"] = _is_text_serial(serial_types[_APPID])

    soft = sum(
        (
            signals["type_small_int"],
            signals["status_small_int"],
            signals["ts_in_range"],
            signals["appid_text"],
        )
    )
    is_plausible = signals["guid_serial_ok"] and soft >= min_soft
    return is_plausible, signals
