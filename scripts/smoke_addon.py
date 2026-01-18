from __future__ import annotations

import sys

from brkraw_viewer.apps.viewer import ViewerApp


def main() -> int:
    app = ViewerApp(path=None, scan_id=None, reco_id=None, info_spec=None)
    try:
        app.update_idletasks()
        app.update()
    finally:
        app.destroy()
    print("Addon smoke test: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
