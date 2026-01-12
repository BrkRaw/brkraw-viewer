from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Dict, Iterable, Optional


class ParamsPanel(ttk.Frame):
    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self._search_var = tk.StringVar(value="")

        search_bar = ttk.Frame(self)
        search_bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        search_bar.columnconfigure(1, weight=1)

        ttk.Label(search_bar, text="Search").grid(row=0, column=0, sticky="w")
        entry = ttk.Entry(search_bar, textvariable=self._search_var)
        entry.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        entry.bind("<Return>", self._on_search)
        ttk.Button(search_bar, text="Go", command=self._on_search).grid(row=0, column=2, padx=(6, 0))

        self._listbox = tk.Listbox(self, exportselection=False, height=10)
        self._listbox.grid(row=1, column=0, sticky="nsew")
        self._listbox.bind("<<ListboxSelect>>", self._on_select)

        self._text = tk.Text(self, wrap="word", height=12)
        self._text.grid(row=2, column=0, sticky="nsew", pady=(6, 0))
        self._text.configure(state=tk.DISABLED)

        self._params: Dict[str, Dict[str, Any]] = {}
        self._param_keys: list[str] = []

    def set_params(self, params: Dict[str, Dict[str, Any]]) -> None:
        self._params = params
        self._param_keys = sorted(params.keys())
        self._refresh_list(self._param_keys)
        self._set_text("Select a parameter file to view contents.")

    def clear(self) -> None:
        self._params = {}
        self._param_keys = []
        self._refresh_list([])
        self._set_text("No parameter data.")

    def _refresh_list(self, items: Iterable[str]) -> None:
        self._listbox.delete(0, tk.END)
        for item in items:
            self._listbox.insert(tk.END, item)

    def _set_text(self, text: str) -> None:
        self._text.configure(state=tk.NORMAL)
        self._text.delete("1.0", tk.END)
        self._text.insert(tk.END, text)
        self._text.configure(state=tk.DISABLED)

    def _on_search(self, *_: object) -> None:
        query = self._search_var.get().strip().lower()
        if not query:
            self._refresh_list(self._param_keys)
            return
        filtered = [key for key in self._param_keys if query in key.lower()]
        self._refresh_list(filtered)

    def _on_select(self, *_: object) -> None:
        selection = self._listbox.curselection()
        if not selection:
            return
        key = self._listbox.get(int(selection[0]))
        data = self._params.get(key)
        if not data:
            self._set_text("No data.")
            return
        lines = [f"[{key}]"]
        for k in sorted(data.keys()):
            lines.append(f"{k} = {data[k]}")
        self._set_text("\n".join(lines))
