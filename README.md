# tao-GUI

A Qt desktop GUI for [Tao](https://www.classe.cornell.edu/bmad/tao.html), built on
[PyTao](https://github.com/bmad-sim/pytao).

Status: early development.

## Features

Each section is its own window, so you can arrange them across screens. Every
window has the same menu bar (File, Tao, Plot, Window, Help), and the Window menu
(Ctrl+1 … Ctrl+5) brings any section back. Window positions and the open plots are
remembered between sessions; Window > Tile Windows lays them out again.

- **Startup window:** when `tao-gui` is run with no arguments and there is no
  `tao.init` in the current directory, this is the only window that opens. Choose an
  init file and/or lattice file, the working directory, other input files (plot,
  data, variable, beam, startup) and options (no plotting, skip startup file, no
  radiation integrals, no smooth-line calc, RF on, debug, extra Tao arguments). It
  shows the Tao command line it will use and keeps a list of recent startups. The
  other windows open once Tao has started; if Tao reports an error, the startup
  window stays open with the message. File > Open brings it back to reinitialize.
- **Console** (main window): Tao command line with history (Up/Down). Anything the
  GUI doesn't have a widget for still works here. Closing it quits.
- **Plot windows:** any Tao plot template (beta, orbit, floor_plan, …), drawn with
  matplotlib from Tao's `pipe` data, with the lattice layout under s-based plots.
  Plot > New Plot Window adds more. Plots redraw after every change to Tao's state.
  - Zooming one s-based plot zooms all of them (Plot > Link s-Axis Zoom; Ctrl+0
    resets).
  - Clicking a plot selects the element there; the selected element is shaded in
    every plot.
- **Lattice:** element table per branch, with a name or key filter (wildcards `*`
  and `%`). Select an element to see its attributes; edit a value to issue `set ele`.
- **Data:** d2/d1 tree and the datums of the chosen d1 array. Edit meas and weight,
  toggle use, or apply use/veto/meas = model to the whole array.
- **Variables:** v1 list and its variables. Edit model, meas and weight, toggle use,
  or use/veto/model = design for the whole array.
- **Optimizer:** choose the optimizer and cycles/loops, run it (Tao > Run Optimizer,
  Ctrl+R), and see the merit and the `show merit` table.

Tao always runs inside the GUI process on one background thread, so the windows stay
responsive while Tao computes. Tao's own plot window is turned off
(`-noplot -external_plotting`). While the optimizer runs, the windows respond, but
Tao commands wait until it finishes.

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

The tests start Tao on the small FODO ring in `tests/files` (with two data and two variables) and run headless
(`QT_QPA_PLATFORM=offscreen`).

### Layout

| Module | Role |
| --- | --- |
| `tao_worker.py` | `TaoClient`/`TaoWorker`: all Tao calls go through one worker thread |
| `application.py` | `TaoGui`: creates the windows, shared menus, selection and linked zoom |
| `windows.py` | Top-level window classes |
| `plots.py` | Plot panels (PyTao graph data → matplotlib) |
| `lattice.py` | Element table and attribute editor |
| `tables.py` | Data and variable browsers |
| `optimizer.py` | Optimizer window |
| `console.py` | Command console |
