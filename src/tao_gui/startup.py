"""Startup window: choose the files and options Tao starts with.

Shown alone when ``tao-gui`` is run with no arguments and there is no
``tao.init`` in the current directory, and again for File > Open.
"""

from __future__ import annotations

import json
import os
import shlex
from dataclasses import asdict, dataclass, field, fields
from typing import Dict, List, Optional

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

MAX_RECENT = 10

# (field, label, Tao flag, file filter). The first two are the main choices.
FILE_FIELDS = (
    ("init_file", "Init file", "-init_file", "Tao init (*.init);;All files (*)"),
    ("lattice_file", "Lattice file", "-lattice_file", "Bmad lattice (*.bmad *.lat);;All files (*)"),
    ("plot_file", "Plot file", "-plot_file", "Tao init (*.init);;All files (*)"),
    ("data_file", "Data file", "-data_file", "Tao init (*.init);;All files (*)"),
    ("var_file", "Variable file", "-var_file", "Tao init (*.init);;All files (*)"),
    ("beam_file", "Beam file", "-beam_file", "All files (*)"),
    ("startup_file", "Startup file", "-startup_file", "All files (*)"),
)

# (field, label, Tao flag or None, tooltip)
OPTION_FIELDS = (
    ("no_plot", "No plotting", None,
     "Do not open plot windows. (Tao itself never opens its own plot window in the GUI.)"),
    ("nostartup", "Skip startup file", "-nostartup", "Do not run the Tao startup command file"),
    ("no_rad_int", "No radiation integrals", "-no_rad_int",
     "Skip the radiation integrals calculation (faster for large rings)"),
    ("disable_smooth_line_calc", "No smooth-line calc", "-disable_smooth_line_calc",
     "Do not compute smooth curves for plots"),
    ("rf_on", "RF on", "-rf_on", "Keep RF cavities on (Tao turns them off by default)"),
    ("debug", "Debug", "-debug", "Tao debug mode"),
)


@dataclass
class StartupOptions:
    directory: str = ""
    init_file: str = ""
    lattice_file: str = ""
    plot_file: str = ""
    data_file: str = ""
    var_file: str = ""
    beam_file: str = ""
    startup_file: str = ""
    no_plot: bool = False
    nostartup: bool = False
    no_rad_int: bool = False
    disable_smooth_line_calc: bool = False
    rf_on: bool = False
    debug: bool = False
    extra_args: str = ""

    def tao_args(self) -> List[str]:
        """Tao command-line arguments (file paths relative to ``directory``)."""
        args: List[str] = []
        for name, _label, flag, _filter in FILE_FIELDS:
            value = getattr(self, name)
            if value:
                args += [flag, self._rel(value)]
        for name, _label, flag, _tip in OPTION_FIELDS:
            if flag and getattr(self, name):
                args.append(flag)
        if self.extra_args.strip():
            args += shlex.split(self.extra_args)
        return args

    def tao_command(self) -> str:
        return shlex.join(self.tao_args())

    def _rel(self, path: str) -> str:
        if self.directory and os.path.isabs(path):
            try:
                rel = os.path.relpath(path, self.directory)
            except ValueError:  # different drive on Windows
                return path
            if not rel.startswith(".."):
                return rel
        return path

    def problems(self) -> List[str]:
        """Reasons the options can't be used to start Tao (empty if OK)."""
        out = []
        if not (self.init_file or self.lattice_file):
            out.append("Choose an init file or a lattice file.")
        if self.directory and not os.path.isdir(self.directory):
            out.append(f"Directory not found: {self.directory}")
        for name, label, _flag, _filter in FILE_FIELDS:
            value = getattr(self, name)
            if value and not os.path.isfile(self._abs(value)):
                out.append(f"{label} not found: {value}")
        try:
            shlex.split(self.extra_args)
        except ValueError as ex:
            out.append(f"Extra arguments: {ex}")
        return out

    def _abs(self, path: str) -> str:
        return path if os.path.isabs(path) else os.path.join(self.directory or os.getcwd(), path)

    def label(self) -> str:
        main = self.init_file or self.lattice_file
        return f"{os.path.basename(main)} — {self.directory}" if main else self.directory

    @classmethod
    def from_dict(cls, data: Dict) -> "StartupOptions":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})


def load_recent() -> List[StartupOptions]:
    raw = QSettings().value("startup/recent", "[]")
    try:
        items = json.loads(raw) if isinstance(raw, str) else []
    except ValueError:
        items = []
    return [StartupOptions.from_dict(d) for d in items if isinstance(d, dict)]


def save_recent(options: StartupOptions) -> None:
    recent = [r for r in load_recent() if r.tao_args() != options.tao_args()
              or r.directory != options.directory]
    recent.insert(0, options)
    QSettings().setValue("startup/recent", json.dumps([asdict(r) for r in recent[:MAX_RECENT]]))


class FileField(QWidget):
    """Line edit plus a Browse button."""

    changed = Signal()

    def __init__(self, title: str, file_filter: str, directory_getter, pick_dir=False,
                 parent=None) -> None:
        super().__init__(parent)
        self.title = title
        self.file_filter = file_filter
        self.directory_getter = directory_getter
        self.pick_dir = pick_dir
        self.edit = QLineEdit()
        self.edit.setClearButtonEnabled(True)
        self.edit.textChanged.connect(self.changed)
        button = QToolButton(text="…")
        button.setToolTip(f"Choose {title.lower()}")
        button.clicked.connect(self.browse)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.edit, 1)
        layout.addWidget(button)

    def text(self) -> str:
        return self.edit.text().strip()

    def set_text(self, text: str) -> None:
        self.edit.setText(text)

    def browse(self) -> None:
        start = self.directory_getter() or os.getcwd()
        if self.pick_dir:
            path = QFileDialog.getExistingDirectory(self, self.title, start)
        else:
            path, _ = QFileDialog.getOpenFileName(self, self.title, start, self.file_filter)
        if path:
            self.set_text(path)


class StartupWindow(QWidget):
    """Pick the Tao startup files and options, then emit ``start_requested``.

    Signals
    -------
    start_requested(StartupOptions)
    cancelled()
        Quit (first start) or Cancel (File > Open while Tao runs).
    """

    start_requested = Signal(object)
    cancelled = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent, Qt.Window)
        self.setObjectName("startup_window")
        self.setWindowTitle("Start Tao")
        self.setMinimumWidth(640)
        self.tao_running = False
        self._accepted = False

        self.recent_combo = QComboBox()
        self.recent_combo.setPlaceholderText("Recent startups")
        self.recent_combo.activated.connect(self._on_recent)

        self.directory = FileField("Working directory", "", lambda: self.directory.text(), True)
        self.directory.setToolTip("Tao runs here; relative file names are resolved from it")
        self.files: Dict[str, FileField] = {}
        for name, label, _flag, file_filter in FILE_FIELDS:
            self.files[name] = FileField(label, file_filter, self.directory.text)
            self.files[name].edit.editingFinished.connect(self._relativize)

        main_form = QFormLayout()
        main_form.addRow("Recent:", self.recent_combo)
        main_form.addRow("Init file:", self.files["init_file"])
        main_form.addRow("Lattice file:", self.files["lattice_file"])
        main_form.addRow("Working directory:", self.directory)
        hint = QLabel("Give an init file, a lattice file, or both.")
        hint.setEnabled(False)
        hint.setToolTip("The working directory is filled in from the first file you choose.")
        main_form.addRow("", hint)

        # "Other input files": a disclosure toggle, collapsed by default.
        self.more_toggle = QToolButton(text="Other input files", checkable=True)
        self.more_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.more_toggle.setArrowType(Qt.RightArrow)
        self.more_toggle.setAutoRaise(True)
        self.more_body = QWidget()
        more_form = QFormLayout(self.more_body)
        more_form.setContentsMargins(0, 0, 0, 0)
        for name, label, _flag, _filter in FILE_FIELDS[2:]:
            more_form.addRow(f"{label}:", self.files[name])
        self.more_body.setVisible(False)
        self.more_toggle.toggled.connect(self._show_more)
        more = QWidget()
        more_layout = QVBoxLayout(more)
        more_layout.setContentsMargins(0, 0, 0, 0)
        more_layout.addWidget(self.more_toggle)
        more_layout.addWidget(self.more_body)

        options = QGroupBox("Options")
        grid = QGridLayout(options)
        self.options: Dict[str, QCheckBox] = {}
        for i, (name, label, _flag, tip) in enumerate(OPTION_FIELDS):
            box = QCheckBox(label)
            box.setToolTip(tip)
            box.toggled.connect(self._update)
            self.options[name] = box
            grid.addWidget(box, i // 3, i % 3)
        self.extra_args = QLineEdit(placeholderText="e.g. -start_branch_at ip_l0")
        self.extra_args.textChanged.connect(self._update)
        grid.addWidget(QLabel("Extra Tao arguments:"), 2, 0)
        grid.addWidget(self.extra_args, 2, 1, 1, 2)

        self.command_label = QLabel()
        self.command_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.command_label.setWordWrap(True)
        self.message = QPlainTextEdit(readOnly=True)
        self.message.setMaximumHeight(110)
        self.message.setVisible(False)

        self.buttons = QDialogButtonBox()
        self.start_button = self.buttons.addButton("Start Tao", QDialogButtonBox.AcceptRole)
        self.start_button.setDefault(True)
        self.cancel_button = self.buttons.addButton("Quit", QDialogButtonBox.RejectRole)
        self.start_button.clicked.connect(self._on_start)
        self.cancel_button.clicked.connect(self.close)

        layout = QVBoxLayout(self)
        layout.addLayout(main_form)
        layout.addWidget(more)
        layout.addWidget(options)
        layout.addWidget(QLabel("Tao will be started with:"))
        layout.addWidget(self.command_label)
        layout.addWidget(self.message)
        layout.addWidget(self.buttons)

        for f in [self.directory, *self.files.values()]:
            f.changed.connect(self._update)
        self.files["init_file"].changed.connect(lambda: self._default_directory("init_file"))
        self.files["lattice_file"].changed.connect(lambda: self._default_directory("lattice_file"))

        self._load_recent()
        self.directory.set_text(os.getcwd())
        self._update()

    # ------------------------------------------------------------------
    def options_value(self) -> StartupOptions:
        opts = StartupOptions(directory=self.directory.text(), extra_args=self.extra_args.text())
        for name, field_widget in self.files.items():
            setattr(opts, name, field_widget.text())
        for name, box in self.options.items():
            setattr(opts, name, box.isChecked())
        return opts

    def set_options(self, opts: StartupOptions) -> None:
        self.directory.set_text(opts.directory or os.getcwd())
        for name, field_widget in self.files.items():
            field_widget.set_text(getattr(opts, name))
        for name, box in self.options.items():
            box.setChecked(getattr(opts, name))
        self.extra_args.setText(opts.extra_args)
        if any(getattr(opts, name) for name, *_ in FILE_FIELDS[2:]):
            self.more_toggle.setChecked(True)
        self._update()

    def _show_more(self, on: bool) -> None:
        self.more_toggle.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        self.more_body.setVisible(on)
        self.adjustSize()

    def set_tao_running(self, running: bool) -> None:
        """While Tao runs, this window reinitializes Tao and Cancel just closes it."""
        self.tao_running = running
        self.cancel_button.setText("Cancel" if running else "Quit")
        self.start_button.setText("Reinitialize Tao" if running else "Start Tao")

    def show_error(self, message: str) -> None:
        self.message.setPlainText(message)
        self.message.setVisible(True)
        self.set_busy(False)
        self.show()
        self.raise_()

    def set_busy(self, busy: bool) -> None:
        self.start_button.setEnabled(not busy and not self.options_value().problems())
        self.start_button.setText("Starting…" if busy else
                                  ("Reinitialize Tao" if self.tao_running else "Start Tao"))

    def accept_started(self) -> None:
        """Tao started: close the window (without quitting)."""
        self._accepted = True
        self.set_busy(False)
        self.message.setVisible(False)
        self.close()
        self._accepted = False

    # ------------------------------------------------------------------
    def _default_directory(self, name: str) -> None:
        path = self.files[name].text()
        if os.path.isabs(path) and os.path.isfile(path):
            other = "lattice_file" if name == "init_file" else "init_file"
            if not self.files[other].text():
                self.directory.set_text(os.path.dirname(path))
            self._relativize()

    def _relativize(self) -> None:
        """Show files inside the working directory relative to it."""
        opts = self.options_value()
        for name, field_widget in self.files.items():
            value = field_widget.text()
            if value:
                rel = opts._rel(value)
                if rel != value:
                    field_widget.set_text(rel)

    def _update(self) -> None:
        opts = self.options_value()
        problems = opts.problems()
        self.command_label.setText(f"<code>tao {opts.tao_command()}</code>" if not problems
                                   else f"<i>{problems[0]}</i>")
        self.start_button.setEnabled(not problems)

    def _load_recent(self) -> None:
        self.recent = load_recent()
        self.recent_combo.clear()
        for opts in self.recent:
            self.recent_combo.addItem(opts.label())
        self.recent_combo.setEnabled(bool(self.recent))
        self.recent_combo.setCurrentIndex(-1)

    def _on_recent(self, index: int) -> None:
        if 0 <= index < len(self.recent):
            self.set_options(self.recent[index])

    def _on_start(self) -> None:
        opts = self.options_value()
        if opts.problems():
            return
        self.message.setVisible(False)
        self.set_busy(True)
        save_recent(opts)
        self._load_recent()
        self.start_requested.emit(opts)

    def closeEvent(self, event) -> None:
        event.accept()
        if not self._accepted:
            self.cancelled.emit()
