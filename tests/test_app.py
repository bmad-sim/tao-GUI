from PySide6.QtCore import Qt

from conftest import wait_idle
from tao_gui import plots

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


# ----------------------------------------------------------------------
# Plot window details


def _graph_height(panel):
    panel.canvas.draw()
    return panel.figure.axes[0].get_window_extent().height


def test_no_region_names_shown(gui):
    for window in gui.plot_windows:
        panel = window.panel
        assert not panel.status.isVisible()
        assert "region" not in window.windowTitle()


def test_plot_window_title_is_just_the_plot(gui):
    assert [w.windowTitle() for w in gui.plot_windows] == ["Plot: beta", "Plot: orbit"]
    gui.plot_windows[1].panel.set_template("floor_plan")
    assert gui.plot_windows[1].windowTitle() == "Plot: floor_plan"


def test_layout_strip_has_no_frame_or_grid(gui):
    ax = gui.plot_panels[0].figure.axes[-1]  # the lattice layout
    assert not any(spine.get_visible() for spine in ax.spines.values())
    assert not any(line.get_visible() for line in ax.get_xgridlines())


def test_toggling_layout_keeps_graph_height(gui, qtbot):
    window = gui.plot_windows[0]
    panel = window.panel
    window.resize(900, 600)
    qtbot.wait(100)
    panel.refresh()
    wait_idle(qtbot, gui.client)
    qtbot.wait(100)
    graph_before = _graph_height(panel)
    height_before = window.height()

    panel.layout_check.setChecked(False)
    wait_idle(qtbot, gui.client)
    qtbot.wait(100)
    assert len(panel.figure.axes) == 1
    assert window.height() < height_before
    assert abs(_graph_height(panel) - graph_before) < 0.06 * graph_before

    panel.layout_check.setChecked(True)
    wait_idle(qtbot, gui.client)
    qtbot.wait(100)
    assert len(panel.figure.axes) == 2
    assert abs(window.height() - height_before) <= 2
    assert abs(_graph_height(panel) - graph_before) < 0.06 * graph_before


# ----------------------------------------------------------------------
# Parameter windows (double-click a datum or variable)


def test_parse_pipe_parameters():
    from tao_gui.details import parse_pipe_parameters

    params = parse_pipe_parameters([
        "data^merit_type;ENUM;T;target",
        "meas_value;REAL;T;  1.200000000000000E+001",
        "ix_d1;INT;F;1",
        "good_user;LOGIC;T;F",
    ])
    assert [(p.name, p.settable, p.value) for p in params] == [
        ("merit_type", True, "target"), ("meas_value", True, 12.0),
        ("ix_d1", False, 1), ("good_user", True, False)]


def test_double_click_datum_opens_parameters(gui, qtbot):
    table = gui.data.table
    assert not (table.editTriggers() & table.EditTrigger.DoubleClicked)
    table.cellDoubleClicked.emit(1, column(table, "Element"))
    window = gui.parameter_windows[("data", "1@twiss.beta[2]")]
    assert window.isVisible()
    assert window.windowTitle() == "Datum: 1@twiss.beta[2]"
    wait_idle(qtbot, gui.client)
    names = [p.name for p in window.table.params]
    assert {"data_type", "merit_type", "meas_value", "model_value", "weight", "s"} <= set(names)
    data_type = table.item(1, column(table, "Data type")).text()
    assert window.table.value_item("data_type").text() == data_type == "beta.b"
    assert data_type in window.header.text()

    # Read-only parameters cannot be edited; settable ones issue `set data`.
    assert not window.table.value_item("model_value").flags() & Qt.ItemIsEditable
    window.table.value_item("weight").setText("3")
    wait_idle(qtbot, gui.client)
    w = run_sync(qtbot, gui.client, lambda t: t.data_d_array("twiss", "beta", ix_uni=1)[1]["weight"])
    assert w == 3
    assert window.table.value_item("weight").text() == "3"
    assert gui.data.table.item(1, column(gui.data.table, "Weight")).text() == "3"

    window.table.value_item("good_user").setCheckState(Qt.Unchecked)
    wait_idle(qtbot, gui.client)
    good = run_sync(qtbot, gui.client, lambda t: t.data_d_array("twiss", "beta", ix_uni=1)[1]["good_user"])
    assert good is False

    # Double-clicking again raises the same window; closing removes it.
    table.cellDoubleClicked.emit(1, 0)
    assert len(gui.parameter_windows) == 1
    window.close()
    assert not gui.parameter_windows


def test_double_click_variable_opens_parameters(gui, qtbot):
    table = gui.variables.table
    table.cellDoubleClicked.emit(0, 0)
    window = gui.parameter_windows[("var", "quad[1]")]
    wait_idle(qtbot, gui.client)
    assert window.windowTitle() == "Variable: quad[1]"
    assert "QF[K1]" in window.header.text()
    assert window.table.value_item("attrib_name").text() == "K1"

    window.table.value_item("step").setText("2e-4")
    wait_idle(qtbot, gui.client)
    step = run_sync(qtbot, gui.client, lambda t: t.var("quad[1]")["step"])
    assert abs(step - 2e-4) < 1e-15

    # A value Tao rejects is put back and reported.
    old = window.table.value_item("base_value").text()
    window.table.value_item("base_value").setText("0.2")
    wait_idle(qtbot, gui.client)
    assert window.table.value_item("base_value").text() == old
    assert "Tao rejected" in window.statusBar().currentMessage()


def test_parameter_window_columns_toggle(gui, qtbot):
    from PySide6.QtCore import QSettings

    from tao_gui.details import TWO_COLUMNS_KEY

    window = gui.show_parameters("data", "1@twiss.beta[1]")
    wait_idle(qtbot, gui.client)
    table = window.table
    n = len(table.params)
    assert window.two_columns.isChecked()  # two columns is the default
    assert table.columnCount() == 4 and table.rowCount() == (n + 1) // 2
    headers = [table.horizontalHeaderItem(c).text() for c in range(4)]
    assert headers == ["Parameter", "Value", "Parameter", "Value"]
    # Parameters run down the left pair, then down the right one.
    assert table.item(0, 0).text() == table.params[0].name
    assert table.item(0, 2).text() == table.params[table.rowCount()].name

    # Editing works in the right-hand pair.
    assert table.value_item("weight").column() == 3
    table.value_item("weight").setText("4")
    wait_idle(qtbot, gui.client)
    w = run_sync(qtbot, gui.client, lambda t: t.data_d_array("twiss", "beta", ix_uni=1)[0]["weight"])
    assert w == 4

    assert fits(qtbot, window)
    width, height = window.width(), window.height()
    window.two_columns.setChecked(False)
    assert table.columnCount() == 2 and table.rowCount() == n
    assert table.value_item("weight").text() == "4"
    # The window refits: narrower and taller (up to the screen height).
    assert fits(qtbot, window)
    assert window.width() < width and window.height() > height
    assert QSettings().value(TWO_COLUMNS_KEY, type=bool) is False

    # New windows use the last choice.
    other = gui.show_parameters("var", "quad[1]")
    assert not other.two_columns.isChecked() and other.table.columnCount() == 2
    wait_idle(qtbot, gui.client)
    assert fits(qtbot, other)

    # Back to two columns: the window refits with no scroll bar.
    window.two_columns.setChecked(True)
    assert fits(qtbot, window) and not table.verticalScrollBar().isVisible()


def fits(qtbot, window) -> bool:
    """The parameter table shows every cell: no scroll bars, no clipped columns.

    A window as tall as the screen may still need a vertical scroll bar.
    """
    qtbot.wait(50)  # let the resize and layout settle
    table = window.table
    max_height = window.screen().availableGeometry().height()
    at_screen_height = window.frameGeometry().height() >= max_height - 1
    if table.verticalScrollBar().isVisible() and not at_screen_height:
        return False
    if table.horizontalScrollBar().isVisible():
        return False
    return all(table.columnWidth(c) >= table.sizeHintForColumn(c)
               for c in range(table.columnCount()))


def test_layout_toggle_only_for_plots_with_layout(gui, qtbot):
    panel = gui.plot_windows[0].panel
    assert panel.template == "beta"
    assert not panel.layout_check.isHidden()

    panel.set_template("floor_plan")  # no lattice layout for a floor plan
    wait_idle(qtbot, gui.client)
    assert panel.layout_check.isHidden()

    panel.set_template("lat_layout")  # is the layout: no second strip under it
    wait_idle(qtbot, gui.client)
    assert panel.layout_check.isHidden() and len(panel.figure.axes) == 1

    panel.set_template("beta")
    wait_idle(qtbot, gui.client)
    assert not panel.layout_check.isHidden()

    # Unticked, the toggle stays (so the layout can be turned back on).
    panel.layout_check.setChecked(False)
    wait_idle(qtbot, gui.client)
    assert not panel.layout_check.isHidden() and len(panel.figure.axes) == 1


def test_floor_plan_window_is_trimmed_to_fit(gui, qtbot):
    window = gui.plot_windows[0]
    panel = window.panel
    window.resize(780, 600)
    qtbot.wait(50)
    panel.set_template("floor_plan")  # equal aspect: the plot can't use the full width
    wait_idle(qtbot, gui.client)
    qtbot.wait(50)
    assert window.width() < 700
    # No blank bands beyond the slack, unless the plot bar needs the width.
    panel.canvas.draw()
    ax = panel.figure.axes[0]
    spare = (ax.get_position(original=True).width - ax.get_position().width) * panel.canvas.width()
    bar_limited = panel.width() <= panel._bar.sizeHint().width() + 4
    assert spare <= 2 * plots.ASPECT_SLACK or bar_limited
    assert panel.toolbar.width() >= panel.toolbar.sizeHint().width()  # all buttons showing

    # Only done when the template is first drawn: a size the user picks is kept.
    window.resize(760, 600)
    gui.act_refresh.trigger()
    wait_idle(qtbot, gui.client)
    assert window.width() == 760
    panel.set_template("beta")  # beta is not fixed-aspect: no trimming
    wait_idle(qtbot, gui.client)
    assert window.width() == 760


def test_floor_plan_click_opens_element_window(gui, qtbot):
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest

    window = gui.plot_windows[0]
    panel = window.panel
    window.resize(700, 600)
    panel.set_template("floor_plan")
    wait_idle(qtbot, gui.client)
    qtbot.wait(50)
    panel.canvas.draw()
    hits = panel._floor_hits[0]
    k = [tuple(i) for i in hits.ids].index((0, QF))
    x, y = hits.ax.transData.transform((hits.p1[k] + hits.p2[k]) / 2)
    assert hits.element_at(x, y) == (0, QF)
    assert hits.element_at(x + 200, y + 200) is None  # empty space inside the ring

    # A real mouse click at the element (Qt's y runs down; matplotlib's runs up).
    ratio = panel.canvas.devicePixelRatioF()
    QTest.mouseClick(panel.canvas, Qt.LeftButton,
                     pos=QPoint(round(x / ratio), round(panel.canvas.height() - y / ratio)))
    element = gui.parameter_windows[("ele", f"0>>{QF}")]
    wait_idle(qtbot, gui.client)
    assert element.isVisible()
    assert element.windowTitle() == "Element: QF"
    assert "Quadrupole" in element.header.text()
    assert gui.lattice.selected_ix == QF and gui.selected.ix == QF

    # Attributes are editable, as in the Lattice window.
    rows = {element.table.item(r, 0).text(): r for r in range(element.table.rowCount())}
    element.table.item(rows["K1"], 1).setText("0.32")
    wait_idle(qtbot, gui.client)
    k1 = run_sync(qtbot, gui.client, lambda t: t.ele_gen_attribs(f"0>>{QF}")["K1"])
    assert abs(k1 - 0.32) < 1e-12

    # In zoom mode a click does not select.
    element.close()
    panel.toolbar.zoom()
    QTest.mouseClick(panel.canvas, Qt.LeftButton,
                     pos=QPoint(round(x / ratio), round(panel.canvas.height() - y / ratio)))
    assert ("ele", f"0>>{QF}") not in gui.parameter_windows
    panel.toolbar.zoom()
