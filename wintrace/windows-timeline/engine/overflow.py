"""Overflow-page chain reassembly for SQLite payload reconstruction.

Each overflow page: first 4B big-endian = next page number (0 = end of chain),
remaining bytes = payload data. A broken or stale chain returns whatever bytes
were gathered before the chain stopped; callers detect truncation by comparing
len(result) to need_bytes.
"""

from __future__ import annotations

_MAX_CHAIN_STEPS = 16384  # guard against cycles / corrupt chains


def reassemble_payload(
    first_overflow_page: int,
    need_bytes: int,
    page_source,
) -> bytes:
    """Follow overflow page chain and return up to ``need_bytes`` of payload.

    Never raises. Returns a partial result if the chain breaks early.
    Callers should treat len(result) < need_bytes as payload_truncated.
    """
    if need_bytes <= 0 or first_overflow_page <= 0:
        return b""

    usable = page_source.usable_size
    data_per_page = usable - 4

    out = bytearray()
    page_no = first_overflow_page
    visited: set[int] = set()
    steps = 0

    while page_no > 0 and len(out) < need_bytes:
        if steps >= _MAX_CHAIN_STEPS:
            break
        if page_no in visited or page_no > page_source.page_count:
            break
        visited.add(page_no)
        steps += 1

        page = page_source.get_page(page_no)
        if len(page) < 4:
            break

        next_page = int.from_bytes(page[0:4], "big")
        remaining = need_bytes - len(out)
        chunk = page[4 : 4 + min(data_per_page, remaining)]
        out.extend(chunk)
        page_no = next_page

    return bytes(out)
