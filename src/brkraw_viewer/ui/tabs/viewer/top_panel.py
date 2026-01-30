from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from brkraw_viewer.ui.windows.hook_options import HookOptionsDialog


class ViewerTopPanel(ttk.Frame):
    def __init__(self, parent: tk.Misc, *, callbacks) -> None:
        super().__init__(parent)
        self._callbacks = callbacks
        self._suspend_zoom = False
        self.grid_propagate(False)
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=0)
        self.columnconfigure(2, weight=1)

        left_container = ttk.Frame(self, width=440)
        left_container.grid(row=0, column=0, sticky="n", padx=(0, 8))
        left_container.grid_propagate(False)
        mid_container = ttk.Frame(self, width=160)
        mid_container.grid(row=0, column=1, sticky="n", padx=(8, 8))
        mid_container.grid_propagate(False)
        right_container = ttk.Frame(self, width=220)
        right_container.grid(row=0, column=2, sticky="n", padx=(8, 0))
        right_container.grid_propagate(False)

        left = ttk.Frame(left_container)
        left.place(relx=0.5, rely=0.0, anchor="n", width=440)
        left.columnconfigure(1, weight=1, uniform="viewer_left_combo")
        left.columnconfigure(2, weight=1, uniform="viewer_left_combo")

        space_row = ttk.Frame(left)
        space_row.grid(row=0, column=0, columnspan=4, pady=(0, 4), sticky="n")
        ttk.Label(space_row, text="Space").pack(side=tk.LEFT, padx=(0, 10))
        self._space_var = tk.StringVar(value="scanner")
        for label, value in (("raw", "raw"), ("scanner", "scanner"), ("subject_ras", "subject_ras")):
            ttk.Radiobutton(
                space_row,
                text=label,
                value=value,
                command=lambda v=value: self._on_space(callbacks, v),
                variable=self._space_var,
            ).pack(side=tk.LEFT, padx=(0, 10))

        ttk.Label(left, text="Subject Type").grid(row=1, column=0, sticky="w", padx=(0, 8))
        self._subject_type_var = tk.StringVar(value="Biped")
        self._subject_type_combo = ttk.Combobox(
            left,
            textvariable=self._subject_type_var,
            state="readonly",
            values=("Biped", "Quadruped", "Phantom", "Other", "OtherAnimal"),
        )
        self._subject_type_combo.grid(row=1, column=1, columnspan=2, sticky="ew")
        self._subject_type_combo.bind("<<ComboboxSelected>>", lambda *_: self._on_subject_change(callbacks))

        ttk.Label(left, text="Pose").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(6, 0))
        self._pose_primary_var = tk.StringVar(value="Head")
        self._pose_secondary_var = tk.StringVar(value="Supine")
        self._pose_primary_combo = ttk.Combobox(
            left,
            textvariable=self._pose_primary_var,
            state="readonly",
            values=("Head", "Foot"),
        )
        self._pose_primary_combo.grid(row=2, column=1, sticky="ew", pady=(6, 0))
        self._pose_primary_combo.bind("<<ComboboxSelected>>", lambda *_: self._on_subject_change(callbacks))
        self._pose_secondary_combo = ttk.Combobox(
            left,
            textvariable=self._pose_secondary_var,
            state="readonly",
            values=("Supine", "Prone", "Left", "Right"),
        )
        self._pose_secondary_combo.grid(row=2, column=2, sticky="ew", padx=(8, 0), pady=(6, 0))
        self._pose_secondary_combo.bind("<<ComboboxSelected>>", lambda *_: self._on_subject_change(callbacks))

        ttk.Button(
            left,
            text="RESET",
            width=8,
            command=lambda: self._on_subject_reset(callbacks),
        ).grid(row=1, column=3, rowspan=2, sticky="ns", padx=(12, 0), pady=(2, 0))

        mid = ttk.Frame(mid_container)
        mid.place(relx=0.5, rely=0.0, anchor="n", width=160)
        mid.columnconfigure(0, weight=1)
        self._crosshair_var = tk.BooleanVar(value=True)
        self._rgb_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            mid,
            text="Crosshair",
            variable=self._crosshair_var,
            command=lambda: self._on_crosshair(callbacks),
        ).grid(row=0, column=0, pady=(0, 4))
        self._rgb_check = ttk.Checkbutton(
            mid,
            text="RGB",
            variable=self._rgb_var,
            command=lambda: self._on_rgb(callbacks),
        )
        self._rgb_check.grid(row=1, column=0, pady=(0, 4))
        zoom_row = ttk.Frame(mid)
        zoom_row.grid(row=2, column=0, pady=(4, 0))
        ttk.Label(zoom_row, text="Zoom").pack(side=tk.LEFT, padx=(0, 4))
        self._zoom_scale = tk.Scale(
            zoom_row,
            from_=1.0,
            to=4.0,
            resolution=0.01,
            digits=2,
            orient=tk.HORIZONTAL,
            showvalue=True,
            length=110,
            command=self._on_zoom,
        )
        self._zoom_scale.set(1.0)
        self._zoom_scale.pack(side=tk.LEFT)

        right = ttk.Frame(right_container)
        right.place(relx=0.5, rely=0.0, anchor="n", width=220)
        right.columnconfigure(0, weight=1)
        hook_box = ttk.Frame(right)
        hook_box.grid(row=0, column=0, pady=(0, 4), sticky="ew")
        hook_box.columnconfigure(1, weight=1)
        ttk.Label(hook_box, text="Available Hook").grid(row=0, column=0, columnspan=2, sticky="w")
        self._hook_name_var = tk.StringVar(value="")
        self._hook_enabled_var = tk.BooleanVar(value=False)
        self._hook_args: dict | None = None

        self._hook_check = ttk.Checkbutton(
            hook_box,
            text="Apply",
            variable=self._hook_enabled_var,
            command=lambda: self._on_hook_toggle(callbacks),
        )
        self._hook_check.grid(row=1, column=0, sticky="w", padx=(0, 6))
        name_entry = ttk.Entry(hook_box, textvariable=self._hook_name_var, width=18, state="readonly")
        name_entry.grid(row=1, column=1, sticky="ew")
        self._hook_options_button = ttk.Button(
            hook_box,
            text="Hook Options",
            command=lambda: self._open_hook_options(callbacks),
        )
        self._hook_options_button.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))

        def _resize(_event: tk.Event | None = None) -> None:
            width = max(self.winfo_width(), 1)
            max_left = 440
            max_mid = 170
            max_right = 220
            gap = 24
            right_width = min(max_right, max(160, width // 4))
            mid_width = min(max_mid, max(140, width // 6))
            left_width = min(max_left, max(0, width - right_width - mid_width - gap))
            left_width = max(left_width, 1)
            mid_width = max(mid_width, 1)
            right_width = max(right_width, 1)
            left_height = max(left.winfo_reqheight(), 1)
            mid_height = max(mid.winfo_reqheight(), 1)
            right_height = max(right.winfo_reqheight(), 1)
            target_height = max(left_height, mid_height, right_height, 1)
            left_container.configure(width=left_width, height=left_height)
            mid_container.configure(width=mid_width, height=mid_height)
            right_container.configure(width=right_width, height=right_height)
            left.place_configure(width=left_width)
            mid.place_configure(width=mid_width)
            right.place_configure(width=right_width)
            try:
                self.configure(height=target_height)
            except Exception:
                pass

        self.bind("<Configure>", _resize)
        self.after(0, _resize)

    def _on_hook_toggle(self, callbacks) -> None:
        handler = getattr(callbacks, "on_viewer_hook_toggle", None)
        if callable(handler):
            handler(self._hook_enabled_var.get(), self._hook_name_var.get())

    def _open_hook_options(self, callbacks) -> None:
        hook_name = (self._hook_name_var.get() or "").strip()
        if not hook_name or hook_name == "None":
            return

        def _apply(values: dict) -> None:
            handler = getattr(callbacks, "on_hook_options_apply", None)
            if callable(handler):
                handler(hook_name, values)
                return
            fallback = getattr(callbacks, "on_viewer_hook_args_change", None)
            if callable(fallback):
                fallback(values)

        dialog = HookOptionsDialog(self, hook_name=hook_name, hook_args=self._hook_args, on_apply=_apply)
        dialog.show()

    def _on_crosshair(self, callbacks) -> None:
        handler = getattr(callbacks, "on_viewer_crosshair_toggle", None)
        if callable(handler):
            handler(self._crosshair_var.get())

    def _on_rgb(self, callbacks) -> None:
        handler = getattr(callbacks, "on_viewer_rgb_toggle", None)
        if callable(handler):
            handler(self._rgb_var.get())

    def _on_zoom(self, value: str) -> None:
        if self._suspend_zoom:
            return
        handler = getattr(self._callbacks, "on_viewer_zoom_change", None)
        if callable(handler):
            handler(float(value))

    def set_zoom_value(self, value: float) -> None:
        self._suspend_zoom = True
        try:
            self._zoom_scale.set(float(value))
        finally:
            self._suspend_zoom = False

    def _on_space(self, callbacks, value: str) -> None:
        handler = getattr(callbacks, "on_viewer_space_change", None)
        if callable(handler):
            handler(value)

    def _on_subject_reset(self, callbacks) -> None:
        handler = getattr(callbacks, "on_viewer_subject_reset", None)
        if callable(handler):
            handler()

    def _on_subject_change(self, callbacks) -> None:
        handler = getattr(callbacks, "on_viewer_subject_change", None)
        if callable(handler):
            handler(
                self._subject_type_var.get(),
                self._pose_primary_var.get(),
                self._pose_secondary_var.get(),
            )

    def set_subject_enabled(self, enabled: bool) -> None:
        state = "readonly" if enabled else "disabled"
        self._subject_type_combo.configure(state=state)
        self._pose_primary_combo.configure(state=state)
        self._pose_secondary_combo.configure(state=state)

    def set_subject_values(self, subject_type: str, pose_primary: str, pose_secondary: str) -> None:
        if subject_type:
            self._subject_type_var.set(subject_type)
        if pose_primary:
            self._pose_primary_var.set(pose_primary)
        if pose_secondary:
            self._pose_secondary_var.set(pose_secondary)

    def set_hook_state(self, hook_name: str, enabled: bool, *, allow_toggle: bool = True) -> None:
        self._hook_name_var.set(hook_name or "None")
        self._hook_enabled_var.set(bool(enabled))
        state = "normal" if allow_toggle and hook_name and hook_name != "None" else "disabled"
        try:
            self._hook_check.configure(state=state)
        except Exception:
            pass
        try:
            self._hook_options_button.configure(state=state)
        except Exception:
            pass

    def set_hook_args(self, hook_args: dict | None) -> None:
        self._hook_args = dict(hook_args) if isinstance(hook_args, dict) else None

    def set_rgb_state(self, *, enabled: bool, active: bool) -> None:
        self._rgb_var.set(bool(active))
        state = "normal" if enabled else "disabled"
        try:
            self._rgb_check.configure(state=state)
        except Exception:
            pass
