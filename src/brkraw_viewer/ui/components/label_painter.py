from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Tuple, List
from .viewport import ViewportCanvas
import numpy as np
from numpy.typing import DTypeLike


LabelChangedCallback = Callable[[np.ndarray], None]
# Stroke bbox in slice space plus slice location.
# (axis, slice_index, r0, c0, r1, c1)
StrokeEndCallback = Callable[[Tuple[int, int, int, int, int, int]], None]


@dataclass
class Brush:
    radius: int = 6
    shape: str = "circle"  # "circle" or "square"


class LabelMapPainter:
    """Discrete label painter that attaches to a viewport.

    Design:
      - Owns or references a 2D label_map (H, W) of integer label indices.
      - Optionally binds a 3D label_volume and paints into the currently selected slice view.
      - Uses the viewport's `canvas_to_image(x,y)` mapping.
      - Updates a per-pixel label map using a brush.
      - Renders labels to an RGBA overlay and pushes it via `viewport.set_overlay_rgba(rgba)`.

    Required viewport API (duck-typed):
      - bind_canvas(sequence: str, func: Callable, add: bool = True) -> str
      - canvas_to_image(x: int, y: int) -> Optional[Tuple[int, int]]
      - get_image_shape() -> Optional[Tuple[int, int]]
      - set_overlay_rgba(rgba: Optional[np.ndarray]) -> None
      - set_brush_preview(row: int, col: int, *, size: int, shape: str, color: str, show: bool = True) -> None
      - clear_brush_preview() -> None

    Notes:
      - This class is UI-only. It does not manage 3D volumes, undo stacks, or saving.
      - Those responsibilities should live in the controller/state.
    """

    def __init__(self, viewport: ViewportCanvas) -> None:
        self._vp = viewport

        self.label_map: Optional[np.ndarray] = None  # (H, W) int
        # Optional 3D label volume support. When set, `label_map` becomes a writable
        # view into the currently selected slice of this volume.
        self.label_volume: Optional[np.ndarray] = None  # (D,H,W) or any 3D, controller-owned
        self.slice_axis: int = 0
        self.slice_index: int = 0

        self.brush = Brush()

        self.active_label: int = 1
        self.erase_label: int = 0
        self.enabled: bool = True

        # RGBA lookup table: index -> color.
        # index 0 should be transparent.
        self.lut_rgba: np.ndarray = self.default_lut_rgba(256)

        # Overlay alpha applied to non-zero labels if LUT alpha is 255.
        self.alpha: int = 180  # 0..255

        # Callbacks
        self.on_label_changed: Optional[LabelChangedCallback] = None
        self.on_stroke_end: Optional[StrokeEndCallback] = None

        # Internal paint state
        self._painting: bool = False
        self._paint_value: int = self.active_label
        self._last_rc: Optional[Tuple[int, int]] = None
        self._dirty_bbox: Optional[List[int]] = None

        # Real-time overlay refresh (throttled)
        self.throttle_ms: int = 33  # ~30 FPS
        self._flush_after_id: Optional[str] = None
        self._flush_pending: bool = False
        # Event binding ids returned by viewport.bind_canvas
        self._bind_ids: List[str] = []
    # ---------- Viewport binding ----------

    def attach(self) -> None:
        """Bind mouse events to the viewport.

        Left button: paint active label.
        Right (or middle) button: erase (label 0).
        """
        # Avoid double-binding.
        self.detach()

        # Use the viewport's bind_canvas helper so we work with embedded/detached tabs.
        self._bind_ids = []
        try:
            self._bind_ids.append(self._vp.bind_canvas("<ButtonPress-1>", self._on_down_paint, add=True))
            self._bind_ids.append(self._vp.bind_canvas("<B1-Motion>", self._on_drag, add=True))
            self._bind_ids.append(self._vp.bind_canvas("<ButtonRelease-1>", self._on_up, add=True))

            # Erase with right click (Button-3). Some mac setups report right click as Button-2.
            self._bind_ids.append(self._vp.bind_canvas("<ButtonPress-3>", self._on_down_erase, add=True))
            self._bind_ids.append(self._vp.bind_canvas("<B3-Motion>", self._on_drag, add=True))
            self._bind_ids.append(self._vp.bind_canvas("<ButtonRelease-3>", self._on_up, add=True))

            self._bind_ids.append(self._vp.bind_canvas("<ButtonPress-2>", self._on_down_erase, add=True))
            self._bind_ids.append(self._vp.bind_canvas("<B2-Motion>", self._on_drag, add=True))
            self._bind_ids.append(self._vp.bind_canvas("<ButtonRelease-2>", self._on_up, add=True))

            # Hover preview
            self._bind_ids.append(self._vp.bind_canvas("<Motion>", self._on_hover_move, add=True))
            self._bind_ids.append(self._vp.bind_canvas("<Leave>", self._on_hover_leave, add=True))
            self._bind_ids.append(self._vp.bind_canvas("<Enter>", self._on_hover_enter, add=True))
        except Exception:
            # If the viewport doesn't support bind_canvas for some reason, fail silently.
            # Controllers/demos can bind directly as a fallback.
            self._bind_ids = []

    def detach(self) -> None:
        """Unbind previously attached events, if the viewport supports it."""
        if not self._bind_ids:
            return
        unbind = getattr(self._vp, "unbind_canvas", None)
        if callable(unbind):
            for bid in list(self._bind_ids):
                try:
                    unbind(bid)
                except Exception:
                    pass
        # Clear hover preview if supported.
        try:
            clr = getattr(self._vp, "clear_brush_preview", None)
            if callable(clr):
                clr()
        except Exception:
            pass
        self._bind_ids = []

    def _slice_view(self, vol: np.ndarray, axis: int, index: int) -> np.ndarray:
        v = np.asarray(vol)
        if v.ndim != 3:
            raise ValueError("label_volume must be 3D")
        ax = int(axis)
        if ax not in (0, 1, 2):
            raise ValueError("slice_axis must be 0, 1, or 2")
        idx = int(index)
        if idx < 0 or idx >= v.shape[ax]:
            raise IndexError("slice_index out of bounds")
        if ax == 0:
            sl = v[idx, :, :]
        elif ax == 1:
            sl = v[:, idx, :]
        else:
            sl = v[:, :, idx]
        # Ensure 2D
        sl2 = np.asarray(sl)
        if sl2.ndim != 2:
            raise RuntimeError("slice view is not 2D")
        return sl2

    def set_label_map(self, label_map: np.ndarray) -> None:
        lm = np.asarray(label_map)
        if lm.ndim != 2:
            raise ValueError("label_map must be 2D (H,W)")
        # 2D-only mode
        self.label_volume = None
        self.slice_axis = 0
        self.slice_index = 0
        self.label_map = lm
        self.refresh_overlay_full()

    def set_label_volume(self, label_volume: np.ndarray, *, axis: int = 0, index: int = 0) -> None:
        """Bind a 3D label volume.

        The painter will write into the currently selected slice view. Controllers should
        call `set_slice(index=...)` when the displayed slice changes.
        """
        vol = np.asarray(label_volume)
        if vol.ndim != 3:
            raise ValueError("label_volume must be 3D")
        self.label_volume = vol
        self.slice_axis = int(axis)
        self.slice_index = int(index)
        self.label_map = self._slice_view(vol, self.slice_axis, self.slice_index)
        self.refresh_overlay_full()

    def set_slice(self, *, index: int, axis: Optional[int] = None) -> None:
        """Update which slice is currently displayed/painted."""
        if self.label_volume is None:
            # 2D-only mode
            self.slice_index = int(index)
            if axis is not None:
                self.slice_axis = int(axis)
            return
        if axis is not None:
            self.slice_axis = int(axis)
        self.slice_index = int(index)
        self.label_map = self._slice_view(self.label_volume, self.slice_axis, self.slice_index)
        self.refresh_overlay_full()

    def ensure_label_map(self, *, dtype: DTypeLike = np.uint16) -> np.ndarray:
        """Create an empty label map if none exists, using the viewport image shape."""
        if self.label_volume is not None:
            # Ensure we have a slice view bound.
            self.label_map = self._slice_view(self.label_volume, self.slice_axis, self.slice_index)
            return self.label_map
        if self.label_map is not None:
            return self.label_map
        shape = self._vp.get_image_shape()
        if shape is None:
            raise RuntimeError("Viewport has no image loaded")
        h, w = shape
        self.label_map = np.zeros((h, w), dtype=dtype)
        self.refresh_overlay_full()
        return self.label_map

    def set_active_label(self, label: int) -> None:
        self.active_label = int(label)

    def set_brush(self, *, radius: Optional[int] = None, shape: Optional[str] = None) -> None:
        if radius is not None:
            self.brush.radius = max(1, int(radius))
        if shape is not None:
            if shape not in ("circle", "square"):
                raise ValueError("shape must be 'circle' or 'square'")
            self.brush.shape = shape

    def set_lut_rgba(self, lut_rgba: np.ndarray) -> None:
        lut = np.asarray(lut_rgba, dtype=np.uint8)
        if lut.ndim != 2 or lut.shape[1] != 4:
            raise ValueError("lut_rgba must be (N,4) uint8")
        self.lut_rgba = lut
        self.refresh_overlay_full()

    def set_label_color(self, label: int, rgb: Tuple[int, int, int], *, alpha: int = 255) -> None:
        """Set a single label color in the RGBA LUT.

        Intended for UI widgets (eg a color picker). Label 0 remains transparent.
        """
        idx = int(label)
        if idx < 0:
            return

        lut = np.asarray(self.lut_rgba, dtype=np.uint8)
        if lut.ndim != 2 or lut.shape[1] != 4:
            raise ValueError("lut_rgba must be (N,4) uint8")

        if idx >= lut.shape[0]:
            n = idx + 1
            new_lut = np.zeros((n, 4), dtype=np.uint8)
            new_lut[: lut.shape[0]] = lut
            lut = new_lut

        r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])
        a = int(alpha)
        r = 0 if r < 0 else 255 if r > 255 else r
        g = 0 if g < 0 else 255 if g > 255 else g
        b = 0 if b < 0 else 255 if b > 255 else b
        a = 0 if a < 0 else 255 if a > 255 else a

        if idx == 0:
            lut[0] = np.array([0, 0, 0, 0], dtype=np.uint8)
        else:
            lut[idx] = np.array([r, g, b, a], dtype=np.uint8)

        self.lut_rgba = lut
        self.refresh_overlay_full()
        # Color pickers often steal focus; restore it and refresh the hover preview.
        self._restore_focus_to_viewport()
        self.refresh_preview_at_pointer()

    def clear(self) -> None:
        self.label_map = None
        self._vp.set_overlay_rgba(None)

    def refresh_overlay_full(self) -> None:
        if self.label_map is None:
            return
        rgba = self.labels_to_rgba(self.label_map)
        self._vp.set_overlay_rgba(rgba)

    def _request_flush(self) -> None:
        """Schedule a throttled overlay refresh while painting."""
        if self.label_map is None:
            return
        self._flush_pending = True
        if self._flush_after_id is not None:
            return
        try:
            self._flush_after_id = str(self._vp.after(self.throttle_ms, self._flush_overlay))
        except Exception:
            # Fallback: refresh immediately if scheduling is not available.
            self._flush_after_id = None
            self._flush_overlay()

    def _flush_overlay(self) -> None:
        """Perform the actual overlay refresh and clear pending state."""
        self._flush_after_id = None
        if not self._flush_pending:
            return
        self._flush_pending = False
        if self.label_map is None:
            return
        rgba = self.labels_to_rgba(self.label_map)
        self._vp.set_overlay_rgba(rgba)

    # ---------- Hover preview ----------

    def _active_label_hex(self) -> str:
        """Return the active label color as a hex string (#RRGGBB)."""
        idx = int(self.active_label)
        lut = np.asarray(self.lut_rgba, dtype=np.uint8)
        if lut.ndim != 2 or lut.shape[1] != 4 or lut.shape[0] == 0:
            return "#ffcc00"
        if idx < 0:
            idx = 0
        if idx >= lut.shape[0]:
            idx = lut.shape[0] - 1
        r = int(lut[idx, 0])
        g = int(lut[idx, 1])
        b = int(lut[idx, 2])
        return f"#{r:02x}{g:02x}{b:02x}"
    
    def _vp_canvas_widget(self):
        """Best-effort access to the underlying Tk Canvas used by the viewport."""
        return getattr(self._vp, "_canvas", None)

    def refresh_preview_at_pointer(self) -> None:
        """Force a hover preview refresh using the current pointer location.

        Useful after a color picker closes, where no <Motion> event may arrive until click.
        """
        if not self.enabled:
            return
        c = self._vp_canvas_widget()
        if c is None:
            return
        try:
            px = int(c.winfo_pointerx()) - int(c.winfo_rootx())
            py = int(c.winfo_pointery()) - int(c.winfo_rooty())
        except Exception:
            return

        rc = self._vp.canvas_to_image(px, py)
        if rc is None:
            self._on_hover_leave(None)
            return

        set_prev = getattr(self._vp, "set_brush_preview", None)
        if not callable(set_prev):
            return
        try:
            set_prev(
                int(rc[0]),
                int(rc[1]),
                size=int(self.brush.radius),
                shape=str(self.brush.shape),
                color=self._active_label_hex(),
                show=True,
            )
        except Exception:
            return

    def _restore_focus_to_viewport(self) -> None:
        """Best-effort focus restoration to the app and viewport."""
        try:
            top = self._vp.winfo_toplevel()
        except Exception:
            top = None

        if top is not None:
            try:
                top.lift()
            except Exception:
                pass
            try:
                top.focus_force()
            except Exception:
                pass

        try:
            self._vp.focus_set()
        except Exception:
            pass

        if top is not None:
            try:
                top.after(1, lambda: self._vp.focus_set())
            except Exception:
                pass

    def _on_hover_move(self, event) -> None:
        if not self.enabled:
            return
        rc = self._vp.canvas_to_image(int(event.x), int(event.y))
        if rc is None:
            self._on_hover_leave(event)
            return

        set_prev = getattr(self._vp, "set_brush_preview", None)
        if not callable(set_prev):
            return

        try:
            set_prev(
                int(rc[0]),
                int(rc[1]),
                size=int(self.brush.radius),
                shape=str(self.brush.shape),
                color=self._active_label_hex(),
                show=True,
            )
        except Exception:
            # Best-effort only
            return

    def _on_hover_leave(self, _event=None) -> None:
        clr = getattr(self._vp, "clear_brush_preview", None)
        if callable(clr):
            try:
                clr()
            except Exception:
                pass

    def _on_hover_enter(self, _event=None) -> None:
        # After returning from modal dialogs (eg color picker), <Motion> may not fire.
        self.refresh_preview_at_pointer()

    # ---------- Rendering ----------

    def labels_to_rgba(self, labels: np.ndarray) -> np.ndarray:
        labels_i = np.asarray(labels)
        if labels_i.ndim != 2:
            raise ValueError("labels must be 2D")

        h, w = labels_i.shape
        out = np.zeros((h, w, 4), dtype=np.uint8)

        lut = self.lut_rgba
        max_idx = int(lut.shape[0] - 1)

        idx = labels_i.astype(np.int32, copy=False)
        if max_idx >= 0:
            idx = np.clip(idx, 0, max_idx)

        rgba = lut[idx]
        out[:, :, :] = rgba

        # Enforce alpha policy: 0 transparent, others get self.alpha unless LUT already has alpha < 255.
        nonzero = idx != 0
        if np.any(nonzero):
            # If LUT alpha is 255, cap with self.alpha. If LUT alpha is already smaller, keep it.
            a = out[:, :, 3].astype(np.int16, copy=False)
            a_nz = a[nonzero]
            a_nz = np.minimum(a_nz, int(self.alpha))
            out[nonzero, 3] = a_nz.astype(np.uint8)
        out[~nonzero, 3] = 0
        return out

    # ---------- Painting ----------

    def _event_to_rc(self, event) -> Optional[Tuple[int, int]]:
        if not self.enabled:
            return None
        return self._vp.canvas_to_image(int(event.x), int(event.y))

    def _on_down_paint(self, event) -> None:
        if self.label_map is None:
            return
        rc = self._event_to_rc(event)
        if rc is None:
            return
        self._start_stroke(int(self.active_label), rc)

    def _on_down_erase(self, event) -> None:
        if self.label_map is None:
            return
        rc = self._event_to_rc(event)
        if rc is None:
            return
        self._start_stroke(int(self.erase_label), rc)

    def _start_stroke(self, value: int, rc: Tuple[int, int]) -> None:
        self._painting = True
        self._paint_value = int(value)
        self._dirty_bbox = None
        # Initialize last point for stroke interpolation.
        self._last_rc = (int(rc[0]), int(rc[1]))
        self._paint_point(int(rc[0]), int(rc[1]))

    def _on_drag(self, event) -> None:
        if not self._painting or self.label_map is None:
            return
        rc = self._event_to_rc(event)
        if rc is None:
            return
        r1, c1 = int(rc[0]), int(rc[1])
        if self._last_rc is None:
            self._last_rc = (r1, c1)
            self._paint_point(r1, c1)
            return
        r0, c0 = self._last_rc
        if (r0, c0) == (r1, c1):
            return

        # Fill between points in image index space to avoid dotted strokes.
        for rr, cc in self._iter_line_rc(r0, c0, r1, c1):
            self._paint_point(rr, cc)
        self._last_rc = (r1, c1)

    def _on_up(self, event) -> None:
        if not self._painting:
            return
        self._painting = False

        # Cancel any scheduled flush and perform a final refresh.
        if self._flush_after_id is not None:
            try:
                self._vp.after_cancel(self._flush_after_id)
            except Exception:
                pass
            self._flush_after_id = None
        self._flush_pending = False

        # Final refresh overlay
        bbox: Optional[Tuple[int, int, int, int]] = None
        if self._dirty_bbox is not None:
            bbox = (self._dirty_bbox[0], self._dirty_bbox[1], self._dirty_bbox[2], self._dirty_bbox[3])
        self.refresh_overlay_full()
        if bbox is not None and self.on_stroke_end is not None:
            try:
                ax = int(self.slice_axis)
                si = int(self.slice_index)
                self.on_stroke_end((ax, si, bbox[0], bbox[1], bbox[2], bbox[3]))
            except Exception:
                pass

        if self.on_label_changed is not None and self.label_map is not None:
            try:
                self.on_label_changed(self.label_map)
            except Exception:
                pass

        # Clear preview (it will reappear on next hover move).
        self._on_hover_leave(None)

        self._last_rc = None
        self._dirty_bbox = None

    def _paint_point(self, row: int, col: int) -> None:
        bbox = self._apply_brush(row, col, self._paint_value)
        if bbox is not None:
            self._mark_dirty(bbox)
            self._request_flush()

    def _iter_line_rc(self, r0: int, c0: int, r1: int, c1: int):
        """Yield (r,c) along a line in image index space (Bresenham)."""
        r0 = int(r0)
        c0 = int(c0)
        r1 = int(r1)
        c1 = int(c1)
        dr = abs(r1 - r0)
        dc = abs(c1 - c0)
        sr = 1 if r0 < r1 else -1
        sc = 1 if c0 < c1 else -1
        err = dr - dc
        r, c = r0, c0
        while True:
            yield r, c
            if r == r1 and c == c1:
                break
            e2 = 2 * err
            if e2 > -dc:
                err -= dc
                r += sr
            if e2 < dr:
                err += dr
                c += sc

    def _apply_brush(self, row: int, col: int, value: int) -> Optional[Tuple[int, int, int, int]]:
        if self.label_map is None:
            return None

        lm = self.label_map
        h, w = lm.shape
        # Brush size semantics (pixel-exact):
        #   size=1 -> 1x1
        #   size=3 -> 3x3
        #   size=10 -> 10x10
        size = int(self.brush.radius)
        if size < 1:
            size = 1

        # Support even sizes by using asymmetric half-widths.
        half_lo = (size - 1) // 2
        half_hi = size // 2

        r0 = max(0, row - half_lo)
        r1 = min(h - 1, row + half_hi)
        c0 = max(0, col - half_lo)
        c1 = min(w - 1, col + half_hi)

        sub = lm[r0 : r1 + 1, c0 : c1 + 1]

        if self.brush.shape == "square":
            sub[:, :] = value
        else:
            yy, xx = np.ogrid[r0 : r1 + 1, c0 : c1 + 1]
            if size == 1:
                sub[:, :] = value
            else:
                # Interpret UI value as disk diameter-like size.
                # Use an effective radius that matches the square footprint scale.
                eff_r = min(half_lo, half_hi)
                mask = (yy - row) ** 2 + (xx - col) ** 2 <= eff_r * eff_r
                sub[mask] = value

        return (r0, c0, r1, c1)

    def _mark_dirty(self, bbox: Tuple[int, int, int, int]) -> None:
        if self._dirty_bbox is None:
            self._dirty_bbox = [bbox[0], bbox[1], bbox[2], bbox[3]]
            return
        self._dirty_bbox[0] = min(self._dirty_bbox[0], bbox[0])
        self._dirty_bbox[1] = min(self._dirty_bbox[1], bbox[1])
        self._dirty_bbox[2] = max(self._dirty_bbox[2], bbox[2])
        self._dirty_bbox[3] = max(self._dirty_bbox[3], bbox[3])

    # ---------- Palette helpers ----------

    @staticmethod
    def default_lut_rgba(n: int) -> np.ndarray:
        """Simple deterministic label palette.

        Index 0 is transparent.
        Indices 1..n-1 get pseudo-distinct colors.
        """
        n = max(1, int(n))
        lut = np.zeros((n, 4), dtype=np.uint8)
        lut[0] = np.array([0, 0, 0, 0], dtype=np.uint8)
        for i in range(1, n):
            r = (37 * i) % 255
            g = (91 * i) % 255
            b = (173 * i) % 255
            lut[i] = np.array([r, g, b, 255], dtype=np.uint8)
        return lut