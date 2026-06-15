"""GUID-first de-duplication for normalized live and carved records."""

from __future__ import annotations

from copy import deepcopy

_META_KEYS = {
    "source",
    "sources",
    "confidence",
    "confidence_label",
    "is_deleted",
    "is_prior_version",
    "payload_truncated",
    "provenance",
    "validation_signals",
}


def _content(record: dict) -> dict:
    return {k: v for k, v in record.items() if k not in _META_KEYS}


def _non_null_count(value) -> int:
    if value is None:
        return 0
    if isinstance(value, dict):
        return sum(_non_null_count(v) for v in value.values())
    if isinstance(value, list):
        return sum(_non_null_count(v) for v in value)
    return 1


def _source_list(records) -> list:
    sources = []
    for record in records:
        for source in record.get("sources") or [record.get("source")]:
            if source is not None and source not in sources:
                sources.append(source)
    return sources


def _best(records) -> dict:
    best = max(
        records,
        key=lambda r: (
            r.get("confidence") or 0,
            _non_null_count(_content(r)),
        ),
    )
    merged = deepcopy(best)
    merged["sources"] = _source_list(records)
    return merged


def deduplicate(live_records: list[dict], carved_records: list[dict]) -> list[dict]:
    """Merge carved duplicates, drop identical live matches, tag prior versions."""
    output = [deepcopy(record) for record in live_records]
    live_by_id = {record.get("Id"): record for record in live_records if record.get("Id")}

    keyed: dict[str, list[dict]] = {}
    keyless = []
    for record in carved_records:
        key = record.get("Id")
        if key is None:
            keyless.append(deepcopy(record))
        else:
            keyed.setdefault(key, []).append(record)

    for key, records in keyed.items():
        merged = _best(records)
        live = live_by_id.get(key)
        if live is not None:
            if _content(live) == _content(merged):
                continue
            merged["is_prior_version"] = True
            merged["is_deleted"] = False
        output.append(merged)

    output.extend(keyless)
    return output
