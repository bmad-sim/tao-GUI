"""Change, Set and Single Mode windows."""

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from conftest import wait_idle
from test_app import QF, run_sync


def k1(qtbot, gui, ix=QF):
    return run_sync(qtbot, gui.client, lambda t: t.ele_gen_attribs(f"0>>{ix}")["K1"])


def var_model(qtbot, gui, name):
    return run_sync(qtbot, gui.client, lambda t: t.var(name)["model_value"])


# ----------------------------------------------------------------------
# Change


def test_change_element_modes(gui, qtbot):
    change = gui.change
    gui.section_actions["change"].trigger()
    assert gui.windows["change"].isVisible()
    change.set_element("qf")
    wait_idle(qtbot, gui.client)
    assert change.attribute.findText("K1") >= 0  # attributes of QF were listed
    change.attribute.setCurrentText("K1")

    change.value_edit.setText("0.01")  # "Add to the value"
    assert change.command() == "change element qf K1 0.01"
    change.change_button.click()
    wait_idle(qtbot, gui.client)
    assert abs(k1(qtbot, gui) - 0.31) < 1e-12
    assert "dMerit" in change.output.toPlainText()  # Tao's report is shown
    assert "Tao> change element qf K1 0.01" in gui.console.output.toPlainText()

    change.mode.setCurrentIndex(1)  # @: set
    change.value_edit.setText("0.25")
    assert change.command() == "change element qf K1 @0.25"
    change.apply()
    wait_idle(qtbot, gui.client)
    assert abs(k1(qtbot, gui) - 0.25) < 1e-12

    change.mode.setCurrentIndex(2)  # d: relative to design
    change.value_edit.setText("0.02")
    assert change.command() == "change element qf K1 d0.02"
    change.apply()
    wait_idle(qtbot, gui.client)
    assert abs(k1(qtbot, gui) - 0.32) < 1e-12

    change.mode.setCurrentIndex(3)  # %: percent
    change.value_edit.setText("50")
    assert change.command() == "change element qf K1 %50"
    change.apply()
    wait_idle(qtbot, gui.client)
    assert abs(k1(qtbot, gui) - 0.48) < 1e-7  # Tao computes "%" in single precision


def test_change_variable_and_tune_commands(gui, qtbot):
    change = gui.change
    change.what.setCurrentText("Variable")
    assert change.var_edit.findText("quad[*]") >= 0
    change.var_edit.setCurrentText("quad[1]")
    change.mode.setCurrentIndex(0)
    change.value_edit.setText("0.005")
    change.apply()
    wait_idle(qtbot, gui.client)
    assert abs(var_model(qtbot, gui, "quad[1]") - 0.305) < 1e-12

    change.what.setCurrentText("Tune")
    assert not change.amount.isVisibleTo(change)
    change.dqa.setText("0.01")
    change.mask_edit.setText("qd")
    # Switches must follow the subcommand ("change -mask ... tune" is rejected by Tao).
    assert change.command() == "change tune -mask qd 0.01 0"
    change.what.setCurrentText("Particle start")
    change.coordinate.setCurrentText("x")
    change.universe_edit.setText("1")
    change.value_edit.setText("0.001")
    assert change.command() == "change 1@particle_start x 0.001"


def test_change_uses_selected_element(gui, qtbot):
    gui.lattice.select_element(QF)
    gui._set_selected(gui.lattice.row_for(QF))
    gui.change.use_selected.click()
    wait_idle(qtbot, gui.client)
    # QF occurs once per cell, so the element is given by index, not name.
    assert gui.change.ele_edit.text() == f"0>>{QF}"


# ----------------------------------------------------------------------
# Set


def test_set_window_groups(gui, qtbot):
    window = gui.windows["set"]
    gui.section_actions["set"].trigger()
    wait_idle(qtbot, gui.client)
    widget = gui.set_widget
    table = widget.table
    assert widget.group.label == "Global"
    assert table.value_item("n_opti_cycles").text() == "20"

    table.value_item("n_opti_cycles").setText("33")  # editable: issues set global
    wait_idle(qtbot, gui.client)
    assert run_sync(qtbot, gui.client, lambda t: t.global_optimization()["n_opti_cycles"]) == 33
    assert "Done: <tt>set global n_opti_cycles = 33</tt>" in widget.status.text()

    widget.select_group("Bmad_com")
    wait_idle(qtbot, gui.client)
    d_orb = table.value_item("d_orb")
    assert len(d_orb.text().split()) == 6  # arrays shown space separated
    d_orb.setText("2e-05 2e-05 2e-05 2e-05 2e-05 2e-05")
    wait_idle(qtbot, gui.client)
    line = [l for l in run_sync(qtbot, gui.client, lambda t: t.cmd("pipe bmad_com"))
            if l.startswith("d_orb")][0]
    assert line.count("2E-05") == 6

    for label in ("Beam", "Beam_init", "Space_charge_com", "PTC_com", "Opti_de_param"):
        widget.select_group(label)
        wait_idle(qtbot, gui.client)
        assert table.params, label
    assert window.isVisible()


def test_set_window_free_form_line_and_history(gui, qtbot):
    widget = gui.set_widget
    gui.section_actions["set"].trigger()
    widget.subcommand.setCurrentText("element")
    widget.args.setCurrentText("qf k1 = 0.27")
    widget.run_line()
    wait_idle(qtbot, gui.client)
    assert abs(k1(qtbot, gui) - 0.27) < 1e-12
    assert widget.history()[0] == "element qf k1 = 0.27"

    widget.args.setCurrentText("qf not_an_attribute = 1")
    widget.run_line()
    wait_idle(qtbot, gui.client)
    assert "Tao rejected" in widget.status.text()

    widget._on_history_chosen("element qf k1 = 0.27")  # picking from the history fills both
    assert widget.subcommand.currentText() == "element"
    assert widget.args.currentText() == "qf k1 = 0.27"


# ----------------------------------------------------------------------
# Single mode


def test_single_mode_buttons_and_keys(gui, qtbot):
    window = gui.windows["single_mode"]
    sm = gui.single_mode
    gui.section_actions["single_mode"].trigger()
    wait_idle(qtbot, gui.client)
    assert [(v.key, v.name, v.attrib, v.key_delta) for v in sm.table_vars] == [
        (1, "quad[1]", "QF[K1]", 0.01), (2, "quad[2]", "QD[K1]", 0.02)]
    assert sm.table.item(0, 1).text() == "quad[1]"
    assert sm.table.item(2, 1).text() == ""  # key 3 is not bound

    sm.table.cellWidget(0, 8).click()  # "+1" for key 1
    wait_idle(qtbot, gui.client)
    assert abs(var_model(qtbot, gui, "quad[1]") - 0.31) < 1e-12

    sm.setFocus()
    QTest.keyClick(sm, "!")  # shift-1: +10 deltas
    wait_idle(qtbot, gui.client)
    assert abs(var_model(qtbot, gui, "quad[1]") - 0.41) < 1e-12
    QTest.keyClick(sm, "w")  # -1 delta of key 2
    wait_idle(qtbot, gui.client)
    assert abs(var_model(qtbot, gui, "quad[2]") - (-0.32)) < 1e-12
    QTest.keyClick(sm, "3")  # unbound key
    assert "not bound" in sm.message.text()

    QTest.keyClick(sm, Qt.Key_Up)  # all deltas x10
    wait_idle(qtbot, gui.client)
    assert [v.key_delta for v in sm.table_vars] == [0.1, 0.2]
    QTest.keyClick(sm, "<")  # all deltas /2
    wait_idle(qtbot, gui.client)
    assert [round(v.key_delta, 12) for v in sm.table_vars] == [0.05, 0.1]

    sm.save_values()
    QTest.keyClick(sm, "1")
    wait_idle(qtbot, gui.client)
    sm.restore_values()
    wait_idle(qtbot, gui.client)
    assert abs(var_model(qtbot, gui, "quad[1]") - 0.41) < 1e-12
    assert sm.n_banks == 1 and sm.bank == 0
    QTest.keyClick(sm, Qt.Key_Right)  # only one bank
    assert sm.bank == 0
    assert window.isVisible()


# ----------------------------------------------------------------------
# Show


def test_show_window(gui, qtbot):
    show = gui.show_widget
    gui.section_actions["show"].trigger()
    assert gui.windows["show"].isVisible()
    assert show.list.count() == 49 and show.current == "element"

    show.set_argument("qf")
    show.run()
    wait_idle(qtbot, gui.client)
    assert "Quadrupole" in show.output.toPlainText()
    assert "Tao> show element qf" in gui.console.output.toPlainText()
    assert show.history()[0] == "element qf"

    show.choose("merit")  # no arguments needed
    show.set_argument("")
    show.run()
    wait_idle(qtbot, gui.client)
    before = show.output.toPlainText()
    assert "Merit" in before or "merit" in before

    # Update automatically: the shown merit follows a change to the lattice.
    show.auto.setChecked(True)
    gui.console.run_command("set ele qf k1 = 0.33")
    wait_idle(qtbot, gui.client)
    assert show.output.toPlainText() != before

    show.show_help()
    wait_idle(qtbot, gui.client)
    assert "show merit" in show.output.toPlainText().lower()

    show._on_history_chosen("element qf")  # picking from the history fills both
    assert show.current == "element" and show.args.currentText() == "qf"


def test_show_uses_selected_element(gui, qtbot):
    gui._set_selected(gui.lattice.row_for(QF))
    gui.show_widget.choose("element")
    gui.show_widget.use_selected.click()
    assert gui.show_widget.args.currentText() == f"0>>{QF}"  # QF's name is not unique
    gui.show_widget.choose("merit")
    assert not gui.show_widget.use_selected.isEnabled()


# ----------------------------------------------------------------------
# Shapes


def test_parse_offsets():
    from tao_gui.shapes_window import parse_offsets

    lines = ['ele_shape(1) =    "fork::*"     "circle"   "red"   0.1  "name"   T  F  1   0.0',
             'ele_shape(12) =   "q*"          "box"      "blue"  0.3  "none"   T  T  2  -0.25',
             'Shape label text size scales as:']
    assert parse_offsets(lines) == {1: 0.0, 12: -0.25}


def test_shapes_window_edit_add_move_delete(gui, qtbot):
    from tao_gui.shapes_window import ShapesWidget

    widget = gui.shapes
    gui.section_actions["shapes"].trigger()
    wait_idle(qtbot, gui.client)
    assert widget.who == "floor_plan"
    table = widget.table

    def tao_shapes(who):
        return run_sync(qtbot, gui.client, lambda t: t.shape_list(who))

    n = len(tao_shapes("floor_plan"))
    assert table.rowCount() == n and n > 0
    color = ShapesWidget.column("color")

    # Edit a cell -> set floor_plan ele_shape(1) = ...
    table.item(0, color).setText("green")
    wait_idle(qtbot, gui.client)
    assert tao_shapes("floor_plan")[0]["color"] == "green"
    assert table.item(0, color).text() == "green"

    # Offset is kept (pipe shape_list does not report it)
    table.item(0, ShapesWidget.column("offset")).setText("0.5")
    wait_idle(qtbot, gui.client)
    assert widget.shapes[0].offset == 0.5
    table.item(0, ShapesWidget.column("draw")).setCheckState(Qt.Unchecked)
    wait_idle(qtbot, gui.client)
    first = tao_shapes("floor_plan")[0]
    assert first["shape_draw"] is False and first["color"] == "green"
    assert widget.shapes[0].offset == 0.5

    # Add below the first shape
    table.selectRow(0)
    widget.new_id.setText("quadrupole::qf")
    widget.add_shape()
    wait_idle(qtbot, gui.client)
    shapes = tao_shapes("floor_plan")
    assert len(shapes) == n + 1 and shapes[1]["ele_name"] == "quadrupole::qf"
    assert widget.selected_row() == 1

    # Move it up, then delete it
    widget.move_shape(-1)
    wait_idle(qtbot, gui.client)
    shapes = tao_shapes("floor_plan")
    assert shapes[0]["ele_name"] == "quadrupole::qf" and shapes[1]["color"] == "green"
    assert widget.selected_row() == 0
    assert widget.shapes[1].offset == 0.5  # moved shape keeps its offset
    widget.delete_shape()
    wait_idle(qtbot, gui.client)
    shapes = tao_shapes("floor_plan")
    assert len(shapes) == n and shapes[0]["color"] == "green"

    # A bad value is reported
    table.item(0, ShapesWidget.column("shape")).setText("not_a_shape")
    wait_idle(qtbot, gui.client)
    assert "Tao rejected" in widget.status.text()

    # The lattice layout has its own list
    widget.select_drawing("lat_layout")
    wait_idle(qtbot, gui.client)
    assert table.rowCount() == len(tao_shapes("lat_layout"))
    assert widget.shapes[0].color != "green"
