"""Lattice browser: element table plus an editable attribute view."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np
from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QSplitter,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .tao_worker import TaoClient


@dataclass
class ElementRow:
    ix: int
    name: str
    key: str
    s: float
    length: float


def fetch_elements(tao, branch: int) -> List[ElementRow]:
    where = f"{branch}>>*"
    ix = tao.lat_list(where, "ele.ix_ele")
    names = tao.lat_list(where, "ele.name")
    keys = tao.lat_list(where, "ele.key")
    s = tao.lat_list(where, "ele.s")
    lengths = tao.lat_list(where, "ele.l")
    return [
        ElementRow(int(i), str(n), str(k), float(sv), float(lv))
        for i, n, k, sv, lv in zip(ix, names, keys, s, lengths)
    ]


def fetch_attributes(tao, ele_id: str) -> Dict[str, Any]:
    return {"head": tao.ele_head(ele_id), "attribs": tao.ele_gen_attribs(ele_id)}


def format_value(value: Any) -> str:
    if isinstance(value, (bool, np.bool_)):
        return "T" if value else "F"
    if isinstance(value, (float, np.floating)):
        return f"{value:.10g}"
    return str(value)


class ElementTableModel(QAbstractTableModel):
    COLUMNS = ("Index", "Name", "Key", "s [m]", "L [m]")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.rows: List[ElementRow] = []

    def set_rows(self, rows: List[ElementRow]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self.COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        col = index.column()
        if role == Qt.DisplayRole:
            return (str(row.ix), row.name, row.key, f"{row.s:.6f}", f"{row.length:.6f}")[col]
        if role == Qt.UserRole:  # sort key
            return (row.ix, row.name, row.key, row.s, row.length)[col]
        if role == Qt.TextAlignmentRole and col in (0, 3, 4):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None


class ElementFilterProxy(QSortFilterProxyModel):
    """Filter by element name or key, using Tao-style wildcards (* and %)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.pattern = ""
        self.setSortRole(Qt.UserRole)

    def set_pattern(self, text: str) -> None:
        text = text.strip().lower().replace("%", "?")
        if text and not any(c in text for c in "*?["):
            text = f"*{text}*"
        if hasattr(self, "beginFilterChange"):  # Qt >= 6.9
            self.beginFilterChange()
            self.pattern = text
            self.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        else:
            self.pattern = text
            self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        if not self.pattern:
            return True
        row = self.sourceModel().rows[source_row]
        return fnmatch.fnmatchcase(row.name.lower(), self.pattern) or fnmatch.fnmatchcase(
            row.key.lower(), self.pattern
        )


class AttributeTable(QTableWidget):
    """Shows ``ele:gen_attribs``; editing a value issues ``set ele``."""

    edited = Signal(str, str)  # attribute, new value text

    def __init__(self, parent=None) -> None:
        super().__init__(0, 3, parent)
        self.setHorizontalHeaderLabels(["Attribute", "Value", "Units"])
        self.verticalHeader().setVisible(False)
        # Not ResizeToContents (re-measures on every setItem); size once per load.
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.Interactive)
        self._loading = False
        self.itemChanged.connect(self._on_item_changed)

    def set_attributes(self, attribs: Dict[str, Any]) -> None:
        self._loading = True
        self.setUpdatesEnabled(False)
        try:
            names = [k for k in attribs if "#" not in k]
            self.clearContents()
            self.setRowCount(len(names))
            for row, name in enumerate(names):
                value = attribs[name]
                name_item = QTableWidgetItem(name)
                name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
                value_item = QTableWidgetItem(format_value(value))
                value_item.setData(Qt.UserRole, format_value(value))
                units_item = QTableWidgetItem(str(attribs.get(f"units#{name}", "")))
                units_item.setFlags(units_item.flags() & ~Qt.ItemIsEditable)
                self.setItem(row, 0, name_item)
                self.setItem(row, 1, value_item)
                self.setItem(row, 2, units_item)
            self.resizeColumnToContents(0)
            self.resizeColumnToContents(2)
        finally:
            self.setUpdatesEnabled(True)
            self._loading = False

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or item.column() != 1:
            return
        text = item.text().strip()
        if text == item.data(Qt.UserRole):
            return
        self.edited.emit(self.item(item.row(), 0).text(), text)


class LatticeWidget(QWidget):
    """Element table on top, attributes of the selected element below."""

    command_output = Signal(str, list)  # command echoed, Tao output
    element_selected = Signal(int, int)  # branch, element index (user selection)
    rows_loaded = Signal()

    def __init__(self, client: TaoClient, parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self.branch = 0
        self.selected_ix: Optional[int] = None

        self.branch_combo = QComboBox()
        self.branch_combo.currentIndexChanged.connect(self._on_branch_changed)
        self.filter_edit = QLineEdit(placeholderText="Filter by name or key (wildcards: * %)")
        self.filter_edit.setClearButtonEnabled(True)

        self.model = ElementTableModel(self)
        self.proxy = ElementFilterProxy(self)
        self.proxy.setSourceModel(self.model)
        self.filter_edit.textChanged.connect(self.proxy.set_pattern)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.SingleSelection)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.AscendingOrder)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.selectionModel().currentRowChanged.connect(self._on_row_changed)

        self.header_label = QLabel()
        self.header_label.setWordWrap(True)
        self.attributes = AttributeTable()
        self.attributes.edited.connect(self._on_attribute_edited)

        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(QLabel("Branch:"))
        row.addWidget(self.branch_combo, 1)
        top_layout.addLayout(row)
        top_layout.addWidget(self.filter_edit)
        top_layout.addWidget(self.table)

        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.addWidget(self.header_label)
        bottom_layout.addWidget(self.attributes)

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(top)
        splitter.addWidget(bottom)
        splitter.setSizes([400, 300])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

        client.started.connect(self._on_tao_started)
        client.state_changed.connect(self.refresh)

    # ------------------------------------------------------------------
    def ele_id(self, ix: Optional[int] = None) -> str:
        return f"{self.branch}>>{self.selected_ix if ix is None else ix}"

    def _on_tao_started(self, _output) -> None:
        self.client.call(lambda t: t.lat_branch_list(), on_done=self._set_branches)

    def _set_branches(self, branches: List[dict]) -> None:
        self.branch_combo.blockSignals(True)
        self.branch_combo.clear()
        for b in branches:
            self.branch_combo.addItem(f"{b['index']}: {b['branch_name']}", b["index"])
        self.branch_combo.blockSignals(False)
        self.branch = branches[0]["index"] if branches else 0
        self.selected_ix = None
        self.refresh()

    def _on_branch_changed(self, index: int) -> None:
        if index < 0:
            return
        self.branch = self.branch_combo.itemData(index)
        self.selected_ix = None
        self.refresh()

    def refresh(self) -> None:
        """Reload the element table and the selected element's attributes."""
        branch = self.branch
        self.client.call(lambda t: fetch_elements(t, branch), on_done=self._set_rows)

    def _set_rows(self, rows: List[ElementRow]) -> None:
        keep = self.selected_ix
        self.model.set_rows(rows)
        if keep is not None:
            self.select_element(keep)
        else:
            self.header_label.clear()
            self.attributes.setRowCount(0)
        self.rows_loaded.emit()

    def row_for(self, ix: int) -> Optional[ElementRow]:
        for row in self.model.rows:
            if row.ix == ix:
                return row
        return None

    def element_at(self, s: float) -> Optional[ElementRow]:
        """The element whose [s_start, s] span contains ``s``, preferring ones with length."""
        best = None
        for row in self.model.rows:
            if row.s - row.length <= s <= row.s:
                if row.length > 0:
                    return row
                best = best or row
        return best

    def select_element(self, ix: int) -> None:
        """Select element ``ix`` (in the current branch) in the table.

        Does not emit ``element_selected``.
        """
        for r, row in enumerate(self.model.rows):
            if row.ix == ix:
                self.selected_ix = ix
                proxy_index = self.proxy.mapFromSource(self.model.index(r, 0))
                if proxy_index.isValid():
                    self.table.setCurrentIndex(proxy_index)
                    self.table.scrollTo(proxy_index)
                self._load_attributes()
                return

    def _on_row_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if not current.isValid():
            return
        row = self.model.rows[self.proxy.mapToSource(current).row()]
        if row.ix != self.selected_ix:
            self.selected_ix = row.ix
            self._load_attributes()
            self.element_selected.emit(self.branch, row.ix)

    def _load_attributes(self) -> None:
        if self.selected_ix is None:
            return
        ele_id = self.ele_id()
        self.client.call(
            lambda t: fetch_attributes(t, ele_id),
            on_done=self._show_attributes,
            on_error=lambda msg: self.header_label.setText(f"<i>{msg}</i>"),
        )

    def _show_attributes(self, info: Dict[str, Any]) -> None:
        head = info["head"]
        self.header_label.setText(
            f"<b>{head['name']}</b> &nbsp; {head['key']} &nbsp; "
            f"index {self.branch}&gt;&gt;{head['ix_ele']} &nbsp; s = {head['s']:.6f} m"
        )
        self.attributes.set_attributes(info["attribs"])

    def _on_attribute_edited(self, attribute: str, value: str) -> None:
        command = f"set ele {self.ele_id()} {attribute} = {value}"
        self.client.cmd(command, on_done=lambda out: self.command_output.emit(command, out))
