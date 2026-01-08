from __future__ import annotations

import importlib
import pprint
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Any, Iterable, Mapping, Optional, cast

from brkraw.core import config as config_core
from brkraw.core import layout as layout_core
from brkraw.core.config import resolve_root
from brkraw.resolver.affine import SubjectPose, SubjectType


class ConvertTabMixin:
    # The concrete host (ViewerApp) provides these attributes/methods.
    # They are declared here to keep type checkers (pyright/pylance) happy.
    _loader: Any
    _scan: Any
    _current_reco_id: Optional[int]
    _status_var: tk.StringVar

    _use_layout_entries_var: tk.BooleanVar
    _layout_template_var: tk.StringVar
    _layout_template_entry: ttk.Entry
    _slicepack_suffix_var: tk.StringVar
    _output_dir_var: tk.StringVar

    _layout_info_spec_name_var: tk.StringVar
    _layout_info_spec_match_var: tk.StringVar
    _layout_metadata_spec_name_var: tk.StringVar
    _layout_metadata_spec_match_var: tk.StringVar
    _layout_info_spec_file_var: tk.StringVar
    _layout_metadata_spec_file_var: tk.StringVar
    _layout_info_spec_combo: Optional[ttk.Combobox]
    _layout_metadata_spec_combo: Optional[ttk.Combobox]
    _layout_key_listbox: Optional[tk.Listbox]
    _layout_key_source_signature: Optional[tuple[Any, ...]]
    _layout_keys_title: tk.StringVar

    _convert_space_var: tk.StringVar
    _convert_use_viewer_pose_var: tk.BooleanVar
    _convert_subject_type_var: tk.StringVar
    _convert_pose_primary_var: tk.StringVar
    _convert_pose_secondary_var: tk.StringVar
    _convert_subject_type_combo: ttk.Combobox
    _convert_pose_primary_combo: ttk.Combobox
    _convert_pose_secondary_combo: ttk.Combobox
    _convert_settings_text: Optional[tk.Text]
    _convert_preview_text: Optional[tk.Text]

    _subject_type_var: tk.StringVar
    _pose_primary_var: tk.StringVar
    _pose_secondary_var: tk.StringVar

    def _installed_specs(self) -> list[dict[str, Any]]: ...
    def _auto_selected_spec_path(self, kind: str) -> Optional[str]: ...
    def _resolve_installed_spec_path(self, *, name: str, kind: str) -> Optional[str]: ...
    @staticmethod
    def _cast_subject_type(value: Optional[str]) -> SubjectType: ...

    @staticmethod
    def _cast_subject_pose(value: Optional[str]) -> SubjectPose: ...

    def _build_convert_tab(self, layout_tab: ttk.Frame) -> None:
        layout_tab.columnconfigure(0, weight=1)
        layout_tab.rowconfigure(1, weight=1)

        output_layout = ttk.LabelFrame(layout_tab, text="Output Layout", padding=(8, 8))
        output_layout.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        output_layout.columnconfigure(1, weight=1)

        ttk.Checkbutton(
            output_layout,
            text="Use config layout_entries",
            variable=self._use_layout_entries_var,
            command=self._update_layout_controls,
        ).grid(row=0, column=0, columnspan=2, sticky="w")

        ttk.Label(output_layout, text="Template").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self._layout_template_entry = ttk.Entry(output_layout, textvariable=self._layout_template_var)
        self._layout_template_entry.grid(row=1, column=1, sticky="ew", pady=(8, 0))

        ttk.Label(output_layout, text="Slicepack suffix").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(output_layout, textvariable=self._slicepack_suffix_var).grid(row=2, column=1, sticky="ew", pady=(8, 0))

        ttk.Label(output_layout, text="Info spec").grid(row=3, column=0, sticky="w", pady=(8, 0))
        self._layout_info_spec_combo = ttk.Combobox(
            output_layout,
            textvariable=self._layout_info_spec_name_var,
            values=("None",),
            state="disabled",
        )
        self._layout_info_spec_combo.grid(row=3, column=1, sticky="ew", pady=(8, 0))
        ttk.Label(output_layout, textvariable=self._layout_info_spec_match_var).grid(
            row=3, column=2, sticky="e", padx=(6, 0), pady=(8, 0)
        )
        self._layout_info_spec_combo.bind("<<ComboboxSelected>>", lambda *_: self._refresh_layout_spec_status())

        ttk.Entry(output_layout, textvariable=self._layout_info_spec_file_var).grid(row=4, column=1, sticky="ew", pady=(6, 0))
        ttk.Button(output_layout, text="Browse", command=lambda: self._browse_layout_spec_file(kind="info_spec")).grid(
            row=4, column=2, sticky="e", padx=(6, 0), pady=(6, 0)
        )

        ttk.Label(output_layout, text="Metadata spec").grid(row=5, column=0, sticky="w", pady=(10, 0))
        self._layout_metadata_spec_combo = ttk.Combobox(
            output_layout,
            textvariable=self._layout_metadata_spec_name_var,
            values=("None",),
            state="disabled",
        )
        self._layout_metadata_spec_combo.grid(row=5, column=1, sticky="ew", pady=(10, 0))
        ttk.Label(output_layout, textvariable=self._layout_metadata_spec_match_var).grid(
            row=5, column=2, sticky="e", padx=(6, 0), pady=(10, 0)
        )
        self._layout_metadata_spec_combo.bind("<<ComboboxSelected>>", lambda *_: self._refresh_layout_spec_status())

        ttk.Entry(output_layout, textvariable=self._layout_metadata_spec_file_var).grid(row=6, column=1, sticky="ew", pady=(6, 0))
        ttk.Button(output_layout, text="Browse", command=lambda: self._browse_layout_spec_file(kind="metadata_spec")).grid(
            row=6, column=2, sticky="e", padx=(6, 0), pady=(6, 0)
        )

        output_layout.columnconfigure(3, weight=0)
        keys_frame = ttk.LabelFrame(output_layout, text="Keys", padding=(6, 6))
        keys_frame.grid(row=0, column=3, rowspan=7, sticky="nsew", padx=(10, 0))
        keys_frame.columnconfigure(0, weight=1)
        keys_frame.rowconfigure(1, weight=1)
        self._layout_keys_title = tk.StringVar(value="Key (click to add)")
        ttk.Label(keys_frame, textvariable=self._layout_keys_title).grid(row=0, column=0, sticky="w")
        self._layout_key_listbox = tk.Listbox(keys_frame, width=28, height=10, exportselection=False)
        self._layout_key_listbox.grid(row=1, column=0, sticky="nsew")
        keys_scroll = ttk.Scrollbar(keys_frame, orient="vertical", command=self._layout_key_listbox.yview)
        keys_scroll.grid(row=1, column=1, sticky="ns")
        self._layout_key_listbox.configure(yscrollcommand=keys_scroll.set)
        self._layout_key_listbox.bind("<Button-1>", self._on_layout_key_mouse_down)
        self._layout_key_listbox.bind("<ButtonRelease-1>", self._on_layout_key_click)
        self._layout_key_listbox.bind("<Double-Button-1>", self._on_layout_key_double_click)

        convert_frame = ttk.LabelFrame(layout_tab, text="Convert", padding=(8, 8))
        convert_frame.grid(row=1, column=0, sticky="nsew")
        convert_frame.columnconfigure(0, weight=1)
        convert_frame.columnconfigure(1, weight=2)
        convert_frame.rowconfigure(0, weight=1)

        convert_left = ttk.Frame(convert_frame)
        convert_left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        convert_left.columnconfigure(1, weight=1)

        ttk.Label(convert_left, text="Output dir").grid(row=0, column=0, sticky="w", pady=(0, 6))
        ttk.Entry(convert_left, textvariable=self._output_dir_var).grid(row=0, column=1, sticky="ew", pady=(0, 6))
        ttk.Button(convert_left, text="Browse", command=self._browse_output_dir).grid(
            row=0, column=2, padx=(6, 0), pady=(0, 6)
        )

        ttk.Label(convert_left, text="Space").grid(row=1, column=0, sticky="w")
        convert_space = ttk.Combobox(
            convert_left,
            textvariable=self._convert_space_var,
            values=("raw", "scanner", "subject_ras"),
            state="readonly",
            width=12,
        )
        convert_space.grid(row=1, column=1, sticky="w")
        convert_space.bind("<<ComboboxSelected>>", lambda *_: self._update_convert_space_controls())

        ttk.Checkbutton(
            convert_left,
            text="Use Viewer type/pose",
            variable=self._convert_use_viewer_pose_var,
            command=self._update_convert_space_controls,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))

        convert_subject_row = ttk.Frame(convert_left)
        convert_subject_row.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        ttk.Label(convert_subject_row, text="Subject Type").pack(side=tk.LEFT)
        self._convert_subject_type_combo = ttk.Combobox(
            convert_subject_row,
            textvariable=self._convert_subject_type_var,
            values=("Biped", "Quadruped", "Phantom", "Other", "OtherAnimal"),
            state="disabled",
            width=12,
        )
        self._convert_subject_type_combo.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(convert_subject_row, text="Pose").pack(side=tk.LEFT, padx=(10, 0))
        self._convert_pose_primary_combo = ttk.Combobox(
            convert_subject_row,
            textvariable=self._convert_pose_primary_var,
            values=("Head", "Foot"),
            state="disabled",
            width=8,
        )
        self._convert_pose_primary_combo.pack(side=tk.LEFT, padx=(8, 0))
        self._convert_pose_secondary_combo = ttk.Combobox(
            convert_subject_row,
            textvariable=self._convert_pose_secondary_var,
            values=("Supine", "Prone", "Left", "Right"),
            state="disabled",
            width=8,
        )
        self._convert_pose_secondary_combo.pack(side=tk.LEFT, padx=(4, 0))

        actions = ttk.Frame(convert_left)
        actions.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        ttk.Button(actions, text="Preview Outputs", command=self._preview_convert_outputs).grid(row=0, column=0, sticky="ew")
        ttk.Button(actions, text="Convert", command=self._convert_current_scan).grid(row=0, column=1, sticky="ew", padx=(8, 0))

        preview_box = ttk.LabelFrame(convert_frame, text="Output Preview", padding=(6, 6))
        preview_box.grid(row=0, column=1, sticky="nsew")
        preview_box.columnconfigure(0, weight=1)
        preview_box.columnconfigure(1, weight=0)
        preview_box.rowconfigure(0, weight=1)
        preview_box.rowconfigure(1, weight=0)

        self._convert_settings_text = tk.Text(preview_box, wrap="word", height=10)
        self._convert_settings_text.grid(row=0, column=0, sticky="nsew", pady=(0, 6))
        settings_scroll = ttk.Scrollbar(preview_box, orient="vertical", command=self._convert_settings_text.yview)
        settings_scroll.grid(row=0, column=1, sticky="ns", pady=(0, 6))
        self._convert_settings_text.configure(yscrollcommand=settings_scroll.set)
        self._convert_settings_text.configure(state=tk.DISABLED)

        self._convert_preview_text = tk.Text(preview_box, wrap="none", height=3)
        self._convert_preview_text.grid(row=1, column=0, sticky="ew")
        preview_scroll_y = ttk.Scrollbar(preview_box, orient="vertical", command=self._convert_preview_text.yview)
        preview_scroll_y.grid(row=1, column=1, sticky="ns")
        preview_scroll_x = ttk.Scrollbar(preview_box, orient="horizontal", command=self._convert_preview_text.xview)
        preview_scroll_x.grid(row=2, column=0, columnspan=2, sticky="ew")
        self._convert_preview_text.configure(yscrollcommand=preview_scroll_y.set, xscrollcommand=preview_scroll_x.set)
        self._convert_preview_text.configure(state=tk.DISABLED)

    def _browse_output_dir(self) -> None:
        path = filedialog.askdirectory(title="Select output directory")
        if not path:
            return
        self._output_dir_var.set(path)

    def _set_convert_preview(self, text: str) -> None:
        if self._convert_preview_text is None:
            return
        self._convert_preview_text.configure(state=tk.NORMAL)
        self._convert_preview_text.delete("1.0", tk.END)
        self._convert_preview_text.insert(tk.END, text)
        self._convert_preview_text.configure(state=tk.DISABLED)

    def _set_convert_settings(self, text: str) -> None:
        if self._convert_settings_text is None:
            return
        self._convert_settings_text.configure(state=tk.NORMAL)
        self._convert_settings_text.delete("1.0", tk.END)
        self._convert_settings_text.insert(tk.END, text)
        self._convert_settings_text.configure(state=tk.DISABLED)

    def _update_convert_space_controls(self) -> None:
        enabled = self._convert_space_var.get() == "subject_ras"
        if self._convert_use_viewer_pose_var.get():
            self._convert_subject_type_combo.configure(state="disabled")
            self._convert_pose_primary_combo.configure(state="disabled")
            self._convert_pose_secondary_combo.configure(state="disabled")
            return
        state = "readonly" if enabled else "disabled"
        self._convert_subject_type_combo.configure(state=state)
        self._convert_pose_primary_combo.configure(state=state)
        self._convert_pose_secondary_combo.configure(state=state)

    def _update_layout_controls(self) -> None:
        use_entries = bool(self._use_layout_entries_var.get())
        try:
            self._layout_template_entry.configure(state="disabled" if use_entries else "normal")
        except Exception:
            pass
        if use_entries and self._layout_key_listbox is not None:
            self._layout_key_listbox.selection_clear(0, tk.END)
        self._refresh_layout_keys()

    def _refresh_layout_spec_selectors(self) -> None:
        if self._layout_info_spec_combo is None or self._layout_metadata_spec_combo is None:
            return
        if self._scan is None:
            self._layout_info_spec_combo.configure(values=("Default",), state="disabled")
            self._layout_metadata_spec_combo.configure(values=("None",), state="disabled")
            self._layout_info_spec_name_var.set("Default")
            self._layout_metadata_spec_name_var.set("None")
            self._refresh_layout_spec_status()
            return

        info_specs = [
            s
            for s in self._installed_specs()
            if s.get("category") == "info_spec" and s.get("name") not in (None, "<Unknown>")
        ]
        meta_specs = [
            s
            for s in self._installed_specs()
            if s.get("category") == "metadata_spec" and s.get("name") not in (None, "<Unknown>")
        ]
        info_names = sorted({cast(str, s["name"]) for s in info_specs if isinstance(s.get("name"), str)})
        meta_names = sorted({cast(str, s["name"]) for s in meta_specs if isinstance(s.get("name"), str)})

        def _auto_name(kind: str, names: list[str]) -> Optional[str]:
            auto_path = self._auto_selected_spec_path(kind)
            if not auto_path:
                return None
            for name in names:
                resolved = self._resolve_installed_spec_path(name=name, kind=kind)
                if resolved and Path(resolved).resolve() == Path(auto_path).resolve():
                    return name
            return None

        if info_names:
            choices = ["Default"] + info_names
            self._layout_info_spec_combo.configure(values=tuple(choices), state="readonly")
            if self._layout_info_spec_name_var.get() not in choices:
                self._layout_info_spec_name_var.set(_auto_name("info_spec", info_names) or "Default")
        else:
            self._layout_info_spec_combo.configure(values=("Default",), state="disabled")
            self._layout_info_spec_name_var.set("Default")

        if meta_names:
            choices = ["None"] + meta_names
            self._layout_metadata_spec_combo.configure(values=tuple(choices), state="readonly")
            if self._layout_metadata_spec_name_var.get() not in choices:
                self._layout_metadata_spec_name_var.set(_auto_name("metadata_spec", meta_names) or "None")
        else:
            self._layout_metadata_spec_combo.configure(values=("None",), state="disabled")
            self._layout_metadata_spec_name_var.set("None")

        self._refresh_layout_spec_status()

    def _refresh_layout_spec_status(self) -> None:
        info_name = (self._layout_info_spec_name_var.get() or "Default").strip()
        meta_name = (self._layout_metadata_spec_name_var.get() or "None").strip()
        info_path = self._layout_override_info_spec_path()
        meta_path = self._layout_override_metadata_spec_path()

        auto_info = self._auto_selected_spec_path("info_spec")
        auto_meta = self._auto_selected_spec_path("metadata_spec")

        if info_name == "Default" and not (self._layout_info_spec_file_var.get() or "").strip():
            self._layout_info_spec_match_var.set("Default")
        elif not info_path:
            self._layout_info_spec_match_var.set("None")
        else:
            self._layout_info_spec_match_var.set(
                "DEFAULT" if auto_info and Path(auto_info).resolve() == Path(info_path).resolve() else "OK"
            )

        if meta_name == "None" or not meta_path:
            self._layout_metadata_spec_match_var.set("None")
        else:
            self._layout_metadata_spec_match_var.set(
                "DEFAULT" if auto_meta and Path(auto_meta).resolve() == Path(meta_path).resolve() else "OK"
            )

        self._refresh_layout_keys()

    def _browse_layout_spec_file(self, *, kind: str) -> None:
        path = filedialog.askopenfilename(
            title=f"Select {kind} YAML",
            filetypes=(("YAML", "*.yaml *.yml"), ("All files", "*.*")),
        )
        if not path:
            return
        if kind == "info_spec":
            self._layout_info_spec_file_var.set(path)
        else:
            self._layout_metadata_spec_file_var.set(path)
        self._refresh_layout_spec_status()

    def _layout_builtin_info_spec_paths(self) -> tuple[Optional[str], Optional[str]]:
        try:
            module = importlib.import_module("brkraw.apps.loader.info.scan")
            scan_yaml = str(Path(cast(Any, module).__file__).with_name("scan.yaml"))
        except Exception:
            scan_yaml = None
        try:
            module = importlib.import_module("brkraw.apps.loader.info.study")
            study_yaml = str(Path(cast(Any, module).__file__).with_name("study.yaml"))
        except Exception:
            study_yaml = None
        return study_yaml, scan_yaml

    def _layout_override_info_spec_path(self) -> Optional[str]:
        file_path = (self._layout_info_spec_file_var.get() or "").strip()
        if file_path:
            return file_path
        name = (self._layout_info_spec_name_var.get() or "Default").strip()
        if name == "Default":
            return None
        return self._resolve_installed_spec_path(name=name, kind="info_spec")

    def _layout_override_metadata_spec_path(self) -> Optional[str]:
        file_path = (self._layout_metadata_spec_file_var.get() or "").strip()
        if file_path:
            return file_path
        name = (self._layout_metadata_spec_name_var.get() or "None").strip()
        if name == "None":
            return None
        return self._resolve_installed_spec_path(name=name, kind="metadata_spec")

    def _refresh_layout_keys(self) -> None:
        if self._layout_key_listbox is None or self._loader is None or self._scan is None:
            return
        scan_id = getattr(self._scan, "scan_id", None)
        if scan_id is None:
            return

        info_spec = self._layout_override_info_spec_path()
        metadata_spec = self._layout_override_metadata_spec_path()
        signature = (
            scan_id,
            self._current_reco_id,
            info_spec or "Default",
            (self._layout_info_spec_file_var.get() or "").strip(),
            metadata_spec or "None",
            (self._layout_metadata_spec_file_var.get() or "").strip(),
        )
        if self._layout_key_source_signature is None:
            self._layout_key_source_signature = signature
        elif self._layout_key_source_signature != signature:
            self._layout_key_source_signature = signature
            if not bool(self._use_layout_entries_var.get()):
                self._layout_template_var.set(config_core.layout_template(root=None) or "")

        try:
            info = layout_core.load_layout_info(
                self._loader,
                scan_id,
                context_map=None,
                root=resolve_root(None),
                reco_id=self._current_reco_id,
                override_info_spec=info_spec,
                override_metadata_spec=metadata_spec,
            )
        except Exception:
            info = {}

        keys = sorted(set(self._flatten_keys(info)) | {"scan_id", "reco_id"})
        previous_state: Optional[str] = None
        try:
            previous_state = str(self._layout_key_listbox.cget("state"))
            if previous_state == str(tk.DISABLED):
                self._layout_key_listbox.configure(state=tk.NORMAL)
        except Exception:
            previous_state = None

        self._layout_key_listbox.delete(0, tk.END)
        for key in keys:
            self._layout_key_listbox.insert(tk.END, key)

        if previous_state == str(tk.DISABLED):
            try:
                self._layout_key_listbox.configure(state=tk.DISABLED)
            except Exception:
                pass

        if hasattr(self, "_layout_keys_title"):
            study_yaml, scan_yaml = self._layout_builtin_info_spec_paths()
            if info_spec is None:
                src = "Default"
                if scan_yaml and study_yaml:
                    src = "Default (study.yaml + scan.yaml)"
            else:
                src = Path(info_spec).name
            self._layout_keys_title.set(f"Key (click to add) — {len(keys)} keys | {src}")

    def _flatten_keys(self, obj: Any, prefix: str = "") -> Iterable[str]:
        if isinstance(obj, Mapping):
            for k, v in obj.items():
                key = str(k)
                path = f"{prefix}.{key}" if prefix else key
                yield path
                yield from self._flatten_keys(v, path)
        elif isinstance(obj, list):
            for idx, v in enumerate(obj):
                path = f"{prefix}[{idx}]" if prefix else f"[{idx}]"
                yield path
                yield from self._flatten_keys(v, path)

    def _on_layout_key_double_click(self, *_: object) -> None:
        if self._layout_key_listbox is None:
            return
        selection = self._layout_key_listbox.curselection()
        if not selection:
            return
        key = str(self._layout_key_listbox.get(int(selection[0])))
        if not key:
            return
        if bool(self._use_layout_entries_var.get()):
            self._status_var.set("Template is disabled (using layout_entries).")
            return
        current = self._layout_template_var.get() or ""
        self._layout_template_var.set(f"{current}{{{key}}}")

    def _on_layout_key_click(self, *_: object) -> None:
        self._on_layout_key_double_click()

    def _on_layout_key_mouse_down(self, *_: object) -> Optional[str]:
        if bool(self._use_layout_entries_var.get()):
            return "break"
        return None

    def _convert_subject_overrides(self) -> tuple[Optional[SubjectType], Optional[SubjectPose]]:
        if self._convert_space_var.get() != "subject_ras":
            return None, None
        if self._convert_use_viewer_pose_var.get():
            subject_type = self._cast_subject_type((self._subject_type_var.get() or "").strip())
            subject_pose = self._cast_subject_pose(
                f"{(self._pose_primary_var.get() or '').strip()}_{(self._pose_secondary_var.get() or '').strip()}"
            )
            return subject_type, subject_pose

        subject_type = self._cast_subject_type((self._convert_subject_type_var.get() or "").strip())
        subject_pose = self._cast_subject_pose(
            f"{(self._convert_pose_primary_var.get() or '').strip()}_{(self._convert_pose_secondary_var.get() or '').strip()}"
        )
        return subject_type, subject_pose

    def _estimate_slicepack_count(self) -> int:
        if self._scan is None or self._current_reco_id is None:
            return 0
        try:
            dataobj = self._scan.get_dataobj(reco_id=self._current_reco_id)
        except Exception:
            return 0
        if isinstance(dataobj, tuple):
            return len(dataobj)
        return 1 if dataobj is not None else 0

    def _planned_output_paths(self) -> list[Path]:
        if self._scan is None or self._current_reco_id is None:
            return []
        scan_id = getattr(self._scan, "scan_id", None)
        if scan_id is None:
            return []

        output_dir = self._output_dir_var.get().strip() or "output"
        output_path = Path(output_dir)

        count = self._estimate_slicepack_count()
        if count <= 0:
            return []

        root = resolve_root(None)
        layout_entries = config_core.layout_entries(root=root)
        layout_template = config_core.layout_template(root=root)

        template_override = (self._layout_template_var.get() or "").strip() or None
        use_entries = bool(self._use_layout_entries_var.get())
        if not use_entries and template_override:
            layout_template = self._render_template_with_context(template_override, reco_id=self._current_reco_id)
            layout_entries = None

        slicepack_suffix = (self._slicepack_suffix_var.get() or "").strip() or config_core.output_slicepack_suffix(
            root=root
        )

        info_spec_path = self._layout_override_info_spec_path()
        metadata_spec_path = self._layout_override_metadata_spec_path()

        try:
            base_name = layout_core.render_layout(
                self._loader,
                scan_id,
                layout_entries=layout_entries,
                layout_template=layout_template,
                context_map=None,
                root=root,
                reco_id=self._current_reco_id,
                override_info_spec=info_spec_path,
                override_metadata_spec=metadata_spec_path,
            )
            info = layout_core.load_layout_info(
                self._loader,
                scan_id,
                context_map=None,
                root=root,
                reco_id=self._current_reco_id,
                override_info_spec=info_spec_path,
                override_metadata_spec=metadata_spec_path,
            )
        except Exception:
            base_name = f"scan-{scan_id}"
            info = {}

        suffixes = (
            layout_core.render_slicepack_suffixes(info, count=count, template=slicepack_suffix) if count > 1 else [""]
        )

        paths: list[Path] = []
        for idx in range(count):
            suffix = suffixes[idx] if idx < len(suffixes) else f"_slpack{idx + 1}"
            filename = f"{base_name}{suffix}.nii.gz"
            paths.append(output_path / filename)
        return paths

    def _render_template_with_context(self, template: str, *, reco_id: Optional[int]) -> str:
        value = "" if reco_id is None else str(int(reco_id))
        for key in ("reco_id", "recoid", "RecoID"):
            template = template.replace(f"{{{key}}}", value)
        return template

    def _preview_convert_outputs(self) -> None:
        if self._scan is None or self._current_reco_id is None:
            self._set_convert_settings("No scan/reco selected.")
            self._set_convert_preview("")
            return
        scan_id = getattr(self._scan, "scan_id", None)
        if scan_id is None:
            self._set_convert_settings("Scan id unavailable.")
            self._set_convert_preview("")
            return

        space = self._convert_space_var.get()
        subject_type, subject_pose = self._convert_subject_overrides()

        planned = self._planned_output_paths()
        if not planned:
            self._set_convert_settings("No output planned (missing data or reco).")
            self._set_convert_preview("")
            return

        settings = {
            "scan_id": scan_id,
            "reco_id": self._current_reco_id,
            "space": space,
            "use_viewer_type_pose": bool(self._convert_use_viewer_pose_var.get()),
            "override_subject_type": str(subject_type) if subject_type is not None else None,
            "override_subject_pose": str(subject_pose) if subject_pose is not None else None,
            "use_layout_entries": bool(self._use_layout_entries_var.get()),
            "template": self._layout_template_var.get(),
            "slicepack_suffix": self._slicepack_suffix_var.get(),
            "layout_info_spec": self._layout_info_spec_name_var.get(),
            "layout_info_spec_file": self._layout_info_spec_file_var.get(),
            "layout_metadata_spec": self._layout_metadata_spec_name_var.get(),
            "layout_metadata_spec_file": self._layout_metadata_spec_file_var.get(),
        }
        self._set_convert_settings(pprint.pformat(settings, sort_dicts=False, width=120))
        self._set_convert_preview("\n".join(str(p) for p in planned))

    def _convert_current_scan(self) -> None:
        if self._loader is None or self._scan is None or self._current_reco_id is None:
            self._status_var.set("No scan selected.")
            return
        scan_id = getattr(self._scan, "scan_id", None)
        if scan_id is None:
            self._status_var.set("Scan id unavailable.")
            return

        planned = self._planned_output_paths()
        if not planned:
            self._status_var.set("No output planned.")
            return

        output_path = planned[0].parent
        output_path.mkdir(parents=True, exist_ok=True)

        subject_type, subject_pose = self._convert_subject_overrides()
        space = self._convert_space_var.get()

        try:
            nii = self._loader.convert(
                scan_id,
                reco_id=self._current_reco_id,
                format="nifti",
                space=cast(Any, space),
                override_subject_type=subject_type,
                override_subject_pose=subject_pose,
                hook_args_by_name=None,
            )
        except Exception as exc:
            self._set_convert_settings(f"Convert failed: {exc}")
            self._status_var.set("Conversion failed.")
            return

        if nii is None:
            self._status_var.set("No NIfTI output generated.")
            return
        nii_list = list(nii) if isinstance(nii, tuple) else [nii]
        if len(nii_list) != len(planned):
            planned = planned[: len(nii_list)]

        for dest, img in zip(planned, nii_list):
            try:
                img.to_filename(str(dest))
            except Exception as exc:
                self._set_convert_preview(f"Save failed: {exc}\n\nPath: {dest}")
                self._status_var.set("Save failed.")
                return
        self._status_var.set(f"Saved {len(nii_list)} file(s) to {output_path}")
