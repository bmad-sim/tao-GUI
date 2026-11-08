"""Shapes window: view and edit the element shapes of floor_plan and lat_layout drawings.

Each drawing (floor plan, lattice layout) has an ordered list of shapes. An
element is drawn with the first shape whose Ele ID matches it (and, if that
shape has "Multi" set, with the further shapes that match). The table lists the
shapes in that order; every cell can be edited, and the buttons add, delete and
reorder shapes.

Reading uses ``pipe shape_list`` (plus ``show plot -<drawing>`` for the offset,
which the pipe command does not report). A whole shape is written with
``set <drawing> ele_shape(<i>) = "<ele_id>" "<shape>" "<color>" <size> "<label>"
<draw> <multi> <line_width> <offset>``, which keeps every field (``pipe
shape_set`` would reset the offset). Adding and deleting use ``pipe
shape_manage``.
"""

from __future__ import annotations

import re
from html import escape
from dataclasses import dataclass, replace
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QStyledItemDelegate,
    QTabBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .tao_worker import TaoClient

DRAWINGS = (("floor_plan", "Floor plan"), ("lat_layout", "Lattice layout"))

# Shape names Tao accepts (tao_ele_shape_input_to_struct). Prefixes var:, asym_var:,
# vvar:, asym_vvar: and pattern:<name> can be typed in.
SHAPES = ("box", "xbox", "bow_tie", "rbow_tie", "circle", "diamond", "x",
          "r_triangle", "l_triangle", "u_triangle", "d_triangle",
          "var:box", "asym_var:box", "vvar:box", "asym_vvar:box")
WALL_SHAPES = ("solid_line", "dashed_line", "dash_dot_line", "dotted_line")
# quick_plot's named colors (Tao also accepts CSS color names).
COLORS = ("black", "red", "green", "blue", "cyan", "magenta", "yellow", "orange",
          "yellow_green", "light_green", "navy_blue", "purple", "reddish_purple",
          "dark_grey", "light_grey", "white", "transparent")
LABELS = ("name", "s", "none")
SWATCH = {"yellow_green": "yellowgreen", "light_green": "lightgreen", "navy_blue": "navy",
          "reddish_purple": "mediumvioletred", "dark_grey": "dimgray",
          "light_grey": "lightgray"}

# Columns: (header, Shape field)
COLUMNS = (("Ele ID", "ele_id"), ("Shape", "shape"), ("Color", "color"), ("Size", "size"),
           ("Label", "label"), ("Draw", "draw"), ("Multi", "multi"),
           ("Line width", "line_width"), ("Offset", "offset"))
CHECK_COLUMNS = ("draw", "multi")
TIPS = {
    "ele_id": "Elements to match: name, class::name, type::, alias::, data::, var::, "
              "building_wall::name (floor plan)",
    "shape": "Shape drawn. Also var:, asym_var:, vvar:, asym_vvar: and pattern:<name>",
    "color": "Color (quick_plot or CSS color name)",
    "size": "Half height of the shape",
    "label": "Label drawn by the element: name, s or none",
    "draw": "Draw this shape",
    "multi": "Also look for further matching shapes after this one",
    "line_width": "Line width (integer)",
    "offset": "Offset transverse to the reference orbit",
}
MAX_SHAPES = 50  # "set <drawing> ele_shape(i)" reads at most 50 shapes


@dataclass(frozen=True)
class Shape:
    index: int
    ele_id: str
    shape: str = "box"
    color: str = "black"
    size: float = 1.0
    label: str = "name"
    draw: bool = True
    multi: bool = False
    line_width: int = 1
    offset: float = 0.0

    def set_command(self, who: str, index: Optional[int] = None) -> str:
        def tf(flag: bool) -> str:
            return "T" if flag else "F"

        return (f'set {who} ele_shape({index or self.index}) = "{self.ele_id}" "{self.shape}" '
                f'"{self.color}" {self.size:.6g} "{self.label}" {tf(self.draw)} '
                f'{tf(self.multi)} {self.line_width} {self.offset:.6g}')


_SHOW_ROW = re.compile(r"^\s*ele_shape\((\d+)\)\s*=.*\s(\S+)\s*$")


def parse_offsets(show_lines: List[str]) -> Dict[int, float]:
    """Offsets (last column) from the ``show plot -floor_plan`` shape table."""
    offsets = {}
    for line in show_lines:
        match = _SHOW_ROW.match(line)
        if match:
            try:
                offsets[int(match.group(1))] = float(match.group(2))
            except ValueError:
                pass
    return offsets


def fetch_shapes(tao, who: str) -> List[Shape]:
    """Runs on the worker thread."""
    offsets = parse_offsets(tao.cmd(f"show plot -{who}", raises=False))
    shapes = []
    for row in tao.shape_list(who):
        i = int(row["shape_index"])
        shapes.append(Shape(i, row["ele_name"], row["shape"], row["color"],
                            float(row["shape_size"]), row["type_label"], bool(row["shape_draw"]),
                            bool(row["multi_shape"]), int(row["line_width"]),
                            offsets.get(i, 0.0)))
    return shapes


def fetch_patterns(tao) -> List[str]:
    try:
        return [p["name"] for p in tao.shape_pattern_list()]
    except Exception:
        return []


def errors_in(out: List[str]) -> str:
    """Tao's error message in command output ('' if none)."""
    for i, line in enumerate(out):
        if line.lstrip().startswith(("[ERROR", "[FATAL")):
            return " ".join(l.strip() for l in out[i + 1:i + 3] if l.strip())
    return ""


class _ComboDelegate(QStyledItemDelegate):
    """Editable drop-down for the Shape, Color and Label columns."""

    def __init__(self, choices, editable: bool, parent=None) -> None:
        super().__init__(parent)
        self.choices = choices  # list, or callable returning one
        self.editable = editable

    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        combo.setEditable(self.editable)
        choices = self.choices() if callable(self.choices) else self.choices
        combo.addItems(list(choices))
        return combo

    def setEditorData(self, editor, index):
        editor.setCurrentText(index.data() or "")

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText().strip())


class ShapesWidget(QWidget):
    command_output = Signal(str, list)

    def __init__(self, client: TaoClient, parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self.shapes: List[Shape] = []
        self.patterns: List[str] = []
        self._filling = False
        self._select_after_refresh: Optional[int] = None

        self.tabs = QTabBar()
        for _who, label in DRAWINGS:
            self.tabs.addTab(label)
        self.tabs.currentChanged.connect(lambda _i: self.refresh())

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([h for h, _f in COLUMNS])
        for col, (_h, field) in enumerate(COLUMNS):
            self.table.horizontalHeaderItem(col).setToolTip(TIPS[field])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
                                   | QAbstractItemView.AnyKeyPressed)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(
            self.table.fontMetrics().height() + 8)
        self.table.setItemDelegateForColumn(
            self.column("shape"), _ComboDelegate(self._shape_choices, True, self.table))
        self.table.setItemDelegateForColumn(
            self.column("color"), _ComboDelegate(COLORS, True, self.table))
        self.table.setItemDelegateForColumn(
            self.column("label"), _ComboDelegate(LABELS, False, self.table))
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemSelectionChanged.connect(self._update_buttons)

        self.new_id = QLineEdit()
        self.new_id.setPlaceholderText("Ele ID for a new shape, e.g. quadrupole::q*")
        self.new_id.returnPressed.connect(self.add_shape)
        self.add_button = QPushButton("Add")
        self.add_button.setToolTip("Add a shape below the selected one (or at the end)")
        self.add_button.clicked.connect(self.add_shape)
        self.delete_button = QPushButton("Delete")
        self.delete_button.clicked.connect(self.delete_shape)
        self.up_button = QPushButton("Move Up")
        self.up_button.clicked.connect(lambda: self.move_shape(-1))
        self.down_button = QPushButton("Move Down")
        self.down_button.clicked.connect(lambda: self.move_shape(1))
        buttons = QHBoxLayout()
        buttons.addWidget(self.new_id, 1)
        for button in (self.add_button, self.delete_button, self.up_button, self.down_button):
            buttons.addWidget(button)

        note = QLabel("An element is drawn with the first shape that matches it "
                      "(and further matches while <i>Multi</i> is set). Double-click a cell to edit.")
        note.setWordWrap(True)
        self.status = QLabel()
        self.status.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.tabs)
        layout.addWidget(note)
        layout.addWidget(self.table, 1)
        layout.addLayout(buttons)
        layout.addWidget(self.status)

        client.state_changed.connect(self.refresh)
        client.started.connect(lambda _out: self.refresh())
        self._update_buttons()

    # ------------------------------------------------------------------
    @staticmethod
    def column(field: str) -> int:
        return [f for _h, f in COLUMNS].index(field)

    @property
    def who(self) -> str:
        return DRAWINGS[max(self.tabs.currentIndex(), 0)][0]

    def select_drawing(self, who: str) -> None:
        self.tabs.setCurrentIndex([w for w, _l in DRAWINGS].index(who))

    def selected_row(self) -> int:
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    def _shape_choices(self) -> List[str]:
        choices = list(SHAPES) + [f"pattern:{p}" for p in self.patterns]
        if self.who == "floor_plan":
            choices += WALL_SHAPES
        return choices

    # Reading -------------------------------------------------------------
    def refresh(self) -> None:
        if not self.client.is_running or not self.isVisible():
            return
        who = self.who

        def fetch(tao):
            return fetch_shapes(tao, who), fetch_patterns(tao)

        self.client.call(fetch, on_done=lambda result: self._show(who, *result),
                         on_error=lambda msg: self.status.setText(f"<i>{msg}</i>"))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()  # not refreshed while hidden

    def _show(self, who: str, shapes: List[Shape], patterns: List[str]) -> None:
        if who != self.who:
            return
        selected = self.selected_row()
        self.shapes, self.patterns = shapes, patterns
        self._filling = True
        self.table.setRowCount(len(shapes))
        for row, shape in enumerate(shapes):
            for col, (_h, field) in enumerate(COLUMNS):
                value = getattr(shape, field)
                item = QTableWidgetItem()
                if field in CHECK_COLUMNS:
                    item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Checked if value else Qt.Unchecked)
                else:
                    item.setText(f"{value:.6g}" if isinstance(value, float) else str(value))
                if field == "color":
                    color = QColor(SWATCH.get(value.lower(), value.lower()))
                    if color.isValid() and value.lower() != "transparent":
                        item.setData(Qt.DecorationRole, color)
                if not shape.draw and field != "draw":
                    item.setForeground(QBrush(Qt.gray))
                self.table.setItem(row, col, item)
            self.table.setVerticalHeaderItem(row, QTableWidgetItem(str(shape.index)))
        self._filling = False
        if self._select_after_refresh is not None:
            selected, self._select_after_refresh = self._select_after_refresh, None
        if 0 <= selected < len(shapes):
            self.table.selectRow(selected)
        self._update_buttons()

    # Editing -------------------------------------------------------------
    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._filling:
            return
        row, field = item.row(), COLUMNS[item.column()][1]
        old = self.shapes[row]
        try:
            if field in CHECK_COLUMNS:
                value = item.checkState() == Qt.Checked
            elif field == "size" or field == "offset":
                value = float(item.text())
            elif field == "line_width":
                value = int(item.text())
            else:
                value = item.text().strip()
                if not value:
                    raise ValueError("empty")
        except ValueError:
            self.status.setText(f"<span style='color:#c0392b'>Bad {field}: "
                                f"<tt>{item.text()}</tt></span>")
            self.refresh()
            return
        if value == getattr(old, field):
            return
        self._run([replace(old, **{field: value}).set_command(self.who)])

    def add_shape(self) -> None:
        ele_id = self.new_id.text().strip()
        if not ele_id:
            self.status.setText("Type the Ele ID of the new shape, then press Add.")
            self.new_id.setFocus()
            return
        if len(self.shapes) >= MAX_SHAPES:
            self.status.setText(f"Tao allows at most {MAX_SHAPES} shapes.")
            return
        row = self.selected_row()
        index = self.shapes[row].index + 1 if row >= 0 else self._next_index()
        size = 1.0
        if self.shapes:  # a size in the drawing's units
            size = self.shapes[min(max(row, 0), len(self.shapes) - 1)].size
        shape = Shape(index, ele_id, size=size)
        who = self.who
        self.new_id.clear()
        self._run([f"pipe shape_manage {who} {index} add", shape.set_command(who)],
                  select=row + 1 if row >= 0 else len(self.shapes))

    def delete_shape(self) -> None:
        row = self.selected_row()
        if row < 0:
            return
        self._run([f"pipe shape_manage {self.who} {self.shapes[row].index} delete"],
                  select=min(row, len(self.shapes) - 2))

    def move_shape(self, step: int) -> None:
        row = self.selected_row()
        other = row + step
        if row < 0 or not 0 <= other < len(self.shapes):
            return
        a, b = self.shapes[row], self.shapes[other]
        self._run([b.set_command(self.who, a.index), a.set_command(self.who, b.index)],
                  select=other)

    def _next_index(self) -> int:
        return max((s.index for s in self.shapes), default=0) + 1

    def _run(self, commands: List[str], select: Optional[int] = None) -> None:
        def run(tao):
            return [(c, tao.cmd(c, raises=False)) for c in commands]

        def done(results) -> None:
            problems = []
            for command, out in results:
                self.command_output.emit(command, out)
                error = errors_in(out)
                if error:
                    problems.append(f"<tt>{escape(command)}</tt> — {escape(error)}")
            if problems:
                self.status.setText("<span style='color:#c0392b'>Tao rejected: "
                                    + "<br>".join(problems) + "</span>")
            else:
                self.status.setText("Done: " + "<br>".join(f"<tt>{escape(c)}</tt>" for c, _o in results))
            if select is not None and select >= 0:
                self._select_after_refresh = select

        self.client.call(run, on_done=done,
                         on_error=lambda msg: self.status.setText(f"<i>{msg}</i>"),
                         modifies=True)

    def _update_buttons(self) -> None:
        row = self.selected_row()
        self.delete_button.setEnabled(row >= 0)
        self.up_button.setEnabled(row > 0)
        self.down_button.setEnabled(0 <= row < len(self.shapes) - 1)
