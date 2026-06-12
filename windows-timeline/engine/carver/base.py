"""Turn a candidate byte offset into a validated CarvedCell, or reject it.

Shared by every carving source. The plausibility gate (engine.validate) is what
keeps random bytes from masquerading as recovered records.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.record import try_read_varint, try_decode_record, local_payload_size
from engine.schema import ACTIVITY_COLUMN_COUNT
from engine.validate import is_plausible_activity
from engine.confidence import score_confidence


@dataclass
class CarvedCell:
    source: str
    table: str
    page_no: int
    cell_offset: int
    rowid: int | None
    serial_types: list
    values: list
    payload_truncated: bool
    signals: dict
    confidence: float
    confidence_label: str
    byte_range: tuple
    decode_errors: list = field(default_factory=list)


def _completeness(values) -> float:
    return sum(1 for v in values if v is not None) / ACTIVITY_COLUMN_COUNT


def _build(source, page_no, off, rowid, view, truncated, abs_base) -> CarvedCell | None:
    plausible, signals = is_plausible_activity(view.serial_types, view.values)
    if not plausible:
        return None
    conf, label = score_confidence(
        source, signals, _completeness(view.values), payload_truncated=truncated
    )
    return CarvedCell(
        source=source,
        table="Activity",
        page_no=page_no,
        cell_offset=off,
        rowid=rowid,
        serial_types=view.serial_types,
        values=view.values,
        payload_truncated=truncated,
        signals=signals,
        confidence=conf,
        confidence_label=label,
        byte_range=(abs_base + off, abs_base + view.body_end),
    )


def carve_full_cell(
    page: bytes,
    off: int,
    usable: int,
    source: str,
    page_no: int,
    abs_base: int,
    encoding: str = "utf-8",
) -> CarvedCell | None:
    """Decode a full table-leaf cell (payload_len + rowid + record) at ``off``."""
    pv = try_read_varint(page, off, len(page))
    if pv is None:
        return None
    payload_len, p1 = pv
    if payload_len < 2:
        return None
    rv = try_read_varint(page, p1, len(page))
    if rv is None:
        return None
    rowid, rec_start = rv

    local_len, has_overflow = local_payload_size(payload_len, usable)
    view = try_decode_record(page, rec_start, rec_start + local_len, encoding)
    if view is None:
        return None
    truncated = view.truncated or has_overflow
    return _build(source, page_no, off, rowid, view, truncated, abs_base)


def carve_record_fragment(
    page: bytes,
    off: int,
    end: int,
    source: str,
    page_no: int,
    abs_base: int,
    encoding: str = "utf-8",
) -> CarvedCell | None:
    """Decode a record header directly (no cell prefix) — for freeblock/slack
    fragments where the payload_len/rowid varints were overwritten."""
    view = try_decode_record(page, off, end, encoding)
    if view is None:
        return None
    return _build(source, page_no, off, None, view, view.truncated, abs_base)
