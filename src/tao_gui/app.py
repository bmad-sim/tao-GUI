"""Entry point: ``tao-gui [tao command-line arguments]``."""

from __future__ import annotations

import shlex
import signal
import sys
from typing import List, Optional

APP_NAME = "Tao GUI"

USAGE = """\
usage: tao-gui [tao arguments]

Starts the Tao GUI. Arguments are passed to Tao as on its command line, e.g.

    tao-gui -init tao.init
    tao-gui -lattice_file my.bmad

With no arguments, a startup window opens where you choose the files and
options (it is also File > Open). If the current directory has a tao.init,
the window is ready to start Tao with it: just press Start Tao. Tao's own plot window is always off
(-noplot -external_plotting); the GUI draws the plots.
"""


def main(argv: Optional[List[str]] = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args and args[0] in ("-h", "--help"):
        print(USAGE)
        return 0

    from PySide6.QtWidgets import QApplication

    from . import macos
    from .application import TaoGui

    macos.set_app_name(APP_NAME)  # menu bar shows "Tao GUI", not "python3.x"
    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setOrganizationName("bmad-sim")
    app.setApplicationName("tao-gui")
    app.setQuitOnLastWindowClosed(False)  # the console window decides
    signal.signal(signal.SIGINT, signal.SIG_DFL)  # Ctrl-C in the terminal quits

    gui = TaoGui()
    app.aboutToQuit.connect(gui.shutdown)
    start(gui, args)
    return app.exec()


def start(gui, args: List[str]) -> None:
    """Start Tao from command-line arguments, or open the startup window.

    With no arguments the startup window always opens (a tao.init in the current
    directory is picked up there, and Start Tao is ready to press).
    """
    if args:
        # The GUI always runs Tao with -noplot; here it means "no plot windows".
        gui.launch(shlex.join(args), plotting="-noplot" not in args)
    else:
        gui.show_startup()  # the only window until Tao starts


if __name__ == "__main__":
    raise SystemExit(main())
