"""Run all Tao calls on one background thread.

Tao (through libtao and ctypes) is not thread safe, so every call goes through a
single worker thread that owns the ``Tao`` instance. GUI code submits jobs with
``TaoClient.call`` and gets the result back on the GUI thread via callbacks.
"""

from __future__ import annotations

import itertools
import traceback
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from PySide6.QtCore import QObject, QThread, Signal, Slot

# Fortran code can put large arrays on the stack; secondary threads on macOS
# default to 512 KiB, which is far too small.
WORKER_STACK_SIZE = 256 * 1024 * 1024

# Always run Tao without its own plot window; the GUI draws the plots.
TAO_STARTUP_FLAGS = {"noplot": True, "external_plotting": True}


class TaoNotStarted(RuntimeError):
    pass


class TaoWorker(QObject):
    """Lives on the worker thread and owns the Tao instance."""

    finished = Signal(int, object)
    failed = Signal(int, str, str)

    def __init__(self) -> None:
        super().__init__()
        self.tao = None
        self.graph_manager = None
        self.layout_region = None  # plot region holding the shared lat_layout

    def start_tao(self, init: str) -> list:
        """Start Tao, or reinitialize it if it is already running."""
        if self.tao is None:
            from pytao import Tao

            self.tao = Tao(init=init, **TAO_STARTUP_FLAGS)
        else:
            self.tao.init(init, **TAO_STARTUP_FLAGS)
        # Only import plotting after Tao exists (it imports matplotlib).
        from pytao.plotting.mpl import MatplotlibGraphManager

        self.graph_manager = MatplotlibGraphManager(self.tao)
        self.layout_region = None
        return list(getattr(self.tao, "init_output", []) or [])

    @Slot(int, object)
    def run_job(self, job_id: int, fn: Callable[["TaoWorker"], Any]) -> None:
        try:
            result = fn(self)
        except Exception as ex:  # report every failure to the GUI
            self.failed.emit(job_id, f"{type(ex).__name__}: {ex}", traceback.format_exc())
        else:
            self.finished.emit(job_id, result)


@dataclass
class _Pending:
    on_done: Optional[Callable[[Any], None]]
    on_error: Optional[Callable[[str], None]]
    modifies: bool


class TaoClient(QObject):
    """GUI-thread handle for submitting jobs to the Tao worker.

    Signals
    -------
    busy_changed(bool)
        True while any job is queued or running.
    state_changed()
        Emitted after a job that may have changed Tao's state (a command,
        a ``set``, a reinit). Views refresh themselves on this.
    started(list)
        Tao finished (re)initializing; carries Tao's init output lines.
    error(str, str)
        A job failed and had no ``on_error`` callback: message, traceback.
    """

    _submit = Signal(int, object)
    busy_changed = Signal(bool)
    state_changed = Signal()
    started = Signal(list)
    error = Signal(str, str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._ids = itertools.count(1)
        self._pending: Dict[int, _Pending] = {}
        self.is_running = False
        self._dirty = False

        self._thread = QThread()
        self._thread.setObjectName("tao-worker")
        self._thread.setStackSize(WORKER_STACK_SIZE)
        self._worker = TaoWorker()
        self._worker.moveToThread(self._thread)
        self._submit.connect(self._worker.run_job)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._thread.start()

    # ------------------------------------------------------------------
    def call_worker(
        self,
        fn: Callable[[TaoWorker], Any],
        on_done: Optional[Callable[[Any], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        modifies: bool = False,
    ) -> int:
        """Run ``fn(worker)`` on the worker thread."""
        job_id = next(self._ids)
        self._pending[job_id] = _Pending(on_done, on_error, modifies)
        if len(self._pending) == 1:
            self.busy_changed.emit(True)
        self._submit.emit(job_id, fn)
        return job_id

    def call(
        self,
        fn: Callable[[Any], Any],
        on_done: Optional[Callable[[Any], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        modifies: bool = False,
    ) -> int:
        """Run ``fn(tao)`` on the worker thread.

        ``on_done(result)`` / ``on_error(message)`` run on the GUI thread.
        Set ``modifies`` when the job can change Tao's state, so that
        ``state_changed`` is emitted afterwards.
        """

        def job(worker: TaoWorker):
            if worker.tao is None:
                raise TaoNotStarted("Tao has not been started")
            return fn(worker.tao)

        return self.call_worker(job, on_done, on_error, modifies)

    def start(self, init: str, on_error: Optional[Callable[[str], None]] = None) -> int:
        """Start (or reinitialize) Tao with a Tao command-line string."""

        def done(output):
            self.is_running = True
            self.started.emit(output)

        return self.call_worker(
            lambda w: w.start_tao(init), on_done=done, on_error=on_error, modifies=True
        )

    def cmd(
        self,
        command: str,
        on_done: Optional[Callable[[list], None]] = None,
        modifies: bool = True,
    ) -> int:
        """Run a Tao command line; errors are returned as output, not raised."""
        return self.call(lambda t: t.cmd(command, raises=False), on_done, modifies=modifies)

    @property
    def busy(self) -> bool:
        return bool(self._pending)

    def shutdown(self) -> None:
        self._thread.quit()
        self._thread.wait(5000)

    # ------------------------------------------------------------------
    @Slot(int, object)
    def _on_finished(self, job_id: int, result: Any) -> None:
        pending = self._pending.pop(job_id, None)
        if pending is None:
            return
        try:
            if pending.on_done is not None:
                pending.on_done(result)
        finally:
            self._after(pending)

    @Slot(int, str, str)
    def _on_failed(self, job_id: int, message: str, tb: str) -> None:
        pending = self._pending.pop(job_id, None)
        if pending is None:
            return
        try:
            if pending.on_error is not None:
                pending.on_error(message)
            else:
                self.error.emit(message, tb)
        finally:
            self._after(pending)

    def _after(self, pending: _Pending) -> None:
        # Coalesce: refresh views once after a run of state-changing jobs.
        if pending.modifies:
            self._dirty = True
        if self._dirty and self.is_running and not any(p.modifies for p in self._pending.values()):
            self._dirty = False
            self.state_changed.emit()
        if not self._pending:
            self.busy_changed.emit(False)
