from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Dict, Optional, Tuple

import numpy as np
from PIL import Image, ImageTk


ClickCallback = Callable[[str, int, int], None]


class OrthogonalCanvas(ttk.Frame):
    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent)
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self.columnconfigure(2, weight=1)
        self.rowconfigure(0, weight=1)

        self._canvas_zy = tk.Canvas(self, background="#111111", highlightthickness=0)
        self._canvas_xy = tk.Canvas(self, background="#111111", highlightthickness=0)
        self._canvas_xz = tk.Canvas(self, background="#111111", highlightthickness=0)

        self._canvas_zy.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self._canvas_xy.grid(row=0, column=1, sticky="nsew", padx=(0, 4))
        self._canvas_xz.grid(row=0, column=2, sticky="nsew")

        self._canvas_map = {"zy": self._canvas_zy, "xy": self._canvas_xy, "xz": self._canvas_xz}
        self._canvas_image_id: Dict[str, Optional[int]] = {"zy": None, "xy": None, "xz": None}
        self._canvas_text_id: Dict[str, Optional[int]] = {"zy": None, "xy": None, "xz": None}
        self._tk_images: Dict[str, Optional[ImageTk.PhotoImage]] = {"zy": None, "xy": None, "xz": None}
        self._markers: Dict[str, list[int]] = {"zy": [], "xy": [], "xz": []}
        self._click_callback: Optional[ClickCallback] = None

        self._last_views: Optional[Dict[str, Tuple[np.ndarray, Tuple[float, float]]]] = None
        self._last_titles: Optional[Dict[str, str]] = None
        self._last_message: Optional[str] = None
        self._last_is_error = False
        self._render_state: Dict[str, Tuple[int, int, int, int, int, int]] = {}

        for key, canvas in self._canvas_map.items():
            canvas.bind("<Configure>", self._on_resize)
            canvas.bind("<Button-1>", lambda event, view=key: self._on_click(view, event))

    def set_click_callback(self, callback: Optional[ClickCallback]) -> None:
        self._click_callback = callback

    def clear_markers(self) -> None:
        for key, canvas in self._canvas_map.items():
            for marker_id in self._markers[key]:
                try:
                    canvas.delete(marker_id)
                except Exception:
                    pass
            self._markers[key] = []

    def add_marker(self, view: str, row: int, col: int, color: str) -> None:
        state = self._render_state.get(view)
        if state is None:
            return
        img_h, img_w, offset_x, offset_y, target_w, target_h = state
        if img_h <= 0 or img_w <= 0:
            return
        display_row = img_h - 1 - row
        x = offset_x + (col + 0.5) * target_w / img_w
        y = offset_y + (display_row + 0.5) * target_h / img_h
        r = 4
        canvas = self._canvas_map[view]
        marker_id = canvas.create_oval(x - r, y - r, x + r, y + r, outline=color, width=2)
        self._markers[view].append(marker_id)

    def render_views(
        self,
        views: Dict[str, Tuple[np.ndarray, Tuple[float, float]]],
        titles: Dict[str, str],
    ) -> None:
        self._last_views = views
        self._last_titles = titles
        self._last_message = None
        self._last_is_error = False
        for key, canvas in self._canvas_map.items():
            img, res = views[key]
            title = titles.get(key, "")
            self._render_canvas(canvas, key, img, res, title)

    def show_message(self, message: str, *, is_error: bool = False) -> None:
        self._last_views = None
        self._last_titles = None
        self._last_message = message
        self._last_is_error = is_error
        for canvas in self._canvas_map.values():
            self._render_message(canvas, message, is_error=is_error)

    def _render_message(self, canvas: tk.Canvas, message: str, *, is_error: bool) -> None:
        canvas.delete("all")
        width = max(canvas.winfo_width(), 1)
        height = max(canvas.winfo_height(), 1)
        if is_error:
            canvas.create_line(10, 10, width - 10, height - 10, fill="#cc3333", width=3)
            canvas.create_line(10, height - 10, width - 10, 10, fill="#cc3333", width=3)
            color = "#cc3333"
        else:
            color = "#dddddd"
        canvas.create_text(
            10,
            10,
            anchor="nw",
            fill=color,
            text=message,
            font=("TkDefaultFont", 10, "bold"),
        )

    def _render_canvas(
        self,
        canvas: tk.Canvas,
        key: str,
        img: np.ndarray,
        res: Tuple[float, float],
        title: str,
    ) -> None:
        canvas.delete("all")
        self._markers[key] = []
        vmin, vmax = np.nanpercentile(img, (1, 99))
        if np.isclose(vmin, vmax):
            vmax = vmin + 1.0
        img_norm = np.clip((img - vmin) / (vmax - vmin), 0.0, 1.0)
        img_uint8 = (img_norm * 255).astype(np.uint8)
        img_display = np.flipud(img_uint8)

        pil_img = Image.fromarray(img_display, mode="L")
        canvas_w = max(canvas.winfo_width(), 1)
        canvas_h = max(canvas.winfo_height(), 1)
        width_mm = float(img.shape[1]) * res[0]
        height_mm = float(img.shape[0]) * res[1]
        if width_mm > 0 and height_mm > 0:
            aspect = width_mm / height_mm
        else:
            aspect = pil_img.width / max(pil_img.height, 1)
        canvas_aspect = canvas_w / max(canvas_h, 1)
        if canvas_aspect >= aspect:
            target_h = canvas_h
            target_w = max(int(target_h * aspect), 1)
        else:
            target_w = canvas_w
            target_h = max(int(target_w / aspect), 1)

        resampling = getattr(Image, "Resampling", Image)
        resample = getattr(resampling, "NEAREST")
        pil_img = pil_img.resize((target_w, target_h), resample)

        self._tk_images[key] = ImageTk.PhotoImage(pil_img)
        x = (canvas_w - target_w) // 2
        y = (canvas_h - target_h) // 2
        self._render_state[key] = (img.shape[0], img.shape[1], x, y, target_w, target_h)
        self._canvas_image_id[key] = canvas.create_image(
            x,
            y,
            anchor="nw",
            image=self._tk_images[key],
        )

        self._canvas_text_id[key] = canvas.create_text(
            10,
            10,
            anchor="nw",
            fill="#dddddd",
            text=title,
            font=("TkDefaultFont", 10, "bold"),
        )

    def _on_resize(self, *_: object) -> None:
        if self._last_message is not None:
            for canvas in self._canvas_map.values():
                self._render_message(canvas, self._last_message, is_error=self._last_is_error)
            return
        if self._last_views and self._last_titles:
            for key, canvas in self._canvas_map.items():
                img, res = self._last_views[key]
                title = self._last_titles.get(key, "")
                self._render_canvas(canvas, key, img, res, title)

    def _on_click(self, view: str, event: tk.Event) -> None:
        if self._click_callback is None:
            return
        state = self._render_state.get(view)
        if state is None:
            return
        img_h, img_w, offset_x, offset_y, target_w, target_h = state
        if img_h <= 0 or img_w <= 0:
            return
        x = event.x - offset_x
        y = event.y - offset_y
        if x < 0 or y < 0 or x > target_w or y > target_h:
            return
        col = int(x * img_w / max(target_w, 1))
        display_row = int(y * img_h / max(target_h, 1))
        row = img_h - 1 - display_row
        self._click_callback(view, row, col)
