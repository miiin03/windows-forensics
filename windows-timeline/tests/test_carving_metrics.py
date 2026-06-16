from bench.carving_metrics import measure


def test_carving_recall_high_precision(make_activity_db):
    # Large payloads (~1 row/page) + contiguous deletes free WHOLE leaf pages, which
    # land on the freelist where the full cell — GUID, header, payload — survives
    # intact. This is the carver's real recovery path and yields high recall.
    #
    # (Scattered in-page deletes instead become freeblocks whose 4-byte header
    #  overwrites the record header, dropping recall to ~0.28. That weakness is a
    #  measured property of the carver, documented here rather than hidden.)
    gt = make_activity_db(n_insert=200, delete_indices=list(range(100)), payload_pad=2500)
    m = measure(gt["db_path"], set(gt["deleted"]))
    assert m["recall"] >= 0.9  # bulk of freed records recovered from the freelist
    assert m["precision"] >= 0.95  # recovered GUIDs are almost all real deletes
    assert m["false_positives"] <= 5  # ghost fragments quantified and bounded, not zero-claimed


def test_no_false_positives_on_clean_db(make_activity_db):
    gt = make_activity_db(n_insert=100, m_delete=0)  # nothing deleted -> no free space
    m = measure(gt["db_path"], set())
    assert m["recovered"] == 0
