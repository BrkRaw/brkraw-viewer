from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Dict, Optional, Tuple

import numpy as np
from PIL import Image, ImageTk, ImageDraw


ClickCallback = Callable[[str, int, int], None]
ZoomCallback = Callable[[int], None]


class OrthogonalCanvas(ttk.Frame):
    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent)
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self.columnconfigure(2, weight=1)
        self.rowconfigure(0, weight=1)

        self._canvas_xz = tk.Canvas(self, background="#111111", highlightthickness=0)
        self._canvas_xy = tk.Canvas(self, background="#111111", highlightthickness=0)
        self._canvas_zy = tk.Canvas(self, background="#111111", highlightthickness=0)

        self._canvas_xz.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self._canvas_xy.grid(row=0, column=1, sticky="nsew", padx=(0, 4))
        self._canvas_zy.grid(row=0, column=2, sticky="nsew")

        self._canvas_map = {"xz": self._canvas_xz, "xy": self._canvas_xy, "zy": self._canvas_zy}
        self._canvas_image_id: Dict[str, Optional[int]] = {"zy": None, "xy": None, "xz": None}
        self._canvas_text_id: Dict[str, Optional[int]] = {"zy": None, "xy": None, "xz": None}
        self._tk_images: Dict[str, Optional[ImageTk.PhotoImage]] = {"zy": None, "xy": None, "xz": None}
        self._markers: Dict[str, list[int]] = {"zy": [], "xy": [], "xz": []}
        self._boxes: Dict[str, list[int]] = {"zy": [], "xy": [], "xz": []}
        self._marker_data: Dict[str, list[Tuple[int, int, str]]] = {"zy": [], "xy": [], "xz": []}
        self._box_data: Dict[str, list[Tuple[int, int, int, int, str, int]]] = {"zy": [], "xy": [], "xz": []}
        self._click_callback: Optional[ClickCallback] = None
        self._zoom_callback: Optional[ZoomCallback] = None
        self._capture_callback: Optional[Callable[[str], None]] = None

        self._last_views: Optional[Dict[str, Tuple[np.ndarray, Tuple[float, float]]]] = None
        self._last_titles: Optional[Dict[str, str]] = None
        self._last_crosshair: Optional[Dict[str, Tuple[int, int]]] = None
        self._last_show_crosshair: bool = False
        self._last_message: Optional[str] = None
        self._last_is_error = False
        self._render_state: Dict[str, Tuple[int, int, int, int, int, int]] = {}

        for key, canvas in self._canvas_map.items():
            canvas.bind("<Configure>", self._on_resize)
            canvas.bind("<Button-1>", lambda event, view=key: self._on_click(view, event))
            canvas.bind("<MouseWheel>", self._on_mousewheel)
            canvas.bind("<Button-4>", self._on_mousewheel)
            canvas.bind("<Button-5>", self._on_mousewheel)
            capture = tk.Button(
                canvas,
                text="◉",
                width=1,
                height=1,
                font=("TkDefaultFont", 10),
                bg="#111111",
                fg="#f6f6f6",
                activebackground="#3a3a3a",
                activeforeground="#ffff00",
                highlightthickness=0,
                borderwidth=0,
                command=lambda view=key: self._on_capture(view),
            )
            capture.place(relx=1.0, rely=1.0, x=0, y=0, anchor="se")

    def set_click_callback(self, callback: Optional[ClickCallback]) -> None:
        self._click_callback = callback

    def set_zoom_callback(self, callback: Optional[ZoomCallback]) -> None:
        self._zoom_callback = callback

    def set_capture_callback(self, callback: Optional[Callable[[str], None]]) -> None:
        self._capture_callback = callback

    def capture_view(self, view: str) -> Optional[Image.Image]:
        if view not in self._canvas_map or not self._last_views or not self._last_titles:
            return None
        canvas = self._canvas_map[view]
        canvas_w = max(canvas.winfo_width(), 1)
        canvas_h = max(canvas.winfo_height(), 1)
        img, res = self._last_views[view]
        title = self._last_titles.get(view, "")
        shared_scale = self._shared_scale()
        rendered = self._render_to_image(
            view=view,
            img=img,
            res=res,
            title=title,
            canvas_w=canvas_w,
            canvas_h=canvas_h,
            shared_scale=shared_scale,
        )
        return rendered

    def clear_markers(self) -> None:
        for key, canvas in self._canvas_map.items():
            for marker_id in self._markers[key]:
                try:
                    canvas.delete(marker_id)
                except Exception:
                    pass
            self._markers[key] = []
            self._marker_data[key] = []

    def clear_boxes(self) -> None:
        for key, canvas in self._canvas_map.items():
            for box_id in self._boxes[key]:
                try:
                    canvas.delete(box_id)
                except Exception:
                    pass
            self._boxes[key] = []
            self._box_data[key] = []

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
        self._marker_data[view].append((int(row), int(col), str(color)))

    def add_box(self, view: str, row0: int, col0: int, row1: int, col1: int, *, color: str, width: int = 2) -> None:
        state = self._render_state.get(view)
        if state is None:
            return
        img_h, img_w, offset_x, offset_y, target_w, target_h = state
        if img_h <= 0 or img_w <= 0:
            return
        r0 = max(0, min(int(row0), img_h - 1))
        r1 = max(0, min(int(row1), img_h - 1))
        c0 = max(0, min(int(col0), img_w - 1))
        c1 = max(0, min(int(col1), img_w - 1))
        row_min, row_max = sorted((r0, r1))
        col_min, col_max = sorted((c0, c1))
        disp_row_min = img_h - 1 - row_max
        disp_row_max = img_h - 1 - row_min
        x0 = offset_x + col_min * target_w / img_w
        x1 = offset_x + (col_max + 1) * target_w / img_w
        y0 = offset_y + disp_row_min * target_h / img_h
        y1 = offset_y + (disp_row_max + 1) * target_h / img_h
        canvas = self._canvas_map[view]
        box_id = canvas.create_rectangle(x0, y0, x1, y1, outline=color, width=width)
        self._boxes[view].append(box_id)
        self._box_data[view].append((int(row0), int(col0), int(row1), int(col1), str(color), int(width)))

    def render_views(
        self,
        views: Dict[str, Tuple[np.ndarray, Tuple[float, float]]],
        titles: Dict[str, str],
        *,
        crosshair: Optional[Dict[str, Tuple[int, int]]] = None,
        show_crosshair: bool = False,
    ) -> None:
        self._last_views = views
        self._last_titles = titles
        self._last_crosshair = crosshair
        self._last_show_crosshair = bool(show_crosshair)
        self._last_message = None
        self._last_is_error = False
        self._render_all_views()

    def show_message(self, message: str, *, is_error: bool = False) -> None:
        self._last_views = None
        self._last_titles = None
        self._last_message = message
        self._last_is_error = is_error
        for canvas in self._canvas_map.values():
            self._render_message(canvas, message, is_error=is_error)

    def show_message_on(self, view: str, message: str, *, is_error: bool = False) -> None:
        self._last_views = None
        self._last_titles = None
        self._last_message = message
        self._last_is_error = is_error
        for key, canvas in self._canvas_map.items():
            if key == view:
                self._render_message(canvas, message, is_error=is_error)
            else:
                canvas.delete("all")

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
        *,
        shared_scale: Optional[float] = None,
    ) -> None:
        canvas.delete("all")
        self._markers[key] = []
        self._boxes[key] = []
        img = np.asarray(img)
        if np.iscomplexobj(img):
            img = np.abs(img)
        else:
            try:
                img = img.astype(float, copy=False)
            except Exception:
                img = img.astype(np.float32, copy=False)
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
        if shared_scale is not None and width_mm > 0 and height_mm > 0:
            target_w = max(int(round(width_mm * shared_scale)), 1)
            target_h = max(int(round(height_mm * shared_scale)), 1)
            target_w = min(target_w, canvas_w)
            target_h = min(target_h, canvas_h)
        else:
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

        if self._last_show_crosshair and self._last_crosshair is not None:
            rc = self._last_crosshair.get(key)
            if rc is not None:
                self._draw_crosshair(key=key, row=int(rc[0]), col=int(rc[1]))

    def _shared_scale(self) -> Optional[float]:
        if not self._last_views:
            return None
        scales = []
        for key, canvas in self._canvas_map.items():
            img, res = self._last_views[key]
            canvas_w = max(canvas.winfo_width(), 1)
            canvas_h = max(canvas.winfo_height(), 1)
            width_mm = float(img.shape[1]) * float(res[0])
            height_mm = float(img.shape[0]) * float(res[1])
            if width_mm <= 0 or height_mm <= 0:
                continue
            scales.append(min(canvas_w / width_mm, canvas_h / height_mm))
        return min(scales) if scales else None

    def _render_to_image(
        self,
        *,
        view: str,
        img: np.ndarray,
        res: Tuple[float, float],
        title: str,
        canvas_w: int,
        canvas_h: int,
        shared_scale: Optional[float] = None,
    ) -> Image.Image:
        img = np.asarray(img)
        if np.iscomplexobj(img):
            img = np.abs(img)
        else:
            try:
                img = img.astype(float, copy=False)
            except Exception:
                img = img.astype(np.float32, copy=False)
        vmin, vmax = np.nanpercentile(img, (1, 99))
        if np.isclose(vmin, vmax):
            vmax = vmin + 1.0
        img_norm = np.clip((img - vmin) / (vmax - vmin), 0.0, 1.0)
        img_uint8 = (img_norm * 255).astype(np.uint8)
        img_display = np.flipud(img_uint8)
        pil_img = Image.fromarray(img_display, mode="L").convert("RGB")

        width_mm = float(img.shape[1]) * res[0]
        height_mm = float(img.shape[0]) * res[1]
        if shared_scale is not None and width_mm > 0 and height_mm > 0:
            target_w = max(int(round(width_mm * shared_scale)), 1)
            target_h = max(int(round(height_mm * shared_scale)), 1)
            target_w = min(target_w, canvas_w)
            target_h = min(target_h, canvas_h)
        else:
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
        background = Image.new("RGB", (canvas_w, canvas_h), "#111111")
        x = (canvas_w - target_w) // 2
        y = (canvas_h - target_h) // 2
        background.paste(pil_img, (x, y))
        draw = ImageDraw.Draw(background)
        if title:
            draw.text((10, 10), title, fill="#dddddd")

        state = (img.shape[0], img.shape[1], x, y, target_w, target_h)
        self._render_state[view] = state
        if self._last_show_crosshair and self._last_crosshair is not None:
            rc = self._last_crosshair.get(view)
            if rc is not None:
                self._draw_crosshair_image(draw, state=state, row=int(rc[0]), col=int(rc[1]))
        for row, col, color in self._marker_data.get(view, []):
            self._draw_marker_image(draw, state=state, row=row, col=col, color=color)
        for row0, col0, row1, col1, color, width in self._box_data.get(view, []):
            self._draw_box_image(
                draw,
                state=state,
                row0=row0,
                col0=col0,
                row1=row1,
                col1=col1,
                color=color,
                width=width,
            )
        return background

    def _draw_marker_image(
        self,
        draw: ImageDraw.ImageDraw,
        *,
        state: Tuple[int, int, int, int, int, int],
        row: int,
        col: int,
        color: str,
    ) -> None:
        img_h, img_w, offset_x, offset_y, target_w, target_h = state
        if img_h <= 0 or img_w <= 0:
            return
        display_row = img_h - 1 - row
        x = offset_x + (col + 0.5) * target_w / img_w
        y = offset_y + (display_row + 0.5) * target_h / img_h
        r = 4
        draw.ellipse((x - r, y - r, x + r, y + r), outline=color, width=2)

    def _draw_box_image(
        self,
        draw: ImageDraw.ImageDraw,
        *,
        state: Tuple[int, int, int, int, int, int],
        row0: int,
        col0: int,
        row1: int,
        col1: int,
        color: str,
        width: int,
    ) -> None:
        img_h, img_w, offset_x, offset_y, target_w, target_h = state
        if img_h <= 0 or img_w <= 0:
            return
        r0 = max(0, min(int(row0), img_h - 1))
        r1 = max(0, min(int(row1), img_h - 1))
        c0 = max(0, min(int(col0), img_w - 1))
        c1 = max(0, min(int(col1), img_w - 1))
        row_min, row_max = sorted((r0, r1))
        col_min, col_max = sorted((c0, c1))
        disp_row_min = img_h - 1 - row_max
        disp_row_max = img_h - 1 - row_min
        x0 = offset_x + col_min * target_w / img_w
        x1 = offset_x + (col_max + 1) * target_w / img_w
        y0 = offset_y + disp_row_min * target_h / img_h
        y1 = offset_y + (disp_row_max + 1) * target_h / img_h
        draw.rectangle((x0, y0, x1, y1), outline=color, width=width)

    def _draw_crosshair_image(
        self,
        draw: ImageDraw.ImageDraw,
        *,
        state: Tuple[int, int, int, int, int, int],
        row: int,
        col: int,
    ) -> None:
        img_h, img_w, offset_x, offset_y, target_w, target_h = state
        if img_h <= 0 or img_w <= 0 or target_w <= 0 or target_h <= 0:
            return
        if row < 0 or col < 0 or row >= img_h or col >= img_w:
            return
        display_row = img_h - 1 - row
        x = offset_x + (col + 0.5) * target_w / img_w
        y = offset_y + (display_row + 0.5) * target_h / img_h
        x0, x1 = offset_x, offset_x + target_w
        y0, y1 = offset_y, offset_y + target_h
        color = "#ffffff"
        draw.line((x0, y, x1, y), fill=color, width=1)
        draw.line((x, y0, x, y1), fill=color, width=1)

    def _draw_crosshair(self, *, key: str, row: int, col: int) -> None:
        state = self._render_state.get(key)
        if state is None:
            return
        img_h, img_w, offset_x, offset_y, target_w, target_h = state
        if img_h <= 0 or img_w <= 0 or target_w <= 0 or target_h <= 0:
            return
        if row < 0 or col < 0 or row >= img_h or col >= img_w:
            return

        display_row = img_h - 1 - row
        x = offset_x + (col + 0.5) * target_w / img_w
        y = offset_y + (display_row + 0.5) * target_h / img_h
        x0, x1 = offset_x, offset_x + target_w
        y0, y1 = offset_y, offset_y + target_h

        dash = (2, 4)
        color = "#ffffff"
        width = 1
        canvas = self._canvas_map[key]
        canvas.create_line(x0, y, x1, y, fill=color, width=width, dash=dash)
        canvas.create_line(x, y0, x, y1, fill=color, width=width, dash=dash)

    def _on_resize(self, *_: object) -> None:
        if self._last_message is not None:
            for canvas in self._canvas_map.values():
                self._render_message(canvas, self._last_message, is_error=self._last_is_error)
            return
        if self._last_views and self._last_titles:
            self._render_all_views()

    def _render_all_views(self) -> None:
        if not self._last_views or not self._last_titles:
            return

        shared_scale = self._shared_scale()

        for key, canvas in self._canvas_map.items():
            img, res = self._last_views[key]
            title = self._last_titles.get(key, "")
            self._render_canvas(canvas, key, img, res, title, shared_scale=shared_scale)

    def _on_capture(self, view: str) -> None:
        if self._capture_callback is None:
            return
        try:
            self._capture_callback(view)
        except Exception:
            pass

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

    def _on_mousewheel(self, event: tk.Event) -> Optional[str]:
        if self._zoom_callback is None:
            return None
        direction = 0
        delta = getattr(event, "delta", 0)
        if isinstance(delta, int) and delta != 0:
            direction = 1 if delta > 0 else -1
        else:
            num = getattr(event, "num", None)
            if num == 4:
                direction = 1
            elif num == 5:
                direction = -1
        if direction != 0:
            try:
                self._zoom_callback(direction)
            except Exception:
                pass
            return "break"
        return None
