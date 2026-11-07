import sys

import pytest

from tao_gui import macos


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
def test_set_app_name():
    assert macos.set_app_name("Tao GUI")
    assert macos.app_name() == "Tao GUI"


@pytest.mark.skipif(sys.platform == "darwin", reason="not macOS")
def test_set_app_name_elsewhere_is_a_no_op():
    assert macos.set_app_name("Tao GUI") is False
    assert macos.app_name() is None
