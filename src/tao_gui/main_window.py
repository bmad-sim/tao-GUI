"""Main window: plot panels in the centre, lattice and console docks."""

from __future__ import annotations

import os
import shlex
from typing import List, Optional

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QSplitter,
)

from . import __version__
from .console import ConsoleWidget
from .lattice import LatticeWidget
from .plots import PlotPanel
from .tao_worker import TaoClient

DEFAULT_TEMPLATES = ("beta", "orbit")


class MainWindow(QMainWindow):
    def __init__(self, client: Optional[TaoClient] = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Tao GUI")
        self.client = client or TaoClient(self)
        self.templates: List[str] = []

        # Central plot area
        self.plot_splitter = QSplitter(Qt.Vertical)
        self.plot_panels: List[PlotPanel] = []
        for name in DEFAULT_TEMPLATES:
            self.add_plot_panel(name, closable=False)
        self.setCentralWidget(self.plot_splitter)

        # Docks
        self.lattice = LatticeWidget(self.client)
        self.lattice_dock = self._add_dock("Lattice", self.lattice, Qt.LeftDockWidgetArea)
        self.console = ConsoleWidget(self.client)
        self.console_dock = self._add_dock("Console", self.console, Qt.BottomDockWidgetArea)
        self.console.exit_requested.connect(self.close)
        self.lattice.command_output.connect(self._echo_command)

        # Status bar
        self.lattice_label = QLabel("Tao not started")
        self.busy_bar = QProgressBar()
        self.busy_bar.setRange(0, 0)
        self.busy_bar.setMaximumWidth(120)
        self.busy_bar.setVisible(False)
        self.statusBar().addWidget(self.lattice_label, 1)
        self.statusBar().addPermanentWidget(self.busy_bar)

        self._build_menus()

        self.client.busy_changed.connect(self._on_busy)
        self.client.started.connect(self._on_started)
        self.client.error.connect(self._on_error)

        self.resize(1400, 900)
        self.resizeDocks([self.lattice_dock], [430], Qt.Horizontal)
        self.resizeDocks([self.console_dock], [200], Qt.Vertical)
        settings = QSettings()
        if settings.contains("geometry"):
            self.restoreGeometry(settings.value("geometry"))
            self.restoreState(settings.value("state"))

    # ------------------------------------------------------------------
    def _add_dock(self, title: str, widget, area) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(f"{title.lower()}_dock")
        dock.setWidget(widget)
        self.addDockWidget(area, dock)
        return dock

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        open_action = QAction("&Open…", self, shortcut=QKeySequence.Open)
        open_action.setStatusTip("Start Tao with a tao.init or lattice file")
        open_action.triggered.connect(self.open_file_dialog)
        file_menu.addAction(open_action)
        reinit_action = QAction("&Reinitialize", self)
        reinit_action.triggered.connect(lambda: self.console.run_command("reinit tao"))
        file_menu.addAction(reinit_action)
        file_menu.addSeparator()
        quit_action = QAction("&Quit", self, shortcut=QKeySequence.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        view_menu = self.menuBar().addMenu("&View")
        add_plot = QAction("&Add plot panel", self, shortcut=QKeySequence("Ctrl+Shift+P"))
        add_plot.triggered.connect(lambda: self.add_plot_panel("", closable=True))
        view_menu.addAction(add_plot)
        refresh = QAction("Re&fresh", self, shortcut=QKeySequence.Refresh)
        refresh.triggered.connect(self.client.state_changed.emit)
        view_menu.addAction(refresh)
        view_menu.addSeparator()
        view_menu.addAction(self.lattice_dock.toggleViewAction())
        view_menu.addAction(self.console_dock.toggleViewAction())

        help_menu = self.menuBar().addMenu("&Help")
        about = QAction("&About Tao GUI", self)
        about.triggered.connect(self._about)
        help_menu.addAction(about)

    # ------------------------------------------------------------------
    def add_plot_panel(self, template: str = "", closable: bool = True) -> PlotPanel:
        panel = PlotPanel(self.client, template, closable=closable)
        panel.close_requested.connect(self._remove_plot_panel)
        if self.templates:
            panel.set_templates(self.templates)
        self.plot_panels.append(panel)
        self.plot_splitter.addWidget(panel)
        panel.refresh()
        return panel

    def _remove_plot_panel(self, panel: PlotPanel) -> None:
        self.plot_panels.remove(panel)
        panel.setParent(None)
        panel.deleteLater()

    # ------------------------------------------------------------------
    def start_tao(self, init: str) -> None:
        """Start (or restart) Tao with a Tao command-line string."""
        self.console.append(f"Starting Tao: {init}", bold=True)
        self.lattice_label.setText("Starting Tao…")
        for panel in self.plot_panels:
            panel.reset()
        self.client.start(init, on_error=self._on_start_failed)

    def open_file_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Tao init or lattice file", os.getcwd(),
            "Tao init (*.init);;Bmad lattice (*.bmad *.lat);;All files (*)",
        )
        if path:
            os.chdir(os.path.dirname(path))  # Tao resolves relative paths from the cwd
            flag = "-init" if path.endswith(".init") else "-lattice_file"
            self.start_tao(f"{flag} {shlex.quote(path)}")

    def _on_start_failed(self, message: str) -> None:
        self.lattice_label.setText("Tao failed to start")
        self.console.append(message, error=True)

    def _on_started(self, output: list) -> None:
        if output:
            self.console.append_lines(output)
        self.client.call(_session_info, on_done=self._on_session_info)

    def _on_session_info(self, info: dict) -> None:
        self.templates = info["templates"]
        for panel in self.plot_panels:
            panel.set_templates(self.templates)
            if panel.template and panel.template not in self.templates and self.templates:
                panel.set_template(self.templates[0])
        self.lattice_label.setText(info["lattice"])
        self.setWindowTitle(f"Tao GUI — {info['lattice']}")

    def _on_busy(self, busy: bool) -> None:
        self.busy_bar.setVisible(busy)

    def _on_error(self, message: str, tb: str) -> None:
        self.console.append(message, error=True)
        self.statusBar().showMessage(message, 8000)

    def _echo_command(self, command: str, output: list) -> None:
        self.console.append(f"Tao> {command}", bold=True)
        self.console.append_lines(output)

    def _about(self) -> None:
        QMessageBox.about(
            self, "About Tao GUI",
            f"<b>Tao GUI</b> {__version__}<br>A Qt frontend for Tao, built on PyTao.",
        )

    def closeEvent(self, event) -> None:
        settings = QSettings()
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("state", self.saveState())
        self.client.shutdown()
        super().closeEvent(event)


def _session_info(tao) -> dict:
    """Plot template names and lattice name (runs on the worker thread)."""
    templates = [str(t) for t in tao.plot_list("t") if t]  # dict: name -> index
    lattice = ""
    for line in tao.cmd("show universe", raises=False):
        if line.strip().startswith("Lattice name:"):
            lattice = line.split(":", 1)[1].strip().strip('"')
    return {"templates": templates, "lattice": lattice or "(unnamed lattice)"}
