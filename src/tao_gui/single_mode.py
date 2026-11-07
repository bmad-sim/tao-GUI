"""Single mode window: Tao's key-bound variables, stepped with buttons or keys.

In Tao's single mode each keystroke changes a variable bound to a key
(``var(i)%key_bound`` and ``var(i)%key_delta`` in the init files, or
``set var <v>|key_bound = T``). The bound variables are in banks of ten:

    Variable        -10   -1   +1   +10
    1 + 10*bank      Q     q    1    !
    2 + 10*bank      W     w    2    @
    ...
    10 + 10*bank     P     p    0    )

This window shows the active bank as a table with buttons, and takes the same
keys while it has focus: the arrow keys change the bank (left/right) and scale
all deltas by 10 (up/down); "<" and ">" scale them by 2.

Each step sets the variable's model value directly, as Tao's single mode does
(``change var`` would also rebuild the optimizer's derivative matrix).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .details import parse_pipe_parameters
from .lattice import format_value
from .tao_worker import TaoClient

PLUS_ONE = "1234567890"
MINUS_ONE = "qwertyuiop"
PLUS_TEN = "!@#$%^&*()"
MINUS_TEN = "QWERTYUIOP"
FACTORS = (-10, -1, 1, 10)
KEYS_FOR_FACTOR = {-10: MINUS_TEN, -1: MINUS_ONE, 1: PLUS_ONE, 10: PLUS_TEN}
COLUMNS = ("Keys", "Variable", "Element[attribute]", "Model", "Saved", "Delta",
           "−10", "−1", "+1", "+10")
STEP_COLUMN = 6  # first of the four step-button columns


@dataclass
class BoundVar:
    key: int  # 1-based position in Tao's key table
    name: str  # e.g. "quad[1]"
    attrib: str  # e.g. "QF[K1]"
    model: float
    key_delta: float
    key_val0: float


def parse_key_bindings(lines: List[str]) -> List[tuple]:
    """(key index, variable name) from ``show key_bindings``."""
    out = []
    for line in lines:
        words = line.split()
        if len(words) >= 2 and words[0].isdigit():
            out.append((int(words[0]), words[1]))
    return out


def fetch_key_table(tao) -> List[BoundVar]:
    """The key-bound variables, in key order (worker thread)."""
    table = []
    for key, name in parse_key_bindings(tao.cmd("show key_bindings", raises=False)):
        values = {p.name: p.value for p in parse_pipe_parameters(tao.cmd(f"pipe var {name}"))}
        table.append(BoundVar(key, name, f"{values['ele_name']}[{values['attrib_name']}]",
                              values["model_value"], values["key_delta"], values["key_val0"]))
    return table


def step_variable(tao, name: str, factor: float) -> list:
    """model += factor * key_delta, read and written in one worker call."""
    values = {p.name: p.value for p in parse_pipe_parameters(tao.cmd(f"pipe var {name}"))}
    value = values["model_value"] + factor * values["key_delta"]
    return tao.cmd(f"set var {name}|model = {value!r}", raises=False)


class SingleModeWidget(QWidget):
    command_output = Signal(str, list)

    def __init__(self, client: TaoClient, parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self.table_vars: List[BoundVar] = []
        self.bank = 0
        self.saved: Dict[str, float] = {}  # values to restore; start as Tao's key_val0
        self.setFocusPolicy(Qt.StrongFocus)

        self.prev_bank = QPushButton("◀")
        self.next_bank = QPushButton("▶")
        self.prev_bank.clicked.connect(lambda: self.set_bank(self.bank - 1))
        self.next_bank.clicked.connect(lambda: self.set_bank(self.bank + 1))
        self.bank_label = QLabel()
        bank_row = QHBoxLayout()
        bank_row.addWidget(self.prev_bank)
        bank_row.addWidget(self.bank_label)
        bank_row.addWidget(self.next_bank)
        bank_row.addStretch(1)

        self.table = QTableWidget(10, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setFocusPolicy(Qt.NoFocus)  # keys go to this window
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)

        delta_row = QHBoxLayout()
        delta_row.addWidget(QLabel("All deltas:"))
        for label, factor, tip in (("÷10", 0.1, "Down arrow"), ("÷2", 0.5, '"<"'),
                                   ("×2", 2.0, '">"'), ("×10", 10.0, "Up arrow")):
            button = QPushButton(label)
            button.setToolTip(f"Key: {tip}")
            button.setFocusPolicy(Qt.NoFocus)
            button.clicked.connect(lambda _=False, f=factor: self.scale_deltas(f))
            delta_row.addWidget(button)
        delta_row.addStretch(1)
        save = QPushButton("Save values")
        save.setToolTip("Remember the current model values (the Saved column)")
        save.clicked.connect(self.save_values)
        restore = QPushButton("Restore saved")
        restore.setToolTip("Set every bound variable back to its Saved value")
        restore.clicked.connect(self.restore_values)
        for button in (save, restore, self.prev_bank, self.next_bank):
            button.setFocusPolicy(Qt.NoFocus)
        delta_row.addWidget(save)
        delta_row.addWidget(restore)

        self.message = QLabel()
        self.message.setWordWrap(True)
        help_text = QLabel(
            "Keys (click here first): <b>1</b>…<b>0</b> step up, <b>q</b>…<b>p</b> step down, "
            "with Shift ×10. <b>←</b>/<b>→</b> change bank, <b>↑</b>/<b>↓</b> deltas ×10/÷10, "
            "<b>&lt;</b>/<b>&gt;</b> deltas ÷2/×2.")
        help_text.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addLayout(bank_row)
        layout.addWidget(self.table, 1)
        layout.addLayout(delta_row)
        layout.addWidget(self.message)
        layout.addWidget(help_text)

        client.state_changed.connect(self.refresh)
        client.started.connect(lambda _out: self._reset())
        self._show_bank()

    # Data ------------------------------------------------------------------
    def _reset(self) -> None:
        self.saved = {}
        self.bank = 0
        self.refresh()

    def refresh(self) -> None:
        if not self.client.is_running or not self.isVisible():
            return
        self.client.call(fetch_key_table, on_done=self._set_table,
                         on_error=lambda msg: self.message.setText(f"<i>{msg}</i>"))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()
        self.setFocus()

    def _set_table(self, table: List[BoundVar]) -> None:
        self.table_vars = table
        for v in table:
            self.saved.setdefault(v.name, v.key_val0)
        self.bank = min(self.bank, self.n_banks - 1)
        self._show_bank()

    @property
    def n_banks(self) -> int:
        return max(1, -(-max((v.key for v in self.table_vars), default=0) // 10))

    def bound(self, key: int) -> Optional[BoundVar]:
        return next((v for v in self.table_vars if v.key == key), None)

    # Display -------------------------------------------------------------------
    def set_bank(self, bank: int) -> None:
        self.bank = max(0, min(bank, self.n_banks - 1))
        self._show_bank()

    def _show_bank(self) -> None:
        first = 10 * self.bank + 1
        self.bank_label.setText(f"Bank {self.bank}: keys {first}–{first + 9}")
        self.prev_bank.setEnabled(self.bank > 0)
        self.next_bank.setEnabled(self.bank < self.n_banks - 1)
        if not self.table_vars:
            self.message.setText("No variables are bound to keys. Bind one with "
                                 "<tt>set var &lt;name&gt;|key_bound = T</tt> (and key_delta), "
                                 "or in the init file.")
        elif not self.message.text().startswith("<span"):
            self.message.setText("")
        for row in range(10):
            v = self.bound(first + row)
            texts = [f"{PLUS_ONE[row]} {MINUS_ONE[row]}"]
            if v is None:
                texts += ["", "", "", "", ""]
            else:
                texts += [v.name, v.attrib, format_value(v.model),
                          format_value(self.saved.get(v.name, v.key_val0)),
                          format_value(v.key_delta)]
            for col, text in enumerate(texts):
                self.table.setItem(row, col, QTableWidgetItem(text))
            for k, factor in enumerate(FACTORS):
                col = STEP_COLUMN + k
                if v is None:
                    self.table.removeCellWidget(row, col)
                    continue
                button = QPushButton(f"{KEYS_FOR_FACTOR[factor][row]}")
                button.setToolTip(f"{'+' if factor > 0 else '−'}{abs(factor)} × delta "
                                  f"(key {KEYS_FOR_FACTOR[factor][row]})")
                button.setFocusPolicy(Qt.NoFocus)
                button.clicked.connect(lambda _=False, n=v.name, f=factor: self.step(n, f))
                self.table.setCellWidget(row, col, button)

    # Actions -------------------------------------------------------------------
    def step(self, name: str, factor: float) -> None:
        command = f"set var {name}|model = <model {'+' if factor > 0 else '-'} {abs(factor)} × key_delta>"
        self.client.call(lambda t: step_variable(t, name, factor),
                         on_done=lambda out: self._done(command, out), modifies=True)

    def step_key(self, row: int, factor: float) -> None:
        v = self.bound(10 * self.bank + row + 1)
        if v is None:
            self.message.setText(f"<span style='color:#c0392b'>Key {PLUS_ONE[row]} "
                                 f"is not bound to a variable in bank {self.bank}.</span>")
            return
        self.step(v.name, factor)

    def scale_deltas(self, factor: float) -> None:
        names = [(v.name, v.key_delta * factor) for v in self.table_vars]
        if not names:
            return

        def apply(tao):
            return [line for name, delta in names
                    for line in tao.cmd(f"set var {name}|key_delta = {delta!r}", raises=False)]

        self.client.call(apply, on_done=lambda out: self._done(
            f"set var …|key_delta (all bound variables ×{factor:g})", out), modifies=True)

    def save_values(self) -> None:
        self.saved = {v.name: v.model for v in self.table_vars}
        self._show_bank()

    def restore_values(self) -> None:
        values = [(v.name, self.saved.get(v.name, v.key_val0)) for v in self.table_vars]
        if not values:
            return

        def apply(tao):
            return [line for name, value in values
                    for line in tao.cmd(f"set var {name}|model = {value!r}", raises=False)]

        self.client.call(apply, on_done=lambda out: self._done(
            "set var …|model = saved (all bound variables)", out), modifies=True)

    def _done(self, command: str, out: list) -> None:
        self.command_output.emit(command, out)
        errors = [line for line in out if line.lstrip().startswith("[ERROR")]
        self.message.setText(f"<span style='color:#c0392b'>{' '.join(out).strip()}</span>"
                             if errors else "")

    # Keys ----------------------------------------------------------------------
    def keyPressEvent(self, event) -> None:
        key, text = event.key(), event.text()
        for factor, chars in KEYS_FOR_FACTOR.items():
            if text and text in chars:
                self.step_key(chars.index(text), factor)
                return
        if key == Qt.Key_Left:
            self.set_bank(self.bank - 1)
        elif key == Qt.Key_Right:
            self.set_bank(self.bank + 1)
        elif key == Qt.Key_Up:
            self.scale_deltas(10.0)
        elif key == Qt.Key_Down:
            self.scale_deltas(0.1)
        elif text == ">":
            self.scale_deltas(2.0)
        elif text == "<":
            self.scale_deltas(0.5)
        else:
            super().keyPressEvent(event)
