import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from x_snowflake import timestamp_ms, id_sort_key, same_thread, THREAD_GAP_MS

ROOT  = "1997633559859790018"   # 2025-12-07 11:45:29.564 UTC
FOCAL = "1997633594659836065"   # root + 8.297s
LATER = "1997681933271330968"   # root + ~192 min (documented false positive)

def test_timestamp_ms_known_id():
    # 2025-12-07 11:45:29.564 UTC == 1765107929564 ms
    assert timestamp_ms(ROOT) == 1765107929564

def test_real_thread_gap_is_8297ms():
    assert timestamp_ms(FOCAL) - timestamp_ms(ROOT) == 8297

def test_false_positive_gap_is_192min():
    assert timestamp_ms(LATER) - timestamp_ms(FOCAL) == 11524823

def test_id_sort_key_orders_by_length_then_value():
    # shorter string = numerically smaller (fewer digits)
    ids = ["1997633594659836065", "999", "1997633559859790018"]
    assert sorted(ids, key=id_sort_key) == ["999", "1997633559859790018", "1997633594659836065"]

def test_same_thread_true_for_8s_gap():
    assert same_thread(ROOT, FOCAL) is True

def test_same_thread_false_for_192min_gap():
    assert same_thread(FOCAL, LATER) is False

def test_same_thread_boundary_is_inclusive():
    # a synthetic pair exactly THREAD_GAP_MS apart must be KEPT (<=)
    base = int(ROOT)
    exactly_30min_later = str(base + (THREAD_GAP_MS << 22))
    assert same_thread(ROOT, exactly_30min_later) is True

def test_same_thread_one_ms_past_boundary_is_false():
    base = int(ROOT)
    over = str(base + ((THREAD_GAP_MS + 1) << 22))
    assert same_thread(ROOT, over) is False
