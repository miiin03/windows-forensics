"""Recover Activity records from freeblocks inside allocated SQLite pages."""

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


def _freelist_pages(page_source) -> set[int]:
    trunk_pages, leaf_pages = freelist_page_numbers(page_source)
    return trunk_pages | leaf_pages


def _scan_block(page_source, page_no: int, page: bytes, start: int, size: int, encoding, cells, seen):
    end = start + size
    if size < 4 or end > min(len(page), page_source.usable_size):
        return

    for off in range(start + 4, end):
        cell = carve_record_fragment(
            page,
            off,
            end,
            "freeblock",
            page_no,
            (page_no - 1) * page_source.page_size,
            encoding,
        )
        _append_unique(cells, seen, cell)


def _scan_page_freeblocks(page_source, page_no: int, page: bytes, encoding, cells, seen):
    try:
        header = parse_page_header(page, page_no, page_source.page_size)
    except (IndexError, ValueError):
        return
    if header.page_type != LEAF_TABLE:
        return

    block_off = header.first_freeblock
    visited = set()
    while block_off:
        if block_off in visited or block_off + 4 > page_source.usable_size:
            break
        visited.add(block_off)

        next_block = int.from_bytes(page[block_off : block_off + 2], "big")
        size = int.from_bytes(page[block_off + 2 : block_off + 4], "big")
        _scan_block(page_source, page_no, page, block_off, size, encoding, cells, seen)

        if next_block == 0 or next_block <= block_off or next_block >= page_source.usable_size:
            break
        block_off = next_block


def carve_freeblocks(page_source, encoding: str | None = None):
    """Carve Activity-shaped fragments from allocated leaf-page freeblocks."""
    encoding = encoding or page_source.header.encoding_name
    excluded_pages = _freelist_pages(page_source)
    cells = []
    seen = set()

    for page_no in range(1, page_source.page_count + 1):
        if page_no in excluded_pages:
            continue
        page = page_source.get_page(page_no)
        if not page or page[0] != LEAF_TABLE:
            continue
        _scan_page_freeblocks(page_source, page_no, page, encoding, cells, seen)

    return cells
