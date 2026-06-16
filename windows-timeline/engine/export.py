"""Build and write the integrated Timeline JSON envelope."""

from __future__ import annotations

import json
from pathlib import Path


def _source_counts(records) -> dict:
    counts = {}
    for record in records:
        source = record.get("source")
        if source is None:
            continue
        counts[source] = counts.get(source, 0) + 1
    return dict(sorted(counts.items()))


def _source_file(info: dict) -> dict:
    return {
        "path": info.get("path"),
        "account": info.get("account"),
        "page_size": info.get("page_size"),
        "freelist_count": info.get("freelist_count", 0),
        "wal_present": info.get("wal_present", False),
        "wal_path": info.get("wal_path"),
        "shm_path": info.get("shm_path"),
        "wal_frames": info.get("wal_frames", 0),
        "secure_delete_suspected": info.get("secure_delete_suspected", False),
        "vacuum_suspected": info.get("vacuum_suspected", False),
    }


def build_output(
    live: list[dict],
    carved: list[dict],
    source_file_info: dict | list[dict],
    *,
    evidence: list[dict] | None = None,
) -> dict:
    records = list(live) + list(carved)
    infos = source_file_info if isinstance(source_file_info, list) else [source_file_info]
    source_files = [_source_file(info) for info in infos]
    obj = {
        "schema_version": 1,
        "tool": "windows-timeline",
        "source_file": source_files[0] if source_files else {},
        "source_files": source_files,
        "evidence": evidence or [],
        "stats": {
            "live": len(live),
            "carved_total": len(carved),
            "by_source": _source_counts(records),
            "deleted_recovered": sum(
                1
                for r in records
                if r.get("is_deleted") and not r.get("is_prior_version")
            ),
            "prior_versions": sum(1 for r in records if r.get("is_prior_version")),
        },
        "records": records,
    }
    return obj


def write_json(path, obj: dict, pretty: bool = False) -> None:
    target = Path(path)
    kwargs = {"ensure_ascii": False}
    if pretty:
        kwargs.update({"indent": 2, "sort_keys": True})
    target.write_text(json.dumps(obj, **kwargs) + "\n", encoding="utf-8")
