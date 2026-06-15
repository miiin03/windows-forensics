"""Recover Activity records from SQLite freelist pages."""

from __future__ import annotations

from engine.carver.base import carve_full_cell
from engine.sqlite_format import LEAF_TABLE, parse_page_header


def _valid_page_no(page_source, page_no: int) -> bool:
    return 1 <= page_no <= page_source.page_count


def _append_unique(cells, seen, cell):
    if cell is None:
        return
    key = (cell.source, cell.page_no, cell.cell_offset, cell.byte_range)
    if key in seen:
        return
    seen.add(key)
    cells.append(cell)


def freelist_page_numbers(page_source):
    """Return ``(trunk_pages, leaf_pages)`` reachable from the DB header.

    The walk is deliberately defensive: corrupt page numbers and trunk cycles
    stop traversal instead of raising from the carver.
    """
    trunk_pages: set[int] = set()
    leaf_pages: set[int] = set()
    page_no = page_source.header.first_freelist_trunk

    while page_no:
        if page_no in trunk_pages or not _valid_page_no(page_source, page_no):
            break
        trunk_pages.add(page_no)
        page = page_source.get_page(page_no)
        if len(page) < 8:
            break

        next_trunk = int.from_bytes(page[0:4], "big")
        nleaf = int.from_bytes(page[4:8], "big")
        max_leaf_entries = max(0, (page_source.usable_size - 8) // 4)
        for i in range(min(nleaf, max_leaf_entries)):
            off = 8 + (i * 4)
            leaf_no = int.from_bytes(page[off : off + 4], "big")
            if _valid_page_no(page_source, leaf_no):
                leaf_pages.add(leaf_no)

        page_no = next_trunk

    return trunk_pages, leaf_pages


def _carve_leaf_page(page_source, page_no: int, page: bytes, encoding: str, cells, seen):
    try:
        header = parse_page_header(page, page_no, page_source.page_size)
    except (IndexError, ValueError):
        _brute_scan_page(page_source, page_no, page, encoding, cells, seen)
        return

    ptr_base = header.cell_ptr_array_offset
    for i in range(header.num_cells):
        ptr_off = ptr_base + (i * 2)
        if ptr_off + 2 > page_source.usable_size:
            break
        cell_off = int.from_bytes(page[ptr_off : ptr_off + 2], "big")
        if not 0 <= cell_off < page_source.usable_size:
            continue
        cell = carve_full_cell(
            page,
            cell_off,
            page_source.usable_size,
            "freelist",
            page_no,
            (page_no - 1) * page_source.page_size,
            encoding,
        )
        _append_unique(cells, seen, cell)


def _brute_scan_page(page_source, page_no: int, page: bytes, encoding: str, cells, seen):
    usable = min(page_source.usable_size, len(page))
    for off in range(usable):
        cell = carve_full_cell(
            page,
            off,
            page_source.usable_size,
            "freelist_brute",
            page_no,
            (page_no - 1) * page_source.page_size,
            encoding,
        )
        _append_unique(cells, seen, cell)


def carve_freelist(page_source, encoding: str | None = None):
    """Carve Activity-shaped records from freelist leaf pages."""
    encoding = encoding or page_source.header.encoding_name
    _, leaf_pages = freelist_page_numbers(page_source)
    cells = []
    seen = set()

    for page_no in sorted(leaf_pages):
        page = page_source.get_page(page_no)
        if not page:
            continue
        if page[0] == LEAF_TABLE:
            _carve_leaf_page(page_source, page_no, page, encoding, cells, seen)
        else:
            _brute_scan_page(page_source, page_no, page, encoding, cells, seen)

    return cells
