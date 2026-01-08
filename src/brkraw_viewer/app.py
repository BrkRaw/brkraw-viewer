from __future__ import annotations

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple, cast
import datetime as dt
from pathlib import Path

import numpy as np
import pprint
import importlib

from brkraw.apps.loader import BrukerLoader
from brkraw.apps.loader.types import StudyLoader
from brkraw.resolver import affine as affine_resolver
from brkraw.resolver.affine import SubjectPose, SubjectType
from brkraw.apps.loader import info as info_resolver
from brkraw.core import config as config_core
from brkraw.core import layout as layout_core
from brkraw.core.config import resolve_root
from brkraw.specs.rules import load_rules, select_rule_use
from brkraw.apps import addon as addon_app
from .utils.orientation import reorient_to_ras
from .viewer_canvas import OrthogonalCanvas
from .app_config import ConfigTabMixin
from .app_convert import ConvertTabMixin

ScanLike = Any

WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 760


class ViewerApp(ConvertTabMixin, ConfigTabMixin, tk.Tk):
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
        self._icon_image: Optional[tk.PhotoImage] = None

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
        self._slice_hint: Optional[int] = slice_index
        self._slice_hint_axis = axis
        self._frame_index = 0
        self._current_reco_id: Optional[int] = None
        self._slicepack_data: Optional[Tuple[np.ndarray, ...]] = None
        self._slicepack_affines: Optional[Tuple[np.ndarray, ...]] = None
        self._current_subject_type: Optional[str] = None
        self._current_subject_pose: Optional[str] = None
        self._view_error: Optional[str] = None
        self._extra_dim_vars: list[tk.IntVar] = []
        self._extra_dim_scales: list[tk.Scale] = []

        self._path_var = tk.StringVar(value=path or "")
        self._x_var = tk.IntVar(value=0)
        self._y_var = tk.IntVar(value=0)
        self._z_var = tk.IntVar(value=0)
        self._frame_var = tk.IntVar(value=0)
        self._slicepack_var = tk.IntVar(value=0)
        self._space_var = tk.StringVar(value="scanner")
        self._show_crosshair_var = tk.BooleanVar(value=True)
        self._zoom_var = tk.DoubleVar(value=1.0)
        self._status_var = tk.StringVar(value="Ready")
        self._viewer_dirty = True
        self._loaded_view_signature: Optional[Tuple[Any, ...]] = None
        self._frame_bar: Optional[ttk.Frame] = None
        self._frame_inner: Optional[ttk.Frame] = None
        self._frame_label: Optional[ttk.Label] = None
        self._slicepack_box: Optional[ttk.Frame] = None
        self._view_crop_origins: Dict[str, Tuple[int, int]] = {"xy": (0, 0), "xz": (0, 0), "zy": (0, 0)}

        self._subject_type_var = tk.StringVar(value="Biped")
        self._pose_primary_var = tk.StringVar(value="Head")
        self._pose_secondary_var = tk.StringVar(value="Supine")
        self._rule_text_var = tk.StringVar(value="Rule: auto")
        self._rule_enabled_var = tk.BooleanVar(value=True)
        self._rule_override_var = tk.BooleanVar(value=False)
        self._rule_override_path = tk.StringVar(value="")
        self._rule_name_var = tk.StringVar(value="None")
        self._rule_match_var = tk.StringVar(value="None")
        self._spec_kind_var = tk.StringVar(value="info_spec")
        self._spec_name_var = tk.StringVar(value="None")
        self._spec_match_var = tk.StringVar(value="None")
        self._spec_path_var = tk.StringVar(value="None")
        self._spec_file_path_var = tk.StringVar(value="")
        self._param_scope_var = tk.StringVar(value="all")
        self._param_query_var = tk.StringVar(value="")

        self._rule_display_map: Dict[str, Tuple[str, Any]] = {}
        self._spec_display_map: Dict[str, Any] = {}

        self._layout_enabled_var = tk.BooleanVar(value=False)
        default_layout_template = config_core.layout_template(root=None) or ""
        default_slicepack_suffix = config_core.output_slicepack_suffix(root=None)
        self._layout_template_var = tk.StringVar(value=default_layout_template)
        self._slicepack_suffix_var = tk.StringVar(value=default_slicepack_suffix)
        self._use_layout_entries_var = tk.BooleanVar(value=True)
        self._layout_info_spec_name_var = tk.StringVar(value="None")
        self._layout_info_spec_match_var = tk.StringVar(value="None")
        self._layout_metadata_spec_name_var = tk.StringVar(value="None")
        self._layout_metadata_spec_match_var = tk.StringVar(value="None")
        self._layout_info_spec_file_var = tk.StringVar(value="")
        self._layout_metadata_spec_file_var = tk.StringVar(value="")
        self._output_dir_var = tk.StringVar(value="output")
        self._convert_space_var = tk.StringVar(value="subject_ras")
        self._convert_subject_type_var = tk.StringVar(value="Biped")
        self._convert_pose_primary_var = tk.StringVar(value="Head")
        self._convert_pose_secondary_var = tk.StringVar(value="Supine")
        self._convert_use_viewer_pose_var = tk.BooleanVar(value=True)

        self._layout_info_spec_combo: Optional[ttk.Combobox] = None
        self._layout_metadata_spec_combo: Optional[ttk.Combobox] = None
        self._layout_key_listbox: Optional[tk.Listbox] = None
        self._layout_key_source_signature: Optional[Tuple[Any, ...]] = None
        self._convert_settings_text: Optional[tk.Text] = None
        self._convert_preview_text: Optional[tk.Text] = None

        self._init_ui()
        self._apply_window_presentation()

        if path:
            self._load_path(path, scan_id=scan_id, reco_id=reco_id)
        else:
            self._status_var.set("Open a study folder, zip, or PvDatasets package to begin.")

    def _apply_window_presentation(self) -> None:
        self._set_app_icon()
        self.after(0, self._bring_to_front)
        self.after(250, self._bring_to_front)

    def _bring_to_front(self) -> None:
        try:
            self.deiconify()
        except Exception:
            pass
        try:
            self.lift()
        except Exception:
            pass
        try:
            self.attributes("-topmost", True)
            self.after(50, lambda: self.attributes("-topmost", False))
        except Exception:
            pass
        try:
            self.focus_force()
        except Exception:
            pass

    def _set_app_icon(self) -> None:
        try:
            here = Path(__file__).resolve().parent
            assets = here / "assets"
            png = assets / "icon.png"
            ico = assets / "icon.ico"
        except Exception:
            return

        if png.exists():
            try:
                self._icon_image = tk.PhotoImage(file=str(png))
                self.iconphoto(True, self._icon_image)
            except Exception:
                self._icon_image = None

        if ico.exists():
            try:
                self.iconbitmap(default=str(ico))
            except Exception:
                pass

    def _init_ui(self) -> None:
        top = ttk.Frame(self, padding=(10, 10, 10, 6))
        top.pack(side=tk.TOP, fill=tk.X)

        load_button = ttk.Menubutton(top, text="Load")
        load_menu = tk.Menu(load_button, tearoff=False)
        load_menu.add_command(label="Folder (Study / .PvDatasets)…", command=self._choose_dir)
        load_menu.add_command(label="Archive File (.zip / .PvDatasets)…", command=self._choose_file)
        load_button.configure(menu=load_menu)
        load_button.pack(side=tk.LEFT, padx=(0, 6))
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
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        paned = ttk.Panedwindow(body, orient=tk.HORIZONTAL)
        paned.grid(row=0, column=0, sticky="nsew")

        left_frame = ttk.Frame(paned, padding=(0, 0, 8, 0))
        left_frame.columnconfigure(0, weight=1)
        left_frame.rowconfigure(1, weight=1)
        left_frame.rowconfigure(3, weight=1)

        ttk.Label(left_frame, text="Scans").grid(row=0, column=0, sticky="w", pady=(0, 4))
        scans_box = ttk.Frame(left_frame)
        scans_box.grid(row=1, column=0, sticky="nsew")
        scans_box.columnconfigure(0, weight=1)
        scans_box.rowconfigure(0, weight=1)
        self._scan_listbox = tk.Listbox(scans_box, width=28, height=18, exportselection=False)
        self._scan_listbox.grid(row=0, column=0, sticky="nsew")
        self._scan_listbox.bind("<<ListboxSelect>>", self._on_scan_select)
        self._scan_scroll = ttk.Scrollbar(scans_box, orient="vertical", command=self._scan_listbox.yview)
        self._scan_scroll.grid(row=0, column=1, sticky="ns")
        self._scan_listbox.configure(yscrollcommand=self._scan_scroll.set)

        ttk.Label(left_frame, text="Recos").grid(row=2, column=0, sticky="w", pady=(10, 4))
        recos_box = ttk.Frame(left_frame)
        recos_box.grid(row=3, column=0, sticky="nsew")
        recos_box.columnconfigure(0, weight=1)
        recos_box.rowconfigure(0, weight=1)
        self._reco_listbox = tk.Listbox(recos_box, width=28, height=8, exportselection=False)
        self._reco_listbox.grid(row=0, column=0, sticky="nsew")
        self._reco_listbox.bind("<<ListboxSelect>>", self._on_reco_select)
        self._reco_scroll = ttk.Scrollbar(recos_box, orient="vertical", command=self._reco_listbox.yview)
        self._reco_scroll.grid(row=0, column=1, sticky="ns")
        self._reco_listbox.configure(yscrollcommand=self._reco_scroll.set)

        right_frame = ttk.Frame(paned)
        right_frame.columnconfigure(0, weight=1)
        right_frame.rowconfigure(0, weight=1)

        paned.add(left_frame, weight=0)
        paned.add(right_frame, weight=1)

        self._notebook = ttk.Notebook(right_frame)
        self._notebook.grid(row=0, column=0, sticky="nsew")
        self._notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        viewer_tab = ttk.Frame(self._notebook)
        info_tab = ttk.Frame(self._notebook)
        layout_tab = ttk.Frame(self._notebook)
        config_tab = ttk.Frame(self._notebook)
        self._notebook.add(viewer_tab, text="Viewer")
        self._notebook.add(info_tab, text="Info")
        self._notebook.add(layout_tab, text="Convert")
        self._notebook.add(config_tab, text="Config")

        viewer_tab.columnconfigure(0, weight=1)
        viewer_tab.rowconfigure(1, weight=1)

        viewer_top = ttk.Frame(viewer_tab)
        viewer_top.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        viewer_top.columnconfigure(0, weight=1)
        viewer_top_inner = ttk.Frame(viewer_top)
        viewer_top_inner.grid(row=0, column=0)

        ttk.Label(viewer_top_inner, text="Space").pack(side=tk.LEFT, padx=(0, 10))
        for label, value in (("raw", "raw"), ("scanner", "scanner"), ("subject_ras", "subject_ras")):
            ttk.Radiobutton(
                viewer_top_inner,
                text=label,
                value=value,
                variable=self._space_var,
                command=self._on_space_change,
            ).pack(side=tk.LEFT, padx=(0, 10))

        ttk.Label(viewer_top_inner, text="Subject Type").pack(side=tk.LEFT, padx=(18, 8))
        self._subject_type_combo = ttk.Combobox(
            viewer_top_inner,
            textvariable=self._subject_type_var,
            state="disabled",
            values=("Biped", "Quadruped", "Phantom", "Other", "OtherAnimal"),
            width=12,
        )
        self._subject_type_combo.pack(side=tk.LEFT)

        ttk.Label(viewer_top_inner, text="Pose").pack(side=tk.LEFT, padx=(18, 8))
        self._pose_primary_combo = ttk.Combobox(
            viewer_top_inner,
            textvariable=self._pose_primary_var,
            state="disabled",
            values=("Head", "Foot"),
            width=8,
        )
        self._pose_primary_combo.pack(side=tk.LEFT)
        self._pose_secondary_combo = ttk.Combobox(
            viewer_top_inner,
            textvariable=self._pose_secondary_var,
            state="disabled",
            values=("Supine", "Prone", "Left", "Right"),
            width=8,
        )
        self._pose_secondary_combo.pack(side=tk.LEFT, padx=(8, 0))

        self._apply_subject_button = ttk.Button(viewer_top_inner, text="Apply", command=self._apply_subject_override)
        self._apply_subject_button.pack(side=tk.LEFT, padx=(10, 0))
        self._apply_subject_button.configure(state=tk.DISABLED)

        self._apply_subject_button.pack_forget()

        for combo in (self._subject_type_combo, self._pose_primary_combo, self._pose_secondary_combo):
            combo.bind("<<ComboboxSelected>>", self._on_subject_override_change)

        preview_frame = ttk.Frame(viewer_tab, padding=(6, 6))
        preview_frame.grid(row=1, column=0, sticky="nsew")
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(2, weight=1)

        slider_bar = ttk.Frame(preview_frame)
        slider_bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        slider_bar.columnconfigure(0, weight=1)
        slider_inner = ttk.Frame(slider_bar)
        slider_inner.grid(row=0, column=0)

        ttk.Label(slider_inner, text="X").pack(side=tk.LEFT, padx=(0, 4))
        self._x_scale = tk.Scale(
            slider_inner,
            from_=0,
            to=0,
            orient=tk.HORIZONTAL,
            showvalue=True,
            command=self._on_x_change,
            length=140,
        )
        self._x_scale.pack(side=tk.LEFT)
        self._x_scale.configure(variable=self._x_var)

        ttk.Label(slider_inner, text="Y").pack(side=tk.LEFT, padx=(6, 4))
        self._y_scale = tk.Scale(
            slider_inner,
            from_=0,
            to=0,
            orient=tk.HORIZONTAL,
            showvalue=True,
            command=self._on_y_change,
            length=140,
        )
        self._y_scale.pack(side=tk.LEFT)
        self._y_scale.configure(variable=self._y_var)

        ttk.Label(slider_inner, text="Z").pack(side=tk.LEFT, padx=(6, 4))
        self._z_scale = tk.Scale(
            slider_inner,
            from_=0,
            to=0,
            orient=tk.HORIZONTAL,
            showvalue=True,
            command=self._on_z_change,
            length=140,
        )
        self._z_scale.pack(side=tk.LEFT)
        self._z_scale.configure(variable=self._z_var)

        ttk.Checkbutton(
            slider_inner,
            text="Crosshair",
            variable=self._show_crosshair_var,
            command=self._update_plot,
        ).pack(side=tk.LEFT, padx=(14, 0))

        ttk.Label(slider_inner, text="Zoom").pack(side=tk.LEFT, padx=(14, 4))
        self._zoom_scale = tk.Scale(
            slider_inner,
            from_=1.0,
            to=4.0,
            resolution=0.25,
            orient=tk.HORIZONTAL,
            showvalue=True,
            command=self._on_zoom_change,
            length=110,
        )
        self._zoom_scale.pack(side=tk.LEFT)
        self._zoom_scale.configure(variable=self._zoom_var)

        frame_bar = ttk.Frame(preview_frame)
        frame_bar.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        self._frame_bar = frame_bar
        frame_bar.columnconfigure(0, weight=1)
        frame_inner = ttk.Frame(frame_bar)
        frame_inner.grid(row=0, column=0)
        self._frame_inner = frame_inner

        self._frame_label = ttk.Label(frame_inner, text="Frame")
        self._frame_label.pack(side=tk.LEFT, padx=(0, 4))
        self._frame_scale = tk.Scale(
            frame_inner,
            from_=0,
            to=0,
            orient=tk.HORIZONTAL,
            showvalue=True,
            command=self._on_frame_change,
            length=160,
        )
        self._frame_scale.pack(side=tk.LEFT)
        self._frame_scale.configure(variable=self._frame_var)

        self._extra_frame = ttk.Frame(frame_inner)
        self._extra_frame.pack(side=tk.LEFT, padx=(10, 0))
        frame_bar.grid_remove()

        self._viewer = OrthogonalCanvas(preview_frame)
        self._viewer.grid(row=2, column=0, sticky="nsew")
        self._viewer.set_click_callback(self._on_view_click)
        self._viewer.set_zoom_callback(self._on_zoom_wheel)

        bottom_bar = ttk.Frame(preview_frame)
        bottom_bar.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        bottom_bar.columnconfigure(0, weight=1)
        slicepack_box = ttk.Frame(bottom_bar)
        slicepack_box.grid(row=0, column=1, sticky="e")
        self._slicepack_box = slicepack_box
        ttk.Label(slicepack_box, text="Slicepack").pack(side=tk.LEFT, padx=(0, 4))
        self._slicepack_scale = tk.Scale(
            slicepack_box,
            from_=0,
            to=0,
            orient=tk.HORIZONTAL,
            showvalue=True,
            command=self._on_slicepack_change,
            length=160,
        )
        self._slicepack_scale.pack(side=tk.LEFT)
        self._slicepack_scale.configure(variable=self._slicepack_var, state=tk.DISABLED)
        self._slicepack_box.grid_remove()

        info_tab.columnconfigure(0, weight=2)
        info_tab.columnconfigure(1, weight=3)
        info_tab.rowconfigure(0, weight=1)

        info_left = ttk.Frame(info_tab, padding=(6, 6))
        info_left.grid(row=0, column=0, sticky="nsew")
        info_left.columnconfigure(0, weight=1)
        info_left.rowconfigure(0, weight=2)
        info_left.rowconfigure(1, weight=1)

        info_controls = ttk.LabelFrame(info_left, text="Scan Info", padding=(8, 8))
        info_controls.grid(row=0, column=0, sticky="nsew")
        info_controls.columnconfigure(1, weight=1)

        ttk.Label(info_controls, text="Rule").grid(row=0, column=0, sticky="w")
        self._rule_combo = ttk.Combobox(
            info_controls,
            textvariable=self._rule_name_var,
            state="disabled",
            values=("None",),
        )
        self._rule_combo.grid(row=0, column=1, sticky="ew", padx=(8, 6))
        self._rule_combo.bind("<<ComboboxSelected>>", lambda *_: self._on_rule_selected())
        ttk.Label(info_controls, textvariable=self._rule_match_var).grid(row=0, column=2, sticky="e")

        ttk.Label(info_controls, text="Spec kind").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self._spec_kind_combo = ttk.Combobox(
            info_controls,
            textvariable=self._spec_kind_var,
            state="readonly",
            values=("info_spec", "metadata_spec"),
            width=14,
        )
        self._spec_kind_combo.grid(row=1, column=1, sticky="w", padx=(8, 6), pady=(10, 0))
        self._spec_kind_combo.bind("<<ComboboxSelected>>", lambda *_: self._refresh_spec_list())

        ttk.Label(info_controls, text="Installed").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self._spec_combo = ttk.Combobox(
            info_controls,
            textvariable=self._spec_name_var,
            state="disabled",
            values=("None",),
        )
        self._spec_combo.grid(row=2, column=1, sticky="ew", padx=(8, 6), pady=(8, 0))
        self._spec_combo.bind("<<ComboboxSelected>>", lambda *_: self._on_spec_selected())
        ttk.Label(info_controls, textvariable=self._spec_match_var).grid(row=2, column=2, sticky="e", pady=(8, 0))

        ttk.Entry(info_controls, textvariable=self._spec_path_var, state="readonly").grid(
            row=3, column=0, columnspan=3, sticky="ew", pady=(6, 0)
        )
        ttk.Button(info_controls, text="Apply Selected", command=self._apply_selected_spec).grid(
            row=4, column=0, columnspan=3, sticky="ew", pady=(8, 0)
        )

        ttk.Label(info_controls, text="Spec file").grid(row=5, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(info_controls, textvariable=self._spec_file_path_var).grid(
            row=5, column=1, sticky="ew", padx=(8, 6), pady=(10, 0)
        )
        ttk.Button(info_controls, text="Browse", command=self._browse_spec_file).grid(
            row=5, column=2, sticky="e", pady=(10, 0)
        )
        ttk.Button(info_controls, text="Apply File", command=self._apply_spec_file).grid(
            row=6, column=0, columnspan=3, sticky="ew", pady=(8, 0)
        )

        param_controls = ttk.LabelFrame(info_left, text="Scan Parameters", padding=(8, 8))
        param_controls.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        param_controls.columnconfigure(0, weight=1)

        file_row = ttk.Frame(param_controls)
        file_row.grid(row=0, column=0, sticky="ew")
        file_row.columnconfigure(1, weight=1)
        ttk.Label(file_row, text="File").grid(row=0, column=0, sticky="w")
        scope_combo = ttk.Combobox(
            file_row,
            textvariable=self._param_scope_var,
            values=("all", "acqp", "method", "reco", "visu_pars"),
            state="readonly",
        )
        scope_combo.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        query_row = ttk.Frame(param_controls)
        query_row.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        query_row.columnconfigure(1, weight=1)
        ttk.Label(query_row, text="Query").grid(row=0, column=0, sticky="w")
        query_entry = ttk.Entry(query_row, textvariable=self._param_query_var)
        query_entry.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        query_entry.bind("<Return>", lambda *_: self._run_param_search())

        ttk.Button(param_controls, text="Search", command=self._run_param_search).grid(
            row=2, column=0, sticky="ew", pady=(8, 0)
        )

        info_right = ttk.Frame(info_tab, padding=(6, 6))
        info_right.grid(row=0, column=1, sticky="nsew")
        info_right.columnconfigure(0, weight=1)
        info_right.rowconfigure(0, weight=1)

        self._info_output_text = tk.Text(info_right, wrap="word")
        self._info_output_text.grid(row=0, column=0, sticky="nsew")
        info_scroll = ttk.Scrollbar(info_right, orient="vertical", command=self._info_output_text.yview)
        info_scroll.grid(row=0, column=1, sticky="ns")
        self._info_output_text.configure(yscrollcommand=info_scroll.set)
        self._info_output_text.configure(state=tk.DISABLED)

        self._build_convert_tab(layout_tab)
        self._build_config_tab(config_tab)

        self._update_convert_space_controls()
        self._update_layout_controls()
        self._refresh_layout_spec_selectors()
        self._load_config_text()

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
            title="Select Bruker dataset archive",
            filetypes=(
                (
                    "Dataset archives",
                    "*.zip *.PvDatasets *.pvdatasets",
                ),
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
        candidate_paths = self._candidate_load_paths(path)
        last_exc: Optional[Exception] = None
        for candidate in candidate_paths:
            try:
                self._loader = BrukerLoader(candidate)
                self._study = cast(StudyLoader, self._loader._study)
                break
            except Exception as exc:
                last_exc = exc
        else:
            details = "\n".join(candidate_paths) if candidate_paths else path
            messagebox.showerror(
                "Load error",
                f"Failed to load dataset:\n{last_exc}\n\nTried:\n{details}",
            )
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

    def _candidate_load_paths(self, path: str) -> list[str]:
        candidate = Path(path)
        suffix_lower = candidate.suffix.lower()
        variants: list[str] = [path]

        if suffix_lower == ".zip":
            variants.append(str(candidate.with_suffix(".zip")))
        elif suffix_lower == ".pvdatasets":
            variants.append(str(candidate.with_suffix(".PvDatasets")))
            variants.append(str(candidate.with_suffix(".pvdatasets")))

        seen: set[str] = set()
        out: list[str] = []
        for item in variants:
            if item in seen:
                continue
            seen.add(item)
            try:
                if Path(item).exists():
                    out.append(item)
            except OSError:
                continue

        if not out:
            return [path]
        return out

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
        self._refresh_info_selectors()
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
        self._preset_subject_defaults_from_reco(reco_id=reco_id)
        self._update_space_controls()
        self._mark_viewer_dirty()
        self._maybe_load_viewer()
        self._refresh_info_selectors()

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

    def _on_slicepack_change(self, value: str) -> None:
        try:
            index = int(float(value))
        except ValueError:
            return
        self._slicepack_var.set(index)
        self._apply_slicepack(index)

    def _on_extra_dim_change(self, *_: object) -> None:
        self._update_plot()

    def _rule_entries(self, kind: str) -> list[Any]:
        try:
            rules = load_rules(root=resolve_root(None), validate=False)
        except Exception:
            rules = {}
        raw = rules.get(kind, [])
        if isinstance(raw, (list, tuple)):
            return list(raw)
        return []

    @staticmethod
    def _rule_name(rule: Any, *, index: int) -> str:
        if isinstance(rule, dict):
            for key in ("name", "spec_name", "spec", "id", "title", "key"):
                value = rule.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        if isinstance(rule, str) and rule.strip():
            return rule.strip()
        return f"rule_{index}"

    @staticmethod
    def _rule_description(rule: Any) -> str:
        if isinstance(rule, dict):
            for key in ("description", "desc", "help"):
                value = rule.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return ""

    def _installed_entries(self) -> list[Tuple[str, Any]]:
        out: list[Tuple[str, Any]] = []
        for kind in ("metadata_spec", "info_spec", "converter_hook"):
            for rule in self._rule_entries(kind):
                out.append((kind, rule))
        return out

    def _installed_specs(self) -> list[Dict[str, str]]:
        try:
            installed = addon_app.list_installed(root=resolve_root(None))
        except Exception:
            return []
        specs = installed.get("specs", [])
        if not isinstance(specs, list):
            return []
        out: list[Dict[str, str]] = []
        for item in specs:
            if isinstance(item, dict):
                out.append({k: str(v) for k, v in item.items() if isinstance(k, str)})
        return out

    def _resolve_installed_spec_path(self, *, name: str, kind: str) -> Optional[str]:
        if not name or name == "None":
            return None
        try:
            path = addon_app.resolve_spec_reference(name, category=kind, root=resolve_root(None))
        except Exception:
            return None
        return str(path)

    def _auto_selected_spec_path(self, kind: str) -> Optional[str]:
        if self._scan is None:
            return None
        try:
            rules = load_rules(root=resolve_root(None), validate=False)
            path = select_rule_use(
                self._scan,
                rules.get(kind, []),
                base=resolve_root(None),
                resolve_paths=True,
            )
        except Exception:
            return None
        return str(path) if path else None

    def _resolve_rule_match(self, kind: str, rule: Any) -> Optional[str]:
        if self._scan is None:
            return None
        try:
            path = select_rule_use(
                self._scan,
                [rule],
                base=resolve_root(None),
                resolve_paths=True,
            )
        except Exception:
            return None
        return str(path) if path else None

    def _refresh_info_selectors(self) -> None:
        if self._scan is None:
            self._rule_combo.configure(values=("None",), state="disabled")
            self._rule_name_var.set("None")
            self._rule_match_var.set("None")
            self._refresh_spec_list()
            return

        installed = self._installed_entries()
        if not installed:
            self._rule_combo.configure(values=("None",), state="disabled")
            self._rule_name_var.set("None")
            self._rule_match_var.set("None")
        else:
            base_names = [self._rule_name(rule, index=i) for i, (_, rule) in enumerate(installed)]
            counts: Dict[str, int] = {}
            for name in base_names:
                counts[name] = counts.get(name, 0) + 1

            display_values: list[str] = []
            self._rule_display_map = {}
            for i, (kind, rule) in enumerate(installed):
                base = self._rule_name(rule, index=i)
                display = f"{base} ({kind})" if counts.get(base, 0) > 1 else base
                display_values.append(display)
                self._rule_display_map[display] = (kind, rule)

            auto_display = "None"
            for display, (kind, rule) in self._rule_display_map.items():
                if self._resolve_rule_match(kind, rule):
                    auto_display = display
                    break

            self._rule_combo.configure(values=display_values, state="readonly")
            if self._rule_name_var.get() not in display_values:
                self._rule_name_var.set(auto_display if auto_display != "None" else display_values[0])
            self._update_rule_match_label()

        self._refresh_spec_list()
        self._refresh_layout_spec_selectors()

    def _update_rule_match_label(self) -> None:
        display = (self._rule_name_var.get() or "").strip()
        selected = self._rule_display_map.get(display)
        if selected is None:
            self._rule_match_var.set("None")
            return
        kind, rule = selected
        path = self._resolve_rule_match(kind, rule)
        self._rule_match_var.set("MATCH" if path else "NO MATCH")

    def _on_rule_selected(self) -> None:
        self._update_rule_match_label()
        self._refresh_spec_list()

    def _refresh_spec_list(self) -> None:
        kind = (self._spec_kind_var.get() or "info_spec").strip()
        installed_specs = [s for s in self._installed_specs() if s.get("category") == kind]
        if self._scan is None or not installed_specs:
            self._spec_combo.configure(values=("None",), state="disabled")
            self._spec_name_var.set("None")
            self._spec_match_var.set("None")
            self._spec_path_var.set("None")
            return

        names = []
        for item in installed_specs:
            n = item.get("name")
            if n and n != "<Unknown>":
                names.append(n)
        names = sorted(set(names))
        if not names:
            self._spec_combo.configure(values=("None",), state="disabled")
            self._spec_name_var.set("None")
            self._spec_match_var.set("None")
            self._spec_path_var.set("None")
            return

        auto_path = self._auto_selected_spec_path(kind)
        auto_name: Optional[str] = None
        if auto_path:
            for name in names:
                resolved = self._resolve_installed_spec_path(name=name, kind=kind)
                if resolved and Path(resolved).resolve() == Path(auto_path).resolve():
                    auto_name = name
                    break

        self._spec_combo.configure(values=tuple(names), state="readonly")
        if self._spec_name_var.get() not in names:
            self._spec_name_var.set(auto_name or names[0])
        self._on_spec_selected()

    def _on_spec_selected(self) -> None:
        kind = (self._spec_kind_var.get() or "info_spec").strip()
        name = (self._spec_name_var.get() or "").strip()
        if self._scan is None or not name or name == "None":
            self._spec_match_var.set("None")
            self._spec_path_var.set("None")
            return
        path = self._resolve_installed_spec_path(name=name, kind=kind)
        if not path:
            self._spec_match_var.set("NO MATCH")
            self._spec_path_var.set("None")
            return
        self._spec_path_var.set(path)
        auto_path = self._auto_selected_spec_path(kind)
        if auto_path and Path(auto_path).resolve() == Path(path).resolve():
            self._spec_match_var.set("DEFAULT")
        else:
            self._spec_match_var.set("OK")

    def _apply_selected_spec(self) -> None:
        if self._scan is None:
            self._set_info_output("No scan selected.")
            return
        kind = (self._spec_kind_var.get() or "info_spec").strip()
        path = (self._spec_path_var.get() or "").strip()
        if not path or path == "None":
            self._set_info_output("No spec selected.")
            return
        data = self._apply_spec_to_scan(kind=kind, spec_path=path, reco_id=self._current_reco_id)
        self._set_info_output(pprint.pformat(data, sort_dicts=False, width=120))

    def _browse_spec_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Select spec YAML",
            filetypes=(("YAML", "*.yaml *.yml"), ("All files", "*.*")),
        )
        if not path:
            return
        self._spec_file_path_var.set(path)

    def _apply_spec_file(self) -> None:
        if self._scan is None:
            self._set_info_output("No scan selected.")
            return
        path = (self._spec_file_path_var.get() or "").strip()
        if not path:
            self._set_info_output("No spec file selected.")
            return
        if not Path(path).exists():
            self._set_info_output(f"Spec file not found: {path}")
            return

        # Try to interpret file as info spec first, then metadata spec.
        for kind in ("info_spec", "metadata_spec"):
            data = self._apply_spec_to_scan(kind=kind, spec_path=path, reco_id=self._current_reco_id)
            if not isinstance(data, dict):
                continue
            if data:
                self._set_info_output(pprint.pformat(data, sort_dicts=False, width=120))
                return
        self._set_info_output("Failed to apply spec file (unsupported or produced empty output).")

    def _apply_spec_to_scan(self, *, kind: str, spec_path: str, reco_id: Optional[int]) -> Dict[str, Any]:
        if self._scan is None:
            return {}

        if kind == "info_spec":
            try:
                return cast(Dict[str, Any], info_resolver.scan(cast(Any, self._scan), spec_source=spec_path))
            except Exception as exc:
                return {"error": str(exc), "kind": kind, "spec_path": spec_path}

        # Prefer scan.get_metadata(...) when available (brkraw metadata pipeline).
        get_metadata = getattr(self._scan, "get_metadata", None)
        if callable(get_metadata):
            variants: list[Dict[str, Any]] = []
            if reco_id is not None:
                variants.extend(
                    [
                        {"reco_id": reco_id, "spec_source": spec_path},
                        {"reco_id": reco_id, "metadata_spec_source": spec_path},
                        {"reco_id": reco_id, "metadata_spec": spec_path},
                        {"reco_id": reco_id, "spec": spec_path},
                        {"reco_id": reco_id},
                    ]
                )
            variants.extend(
                [
                    {"spec_source": spec_path},
                    {"metadata_spec_source": spec_path},
                    {"metadata_spec": spec_path},
                    {"spec": spec_path},
                    {},
                ]
            )
            last_exc: Optional[Exception] = None
            for kwargs in variants:
                try:
                    result = get_metadata(**kwargs)
                    if isinstance(result, dict):
                        return cast(Dict[str, Any], result)
                    return {"error": "get_metadata returned non-dict", "kind": kind, "spec_path": spec_path, "kwargs": kwargs}
                except TypeError as exc:
                    last_exc = exc
                    continue
                except Exception as exc:
                    return {"error": str(exc), "kind": kind, "spec_path": spec_path, "kwargs": kwargs}
            return {
                "error": f"get_metadata signature mismatch: {last_exc}",
                "kind": kind,
                "spec_path": spec_path,
            }

        # Fallback: best-effort metadata spec support via info_resolver.scan (depends on brkraw version).
        for kwargs in (
            {"metadata_spec_source": spec_path, **({"reco_id": reco_id} if reco_id is not None else {})},
            {"metadata_source": spec_path, **({"reco_id": reco_id} if reco_id is not None else {})},
            {"metadata_spec": spec_path, **({"reco_id": reco_id} if reco_id is not None else {})},
        ):
            try:
                return cast(Dict[str, Any], info_resolver.scan(cast(Any, self._scan), **kwargs))
            except TypeError:
                continue
            except Exception as exc:
                return {"error": str(exc), "kind": kind, "spec_path": spec_path, "kwargs": kwargs}
        return {"error": "metadata_spec not supported (no get_metadata and no compatible scan() kwargs)", "kind": kind, "spec_path": spec_path}

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
        self._update_plot()

    def _on_view_click(self, view: str, row: int, col: int) -> None:
        if self._data is None:
            return
        origin_row, origin_col = self._view_crop_origins.get(view, (0, 0))
        row += int(origin_row)
        col += int(origin_col)
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

        self._x_var.set(x)
        self._y_var.set(y)
        self._z_var.set(z)
        self._update_plot()

    def _on_zoom_change(self, value: str) -> None:
        try:
            z = float(value)
        except Exception:
            return
        z = max(1.0, min(4.0, z))
        if abs(float(self._zoom_var.get()) - z) > 1e-9:
            self._zoom_var.set(z)
        self._update_plot()

    def _on_zoom_wheel(self, direction: int) -> None:
        try:
            current = float(self._zoom_var.get())
        except Exception:
            current = 1.0
        step = 0.25
        new = current + (step if direction > 0 else -step)
        new = max(1.0, min(4.0, new))
        if abs(current - new) < 1e-9:
            return
        self._zoom_var.set(new)
        try:
            self._zoom_scale.set(new)
        except Exception:
            pass
        self._update_plot()

    @staticmethod
    def _crop_view(img: np.ndarray, *, center_row: int, center_col: int, zoom: float) -> Tuple[np.ndarray, Tuple[int, int]]:
        if zoom <= 1.0:
            return img, (0, 0)
        h, w = img.shape[:2]
        if h <= 0 or w <= 0:
            return img, (0, 0)
        window_h = max(2, int(round(h / zoom)))
        window_w = max(2, int(round(w / zoom)))
        window_h = min(window_h, h)
        window_w = min(window_w, w)

        center_row = int(max(0, min(h - 1, center_row)))
        center_col = int(max(0, min(w - 1, center_col)))

        r0 = center_row - window_h // 2
        c0 = center_col - window_w // 2
        r0 = max(0, min(h - window_h, r0))
        c0 = max(0, min(w - window_w, c0))
        cropped = img[r0 : r0 + window_h, c0 : c0 + window_w]
        return cropped, (r0, c0)

    def _params_bundle(self, *, reco_id: int) -> Dict[str, Dict[str, Any]]:
        if self._scan is None:
            return {}

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

        return params_data

    def _run_param_search(self) -> None:
        query = (self._param_query_var.get() or "").strip()
        if not query:
            return
        if self._scan is None or self._current_reco_id is None:
            self._status_var.set("No reco selected.")
            return

        bundle = self._params_bundle(reco_id=self._current_reco_id)
        scope = (self._param_scope_var.get() or "all").strip()
        if scope != "all":
            bundle = {scope: bundle.get(scope, {})}

        query_lower = query.lower()
        matches: list[tuple[str, str, Any]] = []

        def _walk(src: str, prefix: str, obj: Any) -> None:
            if isinstance(obj, dict):
                for k, v in obj.items():
                    key = str(k)
                    path = f"{prefix}.{key}" if prefix else key
                    if query_lower in key.lower():
                        matches.append((src, path, v))
                    _walk(src, path, v)
            elif isinstance(obj, (list, tuple)):
                for i, v in enumerate(obj):
                    path = f"{prefix}[{i}]"
                    _walk(src, path, v)
            else:
                try:
                    text = str(obj)
                except Exception:
                    text = ""
                if text and query_lower in text.lower():
                    matches.append((src, prefix, obj))

        for src, data in bundle.items():
            _walk(src, "", data)

        payload = {
            "scope": scope,
            "query": query,
            "matches": [{"file": src, "path": path, "value": value} for src, path, value in matches[:500]],
            "truncated": max(len(matches) - 500, 0),
        }
        self._set_info_output(pprint.pformat(payload, sort_dicts=False, width=120))

    def _set_info_output(self, text: str) -> None:
        self._info_output_text.configure(state=tk.NORMAL)
        self._info_output_text.delete("1.0", tk.END)
        self._info_output_text.insert(tk.END, text)
        self._info_output_text.configure(state=tk.DISABLED)

    def _browse_output_dir(self) -> None:
        super()._browse_output_dir()

    def _set_convert_preview(self, text: str) -> None:
        super()._set_convert_preview(text)

    def _set_convert_settings(self, text: str) -> None:
        super()._set_convert_settings(text)

    def _update_convert_space_controls(self) -> None:
        super()._update_convert_space_controls()

    def _update_layout_controls(self) -> None:
        super()._update_layout_controls()

    def _refresh_layout_spec_selectors(self) -> None:
        super()._refresh_layout_spec_selectors()

    def _refresh_layout_spec_status(self) -> None:
        super()._refresh_layout_spec_status()

    def _browse_layout_spec_file(self, *, kind: str) -> None:
        super()._browse_layout_spec_file(kind=kind)

    def _layout_builtin_info_spec_paths(self) -> tuple[Optional[str], Optional[str]]:
        return super()._layout_builtin_info_spec_paths()

    def _layout_override_info_spec_path(self) -> Optional[str]:
        return super()._layout_override_info_spec_path()

    def _layout_override_metadata_spec_path(self) -> Optional[str]:
        return super()._layout_override_metadata_spec_path()

    def _refresh_layout_keys(self) -> None:
        super()._refresh_layout_keys()

    def _flatten_keys(self, obj: Any, prefix: str = "") -> Iterable[str]:
        return super()._flatten_keys(obj, prefix=prefix)

    def _on_layout_key_double_click(self, *_: object) -> None:
        super()._on_layout_key_double_click(*_)

    def _on_layout_key_click(self, *_: object) -> None:
        super()._on_layout_key_click(*_)

    def _on_layout_key_mouse_down(self, *_: object) -> Optional[str]:
        return super()._on_layout_key_mouse_down(*_)
    def _load_config_text(self) -> None:
        super()._load_config_text()

    def _save_config_text(self) -> None:
        super()._save_config_text()

    def _reset_config_text(self) -> None:
        super()._reset_config_text()

    def _convert_subject_overrides(self) -> tuple[Optional[SubjectType], Optional[SubjectPose]]:
        return super()._convert_subject_overrides()

    def _estimate_slicepack_count(self) -> int:
        return super()._estimate_slicepack_count()

    def _planned_output_paths(self) -> list[Path]:
        return super()._planned_output_paths()

    def _preview_convert_outputs(self) -> None:
        super()._preview_convert_outputs()

    def _convert_current_scan(self) -> None:
        super()._convert_current_scan()

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

        text = "\n".join([line for line in lines if line and line != "None"])
        self._set_info_output(text)

    def _on_space_change(self) -> None:
        self._update_space_controls()
        if self._current_reco_id is None:
            return
        self._mark_viewer_dirty()
        self._maybe_load_viewer()

    def _update_space_controls(self) -> None:
        enabled = self._space_var.get() == "subject_ras"
        combo_state = "readonly" if enabled else "disabled"
        self._subject_type_combo.configure(state=combo_state)
        self._pose_primary_combo.configure(state=combo_state)
        self._pose_secondary_combo.configure(state=combo_state)
        # Apply button removed (changes auto-apply).

    def _apply_subject_override(self) -> None:
        if self._space_var.get() != "subject_ras":
            return
        if self._current_reco_id is None:
            return
        self._mark_viewer_dirty()
        self._maybe_load_viewer()

    def _on_subject_override_change(self, *_: object) -> None:
        if self._space_var.get() != "subject_ras":
            return
        if self._current_reco_id is None:
            return
        self._mark_viewer_dirty()
        self._maybe_load_viewer()

    def _on_tab_changed(self, *_: object) -> None:
        self._maybe_load_viewer()

    def _is_viewer_tab_active(self) -> bool:
        try:
            current = self._notebook.tab(self._notebook.select(), "text")
        except Exception:
            return True
        return current == "Viewer"

    def _mark_viewer_dirty(self) -> None:
        self._viewer_dirty = True

    def _viewer_signature(self) -> Tuple[Any, ...]:
        scan_id = getattr(self._scan, "scan_id", None) if self._scan is not None else None
        return (
            scan_id,
            self._current_reco_id,
            (self._space_var.get() or "").strip(),
            (self._subject_type_var.get() or "").strip(),
            (self._pose_primary_var.get() or "").strip(),
            (self._pose_secondary_var.get() or "").strip(),
        )

    def _maybe_load_viewer(self) -> None:
        if not self._is_viewer_tab_active():
            return
        if self._current_reco_id is None:
            return
        signature = self._viewer_signature()
        if not self._viewer_dirty and self._loaded_view_signature == signature:
            return
        self._load_data(reco_id=self._current_reco_id)
        self._loaded_view_signature = signature
        self._viewer_dirty = False

    def _infer_subject_type_pose_from_reco(self, *, reco_id: int) -> tuple[Optional[str], str]:
        if self._scan is None:
            return None, "Head_Supine"
        try:
            reco = self._scan.avail.get(reco_id)
            visu_pars = getattr(reco, "visu_pars", None) if reco else None
            subj_type, subj_pose = (
                affine_resolver.get_subject_type_and_position(visu_pars) if visu_pars else (None, "Head_Supine")
            )
        except Exception:
            subj_type, subj_pose = None, "Head_Supine"
        return subj_type, subj_pose or "Head_Supine"

    def _preset_subject_defaults_from_reco(self, *, reco_id: int) -> None:
        subj_type, subj_pose = self._infer_subject_type_pose_from_reco(reco_id=reco_id)
        self._current_subject_type = subj_type
        self._current_subject_pose = subj_pose

        self._subject_type_var.set(subj_type or "Biped")
        self._convert_subject_type_var.set(subj_type or "Biped")

        if subj_pose and "_" in subj_pose:
            primary, secondary = subj_pose.split("_", 1)
        else:
            primary, secondary = "Head", "Supine"
        self._pose_primary_var.set(primary or "Head")
        self._pose_secondary_var.set(secondary or "Supine")
        self._convert_pose_primary_var.set(primary or "Head")
        self._convert_pose_secondary_var.set(secondary or "Supine")

    def _resolve_affine_for_space(self, *, reco_id: int) -> Optional[Any]:
        if self._scan is None:
            return None

        selected_space = (self._space_var.get() or "").strip()
        if selected_space not in {"raw", "scanner", "subject_ras"}:
            selected_space = "scanner"

        if selected_space in {"raw", "scanner"}:
            try:
                return self._scan.get_affine(
                    reco_id=reco_id,
                    space=selected_space,
                    override_subject_type=None,
                    override_subject_pose=None,
                )
            except Exception:
                pass

            raw_affine = self._scan.get_affine(
                reco_id=reco_id,
                space="raw",
                override_subject_type=None,
                override_subject_pose=None,
            )
            if raw_affine is None:
                return None
            affines = list(raw_affine) if isinstance(raw_affine, tuple) else [raw_affine]
            subj_type, subj_pose = self._infer_subject_type_pose_from_reco(reco_id=reco_id)
            use_type = self._cast_subject_type(subj_type)
            use_pose = self._cast_subject_pose(subj_pose)
            affines_scanner = [
                affine_resolver.unwrap_to_scanner_xyz(np.asarray(aff), use_type, use_pose)
                for aff in affines
            ]
            return tuple(affines_scanner) if isinstance(raw_affine, tuple) else affines_scanner[0]

        override_type = self._cast_subject_type((self._subject_type_var.get() or "").strip())
        override_pose = self._cast_subject_pose(
            f"{(self._pose_primary_var.get() or '').strip()}_{(self._pose_secondary_var.get() or '').strip()}"
        )

        for space_candidate in ("subject_ras", "subject", "scanner"):
            try:
                affine = self._scan.get_affine(
                    reco_id=reco_id,
                    space=space_candidate,
                    override_subject_type=override_type,
                    override_subject_pose=override_pose,
                )
                if affine is not None:
                    return affine
            except Exception:
                continue

        raw_affine = self._scan.get_affine(
            reco_id=reco_id,
            space="raw",
            override_subject_type=None,
            override_subject_pose=None,
        )
        if raw_affine is None:
            return None
        affines = list(raw_affine) if isinstance(raw_affine, tuple) else [raw_affine]
        affines_subject = [
            affine_resolver.unwrap_to_scanner_xyz(np.asarray(aff), override_type, override_pose)
            for aff in affines
        ]
        return tuple(affines_subject) if isinstance(raw_affine, tuple) else affines_subject[0]

    @staticmethod
    def _cast_subject_type(value: Optional[str]) -> SubjectType:
        allowed = {"Biped", "Quadruped", "Phantom", "Other", "OtherAnimal"}
        if isinstance(value, str) and value in allowed:
            return cast(SubjectType, value)
        return cast(SubjectType, "Biped")

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
        if isinstance(value, str) and value in allowed:
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
            row = idx // 3
            col = (idx % 3) * 2
            label = ttk.Label(self._extra_frame, text=f"Dim {idx + 5}")
            label.grid(row=row, column=col, sticky="w", padx=(0, 4), pady=(0, 4) if row else (0, 0))
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
            scale.grid(row=row, column=col + 1, sticky="w", padx=(0, 10), pady=(0, 4) if row else (0, 0))
            self._extra_dim_vars.append(var)
            self._extra_dim_scales.append(scale)
            scale.configure(variable=var)

    def _load_data(self, *, reco_id: int) -> None:
        if self._scan is None:
            return
        try:
            dataobj = self._scan.get_dataobj(reco_id=reco_id)
            affine = self._resolve_affine_for_space(reco_id=reco_id)
        except Exception as exc:
            messagebox.showerror("Load error", f"Failed to load data:\n{exc}")
            self._status_var.set("Failed to load scan data.")
            return

        if dataobj is None or affine is None:
            self._status_var.set("Scan data unavailable for this reco.")
            return

        affines = list(affine) if isinstance(affine, tuple) else [affine]
        previous_slicepack = int(self._slicepack_var.get())
        self._slicepack_data = None
        self._slicepack_affines = None
        self._slicepack_scale.configure(from_=0, to=0, state=tk.DISABLED)
        self._slicepack_var.set(0)
        self._update_slicepack_visibility(0)

        if isinstance(dataobj, tuple):
            data_list = tuple(np.asarray(item) for item in dataobj)
            if not data_list:
                self._status_var.set("Scan data unavailable for this reco.")
                return
            affine_list = [np.asarray(affines[i] if i < len(affines) else affines[0]) for i in range(len(data_list))]
            self._slicepack_data = data_list
            self._slicepack_affines = tuple(affine_list)
            self._update_slicepack_visibility(len(data_list))
            if len(data_list) > 1:
                self._slicepack_scale.configure(from_=0, to=len(data_list) - 1, state=tk.NORMAL)
                self._slicepack_var.set(min(max(previous_slicepack, 0), len(data_list) - 1))
            self._apply_slicepack(int(self._slicepack_var.get()))
            return

        self._render_data_and_affine(np.asarray(dataobj), np.asarray(affines[0]))
        self._update_slicepack_visibility(1)

    def _apply_slicepack(self, index: int) -> None:
        if self._slicepack_data is None or self._slicepack_affines is None:
            return
        if not self._slicepack_data:
            return
        safe_index = max(min(int(index), len(self._slicepack_data) - 1), 0)
        self._slicepack_var.set(safe_index)
        data = np.asarray(self._slicepack_data[safe_index])
        affine = np.asarray(
            self._slicepack_affines[safe_index]
            if safe_index < len(self._slicepack_affines)
            else self._slicepack_affines[0]
        )
        self._clear_extra_dims()

        label = f"Slicepack {safe_index + 1}/{len(self._slicepack_data)}"
        self._status_var.set(f"Space: {self._space_var.get()} (RAS) | {label}")
        self._render_data_and_affine(data, affine)
        if self._current_reco_id is not None:
            self._update_scan_info(self._current_scan_info_dict(), self._current_reco_id)

    def _render_data_and_affine(self, data: np.ndarray, affine: np.ndarray) -> None:
        if data.ndim < 3:
            self._status_var.set("Scan data is not at least 3D.")
            return
        try:
            data_ras, affine_ras = reorient_to_ras(data, affine)
        except Exception as exc:
            messagebox.showerror("Orientation error", f"Failed to reorient data:\n{exc}")
            return

        self._data = data_ras
        self._affine = affine_ras
        self._res = np.linalg.norm(np.asarray(affine_ras)[:3, :3], axis=0)

        self._view_error = None
        if self._slicepack_data is None:
            self._status_var.set(f"Space: {self._space_var.get()} (RAS)")

        self._update_slice_range()
        self._update_frame_range()
        self._update_plot()

    def _current_scan_info_dict(self) -> Dict[str, Any]:
        scan_id = getattr(self._scan, "scan_id", None) if self._scan is not None else None
        scan_info_all = self._info_full.get("Scan(s)", {}) if self._info_full else {}
        if not isinstance(scan_info_all, dict):
            scan_info_all = {}
        scan_info_all = cast(Dict[int, Any], scan_info_all)
        info = scan_info_all.get(scan_id) if scan_id is not None else {}
        if not info and scan_id is not None and self._scan is not None:
            info = self._resolve_scan_info(scan_id, self._scan)
        if not isinstance(info, dict):
            return {}
        return cast(Dict[str, Any], info)

    def _update_slice_range(self) -> None:
        if self._data is None:
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
        if self._data is None or self._data.ndim < 4:
            self._frame_scale.configure(from_=0, to=0, state=tk.DISABLED)
            self._frame_var.set(0)
            self._clear_extra_dims()
            if self._frame_bar is not None:
                self._frame_bar.grid_remove()
            return

        def _set_frame_controls_visible(visible: bool) -> None:
            if self._frame_label is None:
                return
            if visible:
                try:
                    self._extra_frame.pack_forget()
                except Exception:
                    pass
                try:
                    self._frame_label.pack_forget()
                    self._frame_scale.pack_forget()
                except Exception:
                    pass
                self._frame_label.pack(side=tk.LEFT, padx=(0, 4))
                self._frame_scale.pack(side=tk.LEFT)
                self._extra_frame.pack(side=tk.LEFT, padx=(10, 0))
            else:
                try:
                    self._frame_label.pack_forget()
                    self._frame_scale.pack_forget()
                except Exception:
                    pass

        frame_count = int(self._data.shape[3])
        has_extra = self._data.ndim > 4
        max_index = frame_count - 1

        self._frame_scale.configure(from_=0, to=max_index, state=tk.NORMAL)
        self._frame_var.set(min(self._frame_var.get(), max_index))
        self._update_extra_dims()
        if frame_count <= 1:
            self._frame_var.set(0)
            self._frame_scale.configure(state=tk.DISABLED)
            _set_frame_controls_visible(False)
            if self._frame_bar is not None:
                if has_extra:
                    self._frame_bar.grid()
                else:
                    self._frame_bar.grid_remove()
            return

        _set_frame_controls_visible(True)
        if self._frame_bar is not None:
            self._frame_bar.grid()

    def _update_slicepack_visibility(self, count: int) -> None:
        if self._slicepack_box is None:
            return
        if count > 1:
            self._slicepack_box.grid()
        else:
            self._slicepack_box.grid_remove()

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

    def _update_plot(self) -> None:
        if self._view_error:
            self._viewer.show_message(self._view_error, is_error=True)
            return
        slices = self._orth_slices()
        if self._data is None or slices is None:
            self._viewer.show_message("No data loaded", is_error=False)
            return

        zoom = float(self._zoom_var.get() or 1.0)
        title_map = {
            "zy": f"Z-Y (x={int(self._x_var.get())})",
            "xy": f"X-Y (z={int(self._z_var.get())})",
            "xz": f"X-Z (y={int(self._y_var.get())})",
        }
        if self._data.ndim > 3:
            title_map = {k: f"{v} | frame {int(self._frame_var.get())}" for k, v in title_map.items()}

        self._view_crop_origins = {"xy": (0, 0), "xz": (0, 0), "zy": (0, 0)}
        crosshair_base = {
            "xy": (int(self._y_var.get()), int(self._x_var.get())),
            "xz": (int(self._z_var.get()), int(self._x_var.get())),
            "zy": (int(self._y_var.get()), int(self._z_var.get())),
        }

        if zoom > 1.0:
            zoomed: Dict[str, Tuple[np.ndarray, Tuple[float, float]]] = {}
            crosshair: Dict[str, Tuple[int, int]] = {}
            for key, (img, res) in slices.items():
                center_row, center_col = crosshair_base[key]
                cropped, origin = self._crop_view(img, center_row=center_row, center_col=center_col, zoom=zoom)
                self._view_crop_origins[key] = origin
                crosshair[key] = (center_row - origin[0], center_col - origin[1])
                zoomed[key] = (cropped, res)
            slices = zoomed
        else:
            crosshair = crosshair_base

        self._viewer.render_views(
            slices,
            title_map,
            crosshair=crosshair,
            show_crosshair=bool(self._show_crosshair_var.get()),
        )

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
