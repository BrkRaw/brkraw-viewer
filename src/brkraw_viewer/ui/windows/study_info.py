from __future__ import annotations

import datetime as dt
import tkinter as tk
from tkinter import ttk
from typing import Any, Iterable, Optional


SUBJECT_FIELDS: list[tuple[str, list[tuple[str, str]]]] = [
    ("Study Operator", [("Study", "Opperator"), ("Study", "Operator")]),
    ("Study Date", [("Study", "Date")]),
    ("Study ID", [("Study", "ID")]),
    ("Study Number", [("Study", "Number")]),
    ("Subject ID", [("Subject", "ID")]),
    ("Subject Name", [("Subject", "Name")]),
    ("Subject Type", [("Subject", "Type")]),
    ("Subject Sex", [("Subject", "Sex")]),
    ("Subject DOB", [("Subject", "DateOfBirth")]),
    ("Subject Weight", [("Subject", "Weight")]),
    ("Subject Position", [("Subject", "Position")]),
]


class StudyInfoWindow:
    def __init__(self, parent: tk.Misc, info: dict) -> None:
        self._info = info or {}
        self._window = tk.Toplevel(parent)
        self._window.title("Study Info")
        self._window.geometry("720x280")
        self._window.minsize(560, 220)

        frame = ttk.Frame(self._window, padding=(10, 10))
        frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(3, weight=1)

        self._entries: dict[str, ttk.Entry] = {}
        for idx, (label, _) in enumerate(SUBJECT_FIELDS):
            row = idx // 2
            col = (idx % 2) * 2
            ttk.Label(frame, text=label).grid(row=row, column=col, sticky="w", padx=6, pady=3)
            entry = ttk.Entry(frame, width=22)
            entry.grid(row=row, column=col + 1, sticky="ew", padx=(0, 6), pady=3)
            entry.configure(state="readonly")
            self._entries[label] = entry

        self.update_info(self._info)
        self._fit_to_content()
        _center_window(self._window, parent)

    def winfo_exists(self) -> bool:
        return bool(self._window.winfo_exists())

    def lift(self) -> None:
        self._window.lift()
        self._window.focus_set()

    def destroy(self) -> None:
        if self._window.winfo_exists():
            self._window.destroy()

    def update_info(self, info: dict) -> None:
        self._info = info or {}
        for label, paths in SUBJECT_FIELDS:
            value = None
            for path in paths:
                value = _lookup_nested(self._info, path)
                if value not in (None, ""):
                    break
            if label == "Study Date":
                value = _format_study_date(value)
            entry = self._entries.get(label)
            if entry is None:
                continue
            entry.configure(state="normal")
            entry.delete(0, tk.END)
            entry.insert(0, _format_value(value) if value is not None else "")
            entry.configure(state="readonly")
        self._fit_to_content()

    def _fit_to_content(self) -> None:
        try:
            self._window.update_idletasks()
        except Exception:
            return
        w = int(self._window.winfo_width() or self._window.winfo_reqwidth() or 720)
        h = int(self._window.winfo_reqheight() or self._window.winfo_height() or 280)
        self._window.geometry(f"{w}x{h}")
        try:
            self._window.minsize(560, h)
        except Exception:
            pass


def _lookup_nested(info: dict, path: Iterable[str]) -> Any:
    cur: Any = info
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur.get(key)
    return cur


def _format_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _format_study_date(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, dt.datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, dt.date):
        return dt.datetime.combine(value, dt.time.min).strftime("%Y-%m-%d %H:%M")
    text = str(value).strip()
    for fmt in (
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d",
        "%Y%m%d%H%M",
        "%Y%m%d%H%M%S",
        "%Y%m%d",
    ):
        try:
            parsed = dt.datetime.strptime(text, fmt)
            return parsed.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue
    try:
        parsed = dt.datetime.fromisoformat(text)
        return parsed.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return text


def _center_window(win: tk.Toplevel, parent: tk.Misc) -> None:
    try:
        win.update_idletasks()
    except Exception:
        return
    try:
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
    except Exception:
        return
    try:
        ww = win.winfo_reqwidth()
        wh = win.winfo_reqheight()
    except Exception:
        return
    x = px + max(int((pw - ww) / 2), 0)
    y = py + max(int((ph - wh) / 2), 0)
    try:
        win.geometry(f"+{x}+{y}")
    except Exception:
        pass
