from conftest import wait_idle

N_ELEMENTS = 66  # BEGINNING + 8 cells * 8 elements + END


def run_sync(qtbot, client, fn):
    """Run ``fn(tao)`` on the worker and return its result."""
    box = {}
    client.call(fn, on_done=lambda r: box.setdefault("result", r))
    qtbot.waitUntil(lambda: "result" in box, timeout=30_000)
    return box["result"]


def test_startup(window):
    assert window.client.is_running
    assert len(window.lattice.model.rows) == N_ELEMENTS
    assert "beta" in window.templates
    for panel in window.plot_panels:
        assert panel.region is not None, panel.status.text()
        assert panel.figure.axes, "nothing drawn"


def test_console_command(window, qtbot):
    window.console.input.setText("show ele qf")
    window.console.input.returnPressed.emit()
    wait_idle(qtbot, window.client)
    text = window.console.output.toPlainText()
    assert "Tao> show ele qf" in text
    assert "Quadrupole" in text


def test_console_error_is_shown(window, qtbot):
    window.console.run_command("not_a_command")
    wait_idle(qtbot, window.client)
    assert "UNRECOGNIZED COMMAND" in window.console.output.toPlainText()


def test_filter(window):
    window.lattice.filter_edit.setText("q*")
    assert window.lattice.proxy.rowCount() == 16
    window.lattice.filter_edit.setText("sbend")  # matches the key column
    assert window.lattice.proxy.rowCount() == 16
    window.lattice.filter_edit.clear()
    assert window.lattice.proxy.rowCount() == N_ELEMENTS


def test_edit_attribute_updates_tao_and_plots(window, qtbot):
    lattice = window.lattice
    lattice.select_element(1)  # QF
    wait_idle(qtbot, window.client)
    names = [lattice.attributes.item(r, 0).text() for r in range(lattice.attributes.rowCount())]
    row = names.index("K1")

    beta_panel = window.plot_panels[0]
    before = beta_panel.figure.axes[0].lines[0].get_ydata().copy()

    lattice.attributes.item(row, 1).setText("0.35")
    wait_idle(qtbot, window.client)

    k1 = run_sync(qtbot, window.client, lambda t: t.ele_gen_attribs("0>>1")["K1"])
    assert abs(k1 - 0.35) < 1e-12
    after = beta_panel.figure.axes[0].lines[0].get_ydata()
    assert len(after) != len(before) or abs(after - before).max() > 1e-6
    assert "set ele 0>>1 K1 = 0.35" in window.console.output.toPlainText()


def test_change_template(window, qtbot):
    panel = window.plot_panels[1]
    panel.set_template("floor_plan")
    wait_idle(qtbot, window.client)
    assert panel.region is not None, panel.status.text()
    assert len(panel.figure.axes) == 1  # no lattice layout under a floor plan


def test_worker_error_reaches_callback(window, qtbot):
    errors = []

    def boom(tao):
        raise ValueError("boom")

    window.client.call(boom, on_error=errors.append)
    qtbot.waitUntil(lambda: bool(errors), timeout=10_000)
    assert errors == ["ValueError: boom"]
