from __future__ import annotations

import sys

import tkinter as tk

from brkraw_viewer.app.controller import ViewerController
from brkraw_viewer.ui.main import MainWindow


def main() -> int:
    root = tk.Tk()
    controller = ViewerController()
    MainWindow(root, controller)
    try:
        root.update_idletasks()
        root.update()
    finally:
        root.destroy()
    print("Addon smoke test: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
