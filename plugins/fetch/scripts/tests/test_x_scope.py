import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from x_scope import classify, is_kept

H = "vedanjanam"

def p(**kw):
    base = {"in_reply_to": None, "is_repost": False, "has_quoted_status": False}
    base.update(kw); return base

def test_standalone_original_kept():
    assert classify(p(), H) == "original"
    assert is_kept("original") is True

def test_self_reply_is_kept_thread_body():
    assert classify(p(in_reply_to=H), H) == "self_reply"
    assert is_kept("self_reply") is True

def test_self_reply_case_insensitive():
    assert classify(p(in_reply_to="Vedanjanam"), H) == "self_reply"

def test_reply_to_other_dropped():
    assert classify(p(in_reply_to="someoneelse"), H) == "reply_to_other"
    assert is_kept("reply_to_other") is False

def test_repost_dropped_even_if_self():
    assert classify(p(in_reply_to=H, is_repost=True), H) == "repost"
    assert is_kept("repost") is False

def test_quote_post_kept():
    assert classify(p(has_quoted_status=True), H) == "quote"
    assert is_kept("quote") is True
