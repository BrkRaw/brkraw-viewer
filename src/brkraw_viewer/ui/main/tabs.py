from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Dict, Optional, Tuple


class TabsArea(ttk.Frame):
    def __init__(self, master: tk.Misc, *, callbacks: object) -> None:
        super().__init__(master)
        self._cb = callbacks
        self._tab_builders: Dict[str, Callable[[tk.Misc], ttk.Frame]] = {}
        self._tab_widgets: Dict[str, ttk.Frame] = {}
        self._detached: Dict[str, Tuple[tk.Toplevel, ttk.Frame, int]] = {}
        self._detached_geom: Dict[str, str] = {}

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.notebook = ttk.Notebook(self)
        style = ttk.Style()
        try:
            style.configure("BrkRaw.TNotebook", padding=0)
            style.configure("BrkRaw.TNotebook.Tab", padding=(8, 2))
            self.notebook.configure(style="BrkRaw.TNotebook")
            self.notebook.configure(padding=0)
        except Exception:
            pass
        self.notebook.grid(row=0, column=0, sticky="nsew")

        # Right-click context menu for detach/attach.
        # - Windows/Linux: Button-3
        # - macOS: Button-2 often maps to right click
        self.notebook.bind("<Button-3>", self._on_context_menu, add=True)
        self.notebook.bind("<Button-2>", self._on_context_menu, add=True)
        # - macOS fallback: Control-click
        self.notebook.bind("<Control-Button-1>", self._on_context_menu, add=True)

    def register_tab(self, title: str, builder: Callable[[tk.Misc], ttk.Frame]) -> None:
        self._tab_builders[title] = builder

    def get_tab(self, title: str) -> Optional[ttk.Frame]:
        tab = self._tab_widgets.get(title)
        if tab is not None:
            return tab
        detached = self._detached.get(title)
        if detached is None:
            return None
        return detached[1]

    def get_selected_title(self) -> Optional[str]:
        try:
            tab_id = self.notebook.select()
            if not tab_id:
                return None
            return str(self.notebook.tab(tab_id, "text")) or None
        except Exception:
            return None

    def select_tab(self, title: str) -> None:
        tab = self._tab_widgets.get(title)
        if tab is None:
            return
        try:
            self.notebook.select(tab)
        except Exception:
            pass

    def build_tabs(self) -> None:
        # Rebuild attached tabs only (do not touch detached windows)
        for title, tab in list(self._tab_widgets.items()):
            try:
                self.notebook.forget(tab)
            except Exception:
                pass
            try:
                tab.destroy()
            except Exception:
                pass
        self._tab_widgets.clear()

        for title, builder in self._tab_builders.items():
            if title in self._detached:
                continue
            tab = builder(self.notebook)
            try:
                tab.grid_anchor("n")
            except Exception:
                pass
            self.notebook.add(tab, text=title)
            self._tab_widgets[title] = tab

    def set_tabs_enabled(self, enabled: bool) -> None:
        current = None
        try:
            current = self.get_selected_title()
        except Exception:
            current = None
        for tab_id in self.notebook.tabs():
            try:
                title = str(self.notebook.tab(tab_id, "text"))
                if enabled:
                    self.notebook.tab(tab_id, state="normal")
                else:
                    if title in {"Config", "Viewer"}:
                        self.notebook.tab(tab_id, state="normal")
                    else:
                        self.notebook.tab(tab_id, state="disabled")
            except Exception:
                pass
        if not enabled and current == "Config":
            try:
                self.select_tab("Viewer")
            except Exception:
                pass

    def _center_on_parent(self, win: tk.Toplevel, *, width: Optional[int] = None, height: Optional[int] = None) -> None:
        parent = self.winfo_toplevel()
        try:
            parent.update_idletasks()
            win.update_idletasks()
        except Exception:
            pass

        # Determine window size
        w = int(width or win.winfo_width() or win.winfo_reqwidth() or 800)
        h = int(height or win.winfo_height() or win.winfo_reqheight() or 600)

        # Parent geometry: "WxH+X+Y"
        try:
            geo = parent.winfo_geometry()
            size, pos = geo.split("+", 1)
            pw_s, ph_s = size.split("x", 1)
            px_s, py_s = pos.split("+", 1)
            pw, ph = int(pw_s), int(ph_s)
            px, py = int(px_s), int(py_s)
        except Exception:
            # Fallback to screen center
            sw = win.winfo_screenwidth()
            sh = win.winfo_screenheight()
            x = (sw - w) // 2
            y = (sh - h) // 2
            win.geometry(f"{w}x{h}+{x}+{y}")
            return

        x = px + (pw - w) // 2
        y = py + (ph - h) // 2
        win.geometry(f"{w}x{h}+{x}+{y}")

    def _tab_title_at(self, x: int, y: int) -> Optional[str]:
        try:
            index = self.notebook.index(f"@{x},{y}")
        except Exception:
            return None
        try:
            tab_id = self.notebook.tabs()[index]
            title = str(self.notebook.tab(tab_id, "text"))
            return title or None
        except Exception:
            return None

    def _on_context_menu(self, event: tk.Event) -> None:
        title = self._tab_title_at(int(event.x), int(event.y))
        if not title:
            return

        menu = tk.Menu(self, tearoff=False)
        if title in self._detached:
            menu.add_command(label="Re-attach", command=lambda t=title: self.attach_tab(t))
        else:
            menu.add_command(label="Detach", command=lambda t=title: self.detach_tab(t))

        try:
            menu.tk_popup(int(event.x_root), int(event.y_root))
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass

    def detach_tab(self, title: str) -> None:
        if title in self._detached:
            return

        builder = self._tab_builders.get(title)
        tab = self._tab_widgets.get(title)
        if builder is None or tab is None:
            return

        # Remember current index so we can re-insert at the same position
        idx = 0
        try:
            idx = int(self.notebook.index(tab))
        except Exception:
            idx = 0

        # Remove from notebook
        try:
            self.notebook.forget(tab)
        except Exception:
            pass
        try:
            tab.destroy()
        except Exception:
            pass
        self._tab_widgets.pop(title, None)

        # Create detached window
        win = tk.Toplevel(self)
        win.title(title)

        frame = builder(win)
        frame.pack(fill="both", expand=True, anchor="n")
        self._notify_tab_detached(title)

        # Restore previous geometry if known, otherwise center on parent
        try:
            win.update_idletasks()
        except Exception:
            pass

        geo = self._detached_geom.get(title)
        if geo:
            try:
                win.geometry(geo)
            except Exception:
                self._center_on_parent(win)
        else:
            self._center_on_parent(win)

        def _on_close() -> None:
            self.attach_tab(title)

        win.protocol("WM_DELETE_WINDOW", _on_close)
        self._detached[title] = (win, frame, idx)

    def attach_tab(self, title: str) -> None:
        pair = self._detached.pop(title, None)
        builder = self._tab_builders.get(title)
        if pair is None or builder is None:
            return

        win, frame, idx = pair

        # Remember geometry for next detach
        try:
            self._detached_geom[title] = win.geometry()
        except Exception:
            pass

        try:
            frame.destroy()
        except Exception:
            pass
        try:
            win.destroy()
        except Exception:
            pass

        tab = builder(self.notebook)
        try:
            tab.grid_anchor("n")
        except Exception:
            pass

        # Insert at original position
        try:
            insert_at = min(max(int(idx), 0), len(self.notebook.tabs()))
            self.notebook.insert(insert_at, tab, text=title)
        except Exception:
            # Fallback
            self.notebook.add(tab, text=title)

        self._tab_widgets[title] = tab
        self._notify_tab_built(title)
        try:
            self.notebook.select(tab)
        except Exception:
            pass

    def _notify_tab_built(self, title: str) -> None:
        cb = getattr(self._cb, "on_tab_built", None)
        if callable(cb):
            try:
                cb(str(title))
            except Exception:
                pass

    def _notify_tab_detached(self, title: str) -> None:
        cb = getattr(self._cb, "on_tab_detached", None)
        if callable(cb):
            try:
                cb(str(title))
            except Exception:
                pass

    def _refresh_view(self) -> None:
        cb = getattr(self._cb, "on_refresh", None)
        if callable(cb):
            try:
                cb()
            except Exception:
                pass

    def _add_tab(self, title: str) -> ttk.Frame:
        tab = ttk.Frame(self.notebook)
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)
        self.notebook.add(tab, text=title)
        return tab
