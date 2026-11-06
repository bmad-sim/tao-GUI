"""Data and variable windows.

Both show a list of arrays on the left (d2/d1 data, v1 variables) and the
elements of the chosen array on the right. Edits become Tao ``set`` commands.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .lattice import format_value
from .tao_worker import TaoClient


@dataclass(frozen=True)
class Column:
    key: str  # key in the pipe output dict
    title: str
    set_name: Optional[str] = None  # Tao component for `set` (meas, weight, ...); None = read-only
    kind: str = "str"  # "str", "float" or "bool"


class ArrayTable(QTableWidget):
    """Rows of dicts; editable columns emit ``edited(row_index, column, text)``."""

    edited = Signal(int, object, str)

    def __init__(self, columns: Sequence[Column], parent=None) -> None:
        super().__init__(0, len(columns), parent)
        self.columns = list(columns)
        self.rows: List[Dict[str, Any]] = []
        self.setHorizontalHeaderLabels([c.title for c in self.columns])
        self.verticalHeader().setVisible(False)
        # Not ResizeToContents: that re-measures every column on each setItem,
        # which makes refilling a 100-row table take seconds. Size once per load.
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.horizontalHeader().setStretchLastSection(True)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self._loading = False
        self.itemChanged.connect(self._on_item_changed)

    def set_rows(self, rows: List[Dict[str, Any]]) -> None:
        self._loading = True
        self.setUpdatesEnabled(False)
        self.setSortingEnabled(False)
        try:
            self.rows = rows
            self.clearContents()
            self.setRowCount(len(rows))
            for r, row in enumerate(rows):
                for c, col in enumerate(self.columns):
                    self.setItem(r, c, self._make_item(col, row.get(col.key, "")))
            self.resizeColumnsToContents()  # once per load
        finally:
            self.setUpdatesEnabled(True)
            self._loading = False

    def _make_item(self, col: Column, value: Any) -> QTableWidgetItem:
        item = QTableWidgetItem()
        flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled
        if col.kind == "bool":
            item.setCheckState(Qt.Checked if value else Qt.Unchecked)
            if col.set_name:
                flags |= Qt.ItemIsUserCheckable
        else:
            item.setText(format_value(value))
            item.setData(Qt.UserRole, format_value(value))
            if col.set_name:
                flags |= Qt.ItemIsEditable
            if col.kind == "float":
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        item.setFlags(flags)
        return item

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading:
            return
        col = self.columns[item.column()]
        if not col.set_name:
            return
        if col.kind == "bool":
            text = "T" if item.checkState() == Qt.Checked else "F"
        else:
            text = item.text().strip()
            if text == item.data(Qt.UserRole):
                return
        self.edited.emit(item.row(), col, text)


class ArrayBrowser(QWidget):
    """Tree of arrays on the left, table of the chosen array on the right."""

    command_output = Signal(str, list)

    columns: Sequence[Column] = ()

    def __init__(self, client: TaoClient, parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self.current: Optional[str] = None  # name of the chosen array

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(self.tree_headers())
        self.tree.header().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tree.currentItemChanged.connect(self._on_tree_changed)

        self.title = QLabel()
        self.table = ArrayTable(self.columns)
        self.table.edited.connect(self._on_edited)

        self.button_row = QHBoxLayout()
        for label, action in self.actions():
            button = QPushButton(label)
            button.clicked.connect(lambda _=False, a=action: self._run_action(a))
            self.button_row.addWidget(button)
        self.button_row.addStretch(1)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.title)
        right_layout.addWidget(self.table, 1)
        right_layout.addLayout(self.button_row)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.tree)
        splitter.addWidget(right)
        splitter.setSizes([260, 740])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(splitter)

        client.state_changed.connect(self.refresh)
        client.started.connect(lambda _out: self.reload_tree())

    # Subclass hooks ----------------------------------------------------
    def tree_headers(self) -> List[str]:
        raise NotImplementedError

    def fetch_tree(self, tao) -> list:
        """Runs on the worker: list of (label, extra columns, array name or None, children)."""
        raise NotImplementedError

    def fetch_rows(self, tao, name: str) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def element_name(self, name: str, row: Dict[str, Any]) -> str:
        raise NotImplementedError

    def actions(self) -> List[tuple]:
        """(button label, function(array name) -> Tao command)."""
        return []

    # ------------------------------------------------------------------
    def reload_tree(self) -> None:
        self.client.call(self.fetch_tree, on_done=self._set_tree,
                         on_error=lambda msg: self.title.setText(f"<i>{msg}</i>"))

    def _set_tree(self, nodes: list) -> None:
        keep = self.current
        self.tree.blockSignals(True)
        self.tree.clear()
        select = None

        def add(parent, node):
            nonlocal select
            label, extra, name, children = node
            item = QTreeWidgetItem([label, *extra])
            item.setData(0, Qt.UserRole, name)
            if parent is None:
                self.tree.addTopLevelItem(item)
            else:
                parent.addChild(item)
            for child in children:
                add(item, child)
            if name is not None and (name == keep or (select is None and keep is None)):
                select = item

        for node in nodes:
            add(None, node)
        self.tree.expandAll()
        self.tree.blockSignals(False)
        if select is not None:
            self.tree.setCurrentItem(select)
        else:
            self.current = None
            self.table.set_rows([])
            self.title.setText("<i>Nothing defined</i>" if not nodes else "")

    def _on_tree_changed(self, item: Optional[QTreeWidgetItem], _prev) -> None:
        name = item.data(0, Qt.UserRole) if item is not None else None
        if name is None:
            return
        self.current = name
        self.refresh()

    def refresh(self) -> None:
        if self.current is None or not self.client.is_running:
            return
        name = self.current
        self.client.call(
            lambda t: self.fetch_rows(t, name),
            on_done=lambda rows: self._show_rows(name, rows),
            on_error=lambda msg: self.title.setText(f"<i>{msg}</i>"),
        )

    def _show_rows(self, name: str, rows: List[Dict[str, Any]]) -> None:
        if name != self.current:
            return
        self.title.setText(f"<b>{name}</b> &nbsp; {len(rows)} entries")
        self.table.set_rows(rows)

    def _on_edited(self, row_index: int, col: Column, text: str) -> None:
        row = self.table.rows[row_index]
        command = f"set {self.set_kind} {self.element_name(self.current, row)}|{col.set_name} = {text}"
        self._send(command)

    def _run_action(self, action: Callable[[str], str]) -> None:
        if self.current is not None:
            self._send(action(self.current))

    def _send(self, command: str) -> None:
        self.client.cmd(command, on_done=lambda out: self.command_output.emit(command, out))


class DataWidget(ArrayBrowser):
    set_kind = "data"
    columns = (
        Column("ix_d1", "Index"),
        Column("data_type", "Data type"),
        Column("ele_name", "Element"),
        Column("merit_type", "Merit type"),
        Column("meas_value", "Meas", "meas", "float"),
        Column("model_value", "Model", kind="float"),
        Column("design_value", "Design", kind="float"),
        Column("weight", "Weight", "weight", "float"),
        Column("good_user", "Use", "good_user", "bool"),
        Column("useit_opt", "In opt", kind="bool"),
    )

    def __init__(self, client: TaoClient, universe: int = 1, parent=None) -> None:
        self.universe = universe
        super().__init__(client, parent)

    def tree_headers(self) -> List[str]:
        return ["Data", "Range"]

    def fetch_tree(self, tao) -> list:
        nodes = []
        for d2 in tao.data_d2_array(self.universe):
            children = [
                (d1["name"], [f"{d1['lower_bound']}:{d1['upper_bound']}"], f"{d2}.{d1['name']}", [])
                for d1 in tao.data_d1_array(d2, ix_uni=self.universe)
            ]
            nodes.append((d2, [""], None, children))
        return nodes

    def fetch_rows(self, tao, name: str) -> List[Dict[str, Any]]:
        d2, d1 = name.split(".", 1)
        return list(tao.data_d_array(d2, d1, ix_uni=self.universe))

    def element_name(self, name: str, row: Dict[str, Any]) -> str:
        return f"{self.universe}@{name}[{row['ix_d1']}]"

    def actions(self) -> List[tuple]:
        u = self.universe
        return [
            ("Use all", lambda n: f"use data {u}@{n}"),
            ("Veto all", lambda n: f"veto data {u}@{n}"),
            ("Meas = model", lambda n: f"set data {u}@{n}|meas = {u}@{n}|model"),
        ]


class VariablesWidget(ArrayBrowser):
    set_kind = "var"
    columns = (
        Column("ix_v1", "Index"),
        Column("var_attrib_name", "Element[attribute]"),
        Column("model_value", "Model", "model", "float"),
        Column("design_value", "Design", kind="float"),
        Column("meas_value", "Meas", "meas", "float"),
        Column("weight", "Weight", "weight", "float"),
        Column("good_user", "Use", "good_user", "bool"),
        Column("useit_opt", "In opt", kind="bool"),
    )

    def tree_headers(self) -> List[str]:
        return ["Variables", "Range"]

    def fetch_tree(self, tao) -> list:
        return [
            (v1["name"], [f"{v1['lbound']}:{v1['ubound']}"], v1["name"], [])
            for v1 in tao.var_general()
        ]

    def fetch_rows(self, tao, name: str) -> List[Dict[str, Any]]:
        return list(tao.var_v_array(name))

    def element_name(self, name: str, row: Dict[str, Any]) -> str:
        return f"{name}[{row['ix_v1']}]"

    def actions(self) -> List[tuple]:
        return [
            ("Use all", lambda n: f"use var {n}"),
            ("Veto all", lambda n: f"veto var {n}"),
            ("Model = design", lambda n: f"set var {n}|model = {n}|design"),
        ]
