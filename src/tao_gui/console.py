"""The Main window's contents: a command-file box above the Tao console.

The console is a command line with history and an output pane. The command-file
box runs Tao's ``call`` command and keeps a history of the files called.
"""

from __future__ import annotations

import os
import shlex
from typing import List

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QFont, QFontDatabase, QKeyEvent, QTextCharFormat, QTextCursor, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .tao_worker import TaoClient


class HistoryLineEdit(QLineEdit):
    """Line edit with Up/Down command history."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.history: List[str] = []
        self._pos = 0

    def add_history(self, text: str) -> None:
        if text and (not self.history or self.history[-1] != text):
            self.history.append(text)
        self._pos = len(self.history)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_Up and self.history:
            self._pos = max(0, self._pos - 1)
            self.setText(self.history[self._pos])
        elif event.key() == Qt.Key_Down and self.history:
            self._pos = min(len(self.history), self._pos + 1)
            self.setText(self.history[self._pos] if self._pos < len(self.history) else "")
        else:
            super().keyPressEvent(event)


class ConsoleWidget(QWidget):
    exit_requested = Signal()

    def __init__(self, client: TaoClient, parent=None) -> None:
        super().__init__(parent)
        self.client = client

        self.output = QPlainTextEdit(readOnly=True)
        self.output.setMaximumBlockCount(20000)
        font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        self.output.setFont(font)
        self.input = HistoryLineEdit()
        self.input.setFont(font)
        self.input.setPlaceholderText("Tao command (e.g. show ele q00w, set ele q00w k1 = 0.1)")
        self.input.returnPressed.connect(self._submit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.output)
        layout.addWidget(self.input)

    def _submit(self) -> None:
        command = self.input.text().strip()
        self.input.clear()
        if not command:
            return
        self.input.add_history(command)
        if command.lower() in ("exit", "quit", "x"):
            self.exit_requested.emit()
            return
        self.run_command(command)

    def run_command(self, command: str) -> None:
        """Echo ``command``, run it in Tao, and show its output."""
        self.append(f"Tao> {command}", bold=True)
        if not self.client.is_running:
            self.append("Tao is not running. Use File > Open to start it.", error=True)
            return
        self.client.cmd(command, on_done=self.append_lines)

    def append_lines(self, lines: List[str]) -> None:
        for line in lines:
            self.append(line, error=line.lstrip().startswith(("[ERROR", "[FATAL", "[ABORT")))

    def append(self, text: str, bold: bool = False, error: bool = False) -> None:
        fmt = QTextCharFormat()
        if bold:
            fmt.setFontWeight(QFont.Bold)
        if error:
            fmt.setForeground(QColor("#c0392b"))
        cursor = self.output.textCursor()
        cursor.movePosition(QTextCursor.End)
        if not self.output.document().isEmpty():
            cursor.insertBlock()
        cursor.insertText(text, fmt)
        self.output.setTextCursor(cursor)
        self.output.ensureCursorVisible()


CALL_HISTORY_KEY = "call/history"  # QSettings: command files called, latest first
MAX_CALL_HISTORY = 20


class CallFileBox(QGroupBox):
    """Run a Tao command file (``call <file> [args]``), with a history of past calls.

    The field takes the file name and any arguments, as Tao's ``call`` command does.
    Pick a past call from the list, or Browse… for a file. Relative paths are
    relative to Tao's working directory.
    """

    def __init__(self, console: "ConsoleWidget", parent=None) -> None:
        super().__init__("Command file", parent)
        self.console = console

        self.combo = QComboBox(editable=True)
        self.combo.setInsertPolicy(QComboBox.NoInsert)
        # Long entries in the history must not widen the window.
        self.combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.combo.setMinimumContentsLength(30)
        self.combo.lineEdit().setPlaceholderText("File to call, and any arguments")
        self.combo.lineEdit().returnPressed.connect(self.call)
        self.combo.setToolTip("Runs Tao's \"call\" command: file name, then any arguments")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.browse)
        self.call_button = QPushButton("Call")
        self.call_button.setDefault(True)
        self.call_button.clicked.connect(self.call)

        layout = QHBoxLayout(self)
        layout.addWidget(self.combo, 1)
        layout.addWidget(browse)
        layout.addWidget(self.call_button)
        self._load_history()

    # History ------------------------------------------------------------
    @staticmethod
    def history() -> List[str]:
        value = QSettings().value(CALL_HISTORY_KEY, [])
        if isinstance(value, str):
            value = [value]
        return [str(v) for v in value or []]

    def _load_history(self) -> None:
        text = self.combo.currentText()
        self.combo.clear()
        self.combo.addItems(self.history())
        self.combo.setCurrentText(text)

    def _remember(self, text: str) -> None:
        history = [text] + [h for h in self.history() if h != text]
        QSettings().setValue(CALL_HISTORY_KEY, history[:MAX_CALL_HISTORY])
        self._load_history()

    # Actions ------------------------------------------------------------
    def browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Call command file", os.getcwd(),
                                              "Tao command files (*.tao *.cmd);;All files (*)")
        if path:
            self.combo.setCurrentText(self._relative(path))
            self.combo.lineEdit().setFocus()

    @staticmethod
    def _relative(path: str) -> str:
        """Path relative to Tao's working directory when it is inside it; quoted if needed."""
        rel = os.path.relpath(path, os.getcwd())
        if not rel.startswith(".."):
            path = rel
        return shlex.quote(path)

    def call(self) -> None:
        text = self.combo.currentText().strip()
        if not text:
            return
        self._remember(text)
        self.combo.setCurrentText(text)
        self.console.run_command(f"call {text}")


class MainWidget(QWidget):
    """Main window contents: the command-file box on top, the console below."""

    def __init__(self, call_box: CallFileBox, console: ConsoleWidget, parent=None) -> None:
        super().__init__(parent)
        self.call_box = call_box
        self.console = console
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(call_box)
        layout.addWidget(console, 1)
