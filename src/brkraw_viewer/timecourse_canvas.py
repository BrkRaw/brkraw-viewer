from __future__ import annotations

import tkinter as tk
from typing import Iterable, List, Optional, Tuple


class TimecourseCanvas(tk.Canvas):
    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, background="#111111", highlightthickness=0)
        self._series: List[Tuple[List[float], str, str]] = []
        self._title: str = "Timecourse"
        self.bind("<Configure>", self._on_resize)

    def set_series(self, series: Iterable[Tuple[List[float], str, str]], title: Optional[str] = None) -> None:
        self._series = list(series)
        if title is not None:
            self._title = title
        self._render()

    def clear(self) -> None:
        self._series = []
        self._render()

    def _on_resize(self, *_: object) -> None:
        self._render()

    def _render(self) -> None:
        self.delete("all")
        width = max(self.winfo_width(), 1)
        height = max(self.winfo_height(), 1)
        pad_left = 40
        pad_top = 20
        pad_right = 20
        pad_bottom = 30
        plot_w = max(width - pad_left - pad_right, 1)
        plot_h = max(height - pad_top - pad_bottom, 1)

        self.create_text(
            pad_left,
            5,
            anchor="nw",
            fill="#dddddd",
            text=self._title,
            font=("TkDefaultFont", 10, "bold"),
        )

        if not self._series:
            self.create_text(
                width // 2,
                height // 2,
                anchor="center",
                fill="#666666",
                text="No points selected",
                font=("TkDefaultFont", 10),
            )
            return

        all_vals = [val for series, _, _ in self._series for val in series]
        vmin = min(all_vals)
        vmax = max(all_vals)
        if vmin == vmax:
            vmax = vmin + 1.0

        self.create_line(pad_left, pad_top, pad_left, pad_top + plot_h, fill="#444444")
        self.create_line(pad_left, pad_top + plot_h, pad_left + plot_w, pad_top + plot_h, fill="#444444")

        for series, color, label in self._series:
            if not series:
                continue
            n = len(series)
            points = []
            for i, val in enumerate(series):
                x = pad_left + (plot_w * i / max(n - 1, 1))
                y = pad_top + plot_h - (plot_h * (val - vmin) / (vmax - vmin))
                points.extend([x, y])
            self.create_line(*points, fill=color, width=2)

        for idx, (_, color, label) in enumerate(self._series):
            self.create_text(
                pad_left + 10,
                pad_top + 15 + idx * 14,
                anchor="nw",
                fill=color,
                text=label,
                font=("TkDefaultFont", 9),
            )
