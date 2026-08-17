"""Unit tests for the headed/headless GPU classifier (pure part of x_browse)."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from x_browse import _is_software_renderer


def test_real_gpu_is_not_software():
    assert _is_software_renderer(
        "ANGLE (Apple, ANGLE Metal Renderer: Apple M3 Max, Unspecified Version)") is False

def test_swiftshader_is_software():
    assert _is_software_renderer(
        "ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device))") is True

def test_llvmpipe_is_software():
    assert _is_software_renderer("Mesa/X.org, llvmpipe (LLVM 15.0.7, 256 bits)") is True

def test_empty_renderer_is_not_software():
    # empty is handled separately by is_headed() (treated as unreadable/refuse),
    # the classifier itself only decides "does this string name a software GPU"
    assert _is_software_renderer("") is False

def test_intel_gpu_not_flagged():
    assert _is_software_renderer("ANGLE (Intel, Intel(R) UHD Graphics 630)") is False
