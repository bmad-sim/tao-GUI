"""Parameter windows for a single datum or variable.

Double-clicking a row in the Data or Variables window opens one of these. It
lists every parameter Tao reports for that datum or variable (``python data``
/ ``python var``). Parameters Tao marks as settable can be edited, which
issues ``set data <datum>|<name> = <value>`` or ``set var <var>|<name> = <value>``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, List

from PySide6.QtCore import QSettings, QSize, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .lattice import format_value
from .tao_worker import TaoClient

if TYPE_CHECKING:
    from .application import TaoGui

KIND_TITLES = {"data": "Datum", "var": "Variable"}
TWO_COLUMNS_KEY = "parameters/two_columns"  # QSettings: last choice, used for new windows
VALUE_PADDING = 24  # extra width for value columns, so edited values have room


@dataclass(frozen=True)
class Parameter:
    name: str  # as used in `set data ...|name` (Tao's "data^" style prefixes removed)
    type: str  # Tao pipe type: REAL, INT, LOGIC, STR, ENUM, ...
    settable: bool
    value: Any


def parse_pipe_parameters(lines: List[str]) -> List[Parameter]:
    """Parse ``name;TYPE;settable;value`` lines from ``python data`` / ``python var``."""
    params = []
    for line in lines:
        parts = line.split(";", 3)
        if len(parts) != 4:
            continue
        name, typ, settable, raw = parts
        name = name.split("^")[-1]  # "data^merit_type" -> "merit_type"
        raw = raw.strip()
        value: Any = raw
        if typ == "REAL":
            try:
                value = float(raw)
            except ValueError:
                pass
        elif typ in ("INT", "INUM"):
            try:
                value = int(raw)
            except ValueError:
                pass
        elif typ == "LOGIC":
            value = raw.upper().startswith("T")
        params.append(Parameter(name, typ, settable == "T", value))
    return params


def fetch_parameters(tao, kind: str, name: str) -> List[Parameter]:
    """Runs on the worker thread."""
    return parse_pipe_parameters(tao.cmd(f"python {kind} {name}"))


class ParameterTable(QTableWidget):
    """Parameter / value table in one or two column pairs; edits emit ``edited(name, text)``.

    With two pairs the parameters run down the left pair, then down the right one.
    """

    edited = Signal(str, str)

    def __init__(self, parent=None) -> None:
        super().__init__(0, 2, parent)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        # Compact rows; no grid, so the only rule is the one under the header.
        self.setShowGrid(False)
        self.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.verticalHeader().setDefaultSectionSize(self.fontMetrics().height() + 4)
        self.params: List[Parameter] = []
        self.pairs = 1
        self._loading = False
        self.itemChanged.connect(self._on_item_changed)
        self._setup_columns()

    def set_pairs(self, pairs: int) -> None:
        """Show the parameters in ``pairs`` (1 or 2) parameter/value column pairs."""
        if pairs != self.pairs:
            self.pairs = pairs
            self._setup_columns()
            self.set_parameters(self.params)

    def _setup_columns(self) -> None:
        self.setColumnCount(2 * self.pairs)
        self.setHorizontalHeaderLabels(["Parameter", "Value"] * self.pairs)
        header = self.horizontalHeader()
        for k in range(self.pairs):
            header.setSectionResizeMode(2 * k, QHeaderView.Interactive)
            header.setSectionResizeMode(2 * k + 1, QHeaderView.Stretch)

    def content_size(self) -> QSize:
        """Size the table needs to show every row and column without scrolling."""
        header = self.horizontalHeader()
        width = 2 * self.frameWidth()
        for col in range(self.columnCount()):
            w = max(self.sizeHintForColumn(col), header.sectionSizeHint(col))
            width += w + (VALUE_PADDING if col % 2 else 0)
        height = (2 * self.frameWidth() + header.height()
                  + self.rowCount() * self.verticalHeader().defaultSectionSize())
        return QSize(width, height)

    def _cell(self, index: int) -> tuple:
        """(row, value column) of parameter ``index``."""
        rows = max(1, self.rowCount())
        return index % rows, 2 * (index // rows) + 1

    def set_parameters(self, params: List[Parameter]) -> None:
        self._loading = True
        self.setUpdatesEnabled(False)
        try:
            self.params = params
            self.clearContents()
            self.setRowCount(-(-len(params) // self.pairs))  # ceiling division
            for index, p in enumerate(params):
                row, col = self._cell(index)
                name_item = QTableWidgetItem(p.name)
                name_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                if not p.settable:
                    name_item.setToolTip("Read only")
                value_item = self._value_item(p)
                value_item.setData(Qt.UserRole + 1, index)
                self.setItem(row, col - 1, name_item)
                self.setItem(row, col, value_item)
            for k in range(self.pairs):
                self.resizeColumnToContents(2 * k)
        finally:
            self.setUpdatesEnabled(True)
            self._loading = False

    def _value_item(self, p: Parameter) -> QTableWidgetItem:
        item = QTableWidgetItem()
        flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled
        if p.type == "LOGIC":
            item.setCheckState(Qt.Checked if p.value else Qt.Unchecked)
            if p.settable:
                flags |= Qt.ItemIsUserCheckable
        else:
            text = format_value(p.value)
            item.setText(text)
            item.setData(Qt.UserRole, text)
            if p.settable:
                flags |= Qt.ItemIsEditable
        if not p.settable:
            item.setForeground(self.palette().placeholderText())
        item.setFlags(flags)
        return item

    def value_item(self, name: str) -> QTableWidgetItem:
        for index, p in enumerate(self.params):
            if p.name == name:
                return self.item(*self._cell(index))
        raise KeyError(name)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        index = item.data(Qt.UserRole + 1)
        if self._loading or index is None:
            return
        p = self.params[index]
        if p.type == "LOGIC":
            text = "T" if item.checkState() == Qt.Checked else "F"
        else:
            text = item.text().strip()
            if text == item.data(Qt.UserRole):
                return
        self.edited.emit(p.name, text)


class ParameterWindow(QMainWindow):
    """All parameters of one datum (``kind="data"``) or variable (``kind="var"``)."""

    command_output = Signal(str, list)

    def __init__(self, gui: "TaoGui", client: TaoClient, kind: str, name: str) -> None:
        super().__init__()
        self.gui = gui
        self.client = client
        self.kind = kind
        self.name = name
        self.setObjectName(f"{kind}_parameters_window")
        self.setWindowTitle(f"{KIND_TITLES[kind]}: {name}")

        self.header = QLabel()
        self.header.setTextInteractionFlags(Qt.TextSelectableByMouse)
        two = QSettings().value(TWO_COLUMNS_KEY, True, type=bool)
        self.two_columns = QCheckBox("Two columns")
        self.two_columns.setToolTip("Show the parameters in two parameter/value columns")
        self.two_columns.setChecked(two)
        self.two_columns.toggled.connect(self._on_two_columns)
        self.table = ParameterTable()
        self.table.set_pairs(2 if two else 1)
        self.table.edited.connect(self._on_edited)
        top = QHBoxLayout()
        top.addWidget(self.header, 1)
        top.addWidget(self.two_columns)
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addLayout(top)
        layout.addWidget(self.table, 1)
        self.setCentralWidget(central)
        gui.build_menus(self.menuBar())
        self.resize(400, 300)  # until the parameters arrive; then fit_to_contents
        self._fitted = False

        client.state_changed.connect(self.refresh)
        self.refresh()

    def _on_two_columns(self, on: bool) -> None:
        QSettings().setValue(TWO_COLUMNS_KEY, on)
        self.table.set_pairs(2 if on else 1)
        self.fit_to_contents()

    def fit_to_contents(self) -> None:
        """Resize so the whole table shows without scrolling (within the screen)."""
        if self.isMaximized() or self.isFullScreen() or not self.table.params:
            return
        central = self.centralWidget()
        central.layout().activate()
        need = self.table.content_size()
        # Everything around the table (menu bar, header line, margins, status bar).
        extra_w = self.width() - self.table.width()
        extra_h = self.height() - self.table.height()
        width = max(need.width() + extra_w, central.layout().minimumSize().width())
        height = need.height() + extra_h
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            frame_w = self.frameGeometry().width() - self.width()
            frame_h = self.frameGeometry().height() - self.height()
            width = min(width, area.width() - frame_w)
            height = min(height, area.height() - frame_h)
        self.resize(width, height)

    def refresh(self) -> None:
        if not self.client.is_running:
            return
        kind, name = self.kind, self.name
        self.client.call(lambda t: fetch_parameters(t, kind, name),
                         on_done=self._show, on_error=self._show_error)

    def _show(self, params: List[Parameter]) -> None:
        self.table.set_parameters(params)
        if not self._fitted and params:
            self._fitted = True  # only on opening; later refreshes keep the user's size
            self.fit_to_contents()
        values = {p.name: p.value for p in params}
        if self.kind == "data":
            summary = f"{values.get('data_type', '')} &nbsp; at {values.get('ele_name', '')}"
        else:
            summary = f"{values.get('ele_name', '')}[{values.get('attrib_name', '')}]"
        self.header.setText(f"<b>{self.name}</b> &nbsp; {summary}")

    def _show_error(self, message: str) -> None:
        self.header.setText(f"<b>{self.name}</b> &nbsp; <i>{message}</i>")
        self.table.set_parameters([])

    def _on_edited(self, parameter: str, text: str) -> None:
        command = f"set {self.kind} {self.name}|{parameter} = {text}"

        def done(out: list) -> None:
            self.command_output.emit(command, out)
            if any("[ERROR" in line for line in out):
                # The table refreshes (state_changed) and so shows Tao's value again.
                self.statusBar().showMessage(f"Tao rejected: {command}", 8000)

        self.client.cmd(command, on_done=done)

    def show_and_raise(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def set_lattice_name(self, lattice: str) -> None:
        """Titles name the datum or variable only."""

    def closeEvent(self, event) -> None:
        event.accept()
        if not self.gui.closing:
            self.gui.remove_parameter_window(self)
