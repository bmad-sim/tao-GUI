from PySide6.QtCore import Qt

from conftest import wait_idle

N_ELEMENTS = 66  # BEGINNING + 8 cells * 8 elements + END
QF = 1  # element index of the first QF


def run_sync(qtbot, client, fn):
    """Run ``fn(tao)`` on the worker and return its result."""
    box = {}
    client.call(fn, on_done=lambda r: box.setdefault("result", r))
    qtbot.waitUntil(lambda: "result" in box, timeout=30_000)
    return box["result"]


def column(table, title):
    return [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())].index(title)


# ----------------------------------------------------------------------
# Windows and menus


def test_sections_are_separate_windows(gui):
    windows = list(gui.windows.values()) + gui.plot_windows
    assert {w.key for w in gui.windows.values()} == {
        "console", "lattice", "data", "variables", "optimizer"}
    for window in windows:
        assert window.isWindow() and window.parent() is None
        menus = [a.text().replace("&", "") for a in window.menuBar().actions()]
        assert menus == ["File", "Tao", "Plot", "Window", "Help"]
    assert gui.windows["console"].isVisible()
    assert gui.windows["lattice"].isVisible()
    assert len(gui.plot_windows) == 2 and all(w.isVisible() for w in gui.plot_windows)


def test_window_menu_opens_section(gui):
    data_window = gui.windows["data"]
    assert not data_window.isVisible()
    gui.section_actions["data"].trigger()
    assert data_window.isVisible()
    data_window.close()  # hides, does not destroy
    assert not data_window.isVisible()
    assert gui.windows["data"] is data_window


def test_new_and_close_plot_window(gui, qtbot):
    gui.act_new_plot.trigger()
    assert len(gui.plot_windows) == 3
    window = gui.plot_windows[-1]
    window.panel.set_template("floor_plan")
    wait_idle(qtbot, gui.client)
    assert window.windowTitle().startswith("Plot: floor_plan")
    assert len(window.panel.figure.axes) == 1  # no lattice layout under a floor plan
    window.close()
    assert window not in gui.plot_windows


# ----------------------------------------------------------------------
# Lattice, console


def test_startup(gui):
    assert gui.client.is_running
    assert len(gui.lattice.model.rows) == N_ELEMENTS
    assert "beta" in gui.templates
    for panel in gui.plot_panels:
        assert panel.region is not None, panel.status.text()
        assert panel.is_s_plot


def test_console_command(gui, qtbot):
    gui.console.input.setText("show ele qf")
    gui.console.input.returnPressed.emit()
    wait_idle(qtbot, gui.client)
    text = gui.console.output.toPlainText()
    assert "Tao> show ele qf" in text
    assert "Quadrupole" in text


def test_console_error_is_shown(gui, qtbot):
    gui.console.run_command("not_a_command")
    wait_idle(qtbot, gui.client)
    assert "UNRECOGNIZED COMMAND" in gui.console.output.toPlainText()


def test_filter(gui):
    gui.lattice.filter_edit.setText("q*")
    assert gui.lattice.proxy.rowCount() == 16
    gui.lattice.filter_edit.setText("sbend")  # matches the key column
    assert gui.lattice.proxy.rowCount() == 16
    gui.lattice.filter_edit.clear()
    assert gui.lattice.proxy.rowCount() == N_ELEMENTS


def test_edit_attribute_updates_tao_and_plots(gui, qtbot):
    lattice = gui.lattice
    lattice.select_element(QF)
    wait_idle(qtbot, gui.client)
    names = [lattice.attributes.item(r, 0).text() for r in range(lattice.attributes.rowCount())]
    row = names.index("K1")

    beta_panel = gui.plot_panels[0]
    before = beta_panel.figure.axes[0].lines[0].get_ydata().copy()

    lattice.attributes.item(row, 1).setText("0.35")
    wait_idle(qtbot, gui.client)

    k1 = run_sync(qtbot, gui.client, lambda t: t.ele_gen_attribs(f"0>>{QF}")["K1"])
    assert abs(k1 - 0.35) < 1e-12
    after = beta_panel.figure.axes[0].lines[0].get_ydata()
    assert len(after) != len(before) or abs(after - before).max() > 1e-6
    assert f"set ele 0>>{QF} K1 = 0.35" in gui.console.output.toPlainText()


# ----------------------------------------------------------------------
# Selection and linked zoom


def test_lattice_selection_shades_plots(gui, qtbot):
    gui.lattice.table.selectRow(5)  # user selection (QD)
    wait_idle(qtbot, gui.client)
    row = gui.lattice.row_for(5)
    assert gui.selected is row
    for panel in gui.plot_panels:
        assert panel.selection == (row.s - row.length, row.s)
        assert panel._selection_artists


def test_plot_click_selects_element(gui, qtbot):
    from matplotlib.backend_bases import MouseButton, MouseEvent

    panel = gui.plot_panels[0]
    ax = panel.s_axes[0]
    qf = gui.lattice.row_for(QF)
    s_mid = qf.s - qf.length / 2
    x, y = ax.transData.transform((s_mid, sum(ax.get_ylim()) / 2))
    event = MouseEvent("button_press_event", panel.canvas, x, y, MouseButton.LEFT)
    panel.canvas.callbacks.process("button_press_event", event)
    wait_idle(qtbot, gui.client)
    assert gui.selected is not None and gui.selected.ix == QF
    assert gui.lattice.selected_ix == QF


def test_linked_zoom(gui):
    a, b = gui.plot_panels
    a.s_axes[0].set_xlim(10, 20)  # as if the user zoomed in panel a
    assert b.s_range() == (10, 20)
    gui.act_link_zoom.setChecked(False)
    a.s_axes[0].set_xlim(30, 40)
    assert b.s_range() == (10, 20)
    gui.act_reset_zoom.trigger()
    assert a.s_range()[0] < 1 and b.s_range()[0] < 1


def test_zoom_survives_refresh(gui, qtbot):
    a = gui.plot_panels[0]
    a.s_axes[0].set_xlim(10, 20)
    gui.act_refresh.trigger()
    wait_idle(qtbot, gui.client)
    assert a.s_range() == (10, 20)


# ----------------------------------------------------------------------
# Data, variables, optimizer


def test_data_window(gui, qtbot):
    data = gui.data
    wait_idle(qtbot, gui.client)
    assert data.current == "twiss.beta"
    table = data.table
    assert table.rowCount() == 2
    assert table.item(0, column(table, "Data type")).text() == "beta.a"

    table.item(0, column(table, "Weight")).setText("2")
    wait_idle(qtbot, gui.client)
    w = run_sync(qtbot, gui.client, lambda t: t.data_d_array("twiss", "beta", ix_uni=1)[0]["weight"])
    assert w == 2

    table.item(1, column(table, "Use")).setCheckState(Qt.Unchecked)
    wait_idle(qtbot, gui.client)
    good = run_sync(qtbot, gui.client, lambda t: t.data_d_array("twiss", "beta", ix_uni=1)[1]["good_user"])
    assert good is False
    assert table.item(1, column(table, "Use")).checkState() == Qt.Unchecked


def test_variables_window(gui, qtbot):
    variables = gui.variables
    wait_idle(qtbot, gui.client)
    assert variables.current == "quad"
    table = variables.table
    assert [table.item(r, column(table, "Element[attribute]")).text() for r in range(2)] == [
        "QF[K1]", "QD[K1]"]
    table.item(0, column(table, "Model")).setText("0.31")
    wait_idle(qtbot, gui.client)
    k1 = run_sync(qtbot, gui.client, lambda t: t.ele_gen_attribs(f"0>>{QF}")["K1"])
    assert abs(k1 - 0.31) < 1e-12
    assert table.item(0, column(table, "Model")).text() == "0.31"


def test_optimizer_lowers_merit(gui, qtbot):
    opt = gui.optimizer
    wait_idle(qtbot, gui.client)
    before = float(opt.merit_label.text())
    assert before > 1
    assert opt.optimizer_combo.currentText() == "lm"
    gui.act_run.trigger()
    assert gui.windows["optimizer"].isVisible()
    wait_idle(qtbot, gui.client)
    assert not opt.running
    after = float(opt.merit_label.text())
    assert after < before
    assert "Tao> run" in gui.console.output.toPlainText()


def test_worker_error_reaches_callback(gui, qtbot):
    errors = []

    def boom(tao):
        raise ValueError("boom")

    gui.client.call(boom, on_error=errors.append)
    qtbot.waitUntil(lambda: bool(errors), timeout=10_000)
    assert errors == ["ValueError: boom"]
