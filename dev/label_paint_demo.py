from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from tkinter import colorchooser

import numpy as np

from brkraw_viewer.ui.components.viewport import ViewportCanvas
from brkraw_viewer.ui.components.label_painter import LabelMapPainter


class LabelPaintDemo(ttk.Frame):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)
        self.pack(fill="both", expand=True)

        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        # ---- toolbar ----
        bar = ttk.Frame(self)
        bar.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        bar.columnconfigure(99, weight=1)

        ttk.Label(bar, text="Brush").grid(row=0, column=0, sticky="w")

        # Brush as icon-like toggle buttons (ASCII outline)
        self.var_shape = tk.StringVar(value="circle")
        self._btn_brush_circle = ttk.Radiobutton(
            bar,
            text="( )",
            value="circle",
            variable=self.var_shape,
            command=self._apply_brush_settings,
        )
        self._btn_brush_circle.grid(row=0, column=1, padx=(6, 2))

        self._btn_brush_square = ttk.Radiobutton(
            bar,
            text="[ ]",
            value="square",
            variable=self.var_shape,
            command=self._apply_brush_settings,
        )
        self._btn_brush_square.grid(row=0, column=2, padx=(2, 10))

        # Erase as a toggle button near brush buttons (right-click erase still works)
        self.var_erase = tk.BooleanVar(value=False)
        self._btn_erase = ttk.Checkbutton(bar, text="Erase", variable=self.var_erase, command=self._apply_mode)
        self._btn_erase.grid(row=0, column=3, padx=(0, 14))

        ttk.Label(bar, text="Radius").grid(row=0, column=4, sticky="w")
        self.var_radius = tk.IntVar(value=1)
        radius = ttk.Spinbox(bar, width=5, from_=1, to=100, textvariable=self.var_radius, command=self._apply_brush_settings)
        radius.grid(row=0, column=5, padx=(6, 14))

        ttk.Label(bar, text="Label").grid(row=0, column=6, sticky="w")

        # Label state (exclude 0 - reserved for background/erase)
        self.var_label = tk.IntVar(value=1)
        self._label_display = tk.StringVar(value="1")
        self._label_items: list[int] = [1, 2, 3]
        self._label_add_token = "Add label..."
        # Label metadata state (demo): id -> display name
        self._label_names: dict[int, str] = {lab: f"Label {lab}" for lab in self._label_items}

        # Label selector using a Menubutton so we can show per-label color swatches.
        self._label_menu_images: dict[int, tk.PhotoImage] = {}
        self._label_menu = tk.Menu(bar, tearoff=0)
        self._label_btn = ttk.Menubutton(bar, textvariable=self._label_display, menu=self._label_menu, width=6)
        self._label_btn.grid(row=0, column=7, padx=(6, 6))

        # Clickable color swatch for the selected label (no separate Color button)
        self._swatch = tk.Canvas(bar, width=18, height=18, highlightthickness=1, highlightbackground="#666666", cursor="hand2")
        self._swatch.grid(row=0, column=8, padx=(0, 14))
        self._swatch.bind("<Button-1>", lambda _e: self._pick_label_color())

        self.var_overlay = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="Show overlay", variable=self.var_overlay, command=self._toggle_overlay).grid(row=0, column=9, padx=(6, 14))

        ttk.Button(bar, text="Clear", command=self._clear).grid(row=0, column=10, padx=(6, 0))
        ttk.Button(bar, text="Reset view", command=self._reset_view).grid(row=0, column=11, padx=(6, 0))
        ttk.Button(bar, text="Labels...", command=self._open_label_editor).grid(row=0, column=12, padx=(6, 0))

        # spacer
        ttk.Label(bar, text="").grid(row=0, column=98, sticky="ew")

        # ---- viewport ----
        self.vp = ViewportCanvas(self)
        self.vp.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

        # ---- painter ----
        self.painter = LabelMapPainter(self.vp)
        self.painter.throttle_ms = 33  # adjust if you want
        self.painter.attach()

        # ---- init base and label map ----
        # Defer initialization until after the widgets are realized, so the canvas has a real size.
        self.after_idle(lambda: self._init_empty_scene(h=25, w=25))

        # Label editor popup (created lazily)
        self._label_editor: tk.Toplevel | None = None
        self._label_tree: ttk.Treeview | None = None
        self._var_edit_id = tk.StringVar(value="")
        self._var_edit_name = tk.StringVar(value="")
        self._editor_color_swatch: tk.Canvas | None = None

        # keyboard shortcuts
        parent.bind("<Escape>", lambda _e: self._clear())
        parent.bind("<Key-plus>", lambda _e: self._bump_radius(+1))
        parent.bind("<Key-minus>", lambda _e: self._bump_radius(-1))

    def _label_color_hex(self, lab: int) -> str:
        try:
            lut = getattr(self.painter, "lut_rgba", None)
            if lut is not None and hasattr(lut, "shape") and lut.ndim == 2 and lut.shape[1] == 4 and 0 <= lab < lut.shape[0]:
                r, g, b = int(lut[lab][0]), int(lut[lab][1]), int(lut[lab][2])
                return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            pass
        return "#000000"

    def _label_display_for(self, lab: int) -> str:
        # Show both id and color so the dropdown gives immediate feedback.
        return f"{int(lab)} {self._label_color_hex(int(lab))}"

    def _label_swatch_image(self, lab: int) -> tk.PhotoImage:
        """Return a cached 12x12 PhotoImage filled with the label color."""
        img = self._label_menu_images.get(int(lab))
        if img is not None:
            return img
        img = tk.PhotoImage(width=12, height=12)
        img.put(self._label_color_hex(int(lab)), to=(0, 0, 12, 12))
        self._label_menu_images[int(lab)] = img
        return img

    def _set_selected_label(self, lab: int) -> None:
        self.var_label.set(int(lab))
        # Leaving erase mode if user explicitly selects a label
        self.var_erase.set(False)
        self._apply_label_settings()
        self._apply_mode()
        self._update_swatch()
        # Button text: show only the label id.
        self._label_display.set(f"{int(lab)}")

    def _rebuild_label_menu(self) -> None:
        """Rebuild the dropdown menu with per-label color swatches."""
        try:
            self._label_menu.delete(0, "end")
        except Exception:
            pass
        # Clear image cache so colors refresh after changes.
        self._label_menu_images.clear()

        for lab in self._label_items:
            lab_i = int(lab)
            # Menu entry shows a colored square image plus unicode square.
            img = self._label_swatch_image(lab_i)
            self._label_menu.add_command(
                label=f"{lab_i}",
                image=img,
                compound="left",
                command=lambda v=lab_i: self._set_selected_label(v),
            )

        self._label_menu.add_separator()
        # Lightweight label editor actions
        self._label_menu.add_command(label="+ Add label...", command=self._add_label)
        self._label_menu.add_command(label="- Del label...", command=self._del_label)

    def _add_label(self) -> None:
        # Choose the next available label id
        existing = set(int(x) for x in self._label_items)
        new_lab = 1
        while new_lab in existing:
            new_lab += 1
        self._label_items.append(new_lab)
        self._label_items = sorted(self._label_items)

        # Assign a default color (simple deterministic palette)
        palette = [
            (255, 0, 0),
            (0, 255, 0),
            (0, 128, 255),
            (255, 128, 0),
            (255, 0, 255),
            (0, 255, 255),
            (255, 255, 0),
        ]
        rgb = palette[new_lab % len(palette)]
        try:
            self.painter.set_label_color(int(new_lab), rgb, alpha=255)
        except Exception:
            pass

        # Refresh menu and select the new label
        self._rebuild_label_menu()
        self._set_selected_label(int(new_lab))
        self._label_names[int(new_lab)] = f"Label {int(new_lab)}"
        if self._label_editor is not None and bool(self._label_editor.winfo_exists()):
            self._refresh_label_editor()

    def _del_label(self) -> None:
        """Delete the currently selected label (except 0)."""
        try:
            cur = int(self.var_label.get())
        except Exception:
            cur = 1
        # Only labels in the list are deletable.
        if cur not in self._label_items:
            return
        if len(self._label_items) <= 1:
            # Keep at least one label.
            return
        self._label_items = [x for x in self._label_items if int(x) != int(cur)]
        self._label_items = sorted(int(x) for x in self._label_items)

        self._label_names.pop(int(cur), None)

        # Choose a new current label (nearest, otherwise first)
        if self._label_items:
            new_cur = self._label_items[0]
        else:
            new_cur = 1
            self._label_items = [new_cur]

        self._rebuild_label_menu()
        self._set_selected_label(int(new_cur))
        if self._label_editor is not None and bool(self._label_editor.winfo_exists()):
            self._refresh_label_editor()

    def _get_label_matrix(self) -> np.ndarray | None:
        """Return the label matrix to edit (2D for this demo)."""
        return self.painter.label_map

    def _relabel_in_matrix(self, old: int, new: int) -> None:
        lm = self._get_label_matrix()
        if lm is None:
            return
        if int(old) == int(new):
            return
        lm[lm == int(old)] = int(new)

    def _delete_in_matrix(self, lab: int) -> None:
        lm = self._get_label_matrix()
        if lm is None:
            return
        lm[lm == int(lab)] = 0

    def _prompt_id_conflict(self, *, old: int, new: int) -> str | None:
        """Prompt user when NEW label id already exists.

        Returns: "merge", "replace", or None (cancel/close).
        """
        top = tk.Toplevel(self)
        top.title("Label ID conflict")
        top.transient(self.winfo_toplevel())
        try:
            top.grab_set()
        except Exception:
            pass

        choice: dict[str, str | None] = {"v": None}

        frm = ttk.Frame(top, padding=12)
        frm.pack(fill="both", expand=True)

        msg = (
            f"Label {new} already exists. What do you want to do with label {old} - > {new}?\n\n"
            "Merge: add old voxels into the existing label.\n"
            "Replace: overwrite the existing label voxels with the old label voxels.\n"
        )
        ttk.Label(frm, text=msg, justify="left").grid(row=0, column=0, columnspan=3, sticky="w")

        def _set(v: str | None) -> None:
            choice["v"] = v
            try:
                top.grab_release()
            except Exception:
                pass
            top.destroy()

        btn_merge = ttk.Button(frm, text="Merge", command=lambda: _set("merge"))
        btn_merge.grid(row=1, column=0, padx=(0, 6), pady=(10, 0), sticky="ew")

        btn_replace = ttk.Button(frm, text="Replace", command=lambda: _set("replace"))
        btn_replace.grid(row=1, column=1, padx=(0, 6), pady=(10, 0), sticky="ew")

        btn_cancel = ttk.Button(frm, text="Cancel", command=lambda: _set(None))
        btn_cancel.grid(row=1, column=2, padx=(0, 0), pady=(10, 0), sticky="ew")

        frm.columnconfigure(0, weight=1)
        frm.columnconfigure(1, weight=1)
        frm.columnconfigure(2, weight=1)

        top.protocol("WM_DELETE_WINDOW", lambda: _set(None))
        try:
            top.wait_window()
        except Exception:
            pass
        return choice["v"]

    def _remove_label_id(self, lab: int) -> None:
        self._label_items = [int(x) for x in self._label_items if int(x) != int(lab)]
        self._label_items = sorted(set(int(x) for x in self._label_items))
        self._label_names.pop(int(lab), None)
        if not self._label_items:
            self._label_items = [1]
            self._label_names.setdefault(1, "Label 1")

    def _open_label_editor(self) -> None:
        # Reuse if already open
        if self._label_editor is not None and bool(self._label_editor.winfo_exists()):
            try:
                self._label_editor.lift()
                self._label_editor.focus_force()
            except Exception:
                pass
            self._refresh_label_editor()
            return

        win = tk.Toplevel(self)
        win.title("Label editor")
        win.transient(self.winfo_toplevel())
        try:
            win.grab_set()  # modal-ish for a demo
        except Exception:
            pass
        self._label_editor = win

        frm = ttk.Frame(win, padding=10)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(0, weight=1)

        tree = ttk.Treeview(frm, columns=("id", "name", "color"), show="headings", selectmode="browse", height=8)
        tree.heading("id", text="Label")
        tree.heading("name", text="Name")
        tree.heading("color", text="Color")
        tree.column("id", width=70, anchor="center")
        tree.column("name", width=180, anchor="w")
        tree.column("color", width=120, anchor="center")
        tree.grid(row=0, column=0, sticky="nsew")
        self._label_tree = tree

        sb = ttk.Scrollbar(frm, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        sb.grid(row=0, column=1, sticky="ns")

        # ---- edit controls ----
        ctl = ttk.Frame(frm)
        ctl.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ctl.columnconfigure(11, weight=1)

        ttk.Label(ctl, text="Selected label").grid(row=0, column=0, sticky="w")
        ent = ttk.Entry(ctl, width=6, textvariable=self._var_edit_id)
        ent.grid(row=0, column=1, padx=(6, 12), sticky="w")

        ttk.Label(ctl, text="Name").grid(row=0, column=2, sticky="w")
        ent_name = ttk.Entry(ctl, width=18, textvariable=self._var_edit_name)
        ent_name.grid(row=0, column=3, padx=(6, 12), sticky="w")

        ttk.Button(ctl, text="Change ID", command=self._editor_change_id).grid(row=0, column=4, padx=(0, 6))
        ttk.Button(ctl, text="Merge", command=self._editor_merge_into_id).grid(row=0, column=5, padx=(0, 10))

        # Color swatch + picker
        self._editor_color_swatch = tk.Canvas(ctl, width=14, height=14, highlightthickness=1, highlightbackground="#666666")
        self._editor_color_swatch.grid(row=0, column=6, padx=(0, 6))
        ttk.Button(ctl, text="Color...", command=self._editor_pick_color).grid(row=0, column=7, padx=(0, 6))

        ttk.Button(ctl, text="Rename", command=self._editor_rename_label).grid(row=0, column=8, padx=(0, 6))
        ttk.Button(ctl, text="Delete", command=self._editor_delete_label).grid(row=0, column=9, padx=(0, 6))
        ttk.Button(ctl, text="Add", command=self._editor_add_label).grid(row=0, column=10, padx=(0, 0))

        # Enter key on name field applies rename
        ent_name.bind("<Return>", lambda _e: self._editor_rename_label())

        msg = ttk.Label(ctl, text="Tip: Change ID updates the label matrix; Delete sets voxels to 0.")
        msg.grid(row=1, column=0, columnspan=12, sticky="w", pady=(8, 0))

        def _on_select(_e=None):
            self._editor_sync_selection_to_entry()
        tree.bind("<<TreeviewSelect>>", _on_select)

        def _on_close():
            try:
                win.grab_release()
            except Exception:
                pass
            win.destroy()
            self._label_editor = None
            self._label_tree = None
        win.protocol("WM_DELETE_WINDOW", _on_close)

        self._refresh_label_editor()

    def _refresh_label_editor(self) -> None:
        tree = self._label_tree
        if tree is None:
            return
        # Clear
        for iid in tree.get_children(""):
            tree.delete(iid)
        # Populate
        for lab in sorted(int(x) for x in self._label_items):
            name = self._label_names.get(int(lab), f"Label {int(lab)}")
            tree.insert("", "end", iid=str(lab), values=(str(lab), name, self._label_color_hex(lab)))
        # Select current
        try:
            cur = int(self.var_label.get())
        except Exception:
            cur = 1
        if str(cur) in tree.get_children(""):
            tree.selection_set(str(cur))
            tree.see(str(cur))
        self._editor_sync_selection_to_entry()

    def _editor_sync_selection_to_entry(self) -> None:
        tree = self._label_tree
        if tree is None:
            return
        sel = tree.selection()
        if not sel:
            self._var_edit_id.set("")
            self._var_edit_name.set("")
            # Clear swatch
            try:
                sw = self._editor_color_swatch
                if sw is not None:
                    sw.delete("all")
            except Exception:
                pass
            return
        try:
            lab = int(sel[0])
        except Exception:
            self._var_edit_id.set("")
            self._var_edit_name.set("")
            try:
                sw = self._editor_color_swatch
                if sw is not None:
                    sw.delete("all")
            except Exception:
                pass
            return
        self._var_edit_id.set(str(lab))
        self._var_edit_name.set(self._label_names.get(int(lab), f"Label {int(lab)}"))
        # Update popup color swatch
        try:
            sw = self._editor_color_swatch
            if sw is not None:
                sw.delete("all")
                sw.create_rectangle(0, 0, 14, 14, outline="", fill=self._label_color_hex(int(lab)))
        except Exception:
            pass

    def _editor_add_label(self) -> None:
        self._add_label()
        self._refresh_label_editor()

    def _editor_delete_label(self) -> None:
        tree = self._label_tree
        if tree is None:
            return
        sel = tree.selection()
        if not sel:
            return
        try:
            lab = int(sel[0])
        except Exception:
            return
        if lab not in self._label_items:
            return
        # Delete from matrix and list
        self._delete_in_matrix(lab)
        self._label_items = [int(x) for x in self._label_items if int(x) != lab]
        self._label_names.pop(int(lab), None)
        if not self._label_items:
            self._label_items = [1]
        # Choose a new current label
        new_cur = sorted(self._label_items)[0]
        self._rebuild_label_menu()
        self._set_selected_label(int(new_cur))
        self._refresh_label_editor()
        if self.var_overlay.get():
            self.painter.refresh_overlay_full()

    def _editor_merge_into_id(self) -> None:
        tree = self._label_tree
        if tree is None:
            return
        sel = tree.selection()
        if not sel:
            return
        try:
            old = int(sel[0])
        except Exception:
            return
        try:
            new = int((self._var_edit_id.get() or "").strip())
        except Exception:
            return
        if new < 1 or old < 1:
            return
        if new == old:
            return
        if new not in self._label_items:
            return

        # Merge semantics
        self._relabel_in_matrix(old, new)
        self._remove_label_id(old)

        self._rebuild_label_menu()
        self._set_selected_label(int(new))
        self._refresh_label_editor()
        if self.var_overlay.get():
            self.painter.refresh_overlay_full()

    def _editor_change_id(self) -> None:
        tree = self._label_tree
        if tree is None:
            return
        sel = tree.selection()
        if not sel:
            return
        try:
            old = int(sel[0])
        except Exception:
            return
        try:
            new = int((self._var_edit_id.get() or "").strip())
        except Exception:
            return
        if new < 1:
            return
        if old == new:
            return
        conflict_action: str | None = None
        if new in self._label_items:
            conflict_action = self._prompt_id_conflict(old=old, new=new)
            if conflict_action is None:
                return

        # Update matrix values
        if conflict_action == "replace":
            # Overwrite: clear existing NEW voxels first
            lm = self._get_label_matrix()
            if lm is not None:
                lm[lm == int(new)] = 0
            self._relabel_in_matrix(old, new)
        else:
            # Normal change or merge
            self._relabel_in_matrix(old, new)

        # Update item list / metadata
        if conflict_action in ("merge", "replace"):
            # NEW already exists: remove OLD only, keep NEW metadata
            self._remove_label_id(old)
        else:
            # NEW does not exist: replace id in list and transfer name
            self._label_items = [int(new) if int(x) == old else int(x) for x in self._label_items]
            self._label_items = sorted(set(int(x) for x in self._label_items))

            old_name = self._label_names.pop(int(old), None)
            if old_name is None:
                old_name = f"Label {int(new)}"
            self._label_names[int(new)] = old_name

            # Transfer color (copy lut entry old->new if possible)
            try:
                lut = getattr(self.painter, "lut_rgba", None)
                if lut is not None and hasattr(lut, "shape") and lut.ndim == 2 and lut.shape[1] == 4 and 0 <= old < lut.shape[0]:
                    rgba = lut[old]
                    self.painter.set_label_color(int(new), (int(rgba[0]), int(rgba[1]), int(rgba[2])), alpha=int(rgba[3]))
            except Exception:
                pass

        self._rebuild_label_menu()
        self._set_selected_label(int(new))
        self._var_edit_name.set(self._label_names.get(int(new), f"Label {int(new)}"))
        self._refresh_label_editor()
        if self.var_overlay.get():
            self.painter.refresh_overlay_full()

    def _editor_rename_label(self) -> None:
        tree = self._label_tree
        if tree is None:
            return
        sel = tree.selection()
        if not sel:
            return
        try:
            lab = int(sel[0])
        except Exception:
            return
        name = (self._var_edit_name.get() or "").strip()
        if not name:
            name = f"Label {int(lab)}"
        self._label_names[int(lab)] = name
        self._refresh_label_editor()

    def _editor_pick_color(self) -> None:
        tree = self._label_tree
        if tree is None:
            return
        sel = tree.selection()
        if not sel:
            return
        try:
            lab = int(sel[0])
        except Exception:
            return
        rgb, _hex = colorchooser.askcolor(title=f"Pick color for label {lab}")
        if rgb is None:
            return
        r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])
        self.painter.set_label_color(lab, (r, g, b), alpha=255)
        self._update_swatch()
        self._rebuild_label_menu()
        self._refresh_label_editor()
        try:
            sw = self._editor_color_swatch
            if sw is not None:
                sw.delete("all")
                sw.create_rectangle(0, 0, 14, 14, outline="", fill=self._label_color_hex(int(lab)))
        except Exception:
            pass
        if self.var_overlay.get():
            self.painter.refresh_overlay_full()

    def _apply_brush_settings(self) -> None:
        shp = (self.var_shape.get() or "").strip() or "circle"
        try:
            rad = int(self.var_radius.get())
        except Exception:
            return
        if rad < 1:
            rad = 1
        self.painter.set_brush(radius=rad, shape=shp)

    def _apply_label_settings(self) -> None:
        try:
            lab = int(self.var_label.get())
        except Exception:
            return
        # Exclude background label 0 from the selector.
        if lab < 1:
            lab = 1
        self.var_label.set(lab)
        try:
            self._label_display.set(f"{int(lab)}")
        except Exception:
            pass
        if not self.var_erase.get():
            self.painter.set_active_label(lab)
        self._update_swatch()

    def _apply_mode(self) -> None:
        if self.var_erase.get():
            self.painter.set_active_label(self.painter.erase_label)
        else:
            try:
                lab = int(self.var_label.get())
            except Exception:
                lab = 1
            self.painter.set_active_label(lab)

    def _update_swatch(self) -> None:
        try:
            lab = int(self.var_label.get())
        except Exception:
            lab = 1
        rgba = None
        try:
            lut = getattr(self.painter, "lut_rgba", None)
            if lut is not None and hasattr(lut, "shape") and lut.ndim == 2 and lut.shape[1] == 4 and 0 <= lab < lut.shape[0]:
                rgba = lut[lab]
        except Exception:
            rgba = None

        if rgba is None:
            color = "#000000"
        else:
            r, g, b = int(rgba[0]), int(rgba[1]), int(rgba[2])
            color = f"#{r:02x}{g:02x}{b:02x}"

        try:
            self._swatch.delete("all")
            self._swatch.create_rectangle(0, 0, 18, 18, outline="", fill=color)
        except Exception:
            pass

    def _pick_label_color(self) -> None:
        try:
            lab = int(self.var_label.get())
        except Exception:
            lab = 1
        rgb, _hex = colorchooser.askcolor(title=f"Pick color for label {lab}")
        if rgb is None:
            return
        r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])
        self.painter.set_label_color(lab, (r, g, b), alpha=255)
        self._update_swatch()
        self._rebuild_label_menu()
        try:
            self._label_display.set(f"{int(lab)}")
        except Exception:
            pass

    def _toggle_overlay(self) -> None:
        if not self.var_overlay.get():
            self.vp.set_overlay_rgba(None)
        else:
            self.painter.refresh_overlay_full()

    def _clear(self) -> None:
        lm = self.painter.label_map
        if lm is None:
            return
        lm[:] = 0
        if self.var_overlay.get():
            self.painter.refresh_overlay_full()
        else:
            self.vp.set_overlay_rgba(None)

    def _reset_view(self) -> None:
        shape = self.vp.get_image_shape()
        if shape is None:
            return
        h, w = shape
        base = np.zeros((h, w), dtype=np.float32)
        self.vp.set_view(base=base, title="Label paint demo (empty underlay)")
        if self.var_overlay.get():
            self.painter.refresh_overlay_full()

    def _bump_radius(self, delta: int) -> None:
        r = int(self.var_radius.get())
        r = max(1, r + int(delta))
        self.var_radius.set(r)
        self._apply_brush_settings()

    def _init_empty_scene(self, *, h: int, w: int) -> None:
        base = np.zeros((h, w), dtype=np.float32)  # empty underlay
        self.vp.set_view(
            base=base,
            title="Label paint demo (empty underlay)",
            show_crosshair=False,
            show_colorbar=False,
            allow_upsample=True,
        )
        try:
            self.vp.update_idletasks()
        except Exception:
            pass

        self.painter.ensure_label_map(dtype=np.uint16)
        self.painter.refresh_overlay_full()

        self._apply_brush_settings()
        self._apply_label_settings()
        self._apply_mode()
        self._update_swatch()
        try:
            self._rebuild_label_menu()
            self._label_display.set(f"{int(self.var_label.get())}")
        except Exception:
            pass


def main() -> int:
    root = tk.Tk()
    root.title("BrkRaw Viewer - Label Painter Demo")

    root.geometry("900x700")
    root.minsize(600, 450)

    try:
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:
        pass

    LabelPaintDemo(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())