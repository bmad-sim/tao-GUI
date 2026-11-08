# tao-GUI

A Qt desktop GUI for [Tao](https://www.classe.cornell.edu/bmad/tao.html), built on
[PyTao](https://github.com/bmad-sim/pytao).

Status: early development.

## Features

Window positions and the open plots are
remembered between sessions; Window > Tile Windows lays them out again.

- **Startup window:** when `tao-gui` is run with no arguments, this is the only
  window that opens. If the current directory has a `tao.init`, it is already set up
  to use it: press Start Tao, or change the files and options first. Choose an
  init file and/or lattice file and the working directory. Below them, in two
  columns: the beam, data, startup and plot files, and the beam init position,
  variable and building wall files. A working directory that has a `tao.init` is
  enough on its own. Empty file fields use the init file's setting, which is
  shown greyed in the field.
  - Options the init file can also set (Plotting, Compute radiation integrals,
    Smooth-line calc, RF on) have three states: **Default**, **On** and **Off**.
    Default leaves the choice to the init file (its `tao_params` namelist) or, if it
    doesn't set it, to Tao's built-in default, which the "Default when init file absent"
    column shows. Hover over a menu to see whether the init file sets it. On and Off
    override the init file: they are applied with `set global …` right after Tao
    starts.
  - Checkboxes:
    - **Use init file:** unchecked, no init file is read (`-noinit`), not even a
      `tao.init` in the working directory, and a lattice file is required.
    - **Run startup file:** unchecked, no startup file is run (`-nostartup`), not
      even one in the working directory.
    - **Reverse lattice** (`-reverse`) and **Debug**.
  - **Slice lattice** and **Start branch at** pass `-slice_lattice` and
    `-start_branch_at`.
  - **Extra commands:** Tao commands separated by `;`, run right after startup
    (after the startup file).
  - **Extra Tao arguments:** any other switches.
  - The window shows the Tao command line it will use, and keeps a list of recent
    startups. The other windows open once Tao has started; if Tao reports an error,
    the startup window stays open with the message. File > Open brings it back to
    reinitialize.
- **Main window:** opens on top of the others. Closing it quits.
  - **Command file** box (top): runs Tao's `call` command. Type a file name and any
    arguments, or use Browse…, then Call (or Enter). Past calls are kept in the list,
    latest first, between sessions.
  - **Console** (bottom): Tao command line with history (Up/Down), and the output of
    every command the GUI runs. Anything the GUI doesn't have a widget for still
    works here.
- **Plot windows:** any Tao plot template (beta, orbit, floor_plan, …), drawn with
  matplotlib from Tao's `pipe` data, with the lattice layout under s-based plots.
  Plot > New Plot Window adds more. Plots redraw after every change to Tao's state.
  Zooming one s-based plot zooms all of them, and clicking a plot selects the element
  there. See [Working with plots](#working-with-plots).
- **Lattice:** element table per branch, with a name or key filter (wildcards `*`
  and `%`). Select an element to see its attributes; edit a value to issue `set ele`.
- **Data:** d2/d1 tree and the datums of the chosen d1 array. Edit meas and weight,
  toggle use, or apply use/veto/meas = model to the whole array.
- **Variables:** v1 list and its variables. Edit model, meas and weight, toggle use,
  or use/veto/model = design for the whole array.
- **Datum and variable parameters:** double-click a row in the Data or Variables
  window to open a window with every parameter of that datum or variable. Parameters
  Tao lets you set are editable (`set data` / `set var`); the rest are greyed out.
  "Two columns" (the default) shows them in two parameter/value column pairs; untick it for one.
  In the tables, edit a cell by clicking it once its row is selected, or with F2.
- **Change** (Tao > Change, Ctrl+6): a form for Tao's `change` command: element
  attributes, variables, particle_start and the tunes. Choose how to change (add,
  set `@`, design + `d`, percent `%`), see the command it will run, and Tao's
  report (old and new values, change in merit) below. "Use selected" fills in the
  element selected in the Lattice window or a plot.
- **Set** (Tao > Set, Ctrl+7): Tao's `set` command. Pick a group (global,
  bmad_com, beam, beam_init, space_charge_com, ptc_com, opti_de_param) to see all of
  its parameters; edit the settable ones. A `set` line below runs any other
  subcommand, with a history of past entries.
- **Single Mode** (Tao > Single Mode, Ctrl+8): the variables bound to keys
  (`key_bound`, `key_delta`), ten at a time as in Tao's single mode. Step them with
  the buttons or Tao's keys (1…0 up, q…p down, Shift for ×10; arrows change the bank
  and scale the deltas), scale all deltas, and save and restore values.
- **Show** (Tao > Show, Ctrl+9): any of Tao's `show` subcommands. Pick one from the
  list, add arguments ("Use selected" fills in the selected element), and Show;
  "Update automatically" re-runs it after every change to Tao's state, and Help
  shows Tao's help for the subcommand. Past commands are kept in the list.
- **Shapes** (Plot > Shapes): the element shapes of the floor plan and lattice
  layout drawings, in the order Tao matches them (an element is drawn with the first
  shape whose Ele ID matches; *Multi* lets further matches be drawn too). Edit any cell
  (Ele ID, shape, color, size, label, draw, multi, line width, offset); add a shape
  below the selected one, delete one, or move one up or down. Plots redraw at once.
- **Optimizer:** choose the optimizer and cycles/loops, run it (Tao > Run Optimizer,
  Ctrl+R), and see the merit and the `show merit` table.

Tao always runs inside the GUI process on one background thread, so the windows stay
responsive while Tao computes. Tao's own plot window is turned off
(`-noplot -external_plotting`). While the optimizer runs, the windows respond, but
Tao commands wait until it finishes.

## Working with plots

Each plot window has a bar along the top:

- **Plot:** the Tao plot template shown. Pick one from the list, or type a template
  name and press Enter.
- **Lattice layout:** show or hide the lattice layout strip under the plot. It is
  only there for plots against s that can have one. Turning the strip on or off
  keeps the plot's height; the window grows or shrinks instead.
- **Toolbar** (matplotlib's navigation toolbar), described below.

### Zooming and panning

| Button | What it does |
|---|---|
| Home | Back to the full plot range. |
| Back / Forward | Step through the views you have zoomed or panned to. |
| Pan | Left-drag moves the plot. Right-drag zooms: drag right or up to zoom in, left or down to zoom out. Hold **x** or **y** while dragging to pan or zoom only that axis; hold **Ctrl** to keep the aspect ratio. |
| Zoom | Left-drag a rectangle to zoom into it; right-drag a rectangle to zoom out. Hold **x** or **y** to zoom only that axis. |
| Subplots | Adjust the margins and spacing of the graphs. |
| Customize | Edit axis limits, labels, scales and line styles. |
| Save | Save the plot as an image (PNG, PDF, SVG, …). |

Pan and Zoom stay on until you click the button again. Click the canvas first if
holding **x**, **y** or **Ctrl** has no effect, since the keys go to the canvas
only when it has focus. The mouse wheel does not zoom.

### Linked s-axis zoom

When **Plot > Link s-Axis Zoom** is on (the default), changing the s range of one
plot against s, by zooming, panning, Home, Back or Forward, gives every other
s-based plot window the same s range. The vertical axes are not linked. Plots that
are not against s, such as floor_plan, are not affected.

- **Plot > Reset Zoom** (Ctrl+0) returns every plot to its full range.
- Zoom ranges survive redraws: changing a variable, running the optimizer or
  **Plot > Refresh All** (F5) keeps the range you are looking at.
- A newly opened plot window starts at the linked range.

### Selecting elements

With neither Pan nor Zoom active, click a plot against s to select the lattice
element at that s. The element is shaded in every plot and selected in the
Lattice window, where its attributes are shown. Selecting an element in the
Lattice window shades it in the plots too.

In a floor plan, clicking an element selects it in the same way.

**Shift-click** an element in a lattice layout (the strip under a plot, or the
lat_layout plot) or in a floor plan to also open a window with its attributes.
They are editable, issuing `set ele`, as in the Lattice window. Shift-clicking other
plots selects the element without opening a window.

Shift-clicks also work while Pan or Zoom is active. A shift-click there is a press
and release without moving the mouse. A shift-drag still pans or zooms, and plain
clicks do nothing in those modes.

## Install

Get the code first; the install commands below are run from this checkout:

```bash
git clone https://github.com/bmad-sim/tao-GUI.git
cd tao-GUI
```

Tao and PyTao are easiest to get from conda-forge:

```bash
conda create -n tao-gui -c conda-forge bmad pytao pyside6 matplotlib
conda activate tao-gui
pip install --no-deps -e .
```

To use your own Tao build instead, set `ACC_ROOT_DIR` (PyTao finds `libtao` in
`$ACC_ROOT_DIR/production/lib`) and install into a Python environment that has
PyTao, for example a venv:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e /path/to/pytao   # or: pip install pytao
pip install -e .
```

### Where the `tao-gui` command comes from

`pip install` creates the `tao-gui` command: `pyproject.toml` declares it under
`[project.scripts]`, and pip writes a small launcher script into the environment's
`bin` directory (`$CONDA_PREFIX/bin` for conda, `.venv/bin` for a venv). The shell
finds it because activating the environment puts that `bin` directory on your
`PATH`. So:

- Activate the environment (`conda activate tao-gui` or `source .venv/bin/activate`)
  in each new shell before running `tao-gui`.
- Without activating, run the launcher by its full path, e.g.
  `/path/to/tao-GUI/.venv/bin/tao-gui`, or run the package with that environment's
  Python: `python -m tao_gui`.
- `which tao-gui` shows which launcher the shell will use.

With `-e` (editable install) the launcher runs the code in this checkout, so a
`git pull` takes effect without reinstalling.

## Run

```bash
tao-gui -init tao.init           # any Tao command-line arguments
tao-gui -lattice_file my.bmad
tao-gui                          # startup window (ready to use ./tao.init if present)
```

Run it from the directory you would run Tao from: Tao resolves relative file
names, such as those in `tao.init`, from the current directory.

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
| `details.py` | Parameter window for one datum or variable |
| `optimizer.py` | Optimizer window |
| `change.py` | Change window (`change` command) |
| `set_window.py` | Set window (`set` command) |
| `single_mode.py` | Single Mode window (key-bound variables) |
| `show_window.py` | Show window (`show` command) |
| `shapes_window.py` | Shapes window (floor_plan and lat_layout element shapes) |
| `console.py` | Main window contents: command-file box and Tao console |
