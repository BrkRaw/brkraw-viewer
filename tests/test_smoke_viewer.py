import os
import sys

import pytest

from brkraw_viewer.apps.viewer import ViewerApp


def _has_display() -> bool:
    if sys.platform.startswith("win"):
        return True
    if sys.platform == "darwin":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def test_viewer_app_init_smoke() -> None:
    if not _has_display():
        pytest.skip("No display available for Tk")
    try:
        app = ViewerApp(path=None, scan_id=None, reco_id=None, info_spec=None)
    except Exception as exc:
        if "tk" in exc.__class__.__name__.lower():
            pytest.skip(f"Tk not available: {exc}")
        raise
    try:
        app.update_idletasks()
    finally:
        app.destroy()
