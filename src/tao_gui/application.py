"""The application controller: owns the Tao client, all windows and the menus."""

from __future__ import annotations

import os
import shlex
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, QRect, QSettings, Qt
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMenuBar,
    QMessageBox,
    QProgressBar,
    QToolBar,
)

from . import __version__
from .console import CallFileBox, ConsoleWidget, MainWidget
from .details import ElementWindow, ParameterWindow
from .lattice import ElementRow, LatticeWidget
from .optimizer import OptimizerWidget
from .plots import PlotPanel
from .startup import StartupOptions, StartupWindow
from .tables import DataWidget, VariablesWidget
from .tao_worker import TaoClient
from .windows import PlotWindow, SectionWindow

DEFAULT_TEMPLATES = ("beta", "orbit")

# key, title, window-menu shortcut
SECTIONS = (
    ("console", "Main", "Ctrl+1"),  # key kept as "console" for saved window settings
    ("lattice", "Lattice", "Ctrl+2"),
    ("data", "Data", "Ctrl+3"),
    ("variables", "Variables", "Ctrl+4"),
    ("optimizer", "Optimizer", "Ctrl+5"),
)


class TaoGui(QObject):
    """Creates the windows and wires them together.

    Each section (console, lattice, data, variables, optimizer, and every plot)
    is a separate top-level window. They share one ``TaoClient``, one set of
    menu actions, the element selection, and (optionally) the s-axis zoom.
    """

    def __init__(self, client: Optional[TaoClient] = None, restore: bool = True) -> None:
        super().__init__()
        self.client = client or TaoClient(self)
        self.restore = restore
        self.plotting = True
        self.windows_shown = False
        self.startup_options: Optional[StartupOptions] = None
        self._pending_startup: Optional[StartupOptions] = None
        self.templates: List[str] = []
        self.lattice_name = ""
        self.closing = False
        self.selected: Optional[ElementRow] = None
        self.plot_windows: List[PlotWindow] = []
        self.parameter_windows: Dict[tuple, ParameterWindow] = {}  # (kind, name) -> window
        self._plot_counter = 0

        # Section widgets
        self.console = ConsoleWidget(self.client)
        self.call_box = CallFileBox(self.console)
        self.lattice = LatticeWidget(self.client)
        self.data = DataWidget(self.client)
        self.variables = VariablesWidget(self.client)
        self.optimizer = OptimizerWidget(self.client)
        widgets = {
            "console": MainWidget(self.call_box, self.console),
            "lattice": self.lattice,
            "data": self.data,
            "variables": self.variables,
            "optimizer": self.optimizer,
        }

        self._create_actions()

        self.windows: Dict[str, SectionWindow] = {}
        for key, title, _shortcut in SECTIONS:
            self.windows[key] = SectionWindow(self, key, title, widgets[key])
        self._setup_console_window()

        # Wiring
        self.console.exit_requested.connect(self.quit)
        for widget in (self.lattice, self.data, self.variables, self.optimizer):
            widget.command_output.connect(self._echo_command)
        self.data.details_requested.connect(self.show_parameters)
        self.variables.details_requested.connect(self.show_parameters)
        self.lattice.element_selected.connect(self._on_lattice_selection)
        self.lattice.rows_loaded.connect(self._reapply_selection)
        self.client.busy_changed.connect(self.busy_bar.setVisible)
        self.client.started.connect(self._on_started)
        self.client.error.connect(self._on_error)

        # Startup window (shown alone when there is nothing to start Tao with)
        self.startup = StartupWindow()
        self.startup.start_requested.connect(self._start_from_options)
        self.startup.cancelled.connect(self._on_startup_cancelled)

    # ------------------------------------------------------------------
    # Actions and menus
    def _action(self, text: str, slot, shortcut=None, tip: str = "", checkable=False) -> QAction:
        action = QAction(text, self)
        if shortcut is not None:
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.ApplicationShortcut)
        if tip:
            action.setStatusTip(tip)
        action.setCheckable(checkable)
        action.triggered.connect(slot)
        return action

    def _create_actions(self) -> None:
        a = self._action
        self.act_open = a("&Open…", self.show_startup, QKeySequence.Open,
                          "Choose the files and options to (re)start Tao with")
        self.act_reinit = a("&Reinitialize Tao", lambda: self.console.run_command("reinit tao"))
        self.act_write_lattice = a("&Write Lattice…", self.write_lattice_dialog,
                                   tip="Write the model lattice as a Bmad file")
        self.act_quit = a("&Quit", self.quit, QKeySequence.Quit)

        self.act_run = a("&Run Optimizer", self.run_optimizer, "Ctrl+R")
        self.act_command = a("&Command Line", self.focus_console, "Ctrl+L")

        self.act_new_plot = a("&New Plot Window", lambda: self.add_plot_window("").show_and_raise(),
                              "Ctrl+Shift+N")
        self.act_link_zoom = a("&Link s-Axis Zoom", self._on_link_toggled, checkable=True,
                               tip="Zooming one s-based plot zooms all of them")
        self.act_link_zoom.setChecked(True)
        self.act_reset_zoom = a("Reset &Zoom", self.reset_zoom, "Ctrl+0")
        self.act_refresh = a("Re&fresh All", self.client.state_changed.emit, "F5")

        self.section_actions: Dict[str, QAction] = {}
        for key, title, shortcut in SECTIONS:
            self.section_actions[key] = a(title, lambda _=False, k=key: self.show_section(k), shortcut)
        self.act_tile = a("&Tile Windows", self.tile_windows)
        self.act_show_all = a("&Show All Windows", self.show_all)

        self.act_about = a("&About Tao GUI", self.about)

    def build_menus(self, bar: QMenuBar) -> None:
        """Fill a window's menu bar. Every window gets the same menus."""
        file_menu = bar.addMenu("&File")
        file_menu.addActions([self.act_open, self.act_reinit, self.act_write_lattice])
        file_menu.addSeparator()
        file_menu.addAction(self.act_quit)

        tao_menu = bar.addMenu("&Tao")
        tao_menu.addActions([self.act_run, self.act_command])

        plot_menu = bar.addMenu("&Plot")
        plot_menu.addAction(self.act_new_plot)
        plot_menu.addSeparator()
        plot_menu.addActions([self.act_link_zoom, self.act_reset_zoom, self.act_refresh])

        window_menu = bar.addMenu("&Window")
        window_menu.aboutToShow.connect(lambda m=window_menu: self._fill_window_menu(m))
        self._fill_window_menu(window_menu)

        help_menu = bar.addMenu("&Help")
        help_menu.addAction(self.act_about)

    def _fill_window_menu(self, menu) -> None:
        menu.clear()
        for key, _title, _shortcut in SECTIONS:
            menu.addAction(self.section_actions[key])
        if self.plot_windows:
            menu.addSeparator()
            for window in self.plot_windows:
                action = menu.addAction(window.windowTitle())
                action.triggered.connect(window.show_and_raise)
        if self.parameter_windows:
            menu.addSeparator()
            for window in self.parameter_windows.values():
                action = menu.addAction(window.windowTitle())
                action.triggered.connect(window.show_and_raise)
        menu.addSeparator()
        menu.addActions([self.act_tile, self.act_show_all])

    def _setup_console_window(self) -> None:
        """The Main window: toolbar, command-file box, console and status bar."""
        window = self.windows["console"]
        toolbar = QToolBar("Windows")
        toolbar.setObjectName("windows_toolbar")
        toolbar.setMovable(False)
        for key in ("lattice", "data", "variables", "optimizer"):
            toolbar.addAction(self.section_actions[key])
        toolbar.addSeparator()
        toolbar.addAction(self.act_new_plot)
        toolbar.addAction(self.act_run)
        window.addToolBar(toolbar)

        self.lattice_label = QLabel("Tao not started")
        self.busy_bar = QProgressBar()
        self.busy_bar.setRange(0, 0)
        self.busy_bar.setMaximumWidth(120)
        self.busy_bar.setVisible(False)
        window.statusBar().addWidget(self.lattice_label, 1)
        window.statusBar().addPermanentWidget(self.busy_bar)

    # ------------------------------------------------------------------
    # Windows
    def show_section(self, key: str) -> None:
        self.windows[key].show_and_raise()

    def show_all(self) -> None:
        for window in list(self.windows.values()) + self.plot_windows:
            window.show_and_raise()

    def focus_console(self) -> None:
        self.show_section("console")
        self.console.input.setFocus()

    def add_plot_window(self, template: str) -> PlotWindow:
        self._plot_counter += 1
        panel = PlotPanel(self.client, template)
        window = PlotWindow(self, f"plot{self._plot_counter}", panel)
        window.set_lattice_name(self.lattice_name)
        if self.templates:
            panel.set_templates(self.templates)
        panel.s_clicked.connect(self._on_plot_click)
        panel.element_clicked.connect(self._on_floor_plan_click)
        panel.s_range_changed.connect(lambda r, p=panel: self._on_s_range_changed(p, r))
        if self.selected is not None:
            panel.selection = (self.selected.s - self.selected.length, self.selected.s)
        if self.act_link_zoom.isChecked():
            panel.user_s_range = self._linked_range()
        self.plot_windows.append(window)
        window.resize(900, 480)
        panel.refresh()
        return window

    def remove_plot_window(self, window: PlotWindow) -> None:
        if window in self.plot_windows:
            self.plot_windows.remove(window)
        window.deleteLater()

    def show_parameters(self, kind: str, name: str) -> ParameterWindow:
        """Open (or raise) the parameter window of a datum or variable."""
        window = self.parameter_windows.get((kind, name))
        if window is None:
            window = ParameterWindow(self, self.client, kind, name)
            window.command_output.connect(self._echo_command)
            self.parameter_windows[(kind, name)] = window
        window.show_and_raise()
        return window

    def show_element(self, branch: int, index: int) -> ElementWindow:
        """Open (or raise) the attribute window of a lattice element."""
        key = ("ele", f"{branch}>>{index}")
        window = self.parameter_windows.get(key)
        if window is None:
            window = ElementWindow(self, self.client, branch, index)
            window.command_output.connect(self._echo_command)
            self.parameter_windows[key] = window
        window.show_and_raise()
        return window

    def _on_floor_plan_click(self, branch: int, index: int, open_window: bool) -> None:
        """Clicking a floor-plan element selects it everywhere; shift-click also
        opens its attribute window."""
        row = self.lattice.row_for(index) if branch == self.lattice.branch else None
        if row is not None:  # lords etc. are not in the Lattice window's table
            self.lattice.select_element(index)
            self._set_selected(row)
        if open_window:
            self.show_element(branch, index)

    def remove_parameter_window(self, window: ParameterWindow) -> None:
        self.parameter_windows.pop((window.kind, window.name), None)
        window.deleteLater()

    @property
    def plot_panels(self) -> List[PlotPanel]:
        return [w.panel for w in self.plot_windows]

    def tile_windows(self) -> None:
        """Lay the visible windows out on the primary screen."""
        screen = QGuiApplication.primaryScreen()
        area = screen.availableGeometry() if screen else QRect(0, 0, 1600, 1000)
        x, y, w, h = area.x(), area.y(), area.width(), area.height()
        left_w = int(w * 0.3)
        bottom_h = int(h * 0.28)
        self.windows["lattice"].setGeometry(x, y, left_w, h)
        self.windows["console"].setGeometry(x + left_w, y + h - bottom_h, w - left_w, bottom_h)
        plots = [p for p in self.plot_windows if p.isVisible()] or self.plot_windows
        if plots:
            each = (h - bottom_h) // len(plots)
            for i, window in enumerate(plots):
                window.setGeometry(x + left_w, y + i * each, w - left_w, each)
        for i, key in enumerate(("data", "variables", "optimizer")):
            self.windows[key].setGeometry(x + left_w // 2 + 40 * i, y + 60 + 40 * i,
                                          min(1000, w - left_w), int(h * 0.55))

    # ------------------------------------------------------------------
    # Persistence
    def show_windows(self) -> None:
        """Create the plot windows and show the section windows (once)."""
        if self.windows_shown:
            return
        self.windows_shown = True
        restore = self.restore
        settings = QSettings()
        if self.plotting:
            self._add_default_plots(settings.value("plots/templates") if restore else None)

        restored = False
        if restore and settings.contains("windows/console/geometry"):
            for key, window in self.windows.items():
                geometry = settings.value(f"windows/{key}/geometry")
                if geometry is not None:
                    window.restoreGeometry(geometry)
            for i, window in enumerate(self.plot_windows):
                geometry = settings.value(f"plots/{i}/geometry")
                if geometry is not None:
                    window.restoreGeometry(geometry)
            restored = True
            self.act_link_zoom.setChecked(settings.value("plots/link_zoom", True, type=bool))
        if not restored:
            self.tile_windows()

        visible = settings.value("windows/visible") if restored else None
        if isinstance(visible, str):
            visible = [visible]
        for key in visible or ("lattice",):
            if key in self.windows and key != "console":
                self.windows[key].show()
        for window in self.plot_windows:
            window.show()
        # The Main window last, so it starts on top of the others.
        self.windows["console"].show_and_raise()

    def _add_default_plots(self, templates=None) -> None:
        if isinstance(templates, str):
            templates = [templates]
        for template in templates or DEFAULT_TEMPLATES:
            self.add_plot_window(template)

    def set_plotting(self, on: bool) -> None:
        """Turn plot windows on or off (the "Plotting" startup option)."""
        self.plotting = on
        for action in (self.act_new_plot, self.act_link_zoom, self.act_reset_zoom):
            action.setEnabled(on)
        if not on:
            for window in list(self.plot_windows):
                window.close()
        elif self.windows_shown and not self.plot_windows:
            self._add_default_plots()
            for window in self.plot_windows:
                window.show()

    def save_window(self, window: SectionWindow) -> None:
        QSettings().setValue(f"windows/{window.key}/geometry", window.saveGeometry())

    def save_settings(self) -> None:
        settings = QSettings()
        for key, window in self.windows.items():
            settings.setValue(f"windows/{key}/geometry", window.saveGeometry())
        settings.setValue("windows/visible", [k for k, w in self.windows.items() if w.isVisible()])
        if self.plotting:  # keep the saved plots when this session had plotting off
            settings.setValue("plots/templates", [p.template for p in self.plot_panels if p.template])
        for i, window in enumerate(w for w in self.plot_windows if w.panel.template):
            settings.setValue(f"plots/{i}/geometry", window.saveGeometry())
        settings.setValue("plots/link_zoom", self.act_link_zoom.isChecked())

    def shutdown(self, save: bool = True) -> None:
        """Save the layout, close every window and stop the Tao thread."""
        if self.closing:
            return
        if save:
            self.save_settings()
        self.closing = True
        self.startup.blockSignals(True)
        self.startup.close()
        for window in (list(self.windows.values()) + self.plot_windows
                       + list(self.parameter_windows.values())):
            window.close()
        self.client.shutdown()

    def quit(self) -> None:
        self.shutdown()
        QApplication.quit()

    # ------------------------------------------------------------------
    # Tao lifecycle
    def launch(self, init: str, plotting: bool = True) -> None:
        """Show the windows and start Tao (used when the command line says what to run)."""
        self.set_plotting(plotting)
        self.show_windows()
        self.start_tao(init)

    def start_tao(self, init: str) -> None:
        """Start (or restart) Tao with a Tao command-line string."""
        self.console.append(f"Starting Tao: {init}", bold=True)
        self.lattice_label.setText("Starting Tao…")
        for panel in self.plot_panels:
            panel.reset()
        self.client.start(init, on_error=self._on_start_failed)

    def show_startup(self) -> None:
        """Show the startup window (alone on first start; File > Open later)."""
        if self.startup_options is not None:
            self.startup.set_options(self.startup_options)
        self.startup.set_tao_running(self.client.is_running)
        self.startup.show()
        self.startup.raise_()
        self.startup.activateWindow()

    def _start_from_options(self, opts: StartupOptions) -> None:
        if opts.directory:
            os.chdir(opts.directory)  # Tao resolves relative paths from the cwd
        self._pending_startup = opts
        self.console.append(f"Starting Tao: {opts.tao_command()}", bold=True)
        self.lattice_label.setText("Starting Tao…")
        for panel in self.plot_panels:
            panel.reset()
        self.client.start(opts.tao_command(), on_error=self._on_startup_failed)
        # Explicit On/Off choices override the init file (see startup.py).
        commands = opts.set_commands()
        if commands:
            def apply(tao):
                return [(c, tao.cmd(c, raises=False)) for c in commands]

            def echo(results):
                for command, output in results:
                    self._echo_command(command, output)

            # Queued behind the start; fails harmlessly (TaoNotStarted) if the start fails.
            self.client.call(apply, on_done=echo, on_error=lambda _msg: None, modifies=True)

    def _on_startup_failed(self, message: str) -> None:
        self._pending_startup = None
        self.console.append(message, error=True)
        self.lattice_label.setText("Tao failed to start" if not self.client.is_running
                                   else self.lattice_name)
        self.startup.show_error(message)

    def _on_startup_cancelled(self) -> None:
        if not self.windows_shown and not self.client.is_running:
            self.quit()  # nothing else is open

    def write_lattice_dialog(self) -> None:
        if not self.client.is_running:
            return
        path, _ = QFileDialog.getSaveFileName(
            self.windows["console"], "Write lattice", os.path.join(os.getcwd(), "lat.bmad"),
            "Bmad lattice (*.bmad);;All files (*)",
        )
        if path:
            self.console.run_command(f"write bmad {shlex.quote(path)}")

    def run_optimizer(self) -> None:
        self.show_section("optimizer")
        self.optimizer.run()

    def _on_start_failed(self, message: str) -> None:
        self.lattice_label.setText("Tao failed to start")
        self.console.append(message, error=True)

    def _on_started(self, output: list) -> None:
        opts, self._pending_startup = self._pending_startup, None
        if opts is not None:
            self.startup_options = opts
            self.startup.accept_started()
            self.set_plotting(opts.effective("plotting"))
            self.show_windows()
        if output:
            self.console.append_lines(output)
        self.selected = None
        self.client.call(_session_info, on_done=self._on_session_info)

    def _on_session_info(self, info: dict) -> None:
        self.templates = info["templates"]
        self.lattice_name = info["lattice"]
        for panel in self.plot_panels:
            panel.set_templates(self.templates)
            if panel.template and panel.template not in self.templates and self.templates:
                panel.set_template(self.templates[0])
        self.lattice_label.setText(self.lattice_name)
        for window in list(self.windows.values()) + self.plot_windows:
            window.set_lattice_name(self.lattice_name)

    def _on_error(self, message: str, tb: str) -> None:
        self.console.append(message, error=True)
        self.windows["console"].statusBar().showMessage(message, 8000)

    def _echo_command(self, command: str, output: list) -> None:
        self.console.append(f"Tao> {command}", bold=True)
        self.console.append_lines(output)

    # ------------------------------------------------------------------
    # Selection and linked zoom
    def _on_lattice_selection(self, _branch: int, ix: int) -> None:
        self._set_selected(self.lattice.row_for(ix))

    def _on_plot_click(self, s: float, open_window: bool = False) -> None:
        """Clicking an s-plot selects the element at s; shift-clicking a lattice
        layout also opens its attribute window."""
        row = self.lattice.element_at(s)
        if row is None:
            return
        self.lattice.select_element(row.ix)
        self._set_selected(row)
        if open_window:
            self.show_element(self.lattice.branch, row.ix)

    def _reapply_selection(self) -> None:
        if self.selected is not None:
            self._set_selected(self.lattice.row_for(self.selected.ix))

    def _set_selected(self, row: Optional[ElementRow]) -> None:
        self.selected = row
        s_range = None if row is None else (row.s - row.length, row.s)
        for panel in self.plot_panels:
            panel.set_selection(s_range)
        if row is not None:
            self.windows["console"].statusBar().showMessage(
                f"Selected {row.name} ({row.key}) at s = {row.s:.4f} m", 5000)

    def _linked_range(self):
        for panel in self.plot_panels:
            if panel.is_s_plot and panel.user_s_range is not None:
                return panel.user_s_range
        return None

    def _on_s_range_changed(self, source: PlotPanel, s_range) -> None:
        if not self.act_link_zoom.isChecked():
            return
        for panel in self.plot_panels:
            if panel is not source:
                panel.set_s_range(s_range)

    def _on_link_toggled(self, on: bool) -> None:
        if on:
            s_range = self._linked_range()
            if s_range is not None:
                for panel in self.plot_panels:
                    panel.set_s_range(s_range)

    def reset_zoom(self) -> None:
        for panel in self.plot_panels:
            panel.set_s_range(None)

    def about(self) -> None:
        QMessageBox.about(
            self.windows["console"], "About Tao GUI",
            f"<b>Tao GUI</b> {__version__}<br>A Qt frontend for Tao, built on PyTao.",
        )


def _session_info(tao) -> dict:
    """Plot template names and lattice name (runs on the worker thread)."""
    templates = [str(t) for t in tao.plot_list("t") if t]  # dict: name -> index
    lattice = ""
    for line in tao.cmd("show universe", raises=False):
        if line.strip().startswith("Lattice name:"):
            lattice = line.split(":", 1)[1].strip().strip('"')
    return {"templates": templates, "lattice": lattice or "(unnamed lattice)"}
