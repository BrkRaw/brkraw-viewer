from __future__ import annotations

import tkinter as tk
from tkinter import ttk, filedialog
import tkinter.font as tkfont
from pathlib import Path
from typing import Callable, List, Optional, Any

from brkraw_viewer.app.services.viewer_config import registry_columns


class RegistryWindow:
    def __init__(
        self,
        parent: tk.Misc,
        *,
        list_entries: Callable[[], List[dict]],
        add_paths: Callable[[List[Path]], tuple[int, int]],
        remove_paths: Callable[[List[Path]], int],
        scan_paths: Callable[[List[Path]], tuple[int, int]],
        open_path: Callable[[Path], None],
        get_current_path: Callable[[], Optional[Path]],
    ) -> None:
        self._list_entries = list_entries
        self._add_paths = add_paths
        self._remove_paths = remove_paths
        self._scan_paths = scan_paths
        self._open_path = open_path
        self._get_current_path = get_current_path

        self._window = tk.Toplevel(parent)
        self._window.title("Dataset Registry")
        self._window.geometry("920x420")
        self._window.minsize(760, 320)
        self._center_on_parent(parent)
        self._resize_job: Optional[str] = None

        toolbar = ttk.Frame(self._window, padding=(8, 8, 8, 4))
        toolbar.pack(side=tk.TOP, fill=tk.X)

        add_button = ttk.Menubutton(toolbar, text="+", width=3)
        add_menu = tk.Menu(add_button, tearoff=False)
        add_menu.add_command(label="Current session", command=self._add_current_session)
        add_menu.add_command(label="Folder (Study)…", command=self._add_folder)
        add_menu.add_command(label="Archive File (.zip / .PvDatasets)…", command=self._add_archive)
        add_button.configure(menu=add_menu)
        add_button.pack(side=tk.LEFT)
        self._add_menu = add_menu

        ttk.Button(toolbar, text="-", command=self._remove_selected, width=3).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Refresh", command=self.refresh).pack(side=tk.RIGHT)

        body = ttk.Frame(self._window, padding=(8, 0, 8, 6))
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        self._columns = self._load_columns()
        columns = [col["key"] for col in self._columns]
        tree = ttk.Treeview(body, columns=columns, show="headings", selectmode="extended")
        tree.grid(row=0, column=0, sticky="nsew")
        self._tree = tree

        vscroll = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
        vscroll.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=vscroll.set)

        tree.tag_configure("missing", foreground="#cc3333")
        tree.bind("<Double-1>", self._on_double_click)
        tree.bind("<Configure>", self._on_tree_resize)

        status_bar = ttk.Frame(self._window, padding=(8, 4))
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        status_bar.columnconfigure(0, weight=1)
        self._status_var = tk.StringVar(value="Ready")
        ttk.Label(status_bar, textvariable=self._status_var, anchor="w").grid(row=0, column=0, sticky="w")
        ttk.Button(status_bar, text="Load", command=self._open_selected).grid(row=0, column=1, sticky="e")

        self._sort_key: Optional[str] = None
        self._sort_desc = False
        self._configure_columns()
        self.refresh()
        self._update_add_menu_state()

    def winfo_exists(self) -> bool:
        return bool(self._window.winfo_exists())

    def lift(self) -> None:
        self._window.lift()
        self._window.focus_set()

    def destroy(self) -> None:
        if self._window.winfo_exists():
            self._window.destroy()

    def refresh(self) -> None:
        entries = self._list_entries()
        self._tree.delete(*self._tree.get_children())
        for entry in entries:
            values = [self._resolve_entry_value(entry, col["key"]) for col in self._columns]
            tag = "missing" if not entry.get("path") else ""
            self._tree.insert("", "end", values=values, tags=(tag,))
        self._status_var.set(f"{len(entries)} item(s)")
        self._update_add_menu_state()
        self._fit_columns()

    def set_status(self, text: str) -> None:
        self._status_var.set(text)

    def _load_columns(self) -> List[dict]:
        cols = registry_columns()
        normalized = []
        for col in cols:
            if isinstance(col, dict) and "key" in col:
                entry = dict(col)
                entry.setdefault("hidden", False)
                normalized.append(entry)
        return [c for c in normalized if not c.get("hidden")]

    def _configure_columns(self) -> None:
        for col in self._columns:
            key = col["key"]
            title = str(col.get("title") or key)
            width = int(col.get("width") or 120)
            anchor = "w" if key in ("basename", "path") else "center"
            self._tree.heading(key, text=title, command=lambda k=key: self._on_sort(k))
            self._tree.column(key, width=width, anchor=anchor, stretch=True)

    def _resolve_entry_value(self, entry: dict, key: str) -> Any:
        if key in entry:
            return entry.get(key, "")
        if key.startswith("Study."):
            study = entry.get("study", {})
            if isinstance(study, dict):
                return study.get(key.split(".", 1)[1], "")
        return ""

    def _selected_paths(self) -> List[Path]:
        out: List[Path] = []
        for item in self._tree.selection():
            values = self._tree.item(item, "values")
            if not values:
                continue
            try:
                path_idx = [c["key"] for c in self._columns].index("path")
            except ValueError:
                continue
            if path_idx < len(values):
                raw = values[path_idx]
                if raw:
                    out.append(Path(str(raw)))
        return out

    def _on_double_click(self, event: tk.Event) -> Optional[str]:
        region = self._tree.identify_region(int(event.x), int(event.y))
        if region == "separator":
            col_id = self._tree.identify_column(int(event.x))
            key = self._column_key_from_id(col_id)
            if key:
                self._autofit_column(key)
            return "break"
        self._open_selected()
        return None

    def _open_selected(self) -> None:
        paths = self._selected_paths()
        if paths:
            self._open_path(paths[0])

    def _remove_selected(self) -> None:
        paths = self._selected_paths()
        if not paths:
            return
        _ = self._remove_paths(paths)
        self._status_var.set("Removing...")

    def _add_current_session(self) -> None:
        path = self._get_current_path()
        if path is None:
            self._status_var.set("No dataset loaded")
            return
        _ = self._add_paths([path])
        self._status_var.set("Adding...")

    def _add_folder(self) -> None:
        path = filedialog.askdirectory(title="Select Bruker study folder")
        if not path:
            return
        _ = self._add_paths([Path(path)])
        self._status_var.set("Adding...")

    def _add_archive(self) -> None:
        path = filedialog.askopenfilename(
            title="Select Bruker dataset archive",
            filetypes=(
                ("Dataset archives", "*.zip *.PvDatasets *.pvdatasets"),
                ("All files", "*.*"),
            ),
        )
        if not path:
            return
        _ = self._add_paths([Path(path)])
        self._status_var.set("Adding...")

    def _update_add_menu_state(self) -> None:
        path = self._get_current_path()
        state = "normal" if path is not None else "disabled"
        try:
            self._add_menu.entryconfigure(0, state=state)
        except Exception:
            pass

    def _center_on_parent(self, parent: tk.Misc) -> None:
        try:
            parent.update_idletasks()
            self._window.update_idletasks()
        except Exception:
            pass
        w = int(self._window.winfo_width() or self._window.winfo_reqwidth() or 920)
        h = int(self._window.winfo_height() or self._window.winfo_reqheight() or 420)
        try:
            geo = parent.winfo_geometry()
            size, pos = geo.split("+", 1)
            pw_s, ph_s = size.split("x", 1)
            px_s, py_s = pos.split("+", 1)
            pw, ph = int(pw_s), int(ph_s)
            px, py = int(px_s), int(py_s)
            x = px + (pw - w) // 2
            y = py + (ph - h) // 2
        except Exception:
            sw = self._window.winfo_screenwidth()
            sh = self._window.winfo_screenheight()
            x = (sw - w) // 2
            y = (sh - h) // 2
        self._window.geometry(f"{w}x{h}+{x}+{y}")

    def _on_tree_resize(self, _event: tk.Event) -> None:
        if self._resize_job is not None:
            try:
                self._window.after_cancel(self._resize_job)
            except Exception:
                pass
        self._resize_job = self._window.after(50, self._fit_columns)

    def _column_key_from_id(self, col_id: str) -> Optional[str]:
        if not col_id.startswith("#"):
            return None
        try:
            idx = int(col_id[1:]) - 1
        except Exception:
            return None
        keys = [c["key"] for c in self._columns]
        if 0 <= idx < len(keys):
            return keys[idx]
        return None

    def _autofit_column(self, key: str) -> None:
        font = self._tree_font()
        header = str(self._tree.heading(key, "text") or key)
        max_w = font.measure(header) + 16
        for item in self._tree.get_children():
            values = self._tree.item(item, "values")
            idx = [c["key"] for c in self._columns].index(key)
            if idx < len(values):
                max_w = max(max_w, font.measure(str(values[idx])) + 16)
        self._tree.column(key, width=max_w, stretch=True)

    def _fit_columns(self) -> None:
        self._resize_job = None
        if not self._tree.winfo_exists():
            return
        font = self._tree_font()
        keys = [c["key"] for c in self._columns]
        widths: dict[str, int] = {}
        total = 0
        for key in keys:
            header = str(self._tree.heading(key, "text") or key)
            max_w = font.measure(header) + 16
            idx = keys.index(key)
            for item in self._tree.get_children():
                values = self._tree.item(item, "values")
                if idx < len(values):
                    max_w = max(max_w, font.measure(str(values[idx])) + 16)
            widths[key] = max_w
            total += max_w

        avail = max(int(self._tree.winfo_width()) - 8, 100)
        if total < avail:
            extra = avail - total
            flex_keys = [k for k in keys if k in ("path", "basename")] or keys
            if flex_keys:
                per = extra // len(flex_keys)
                for k in flex_keys:
                    widths[k] += per

        for key in keys:
            self._tree.column(key, width=widths[key], stretch=True)

    def _tree_font(self) -> tkfont.Font:
        try:
            return tkfont.nametofont(str(self._tree.cget("font")))
        except Exception:
            try:
                return tkfont.nametofont("TkDefaultFont")
            except Exception:
                return tkfont.Font()

    def _on_sort(self, key: str) -> None:
        if self._sort_key == key:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_key = key
            self._sort_desc = False
        self._apply_sort()
        self._update_sort_heading()

    def _apply_sort(self) -> None:
        if not self._sort_key:
            return
        key = self._sort_key
        keys = [c["key"] for c in self._columns]
        try:
            idx = keys.index(key)
        except ValueError:
            return
        items = list(self._tree.get_children())

        def _sort_value(item_id: str) -> tuple[int, Any]:
            values = self._tree.item(item_id, "values")
            raw = values[idx] if idx < len(values) else ""
            try:
                return (0, float(raw))
            except Exception:
                return (1, str(raw).lower())

        items.sort(key=_sort_value, reverse=self._sort_desc)
        for item in items:
            self._tree.move(item, "", "end")

    def _update_sort_heading(self) -> None:
        arrow = "▼" if self._sort_desc else "▲"
        for col in self._columns:
            key = col["key"]
            title = str(col.get("title") or key)
            label = f"{title} {arrow}" if key == self._sort_key else title
            self._tree.heading(key, text=label)
