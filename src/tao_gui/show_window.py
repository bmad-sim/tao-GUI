"""Show window: run any of Tao's ``show`` subcommands and read the output.

Pick a subcommand from the list. Its switches appear as check boxes, switches
that exclude each other (they set the same thing in Tao) as radio buttons, and
values and arguments as drop-down lists filled from Tao (elements, data,
variables, plots, universes, branches, ...) wherever Tao can list them. What
each subcommand takes is in ``show_options.py``. The command line being built
is shown above the output after it runs. Switches are shown without the leading
"-", which only marks them on Tao's command line. Controls that do not apply are
hidden ("Use selected" for a subcommand without an element, "Recent" with no
history, "New window" with no output).

"Update automatically" re-runs the command whenever Tao's state changes, "Help"
shows Tao's help for the subcommand, "Recent" re-runs a past command, and "New
window" copies the output into a window of its own (which can be saved to a file).
"""

from __future__ import annotations

import html
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QDoubleValidator, QFontDatabase
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .show_options import SPECS, SPEC_BY_NAME, Arg, Choice, Flag, Positional, ShowSpec, element_fields
from .tao_worker import TaoClient

SUBCOMMANDS = tuple(spec.name for spec in SPECS)
HISTORY_KEY = "show/history2"  # full command lines ("show/history" held "<sub> <args>")
MAX_HISTORY = 30
FLAG_COLUMNS = 3

FORMATS = ("es12.4", "es16.8", "es15.6", "f10.4", "f12.6", "f14.6")
ATTRIBUTES = ("l", "s", "k1", "k2", "angle", "e_tot", "beta_a", "beta_b", "alpha_a", "alpha_b",
              "eta_x", "eta_y", "phi_a", "phi_b", "orbit_x", "orbit_y", "x_offset", "y_offset",
              "tilt", "hkick", "vkick", "voltage", "phi0", "rf_frequency", "is_on")


# ----------------------------------------------------------------------
# Lists for the drop-downs (fetched on the worker thread)

def fetch_choices(tao) -> Dict[str, List]:
    """Names Tao can list, keyed by Arg.kind. Each value is a list of (text, value)."""
    def safe(fn, default=()):
        try:
            return fn()
        except Exception:
            return list(default)

    n_uni = safe(lambda: int(tao.super_universe()["n_universe"]), [1]) or 1
    choices: Dict[str, List[Tuple[str, str]]] = {
        "universe": [(str(i), str(i)) for i in range(1, n_uni + 1)],
        "branch": [(f"{b['index']}  {b['branch_name']}", str(b["index"]))
                   for b in safe(tao.lat_branch_list)],
    }
    names = safe(lambda: list(dict.fromkeys(str(n) for n in tao.lat_list("*", "ele.name"))))
    choices["element"] = [(n, n) for n in names]
    data = []
    for d2 in safe(lambda: tao.data_d2_array(1)):
        data.append(d2)
        data += [f"{d2}.{d1['name']}" for d1 in safe(lambda: tao.data_d1_array(d2, ix_uni=1))]
    choices["data"] = [(d, d) for d in data]
    choices["variable"] = [(v["name"], v["name"]) for v in safe(tao.var_general)]
    regions = [r["region"] for r in safe(lambda: tao.plot_list("r")) if r.get("plot_name")]
    templates = [str(t) for t in safe(lambda: tao.plot_list("t")) if t]
    choices["plot"] = [(r, r) for r in regions] + [(f"T::{t}", f"T::{t}") for t in templates]
    choices["template"] = [(t, t) for t in templates]
    return choices


def fetch_graphs(tao, templates: List[str], curves: bool) -> List[str]:
    """"plot.graph" (or "plot.graph.curve") names of the templates."""
    out = []
    for plot in templates:
        try:
            info = tao.plot1(plot)
        except Exception:
            continue
        for i in range(1, int(info.get("num_graphs", 0)) + 1):
            graph = f"{plot}.{info[f'graph[{i}]']}"
            if not curves:
                out.append(graph)
                continue
            try:
                g = tao.plot_graph(graph)
            except Exception:
                continue
            out += [f"{graph}.{g[f'curve[{j}]']}" for j in range(1, int(g.get("num_curves", 0)) + 1)]
    return out


# ----------------------------------------------------------------------
# Widgets

class ArgWidget(QWidget):
    """Picks one value. Drop-downs are editable, so anything can still be typed."""

    changed = Signal()

    def __init__(self, arg: Arg, parent=None) -> None:
        super().__init__(parent)
        self.arg = arg
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.combo: Optional[QComboBox] = None
        self.edit: Optional[QLineEdit] = None
        self.spin: Optional[QSpinBox] = None
        kind = arg.kind
        if kind == "int":
            self.spin = QSpinBox()
            self.spin.setRange(0, 1_000_000)
            self.spin.setSpecialValueText(" ")  # 0: not given
            self.spin.valueChanged.connect(self.changed)
            layout.addWidget(self.spin)
            layout.addStretch(1)
        elif kind in ("float", "text", "file"):
            self.edit = QLineEdit(placeholderText=arg.placeholder)
            if kind == "float":
                self.edit.setValidator(QDoubleValidator())
                self.edit.setMaximumWidth(140)
            self.edit.textChanged.connect(self.changed)
            layout.addWidget(self.edit, 1)
            if kind == "file":
                browse = QPushButton("…")
                browse.setMaximumWidth(32)
                browse.clicked.connect(self._browse)
                layout.addWidget(browse)
        else:
            self.combo = QComboBox(editable=True)
            self.combo.setInsertPolicy(QComboBox.NoInsert)
            self.combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            self.combo.setMinimumContentsLength(14)
            self.combo.lineEdit().setPlaceholderText(arg.placeholder or self._placeholder())
            self.combo.currentTextChanged.connect(self.changed)
            if self.combo.completer() is not None:
                self.combo.completer().setFilterMode(Qt.MatchContains)
                self.combo.completer().setCaseSensitivity(Qt.CaseInsensitive)
            layout.addWidget(self.combo, 1)
            if kind == "format":
                self.set_items([(f, f) for f in FORMATS])
            elif kind == "attribute":
                self.set_items([(a, a) for a in ATTRIBUTES])
            elif kind == "track_format":
                self.set_items([("no", "no")] + [(f, f) for f in FORMATS])

    def _placeholder(self) -> str:
        return {"element": "element", "universe": "universe", "branch": "branch",
                "data": "data name", "variable": "variable name", "plot": "plot or region",
                "graph": "plot.graph", "curve": "plot.graph.curve"}.get(self.arg.kind, "")

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose file")
        if path:
            self.edit.setText(path)

    def set_items(self, items: List[Tuple[str, str]]) -> None:
        """(text shown, value used) pairs; the typed text is kept."""
        if self.combo is None:
            return
        text = self.combo.currentText()
        self.combo.blockSignals(True)
        self.combo.clear()
        for shown, value in items:
            self.combo.addItem(shown, value)
        self.combo.setCurrentIndex(-1)
        self.combo.setEditText(text)
        self.combo.blockSignals(False)

    def value(self) -> str:
        if self.spin is not None:
            return str(self.spin.value()) if self.spin.value() > 0 else ""
        if self.edit is not None:
            return self.edit.text().strip()
        text = self.combo.currentText().strip()
        index = self.combo.findText(text)
        if index >= 0 and self.combo.itemData(index) is not None:
            return str(self.combo.itemData(index))
        return text

    def set_value(self, text: str) -> None:
        if self.spin is not None:
            self.spin.setValue(int(text) if text.isdigit() else 0)
        elif self.edit is not None:
            self.edit.setText(text)
        else:
            self.combo.setEditText(text)


class SpecForm(QWidget):
    """Check boxes, radio buttons and pickers for one subcommand."""

    changed = Signal()

    def __init__(self, spec: ShowSpec, parent=None) -> None:
        super().__init__(parent)
        self.spec = spec
        self.flags: List[Tuple[Flag, QCheckBox, Optional[ArgWidget]]] = []
        self.choices: List[Tuple[Choice, QButtonGroup, List[Optional[ArgWidget]]]] = []
        self.positionals: List[Tuple[Positional, ArgWidget]] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        summary = QLabel(f"<b>show {spec.name}</b> — {html.escape(spec.summary)}")
        summary.setWordWrap(True)
        layout.addWidget(summary)

        if spec.positionals:
            box = QGroupBox("Arguments")
            form = QFormLayout(box)
            for pos in spec.positionals:
                picker = ArgWidget(pos.arg)
                picker.setToolTip(pos.tip)
                picker.changed.connect(self.changed)
                label = pos.label + ("" if pos.optional else " *")
                form.addRow(f"{label}:", picker)
                self.positionals.append((pos, picker))
            layout.addWidget(box)

        for item in spec.items:
            if isinstance(item, Choice):
                layout.addWidget(self._choice_box(item))

        plain = [f for f in spec.items if isinstance(f, Flag) and f.arg is None]
        valued = [f for f in spec.items if isinstance(f, Flag) and f.arg is not None]
        if plain or valued:
            box = QGroupBox("Switches")
            grid = QGridLayout(box)
            for i, flag in enumerate(plain):
                check = self._check(flag)
                grid.addWidget(check, i // FLAG_COLUMNS, i % FLAG_COLUMNS)
                self.flags.append((flag, check, None))
            row = (len(plain) + FLAG_COLUMNS - 1) // FLAG_COLUMNS
            for i, flag in enumerate(valued):
                check = self._check(flag)
                picker = ArgWidget(flag.arg)
                picker.setEnabled(False)
                check.toggled.connect(picker.setEnabled)
                picker.changed.connect(lambda c=check: c.setChecked(True))
                picker.changed.connect(self.changed)
                grid.addWidget(check, row + i, 0)
                grid.addWidget(picker, row + i, 1, 1, FLAG_COLUMNS - 1)
                self.flags.append((flag, check, picker))
            for col in range(FLAG_COLUMNS):
                grid.setColumnStretch(col, 1)
            layout.addWidget(box)

        if not spec.items and not spec.positionals:
            note = QLabel("<i>No options.</i>")
            layout.addWidget(note)
        layout.addStretch(1)

    def _check(self, flag: Flag) -> QCheckBox:
        check = QCheckBox(display_name(flag.switch))
        check.setToolTip(flag.tip)
        check.toggled.connect(self.changed)
        return check

    def _choice_box(self, choice: Choice) -> QGroupBox:
        box = QGroupBox(choice.label)
        box.setToolTip(choice.tip)
        grid = QGridLayout(box)
        group = QButtonGroup(box)
        pickers: List[Optional[ArgWidget]] = []
        row = col = 0
        for i, option in enumerate(choice.options):
            radio = QRadioButton(display_name(option.label))
            radio.setToolTip(option.tip)
            group.addButton(radio, i)
            picker = None
            if option.arg is not None:
                picker = ArgWidget(option.arg)
                picker.setEnabled(False)
                radio.toggled.connect(picker.setEnabled)
                picker.changed.connect(lambda r=radio: r.setChecked(True))
                picker.changed.connect(self.changed)
                if col:
                    row, col = row + 1, 0
                grid.addWidget(radio, row, 0)
                grid.addWidget(picker, row, 1, 1, FLAG_COLUMNS - 1)
                row += 1
            else:
                grid.addWidget(radio, row, col)
                col += 1
                if col == FLAG_COLUMNS:
                    row, col = row + 1, 0
            pickers.append(picker)
        for c in range(FLAG_COLUMNS):
            grid.setColumnStretch(c, 1)
        group.button(0).setChecked(True)
        group.idToggled.connect(lambda _id, on: on and self.changed.emit())
        self.choices.append((choice, group, pickers))
        return box

    # ------------------------------------------------------------------
    def arguments(self) -> List[str]:
        """The switches and arguments, in order."""
        # A switch whose optional value is left blank goes first: Tao would take a
        # following non-switch word (an argument) as its value.
        first: List[str] = []
        words: List[str] = []

        def add(switches: str, arg: Optional[Arg], value: str) -> None:
            target = first if arg is not None and not arg.required and not value else words
            target.extend(self._switch_words(switches, arg, value))

        for choice, group, pickers in self.choices:
            i = group.checkedId()
            option = choice.options[i]
            add(option.switches, option.arg, pickers[i].value() if pickers[i] is not None else "")
        for flag, check, picker in self.flags:
            if check.isChecked():
                add(flag.switch, flag.arg, picker.value() if picker else "")
        words += [picker.value() for _pos, picker in self.positionals if picker.value()]
        return first + words

    @staticmethod
    def _switch_words(switches: str, arg: Optional[Arg], value: str) -> List[str]:
        if not switches:
            return []
        if arg is not None and arg.repeat:
            values = value.replace(",", " ").split()
            return [w for v in values for w in (arg.repeat, v)] or [switches]
        return [switches] + ([value] if value else [])

    def missing(self) -> List[str]:
        """Required values not given yet."""
        out = [f"{pos.label}" for pos, picker in self.positionals
               if not pos.optional and not picker.value()]
        for flag, check, picker in self.flags:
            if check.isChecked() and picker is not None and flag.arg.required and not picker.value():
                out.append(display_name(flag.switch))
        for choice, group, pickers in self.choices:
            i = group.checkedId()
            option = choice.options[i]
            if pickers[i] is not None and option.arg.required and not pickers[i].value():
                out.append(display_name(option.label))
        return out

    def pickers(self) -> List[ArgWidget]:
        """Every value picker (positionals first)."""
        out = [p for _pos, p in self.positionals]
        out += [p for _f, _c, p in self.flags if p is not None]
        out += [p for _c, _g, ps in self.choices for p in ps if p is not None]
        return out

    def set_element(self, name: str) -> bool:
        """Put an element in the first element picker (and tick its switch)."""
        for picker in self.pickers():
            if picker.arg.kind == "element":
                picker.set_value(name)
                return True
        return False

    # For tests and scripting -----------------------------------------------
    def check(self, switch: str, on: bool = True, value: str = "") -> None:
        for flag, check, picker in self.flags:
            if flag.switch == switch:
                check.setChecked(on)
                if value and picker is not None:
                    picker.set_value(value)
                return
        raise KeyError(switch)

    def select(self, label: str, value: str = "") -> None:
        for choice, group, pickers in self.choices:
            for i, option in enumerate(choice.options):
                if label in (option.label, display_name(option.label)):
                    group.button(i).setChecked(True)
                    if value and pickers[i] is not None:
                        pickers[i].set_value(value)
                    return
        raise KeyError(label)

    def set_positional(self, label: str, value: str) -> None:
        for pos, picker in self.positionals:
            if pos.label == label:
                picker.set_value(value)
                return
        raise KeyError(label)


def display_name(switches: str) -> str:
    """"-orbit -floor_coords" -> "orbit + floor_coords": the dash only marks a
    switch on the command line."""
    words = switches.split()
    if not words or not all(w.startswith("-") for w in words):
        return switches  # a plain label, e.g. "element end"
    return " + ".join(w[1:] for w in words)


class ResultWindow(QWidget):
    """A copy of one command's output, in a window of its own."""

    def __init__(self, command: str, text: str, parent=None) -> None:
        super().__init__(parent, Qt.Window)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.command = command
        self.setWindowTitle(f"Tao: {command}" if command else "Tao output")
        self.text = QPlainTextEdit(readOnly=True)
        self.text.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.text.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.text.setPlainText(text)
        save = QPushButton("Save As…")
        save.clicked.connect(self.save_as)
        label = QLabel(f"<tt>{html.escape(command)}</tt>")
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        head = QHBoxLayout()
        head.addWidget(label, 1)
        head.addWidget(save)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addLayout(head)
        layout.addWidget(self.text, 1)
        self.resize(820, 520)

    def save_as(self) -> None:
        name = "_".join(self.command.split()[:2]) or "tao_output"
        path, _ = QFileDialog.getSaveFileName(self, "Save output", f"{name}.txt",
                                              "Text files (*.txt);;All files (*)")
        if path:
            self.save(path)

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            f.write(self.text.toPlainText() + "\n")


class ShowWidget(QWidget):
    command_output = Signal(str, list)

    def __init__(self, client: TaoClient, parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self.last_command = ""
        self.forms: Dict[str, SpecForm] = {}
        self.choices: Dict[str, List[Tuple[str, str]]] = {}
        self.graph_lists: Dict[str, List[str]] = {}

        self.list = QListWidget()
        for spec in SPECS:
            self.list.addItem(spec.name)
            self.list.item(self.list.count() - 1).setToolTip(spec.summary)
        self.list.currentTextChanged.connect(self._on_subcommand_chosen)
        self.list.itemDoubleClicked.connect(lambda _item: self.run())

        self.form_area = QScrollArea()
        self.form_area.setWidgetResizable(True)
        self.form_area.setFrameShape(QScrollArea.NoFrame)

        self.use_selected = QPushButton("Use selected")
        self.use_selected.setToolTip("Use the element selected in the Lattice window or a plot")
        self.show_button = QPushButton("Show")
        self.show_button.setDefault(True)
        self.show_button.clicked.connect(self.run)
        help_button = QPushButton("Help")
        help_button.setToolTip("Tao's help for this subcommand")
        help_button.clicked.connect(self.show_help)
        self.auto = QCheckBox("Update automatically")
        self.auto.setToolTip("Re-run the command whenever Tao's state changes")
        self.recent = QComboBox()
        self.recent.setPlaceholderText("Recent")
        self.recent.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.recent.setMinimumContentsLength(18)
        self.recent.activated.connect(lambda i: self.run_command(self.recent.itemText(i)))

        line = QHBoxLayout()
        line.addStretch(1)
        line.addWidget(self.use_selected)
        line.addWidget(self.show_button)
        line.addWidget(help_button)
        self.new_window = QPushButton("New window")
        self.new_window.setToolTip("Copy this output into a window of its own")
        self.new_window.clicked.connect(self.open_result_window)
        self.new_window.hide()  # until there is output
        self.result_windows: List[ResultWindow] = []
        self.output_command = ""
        options = QHBoxLayout()
        self.status = QLabel()
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        options.addWidget(self.status, 1)
        options.addWidget(self.new_window)
        options.addWidget(self.recent)
        options.addWidget(self.auto)

        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.addWidget(self.form_area, 1)
        top_layout.addLayout(line)

        self.output = QPlainTextEdit(readOnly=True)
        self.output.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.output.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.output.setPlaceholderText("Choose a subcommand on the left and press Show.")
        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.addLayout(options)
        bottom_layout.addWidget(self.output, 1)

        right = QSplitter(Qt.Vertical)
        right.addWidget(top)
        right.addWidget(bottom)
        right.setStretchFactor(1, 1)
        right.setSizes([400, 380])
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.list)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([160, 760])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(splitter)

        self._load_history()
        client.state_changed.connect(self._on_state_changed)
        client.started.connect(lambda _out: self._reload_choices())
        self.list.setCurrentRow(SUBCOMMANDS.index("element"))

    # ------------------------------------------------------------------
    @property
    def current(self) -> str:
        item = self.list.currentItem()
        return item.text() if item else ""

    @property
    def form(self) -> SpecForm:
        return self.forms[self.current]

    def command(self) -> str:
        return " ".join(["show", self.current] + self.form.arguments())

    def choose(self, name: str) -> None:
        self.list.setCurrentRow(SUBCOMMANDS.index(name))

    def set_argument(self, text: str) -> None:
        """Fill the element (from the selection)."""
        self.form.set_element(text)

    def run(self) -> None:
        missing = self.form.missing()
        if missing:
            self.status.setText("<span style='color:#c0392b'>Fill in: "
                                + html.escape(", ".join(missing)) + "</span>")
            return
        self.run_command(self.command())

    def run_command(self, command: str) -> None:
        self._remember(command)
        self.last_command = command
        self._run(command, echo=True)

    def open_result_window(self) -> "ResultWindow":
        """Copy the current output into a window of its own."""
        window = ResultWindow(self.output_command, self.output.toPlainText(), self)
        self.result_windows.append(window)
        window.destroyed.connect(lambda _obj=None, w=window: self._forget(w))
        window.show()
        return window

    def _forget(self, window: "ResultWindow") -> None:
        if window in self.result_windows:
            self.result_windows.remove(window)

    def show_help(self) -> None:
        self._run(f"help show {self.current}", echo=False)

    def _run(self, command: str, echo: bool) -> None:
        if not self.client.is_running:
            self.status.setText("<i>Tao is not running</i>")
            return

        def done(out: list) -> None:
            scroll = self.output.verticalScrollBar().value()
            self.output.setPlainText("\n".join(out) if out else "(no output)")
            if command == self.last_command and not echo:
                self.output.verticalScrollBar().setValue(scroll)  # keep place on auto-update
            self.status.setText(f"<tt>{html.escape(command)}</tt>")
            self.output_command = command
            self.new_window.show()
            if echo:
                self.command_output.emit(command, out)

        # "show" does not change Tao's state, so no state_changed (and no loop).
        self.client.cmd(command, on_done=done, modifies=False)

    def _on_state_changed(self) -> None:
        if self.auto.isChecked() and self.last_command and self.isVisible():
            self._run(self.last_command, echo=False)

    # Forms --------------------------------------------------------------------
    def _on_subcommand_chosen(self, name: str) -> None:
        if not name:
            return
        if name not in self.forms:
            form = SpecForm(SPEC_BY_NAME[name])
            self._fill_choices(form)
            self.forms[name] = form
        old = self.form_area.takeWidget()
        if old is not None:
            old.hide()
        self.form_area.setWidget(self.forms[name])
        self.forms[name].show()
        self.use_selected.setVisible(element_fields(SPEC_BY_NAME[name]) > 0)
        if name in ("graph", "curve"):
            self._load_graphs(name)

    def _fill_choices(self, form: SpecForm) -> None:
        for picker in form.pickers():
            kind = picker.arg.kind
            if kind in ("graph", "curve"):
                picker.set_items([(g, g) for g in self.graph_lists.get(kind, [])])
            elif kind in self.choices:
                picker.set_items(self.choices[kind])

    def _reload_choices(self) -> None:
        self.graph_lists.clear()

        def done(choices) -> None:
            self.choices = choices
            for form in self.forms.values():
                self._fill_choices(form)
            if self.current in ("graph", "curve"):
                self._load_graphs(self.current)

        self.client.call(fetch_choices, on_done=done, on_error=lambda _msg: None)

    def _load_graphs(self, kind: str) -> None:
        if kind in self.graph_lists or not self.client.is_running:
            return
        templates = [v for _t, v in self.choices.get("template", [])]
        if not templates:
            return

        def done(names) -> None:
            self.graph_lists[kind] = names
            for form in self.forms.values():
                self._fill_choices(form)

        self.client.call(lambda t: fetch_graphs(t, templates, kind == "curve"),
                         on_done=done, on_error=lambda _msg: None)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self.client.is_running and not self.choices:
            self._reload_choices()

    # History ----------------------------------------------------------------
    @staticmethod
    def history() -> List[str]:
        value = QSettings().value(HISTORY_KEY, [])
        if isinstance(value, str):
            value = [value]
        return [str(v) for v in value or []]

    def _load_history(self) -> None:
        self.recent.blockSignals(True)
        self.recent.clear()
        self.recent.addItems(self.history())
        self.recent.setCurrentIndex(-1)
        self.recent.blockSignals(False)
        self.recent.setVisible(self.recent.count() > 0)

    def _remember(self, command: str) -> None:
        history = [command] + [h for h in self.history() if h != command]
        QSettings().setValue(HISTORY_KEY, history[:MAX_HISTORY])
        self._load_history()
