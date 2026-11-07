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
    assert "tao.init" in gui.startup.command_label.text()


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


def test_plotting_off(fresh_gui, qtbot):
    gui = fresh_gui
    gui.show_startup()
    gui.startup.set_options(StartupOptions(directory=str(FILES), lattice_file="fodo.bmad",
                                           plotting=False))
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
                                           rad_int=False))
    start(qtbot, gui)
    gui.startup._load_recent()
    assert gui.startup.recent_combo.count() == 1
    gui.startup.set_options(StartupOptions())
    gui.startup._on_recent(0)
    assert gui.startup.files["init_file"].text() == "tao.init"
    assert gui.startup.tri["rad_int"].value() is False


def test_options_to_args():
    opts = StartupOptions(directory="/a/b", init_file="/a/b/tao.init", lattice_file="/c/l.bmad",
                          run_startup=False, rf_on=True, plotting=False, rad_int=False,
                          extra_args="-reverse")
    assert opts.tao_args() == ["-init_file", "tao.init", "-lattice_file", "/c/l.bmad",
                               "-no_rad_int", "-nostartup", "-reverse"]
    assert opts.set_commands() == ["set global rad_int_user_calc_on = F", "set global rf_on = T"]


def test_file_open_reuses_startup_window(gui, qtbot):
    gui.act_open.trigger()
    assert gui.startup.isVisible()
    assert gui.startup.start_button.text() == "Reinitialize Tao"
    gui.startup.cancel_button.click()
    assert not gui.startup.isVisible()
    assert gui.windows["console"].isVisible()  # cancelling does not quit


def test_option_labels_and_defaults(fresh_gui):
    from tao_gui.startup import CHECK_OPTIONS, TRI_OPTIONS

    labels = [o.label for o in TRI_OPTIONS] + [c[1] for c in CHECK_OPTIONS]
    for label in labels:
        assert not label.lower().startswith(("no ", "skip", "disable")), label
    assert "Compute radiation integrals" in labels
    startup = fresh_gui.startup
    for opt in TRI_OPTIONS:  # all tri-state options start as "not set"
        assert startup.tri[opt.name].value() is None
    assert startup.checks["run_startup"].isChecked()
    assert not startup.checks["debug"].isChecked()
    opts = StartupOptions(init_file="a.init")
    assert opts.tao_args() == ["-init_file", "a.init"] and opts.set_commands() == []


def test_default_follows_init_file(fresh_gui, tmp_path):
    (tmp_path / "rf.init").write_text(
        "&tao_start\n  startup_file = 'my.startup'  ! comment\n/\n"
        "&tao_design_lattice\n  design_lattice(1)%file = 'x.bmad'\n/\n"
        "&tao_params\n  global%rf_on = F\n  global%disable_smooth_line_calc = .true.\n/\n")
    (tmp_path / "x.bmad").write_text("")
    startup = fresh_gui.startup
    startup.set_options(StartupOptions(directory=str(tmp_path), init_file="rf.init"))
    for opt in ("rf_on", "smooth_line_calc", "rad_int", "plotting"):
        assert startup.tri[opt].itemText(0) == "Default"
        assert startup.tao_default_labels[opt].text() == "On"  # Tao's own defaults
    assert "rf.init sets it off" in startup.tri["rf_on"].toolTip()
    assert "rf.init sets it off" in startup.tri["smooth_line_calc"].toolTip()
    assert "doesn't set it" in startup.tri["rad_int"].toolTip()
    assert startup.files["startup_file"].edit.placeholderText() == "my.startup (from rf.init)"
    opts = startup.options_value()
    assert opts.effective("rf_on") is False and opts.effective("rad_int") is True


def test_explicit_choice_overrides_init_file(fresh_gui, qtbot, tmp_path):
    import shutil

    shutil.copy(FILES / "fodo.bmad", tmp_path)
    (tmp_path / "rf.init").write_text(
        "&tao_design_lattice\n  design_lattice(1)%file = 'fodo.bmad'\n/\n"
        "&tao_params\n  global%rf_on = F\n  global%disable_smooth_line_calc = T\n/\n")
    gui = fresh_gui
    gui.startup.set_options(StartupOptions(directory=str(tmp_path), init_file="rf.init",
                                           rf_on=True, smooth_line_calc=True))
    assert "set global rf_on = T" in gui.startup.command_label.text()
    start(qtbot, gui)
    assert gui.client.is_running
    box = {}
    gui.client.call(lambda t: t.tao_global(), on_done=lambda g: box.setdefault("g", g))
    qtbot.waitUntil(lambda: "g" in box, timeout=30_000)
    assert box["g"]["rf_on"] is True
    assert box["g"]["disable_smooth_line_calc"] is False


def test_old_recent_entries_are_converted():
    old = {"init_file": "a.init", "no_plot": True, "nostartup": False, "no_rad_int": False,
           "disable_smooth_line_calc": False, "rf_on": False, "debug": False}
    opts = StartupOptions.from_dict(old)
    assert (opts.plotting, opts.run_startup, opts.rad_int, opts.smooth_line_calc, opts.rf_on) == (
        False, True, None, None, None)


def test_working_directory_with_tao_init_is_enough(fresh_gui, qtbot):
    gui = fresh_gui
    gui.show_startup()
    gui.startup.set_options(StartupOptions(directory=str(FILES)))
    assert gui.startup.start_button.isEnabled()
    assert gui.startup.files["init_file"].edit.placeholderText().startswith("tao.init")
    assert "-init_file tao.init" in gui.startup.command_label.text()
    start(qtbot, gui)
    assert gui.client.is_running
    assert len(gui.lattice.model.rows) == 66


def test_directory_without_tao_init_is_not_enough(fresh_gui, tmp_path):
    gui = fresh_gui
    gui.startup.set_options(StartupOptions(directory=str(tmp_path)))
    assert not gui.startup.start_button.isEnabled()
    assert StartupOptions(directory=str(tmp_path)).tao_args() == []


def test_recent_has_no_duplicates(fresh_gui):
    from tao_gui.startup import load_recent, save_recent

    d = str(FILES)
    save_recent(StartupOptions(directory=d, init_file="tao.init", rad_int=False))
    save_recent(StartupOptions(directory=d, lattice_file="fodo.bmad"))
    # Same files again: by absolute path, with a trailing slash, and with other options.
    save_recent(StartupOptions(directory=d + os.sep, init_file=str(FILES / "tao.init"),
                               rf_on=True))
    recent = load_recent()
    assert len(recent) == 2
    assert recent[0].rf_on is True and recent[0].rad_int is None  # the latest one is kept
    assert recent[1].lattice_file == "fodo.bmad"

    # A working directory whose tao.init is used is the same startup as naming tao.init.
    save_recent(StartupOptions(directory=d))
    recent = load_recent()
    assert len(recent) == 2 and recent[0].init_file == ""


def test_saved_duplicates_are_dropped_on_load(fresh_gui):
    import json

    from PySide6.QtCore import QSettings

    from tao_gui.startup import load_recent

    d = str(FILES)
    entries = [{"directory": d, "init_file": "tao.init", "rf_on": True},
               {"directory": d, "init_file": "tao.init", "rf_on": False}]
    QSettings().setValue("startup/recent", json.dumps(entries))
    recent = load_recent()
    assert len(recent) == 1 and recent[0].rf_on is True
    fresh_gui.startup._load_recent()
    assert fresh_gui.startup.recent_combo.count() == 1
