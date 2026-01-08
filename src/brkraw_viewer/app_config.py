from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from brkraw.core import config as config_core


class ConfigTabMixin:
    _config_text: tk.Text
    _config_path_var: tk.StringVar

    def _build_config_tab(self, config_tab: ttk.Frame) -> None:
        config_tab.columnconfigure(0, weight=1)
        config_tab.rowconfigure(1, weight=1)
        config_bar = ttk.Frame(config_tab, padding=(6, 6))
        config_bar.grid(row=0, column=0, sticky="ew")
        ttk.Button(config_bar, text="Save", command=self._save_config_text).pack(side=tk.LEFT)
        ttk.Button(config_bar, text="Reset", command=self._reset_config_text).pack(side=tk.LEFT, padx=(6, 0))
        self._config_path_var = tk.StringVar(value="")
        ttk.Label(config_bar, textvariable=self._config_path_var).pack(side=tk.LEFT, padx=(12, 0))

        config_body = ttk.Frame(config_tab, padding=(6, 6))
        config_body.grid(row=1, column=0, sticky="nsew")
        config_body.columnconfigure(0, weight=1)
        config_body.rowconfigure(0, weight=1)
        self._config_text = tk.Text(config_body, wrap="none")
        self._config_text.grid(row=0, column=0, sticky="nsew")
        config_scroll = ttk.Scrollbar(config_body, orient="vertical", command=self._config_text.yview)
        config_scroll.grid(row=0, column=1, sticky="ns")
        self._config_text.configure(yscrollcommand=config_scroll.set)

    def _load_config_text(self) -> None:
        try:
            paths = config_core.ensure_initialized(root=None, create_config=True, exist_ok=True)
            self._config_path_var.set(str(paths.config_file))
            content = paths.config_file.read_text(encoding="utf-8")
        except Exception as exc:
            self._config_path_var.set("")
            self._config_text.delete("1.0", tk.END)
            self._config_text.insert(tk.END, f"# Failed to load config.yaml: {exc}\n")
            return
        self._config_text.delete("1.0", tk.END)
        self._config_text.insert(tk.END, content)

    def _save_config_text(self) -> None:
        try:
            paths = config_core.ensure_initialized(root=None, create_config=True, exist_ok=True)
            self._config_path_var.set(str(paths.config_file))
            text = self._config_text.get("1.0", tk.END)
            paths.config_file.write_text(text, encoding="utf-8")
        except Exception as exc:
            messagebox.showerror("Save error", f"Failed to save config.yaml:\n{exc}")

    def _reset_config_text(self) -> None:
        try:
            config_core.reset_config(root=None)
        except Exception as exc:
            messagebox.showerror("Reset error", f"Failed to reset config.yaml:\n{exc}")
            return
        self._load_config_text()
