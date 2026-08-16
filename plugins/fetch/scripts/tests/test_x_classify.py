import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from x_classify import needs_click_in

def _sig(**kw):
    base = {"is_thread": False, "truncated": False, "is_article": False, "photo_count": 0}
    base.update(kw); return base

def test_include_metrics_approximate_does_not_force_clickin():
    assert needs_click_in(_sig(), include_metrics="approximate") is False

def test_include_metrics_off_does_not_force_clickin():
    assert needs_click_in(_sig(), include_metrics="off") is False

def test_include_metrics_exact_forces_clickin():
    assert needs_click_in(_sig(), include_metrics="exact") is True

def test_thread_signal_forces_clickin():
    assert needs_click_in(_sig(is_thread=True), include_metrics="approximate") is True

def test_truncated_forces_clickin():
    assert needs_click_in(_sig(truncated=True), include_metrics="approximate") is True

def test_article_forces_clickin():
    assert needs_click_in(_sig(is_article=True), include_metrics="approximate") is True

def test_media_present_forces_clickin():
    assert needs_click_in(_sig(photo_count=2), include_metrics="approximate") is True

def test_plain_post_with_approximate_metrics_stays_on_timeline():
    assert needs_click_in(_sig(), include_metrics="approximate") is False
