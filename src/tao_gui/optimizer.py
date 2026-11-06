"""Optimizer window: choose an optimizer, run it, and watch the merit."""

from __future__ import annotations

from typing import Any, Dict

from PySide6.QtCore import Signal
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .tao_worker import TaoClient

OPTIMIZERS = ("lm", "lmdif", "geodesic_lm", "svd", "de")


def fetch_status(tao) -> Dict[str, Any]:
    return {
        "merit": tao.merit(),
        "settings": tao.global_optimization(),
        "show_merit": tao.cmd("show merit", raises=False),
    }


class OptimizerWidget(QWidget):
    command_output = Signal(str, list)

    def __init__(self, client: TaoClient, parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self.running = False

        self.optimizer_combo = QComboBox()
        self.optimizer_combo.addItems(OPTIMIZERS)
        self.cycles_spin = QSpinBox(minimum=1, maximum=1_000_000, value=20)
        self.loops_spin = QSpinBox(minimum=1, maximum=10_000, value=1)
        self.merit_label = QLabel("—")
        font = self.merit_label.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        self.merit_label.setFont(font)

        self.run_button = QPushButton("Run optimizer")
        self.run_button.setDefault(True)
        self.run_button.clicked.connect(self.run)
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh)

        form = QFormLayout()
        form.addRow("Optimizer:", self.optimizer_combo)
        form.addRow("Cycles per loop (n_opti_cycles):", self.cycles_spin)
        form.addRow("Loops (n_opti_loops):", self.loops_spin)
        form.addRow("Merit:", self.merit_label)

        buttons = QHBoxLayout()
        buttons.addWidget(self.run_button)
        buttons.addWidget(refresh_button)
        buttons.addStretch(1)

        mono = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        self.merit_text = QPlainTextEdit(readOnly=True)
        self.merit_text.setFont(mono)
        self.merit_text.setLineWrapMode(QPlainTextEdit.NoWrap)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(buttons)
        layout.addWidget(QLabel("Largest merit contributions (show merit):"))
        layout.addWidget(self.merit_text, 1)

        client.state_changed.connect(self.refresh)
        client.started.connect(lambda _out: self.refresh(update_settings=True))

    def refresh(self, update_settings: bool = False) -> None:
        if not self.client.is_running:
            return
        self.client.call(fetch_status, on_done=lambda s: self._show(s, update_settings))

    def _show(self, status: Dict[str, Any], update_settings: bool) -> None:
        self.merit_label.setText(f"{status['merit']:.6g}")
        self.merit_text.setPlainText("\n".join(status["show_merit"]).strip("\n"))
        if update_settings:
            settings = status["settings"]
            name = str(settings.get("optimizer", "lm"))
            if self.optimizer_combo.findText(name) < 0:
                self.optimizer_combo.addItem(name)
            self.optimizer_combo.setCurrentText(name)
            self.cycles_spin.setValue(int(settings.get("n_opti_cycles", 20)))
            self.loops_spin.setValue(int(settings.get("n_opti_loops", 1)))

    def run(self) -> None:
        """Set the optimizer globals and run the optimizer."""
        if self.running or not self.client.is_running:
            return
        commands = [
            f"set global optimizer = {self.optimizer_combo.currentText()}",
            f"set global n_opti_cycles = {self.cycles_spin.value()}",
            f"set global n_opti_loops = {self.loops_spin.value()}",
            "run",
        ]
        self.running = True
        self.run_button.setEnabled(False)
        self.run_button.setText("Running…")

        def job(tao):
            out = []
            for command in commands:
                out.append((command, tao.cmd(command, raises=False)))
            return out

        self.client.call(job, on_done=self._on_run_done, on_error=self._on_run_error, modifies=True)

    def _on_run_done(self, results) -> None:
        for command, output in results:
            self.command_output.emit(command, output)
        self._finish()

    def _on_run_error(self, message: str) -> None:
        self.command_output.emit("run", [f"[ERROR] {message}"])
        self._finish()

    def _finish(self) -> None:
        self.running = False
        self.run_button.setEnabled(True)
        self.run_button.setText("Run optimizer")
