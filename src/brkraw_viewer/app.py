from __future__ import annotations

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Any, Dict, Iterable, Optional, Tuple, cast
import datetime as dt
from pathlib import Path

import numpy as np

from brkraw.apps.loader import BrukerLoader
from brkraw.apps.loader.types import StudyLoader
from brkraw.resolver import affine as affine_resolver
from brkraw.resolver.affine import SubjectPose, SubjectType
from brkraw.apps.loader import info as info_resolver
from brkraw.core.config import resolve_root
from brkraw.specs.rules import load_rules, select_rule_use
from .orientation import reorient_to_ras
from .viewer_canvas import OrthogonalCanvas
from .timecourse_canvas import TimecourseCanvas
from .params_panel import ParamsPanel

ScanLike = Any

WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 760


class ViewerApp(tk.Tk):
    def __init__(
        self,
        *,
        path: Optional[str],
        scan_id: Optional[int],
        reco_id: Optional[int],
        info_spec: Optional[str],
        axis: str,
        slice_index: Optional[int],
    ) -> None:
        super().__init__()
        self.title("BrkRaw Viewer")
        self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.minsize(980, 640)

        self._loader: Optional[BrukerLoader] = None
        self._study: Optional[StudyLoader] = None
        self._scan: Optional[ScanLike] = None
        self._scan_ids: list[int] = []
        self._scan_info_cache: Dict[int, Dict[str, Any]] = {}
        self._info_full: Dict[str, Any] = {}
        self._info_spec = info_spec

        self._data: Optional[np.ndarray] = None
        self._affine: Optional[np.ndarray] = None
        self._res: Optional[np.ndarray] = None
        self._qc_message: Optional[str] = None
        self._slice_hint: Optional[int] = slice_index
        self._slice_hint_axis = axis
        self._frame_index = 0
        self._current_reco_id: Optional[int] = None
        self._tripilot_data: Optional[Tuple[np.ndarray, ...]] = None
        self._tripilot_views: Optional[Dict[str, Tuple[np.ndarray, Tuple[float, float]]]] = None
        self._current_subject_type: Optional[str] = None
        self._current_subject_pose: Optional[str] = None
        self._user_pose_override = False
        self._view_error: Optional[str] = None
        self._roi_points: list[Dict[str, Any]] = []
        self._roi_colors = ["#ff6b6b", "#4ecdc4", "#ffd166", "#c7f464", "#8ecae6", "#c77dff"]
        self._roi_index = 0
        self._extra_dim_vars: list[tk.IntVar] = []
        self._extra_dim_scales: list[tk.Scale] = []

        self._path_var = tk.StringVar(value=path or "")
        self._x_var = tk.IntVar(value=0)
        self._y_var = tk.IntVar(value=0)
        self._z_var = tk.IntVar(value=0)
        self._frame_var = tk.IntVar(value=0)
        self._status_var = tk.StringVar(value="Ready")

        self._subject_type_var = tk.StringVar(value="Default")
        self._pose_primary_var = tk.StringVar(value="Default")
        self._pose_secondary_var = tk.StringVar(value="Default")
        self._rule_text_var = tk.StringVar(value="Rule: auto")
        self._rule_enabled_var = tk.BooleanVar(value=True)
        self._rule_override_var = tk.BooleanVar(value=False)
        self._rule_override_path = tk.StringVar(value="")

        self._layout_enabled_var = tk.BooleanVar(value=False)
        self._layout_template_var = tk.StringVar(value="")
        self._slicepack_suffix_var = tk.StringVar(value="")
        self._output_dir_var = tk.StringVar(value="output")

        self._init_ui()

        if path:
            self._load_path(path, scan_id=scan_id, reco_id=reco_id)
        else:
            self._status_var.set("Open a study folder or zip to begin.")

    def _init_ui(self) -> None:
        top = ttk.Frame(self, padding=(10, 10, 10, 6))
        top.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(top, text="Open File", command=self._choose_file).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(top, text="Open Directory", command=self._choose_dir).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(top, text="Refresh", command=self._refresh).pack(side=tk.LEFT)

        ttk.Label(top, text="Path:").pack(side=tk.LEFT, padx=(12, 6))
        path_entry = ttk.Entry(top, textvariable=self._path_var, width=70)
        path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        path_entry.configure(state="readonly")

        subject_frame = ttk.LabelFrame(self, text="Subject Info", padding=(10, 8))
        subject_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(0, 8))

        self._subject_fields = [
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
        self._subject_entries: Dict[str, ttk.Entry] = {}
        for idx, (label, _) in enumerate(self._subject_fields):
            row = idx // 4
            col = (idx % 4) * 2
            ttk.Label(subject_frame, text=label).grid(row=row, column=col, sticky="w", padx=6, pady=3)
            entry = ttk.Entry(subject_frame, width=18)
            entry.grid(row=row, column=col + 1, sticky="w", padx=(0, 6), pady=3)
            entry.configure(state="readonly")
            self._subject_entries[label] = entry

        body = ttk.Frame(self, padding=(10, 4, 10, 10))
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        body.columnconfigure(0, weight=0)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        list_frame = ttk.Frame(body)
        list_frame.grid(row=0, column=0, sticky="ns")

        ttk.Label(list_frame, text="Scans").pack(anchor=tk.W, pady=(0, 4))
        self._scan_listbox = tk.Listbox(list_frame, width=30, height=18, exportselection=False)
        self._scan_listbox.pack(fill=tk.BOTH, expand=False)
        self._scan_listbox.bind("<<ListboxSelect>>", self._on_scan_select)
        self._scan_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self._scan_listbox.yview)
        self._scan_listbox.configure(yscrollcommand=self._scan_scroll.set)
        self._scan_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        ttk.Label(list_frame, text="Recos").pack(anchor=tk.W, pady=(12, 4))
        self._reco_listbox = tk.Listbox(list_frame, width=30, height=6, exportselection=False)
        self._reco_listbox.pack(fill=tk.BOTH, expand=False)
        self._reco_listbox.bind("<<ListboxSelect>>", self._on_reco_select)
        self._reco_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self._reco_listbox.yview)
        self._reco_listbox.configure(yscrollcommand=self._reco_scroll.set)
        self._reco_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        right_frame = ttk.Frame(body)
        right_frame.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        right_frame.columnconfigure(0, weight=1)
        right_frame.rowconfigure(0, weight=1)

        notebook = ttk.Notebook(right_frame)
        notebook.grid(row=0, column=0, sticky="nsew")

        viewer_tab = ttk.Frame(notebook)
        info_tab = ttk.Frame(notebook)
        layout_tab = ttk.Frame(notebook)
        time_tab = ttk.Frame(notebook)
        params_tab = ttk.Frame(notebook)
        notebook.add(viewer_tab, text="Viewer")
        notebook.add(info_tab, text="Info")
        notebook.add(layout_tab, text="Layout")
        notebook.add(time_tab, text="Timecourse")
        notebook.add(params_tab, text="Params")

        viewer_tab.columnconfigure(0, weight=1)
        viewer_tab.rowconfigure(0, weight=1)

        preview_frame = ttk.LabelFrame(viewer_tab, text="Preview", padding=(6, 6))
        preview_frame.grid(row=0, column=0, sticky="nsew")
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(2, weight=1)
        preview_frame.rowconfigure(3, weight=0)

        control_bar = ttk.Frame(preview_frame)
        control_bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        ttk.Label(control_bar, text="X").pack(side=tk.LEFT, padx=(0, 4))
        self._x_scale = tk.Scale(
            control_bar,
            from_=0,
            to=0,
            orient=tk.HORIZONTAL,
            showvalue=True,
            command=self._on_x_change,
            length=140,
        )
        self._x_scale.pack(side=tk.LEFT)

        ttk.Label(control_bar, text="Y").pack(side=tk.LEFT, padx=(6, 4))
        self._y_scale = tk.Scale(
            control_bar,
            from_=0,
            to=0,
            orient=tk.HORIZONTAL,
            showvalue=True,
            command=self._on_y_change,
            length=140,
        )
        self._y_scale.pack(side=tk.LEFT)

        ttk.Label(control_bar, text="Z").pack(side=tk.LEFT, padx=(6, 4))
        self._z_scale = tk.Scale(
            control_bar,
            from_=0,
            to=0,
            orient=tk.HORIZONTAL,
            showvalue=True,
            command=self._on_z_change,
            length=140,
        )
        self._z_scale.pack(side=tk.LEFT)

        ttk.Label(control_bar, text="Frame").pack(side=tk.LEFT, padx=(10, 4))
        self._frame_scale = tk.Scale(
            control_bar,
            from_=0,
            to=0,
            orient=tk.HORIZONTAL,
            showvalue=True,
            command=self._on_frame_change,
            length=160,
        )
        self._frame_scale.pack(side=tk.LEFT)

        self._extra_frame = ttk.Frame(preview_frame)
        self._extra_frame.grid(row=3, column=0, sticky="ew", pady=(4, 0))

        orient_bar = ttk.Frame(preview_frame)
        orient_bar.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(orient_bar, text="Subject Type").pack(side=tk.LEFT, padx=(0, 4))
        self._subject_type_combo = ttk.Combobox(
            orient_bar,
            textvariable=self._subject_type_var,
            state="readonly",
            values=("Default", "Biped", "Quadruped", "Phantom", "Other", "OtherAnimal"),
            width=12,
        )
        self._subject_type_combo.pack(side=tk.LEFT)

        ttk.Label(orient_bar, text="Pose").pack(side=tk.LEFT, padx=(10, 4))
        self._pose_primary_combo = ttk.Combobox(
            orient_bar,
            textvariable=self._pose_primary_var,
            state="readonly",
            values=("Default", "Head", "Foot"),
            width=8,
        )
        self._pose_primary_combo.pack(side=tk.LEFT)
        self._pose_secondary_combo = ttk.Combobox(
            orient_bar,
            textvariable=self._pose_secondary_var,
            state="readonly",
            values=("Default", "Supine", "Prone", "Left", "Right"),
            width=8,
        )
        self._pose_secondary_combo.pack(side=tk.LEFT, padx=(4, 0))

        ttk.Button(orient_bar, text="Apply", command=self._apply_orientation_override).pack(
            side=tk.LEFT,
            padx=(10, 0),
        )

        self._viewer = OrthogonalCanvas(preview_frame)
        self._viewer.grid(row=2, column=0, sticky="nsew")
        self._viewer.set_click_callback(self._on_view_click)

        info_tab.columnconfigure(0, weight=1)
        info_tab.rowconfigure(0, weight=1)

        info_frame = ttk.LabelFrame(info_tab, text="Scan Info", padding=(6, 6))
        info_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 0))
        info_frame.columnconfigure(0, weight=1)
        info_frame.rowconfigure(1, weight=1)

        rule_bar = ttk.Frame(info_frame)
        rule_bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        rule_bar.columnconfigure(2, weight=1)

        ttk.Checkbutton(
            rule_bar,
            text="Use rule",
            variable=self._rule_enabled_var,
            command=self._on_rule_toggle,
        ).grid(row=0, column=0, sticky="w")

        ttk.Label(rule_bar, textvariable=self._rule_text_var).grid(row=0, column=1, sticky="w", padx=(8, 0))

        ttk.Checkbutton(
            rule_bar,
            text="Override spec",
            variable=self._rule_override_var,
            command=self._on_rule_toggle,
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        override_entry = ttk.Entry(rule_bar, textvariable=self._rule_override_path)
        override_entry.grid(row=1, column=1, sticky="ew", padx=(8, 4), pady=(4, 0))
        ttk.Button(rule_bar, text="Browse", command=self._browse_rule_override).grid(
            row=1,
            column=2,
            sticky="e",
            pady=(4, 0),
        )

        self._scan_info_text = tk.Text(info_frame, width=40, height=10, wrap="word")
        self._scan_info_text.grid(row=1, column=0, sticky="ew")
        self._scan_info_text.configure(state=tk.DISABLED)

        layout_tab.columnconfigure(0, weight=1)
        layout_tab.rowconfigure(0, weight=1)

        layout_frame = ttk.LabelFrame(layout_tab, text="Layout / Convert", padding=(6, 6))
        layout_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 0))
        layout_frame.columnconfigure(1, weight=1)

        ttk.Checkbutton(
            layout_frame,
            text="Use custom layout",
            variable=self._layout_enabled_var,
        ).grid(row=0, column=0, sticky="w")

        ttk.Label(layout_frame, text="Template").grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(layout_frame, textvariable=self._layout_template_var).grid(row=1, column=1, sticky="ew", pady=(4, 0))

        ttk.Label(layout_frame, text="Slicepack suffix").grid(row=2, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(layout_frame, textvariable=self._slicepack_suffix_var).grid(row=2, column=1, sticky="ew", pady=(4, 0))

        ttk.Label(layout_frame, text="Output dir").grid(row=3, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(layout_frame, textvariable=self._output_dir_var).grid(row=3, column=1, sticky="ew", pady=(4, 0))
        ttk.Button(layout_frame, text="Browse", command=self._browse_output_dir).grid(row=3, column=2, padx=(6, 0), pady=(4, 0))

        ttk.Button(layout_frame, text="Convert", command=self._convert_current_scan).grid(row=4, column=0, columnspan=3, sticky="ew", pady=(6, 0))

        time_tab.columnconfigure(0, weight=1)
        time_tab.rowconfigure(1, weight=1)

        time_toolbar = ttk.Frame(time_tab)
        time_toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Button(time_toolbar, text="Clear Points", command=self._clear_points).pack(side=tk.LEFT)
        ttk.Button(time_toolbar, text="Remove Last", command=self._remove_last_point).pack(side=tk.LEFT, padx=(6, 0))

        self._time_canvas = TimecourseCanvas(time_tab)
        self._time_canvas.grid(row=1, column=0, sticky="nsew")

        params_tab.columnconfigure(0, weight=1)
        params_tab.rowconfigure(0, weight=1)
        self._params_panel = ParamsPanel(params_tab)
        self._params_panel.grid(row=0, column=0, sticky="nsew")

        status = ttk.Label(
            self,
            textvariable=self._status_var,
            relief=tk.SUNKEN,
            anchor=tk.W,
            padding=(8, 4),
        )
        status.pack(side=tk.BOTTOM, fill=tk.X)

    def _choose_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Select Bruker dataset zip",
            filetypes=(
                ("Zip compressed", "*.zip"),
                ("All files", "*.*"),
            ),
        )
        if not path:
            return
        self._path_var.set(path)
        self._load_path(path, scan_id=None, reco_id=None)

    def _choose_dir(self) -> None:
        path = filedialog.askdirectory(title="Select Bruker study folder")
        if not path:
            return
        self._path_var.set(path)
        self._load_path(path, scan_id=None, reco_id=None)

    def _refresh(self) -> None:
        path = self._path_var.get()
        if not path:
            return
        self._load_path(path, scan_id=None, reco_id=None)

    def _load_path(
        self,
        path: str,
        *,
        scan_id: Optional[int],
        reco_id: Optional[int],
    ) -> None:
        try:
            self._loader = BrukerLoader(path)
            self._study = cast(StudyLoader, self._loader._study)
        except Exception as exc:
            messagebox.showerror("Load error", f"Failed to load dataset:\n{exc}")
            self._status_var.set("Failed to load dataset.")
            return

        self._scan_info_cache.clear()
        self._info_full = self._resolve_info_bundle()
        self._scan_ids = list(self._study.avail.keys()) if self._study else []
        if not self._scan_ids:
            self._status_var.set("No scans found.")
            return

        self._update_subject_info()
        self._populate_scan_list()

        target_scan = scan_id if scan_id in self._scan_ids else self._scan_ids[0]
        self._select_scan(target_scan)
        if reco_id is not None:
            self._select_reco(reco_id)

    def _populate_scan_list(self) -> None:
        if self._study is None:
            return
        self._scan_listbox.delete(0, tk.END)
        scan_info_all = self._info_full.get("Scan(s)", {}) if self._info_full else {}
        if not isinstance(scan_info_all, dict):
            scan_info_all = {}
        scan_info_all = cast(Dict[int, Any], scan_info_all)
        for scan_id in self._scan_ids:
            scan = self._study.avail.get(scan_id)
            info = scan_info_all.get(scan_id) or self._resolve_scan_info(scan_id, scan)
            protocol = self._format_value(info.get("Protocol", "N/A"))
            self._scan_listbox.insert(tk.END, f"{scan_id:03d} :: {protocol}")

    def _select_scan(self, scan_id: int) -> None:
        if scan_id not in self._scan_ids:
            return
        idx = self._scan_ids.index(scan_id)
        self._scan_listbox.selection_clear(0, tk.END)
        self._scan_listbox.selection_set(idx)
        self._scan_listbox.activate(idx)
        self._on_scan_select()

    def _select_reco(self, reco_id: int) -> None:
        reco_ids = self._current_reco_ids()
        if reco_id not in reco_ids:
            return
        idx = reco_ids.index(reco_id)
        self._reco_listbox.selection_clear(0, tk.END)
        self._reco_listbox.selection_set(idx)
        self._reco_listbox.activate(idx)
        self._on_reco_select()

    def _current_reco_ids(self) -> list[int]:
        if self._scan is None:
            return []
        return list(self._scan.avail.keys())

    def _on_scan_select(self, *_: object) -> None:
        selection = self._scan_listbox.curselection()
        if not selection:
            return
        scan_id = self._scan_ids[int(selection[0])]
        if self._study is None:
            return
        self._scan = self._study.avail.get(scan_id)
        self._populate_reco_list(scan_id)
        reco_ids = self._current_reco_ids()
        if reco_ids:
            self._select_reco(reco_ids[0])
        else:
            self._status_var.set(f"Scan {scan_id} has no reco data.")

    def _populate_reco_list(self, scan_id: int) -> None:
        if self._study is None:
            return
        self._reco_listbox.delete(0, tk.END)
        scan = self._study.avail.get(scan_id)
        scan_info_all = self._info_full.get("Scan(s)", {}) if self._info_full else {}
        if not isinstance(scan_info_all, dict):
            scan_info_all = {}
        scan_info_all = cast(Dict[int, Any], scan_info_all)
        info = scan_info_all.get(scan_id) or self._resolve_scan_info(scan_id, scan)
        recos = info.get("Reco(s)", {})
        for reco_id in self._current_reco_ids():
            label = self._format_value(recos.get(reco_id, {}).get("Type", "N/A"))
            self._reco_listbox.insert(tk.END, f"{reco_id:03d} :: {label}")

    def _on_reco_select(self, *_: object) -> None:
        selection = self._reco_listbox.curselection()
        if not selection or self._scan is None:
            return
        reco_ids = self._current_reco_ids()
        if not reco_ids:
            return
        reco_id = reco_ids[int(selection[0])]
        self._current_reco_id = reco_id
        self._load_data(reco_id=reco_id)
        self._update_params_panel(reco_id=reco_id)

        scan_id = getattr(self._scan, "scan_id", None)
        scan_info_all = self._info_full.get("Scan(s)", {}) if self._info_full else {}
        if not isinstance(scan_info_all, dict):
            scan_info_all = {}
        scan_info_all = cast(Dict[int, Any], scan_info_all)
        info = scan_info_all.get(scan_id) if scan_id is not None else {}
        if not info and scan_id is not None:
            info = self._resolve_scan_info(scan_id, self._scan)
        if not isinstance(info, dict):
            info = {}
        if not info and not self._rule_enabled_var.get():
            self._set_view_error("Rule disabled: scan info unavailable.")
        self._update_scan_info(cast(Dict[str, Any], info), reco_id)

    def _on_x_change(self, value: str) -> None:
        try:
            self._x_var.set(int(float(value)))
        except ValueError:
            return
        self._update_plot()

    def _on_y_change(self, value: str) -> None:
        try:
            self._y_var.set(int(float(value)))
        except ValueError:
            return
        self._update_plot()

    def _on_z_change(self, value: str) -> None:
        try:
            self._z_var.set(int(float(value)))
        except ValueError:
            return
        self._update_plot()

    def _on_frame_change(self, value: str) -> None:
        try:
            self._frame_var.set(int(float(value)))
        except ValueError:
            return
        self._update_plot()

    def _on_extra_dim_change(self, *_: object) -> None:
        self._update_plot()

    def _on_rule_toggle(self) -> None:
        if self._current_reco_id is None:
            return
        self._view_error = None
        self._scan_info_cache.clear()
        if self._scan is not None and self._current_reco_id is not None:
            scan_id = getattr(self._scan, "scan_id", None)
            if scan_id is not None:
                info = self._resolve_scan_info(scan_id, self._scan)
                self._update_scan_info(info, self._current_reco_id)
                if not info and not self._rule_enabled_var.get():
                    self._set_view_error("Rule disabled: scan info unavailable.")

    def _browse_rule_override(self) -> None:
        path = filedialog.askopenfilename(
            title="Select info spec YAML",
            filetypes=(("YAML", "*.yaml *.yml"), ("All files", "*.*")),
        )
        if not path:
            return
        self._rule_override_path.set(path)
        self._rule_override_var.set(True)
        self._on_rule_toggle()

    def _set_view_error(self, message: str) -> None:
        self._view_error = message
        self._status_var.set(message)
        self._viewer.clear_markers()
        self._time_canvas.clear()
        self._update_plot()

    def _on_view_click(self, view: str, row: int, col: int) -> None:
        if self._data is None:
            return
        if self._tripilot_views is not None:
            return
        x_idx = int(self._x_var.get())
        y_idx = int(self._y_var.get())
        z_idx = int(self._z_var.get())
        if view == "zy":
            x = x_idx
            y = row
            z = col
        elif view == "xy":
            x = col
            y = row
            z = z_idx
        else:
            x = col
            y = y_idx
            z = row

        shape = self._data.shape
        if x < 0 or y < 0 or z < 0 or x >= shape[0] or y >= shape[1] or z >= shape[2]:
            return

        color = self._roi_colors[self._roi_index % len(self._roi_colors)]
        self._roi_index += 1
        point = {"x": x, "y": y, "z": z, "view": view, "row": row, "col": col, "color": color}
        self._roi_points.append(point)
        self._viewer.add_marker(view, row, col, color)
        self._update_timecourse_plot()

    def _clear_points(self) -> None:
        self._roi_points = []
        self._roi_index = 0
        self._viewer.clear_markers()
        self._update_timecourse_plot()

    def _remove_last_point(self) -> None:
        if not self._roi_points:
            return
        self._roi_points.pop()
        self._viewer.clear_markers()
        self._render_markers()
        self._update_timecourse_plot()

    def _render_markers(self) -> None:
        for point in self._roi_points:
            self._viewer.add_marker(point["view"], point["row"], point["col"], point["color"])

    def _update_timecourse_plot(self) -> None:
        if self._data is None or not self._roi_points:
            self._time_canvas.clear()
            return
        series_list = []
        for idx, point in enumerate(self._roi_points):
            x = point["x"]
            y = point["y"]
            z = point["z"]
            color = point["color"]
            label = f"P{idx + 1} ({x},{y},{z})"
            if self._data.ndim >= 4:
                values = self._data[x, y, z, :].astype(float).tolist()
            else:
                values = [float(self._data[x, y, z])]
            series_list.append((values, color, label))
        self._time_canvas.set_series(series_list, title="Timecourse (frame axis)")

    def _update_params_panel(self, *, reco_id: int) -> None:
        if self._scan is None:
            self._params_panel.clear()
            return
        params_data: Dict[str, Dict[str, Any]] = {}

        def _to_dict(obj: Any) -> Optional[Dict[str, Any]]:
            if obj is None:
                return None
            getter = getattr(obj, "get", None)
            if callable(getter):
                try:
                    return dict(obj)
                except Exception:
                    return None
            return None

        for name in ("method", "acqp"):
            params = getattr(self._scan, name, None)
            if params is None:
                continue
            data = _to_dict(params)
            if data:
                params_data[name] = data

        try:
            reco = self._scan.avail.get(reco_id)
        except Exception:
            reco = None
        if reco is not None:
            for name in ("visu_pars", "reco"):
                params = getattr(reco, name, None)
                data = _to_dict(params)
                if data:
                    params_data[name] = data

        if params_data:
            self._params_panel.set_params(params_data)
        else:
            self._params_panel.clear()

    def _browse_output_dir(self) -> None:
        path = filedialog.askdirectory(title="Select output directory")
        if not path:
            return
        self._output_dir_var.set(path)

    def _convert_current_scan(self) -> None:
        if self._loader is None or self._scan is None or self._current_reco_id is None:
            self._status_var.set("No scan selected.")
            return
        scan_id = getattr(self._scan, "scan_id", None)
        if scan_id is None:
            self._status_var.set("Scan id unavailable.")
            return

        output_dir = self._output_dir_var.get().strip() or "output"
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        layout_template = None
        slicepack_suffix = None
        if self._layout_enabled_var.get():
            layout_template = self._layout_template_var.get().strip() or None
            slicepack_suffix = self._slicepack_suffix_var.get().strip() or None

        try:
            nii = self._loader.convert(
                scan_id,
                reco_id=self._current_reco_id,
                format="nifti",
                hook_args_by_name=None,
            )
        except Exception as exc:
            messagebox.showerror("Convert error", f"Failed to convert scan:\n{exc}")
            self._status_var.set("Conversion failed.")
            return

        if nii is None:
            self._status_var.set("No NIfTI output generated.")
            return
        nii_list = list(nii) if isinstance(nii, tuple) else [nii]

        if layout_template:
            base_name = layout_template
        else:
            base_name = f"scan-{scan_id}"
            if self._current_reco_id is not None:
                base_name = f"{base_name}_reco-{self._current_reco_id}"

        for idx, img in enumerate(nii_list):
            suffix = ""
            if len(nii_list) > 1:
                if slicepack_suffix:
                    suffix = slicepack_suffix.format(index=idx)
                else:
                    suffix = f"_slpack{idx}"
            filename = f"{base_name}{suffix}.nii.gz"
            dest = output_path / filename
            try:
                img.to_filename(str(dest))
            except Exception as exc:
                messagebox.showerror("Save error", f"Failed to save NIfTI:\n{exc}")
                self._status_var.set("Save failed.")
                return
        self._status_var.set(f"Saved {len(nii_list)} file(s) to {output_path}")

    def _update_subject_info(self) -> None:
        info = self._info_full or {}
        for label, paths in self._subject_fields:
            value = None
            for path in paths:
                value = self._lookup_nested(info, path)
                if value not in (None, ""):
                    break
            entry = self._subject_entries[label]
            entry.configure(state="normal")
            entry.delete(0, tk.END)
            entry.insert(0, self._format_value(value) if value is not None else "")
            entry.configure(state="readonly")

    def _resolve_scan_info(
        self,
        scan_id: Optional[int],
        scan: Optional[ScanLike],
    ) -> Dict[str, Any]:
        if scan_id is None or scan is None:
            return {}
        if scan_id in self._scan_info_cache:
            return self._scan_info_cache[scan_id]
        try:
            spec_path = self._select_info_spec_path(scan)
            if spec_path:
                info = info_resolver.scan(cast(Any, scan), spec_source=spec_path)
            else:
                info = info_resolver.scan(cast(Any, scan))
        except Exception:
            info = {}
        self._scan_info_cache[scan_id] = info
        return info

    def _select_info_spec_path(self, scan: ScanLike) -> Optional[str]:
        if not self._rule_enabled_var.get():
            self._rule_text_var.set("Rule: disabled")
            return None
        if self._rule_override_var.get():
            override_path = self._rule_override_path.get().strip()
            if override_path:
                if not Path(override_path).exists():
                    self._rule_text_var.set("Rule: override (missing)")
                    self._set_view_error("Override spec not found.")
                    return None
                self._rule_text_var.set(f"Rule: override ({override_path})")
                return override_path
        if self._info_spec:
            self._rule_text_var.set(f"Rule: fixed ({self._info_spec})")
            return self._info_spec
        try:
            rules = load_rules(root=resolve_root(None), validate=False)
            spec_path = select_rule_use(
                scan,
                rules.get("info_spec", []),
                base=resolve_root(None),
                resolve_paths=True,
            )
        except Exception:
            spec_path = None
        if spec_path:
            self._rule_text_var.set(f"Rule: auto ({spec_path})")
            return str(spec_path)
        self._rule_text_var.set("Rule: auto (default)")
        return None

    def _update_scan_info(self, info: Dict[str, Any], reco_id: int) -> None:
        lines = []
        if info:
            lines.append(f"Protocol: {self._format_value(info.get('Protocol'))}")
            lines.append(f"Method: {self._format_value(info.get('Method'))}")
            lines.append(f"TR (ms): {self._format_value(info.get('TR (ms)'))}")
            lines.append(f"TE (ms): {self._format_value(info.get('TE (ms)'))}")
            lines.append(f"FlipAngle (degree): {self._format_value(info.get('FlipAngle (degree)'))}")
            lines.append(f"Dim: {self._format_value(info.get('Dim'))}")
            lines.append(f"Shape: {self._format_value(info.get('Shape'))}")
            lines.append(f"FOV (mm): {self._format_value(info.get('FOV (mm)'))}")
            lines.append(f"NumSlicePack: {self._format_value(info.get('NumSlicePack'))}")
            lines.append(f"SliceOrient: {self._format_value(info.get('SliceOrient'))}")
            lines.append(f"ReadOrient: {self._format_value(info.get('ReadOrient'))}")
            lines.append(f"SliceGap (mm): {self._format_value(info.get('SliceGap (mm)'))}")
            lines.append(f"SliceDistance (mm): {self._format_value(info.get('SliceDistance (mm)'))}")
            lines.append(f"NumAverage: {self._format_value(info.get('NumAverage'))}")
            lines.append(f"NumRepeat: {self._format_value(info.get('NumRepeat'))}")

            reco_type = info.get("Reco(s)", {}).get(reco_id, {}).get("Type")
            lines.append(f"Reco Type: {self._format_value(reco_type)}")

        if self._data is not None and self._affine is not None:
            res = self._res if self._res is not None else np.diag(self._affine)[:3]
            lines.append("")
            lines.append(f"RAS Shape: {self._data.shape}")
            lines.append(f"RAS Resolution: {self._format_value(np.round(res, 4))}")
            if self._qc_message:
                lines.append(self._qc_message)

        text = "\n".join([line for line in lines if line and line != "None"])
        self._scan_info_text.configure(state=tk.NORMAL)
        self._scan_info_text.delete("1.0", tk.END)
        self._scan_info_text.insert(tk.END, text)
        self._scan_info_text.configure(state=tk.DISABLED)

    def _apply_orientation_override(self) -> None:
        if self._scan is None or self._current_reco_id is None:
            return
        self._user_pose_override = True
        self._load_data(reco_id=self._current_reco_id)

    def _resolve_scanner_affine(self, *, reco_id: int) -> Optional[Any]:
        if self._scan is None:
            return None
        raw_affine = self._scan.get_affine(
            reco_id=reco_id,
            space="raw",
            override_subject_type=None,
            override_subject_pose=None,
        )
        if raw_affine is None:
            return None
        affines = list(raw_affine) if isinstance(raw_affine, tuple) else [raw_affine]

        try:
            reco = self._scan.avail.get(reco_id)
            visu_pars = getattr(reco, "visu_pars", None) if reco else None
            subj_type, subj_pose = affine_resolver.get_subject_type_and_position(visu_pars) if visu_pars else (None, "Head_Supine")
        except Exception:
            subj_type, subj_pose = None, "Head_Supine"

        override_type = self._get_subject_type_override()
        override_pose = self._get_subject_pose_override()
        use_type = self._cast_subject_type(override_type or subj_type)
        use_pose = self._cast_subject_pose(override_pose or subj_pose)

        self._current_subject_type = subj_type
        self._current_subject_pose = subj_pose
        if not self._user_pose_override:
            self._sync_subject_pose_defaults(subj_type, subj_pose)

        affines_scanner = [
            affine_resolver.unwrap_to_scanner_xyz(np.asarray(aff), use_type, use_pose)
            for aff in affines
        ]
        if isinstance(raw_affine, tuple):
            return tuple(affines_scanner)
        return affines_scanner[0]

    def _get_subject_type_override(self) -> Optional[str]:
        value = (self._subject_type_var.get() or "").strip()
        if not value or value == "Default":
            return None
        return value

    def _get_subject_pose_override(self) -> Optional[str]:
        primary = (self._pose_primary_var.get() or "").strip()
        secondary = (self._pose_secondary_var.get() or "").strip()
        if not primary or not secondary:
            return None
        if primary == "Default" or secondary == "Default":
            return None
        return f"{primary}_{secondary}"

    def _sync_subject_pose_defaults(self, subj_type: Optional[str], subj_pose: Optional[str]) -> None:
        if subj_type:
            self._subject_type_var.set(subj_type)
        else:
            self._subject_type_var.set("Default")
        if subj_pose and "_" in subj_pose:
            primary, secondary = subj_pose.split("_", 1)
            self._pose_primary_var.set(primary)
            self._pose_secondary_var.set(secondary)
        else:
            self._pose_primary_var.set("Default")
            self._pose_secondary_var.set("Default")

    @staticmethod
    def _cast_subject_type(value: Optional[str]) -> Optional[SubjectType]:
        allowed = {"Biped", "Quadruped", "Phantom", "Other", "OtherAnimal"}
        if value in allowed:
            return cast(SubjectType, value)
        return None

    @staticmethod
    def _cast_subject_pose(value: Optional[str]) -> SubjectPose:
        allowed = {
            "Head_Supine",
            "Head_Prone",
            "Head_Left",
            "Head_Right",
            "Foot_Supine",
            "Foot_Prone",
            "Foot_Left",
            "Foot_Right",
        }
        if value in allowed:
            return cast(SubjectPose, value)
        return cast(SubjectPose, "Head_Supine")

    def _clear_extra_dims(self) -> None:
        for widget in self._extra_frame.winfo_children():
            widget.destroy()
        self._extra_dim_vars = []
        self._extra_dim_scales = []

    def _update_extra_dims(self) -> None:
        if self._data is None:
            self._clear_extra_dims()
            return
        extra_dims = self._data.shape[4:] if self._data.ndim > 4 else ()
        if len(extra_dims) == len(self._extra_dim_scales):
            for idx, size in enumerate(extra_dims):
                self._extra_dim_scales[idx].configure(from_=0, to=max(size - 1, 0))
            return

        self._clear_extra_dims()
        for idx, size in enumerate(extra_dims):
            label = ttk.Label(self._extra_frame, text=f"Dim {idx + 5}")
            label.pack(side=tk.LEFT, padx=(0, 4))
            var = tk.IntVar(value=0)
            scale = tk.Scale(
                self._extra_frame,
                from_=0,
                to=max(size - 1, 0),
                orient=tk.HORIZONTAL,
                showvalue=True,
                command=lambda _: self._on_extra_dim_change(),
                length=140,
            )
            scale.pack(side=tk.LEFT, padx=(0, 8))
            self._extra_dim_vars.append(var)
            self._extra_dim_scales.append(scale)
            scale.configure(variable=var)

    def _load_data(self, *, reco_id: int) -> None:
        if self._scan is None:
            return
        try:
            dataobj = self._scan.get_dataobj(reco_id=reco_id)
            affine = self._resolve_scanner_affine(reco_id=reco_id)
        except Exception as exc:
            messagebox.showerror("Load error", f"Failed to load data:\n{exc}")
            self._status_var.set("Failed to load scan data.")
            return

        if dataobj is None or affine is None:
            self._status_var.set("Scan data unavailable for this reco.")
            return

        self._tripilot_data = None
        self._tripilot_views = None
        if isinstance(dataobj, tuple):
            self._tripilot_data = tuple(np.asarray(item) for item in dataobj)
            dataobj = dataobj[0]
            self._status_var.set("Multiple slice packs detected; showing the first pack.")

        affines = list(affine) if isinstance(affine, tuple) else [affine]

        data = np.asarray(dataobj)
        if data.ndim < 3:
            self._status_var.set("Scan data is not at least 3D.")
            return

        try:
            data_ras, affine_ras, info = reorient_to_ras(data, np.asarray(affines[0]))
        except Exception as exc:
            messagebox.showerror("Orientation error", f"Failed to reorient data:\n{exc}")
            return

        self._data = data_ras
        self._affine = affine_ras
        self._res = info.get("res_ras")
        self._qc_message = info.get("qc_message")

        if self._tripilot_data and len(self._tripilot_data) >= 3:
            self._tripilot_views = self._build_tripilot_views(self._tripilot_data, affines)

        self._view_error = None
        self._status_var.set("Space: scanner (RAS)")

        self._update_slice_range()
        self._update_frame_range()
        self._update_plot()

    def _update_slice_range(self) -> None:
        if self._data is None:
            self._x_scale.configure(from_=0, to=0, state=tk.DISABLED)
            self._y_scale.configure(from_=0, to=0, state=tk.DISABLED)
            self._z_scale.configure(from_=0, to=0, state=tk.DISABLED)
            self._x_var.set(0)
            self._y_var.set(0)
            self._z_var.set(0)
            return
        if self._tripilot_views is not None:
            self._x_scale.configure(from_=0, to=0, state=tk.DISABLED)
            self._y_scale.configure(from_=0, to=0, state=tk.DISABLED)
            self._z_scale.configure(from_=0, to=0, state=tk.DISABLED)
            self._x_var.set(0)
            self._y_var.set(0)
            self._z_var.set(0)
            return
        shape = self._data.shape
        max_x = max(shape[0] - 1, 0)
        max_y = max(shape[1] - 1, 0)
        max_z = max(shape[2] - 1, 0)
        self._x_scale.configure(from_=0, to=max_x, state=tk.NORMAL)
        self._y_scale.configure(from_=0, to=max_y, state=tk.NORMAL)
        self._z_scale.configure(from_=0, to=max_z, state=tk.NORMAL)

        if self._slice_hint is not None:
            hint = max(self._slice_hint, 0)
            axis = (self._slice_hint_axis or "").lower()
            if axis == "sagittal":
                self._x_var.set(min(hint, max_x))
            elif axis == "coronal":
                self._y_var.set(min(hint, max_y))
            else:
                self._z_var.set(min(hint, max_z))
            self._slice_hint = None
        else:
            self._x_var.set(max_x // 2)
            self._y_var.set(max_y // 2)
            self._z_var.set(max_z // 2)

    def _update_frame_range(self) -> None:
        if self._tripilot_views is not None or self._data is None or self._data.ndim < 4:
            self._frame_scale.configure(from_=0, to=0, state=tk.DISABLED)
            self._frame_var.set(0)
            self._clear_extra_dims()
            return
        max_index = self._data.shape[3] - 1
        self._frame_scale.configure(from_=0, to=max_index, state=tk.NORMAL)
        self._frame_var.set(min(self._frame_var.get(), max_index))
        self._update_extra_dims()

    def _get_volume(self) -> Optional[np.ndarray]:
        if self._data is None:
            return None
        data = self._data
        if data.ndim > 3:
            frame = int(self._frame_var.get())
            data = data[..., frame]
            for idx, var in enumerate(self._extra_dim_vars):
                dim_index = int(var.get())
                if data.ndim <= 3:
                    break
                data = data[..., dim_index]
        return data

    def _orth_slices(self) -> Optional[Dict[str, Tuple[np.ndarray, Tuple[float, float]]]]:
        if self._tripilot_views is not None:
            return self._tripilot_views
        data = self._get_volume()
        if data is None or self._res is None:
            return None
        rx, ry, rz = self._res
        x_idx = int(self._x_var.get())
        y_idx = int(self._y_var.get())
        z_idx = int(self._z_var.get())

        img_zy = data[x_idx, :, :]  # (y, z)
        img_xy = data[:, :, z_idx].T  # (y, x)
        img_xz = data[:, y_idx, :].T  # (z, x)

        return {
            "zy": (img_zy, (float(rz), float(ry))),
            "xy": (img_xy, (float(rx), float(ry))),
            "xz": (img_xz, (float(rx), float(rz))),
        }

    def _build_tripilot_views(
        self,
        data_list: Tuple[np.ndarray, ...],
        affines: list[np.ndarray],
    ) -> Dict[str, Tuple[np.ndarray, Tuple[float, float]]]:
        views: Dict[str, Tuple[np.ndarray, Tuple[float, float]]] = {}
        keys = ("zy", "xy", "xz")
        for idx, key in enumerate(keys):
            if idx >= len(data_list):
                continue
            data = np.asarray(data_list[idx])
            affine = np.asarray(affines[idx if idx < len(affines) else 0])
            if data.ndim == 2:
                data = data[:, :, np.newaxis]
            elif data.ndim < 2:
                continue
            try:
                data_ras, _, info = reorient_to_ras(data, affine)
                res = info.get("res_ras")
            except Exception:
                data_ras = data
                res = None

            if data_ras.ndim > 2:
                slice_idx = data_ras.shape[2] // 2
                img = data_ras[:, :, slice_idx]
            else:
                img = data_ras

            if isinstance(res, (list, tuple, np.ndarray)) and len(res) >= 2:
                spacing = (float(res[0]), float(res[1]))
            else:
                spacing = (1.0, 1.0)
            views[key] = (img, spacing)
        return views

    def _update_plot(self) -> None:
        if self._view_error:
            self._viewer.show_message(self._view_error, is_error=True)
            return
        slices = self._orth_slices()
        if self._data is None or slices is None:
            self._viewer.show_message("No data loaded", is_error=False)
            return

        title_map = {
            "zy": f"Z-Y (x={int(self._x_var.get())})",
            "xy": f"X-Y (z={int(self._z_var.get())})",
            "xz": f"X-Z (y={int(self._y_var.get())})",
        }
        if self._data.ndim > 3:
            title_map = {k: f"{v} | frame {int(self._frame_var.get())}" for k, v in title_map.items()}
        self._viewer.render_views(slices, title_map)
        self._render_markers()

    @staticmethod
    def _format_value(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, dt.datetime):
            return value.isoformat(sep=" ", timespec="seconds")
        if isinstance(value, (list, tuple, np.ndarray)):
            return ", ".join(str(v) for v in value)
        return str(value)

    @staticmethod
    def _lookup_nested(data: Dict[str, Any], path: Iterable[str]) -> Optional[Any]:
        current: Any = data
        for key in path:
            if not isinstance(current, dict) or key not in current:
                return None
            current = current[key]
        return current

    def _resolve_info_bundle(self) -> Dict[str, Any]:
        if not self._loader:
            return {}
        try:
            info = self._loader.info(as_dict=True, scan_transpose=False)
        except Exception:
            info = {}
        info_dict: Dict[str, Any]
        if isinstance(info, dict):
            info_dict = cast(Dict[str, Any], info)
        else:
            info_dict = {}
        if self._study:
            scan_info: Dict[int, Dict[str, Any]] = {}
            for scan_id in self._study.avail.keys():
                scan = self._study.avail.get(scan_id)
                if scan is None:
                    continue
                try:
                    spec_path = self._select_info_spec_path(scan)
                    if spec_path:
                        scan_info[scan_id] = info_resolver.scan(cast(Any, scan), spec_source=spec_path)
                    else:
                        scan_info[scan_id] = info_resolver.scan(cast(Any, scan))
                except Exception:
                    scan_block = info_dict.get("Scan(s)", {})
                    if isinstance(scan_block, dict):
                        scan_info[scan_id] = scan_block.get(scan_id, {})
                    else:
                        scan_info[scan_id] = {}
            if scan_info:
                info_dict["Scan(s)"] = scan_info
        return info_dict


def launch(
    *,
    path: Optional[str],
    scan_id: Optional[int],
    reco_id: Optional[int],
    info_spec: Optional[str],
    axis: str,
    slice_index: Optional[int],
) -> int:
    app = ViewerApp(
        path=path,
        scan_id=scan_id,
        reco_id=reco_id,
        info_spec=info_spec,
        axis=axis,
        slice_index=slice_index,
    )
    app.mainloop()
    return 0
