from __future__ import annotations

import logging
import tkinter as tk
from tkinter import ttk
from typing import Any, Dict, Optional

from brkraw_viewer.app.services.hooks import load_viewer_hooks

logger = logging.getLogger("brkraw.viewer")


class ExtensionsTab:
    TITLE = "Extensions"
    _last_selected: Optional[str] = None

    def __init__(self, parent: tk.Misc, callbacks) -> None:
        self._cb = callbacks
        self.frame = ttk.Frame(parent)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(1, weight=1)
        try:
            self.frame.grid_anchor("n")
        except Exception:
            pass

        self._extensions_hooks: Dict[str, Any] = {}
        self._extensions_combo: Optional[ttk.Combobox] = None
        self._extensions_container: Optional[ttk.Frame] = None
        self._extensions_current_widget: Optional[tk.Widget] = None

        self._build()

    def _build(self) -> None:
        available: Dict[str, Any] = {}
        for hook in load_viewer_hooks():
            build_tab = getattr(hook, "build_tab", None)
            if callable(build_tab):
                name = getattr(hook, "name", None) or getattr(hook, "tab_title", None) or "Extension"
                available[str(name)] = hook

        tab = self.frame
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)

        header = ttk.Frame(tab)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 6), padx=6)
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text="Extension").grid(row=0, column=0, sticky="w")

        names = sorted(available.keys())
        combo = ttk.Combobox(
            header,
            state="readonly",
            values=["None", *names],
            width=30,
        )
        combo.grid(row=0, column=1, sticky="w", padx=(8, 0))
        combo.set("None")
        combo.bind("<<ComboboxSelected>>", self._on_extension_selected)
        self._extensions_combo = combo

        container = ttk.Frame(tab)
        container.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 6))
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)
        self._extensions_container = container
        try:
            container.grid_anchor("n")
        except Exception:
            pass

        if not available:
            ttk.Label(container, text="No extensions available.", anchor="w").grid(
                row=0, column=0, sticky="nw", padx=6, pady=6
            )
            return

        self._extensions_hooks = available
        if ExtensionsTab._last_selected in available:
            combo.set(ExtensionsTab._last_selected)
            self._select_extension(ExtensionsTab._last_selected)

    def _on_extension_selected(self, *_: object) -> None:
        if self._extensions_container is None or self._extensions_combo is None:
            return
        name = self._extensions_combo.get()
        self._select_extension(name)

    def _select_extension(self, name: str) -> None:
        if self._extensions_container is None:
            return
        if self._extensions_current_widget is not None:
            try:
                self._extensions_current_widget.destroy()
            except Exception:
                pass
            self._extensions_current_widget = None
        if not name or name == "None":
            ExtensionsTab._last_selected = None
            self._fit_detached_window()
            return
        hook = self._extensions_hooks.get(name)
        if hook is None:
            return
        build_tab = getattr(hook, "build_tab", None)
        if not callable(build_tab):
            return
        try:
            widget = build_tab(self._extensions_container, self._cb)
        except Exception as exc:
            logger.warning("Failed to build extension tab for %s: %s", name, exc)
            return
        if widget is None:
            return
        if not isinstance(widget, tk.Widget):
            logger.warning("Extension %s returned non-widget tab: %s", name, widget)
            return
        widget.grid(row=0, column=0, sticky="nsew")
        self._extensions_current_widget = widget
        ExtensionsTab._last_selected = name
        self._fit_detached_window()

    def _fit_detached_window(self) -> None:
        if self._extensions_current_widget is None:
            return
        try:
            win = self.frame.winfo_toplevel()
        except Exception:
            return
        try:
            if str(win.title()) != self.TITLE:
                return
        except Exception:
            return
        try:
            win.update_idletasks()
        except Exception:
            pass
        try:
            req_w = int(self._extensions_current_widget.winfo_reqwidth())
            req_h = int(self._extensions_current_widget.winfo_reqheight())
        except Exception:
            return
        pad_w = 24
        pad_h = 64
        width = max(req_w + pad_w, 360)
        height = max(req_h + pad_h, 240)
        try:
            win.geometry(f"{width}x{height}")
        except Exception:
            pass
