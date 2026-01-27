from __future__ import annotations

import tkinter as tk
from tkinter import ttk, filedialog
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

        hscroll = ttk.Scrollbar(body, orient="horizontal", command=tree.xview)
        hscroll.grid(row=1, column=0, sticky="ew")
        tree.configure(xscrollcommand=hscroll.set)

        tree.tag_configure("missing", foreground="#cc3333")
        tree.bind("<Double-1>", self._on_double_click)

        status_bar = ttk.Frame(self._window, padding=(8, 4))
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        status_bar.columnconfigure(0, weight=1)
        self._status_var = tk.StringVar(value="Ready")
        ttk.Label(status_bar, textvariable=self._status_var, anchor="w").grid(row=0, column=0, sticky="w")
        ttk.Button(status_bar, text="Load", command=self._open_selected).grid(row=0, column=1, sticky="e")

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
            self._tree.heading(key, text=title)
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

    def _on_double_click(self, _evt: object) -> None:
        self._open_selected()

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
