"""Plot panels: Tao plot templates drawn with matplotlib.

Graph data comes from PyTao's plotting layer (``pytao.plotting``), which reads
it from Tao with ``pipe`` commands. Each panel owns one Tao plot region and
re-reads it whenever Tao's state changes.

Panels showing plots against s ("s-plots") can share their s range (linked
zoom), show the selected element as a shaded band, and report clicks so the
clicked element can be selected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtCore import QSize, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from .tao_worker import TaoClient, TaoWorker

LAYOUT_TEMPLATE = "lat_layout"
FLOOR_CLICK_PIXELS = 5  # how near (pixels) a click must be to a thin floor-plan element
ASPECT_SLACK = 8  # pixels left around a fixed-aspect plot when trimming the window
# Height of each graph and of the lattice layout strip, relative to each other.
GRAPH_RATIO = 3
LAYOUT_RATIO = 1
SELECTION_COLOR = "#f5b041"

Range = Tuple[float, float]


@dataclass
class PlotData:
    region: str
    graphs: List[Any] = field(default_factory=list)
    layout: Optional[Any] = None  # the layout graph, when it is to be drawn
    layout_available: bool = False  # this plot can have a lattice layout strip

    @property
    def is_s_plot(self) -> bool:
        return bool(self.graphs) and all(getattr(g, "is_s_plot", False) for g in self.graphs)


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

    data = PlotData(region=region, graphs=graphs)
    if data.is_s_plot and not any(isinstance(g, LatticeLayoutGraph) for g in graphs):
        # Read even when it won't be drawn, to know whether the toggle applies.
        layout = _layout_graph(worker, gm, LatticeLayoutGraph)
        data.layout_available = layout is not None
        if include_layout:
            data.layout = layout
    return data


def _layout_graph(worker: TaoWorker, gm, layout_cls):
    """The lattice layout graph, shared by all panels and re-read each time."""
    region = worker.layout_region
    if region is not None:
        graphs = gm.update_region(region_name=region, template_name=LAYOUT_TEMPLATE)
    else:
        graphs = gm.prepare_graphs_by_name(LAYOUT_TEMPLATE)
        if graphs:
            worker.layout_region = graphs[0].region_name
    return next((g for g in graphs if isinstance(g, layout_cls)), None)


def style_layout_axes(ax) -> None:
    """The lattice layout strip: no frame, no grid, no x ticks (element labels sit there)."""
    ax.grid(False)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_xlabel("")
    ax.tick_params(axis="x", bottom=False, labelbottom=False)


def draw_plot(figure: Figure, data: PlotData) -> list:
    """Draw ``data`` into ``figure`` (GUI thread). Returns the s-axes."""
    from pytao.plotting import mpl as tao_mpl

    figure.clear()
    graphs = list(data.graphs)
    if not graphs:
        figure.text(0.5, 0.5, "No graphs to show", ha="center", va="center")
        return []

    s_plot = data.is_s_plot
    ratios = [GRAPH_RATIO] * len(graphs) + ([LAYOUT_RATIO] if data.layout is not None else [])
    axes = figure.subplots(len(ratios), 1, sharex=s_plot,
                           gridspec_kw={"height_ratios": ratios}, squeeze=False)[:, 0]
    for ax, graph in zip(axes, graphs):
        try:
            tao_mpl.plot(graph, ax)
        except NotImplementedError as ex:
            ax.text(0.5, 0.5, str(ex), ha="center", va="center", transform=ax.transAxes)
    if data.layout is not None:
        tao_mpl.plot(data.layout, axes[-1])
        style_layout_axes(axes[-1])
        axes[-1].set_xlim(axes[0].get_xlim())
    if s_plot:
        for ax in axes[: len(graphs)]:
            ax.tick_params(labelbottom=True)
    return list(axes) if s_plot else []


class FloorPlanHits:
    """Finds the floor-plan element under a click.

    Each element is reduced to its centre line (x1, y1) → (x2, y2) and half width.
    A click hits the nearest element whose line is within its half width, or
    within ``FLOOR_CLICK_PIXELS`` for thin elements. Distances are measured in
    pixels, so this works at any zoom. Vectorized: fast for thousands of elements.
    """

    def __init__(self, ax, elements) -> None:
        self.ax = ax
        rows = [(e.branch_index, e.index, e.shape.x1, e.shape.y1, e.shape.x2, e.shape.y2,
                 max(abs(e.shape.off1), abs(e.shape.off2)))
                for e in elements if e.shape is not None]
        table = np.array(rows, dtype=float).reshape(-1, 7)
        self.ids = table[:, :2].astype(int)
        self.p1, self.p2, self.half = table[:, 2:4], table[:, 4:6], table[:, 6]

    def element_at(self, x_pixel: float, y_pixel: float) -> Optional[Tuple[int, int]]:
        """(branch, element index) at display point (x_pixel, y_pixel), or None."""
        if len(self.ids) == 0:
            return None
        to_pixels = self.ax.transData.transform
        a, b = to_pixels(self.p1), to_pixels(self.p2)
        click = np.array([x_pixel, y_pixel])
        ab = b - a
        length2 = np.einsum("ij,ij->i", ab, ab)
        t = np.clip(np.einsum("ij,ij->i", click - a, ab) / np.where(length2 > 0, length2, 1), 0, 1)
        distance = np.hypot(*(a + t[:, None] * ab - click).T)
        scale = abs(to_pixels((1, 0))[0] - to_pixels((0, 0))[0])  # pixels per data unit
        within = distance <= np.maximum(self.half * scale, FLOOR_CLICK_PIXELS)
        if not within.any():
            return None
        best = np.flatnonzero(within)[np.argmin(distance[within])]
        return int(self.ids[best, 0]), int(self.ids[best, 1])


class PlotPanel(QWidget):
    """One plot area showing a single Tao plot template.

    Signals
    -------
    template_changed(str)
    s_clicked(float)
        The user clicked an s-plot at this s (not in zoom/pan mode).
    s_range_changed(object)
        The user changed the s range (zoom, pan, home): an (s0, s1) tuple.
    element_clicked(int, int)
        The user clicked an element of a floor plan: (branch, element index).
    """

    template_changed = Signal(str)
    s_clicked = Signal(float)
    s_range_changed = Signal(object)
    element_clicked = Signal(int, int)

    def __init__(self, client: TaoClient, template: str = "", parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self.template = template
        self.region: Optional[str] = None
        self.s_axes: list = []
        self.selection: Optional[Range] = None
        self.user_s_range: Optional[Range] = None
        self._selection_artists: list = []
        self._floor_hits: List[FloorPlanHits] = []
        self._refresh_pending = False
        self._refreshing = False
        self._drawing = False

        self.template_combo = QComboBox(editable=True)
        self.template_combo.setMinimumContentsLength(14)
        self.template_combo.setInsertPolicy(QComboBox.NoInsert)
        if template:
            self.template_combo.addItem(template)
        self.template_combo.activated.connect(self._on_template_chosen)
        self.template_combo.lineEdit().returnPressed.connect(self._on_template_chosen)

        self.layout_check = QCheckBox("Lattice layout")
        self.layout_check.setChecked(True)
        self.layout_check.toggled.connect(self._on_layout_toggled)
        self.layout_check.setVisible(False)  # shown once a plot that can have a layout is drawn

        # "tight" re-fits the margins on every draw, including after a resize.
        self.figure = Figure(layout="tight")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.mpl_connect("button_press_event", self._on_click)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        self.toolbar.setIconSize(QSize(18, 18))
        self.status = QLabel()  # only shown for errors
        self.status.setVisible(False)
        self._has_layout = False  # the last drawing included the lattice layout
        self._n_graphs = 0
        self._resize_for_layout: Optional[int] = None  # canvas height when layout was toggled
        self._fit_aspect = True  # on the next drawing, trim space a fixed-aspect plot can't use

        self._bar = bar = QHBoxLayout()
        bar.addWidget(QLabel("Plot:"))
        bar.addWidget(self.template_combo)
        bar.addWidget(self.layout_check)
        bar.addWidget(self.toolbar, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.addLayout(bar)
        layout.addWidget(self.canvas, 1)
        layout.addWidget(self.status)

        client.state_changed.connect(self.refresh)

    # ------------------------------------------------------------------
    # Template choice
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
        self.user_s_range = None
        self._fit_aspect = True
        self.template_combo.setCurrentText(name)
        self.template_changed.emit(name)
        self.refresh()

    def reset(self) -> None:
        """Forget the region after Tao is reinitialized."""
        self.region = None

    # ------------------------------------------------------------------
    # Data
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

    def _on_layout_toggled(self, _on: bool) -> None:
        self._resize_for_layout = self.canvas.height()
        self.refresh()

    def _keep_graph_height(self, has_layout: bool, n_graphs: int) -> None:
        """After the layout was toggled, grow or shrink the window by the layout's
        share so the graphs keep their height."""
        start_height, self._resize_for_layout = self._resize_for_layout, None
        if start_height is None or has_layout == self._has_layout or n_graphs == 0:
            return
        window = self.window()
        if window is self or window.isMaximized() or window.isFullScreen():
            return
        graphs = GRAPH_RATIO * n_graphs
        if has_layout:  # new height H' with graphs' share of H' equal to the old H
            delta = round(start_height * LAYOUT_RATIO / graphs)
        else:
            delta = -round(start_height * LAYOUT_RATIO / (graphs + LAYOUT_RATIO))
        window.resize(window.width(), window.height() + delta)

    def _on_data(self, data: PlotData) -> None:
        self.region = data.region
        self.layout_check.setVisible(data.layout_available)
        has_layout = data.layout is not None
        self._keep_graph_height(has_layout, len(data.graphs))
        self._has_layout, self._n_graphs = has_layout, len(data.graphs)
        self._drawing = True
        try:
            self.s_axes = draw_plot(self.figure, data)
            self._floor_hits = [FloorPlanHits(ax, g.elements)
                                for ax, g in zip(self.figure.axes, data.graphs)
                                if type(g).__name__ == "FloorPlanGraph"]
            self._selection_artists = []
            # Home (toolbar) goes to the full range; then restore the user's zoom.
            self.toolbar.update()
            self.toolbar.push_current()
            if self.s_axes:
                self.s_axes[0].callbacks.connect("xlim_changed", self._on_xlim_changed)
                if self.user_s_range is not None:
                    self.s_axes[0].set_xlim(self.user_s_range)
                self._draw_selection()
        finally:
            self._drawing = False
        if self._fit_aspect:
            self._fit_aspect = False
            self._trim_to_aspect()
        self.canvas.draw_idle()
        self.status.setVisible(False)
        self._done()

    def _trim_to_aspect(self) -> None:
        """Shrink the window by the space a fixed-aspect plot (e.g. floor_plan) leaves empty.

        Such axes keep their data aspect ratio by shrinking their box, which leaves
        blank bands at the sides (or top and bottom). Done once when a template is
        first drawn, so a size the user picks later is kept.
        """
        window = self.window()
        if window is self or window.isMaximized() or window.isFullScreen():
            return
        axes = [ax for ax in self.figure.axes
                if ax.get_aspect() != "auto" and ax.get_adjustable() == "box"]
        if not axes:
            return
        self.canvas.draw()  # lay out, so the axes boxes reflect the aspect
        width, height = self.canvas.width(), self.canvas.height()
        spare_w = min((ax.get_position(original=True).width - ax.get_position().width) * width
                      for ax in axes)
        spare_h = min((ax.get_position(original=True).height - ax.get_position().height) * height
                      for ax in axes)
        spare_w, spare_h = int(spare_w) - ASPECT_SLACK, int(spare_h) - ASPECT_SLACK
        # Keep the whole bar (template, layout toggle, toolbar) visible.
        self._bar.invalidate()  # the layout toggle may just have been shown or hidden
        margins = self.layout().contentsMargins()
        bar_width = self._bar.sizeHint().width() + margins.left() + margins.right()
        spare_w = min(spare_w, self.width() - bar_width)
        if spare_w > 0 or spare_h > 0:
            window.resize(window.width() - max(spare_w, 0), window.height() - max(spare_h, 0))

    def _on_error(self, message: str) -> None:
        self.figure.clear()
        self.s_axes = []
        self._floor_hits = []
        self.figure.text(0.5, 0.5, message, ha="center", va="center", wrap=True)
        self.layout_check.setVisible(False)
        self.canvas.draw_idle()
        self.status.setText(f"Could not plot {self.template!r}")
        self.status.setVisible(True)
        self._resize_for_layout = None
        self.region = None
        self._done()

    def _done(self) -> None:
        self._refreshing = False
        if self._refresh_pending:
            self._refresh_pending = False
            self.refresh()

    # ------------------------------------------------------------------
    # s range (linked zoom)
    @property
    def is_s_plot(self) -> bool:
        return bool(self.s_axes)

    def s_range(self) -> Optional[Range]:
        return tuple(self.s_axes[0].get_xlim()) if self.s_axes else None

    def set_s_range(self, s_range: Optional[Range]) -> None:
        """Show ``s_range`` (None: full range) without re-emitting it."""
        self.user_s_range = s_range
        if not self.s_axes:
            return
        self._drawing = True
        try:
            if s_range is None:
                self.toolbar.home()
            else:
                self.s_axes[0].set_xlim(s_range)
        finally:
            self._drawing = False
        self.canvas.draw_idle()

    def _on_xlim_changed(self, ax) -> None:
        if self._drawing:
            return
        self.user_s_range = tuple(ax.get_xlim())
        self.s_range_changed.emit(self.user_s_range)

    # ------------------------------------------------------------------
    # Selection
    def set_selection(self, s_range: Optional[Range]) -> None:
        """Shade ``s_range`` (s_start, s_end) of the selected element."""
        self.selection = s_range
        if self.s_axes:
            self._draw_selection()
            self.canvas.draw_idle()

    def _draw_selection(self) -> None:
        for artist in self._selection_artists:
            artist.remove()
        self._selection_artists = []
        if self.selection is None:
            return
        s0, s1 = self.selection
        for ax in self.s_axes:
            if s1 - s0 > 0:
                artist = ax.axvspan(s0, s1, color=SELECTION_COLOR, alpha=0.35, zorder=0, lw=0)
            else:
                artist = ax.axvline(s0, color=SELECTION_COLOR, lw=2, zorder=0)
            self._selection_artists.append(artist)

    def _on_click(self, event) -> None:
        if event.button != 1 or self.toolbar.mode != "":  # not zooming or panning
            return
        if event.inaxes in self.s_axes and event.xdata is not None:
            self.s_clicked.emit(float(event.xdata))
            return
        for hits in self._floor_hits:
            if event.inaxes is hits.ax:
                found = hits.element_at(event.x, event.y)
                if found is not None:
                    self.element_clicked.emit(*found)
                return
