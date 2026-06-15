"""Recover Activity records from prior-version frames in SQLite WAL (-wal) files."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from engine.carver.base import carve_full_cell
from engine.sqlite_format import LEAF_TABLE

WAL_MAGIC_LE = 0x377F0682
WAL_MAGIC_BE = 0x377F0683
WAL_HEADER_SIZE = 32
FRAME_HEADER_SIZE = 24


@dataclass
class WalHeader:
    magic: int
    format_version: int
    page_size: int
    checkpoint_seq: int
    salt1: int
    salt2: int
    checksum1: int
    checksum2: int

    @property
    def is_big_endian(self) -> bool:
        return self.magic == WAL_MAGIC_BE


@dataclass
class WalFrame:
    index: int
    page_no: int
    commit_size: int
    salt1: int
    salt2: int
    data: bytes
    salt_match: bool

    @property
    def is_commit(self) -> bool:
        return self.commit_size != 0


def parse_wal_header(data: bytes) -> WalHeader | None:
    if len(data) < WAL_HEADER_SIZE:
        return None
    magic = struct.unpack(">I", data[0:4])[0]
    if magic not in (WAL_MAGIC_LE, WAL_MAGIC_BE):
        return None
    fmt, page_size, ckpt_seq = struct.unpack(">III", data[4:16])
    salt1, salt2, ck1, ck2 = struct.unpack(">IIII", data[16:32])
    return WalHeader(
        magic=magic,
        format_version=fmt,
        page_size=page_size,
        checkpoint_seq=ckpt_seq,
        salt1=salt1,
        salt2=salt2,
        checksum1=ck1,
        checksum2=ck2,
    )


def read_wal_frames(data: bytes, wal_header: WalHeader) -> list[WalFrame]:
    page_size = wal_header.page_size
    frame_size = FRAME_HEADER_SIZE + page_size
    offset = WAL_HEADER_SIZE
    frames = []
    idx = 0
    while offset + frame_size <= len(data):
        fh = data[offset : offset + FRAME_HEADER_SIZE]
        page_no = struct.unpack(">I", fh[0:4])[0]
        commit_size = struct.unpack(">I", fh[4:8])[0]
        salt1 = struct.unpack(">I", fh[8:12])[0]
        salt2 = struct.unpack(">I", fh[12:16])[0]
        page_data = data[offset + FRAME_HEADER_SIZE : offset + frame_size]
        salt_match = salt1 == wal_header.salt1 and salt2 == wal_header.salt2
        frames.append(
            WalFrame(
                index=idx,
                page_no=page_no,
                commit_size=commit_size,
                salt1=salt1,
                salt2=salt2,
                data=page_data,
                salt_match=salt_match,
            )
        )
        offset += frame_size
        idx += 1
    return frames


def count_wal_frames(wal_path: str) -> int:
    """Return frame count for a WAL file, or 0 on any error."""
    try:
        with open(wal_path, "rb") as f:
            data = f.read()
    except OSError:
        return 0
    if len(data) < WAL_HEADER_SIZE:
        return 0
    header = parse_wal_header(data)
    if header is None:
        return 0
    return len(read_wal_frames(data, header))


def _btree_type_offset(page_no: int) -> int:
    return 100 if page_no == 1 else 0


def _extract_rowids(page: bytes, page_no: int, page_size: int) -> set[int]:
    """Best-effort: collect rowids of live cells in a table-leaf page."""
    from engine.record import try_read_varint
    from engine.sqlite_format import parse_page_header

    off = _btree_type_offset(page_no)
    if len(page) <= off or page[off] != LEAF_TABLE:
        return set()
    rowids: set[int] = set()
    try:
        header = parse_page_header(page, page_no, page_size)
        ptr_base = header.cell_ptr_array_offset
        for i in range(header.num_cells):
            ptr_off = ptr_base + i * 2
            if ptr_off + 2 > len(page):
                break
            cell_off = int.from_bytes(page[ptr_off : ptr_off + 2], "big")
            if not 0 <= cell_off < len(page):
                continue
            pv = try_read_varint(page, cell_off, len(page))
            if pv is None:
                continue
            _, p1 = pv
            rv = try_read_varint(page, p1, len(page))
            if rv is None:
                continue
            rowid, _ = rv
            rowids.add(rowid)
    except Exception:
        pass
    return rowids


def _carve_prior_frame(
    frame: WalFrame,
    page_size: int,
    encoding: str,
    cells: list,
    seen: set,
    current_rowids: set[int],
) -> None:
    off = _btree_type_offset(frame.page_no)
    if len(frame.data) <= off or frame.data[off] != LEAF_TABLE:
        return

    source = "wal" if frame.salt_match else "wal_stale"
    abs_base = (
        WAL_HEADER_SIZE
        + frame.index * (FRAME_HEADER_SIZE + page_size)
        + FRAME_HEADER_SIZE
    )

    try:
        from engine.sqlite_format import parse_page_header

        header = parse_page_header(frame.data, frame.page_no, page_size)
        ptr_base = header.cell_ptr_array_offset
        for i in range(header.num_cells):
            ptr_off = ptr_base + i * 2
            if ptr_off + 2 > page_size:
                break
            cell_off = int.from_bytes(frame.data[ptr_off : ptr_off + 2], "big")
            if not 0 <= cell_off < page_size:
                continue
            cell = carve_full_cell(
                frame.data,
                cell_off,
                page_size,
                source,
                frame.page_no,
                abs_base,
                encoding,
            )
            if cell is None:
                continue
            if cell.rowid is not None and cell.rowid in current_rowids:
                continue
            key = (cell.source, cell.page_no, cell.cell_offset, cell.byte_range)
            if key not in seen:
                seen.add(key)
                cells.append(cell)
    except Exception:
        pass


def carve_wal(
    wal_path: str,
    page_size: int | None = None,
    encoding: str = "utf-8",
) -> list:
    """Carve Activity records from prior-version WAL frames.

    Frames for the same page_no are grouped in file order. The last frame is
    the current state; earlier frames hold deleted/modified-away records. Only
    cells whose rowid is absent from the latest frame are emitted (avoids
    duplicating live records already captured by the live parser).

    source="wal" when frame salt matches WAL header (current epoch).
    source="wal_stale" for mismatched salt (recycled/old WAL).
    """
    try:
        with open(wal_path, "rb") as f:
            data = f.read()
    except OSError:
        return []

    if len(data) < WAL_HEADER_SIZE:
        return []

    wal_header = parse_wal_header(data)
    if wal_header is None:
        return []

    ps = page_size if page_size is not None else wal_header.page_size
    frames = read_wal_frames(data, wal_header)
    if not frames:
        return []

    by_page: dict[int, list[WalFrame]] = {}
    for f in frames:
        by_page.setdefault(f.page_no, []).append(f)

    cells: list = []
    seen: set = set()

    for page_no, page_frames in by_page.items():
        if len(page_frames) < 2:
            continue
        latest_frame = page_frames[-1]
        current_rowids = _extract_rowids(latest_frame.data, page_no, ps)
        for frame in page_frames[:-1]:
            _carve_prior_frame(frame, ps, encoding, cells, seen, current_rowids)

    return cells
