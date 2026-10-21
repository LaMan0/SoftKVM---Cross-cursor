"""Point d'entrée de SoftKVM (utilisé par `python -m softkvm` et par le .exe)."""

import logging
import os
import sys
import tkinter as tk

from .gui import App


def _enable_dpi_awareness():
    """Sous Windows, tkinter, pynput et les hooks utilisent alors les mêmes pixels physiques."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (OSError, AttributeError):
        pass


def main():
    logging.basicConfig(
        filename=os.path.join(os.path.expanduser("~"), "softkvm.log"),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    _enable_dpi_awareness()
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
