"""Page access over the raw database file, with an optional WAL overlay.

ActivitiesCache.db files are small (tens of MB), so we read the whole image
into memory. ``get_page`` is the single choke point deciding whether callers
see the committed on-disk version of a page or its latest WAL version.
"""

from __future__ import annotations

from engine.sqlite_format import DBHeader, parse_db_header


class PageSource:
    def __init__(self, data: bytes, header: DBHeader, wal_overlay: dict | None = None):
        self.data = data
        self.header = header
        self.page_size = header.page_size
        self.usable_size = header.usable_size
        self.wal_overlay = wal_overlay or {}
        self.page_count = len(data) // self.page_size

    @classmethod
    def from_file(cls, path: str, wal_overlay: dict | None = None) -> "PageSource":
        with open(path, "rb") as f:
            data = f.read()
        header = parse_db_header(data[:100])
        return cls(data, header, wal_overlay)

    def get_page(self, page_no: int, use_wal: bool = False) -> bytes:
        """Return the bytes of page ``page_no`` (1-based)."""
        if use_wal and page_no in self.wal_overlay:
            return self.wal_overlay[page_no]
        off = (page_no - 1) * self.page_size
        return self.data[off : off + self.page_size]
