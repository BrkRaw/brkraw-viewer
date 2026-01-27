from __future__ import annotations

import queue
import tkinter as tk
from tkinter import ttk, filedialog
import logging


class WorkerLogWindow(tk.Toplevel):
    def __init__(self, parent: tk.Misc, log_queue) -> None:
        super().__init__(parent)
        self.title("Worker Log")
        self.geometry("700x420")
        self.log_queue = log_queue

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        frame = ttk.Frame(self, padding=10)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        self.text = tk.Text(frame, wrap="word", state="disabled")
        self.text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.text.configure(yscrollcommand=scroll.set)

        actions = ttk.Frame(frame)
        actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        actions.columnconfigure(0, weight=1)

        ttk.Button(actions, text="Clear", command=self._clear).grid(row=0, column=0, sticky="w")
        ttk.Button(actions, text="Save", command=self._save).grid(row=0, column=1, sticky="e")

        self._polling = True
        self._poll_logs()

    def _poll_logs(self) -> None:
        if not self._polling:
            return
        try:
            while True:
                record = self.log_queue.get_nowait()
                msg = self._format_record(record)
                self.append_text(msg)
        except queue.Empty:
            pass
        self.after(100, self._poll_logs)

    @staticmethod
    def _format_record(record: logging.LogRecord) -> str:
        return f"[{record.levelname}] {record.getMessage()}\n"

    def append_text(self, text: str) -> None:
        self.text.configure(state="normal")
        self.text.insert("end", text)
        self.text.see("end")
        self.text.configure(state="disabled")

    def _clear(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", tk.END)
        self.text.configure(state="disabled")

    def _save(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Save worker log",
            defaultextension=".txt",
            filetypes=(("Text", "*.txt"), ("All files", "*.*")),
        )
        if not path:
            return
        content = self.text.get("1.0", tk.END)
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(content)
        except Exception:
            return
