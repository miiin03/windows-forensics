"""Measure carving precision/recall vs known-deleted GUID ground truth."""

from __future__ import annotations

import sys

from engine.pages import PageSource
from engine.carver.freelist import carve_freelist
from engine.carver.freeblock import carve_freeblocks


def _carved_guids(db_path: str) -> set[bytes]:
    ps = PageSource.from_file(db_path)
    cells = carve_freelist(ps) + carve_freeblocks(ps)
    return {c.values[0] for c in cells if c.values and isinstance(c.values[0], bytes)}


def measure(db_path: str, deleted_guids: set[bytes]) -> dict:
    recovered = _carved_guids(db_path)
    tp = len(recovered & deleted_guids)
    fp = len(recovered - deleted_guids)  # recovered but not a known delete = false positive
    recall = tp / len(deleted_guids) if deleted_guids else 0.0
    precision = tp / len(recovered) if recovered else (1.0 if not deleted_guids else 0.0)
    return {
        "recovered": len(recovered),
        "true_positives": tp,
        "false_positives": fp,
        "recall": round(recall, 3),
        "precision": round(precision, 3),
    }


if __name__ == "__main__":  # python -m bench.carving_metrics <db>  (manual check)
    print(measure(sys.argv[1], set()))
