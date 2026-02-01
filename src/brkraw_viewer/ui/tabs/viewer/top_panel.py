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

        left_container = ttk.Frame(self, width=300)
        left_container.grid(row=0, column=0, sticky="n", padx=(0, 8))
        left_container.grid_propagate(False)
        mid_container = ttk.Frame(self, width=240)
        mid_container.grid(row=0, column=1, sticky="n", padx=(8, 8))
        mid_container.grid_propagate(False)
        right_container = ttk.Frame(self, width=240)
        right_container.grid(row=0, column=2, sticky="n", padx=(8, 0))
        right_container.grid_propagate(False)

        left = ttk.Frame(left_container)
        left.place(relx=0.5, rely=0.0, anchor="n", width=300)
        left.columnconfigure(0, weight=1)

        orientation_frame = ttk.LabelFrame(left, text="Orientation", padding=(6, 4))
        orientation_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 0))
        orientation_frame.columnconfigure(1, weight=1, uniform="viewer_orientation_cols")
        orientation_frame.columnconfigure(2, weight=1, uniform="viewer_orientation_cols")

        ttk.Label(orientation_frame, text="Space").grid(row=0, column=0, sticky="w", padx=(0, 8))
        space_radio_frame = ttk.Frame(orientation_frame)
        space_radio_frame.grid(row=0, column=1, columnspan=2, sticky="ew", pady=(0, 4))
        self._space_var = tk.StringVar(value="scanner")
        for label, value in (("raw", "raw"), ("scanner", "scanner"), ("subject_ras", "subject_ras")):
            ttk.Radiobutton(
                space_radio_frame,
                text=label,
                value=value,
                command=lambda v=value: self._on_space(callbacks, v),
                variable=self._space_var,
            ).pack(side=tk.LEFT, padx=(0, 10))

        ttk.Label(orientation_frame, text="Type").grid(row=1, column=0, sticky="w", padx=(0, 8))
        self._subject_type_var = tk.StringVar(value="Biped")
        self._subject_type_combo = ttk.Combobox(
            orientation_frame,
            textvariable=self._subject_type_var,
            state="readonly",
            values=("Biped", "Quadruped", "Phantom", "Other", "OtherAnimal"),
            width=8,
        )
        self._subject_type_combo.grid(row=1, column=1, sticky="ew", padx=(0, 4))
        self._subject_type_combo.bind("<<ComboboxSelected>>", lambda *_: self._on_subject_change(callbacks))

        ttk.Button(
            orientation_frame,
            text="RESET",
            width=6,
            command=lambda: self._on_subject_reset(callbacks),
        ).grid(row=1, column=2, sticky="ew", padx=(4, 0))

        ttk.Label(orientation_frame, text="Pose").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(6, 0))
        self._pose_primary_var = tk.StringVar(value="Head")
        self._pose_secondary_var = tk.StringVar(value="Supine")
        self._pose_primary_combo = ttk.Combobox(
            orientation_frame,
            textvariable=self._pose_primary_var,
            state="readonly",
            values=("Head", "Foot"),
            width=8,
        )
        self._pose_primary_combo.grid(row=2, column=1, sticky="ew", padx=(0, 4), pady=(6, 0))
        self._pose_primary_combo.bind("<<ComboboxSelected>>", lambda *_: self._on_subject_change(callbacks))
        self._pose_secondary_combo = ttk.Combobox(
            orientation_frame,
            textvariable=self._pose_secondary_var,
            state="readonly",
            values=("Supine", "Prone", "Left", "Right"),
            width=8,
        )
        self._pose_secondary_combo.grid(row=2, column=2, sticky="ew", padx=(4, 0), pady=(6, 0))
        self._pose_secondary_combo.bind("<<ComboboxSelected>>", lambda *_: self._on_subject_change(callbacks))

        flip_row = ttk.Frame(orientation_frame)
        flip_row.grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(flip_row, text="Flip").pack(side=tk.LEFT, padx=(0, 14))
        self._flip_x_var = tk.BooleanVar(value=False)
        self._flip_y_var = tk.BooleanVar(value=False)
        self._flip_z_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            flip_row,
            text="X",
            variable=self._flip_x_var,
            command=lambda: self._on_flip(callbacks, "x"),
        ).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Checkbutton(
            flip_row,
            text="Y",
            variable=self._flip_y_var,
            command=lambda: self._on_flip(callbacks, "y"),
        ).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Checkbutton(
            flip_row,
            text="Z",
            variable=self._flip_z_var,
            command=lambda: self._on_flip(callbacks, "z"),
        ).pack(side=tk.LEFT)

        mid = ttk.Frame(mid_container)
        mid.place(relx=0.5, rely=0.0, anchor="n", width=240)
        mid.columnconfigure(0, weight=1)

        hook_frame = ttk.LabelFrame(mid, text="Hook", padding=(6, 4))
        hook_frame.grid(row=0, column=0, sticky="nsew")
        hook_frame.columnconfigure(1, weight=1)

        self._hook_name_var = tk.StringVar(value="Disabled")
        self._hook_enabled_var = tk.BooleanVar(value=False)
        self._hook_args: dict | None = None

        self._hook_check = ttk.Checkbutton(
            hook_frame,
            text="Apply",
            variable=self._hook_enabled_var,
            command=lambda: self._on_hook_toggle(callbacks),
            state="disabled",
        )
        self._hook_check.grid(row=0, column=0, sticky="w", padx=(0, 6))
        name_entry = ttk.Entry(hook_frame, textvariable=self._hook_name_var, width=14, state="readonly")
        name_entry.grid(row=0, column=1, sticky="ew")
        self._hook_options_button = ttk.Button(
            hook_frame,
            text="Hook Options",
            command=lambda: self._open_hook_options(callbacks),
            state="disabled",
        )
        self._hook_options_button.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        right = ttk.Frame(right_container)
        right.place(relx=0.5, rely=0.0, anchor="n", width=240)
        right.columnconfigure(0, weight=1)

        control_frame = ttk.LabelFrame(right, text="Control", padding=(6, 4))
        control_frame.grid(row=0, column=0, sticky="nsew")
        control_frame.columnconfigure(0, weight=1)

        self._crosshair_var = tk.BooleanVar(value=True)
        self._rgb_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            control_frame,
            text="Crosshair",
            variable=self._crosshair_var,
            command=lambda: self._on_crosshair(callbacks),
        ).grid(row=0, column=0, sticky="w", pady=(0, 4))
        self._rgb_check = ttk.Checkbutton(
            control_frame,
            text="RGB",
            variable=self._rgb_var,
            command=lambda: self._on_rgb(callbacks),
        )
        self._rgb_check.grid(row=1, column=0, sticky="w", pady=(0, 4))
        zoom_row = ttk.Frame(control_frame)
        zoom_row.grid(row=2, column=0, pady=(4, 0), sticky="ew")
        ttk.Label(zoom_row, text="Zoom").pack(side=tk.LEFT, padx=(0, 4))
        self._zoom_scale = tk.Scale(
            zoom_row,
            from_=1.0,
            to=4.0,
            resolution=0.01,
            digits=2,
            orient=tk.HORIZONTAL,
            showvalue=True,
            length=80,
            command=self._on_zoom,
        )
        self._zoom_scale.set(1.0)
        self._zoom_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)

        def _resize(_event: tk.Event | None = None) -> None:
            width = max(self.winfo_width(), 1)
            
            w_left = 300
            w_mid = 240
            w_right = 240
            gap = 24
            
            total_req = w_left + w_mid + w_right + (gap * 2)
            start_x = max(0, (width - total_req) // 2)
            
            # Place containers
            # Since containers are grid-managed by 'self', grid propagation might interfere if we change widths.
            # But 'grid_propagate(False)' is set.
            # We are configuring container sizes here. Grid will place them.
            # Wait, 'grid(row=0, column=0)' places them. 'place' is used for INNER content?
            # No, 'left = ttk.Frame(left_container); left.place(...)'.
            # The containers themselves (left_container) are grid-managed.
            # To center them, we need to adjust padding or column weights?
            # Or resizing the containers?
            # If columns 0,1,2 have weights, grid expands them.
            # To center fixed-size content, we can use a wrapper or just padding.
            # But ' ViewerTopPanel' logic was to resize 'left_container', etc.
            # If I want to center them, I should probably not use grid column weights for expansion,
            # or use padding to center.
            # Actually, the user wants "aligned same ratio".
            # If I fix widths of containers, grid will pack them left-aligned if weights are 0?
            # 'self.columnconfigure(0, weight=1)' etc.
            # If I want centering, I can make cols 0,1,2 weight 0, and add spacer cols?
            # Or simpler: Rely on 'grid' to center? grid doesn't auto-center multiple columns easily.
            # I'll stick to 'place' for positioning if I remove grid?
            # No, refactoring to 'place' is risky.
            # Let's adjust 'left_container' width?
            # No, if 'left_container' is 300, and I want it centered relative to total width...
            # I should resize the containers to fill the space but center content inside?
            # Existing code: 'left.place(relx=0.5, ... anchor="n")'. This centers 'left' inside 'left_container'.
            # So if I make 'left_container', 'mid_container', 'right_container' fill the width, the content will be centered in each?
            # User wants "Three sections Center align". "Aligned same ratio".
            # This implies the 3 sections as a group are centered?
            # Or each section centered in its 1/3?
            # "세 섹션을 Center align해줄수 있나? 창이 커져도 가운데 같은 비율로 aligned 되게?"
            # This usually means centered as a block.
            # 300 | 240 | 240.
            # If I make the containers fixed size, grid will put them left.
            # I can use a container frame for all 3, and center that frame?
            # Changing hierarchy is invasive.
            # Alternative: Use padding in `_resize`.
            # If I calculate `start_x`, I can use `grid(padx=...)`?
            # But grid padding is per cell.
            # Or I can use `place` for the containers themselves?
            # Let's try `place` for containers.
            # `grid_forget` them and use `place`.
            # `ViewerTopPanel` is a Frame. I can place children.
            pass # I will modify _resize to use place for containers.

            left_container.grid_forget()
            mid_container.grid_forget()
            right_container.grid_forget()
            
            x = start_x
            left_container.place(x=x, y=0, width=w_left, height=max(left.winfo_reqheight(), 1))
            x += w_left + gap
            mid_container.place(x=x, y=0, width=w_mid, height=max(mid.winfo_reqheight(), 1))
            x += w_mid + gap
            right_container.place(x=x, y=0, width=w_right, height=max(right.winfo_reqheight(), 1))
            
            # Inner placement (centering inside container)
            # Since container width == content width (fixed), centering is trivial (relx=0.5 or 0).
            # 'left' is placed in 'left_container'.
            left.place(relx=0.0, x=0, width=w_left)
            # mid is placed in mid_container
            # right in right_container
            
            target_height = max(left.winfo_reqheight(), mid.winfo_reqheight(), right.winfo_reqheight(), 1)
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

    def _on_flip(self, callbacks, axis: str) -> None:
        var = getattr(self, f"_flip_{axis}_var", None)
        if var is None:
            return
        handler = getattr(callbacks, "on_viewer_flip_change", None)
        if callable(handler):
            handler(axis, var.get())

    def set_flip_values(self, x: bool, y: bool, z: bool) -> None:
        self._flip_x_var.set(bool(x))
        self._flip_y_var.set(bool(y))
        self._flip_z_var.set(bool(z))

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
        has_hook = bool(hook_name and hook_name != "None")
        display_name = hook_name if has_hook else "Disabled"
        self._hook_name_var.set(display_name)
        
        if not has_hook:
            self._hook_enabled_var.set(False)
        else:
            self._hook_enabled_var.set(bool(enabled))

        state = "normal" if allow_toggle and has_hook else "disabled"
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
