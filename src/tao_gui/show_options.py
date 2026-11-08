"""What each ``show`` subcommand takes: switches, choices and arguments.

Read off Tao's ``tao_show_this.f90`` (how each switch is parsed) and the
switch lists in ``tao_switches_for`` (tao_command_names_mod.f90):

* ``Flag``: a switch that is on or off (a check box). With an ``Arg`` the
  switch takes a value, shown next to the check box.
* ``Choice``: switches that set the same thing in Tao, so only one of them
  counts (radio buttons). The first option is Tao's default (no switch).
* ``Positional``: an argument after the switches.

``Arg.kind`` says how the value is picked (see ``show_window.ArgWidget``):
element, universe, branch, data, variable, plot, graph, curve, attribute,
format, track_format, int, float, file, text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple, Union


@dataclass(frozen=True)
class Arg:
    kind: str
    placeholder: str = ""
    required: bool = True  # False: the switch may be given without a value
    repeat: str = ""  # each word becomes "<repeat> <word>" (e.g. "-attribute")


@dataclass(frozen=True)
class Flag:
    switch: str
    tip: str = ""
    arg: Optional[Arg] = None


@dataclass(frozen=True)
class Option:
    switches: str  # "" for Tao's default; may be several ("-orbit -floor_coords")
    label: str
    tip: str = ""
    arg: Optional[Arg] = None


@dataclass(frozen=True)
class Choice:
    label: str
    options: Tuple[Option, ...]
    tip: str = ""


@dataclass(frozen=True)
class Positional:
    label: str
    arg: Arg
    tip: str = ""
    optional: bool = True


Item = Union[Flag, Choice]


@dataclass(frozen=True)
class ShowSpec:
    name: str
    summary: str
    items: Tuple[Item, ...] = ()
    positionals: Tuple[Positional, ...] = ()


def _spec(name, summary, *items, positionals=()):
    return ShowSpec(name, summary, tuple(items), tuple(positionals))


ELE = Arg("element", "element name, index or list")
UNI = Arg("universe")
BRANCH = Arg("branch")
INT = Arg("int")
TRACK_FMT = Arg("track_format", "format (blank: default, \"no\": hide)", required=False)

LATTICE = Choice("Lattice", (Option("", "model"), Option("-design", "design"),
                             Option("-base", "base")),
                 "Which lattice to use (Tao's model, design or base lattice)")
UNIVERSE = Flag("-universe", "Universe to use (default: the default universe)", UNI)

MAP_ITEMS: Tuple[Item, ...] = (
    Choice("Output", (Option("", "standard"),
                      Option("-lattice_format", "-lattice_format",
                             "Bmad lattice format (taylor element)"),
                      Option("-scibmad", "-scibmad", "SciBmad format",
                             Arg("text", "suffix", required=False)))),
    Flag("-elements", "Matrices of each of these elements", ELE),
    Flag("-order", "Map order", INT),
    Flag("-s", "Locations are s positions (in meters)"),
    Flag("-eigen_modes", "Also show the eigen modes"),
    Flag("-inverse", "Inverse map"),
    Flag("-radiation", "Include radiation"),
    Flag("-ptc", "Use PTC"),
    Flag("-angle_coordinates", "Use angle (x') coordinates"),
    Flag("-noclean", "Do not drop tiny terms"),
    Flag("-number_format", "Number format, e.g. es12.4", Arg("format")),
    UNIVERSE,
)
MAP_POSITIONALS = (Positional("From", ELE), Positional("To", ELE))

SPECS: Tuple[ShowSpec, ...] = (
    _spec("alias", "Command aliases."),
    _spec("attribute", "Values of an attribute for a list of elements.",
          Flag("#format", "Fortran format for the values, e.g. es16.8", Arg("format")),
          positionals=(Positional("Elements", ELE, optional=False),
                       Positional("Attribute", Arg("attribute"), optional=False))),
    _spec("beam", "Beam initialization, or beam statistics at an element.",
          Choice("Show", (Option("", "beam_init / element"),
                          Option("-lattice", "-lattice", "Sigma matrix, etc. at the element"),
                          Option("-comb", "-comb", "Sigma matrix, etc. at a comb index")),
                 "-lattice and -comb set the same thing in Tao"),
          UNIVERSE,
          Flag("-z", "Parameters of a slice of the bunch between z1 and z2",
               Arg("text", "z1 z2")),
          positionals=(Positional("Element / comb index", ELE),)),
    _spec("branch", "Lattice branches.", UNIVERSE),
    _spec("building_wall", "The building wall."),
    _spec("chromaticity", "Chromaticity, momentum compaction and phase slip.",
          Flag("-taylor", "Show the Taylor maps"), UNIVERSE),
    _spec("constraints", "Optimization constraints."),
    _spec("control", "Lords and slaves of an element.",
          positionals=(Positional("Element", ELE, optional=False),)),
    _spec("curve", "Attributes of a plot curve.",
          Flag("-line", "Also show the line points"),
          Flag("-symbol", "Also show the symbol points"),
          Flag("-no_header", "No header lines"),
          positionals=(Positional("Curve", Arg("curve"), optional=False),)),
    _spec("data", "Data (d2 arrays, a d1 array, or datums).",
          positionals=(Positional("Data", Arg("data"),
                                  "Blank: all d2 data. E.g. orbit, orbit.x, orbit.x[3:9]"),)),
    _spec("debug", "Debug information."),
    _spec("derivative", "dModel/dVariable derivatives.",
          Flag("-derivative_recalc", "Recalculate the derivatives first"),
          positionals=(Positional("Data", Arg("data")), Positional("Variables", Arg("variable")))),
    _spec("dynamic_aperture", "Dynamic aperture."),
    _spec("element", "Information on lattice elements.",
          LATTICE,
          Flag("-attributes", "All attributes, including those that are zero"),
          Flag("-all", "Same as -attributes -floor_coords -taylor -wall -xfer_mat"),
          Flag("-everything", "Same as -all"),
          Flag("-data", "Data associated with the element"),
          Flag("-field", "Field maps / grid data"),
          Flag("-floor_coords", "Global floor coordinates at the exit end"),
          Flag("-taylor", "The element's Taylor map, if it has one"),
          Flag("-xfer_mat", "6x6 transfer matrix and 0th order map"),
          Flag("-wall", "Wall (beam chamber) information"),
          Flag("-ptc", "Associated PTC fibre (other switches are ignored)"),
          Flag("-radiation_kick", "Radiation kick parameters"),
          Flag("-no_slaves", "With wild cards: skip super and multipass slaves"),
          Flag("-no_super_slaves", "With wild cards: skip super slaves"),
          Flag("-internal", "Internal parameters (for debugging)"),
          positionals=(Positional("Element", ELE, optional=False),)),
    _spec("emittance", "Emittances.",
          Choice("Show", (Option("", "emittances"),
                          Option("-xmatrix", "-xmatrix", "Transfer matrix"),
                          Option("-sigma_matrix", "-sigma_matrix", "Sigma matrix"))),
          Flag("-element", "Element to evaluate at", ELE),
          UNIVERSE),
    _spec("field", "Electromagnetic field at a point in an element.",
          Choice("s is", (Option("", "relative to element start"),
                          Option("-percent_len", "-percent_len", "Fraction of the element length"),
                          Option("-absolute_s", "-absolute_s", "Absolute s position")),
                 "-percent_len and -absolute_s set the same thing in Tao"),
          Flag("-derivatives", "Also show field derivatives"),
          Flag("-grid_pt", "x, y, s are grid point indices"),
          positionals=(Positional("Element", ELE, optional=False),
                       Positional("x", Arg("float"), optional=False),
                       Positional("y", Arg("float"), optional=False),
                       Positional("s", Arg("float"), optional=False),
                       Positional("t or z", Arg("float")))),
    _spec("global", "Global parameters.",
          Choice("Show", (Option("", "Tao globals"),
                          Option("-optimization", "-optimization"),
                          Option("-bmad_com", "-bmad_com"),
                          Option("-space_charge_com", "-space_charge_com"),
                          Option("-ptc_com", "-ptc_com"),
                          Option("-ran_state", "-ran_state", "Random number generator state"),
                          Option("-environment", "-environment",
                                 "Environment variables defined in the lattice files"),
                          Option("-internal", "-internal")),
                 "Only one section is shown")),
    _spec("graph", "Attributes of a plot graph.",
          Flag("-rms", "Also show RMS values"),
          Flag("-debug", "Debug information"),
          positionals=(Positional("Graph", Arg("graph"), optional=False),)),
    _spec("history", "Command history.",
          Flag("-all", "The whole history"),
          Flag("-filed", "Number as for a command file"),
          Flag("-no_num", "No command numbers"),
          positionals=(Positional("Number to show", INT),)),
    _spec("hom", "Higher order modes of lcavities."),
    _spec("internal", "Internal information (for debugging).",
          Choice("Show", (Option("-pipe", "-pipe", "Pipe interface buffers"),
                          Option("-control", "-control", "Control information of an element",
                                 ELE)))),
    _spec("key_bindings", "Single mode key bindings."),
    _spec("lattice", "A table of lattice elements.",
          Choice("Columns", (
              Option("", "standard"),
              Option("-orbit", "-orbit"),
              Option("-floor_coords", "-floor_coords"),
              Option("-orbit -floor_coords", "-orbit -floor_coords"),
              Option("-spin", "-spin"),
              Option("-orbit -spin", "-orbit -spin"),
              Option("-energy", "-energy"),
              Option("-radiation_integrals", "-radiation_integrals"),
              Option("-sum_radiation_integrals", "-sum_radiation_integrals"),
              Option("-6d_radiation_integrals", "-6d_radiation_integrals"),
              Option("-ri_radiation_integrals", "-ri_radiation_integrals"),
              Option("-attribute", "-attribute", "Columns of the given attributes",
                     Arg("attribute", "attribute names", repeat="-attribute")),
              Option("-custom", "-custom", "Columns from a custom_show_list namelist file",
                     Arg("file"))),
                 "Which columns to show (these switches set the same thing in Tao)"),
          LATTICE,
          Choice("Evaluate at", (Option("", "element end"), Option("-beginning", "-beginning"),
                                 Option("-middle", "-middle"))),
          Choice("Elements", (Option("", "default"),
                              Option("-tracking_elements", "-tracking_elements",
                                     "Only elements in the tracking part"),
                              Option("-lords", "-lords", "Only lord elements"))),
          Choice("Undefined values", (Option("", "blank"),
                                      Option("-0undef", "-0undef", "Print undefined as 0"),
                                      Option("-undef0", "-undef0",
                                             "Print undefined as 0 using the column format"))),
          Flag("-all", "All elements (not just the first 200)"),
          Flag("-no_slaves", "Skip super and multipass slaves"),
          Flag("-no_super_slaves", "Skip super slaves"),
          Flag("-rms", "Show mean and RMS at the bottom"),
          Flag("-no_label_lines", "No header or tail lines"),
          Flag("-no_tail_lines", "No tail lines"),
          Flag("-branch", "Lattice branch", BRANCH),
          UNIVERSE,
          Flag("-s", "Give the range as s1:s2 positions (in meters)"),
          Flag("-blank_replacement", "String to print in place of blank fields",
               Arg("text", "string")),
          Flag("-remove_line_if_zero", "Remove lines where this column is zero",
               Arg("int")),
          positionals=(Positional("Elements", ELE, "Blank: the first elements. E.g. 1:100, q*"),)),
    _spec("matrix", "Transfer matrices.", *MAP_ITEMS, positionals=MAP_POSITIONALS),
    _spec("merit", "Merit function contributions.",
          Flag("-derivative", "Merit derivative information"),
          Flag("-merit_only", "Only the merit value")),
    _spec("normal_form", "Normal form (being reworked in Tao)."),
    _spec("optimizer", "Optimizer settings."),
    _spec("orbit", "Orbit at an element.",
          positionals=(Positional("Element", ELE, optional=False),)),
    _spec("particle", "Particles of a tracked beam.",
          Flag("-bunch", "Bunch index", INT),
          Flag("-particle", "Particle index", INT),
          Flag("-element", "Element", ELE),
          Flag("-lost", "Lost particle positions"),
          Flag("-all", "All particles")),
    _spec("plot", "Plot regions, templates and settings.",
          Choice("Show", (Option("", "regions / a plot"),
                          Option("-templates", "-templates"),
                          Option("-floor_plan", "-floor_plan", "Floor plan settings and shapes"),
                          Option("-lat_layout", "-lat_layout",
                                 "Lattice layout settings and shapes"),
                          Option("-page", "-page", "Plot page settings")),
                 "These switches set the same thing in Tao"),
          positionals=(Positional("Plot / template", Arg("plot")),)),
    _spec("ptc", "PTC parameters.", Flag("-emittance", "PTC emittance calculation")),
    _spec("radiation_integrals", "Radiation integrals.",
          Flag("-branch", "Lattice branch", BRANCH),
          positionals=(Positional("Universe", UNI),)),
    _spec("rampers", "Ramper elements.",
          Flag("-energy_show", "Include energy ramp information"), UNIVERSE),
    _spec("spin", "Spin information.",
          Choice("Show", (Option("", "1-turn analysis"),
                          Option("-element", "-element", "Analysis at an element, or between two",
                                 Arg("element", "{ref_ele} ele")),
                          Option("-isf", "-isf", "Invariant spin field"),
                          Option("-spin_tune", "-spin_tune", "Spin tune")),
                 "These switches set the same thing in Tao"),
          Flag("-g_map", "Show the G-matrix"),
          Flag("-flip_n_axis", "Flip the n-axis"),
          Flag("-n_axis", "n-axis", Arg("text", "nx, ny, nz")),
          Flag("-l_axis", "l-axis", Arg("text", "lx, ly, lz")),
          Flag("-ignore_kinetic", "Ignore the kinetic term for these elements", ELE),
          Flag("-x_zero", "Zero the x component for these elements", ELE),
          Flag("-y_zero", "Zero the y component for these elements", ELE),
          Flag("-z_zero", "Zero the z component for these elements", ELE)),
    _spec("string", "Print a string (with `expression` substitution).",
          positionals=(Positional("String", Arg("text", "text to print"), optional=False),)),
    _spec("symbolic_numbers", "Symbolic constants.",
          Choice("Show", (Option("", "user defined"),
                          Option("-physical_constants", "-physical_constants"),
                          Option("-lattice_constants", "-lattice_constants")))),
    _spec("taylor_map", "Transfer maps.", *MAP_ITEMS, positionals=MAP_POSITIONALS),
    _spec("top10", "The ten largest merit contributions.",
          Flag("-derivative", "Merit derivative information"),
          Flag("-merit_only", "Only the merit value")),
    _spec("track", "Tracking along the lattice.",
          LATTICE,
          Flag("-s", "s position", TRACK_FMT),
          Flag("-position", "Position", TRACK_FMT),
          Flag("-momentum", "Momentum", TRACK_FMT),
          Flag("-velocity", "Velocity", TRACK_FMT),
          Flag("-energy", "Energy", TRACK_FMT),
          Flag("-time", "Time", TRACK_FMT),
          Flag("-spin", "Spin", TRACK_FMT),
          Flag("-twiss", "Twiss parameters", TRACK_FMT),
          Flag("-dispersion", "Dispersion", TRACK_FMT),
          Flag("-e_field", "Electric field", TRACK_FMT),
          Flag("-b_field", "Magnetic field", TRACK_FMT),
          Flag("-element", "Element", ELE),
          Flag("-range", "s range", Arg("text", "s1 s2")),
          Flag("-points", "Number of points", INT),
          Flag("-branch", "Lattice branch", BRANCH),
          UNIVERSE,
          Flag("-no_label_lines", "No header lines")),
    _spec("tune", "Tunes."),
    _spec("twiss_and_orbit", "Twiss parameters and orbit at an s position.",
          LATTICE, Flag("-branch", "Lattice branch", BRANCH), UNIVERSE,
          positionals=(Positional("s", Arg("float"), "s position in meters", optional=False),)),
    _spec("universe", "Universe information.",
          Flag("-branch", "Lattice branch", BRANCH),
          positionals=(Positional("Universe", UNI),)),
    _spec("use", "Data and variables in use (as Tao commands)."),
    _spec("value", "Value of an expression.",
          Flag("#format", "Fortran format, e.g. f10.4", Arg("format")),
          positionals=(Positional("Expression", Arg("text", "e.g. lat::beta.a[3]"),
                                  optional=False),)),
    _spec("variables", "Variables.",
          Flag("-bmad_format", "In Bmad lattice format"),
          Flag("-good_opt_only", "Only variables used in the optimization"),
          Flag("-no_label_lines", "No header lines"),
          UNIVERSE,
          positionals=(Positional("Variables", Arg("variable"),
                                  "Blank: all v1 arrays. E.g. quad_k1, quad_k1[10]"),)),
    _spec("version", "Tao version."),
    _spec("wake_elements", "Elements with wakes."),
    _spec("wall", "Chamber wall sections.",
          Flag("-branch", "Lattice branch", BRANCH),
          Flag("-section", "A single wall section", INT),
          Flag("-angle", "Angle", Arg("float")),
          Flag("-s", "Sections between s positions", Arg("text", "s1:s2")),
          positionals=(Positional("Sections", Arg("text", "n1:n2")),)),
    _spec("wave", "Wave analysis."),
)

SPEC_BY_NAME: Dict[str, ShowSpec] = {spec.name: spec for spec in SPECS}


def element_fields(spec: ShowSpec) -> int:
    """Number of places that take an element (positionals first)."""
    n = sum(p.arg.kind == "element" for p in spec.positionals)
    for item in spec.items:
        if isinstance(item, Flag) and item.arg is not None and item.arg.kind == "element":
            n += 1
        elif isinstance(item, Choice):
            n += sum(o.arg is not None and o.arg.kind == "element" for o in item.options)
    return n
