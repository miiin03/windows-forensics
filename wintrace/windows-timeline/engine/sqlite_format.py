"""SQLite file-format structures: database header + B-tree page header.

Reference: https://www.sqlite.org/fileformat2.html
All multi-byte integers in these headers are big-endian.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"SQLite format 3\x00"

# B-tree page types (first byte of a page header).
INTERIOR_INDEX = 0x02
INTERIOR_TABLE = 0x05
LEAF_INDEX = 0x0A
LEAF_TABLE = 0x0D

_LEAF_TYPES = (LEAF_TABLE, LEAF_INDEX)
_INTERIOR_TYPES = (INTERIOR_TABLE, INTERIOR_INDEX)

_ENCODINGS = {1: "UTF-8", 2: "UTF-16le", 3: "UTF-16be"}


@dataclass(frozen=True)
class DBHeader:
    page_size: int
    reserved: int
    write_format: int
    read_format: int
    file_change_counter: int
    db_size_pages: int
    first_freelist_trunk: int
    freelist_count: int
    schema_cookie: int
    text_encoding: int
    version_valid_for: int
    sqlite_version: int

    @property
    def usable_size(self) -> int:
        """Bytes of each page usable for content (page minus reserved tail)."""
        return self.page_size - self.reserved

    @property
    def encoding_name(self) -> str:
        return _ENCODINGS.get(self.text_encoding, f"unknown({self.text_encoding})")

    @property
    def db_size_trustworthy(self) -> bool:
        """The in-header page count is valid only when the change counter
        matches version-valid-for; otherwise fall back to file size."""
        return self.file_change_counter == self.version_valid_for


def parse_db_header(first100: bytes) -> DBHeader:
    """Parse the 100-byte database header. Raises ``ValueError`` on bad magic."""
    if first100[:16] != MAGIC:
        raise ValueError(f"not a SQLite database (bad magic: {first100[:16]!r})")

    raw_page_size = struct.unpack(">H", first100[16:18])[0]
    page_size = 65536 if raw_page_size == 1 else raw_page_size

    return DBHeader(
        page_size=page_size,
        write_format=first100[18],
        read_format=first100[19],
        reserved=first100[20],
        file_change_counter=struct.unpack(">I", first100[24:28])[0],
        db_size_pages=struct.unpack(">I", first100[28:32])[0],
        first_freelist_trunk=struct.unpack(">I", first100[32:36])[0],
        freelist_count=struct.unpack(">I", first100[36:40])[0],
        schema_cookie=struct.unpack(">I", first100[40:44])[0],
        text_encoding=struct.unpack(">I", first100[56:60])[0],
        version_valid_for=struct.unpack(">I", first100[92:96])[0],
        sqlite_version=struct.unpack(">I", first100[96:100])[0],
    )


@dataclass(frozen=True)
class PageHeader:
    page_type: int
    first_freeblock: int
    num_cells: int
    cell_content_start: int  # 0 in the raw header is resolved here to 65536
    num_frag_free: int
    right_most_pointer: int | None  # interior pages only
    header_len: int  # 8 (leaf) or 12 (interior)
    cell_ptr_array_offset: int  # absolute offset within the page

    @property
    def is_leaf(self) -> bool:
        return self.page_type in _LEAF_TYPES

    @property
    def is_table(self) -> bool:
        return self.page_type in (LEAF_TABLE, INTERIOR_TABLE)


def parse_page_header(page: bytes, page_no: int, page_size: int) -> PageHeader:
    """Parse the B-tree header of ``page`` (the full page bytes).

    Page 1 carries the 100-byte database header, so its B-tree header begins
    at byte 100; every other page's header begins at byte 0.
    """
    start = 100 if page_no == 1 else 0
    page_type = page[start]
    first_freeblock, num_cells, content_start, num_frag = struct.unpack(
        ">HHHB", page[start + 1 : start + 8]
    )
    cell_content_start = 65536 if content_start == 0 else content_start

    if page_type in _INTERIOR_TYPES:
        header_len = 12
        right_most = struct.unpack(">I", page[start + 8 : start + 12])[0]
    else:
        header_len = 8
        right_most = None

    return PageHeader(
        page_type=page_type,
        first_freeblock=first_freeblock,
        num_cells=num_cells,
        cell_content_start=cell_content_start,
        num_frag_free=num_frag,
        right_most_pointer=right_most,
        header_len=header_len,
        cell_ptr_array_offset=start + header_len,
    )
