from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from ..sharedtypes import Command


class SubjectBar(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        *,
        study_id_var: tk.StringVar,
        subject_id_var: tk.StringVar,
        study_date_var: tk.StringVar,
        on_open_study_info: Command,
    ) -> None:
        super().__init__(master, padding=(10, 0, 10, 8))

        ttk.Label(
            self, 
            text="Study ID"
        ).pack(side="left")
        ttk.Entry(
            self, 
            textvariable=study_id_var, 
            width=14, 
            state="readonly"
        ).pack(side="left", padx=(6, 12))

        ttk.Label(
            self, 
            text="Subject ID"
        ).pack(side="left")
        ttk.Entry(
            self, 
            textvariable=subject_id_var, 
            width=14, 
            state="readonly"
        ).pack(side="left", padx=(6, 12))

        ttk.Label(
            self, 
            text="Study Date"
        ).pack(side="left")
        ttk.Entry(
            self, 
            textvariable=study_date_var, 
            width=18, 
            state="readonly"
        ).pack(side="left", padx=(6, 0))

        ttk.Button(
            self, 
            text="Study Info", 
            command=on_open_study_info
        ).pack(side="right")