"""Plot panels: Tao plot templates drawn with matplotlib.

Graph data comes from PyTao's plotting layer (``pytao.plotting``), which reads
it from Tao with ``pipe`` commands. Each panel owns one Tao plot region and
re-reads it whenever Tao's state changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtCore import QSize, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .tao_worker import TaoClient, TaoWorker

LAYOUT_TEMPLATE = "lat_layout"


@dataclass
class PlotData:
    region: str
    graphs: List[Any] = field(default_factory=list)
    layout: Optional[Any] = None


def fetch_plot(
    worker: TaoWorker,
    template: str,
    region: Optional[str],
    include_layout: bool,
) -> PlotData:
    """Place (if needed) and read the graphs for ``template``.

    Runs on the worker thread. Returns plain graph dataclasses that are safe to
    hand to the GUI thread.
    """
    from pytao.plotting.plot import LatticeLayoutGraph

    gm = worker.graph_manager
    if region is None:
        graphs = gm.prepare_graphs_by_name(template)
        region = graphs[0].region_name if graphs else gm.get_region_to_place_template(template)
    else:
        graphs = gm.update_region(region_name=region, template_name=template)

    layout = None
    if include_layout and any(getattr(g, "is_s_plot", False) for g in graphs):
        layout = _layout_graph(worker, gm, LatticeLayoutGraph)
    return PlotData(region=region, graphs=graphs, layout=layout)


def _layout_graph(worker: TaoWorker, gm, layout_cls):
    """The lattice layout graph, shared by all panels and re-read each time."""
    region = getattr(worker, "layout_region", None)
    if region is not None:
        graphs = gm.update_region(region_name=region, template_name=LAYOUT_TEMPLATE)
    else:
        graphs = gm.prepare_graphs_by_name(LAYOUT_TEMPLATE)
        if graphs:
            worker.layout_region = graphs[0].region_name
    return next((g for g in graphs if isinstance(g, layout_cls)), None)


def draw_plot(figure: Figure, data: PlotData) -> None:
    """Draw ``data`` into ``figure`` (GUI thread)."""
    from pytao.plotting import mpl as tao_mpl

    figure.clear()
    graphs = list(data.graphs)
    if not graphs:
        figure.text(0.5, 0.5, "No graphs to show", ha="center", va="center")
        return

    ratios = [3] * len(graphs) + ([1] if data.layout is not None else [])
    axes = figure.subplots(len(ratios), 1, sharex=data.layout is not None,
                           gridspec_kw={"height_ratios": ratios}, squeeze=False)[:, 0]
    for ax, graph in zip(axes, graphs):
        try:
            tao_mpl.plot(graph, ax)
        except NotImplementedError as ex:
            ax.text(0.5, 0.5, str(ex), ha="center", va="center", transform=ax.transAxes)
    if data.layout is not None:
        tao_mpl.plot(data.layout, axes[-1])
        axes[-1].set_xlim(axes[0].get_xlim())
        axes[-1].set_xlabel("")
        axes[-1].tick_params(labelbottom=False)  # element labels sit there
        for ax in axes[:-1]:
            ax.tick_params(labelbottom=True)
    figure.tight_layout()


class PlotPanel(QWidget):
    """One plot area showing a single Tao plot template."""

    close_requested = Signal(object)

    def __init__(self, client: TaoClient, template: str = "", closable: bool = False,
                 parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self.template = template
        self.region: Optional[str] = None
        self._refresh_pending = False
        self._refreshing = False

        self.template_combo = QComboBox(editable=True)
        self.template_combo.setMinimumContentsLength(14)
        self.template_combo.setInsertPolicy(QComboBox.NoInsert)
        if template:
            self.template_combo.addItem(template)
        self.template_combo.activated.connect(self._on_template_chosen)
        self.template_combo.lineEdit().returnPressed.connect(self._on_template_chosen)

        self.layout_check = QCheckBox("Lattice layout")
        self.layout_check.setChecked(True)
        self.layout_check.toggled.connect(lambda _on: self.refresh())

        self.figure = Figure(layout=None)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        self.toolbar.setIconSize(QSize(18, 18))
        self.status = QLabel()

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Plot:"))
        bar.addWidget(self.template_combo)
        bar.addWidget(self.layout_check)
        bar.addWidget(self.toolbar, 1)
        if closable:
            close = QPushButton("Close")
            close.clicked.connect(lambda: self.close_requested.emit(self))
            bar.addWidget(close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.addLayout(bar)
        layout.addWidget(self.canvas, 1)
        layout.addWidget(self.status)

        client.state_changed.connect(self.refresh)

    def set_templates(self, names: List[str]) -> None:
        current = self.template_combo.currentText()
        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        self.template_combo.addItems(names)
        self.template_combo.setCurrentText(current)
        self.template_combo.blockSignals(False)

    def _on_template_chosen(self, *_args) -> None:
        name = self.template_combo.currentText().strip()
        if name and name != self.template:
            self.set_template(name)

    def set_template(self, name: str) -> None:
        self.template = name
        self.region = None  # place the new template
        self.template_combo.setCurrentText(name)
        self.refresh()

    def reset(self) -> None:
        """Forget the region after Tao is reinitialized."""
        self.region = None

    def refresh(self) -> None:
        if not self.template or not self.client.is_running:
            return
        if self._refreshing:  # coalesce bursts of refresh requests
            self._refresh_pending = True
            return
        self._refreshing = True
        template, region, include_layout = self.template, self.region, self.layout_check.isChecked()
        self.client.call_worker(
            lambda w: fetch_plot(w, template, region, include_layout),
            on_done=self._on_data,
            on_error=self._on_error,
        )

    def _on_data(self, data: PlotData) -> None:
        self.region = data.region
        draw_plot(self.figure, data)
        self.canvas.draw_idle()
        self.status.setText(f"{self.template} in region {data.region}")
        self._done()

    def _on_error(self, message: str) -> None:
        self.figure.clear()
        self.figure.text(0.5, 0.5, message, ha="center", va="center", wrap=True)
        self.canvas.draw_idle()
        self.status.setText(f"Could not plot {self.template!r}")
        self.region = None
        self._done()

    def _done(self) -> None:
        self._refreshing = False
        if self._refresh_pending:
            self._refresh_pending = False
            self.refresh()
