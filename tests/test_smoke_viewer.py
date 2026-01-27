import os
import sys

import tkinter as tk

import pytest

from brkraw_viewer.app.controller import ViewerController
from brkraw_viewer.ui.main import MainWindow


def _has_display() -> bool:
    if sys.platform.startswith("win"):
        return True
    if sys.platform == "darwin":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def test_viewer_app_init_smoke() -> None:
    if not _has_display():
        pytest.skip("No display available for Tk")
    if os.environ.get("BRKRAW_VIEWER_SMOKE") != "1":
        pytest.skip("Set BRKRAW_VIEWER_SMOKE=1 to enable GUI smoke test.")
    try:
        root = tk.Tk()
        root.withdraw()
        controller = ViewerController()
        MainWindow(root, controller)
        root.update_idletasks()
        root.destroy()
    except Exception as exc:
        if "tk" in exc.__class__.__name__.lower():
            pytest.skip(f"Tk not available: {exc}")
        raise
