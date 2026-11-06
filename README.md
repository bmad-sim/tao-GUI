# tao-GUI

A Qt desktop GUI for [Tao](https://www.classe.cornell.edu/bmad/tao.html), built on
[PyTao](https://github.com/bmad-sim/pytao).

Status: early development.

## Features

- **Plots:** any Tao plot template (beta, orbit, floor_plan, …), drawn with matplotlib
  from Tao's `pipe` data, with the lattice layout underneath s-based plots. Zoom and pan
  with the toolbar. Plots redraw after every change to Tao's state. Add more panels
  with View > Add plot panel.
- **Lattice browser:** element table per branch, with a name or key filter
  (wildcards `*` and `%`). Select an element to see its attributes; edit a value to
  issue `set ele`.
- **Console:** a Tao command line with history (Up/Down). Anything the GUI doesn't
  have a widget for still works here.

Tao always runs inside the GUI process on one background thread, so the window stays
responsive while Tao computes. Tao's own plot window is turned off
(`-noplot -external_plotting`).

## Install

Tao and PyTao are easiest to get from conda-forge:

```bash
conda create -n tao-gui -c conda-forge bmad pytao pyside6 matplotlib
conda activate tao-gui
pip install --no-deps -e .
```

To use your own Tao build instead, set `ACC_ROOT_DIR` (PyTao finds `libtao` in
`$ACC_ROOT_DIR/production/lib`) and `pip install -e .` into an environment with PyTao.

## Run

```bash
tao-gui -init tao.init           # any Tao command-line arguments
tao-gui -lattice_file my.bmad
tao-gui                          # uses ./tao.init if present, else File > Open
```

## Develop

```bash
pip install -e ".[test]"
pytest
```

The tests start Tao on the small FODO ring in `tests/files` and run headless
(`QT_QPA_PLATFORM=offscreen`).

### Layout

| Module | Role |
| --- | --- |
| `tao_worker.py` | `TaoClient`/`TaoWorker`: all Tao calls go through one worker thread |
| `main_window.py` | Main window, menus, docks |
| `plots.py` | Plot panels (PyTao graph data → matplotlib) |
| `lattice.py` | Element table and attribute editor |
| `console.py` | Command console |
