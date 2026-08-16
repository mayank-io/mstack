import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from x_media import media_filename

def test_media_filename_format():
    assert media_filename("vedanjanam", "2020489596505592084", 1) \
        == "vedanjanam-2020489596505592084-1.jpg"

def test_media_filename_lowercases_handle():
    assert media_filename("Vedanjanam", "1", 2) == "vedanjanam-1-2.jpg"
