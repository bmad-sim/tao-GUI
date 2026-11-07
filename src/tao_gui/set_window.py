"""Set window: Tao's ``set`` command.

On the left is a list of the parameter groups that Tao reports through its pipe
interface (global, bmad_com, beam, beam_init, …). Choosing one shows all of its
parameters, with those Tao marks settable editable; an edit issues
``set <group> <parameter> = <value>``. Below, a free-form line runs any other
``set`` subcommand (``set tune``, ``set plot``, ``set lattice``, …).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import List

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .details import Parameter, ParameterTable, parse_pipe_parameters
from .tao_worker import TaoClient


@dataclass(frozen=True)
class SetGroup:
    label: str
    pipe: str  # pipe command that lists the parameters
    set_prefix: str  # "set ..." command before "<parameter> = <value>"
    tip: str = ""


GROUPS = (
    SetGroup("Global", "global", "set global", "Tao global parameters (s%global)"),
    SetGroup("Bmad_com", "bmad_com", "set bmad_com", "Bmad global parameters"),
    SetGroup("Beam", "beam 1@0", "set beam", "Beam tracking parameters (universe 1, branch 0)"),
    SetGroup("Beam_init", "beam_init 1@0", "set beam_init",
             "Beam initialization (universe 1, branch 0)"),
    SetGroup("Space_charge_com", "space_charge_com", "set space_charge_com",
             "Space charge and CSR parameters"),
    SetGroup("PTC_com", "ptc_com", "set ptc_com", "PTC parameters"),
    SetGroup("Opti_de_param", "global:opti_de", "set opti_de_param",
             "Differential evolution optimizer parameters"),
)

# Every "set" subcommand, for the free-form line (see "set" in the Tao manual).
SUBCOMMANDS = (
    "beam", "beam_init", "bmad_com", "branch", "calculate", "curve", "data", "default",
    "dynamic_aperture", "element", "floor_plan", "geodesic_lm", "global", "graph", "key",
    "lat_layout", "lattice", "opti_de_param", "particle_start", "plot", "plot_page",
    "ptc_com", "ran_state", "region", "space_charge_com", "symbolic_number", "tune",
    "universe", "variable", "wave", "z_tune",
)
HISTORY_KEY = "set/history"
MAX_HISTORY = 20


def for_display(param: Parameter) -> Parameter:
    """Arrays come as "a;b;c"; show (and set) them space separated, as Tao reads them."""
    if param.type.endswith("_ARR") and isinstance(param.value, str):
        return replace(param, value=" ".join(v.strip() for v in param.value.split(";")))
    return param


def fetch_group(tao, group: SetGroup) -> List[Parameter]:
    """Runs on the worker thread."""
    return [for_display(p) for p in parse_pipe_parameters(tao.cmd(f"pipe {group.pipe}"))]


class SetWidget(QWidget):
    command_output = Signal(str, list)

    def __init__(self, client: TaoClient, parent=None) -> None:
        super().__init__(parent)
        self.client = client

        self.groups = QListWidget()
        for group in GROUPS:
            self.groups.addItem(group.label)
            self.groups.item(self.groups.count() - 1).setToolTip(group.tip)
        self.groups.currentRowChanged.connect(lambda _row: self.refresh())

        self.header = QLabel()
        self.two_columns = QCheckBox("Two columns")
        self.two_columns.setChecked(True)
        self.table = ParameterTable()
        self.table.set_pairs(2)
        self.table.edited.connect(self._on_edited)
        self.two_columns.toggled.connect(lambda on: self.table.set_pairs(2 if on else 1))
        head = QHBoxLayout()
        head.addWidget(self.header, 1)
        head.addWidget(self.two_columns)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addLayout(head)
        right_layout.addWidget(self.table, 1)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.groups)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([150, 750])

        # Free-form "set <subcommand> <arguments>"
        self.subcommand = QComboBox()
        self.subcommand.addItems(SUBCOMMANDS)
        self.subcommand.setCurrentText("element")
        self.args = QComboBox(editable=True)
        self.args.setInsertPolicy(QComboBox.NoInsert)
        self.args.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.args.setMinimumContentsLength(30)
        self.args.lineEdit().setPlaceholderText("Arguments, e.g. q1w k1 = 0.3")
        self.args.lineEdit().returnPressed.connect(self.run_line)
        self.args.textActivated.connect(self._on_history_chosen)
        run = QPushButton("Set")
        run.clicked.connect(self.run_line)
        line = QHBoxLayout()
        line.addWidget(QLabel("set"))
        line.addWidget(self.subcommand)
        line.addWidget(self.args, 1)
        line.addWidget(run)

        self.status = QLabel()
        self.status.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(splitter, 1)
        layout.addLayout(line)
        layout.addWidget(self.status)

        self._load_history()
        client.state_changed.connect(self.refresh)
        client.started.connect(lambda _out: self.refresh())
        self.groups.setCurrentRow(0)

    @property
    def group(self) -> SetGroup:
        return GROUPS[max(self.groups.currentRow(), 0)]

    def select_group(self, label: str) -> None:
        self.groups.setCurrentRow([g.label for g in GROUPS].index(label))

    # Parameter table -------------------------------------------------------
    def refresh(self) -> None:
        if not self.client.is_running or not self.isVisible():
            return
        group = self.group
        self.client.call(lambda t: fetch_group(t, group),
                         on_done=lambda params: self._show(group, params),
                         on_error=lambda msg: self._show_error(group, msg))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()  # not refreshed while hidden

    def _show(self, group: SetGroup, params: List[Parameter]) -> None:
        if group is not self.group:
            return
        self.header.setText(f"<b>{group.set_prefix}</b> &lt;parameter&gt; = &lt;value&gt;")
        self.table.set_parameters(params)

    def _show_error(self, group: SetGroup, message: str) -> None:
        if group is self.group:
            self.header.setText(f"<i>{message}</i>")
            self.table.set_parameters([])

    def _on_edited(self, name: str, text: str) -> None:
        self._send(f"{self.group.set_prefix} {name} = {text}")

    # Free-form line ------------------------------------------------------------
    def run_line(self) -> None:
        args = self.args.currentText().strip()
        sub = self.subcommand.currentText()
        if not args and sub not in ("calculate",):
            return
        entry = f"{sub} {args}".strip()
        self._remember(entry)
        self.args.setCurrentText("")
        self._send(f"set {entry}")

    def _on_history_chosen(self, text: str) -> None:
        """Choosing "element q1 k1 = 0.3" from the history fills both fields."""
        sub, _, args = text.partition(" ")
        if sub in SUBCOMMANDS:
            self.subcommand.setCurrentText(sub)
            self.args.setCurrentText(args)

    @staticmethod
    def history() -> List[str]:
        value = QSettings().value(HISTORY_KEY, [])
        if isinstance(value, str):
            value = [value]
        return [str(v) for v in value or []]

    def _load_history(self) -> None:
        self.args.blockSignals(True)
        self.args.clear()
        self.args.addItems(self.history())
        self.args.setCurrentIndex(-1)
        self.args.blockSignals(False)

    def _remember(self, entry: str) -> None:
        history = [entry] + [h for h in self.history() if h != entry]
        QSettings().setValue(HISTORY_KEY, history[:MAX_HISTORY])
        self._load_history()

    # ------------------------------------------------------------------
    def _send(self, command: str) -> None:
        def done(out: list) -> None:
            self.command_output.emit(command, out)
            errors = [line for line in out if line.lstrip().startswith("[ERROR")]
            if errors:
                detail = " ".join(l.strip() for l in out[out.index(errors[0]) + 1:][:2])
                self.status.setText(f"<span style='color:#c0392b'>Tao rejected: "
                                    f"<tt>{command}</tt> — {detail}</span>")
            else:
                self.status.setText(f"Done: <tt>{command}</tt>")

        self.client.cmd(command, on_done=done)
