"""Recover Activity record fragments from SQLite page slack space.

The slack region is the unallocated gap between the end of the cell pointer
array and ``cell_content_start`` within each allocated table-leaf page. After
SQLite defragments a page, this gap grows and retains bytes from previously
stored cells; those bytes are scanned here with carve_record_fragment.

Freeblock areas (within the cell-content zone, handled by freeblock.py) and
freelist pages (handled by freelist.py) are kept separate — the slack gap is
strictly BEFORE cell_content_start, so there is no byte-range overlap.
"""

from __future__ import annotations

from engine.carver.base import carve_record_fragment
from engine.carver.freelist import freelist_page_numbers
from engine.sqlite_format import LEAF_TABLE, parse_page_header


def _append_unique(cells, seen, cell):
    if cell is None:
        return
    key = (cell.source, cell.page_no, cell.cell_offset, cell.byte_range)
    if key in seen:
        return
    seen.add(key)
    cells.append(cell)


def _scan_page_slack(page_source, page_no: int, page: bytes, encoding: str, cells, seen):
    try:
        header = parse_page_header(page, page_no, page_source.page_size)
    except (IndexError, ValueError):
        return

    if header.page_type != LEAF_TABLE:
        return

    ptr_end = header.cell_ptr_array_offset + header.num_cells * 2
    # cell_content_start is already resolved to 65536 when the raw value is 0,
    # so clamp to usable_size before using it as a bound.
    content_start = min(header.cell_content_start, page_source.usable_size)

    if content_start <= ptr_end:
        return

    abs_base = (page_no - 1) * page_source.page_size
    for off in range(ptr_end, content_start):
        cell = carve_record_fragment(
            page,
            off,
            content_start,
            "slack",
            page_no,
            abs_base,
            encoding,
        )
        _append_unique(cells, seen, cell)


def carve_slack(page_source, encoding: str | None = None):
    """Carve Activity record fragments from the slack gap of allocated leaf pages."""
    encoding = encoding or page_source.header.encoding_name
    trunk_pages, leaf_pages = freelist_page_numbers(page_source)
    excluded = trunk_pages | leaf_pages
    cells = []
    seen = set()

    for page_no in range(1, page_source.page_count + 1):
        if page_no in excluded:
            continue
        page = page_source.get_page(page_no)
        # page[0] is the B-tree type for all pages except page 1 (which starts with
        # SQLite magic). Page 1 is always the schema table, never an Activity leaf.
        if not page or page[0] != LEAF_TABLE:
            continue
        _scan_page_slack(page_source, page_no, page, encoding, cells, seen)

    return cells
