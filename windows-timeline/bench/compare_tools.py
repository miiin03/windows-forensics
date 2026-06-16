"""Cross-check our live parse against a free reference tool's output.

WxTCmd (Eric Zimmerman) is the de-facto free Windows Timeline parser; it emits a
CSV of live Activity rows. compare_live_with_wxtcmd_csv() compares the set of
Activity GUIDs we recover live against the set WxTCmd reports, so divergence
(rows we miss, or rows we invent) is quantified rather than asserted.

Carving cross-checks (FQLite / undark on freed pages) are run manually — see
docs/benchmark/대조실험-가이드.md — because those tools need a GUI / separate
build and can't be driven deterministically from a unit test.
"""

from __future__ import annotations

import csv
import re

from engine.live_parser import read_activity

# 32 hex chars with optional dashes/braces (e.g. {GUID} or 8-4-4-4-12 form).
_HEX_ONLY = re.compile(r"[^0-9a-f]")
_GUID_RE = re.compile(r"^[0-9a-f]{32}$")


def _norm(value) -> str | None:
    """Reduce any GUID rendering (dashed, braced, raw hex) to bare lowercase hex."""
    if value is None:
        return None
    if isinstance(value, bytes):
        h = value.hex()
    else:
        h = _HEX_ONLY.sub("", str(value).strip().lower())
    return h if _GUID_RE.match(h) else None


def _our_guids(db_path: str) -> set[str]:
    guids = set()
    for record in read_activity(db_path):
        norm = _norm(record.values.get("Id"))
        if norm:
            guids.add(norm)
    return guids


def _detect_id_column(header: list[str], rows: list[list[str]]) -> int | None:
    """Find the GUID column: an exact 'Id' header wins; else the column whose
    values most look like GUIDs."""
    for i, name in enumerate(header):
        if name.strip().lower() == "id":
            return i

    best_idx, best_hits = None, 0
    for i in range(len(header)):
        hits = sum(1 for row in rows if i < len(row) and _norm(row[i]))
        if hits > best_hits:
            best_idx, best_hits = i, hits
    return best_idx if best_hits else None


def _wxtcmd_guids(csv_path: str) -> set[str]:
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        rows = list(reader)
    if not rows:
        return set()
    header, body = rows[0], rows[1:]
    idx = _detect_id_column(header, body)
    if idx is None:
        return set()
    guids = set()
    for row in body:
        if idx < len(row):
            norm = _norm(row[idx])
            if norm:
                guids.add(norm)
    return guids


def compare_live_with_wxtcmd_csv(db_path: str, csv_path: str) -> dict:
    """Compare our live Activity GUID set vs a WxTCmd CSV's GUID set.

    Returns {ours_count, wxtcmd_count, match, only_ours, only_wxtcmd}.
    ``match`` is True only when the two sets are identical.
    """
    ours = _our_guids(db_path)
    theirs = _wxtcmd_guids(csv_path)
    return {
        "ours_count": len(ours),
        "wxtcmd_count": len(theirs),
        "match": ours == theirs,
        "only_ours": sorted(ours - theirs),
        "only_wxtcmd": sorted(theirs - ours),
    }
