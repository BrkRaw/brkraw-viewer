from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import cast, Tuple

import tkinter as tk
from PIL import Image, ImageTk, ImageOps


def load_icon(
    name: str,
    size: tuple[int, int] | None = None,
    *,
    invert: bool = False,
) -> tk.PhotoImage | None:
    """Load an icon from the package assets directory, optionally resized."""
    try:
        return _load_icon_cached(name, size, invert)
    except Exception:
        return None


@lru_cache(maxsize=64)
def _load_icon_cached(name: str, size: Tuple[int, int] | None, invert: bool) -> tk.PhotoImage:
    assets_dir = Path(__file__).resolve().parents[1] / "assets"
    icon_path = assets_dir / name
    img = Image.open(icon_path)
    if invert:
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA")
        alpha = img.getchannel("A") if img.mode == "RGBA" else None
        base = img.convert("RGB")
        base = ImageOps.invert(base)
        img = base.convert("RGBA")
        if alpha is not None:
            img.putalpha(alpha)
    if size is not None:
        resample = getattr(Image, "Resampling", Image)
        lanczos = getattr(resample, "LANCZOS", None)
        if lanczos is None:
            lanczos = getattr(Image, "LANCZOS", 1)
        img = img.resize(size, lanczos)
    return cast(tk.PhotoImage, ImageTk.PhotoImage(img))
