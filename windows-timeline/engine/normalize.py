"""Normalize live and carved Activity records into JSON-ready dictionaries."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from engine.carver.base import CarvedCell
from engine.live_parser import LiveRecord
from engine.schema import (
    ACTIVITY_COLUMN_NAMES,
    ACTIVITY_TYPE_LABELS,
    DATETIME_COLUMNS,
    JSON_BLOB_COLUMNS,
)


def _guid_hex(value):
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


def _timestamp(value):
    if value is None:
        return None
    try:
        epoch = int(value)
    except (TypeError, ValueError):
        return None
    iso = datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")
    return {"epoch": epoch, "iso8601": iso}


def _to_text(value):
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _json_blob(value):
    if value is None:
        return {"parsed": None, "parse_ok": False, "raw_len": 0, "raw": None}
    raw_len = len(value) if isinstance(value, (bytes, bytearray)) else len(str(value))
    text = _to_text(value)
    try:
        parsed = json.loads(text)
        return {"parsed": parsed, "parse_ok": True, "raw_len": raw_len}
    except (TypeError, json.JSONDecodeError):
        return {"parsed": None, "parse_ok": False, "raw_len": raw_len, "raw": text}


def _app_name(appid):
    text = _to_text(appid)
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(parsed, list) and parsed:
        first = parsed[0]
        if isinstance(first, dict):
            return first.get("application") or first.get("app") or text
    if isinstance(parsed, dict):
        return parsed.get("application") or parsed.get("app") or text
    return text


def _values_from_record(record) -> dict:
    if isinstance(record, LiveRecord):
        return dict(record.values)
    if isinstance(record, CarvedCell):
        return {
            name: record.values[i] if i < len(record.values) else None
            for i, name in enumerate(ACTIVITY_COLUMN_NAMES)
        }
    raise TypeError(f"unsupported record type: {type(record)!r}")


def _base(record):
    if isinstance(record, LiveRecord):
        return {
            "table": record.table,
            "source": record.source,
            "sources": list(record.sources),
            "is_deleted": False,
            "is_prior_version": False,
            "payload_truncated": False,
            "confidence": 1.0,
            "confidence_label": "high",
            "validation_signals": {},
            "provenance": {"rowid": record.rowid},
        }
    if isinstance(record, CarvedCell):
        return {
            "table": record.table,
            "source": record.source,
            "sources": [record.source],
            "is_deleted": record.source != "live",
            "is_prior_version": False,
            "payload_truncated": record.payload_truncated,
            "confidence": record.confidence,
            "confidence_label": record.confidence_label,
            "validation_signals": dict(record.signals),
            "provenance": {
                "page_no": record.page_no,
                "cell_offset": record.cell_offset,
                "rowid": record.rowid,
                "byte_range": list(record.byte_range),
                "serial_types": list(record.serial_types),
                "decode_errors": list(record.decode_errors),
            },
        }
    raise TypeError(f"unsupported record type: {type(record)!r}")


def normalize_record(record) -> dict:
    """Return a JSON-ready normalized Activity record."""
    values = _values_from_record(record)
    out = _base(record)

    out["Id"] = _guid_hex(values.get("Id"))
    appid = values.get("AppId")
    out["AppId_raw"] = _to_text(appid)
    out["app_name"] = _app_name(appid)

    activity_type = values.get("ActivityType")
    out["ActivityType"] = activity_type
    out["activity_type_label"] = ACTIVITY_TYPE_LABELS.get(activity_type)

    out["timestamps"] = {
        name: normalized
        for name in sorted(DATETIME_COLUMNS)
        if (normalized := _timestamp(values.get(name))) is not None
    }

    for name in JSON_BLOB_COLUMNS:
        out[name] = _json_blob(values.get(name))

    special = {"Id", "AppId", "ActivityType", *DATETIME_COLUMNS, *JSON_BLOB_COLUMNS}
    out["other_columns"] = {
        name: _guid_hex(value) if isinstance(value, bytes) else value
        for name, value in values.items()
        if name not in special
    }
    return out


def normalize_records(records) -> list[dict]:
    return [normalize_record(record) for record in records]
