import os
import pathlib

import pytest

FILES = pathlib.Path(__file__).parent / "files"

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def wait_idle(qtbot, client, timeout=60_000):
    qtbot.waitUntil(lambda: not client.busy, timeout=timeout)


@pytest.fixture
def gui(qtbot, monkeypatch):
    from PySide6.QtCore import QCoreApplication, QSettings

    from tao_gui.application import TaoGui

    QCoreApplication.setOrganizationName("bmad-sim-tests")
    QCoreApplication.setApplicationName("tao-gui-tests")
    QSettings().clear()
    monkeypatch.chdir(FILES)

    app = TaoGui(restore=False)
    for window in list(app.windows.values()) + app.plot_windows:
        qtbot.addWidget(window)
    app.start_tao("-init tao.init")
    qtbot.waitUntil(lambda: app.client.is_running, timeout=60_000)
    wait_idle(qtbot, app.client)
    yield app
    app.shutdown(save=False)
