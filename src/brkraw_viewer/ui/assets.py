from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import cast, Tuple

import tkinter as tk
from PIL import Image, ImageTk


def load_icon(name: str, size: tuple[int, int] | None = None) -> tk.PhotoImage | None:
    """Load an icon from the package assets directory, optionally resized."""
    try:
        return _load_icon_cached(name, size)
    except Exception:
        return None


@lru_cache(maxsize=64)
def _load_icon_cached(name: str, size: Tuple[int, int] | None) -> tk.PhotoImage:
    assets_dir = Path(__file__).resolve().parents[1] / "assets"
    icon_path = assets_dir / name
    img = Image.open(icon_path)
    if size is not None:
        resample = getattr(Image, "Resampling", Image)
        lanczos = getattr(resample, "LANCZOS", None)
        if lanczos is None:
            lanczos = getattr(Image, "LANCZOS", 1)
        img = img.resize(size, lanczos)
    return cast(tk.PhotoImage, ImageTk.PhotoImage(img))
