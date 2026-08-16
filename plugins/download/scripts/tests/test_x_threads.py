import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from x_threads import cluster
from x_snowflake import THREAD_GAP_MS

ROOT = 1997633559859790018
def at(delta_ms):  # build an ID delta_ms after ROOT
    return str(ROOT + (delta_ms << 22))

def rec(sid, reply_other=False):
    return {"status_id": sid, "is_reply_to_other": reply_other}

def test_tight_cluster_is_one_thread():
    posts = [rec(at(0)), rec(at(8297)), rec(at(16000))]
    assert cluster(posts) == [[at(0), at(8297), at(16000)]]

def test_gap_splits_thread_from_replies():
    # 3 thread posts, then a 192-min-later reply-to-commenter
    posts = [rec(at(0)), rec(at(8297)), rec(at(16000)),
             rec(at(11524823), reply_other=True)]
    assert cluster(posts) == [[at(0), at(8297), at(16000)], [at(11524823)]]

def test_reply_to_other_never_joins_even_if_close():
    posts = [rec(at(0)), rec(at(5000), reply_other=True)]
    assert cluster(posts) == [[at(0)], [at(5000)]]

def test_exact_boundary_gap_stays_in_thread():
    posts = [rec(at(0)), rec(at(THREAD_GAP_MS))]  # exactly 30 min
    assert cluster(posts) == [[at(0), at(THREAD_GAP_MS)]]

def test_one_ms_over_boundary_splits():
    posts = [rec(at(0)), rec(at(THREAD_GAP_MS + 1))]
    assert cluster(posts) == [[at(0)], [at(THREAD_GAP_MS + 1)]]

def test_single_post_is_singleton():
    assert cluster([rec(at(0))]) == [[at(0)]]
