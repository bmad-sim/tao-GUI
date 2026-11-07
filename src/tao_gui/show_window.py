"""Show window: run any of Tao's ``show`` subcommands and read the output.

Pick a subcommand from the list (or type it), add arguments, and press Show.
The output stays in the window, and "Update automatically" re-runs the command
whenever Tao's state changes (after a set, change, optimizer run, …). "Help"
shows Tao's own help for the chosen subcommand.
"""

from __future__ import annotations

from typing import List

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .tao_worker import TaoClient

# Tao's "show <what>" names (tao_show_what_names in tao_command_names_mod.f90).
SUBCOMMANDS = (
    "alias", "attribute", "beam", "branch", "building_wall", "chromaticity", "constraints",
    "control", "curve", "data", "debug", "derivative", "dynamic_aperture", "element",
    "emittance", "field", "global", "graph", "history", "hom", "internal", "key_bindings",
    "lattice", "matrix", "merit", "normal_form", "optimizer", "orbit", "particle", "plot",
    "ptc", "radiation_integrals", "rampers", "spin", "string", "symbolic_numbers",
    "taylor_map", "top10", "track", "tune", "twiss_and_orbit", "universe", "use", "value",
    "variables", "version", "wake_elements", "wall", "wave",
)
# Subcommands whose argument is an element: "Use selected" fills it in.
ELEMENT_SUBCOMMANDS = ("element", "attribute", "field", "matrix", "taylor_map", "control")
HISTORY_KEY = "show/history"
MAX_HISTORY = 30


class ShowWidget(QWidget):
    command_output = Signal(str, list)

    def __init__(self, client: TaoClient, parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self.last_command = ""

        self.list = QListWidget()
        self.list.addItems(SUBCOMMANDS)
        self.list.currentTextChanged.connect(self._on_subcommand_chosen)
        self.list.itemDoubleClicked.connect(lambda _item: self.run())

        self.subcommand = QLabel()
        self.args = QComboBox(editable=True)
        self.args.setInsertPolicy(QComboBox.NoInsert)
        self.args.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.args.setMinimumContentsLength(24)
        self.args.lineEdit().setPlaceholderText("Arguments (optional), e.g. q1w -all")
        self.args.lineEdit().returnPressed.connect(self.run)
        self.args.textActivated.connect(self._on_history_chosen)
        self.use_selected = QPushButton("Use selected")
        self.use_selected.setToolTip("Use the element selected in the Lattice window or a plot")
        show = QPushButton("Show")
        show.setDefault(True)
        show.clicked.connect(self.run)
        help_button = QPushButton("Help")
        help_button.setToolTip("Tao's help for this subcommand")
        help_button.clicked.connect(self.show_help)
        self.auto = QCheckBox("Update automatically")
        self.auto.setToolTip("Re-run the command whenever Tao's state changes")

        line = QHBoxLayout()
        line.addWidget(QLabel("show"))
        line.addWidget(self.subcommand)
        line.addWidget(self.args, 1)
        line.addWidget(self.use_selected)
        line.addWidget(show)
        line.addWidget(help_button)
        options = QHBoxLayout()
        self.status = QLabel()
        options.addWidget(self.status, 1)
        options.addWidget(self.auto)

        self.output = QPlainTextEdit(readOnly=True)
        self.output.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.output.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.output.setPlaceholderText("Choose a subcommand on the left and press Show.")

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addLayout(line)
        right_layout.addLayout(options)
        right_layout.addWidget(self.output, 1)
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.list)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([160, 740])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(splitter)

        self._load_history()
        client.state_changed.connect(self._on_state_changed)
        self.list.setCurrentRow(SUBCOMMANDS.index("element"))

    # ------------------------------------------------------------------
    @property
    def current(self) -> str:
        return self.subcommand.text()

    def command(self) -> str:
        args = self.args.currentText().strip()
        return f"show {self.current} {args}".strip()

    def run(self) -> None:
        command = self.command()
        args = self.args.currentText().strip()
        self._remember(f"{self.current} {args}".strip())
        self.last_command = command
        self._run(command, echo=True)

    def show_help(self) -> None:
        self._run(f"help show {self.current}", echo=False)

    def set_argument(self, text: str) -> None:
        self.args.setCurrentText(text)

    def _run(self, command: str, echo: bool) -> None:
        if not self.client.is_running:
            self.status.setText("<i>Tao is not running</i>")
            return

        def done(out: list) -> None:
            scroll = self.output.verticalScrollBar().value()
            self.output.setPlainText("\n".join(out) if out else "(no output)")
            if command == self.last_command and not echo:
                self.output.verticalScrollBar().setValue(scroll)  # keep place on auto-update
            self.status.setText(f"<tt>{command}</tt>")
            if echo:
                self.command_output.emit(command, out)

        # "show" does not change Tao's state, so no state_changed (and no loop).
        self.client.cmd(command, on_done=done, modifies=False)

    def _on_state_changed(self) -> None:
        if self.auto.isChecked() and self.last_command and self.isVisible():
            self._run(self.last_command, echo=False)

    def _on_subcommand_chosen(self, name: str) -> None:
        self.subcommand.setText(name)
        self.use_selected.setEnabled(name in ELEMENT_SUBCOMMANDS)

    def choose(self, name: str) -> None:
        self.list.setCurrentRow(SUBCOMMANDS.index(name))

    # History ----------------------------------------------------------------
    def _on_history_chosen(self, text: str) -> None:
        sub, _, args = text.partition(" ")
        if sub in SUBCOMMANDS:
            self.choose(sub)
            self.args.setCurrentText(args)

    @staticmethod
    def history() -> List[str]:
        value = QSettings().value(HISTORY_KEY, [])
        if isinstance(value, str):
            value = [value]
        return [str(v) for v in value or []]

    def _load_history(self) -> None:
        text = self.args.currentText()
        self.args.blockSignals(True)
        self.args.clear()
        self.args.addItems(self.history())
        self.args.setCurrentText(text)
        self.args.blockSignals(False)

    def _remember(self, entry: str) -> None:
        history = [entry] + [h for h in self.history() if h != entry]
        QSettings().setValue(HISTORY_KEY, history[:MAX_HISTORY])
        self._load_history()
