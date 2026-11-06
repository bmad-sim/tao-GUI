"""Startup window: choose the files and options Tao starts with.

Shown alone when ``tao-gui`` is run with no arguments and there is no
``tao.init`` in the current directory, and again for File > Open.

Options that the init file can also set are tri-state: Default / On / Off.
"Default" passes nothing, so Tao uses the init file's setting (its
``tao_params`` namelist) or, if the init file doesn't set it, Tao's built-in
default. The window reads the init file to show what "Default" will be.
On / Off override the init file: they are applied with ``set global`` right
after Tao starts. (Tao's own ``-rf_on`` / ``--rf_on`` style switches would do
the same, but pytao 1.4 drops ``-rf_on`` and every ``--`` switch.)
"""

from __future__ import annotations

import json
import os
import re
import shlex
from dataclasses import asdict, dataclass, fields
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

MAX_RECENT = 10

# (field, label, Tao flag, file filter, tao_start namelist name or None)
FILE_FIELDS = (
    ("init_file", "Init file", "-init_file", "Tao init (*.init);;All files (*)", None),
    ("lattice_file", "Lattice file", "-lattice_file",
     "Bmad lattice (*.bmad *.lat);;All files (*)", None),
    ("beam_file", "Beam file", "-beam_file", "All files (*)", "beam_file"),
    ("data_file", "Data file", "-data_file", "Tao init (*.init);;All files (*)", "data_file"),
    ("var_file", "Variable file", "-var_file", "Tao init (*.init);;All files (*)", "var_file"),
    ("startup_file", "Startup file", "-startup_file", "All files (*)", "startup_file"),
    ("plot_file", "Plot file", "-plot_file", "Tao init (*.init);;All files (*)", "plot_file"),
)


@dataclass(frozen=True)
class TriOption:
    """An option the init file can also set (Default / On / Off)."""

    name: str  # StartupOptions field
    label: str
    tip: str
    global_name: Optional[str] = None  # Tao s%global component (None: GUI-only)
    invert: bool = False  # Tao global means the opposite (disable_...)
    off_flag: Optional[str] = None  # also passed on the command line when Off
    tao_default: bool = True  # Tao's built-in value, as seen by the user

    def set_command(self, value: bool) -> Optional[str]:
        if self.global_name is None:
            return None
        tao_value = (not value) if self.invert else value
        return f"set global {self.global_name} = {'T' if tao_value else 'F'}"


TRI_OPTIONS = (
    TriOption("plotting", "Plotting",
              "Open plot windows. (Tao itself never opens its own plot window in the GUI.)",
              global_name=None, tao_default=True),
    TriOption("rad_int", "Compute radiation integrals",
              "Compute the radiation integrals (Off starts large rings faster)",
              global_name="rad_int_user_calc_on", off_flag="-no_rad_int"),
    TriOption("smooth_line_calc", "Smooth-line calc", "Compute smooth curves for plots",
              global_name="disable_smooth_line_calc", invert=True,
              off_flag="-disable_smooth_line_calc"),
    TriOption("rf_on", "RF on", "RF cavities on (does not affect lcavities)",
              global_name="rf_on"),
)

# Init-file global that the Plotting default follows.
_PLOT_GLOBAL = "plot_on"

# (field, label, Tao flag when unchecked, Tao flag when checked, tooltip)
CHECK_OPTIONS = (
    ("run_startup", "Run startup file", "-nostartup", None, "Run the Tao startup command file"),
    ("debug", "Debug", None, "-debug", "Tao debug mode"),
)


# ----------------------------------------------------------------------
# Reading the init file


def _parse_value(text: str):
    text = text.strip()
    if text[:1] in "'\"" and text[-1:] == text[:1]:
        return text[1:-1]
    low = text.lower().strip(".")
    if low in ("t", "true"):
        return True
    if low in ("f", "false"):
        return False
    return text


def read_init_settings(path: str) -> Dict[str, object]:
    """Best-effort read of the ``tao_start`` and ``tao_params`` namelists.

    Returns lower-case keys such as ``"startup_file"`` and ``"global%rf_on"``.
    Unreadable files give an empty dict.
    """
    try:
        with open(path, errors="replace") as f:
            text = f.read()
    except OSError:
        return {}
    lines = []
    for line in text.splitlines():  # drop comments ('!' outside quotes)
        out, quote = [], None
        for ch in line:
            if quote:
                quote = None if ch == quote else quote
            elif ch in "'\"":
                quote = ch
            elif ch == "!":
                break
            out.append(ch)
        lines.append("".join(out))
    text = "\n".join(lines)

    settings: Dict[str, object] = {}
    for match in re.finditer(r"&(tao_start|tao_params)\b(.*?)(?:^\s*/|&end\b)", text,
                             re.IGNORECASE | re.DOTALL | re.MULTILINE):
        body = match.group(2)
        for item in re.finditer(r"([A-Za-z_][\w%]*)\s*=\s*('[^']*'|\"[^\"]*\"|[^\s,/]+)", body):
            settings[item.group(1).lower()] = _parse_value(item.group(2))
    return settings


# ----------------------------------------------------------------------


@dataclass
class StartupOptions:
    directory: str = ""
    init_file: str = ""
    lattice_file: str = ""
    beam_file: str = ""
    data_file: str = ""
    var_file: str = ""
    startup_file: str = ""
    plot_file: str = ""
    # Tri-state: None = not set (init file / Tao default), True = on, False = off.
    plotting: Optional[bool] = None
    rad_int: Optional[bool] = None
    smooth_line_calc: Optional[bool] = None
    rf_on: Optional[bool] = None
    run_startup: bool = True
    debug: bool = False
    extra_args: str = ""

    # -- Tao command line ------------------------------------------------
    def tao_args(self) -> List[str]:
        """Tao command-line arguments (file paths relative to ``directory``)."""
        args: List[str] = []
        for name, _label, flag, _filter, _nml in FILE_FIELDS:
            value = getattr(self, name)
            if value:
                args += [flag, self._rel(value)]
        for opt in TRI_OPTIONS:
            if opt.off_flag and getattr(self, opt.name) is False:
                args.append(opt.off_flag)
        for name, _label, flag_off, flag_on, _tip in CHECK_OPTIONS:
            flag = flag_on if getattr(self, name) else flag_off
            if flag:
                args.append(flag)
        if self.extra_args.strip():
            args += shlex.split(self.extra_args)
        return args

    def tao_command(self) -> str:
        return shlex.join(self.tao_args())

    def set_commands(self) -> List[str]:
        """Tao commands applying the explicit (On/Off) tri-state choices after startup."""
        commands = []
        for opt in TRI_OPTIONS:
            value = getattr(self, opt.name)
            if value is not None:
                command = opt.set_command(value)
                if command:
                    commands.append(command)
        return commands

    # -- Init-file defaults ----------------------------------------------
    def init_path(self) -> Optional[str]:
        """The init file Tao will read: the chosen one, or tao.init in the directory."""
        if self.init_file:
            return self._abs(self.init_file)
        default = self._abs("tao.init")
        return default if os.path.isfile(default) else None

    def init_settings(self) -> Dict[str, object]:
        path = self.init_path()
        return read_init_settings(path) if path else {}

    def default_value(self, opt: TriOption, settings: Optional[Dict] = None) -> Tuple[bool, str]:
        """(value, source) that "Default" gives for ``opt``: source is the init file or "Tao"."""
        settings = self.init_settings() if settings is None else settings
        key = f"global%{opt.global_name or _PLOT_GLOBAL}"
        value = settings.get(key)
        if isinstance(value, bool):
            value = (not value) if opt.invert else value
            return value, os.path.basename(self.init_path() or "init file")
        return opt.tao_default, "Tao"

    def effective(self, name: str) -> bool:
        opt = next(o for o in TRI_OPTIONS if o.name == name)
        value = getattr(self, name)
        return self.default_value(opt)[0] if value is None else value

    # -- Paths and checks -------------------------------------------------
    def _rel(self, path: str) -> str:
        if self.directory and os.path.isabs(path):
            try:
                rel = os.path.relpath(path, self.directory)
            except ValueError:  # different drive on Windows
                return path
            if not rel.startswith(".."):
                return rel
        return path

    def _abs(self, path: str) -> str:
        return path if os.path.isabs(path) else os.path.join(self.directory or os.getcwd(), path)

    def problems(self) -> List[str]:
        """Reasons the options can't be used to start Tao (empty if OK)."""
        out = []
        if not (self.init_file or self.lattice_file):
            out.append("Choose an init file or a lattice file.")
        if self.directory and not os.path.isdir(self.directory):
            out.append(f"Directory not found: {self.directory}")
        for name, label, _flag, _filter, _nml in FILE_FIELDS:
            value = getattr(self, name)
            if value and not os.path.isfile(self._abs(value)):
                out.append(f"{label} not found: {value}")
        try:
            shlex.split(self.extra_args)
        except ValueError as ex:
            out.append(f"Extra arguments: {ex}")
        return out

    def label(self) -> str:
        main = self.init_file or self.lattice_file
        return f"{os.path.basename(main)} — {self.directory}" if main else self.directory

    @classmethod
    def from_dict(cls, data: Dict) -> "StartupOptions":
        data = dict(data)
        # Recent startups saved before the options were positive and tri-state:
        # a set negative switch means Off; an unset one means "not set". The old
        # two-state "RF on" unchecked also meant "not set".
        if "no_plot" in data and data.get("rf_on") is False:
            data["rf_on"] = None
        for old, new in (("no_plot", "plotting"), ("no_rad_int", "rad_int"),
                         ("disable_smooth_line_calc", "smooth_line_calc")):
            if old in data and new not in data:
                data[new] = False if data.pop(old) else None
        if "nostartup" in data and "run_startup" not in data:
            data["run_startup"] = not data.pop("nostartup")
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
    recent = [r for r in load_recent() if asdict(r) != asdict(options)]
    recent.insert(0, options)
    QSettings().setValue("startup/recent", json.dumps([asdict(r) for r in recent[:MAX_RECENT]]))


# ----------------------------------------------------------------------
# Widgets


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


class TriStateCombo(QComboBox):
    """Default (shows what it resolves to) / On / Off."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.addItem("Default", None)
        self.addItem("On", True)
        self.addItem("Off", False)
        self.currentIndexChanged.connect(lambda _i: self.changed.emit())

    def value(self) -> Optional[bool]:
        return self.currentData()

    def set_value(self, value: Optional[bool]) -> None:
        self.setCurrentIndex({None: 0, True: 1, False: 2}[value])

    def set_default_text(self, value: bool, source: str) -> None:
        self.setItemText(0, f"Default ({'on' if value else 'off'}, {source})")


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
        self.setMinimumWidth(660)
        self.tao_running = False
        self._accepted = False

        self.recent_combo = QComboBox()
        self.recent_combo.setPlaceholderText("Recent startups")
        self.recent_combo.activated.connect(self._on_recent)

        self.directory = FileField("Working directory", "", lambda: self.directory.text(), True)
        self.directory.setToolTip("Tao runs here; relative file names are resolved from it")
        self.files: Dict[str, FileField] = {}
        for name, label, _flag, file_filter, _nml in FILE_FIELDS:
            self.files[name] = FileField(label, file_filter, self.directory.text)
            self.files[name].edit.editingFinished.connect(self._relativize)

        form = QFormLayout()
        form.addRow("Recent:", self.recent_combo)
        form.addRow("Init file:", self.files["init_file"])
        form.addRow("Lattice file:", self.files["lattice_file"])
        form.addRow("Working directory:", self.directory)
        hint = QLabel("Give an init file, a lattice file, or both. Empty fields below use "
                      "the init file's setting.")
        hint.setWordWrap(True)
        hint.setEnabled(False)
        form.addRow("", hint)
        for name, label, _flag, _filter, _nml in FILE_FIELDS[2:]:
            form.addRow(f"{label}:", self.files[name])

        options = QGroupBox("Options")
        options_form = QFormLayout(options)
        self.tri: Dict[str, TriStateCombo] = {}
        for opt in TRI_OPTIONS:
            combo = TriStateCombo()
            combo.setToolTip(opt.tip + "\nDefault: use the init file's setting, or Tao's.")
            combo.changed.connect(self._update)
            self.tri[opt.name] = combo
            options_form.addRow(f"{opt.label}:", combo)
        self.checks: Dict[str, QCheckBox] = {}
        check_row = QHBoxLayout()
        defaults = StartupOptions()
        for name, label, _off, _on, tip in CHECK_OPTIONS:
            box = QCheckBox(label)
            box.setToolTip(tip)
            box.setChecked(getattr(defaults, name))
            box.toggled.connect(self._update)
            self.checks[name] = box
            check_row.addWidget(box)
        check_row.addStretch(1)
        options_form.addRow(check_row)
        self.extra_args = QLineEdit(placeholderText="e.g. -start_branch_at ip_l0")
        self.extra_args.textChanged.connect(self._update)
        options_form.addRow("Extra Tao arguments:", self.extra_args)

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
        layout.addLayout(form)
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
        for name, combo in self.tri.items():
            setattr(opts, name, combo.value())
        for name, box in self.checks.items():
            setattr(opts, name, box.isChecked())
        return opts

    def set_options(self, opts: StartupOptions) -> None:
        self.directory.set_text(opts.directory or os.getcwd())
        for name, field_widget in self.files.items():
            field_widget.set_text(getattr(opts, name))
        for name, combo in self.tri.items():
            combo.set_value(getattr(opts, name))
        for name, box in self.checks.items():
            box.setChecked(getattr(opts, name))
        self.extra_args.setText(opts.extra_args)
        self._update()

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
        for field_widget in self.files.values():
            value = field_widget.text()
            if value:
                rel = opts._rel(value)
                if rel != value:
                    field_widget.set_text(rel)

    def _update(self) -> None:
        opts = self.options_value()
        settings = opts.init_settings()
        init_name = os.path.basename(opts.init_path() or "") or "init file"

        # What "Default" means, per the init file.
        for opt in TRI_OPTIONS:
            self.tri[opt.name].set_default_text(*opts.default_value(opt, settings))
        for name, _label, _flag, _filter, nml in FILE_FIELDS:
            if nml is None:
                continue
            value = settings.get(nml)
            self.files[name].edit.setPlaceholderText(
                f"{value} (from {init_name})" if isinstance(value, str) and value else "")

        problems = opts.problems()
        if problems:
            self.command_label.setText(f"<i>{problems[0]}</i>")
        else:
            text = f"<code>tao {opts.tao_command()}</code>"
            commands = opts.set_commands()
            if commands:
                text += "<br>then: <code>" + "; ".join(commands) + "</code>"
            self.command_label.setText(text)
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
