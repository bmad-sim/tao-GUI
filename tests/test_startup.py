import os

from PySide6.QtWidgets import QApplication

from conftest import FILES, wait_idle
from tao_gui.startup import StartupOptions


def visible_windows():
    return [w for w in QApplication.topLevelWidgets() if w.isVisible()]


def start(qtbot, gui):
    gui.startup.start_button.click()
    qtbot.waitUntil(lambda: gui.client.is_running or gui.startup.message.isVisible(),
                    timeout=60_000)
    wait_idle(qtbot, gui.client)


def test_only_startup_window_opens(fresh_gui):
    gui = fresh_gui
    gui.show_startup()
    assert visible_windows() == [gui.startup]
    assert not gui.plot_windows
    assert not gui.startup.start_button.isEnabled()  # nothing chosen yet
    assert "init file or a lattice file" in gui.startup.command_label.text()


def test_start_from_init_file(fresh_gui, qtbot):
    gui = fresh_gui
    gui.show_startup()
    gui.startup.files["init_file"].set_text(str(FILES / "tao.init"))
    # Choosing a file sets the working directory and shows the file relative to it.
    assert gui.startup.directory.text() == str(FILES)
    gui.startup._relativize()
    assert gui.startup.files["init_file"].text() == "tao.init"
    assert "-init_file tao.init" in gui.startup.command_label.text()

    start(qtbot, gui)
    assert gui.client.is_running
    assert os.getcwd() == str(FILES)
    assert not gui.startup.isVisible()
    assert gui.windows["console"].isVisible() and gui.windows["lattice"].isVisible()
    assert len(gui.plot_windows) == 2
    assert len(gui.lattice.model.rows) == 66


def test_no_plotting_option(fresh_gui, qtbot):
    gui = fresh_gui
    gui.show_startup()
    gui.startup.set_options(StartupOptions(directory=str(FILES), lattice_file="fodo.bmad",
                                           no_plot=True))
    start(qtbot, gui)
    assert gui.client.is_running
    assert gui.windows["console"].isVisible()
    assert gui.plot_windows == []
    assert not gui.act_new_plot.isEnabled()


def test_bad_start_keeps_startup_window(fresh_gui, qtbot, tmp_path):
    gui = fresh_gui
    (tmp_path / "bad.bmad").write_text(
        "parameter[geometry] = open\nbeginning[beta_a] = 10\nbeginning[beta_b] = 10\n"
        "d: drift, l = 1\nring: line = (d, nosuch)\nuse, ring\n")
    gui.show_startup()
    gui.startup.set_options(StartupOptions(directory=str(tmp_path), lattice_file="bad.bmad"))
    start(qtbot, gui)
    assert not gui.client.is_running
    assert gui.startup.isVisible()
    assert "NOT A DEFINED ELEMENT" in gui.startup.message.toPlainText()
    assert not gui.windows["console"].isVisible()
    assert gui.startup.start_button.isEnabled()  # can fix the choice and retry

    gui.startup.set_options(StartupOptions(directory=str(FILES), lattice_file="fodo.bmad"))
    start(qtbot, gui)
    assert gui.client.is_running
    assert not gui.startup.isVisible()
    assert gui.windows["console"].isVisible()


def test_missing_file_blocks_start(fresh_gui):
    gui = fresh_gui
    gui.startup.set_options(StartupOptions(directory=str(FILES), init_file="nope.init"))
    assert not gui.startup.start_button.isEnabled()
    assert "not found" in gui.startup.command_label.text()


def test_recent_startups(fresh_gui, qtbot):
    gui = fresh_gui
    gui.startup.set_options(StartupOptions(directory=str(FILES), init_file="tao.init",
                                           no_rad_int=True))
    start(qtbot, gui)
    gui.startup._load_recent()
    assert gui.startup.recent_combo.count() == 1
    gui.startup.set_options(StartupOptions())
    gui.startup._on_recent(0)
    assert gui.startup.files["init_file"].text() == "tao.init"
    assert gui.startup.options["no_rad_int"].isChecked()


def test_options_to_args():
    opts = StartupOptions(directory="/a/b", init_file="/a/b/tao.init", lattice_file="/c/l.bmad",
                          nostartup=True, rf_on=True, no_plot=True, extra_args="-reverse")
    assert opts.tao_args() == ["-init_file", "tao.init", "-lattice_file", "/c/l.bmad",
                               "-nostartup", "-rf_on", "-reverse"]


def test_file_open_reuses_startup_window(gui, qtbot):
    gui.act_open.trigger()
    assert gui.startup.isVisible()
    assert gui.startup.start_button.text() == "Reinitialize Tao"
    gui.startup.cancel_button.click()
    assert not gui.startup.isVisible()
    assert gui.windows["console"].isVisible()  # cancelling does not quit
