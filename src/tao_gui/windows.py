"""Top-level windows. Every section of the GUI is its own detached window.

All windows get the same menu bar (built by ``TaoGui.build_menus`` from shared
actions). Closing the console window quits; closing a section window hides
it (reopen it from the Window menu); closing a plot window removes it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QMainWindow, QWidget

if TYPE_CHECKING:
    from .application import TaoGui


class SectionWindow(QMainWindow):
    def __init__(self, gui: "TaoGui", key: str, title: str, widget: QWidget) -> None:
        super().__init__()
        self.gui = gui
        self.key = key
        self.base_title = title
        self.setObjectName(f"{key}_window")
        self.setWindowTitle(title)
        self.setCentralWidget(widget)
        gui.build_menus(self.menuBar())

    def set_lattice_name(self, lattice: str) -> None:
        self.setWindowTitle(f"{self.base_title} — {lattice}" if lattice else self.base_title)

    def show_and_raise(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event) -> None:
        if self.gui.closing:
            event.accept()
        elif self.key == "console":
            event.accept()  # closing the console quits the GUI
            self.gui.quit()
        elif self.key.startswith("plot"):
            event.accept()
            self.gui.remove_plot_window(self)
        else:
            self.gui.save_window(self)
            event.accept()  # hides; reopen from the Window menu


class PlotWindow(SectionWindow):
    def __init__(self, gui: "TaoGui", key: str, panel) -> None:
        super().__init__(gui, key, "Plot", panel)
        self.panel = panel
        panel.template_changed.connect(lambda _name: self._retitle())
        self._retitle()

    def set_lattice_name(self, lattice: str) -> None:
        """Plot window titles show only the plot (lattice names are often blank)."""

    def _retitle(self) -> None:
        self.setWindowTitle(f"Plot: {self.panel.template or '(choose a template)'}")
