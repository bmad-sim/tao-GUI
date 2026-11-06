"""Entry point: ``tao-gui [tao command-line arguments]``."""

from __future__ import annotations

import os
import shlex
import signal
import sys
from typing import List, Optional

USAGE = """\
usage: tao-gui [tao arguments]

Starts the Tao GUI. Arguments are passed to Tao as on its command line, e.g.

    tao-gui -init tao.init
    tao-gui -lattice_file my.bmad

With no arguments, Tao is started if a tao.init file is in the current
directory; otherwise use File > Open. Tao's own plot window is always off
(-noplot -external_plotting); the GUI draws the plots.
"""


def main(argv: Optional[List[str]] = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args and args[0] in ("-h", "--help"):
        print(USAGE)
        return 0

    from PySide6.QtWidgets import QApplication

    from .application import TaoGui

    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setOrganizationName("bmad-sim")
    app.setApplicationName("tao-gui")
    app.setQuitOnLastWindowClosed(False)  # the console window decides
    signal.signal(signal.SIGINT, signal.SIG_DFL)  # Ctrl-C in the terminal quits

    gui = TaoGui()
    app.aboutToQuit.connect(gui.shutdown)
    if args:
        gui.start_tao(shlex.join(args))
    elif os.path.exists("tao.init"):
        gui.start_tao("-init tao.init")
    else:
        gui.console.append("No tao.init here. Use File > Open to start Tao.")
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
