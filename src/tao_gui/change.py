"""Change window: a form for Tao's ``change`` command.

``change`` varies real parameters of the model: element attributes, variables,
particle_start coordinates, and the tunes. The form builds the command line,
shows it before it is run, and shows Tao's report (old and new values and the
change in merit) below.
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .tao_worker import TaoClient

# (label, prefix written before the number). See "change" in the Tao manual.
MODES = (
    ("Add to the value", ""),
    ("Set the value (@)", "@"),
    ("Design value + (d)", "d"),
    ("Change by percent (%)", "%"),
)
COORDINATES = ("x", "px", "y", "py", "z", "pz", "t")
WHATS = ("Element", "Variable", "Particle start", "Tune", "Z tune")


def real_attributes(attribs: dict) -> List[str]:
    """Names of the real-valued attributes in ``ele:gen_attribs`` output."""
    return [name for name, value in attribs.items()
            if "#" not in name and isinstance(value, float)]


def fetch_attribute_names(tao, ele_list: str) -> List[str]:
    """Real attributes of the first element matching ``ele_list`` (worker thread)."""
    ix = tao.lat_list(ele_list, "ele.ix_ele", flags="-array_out -track_only")
    branch = tao.lat_list(ele_list, "ele.ix_branch", flags="-array_out -track_only")
    if len(ix) == 0:
        ix = tao.lat_list(ele_list, "ele.ix_ele", flags="-array_out")
        branch = tao.lat_list(ele_list, "ele.ix_branch", flags="-array_out")
    if len(ix) == 0:
        return []
    return real_attributes(tao.ele_gen_attribs(f"{int(branch[0])}>>{int(ix[0])}"))


class ChangeWidget(QWidget):
    """Form for ``change element | variable | particle_start | tune | z_tune``."""

    command_output = Signal(str, list)

    def __init__(self, client: TaoClient, parent=None) -> None:
        super().__init__(parent)
        self.client = client

        self.what = QComboBox()
        self.what.addItems(WHATS)
        self.what.currentIndexChanged.connect(self._on_what_changed)

        # Element
        self.ele_edit = QLineEdit()
        self.ele_edit.setPlaceholderText("Element list, e.g. q1w, quadrupole::q*, 3:5")
        self.ele_edit.editingFinished.connect(self._load_attributes)
        self.use_selected = QPushButton("Use selected")
        self.use_selected.setToolTip("Use the element selected in the Lattice window or a plot")
        self.attribute = QComboBox(editable=True)
        self.attribute.setInsertPolicy(QComboBox.NoInsert)
        self.attribute.lineEdit().setPlaceholderText("Attribute, e.g. k1")
        self.attribute.setMinimumContentsLength(16)
        ele_row = QHBoxLayout()
        ele_row.addWidget(self.ele_edit, 1)
        ele_row.addWidget(self.use_selected)
        ele_page = QWidget()
        ele_form = QFormLayout(ele_page)
        ele_form.setContentsMargins(0, 0, 0, 0)
        ele_form.addRow("Elements:", ele_row)
        ele_form.addRow("Attribute:", self.attribute)

        # Variable
        self.var_edit = QComboBox(editable=True)
        self.var_edit.setInsertPolicy(QComboBox.NoInsert)
        self.var_edit.lineEdit().setPlaceholderText("Variables, e.g. quad[1], quad[3:5], quad[*]")
        var_page = QWidget()
        var_form = QFormLayout(var_page)
        var_form.setContentsMargins(0, 0, 0, 0)
        var_form.addRow("Variables:", self.var_edit)

        # Particle start
        self.coordinate = QComboBox()
        self.coordinate.addItems(COORDINATES)
        self.universe_edit = QLineEdit()
        self.universe_edit.setPlaceholderText("default")
        self.universe_edit.setMaximumWidth(80)
        start_page = QWidget()
        start_form = QFormLayout(start_page)
        start_form.setContentsMargins(0, 0, 0, 0)
        start_form.addRow("Coordinate:", self.coordinate)
        start_form.addRow("Universe:", self.universe_edit)

        # Tune / z tune
        self.dqa = QLineEdit("0")
        self.dqb = QLineEdit("0")
        self.mask_edit = QLineEdit()
        self.mask_edit.setPlaceholderText("Quadrupoles not to use, e.g. q1*")
        tune_page = QWidget()
        tune_form = QFormLayout(tune_page)
        tune_form.setContentsMargins(0, 0, 0, 0)
        tune_form.addRow("dQa:", self.dqa)
        tune_form.addRow("dQb:", self.dqb)
        tune_form.addRow("Mask:", self.mask_edit)
        self.dqz = QLineEdit("0")
        ztune_page = QWidget()
        ztune_form = QFormLayout(ztune_page)
        ztune_form.setContentsMargins(0, 0, 0, 0)
        ztune_form.addRow("dQz:", self.dqz)

        self.pages = QStackedWidget()
        for page in (ele_page, var_page, start_page, tune_page, ztune_page):
            self.pages.addWidget(page)

        # Amount (element, variable, particle start)
        self.mode = QComboBox()
        for label, _prefix in MODES:
            self.mode.addItem(label)
        self.value_edit = QLineEdit()
        self.value_edit.setPlaceholderText("Number")
        self.value_edit.returnPressed.connect(self.apply)
        self.amount = QWidget()
        amount_form = QFormLayout(self.amount)
        amount_form.setContentsMargins(0, 0, 0, 0)
        amount_form.addRow("How:", self.mode)
        amount_form.addRow("Amount:", self.value_edit)

        self.preview = QLabel()
        self.preview.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.change_button = QPushButton("Change")
        self.change_button.setDefault(True)
        self.change_button.clicked.connect(self.apply)
        button_row = QHBoxLayout()
        button_row.addWidget(self.preview, 1)
        button_row.addWidget(self.change_button)

        self.output = QPlainTextEdit(readOnly=True)
        self.output.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.output.setMaximumBlockCount(5000)
        self.output.setPlaceholderText("Tao's report of each change appears here.")

        top = QFormLayout()
        top.addRow("Change:", self.what)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addLayout(top)
        layout.addWidget(self.pages)
        layout.addWidget(self.amount)
        layout.addLayout(button_row)
        layout.addWidget(self.output, 1)

        for signal in (self.ele_edit.textChanged, self.attribute.currentTextChanged,
                       self.var_edit.currentTextChanged, self.coordinate.currentTextChanged,
                       self.universe_edit.textChanged, self.dqa.textChanged, self.dqb.textChanged,
                       self.mask_edit.textChanged, self.dqz.textChanged,
                       self.mode.currentIndexChanged, self.value_edit.textChanged):
            signal.connect(self._update_preview)
        client.started.connect(lambda _out: self._load_variables())
        self._on_what_changed(0)

    # ------------------------------------------------------------------
    def command(self) -> Optional[str]:
        """The ``change`` command the form describes, or None if it is incomplete."""
        what = self.what.currentText()
        prefix = MODES[self.mode.currentIndex()][1]
        value = self.value_edit.text().strip()
        # No space after the prefix: "change ele q k1 d 0.1" (as in the manual) is
        # rejected by Tao ("Expression is blank"); "d0.1" works.
        amount = f"{prefix}{value}"
        if what == "Element":
            eles, attrib = self.ele_edit.text().strip(), self.attribute.currentText().strip()
            if eles and attrib and value:
                return f"change element {eles} {attrib} {amount}"
        elif what == "Variable":
            var = self.var_edit.currentText().strip()
            if var and value:
                return f"change variable {var} {amount}"
        elif what == "Particle start":
            uni = self.universe_edit.text().strip()
            if value:
                return f"change {uni + '@' if uni else ''}particle_start {self.coordinate.currentText()} {amount}"
        elif what == "Tune":
            dqa, dqb = self.dqa.text().strip() or "0", self.dqb.text().strip() or "0"
            mask = self.mask_edit.text().strip()
            # Switches go after the subcommand: Tao does not look for them before it.
            return f"change tune {'-mask ' + mask + ' ' if mask else ''}{dqa} {dqb}"
        else:
            return f"change z_tune {self.dqz.text().strip() or '0'}"
        return None

    def apply(self) -> None:
        command = self.command()
        if command is None:
            return
        self.output.appendPlainText(f"Tao> {command}")

        def done(out: list) -> None:
            self.output.appendPlainText("\n".join(out) if out else "(no output)")
            self.output.appendPlainText("")
            self.command_output.emit(command, out)

        self.client.cmd(command, on_done=done)

    def set_element(self, name: str) -> None:
        """Fill in an element (from the selection) and list its attributes."""
        self.what.setCurrentText("Element")
        self.ele_edit.setText(name)
        self._load_attributes()

    # ------------------------------------------------------------------
    def _on_what_changed(self, index: int) -> None:
        # Size the stack to the shown page only (not the tallest one).
        for i in range(self.pages.count()):
            policy = QSizePolicy.Preferred if i == index else QSizePolicy.Ignored
            self.pages.widget(i).setSizePolicy(QSizePolicy.Preferred, policy)
        self.pages.setCurrentIndex(index)
        self.pages.adjustSize()
        self.amount.setVisible(WHATS[index] in ("Element", "Variable", "Particle start"))
        self._update_preview()

    def _update_preview(self, *_args) -> None:
        command = self.command()
        self.preview.setText(f"<tt>{command}</tt>" if command else "<i>Fill in the form</i>")
        self.change_button.setEnabled(command is not None)

    def _load_attributes(self) -> None:
        eles = self.ele_edit.text().strip()
        if not eles or not self.client.is_running:
            return
        self.client.call(lambda t: fetch_attribute_names(t, eles),
                         on_done=self._set_attributes, on_error=lambda _msg: None)

    def _set_attributes(self, names: List[str]) -> None:
        current = self.attribute.currentText()
        self.attribute.clear()
        self.attribute.addItems(names)
        self.attribute.setCurrentText(current)

    def _load_variables(self) -> None:
        def fetch(tao):
            return [v["name"] for v in tao.var_general()]

        def show(names):
            current = self.var_edit.currentText()
            self.var_edit.clear()
            self.var_edit.addItems([f"{n}[*]" for n in names])
            self.var_edit.setCurrentText(current)

        self.client.call(fetch, on_done=show, on_error=lambda _msg: None)
