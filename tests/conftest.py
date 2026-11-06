import os
import pathlib

import pytest

FILES = pathlib.Path(__file__).parent / "files"

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def wait_idle(qtbot, client, timeout=60_000):
    qtbot.waitUntil(lambda: not client.busy, timeout=timeout)


@pytest.fixture
def window(qtbot, monkeypatch):
    from PySide6.QtCore import QCoreApplication

    from tao_gui.main_window import MainWindow

    QCoreApplication.setOrganizationName("bmad-sim-tests")
    QCoreApplication.setApplicationName("tao-gui-tests")
    monkeypatch.chdir(FILES)

    win = MainWindow()
    qtbot.addWidget(win)
    win.start_tao("-init tao.init")
    qtbot.waitUntil(lambda: win.client.is_running, timeout=60_000)
    wait_idle(qtbot, win.client)
    yield win
    win.client.shutdown()
