"""Command-line orchestration for ActivitiesCache.db timeline export."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from engine.carver.freeblock import carve_freeblocks
from engine.carver.freelist import carve_freelist
from engine.dedup import deduplicate
from engine.discovery import ActivityDbCandidate, find_activitiescache_dbs
from engine.export import build_output, write_json
from engine.live_parser import read_activity
from engine.normalize import normalize_records
from engine.pages import PageSource


_SOURCES = ("all", "live", "freelist", "freeblock")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m engine",
        description="Parse ActivitiesCache.db and export live plus carved Timeline records.",
    )
    parser.add_argument(
        "db",
        nargs="?",
        metavar="ActivitiesCache.db",
        help="SQLite ActivitiesCache.db path; omitted means auto-discover local accounts",
    )
    parser.add_argument("-o", "--output", help="output JSON path")
    parser.add_argument("--root", help="scan root for ConnectedDevicesPlatform when db is omitted")
    parser.add_argument(
        "--source",
        action="append",
        choices=_SOURCES,
        help="source to include; may repeat (default: all)",
    )
    parser.add_argument(
        "--phase",
        type=int,
        choices=(1, 2, 3),
        default=1,
        help="carving phase to run (default: 1)",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.0,
        help="drop carved records below this confidence",
    )
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON")
    parser.add_argument("--stats-only", action="store_true", help="write envelope without records")
    parser.add_argument("--no-wal", action="store_true", help="do not inspect a companion WAL file")
    return parser


def _wanted(args) -> set[str]:
    selected = args.source or ["all"]
    if "all" in selected:
        return {"live", "freelist", "freeblock"}
    return set(selected)


def _source_info(path: str, page_source: PageSource, no_wal: bool) -> dict:
    wal_path = Path(path + "-wal")
    wal_present = (not no_wal) and wal_path.exists()
    return {
        "path": path,
        "page_size": page_source.page_size,
        "freelist_count": page_source.header.freelist_count,
        "wal_present": wal_present,
        "wal_frames": 0,
        "secure_delete_suspected": False,
        "vacuum_suspected": page_source.header.freelist_count == 0 and not wal_present,
    }


def _candidate_from_path(path: str) -> ActivityDbCandidate:
    db = Path(path)
    wal = db.with_name(db.name + "-wal")
    shm = db.with_name(db.name + "-shm")
    return ActivityDbCandidate(
        db_path=str(db),
        wal_path=str(wal) if wal.exists() else None,
        shm_path=str(shm) if shm.exists() else None,
        account=db.parent.name,
    )


def _source_info_for(candidate: ActivityDbCandidate, page_source: PageSource, no_wal: bool) -> dict:
    info = _source_info(candidate.db_path, page_source, no_wal)
    info["account"] = candidate.account
    info["wal_path"] = candidate.wal_path if not no_wal else None
    info["shm_path"] = candidate.shm_path
    info["wal_present"] = bool(info["wal_path"])
    info["vacuum_suspected"] = page_source.header.freelist_count == 0 and not info["wal_present"]
    return info


def _tag_records(records, candidate: ActivityDbCandidate) -> list[dict]:
    tagged = []
    for record in records:
        item = dict(record)
        item["source_db_account"] = candidate.account
        item["source_db_path"] = candidate.db_path
        tagged.append(item)
    return tagged


def _process_candidate(candidate: ActivityDbCandidate, args) -> tuple[list[dict], list[dict], dict]:
    wanted = _wanted(args)
    page_source = PageSource.from_file(candidate.db_path)

    live_raw = read_activity(candidate.db_path, immutable=True) if "live" in wanted else []
    carved_raw = []
    if args.phase >= 1:
        if "freelist" in wanted:
            carved_raw.extend(carve_freelist(page_source))
        if "freeblock" in wanted:
            carved_raw.extend(carve_freeblocks(page_source))

    live = normalize_records(live_raw)
    carved = [
        record
        for record in normalize_records(carved_raw)
        if (record.get("confidence") or 0) >= args.min_confidence
    ]
    merged = deduplicate(live, carved)
    merged_live = [record for record in merged if record.get("source") == "live"]
    merged_carved = [record for record in merged if record.get("source") != "live"]
    return (
        _tag_records(merged_live, candidate),
        _tag_records(merged_carved, candidate),
        _source_info_for(candidate, page_source, args.no_wal),
    )


def discover_candidates(args) -> list[ActivityDbCandidate]:
    if args.db:
        return [_candidate_from_path(args.db)]
    return find_activitiescache_dbs(root=args.root)


def run(args) -> dict | None:
    candidates = discover_candidates(args)
    if not candidates:
        print(
            "No ActivitiesCache.db files found. Provide a db path or use --root/WT_CDP_DIR/LOCALAPPDATA.",
            file=sys.stderr,
        )
        return None

    all_live = []
    all_carved = []
    source_infos = []
    for candidate in candidates:
        live, carved, info = _process_candidate(candidate, args)
        all_live.extend(live)
        all_carved.extend(carved)
        source_infos.append(info)

    obj = build_output(all_live, all_carved, source_infos)
    if args.stats_only:
        obj = {k: v for k, v in obj.items() if k != "records"}
    return obj


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.output and not args.stats_only:
        parser.error("-o/--output is required unless --stats-only is used")
    obj = run(args)
    if obj is None:
        return 0
    if args.output:
        write_json(args.output, obj, pretty=args.pretty)
    else:
        kwargs = {"ensure_ascii": False}
        if args.pretty:
            kwargs.update({"indent": 2, "sort_keys": True})
        print(json.dumps(obj, **kwargs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
