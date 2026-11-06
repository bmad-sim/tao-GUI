"""Tao command console: a command line with history and an output pane."""

from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QFontDatabase, QKeyEvent, QTextCharFormat, QTextCursor, QColor
from PySide6.QtWidgets import QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget

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
