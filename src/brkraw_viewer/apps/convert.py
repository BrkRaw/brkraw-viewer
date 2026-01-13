from __future__ import annotations

import importlib
import tkinter as tk
import logging
import json
import yaml
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Any, Iterable, Mapping, Optional, cast

from brkraw.core import config as config_core
from brkraw.core import layout as layout_core
from brkraw.core.config import resolve_root
from brkraw.resolver import affine as affine_resolver
from brkraw.resolver.affine import SubjectPose, SubjectType
from brkraw.specs import remapper as remapper_core

logger = logging.getLogger("brkraw.viewer")

class ConvertTabMixin:
    # The concrete host (ViewerApp) provides these attributes/methods.
    # They are declared here to keep type checkers (pyright/pylance) happy.
    _loader: Any
    _scan: Any
    _current_reco_id: Optional[int]
    _status_var: tk.StringVar

    _use_layout_entries_var: tk.BooleanVar
    _layout_source_var: tk.StringVar
    _layout_auto_var: tk.BooleanVar
    _layout_template_var: tk.StringVar
    _layout_template_entry: ttk.Entry
    _layout_template_combo: Optional[ttk.Combobox]
    _layout_source_combo: Optional[ttk.Combobox]
    _layout_auto_check: Optional[ttk.Checkbutton]
    _slicepack_suffix_var: tk.StringVar
    _output_dir_var: tk.StringVar
    _layout_rule_display_var: tk.StringVar
    _layout_info_spec_display_var: tk.StringVar
    _layout_metadata_spec_display_var: tk.StringVar
    _layout_context_map_display_var: tk.StringVar
    _layout_template_manual: str

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
    _layout_key_add_button: Optional[ttk.Button]
    _layout_key_remove_button: Optional[ttk.Button]
    _addon_context_map_var: tk.StringVar
    _addon_output_payload: Optional[Any]
    _convert_sidecar_var: tk.BooleanVar
    _convert_sidecar_format_var: tk.StringVar
    _sidecar_format_frame: ttk.Frame
    _rule_name_var: tk.StringVar

    def _resolve_spec_path(self) -> Optional[str]: ...
    def _spec_record_from_path(self, path: Optional[str]) -> dict[str, Any]: ...
    def _auto_applied_rule(self) -> Optional[dict[str, Any]]: ...
    # def _on_layout_template_change(self) -> None: ...

    _convert_space_var: tk.StringVar
    _convert_use_viewer_pose_var: tk.BooleanVar
    _convert_flip_x_var: tk.BooleanVar
    _convert_flip_y_var: tk.BooleanVar
    _convert_flip_z_var: tk.BooleanVar
    _convert_subject_type_var: tk.StringVar
    _convert_pose_primary_var: tk.StringVar
    _convert_pose_secondary_var: tk.StringVar
    _convert_subject_type_combo: ttk.Combobox
    _convert_pose_primary_combo: ttk.Combobox
    _convert_pose_secondary_combo: ttk.Combobox
    _convert_flip_x_check: ttk.Checkbutton
    _convert_flip_y_check: ttk.Checkbutton
    _convert_flip_z_check: ttk.Checkbutton
    _convert_settings_text: Optional[tk.Text]
    _convert_preview_text: Optional[tk.Text]

    _subject_type_var: tk.StringVar
    _pose_primary_var: tk.StringVar
    _pose_secondary_var: tk.StringVar
    _affine_flip_x_var: tk.BooleanVar
    _affine_flip_y_var: tk.BooleanVar
    _affine_flip_z_var: tk.BooleanVar

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

        ttk.Label(output_layout, text="Layout source").grid(row=0, column=0, sticky="w")
        self._layout_source_combo = ttk.Combobox(
            output_layout,
            textvariable=self._layout_source_var,
            values=tuple(self._layout_source_choices()),
            state="readonly",
        )
        self._layout_source_combo.grid(row=0, column=1, sticky="ew")
        self._layout_source_combo.bind("<<ComboboxSelected>>", lambda *_: self._update_layout_controls())
        self._layout_auto_check = ttk.Checkbutton(
            output_layout,
            text="Auto",
            variable=self._layout_auto_var,
            command=self._update_layout_controls,
        )
        self._layout_auto_check.grid(row=0, column=2, sticky="e")

        ttk.Label(output_layout, text="Rule").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(output_layout, textvariable=self._layout_rule_display_var, state="readonly").grid(
            row=1, column=1, sticky="ew", pady=(8, 0)
        )

        ttk.Label(output_layout, text="Info spec").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(output_layout, textvariable=self._layout_info_spec_display_var, state="readonly").grid(
            row=2, column=1, sticky="ew", pady=(6, 0)
        )

        ttk.Label(output_layout, text="Metadata spec").grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(output_layout, textvariable=self._layout_metadata_spec_display_var, state="readonly").grid(
            row=3, column=1, sticky="ew", pady=(6, 0)
        )

        ttk.Label(output_layout, text="Context map").grid(row=4, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(output_layout, textvariable=self._layout_context_map_display_var, state="readonly").grid(
            row=4, column=1, sticky="ew", pady=(6, 0)
        )

        ttk.Label(output_layout, text="Template").grid(row=5, column=0, sticky="w", pady=(10, 0))
        self._layout_template_entry = ttk.Entry(output_layout, textvariable=self._layout_template_var)
        self._layout_template_entry.grid(row=5, column=1, sticky="ew", pady=(10, 0))
        self._layout_template_combo = None

        ttk.Label(output_layout, text="Slicepack suffix").grid(row=6, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(output_layout, textvariable=self._slicepack_suffix_var, state="readonly").grid(
            row=6, column=1, sticky="ew", pady=(6, 0)
        )

        output_layout.columnconfigure(3, weight=0)
        keys_frame = ttk.LabelFrame(output_layout, text="Keys", padding=(6, 6))
        keys_frame.grid(row=0, column=3, rowspan=7, sticky="nsew", padx=(10, 0))
        keys_frame.columnconfigure(0, weight=1)
        keys_frame.rowconfigure(1, weight=1)
        self._layout_keys_title = tk.StringVar(value="Key (select then +)")
        ttk.Label(keys_frame, textvariable=self._layout_keys_title).grid(row=0, column=0, sticky="w")
        self._layout_key_listbox = tk.Listbox(keys_frame, width=28, height=10, exportselection=False)
        self._layout_key_listbox.grid(row=1, column=0, sticky="nsew")
        keys_scroll = ttk.Scrollbar(keys_frame, orient="vertical", command=self._layout_key_listbox.yview)
        keys_scroll.grid(row=1, column=1, sticky="ns")
        self._layout_key_listbox.configure(yscrollcommand=keys_scroll.set)
        self._layout_key_listbox.bind("<Button-1>", self._on_layout_key_mouse_down)
        self._layout_key_listbox.bind("<ButtonRelease-1>", self._on_layout_key_click)
        self._layout_key_listbox.bind("<Double-Button-1>", self._on_layout_key_double_click)

        self._layout_key_add_button = None
        self._layout_key_remove_button = None
        key_buttons = ttk.Frame(keys_frame)
        key_buttons.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        key_buttons.columnconfigure(0, weight=1)
        key_buttons.columnconfigure(1, weight=1)
        self._layout_key_add_button = ttk.Button(key_buttons, text="+", command=self._add_selected_layout_key)
        self._layout_key_add_button.grid(row=0, column=0, sticky="ew")
        self._layout_key_remove_button = ttk.Button(key_buttons, text="-", command=self._remove_selected_layout_key)
        self._layout_key_remove_button.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        convert_frame = ttk.Frame(layout_tab, padding=(8, 8))
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

        sidecar_row = ttk.Frame(convert_left)
        sidecar_row.grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 6))
        ttk.Checkbutton(
            sidecar_row,
            text="Sidecar",
            variable=self._convert_sidecar_var,
            command=self._update_sidecar_controls,
        ).pack(side=tk.LEFT)
        self._sidecar_format_frame = ttk.Frame(sidecar_row)
        self._sidecar_format_frame.pack(side=tk.LEFT, padx=(12, 0))
        ttk.Label(self._sidecar_format_frame, text="Format").pack(side=tk.LEFT)
        ttk.Radiobutton(
            self._sidecar_format_frame,
            text="JSON",
            value="json",
            variable=self._convert_sidecar_format_var,
        ).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Radiobutton(
            self._sidecar_format_frame,
            text="YAML",
            value="yaml",
            variable=self._convert_sidecar_format_var,
        ).pack(side=tk.LEFT, padx=(6, 0))

        ttk.Label(convert_left, text="Space").grid(row=2, column=0, sticky="w")
        convert_space = ttk.Combobox(
            convert_left,
            textvariable=self._convert_space_var,
            values=("raw", "scanner", "subject_ras"),
            state="readonly",
            width=12,
        )
        convert_space.grid(row=2, column=1, sticky="w")
        convert_space.bind("<<ComboboxSelected>>", lambda *_: self._update_convert_space_controls())

        ttk.Checkbutton(
            convert_left,
            text="Use Viewer orientation",
            variable=self._convert_use_viewer_pose_var,
            command=self._update_convert_space_controls,
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

        convert_subject_row = ttk.Frame(convert_left)
        convert_subject_row.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(6, 0))
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

        convert_flip_row = ttk.Frame(convert_left)
        convert_flip_row.grid(row=5, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Label(convert_flip_row, text="Flip").pack(side=tk.LEFT)
        self._convert_flip_x_check = ttk.Checkbutton(
            convert_flip_row,
            text="X",
            variable=self._convert_flip_x_var,
        )
        self._convert_flip_x_check.pack(side=tk.LEFT, padx=(8, 0))
        self._convert_flip_y_check = ttk.Checkbutton(
            convert_flip_row,
            text="Y",
            variable=self._convert_flip_y_var,
        )
        self._convert_flip_y_check.pack(side=tk.LEFT, padx=(6, 0))
        self._convert_flip_z_check = ttk.Checkbutton(
            convert_flip_row,
            text="Z",
            variable=self._convert_flip_z_var,
        )
        self._convert_flip_z_check.pack(side=tk.LEFT, padx=(6, 0))

        actions = ttk.Frame(convert_left)
        actions.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        ttk.Button(actions, text="Preview Outputs", command=self._preview_convert_outputs).grid(row=0, column=0, sticky="ew")
        ttk.Button(actions, text="Convert", command=self._convert_current_scan).grid(row=0, column=1, sticky="ew", padx=(8, 0))

        self._update_sidecar_controls()

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
            self._convert_flip_x_var.set(bool(self._affine_flip_x_var.get()))
            self._convert_flip_y_var.set(bool(self._affine_flip_y_var.get()))
            self._convert_flip_z_var.set(bool(self._affine_flip_z_var.get()))
            self._convert_flip_x_check.configure(state="disabled")
            self._convert_flip_y_check.configure(state="disabled")
            self._convert_flip_z_check.configure(state="disabled")
            return
        state = "readonly" if enabled else "disabled"
        self._convert_subject_type_combo.configure(state=state)
        self._convert_pose_primary_combo.configure(state=state)
        self._convert_pose_secondary_combo.configure(state=state)
        flip_state = "normal" if enabled else "disabled"
        self._convert_flip_x_check.configure(state=flip_state)
        self._convert_flip_y_check.configure(state=flip_state)
        self._convert_flip_z_check.configure(state=flip_state)

    def _update_layout_controls(self) -> None:
        self._sync_layout_source_state()
        self._refresh_layout_display()
        template_enabled = self._layout_template_enabled()
        button_state = "normal" if template_enabled else "disabled"
        for btn in (getattr(self, "_layout_key_add_button", None), getattr(self, "_layout_key_remove_button", None)):
            if btn is None:
                continue
            try:
                btn.configure(state=button_state)
            except Exception:
                pass
        try:
            if template_enabled:
                self._layout_template_entry.state(["!disabled"])
            else:
                self._layout_template_entry.state(["disabled"])
        except Exception:
            pass
        if not template_enabled and self._layout_key_listbox is not None:
            self._layout_key_listbox.selection_clear(0, tk.END)
        if self._layout_key_listbox is not None:
            try:
                self._layout_key_listbox.configure(state=tk.NORMAL if template_enabled else tk.DISABLED)
            except Exception:
                pass
        self._refresh_layout_keys()

    def _update_sidecar_controls(self) -> None:
        enable = bool(self._convert_sidecar_var.get())
        for child in getattr(self, "_sidecar_format_frame", ttk.Frame()).winfo_children():
            try:
                state_fn = getattr(child, "state", None)
                if callable(state_fn):
                    state_fn(["!disabled"] if enable else ["disabled"])
            except Exception:
                pass

    def _layout_source_choices(self) -> list[str]:
        return ["GUI template", "Context map", "Config"]

    def _layout_source_mode(self) -> str:
        if bool(self._layout_auto_var.get()):
            return "auto"
        value = (self._layout_source_var.get() or "").strip()
        if value not in self._layout_source_choices():
            return "Config"
        return value

    def _has_context_map(self) -> bool:
        path = (self._addon_context_map_var.get() or "").strip()
        return bool(path) and Path(path).exists()

    def _sync_layout_source_state(self) -> None:
        if self._layout_source_combo is None:
            return
        if bool(self._layout_auto_var.get()):
            self._layout_source_combo.configure(state="disabled")
            return
        self._layout_source_combo.configure(state="readonly")
        if self._layout_source_var.get() not in self._layout_source_choices():
            self._layout_source_var.set("Config")
        if not self._has_context_map() and self._layout_source_var.get() == "Context map":
            self._layout_source_var.set("Config")

    def _layout_template_enabled(self) -> bool:
        if bool(self._layout_auto_var.get()):
            return False
        return self._layout_source_var.get() == "GUI template"

    def _on_layout_template_change(self) -> None:
        if not bool(self._layout_auto_var.get()):
            self._layout_template_manual = (self._layout_template_var.get() or "")

    def _refresh_layout_display(self) -> None:
        rule_display = ""
        try:
            rule_name = (self._rule_name_var.get() or "").strip()
            if rule_name and rule_name != "None":
                rule_display = rule_name
        except Exception:
            rule_display = ""
        if not rule_display:
            auto_rule = self._auto_applied_rule()
            if auto_rule is not None:
                rule_display = str(auto_rule.get("name") or "")
        self._layout_rule_display_var.set(rule_display)

        info_spec = ""
        meta_spec = ""
        spec_path = None
        try:
            spec_path = self._resolve_spec_path()
        except Exception:
            spec_path = None
        if spec_path:
            record = self._spec_record_from_path(spec_path)
            category = record.get("category")
            if category == "metadata_spec":
                meta_spec = spec_path
            else:
                info_spec = spec_path
        if not info_spec:
            info_spec = self._auto_selected_spec_path("info_spec") or ""
        if not meta_spec:
            meta_spec = self._auto_selected_spec_path("metadata_spec") or ""
        if not info_spec:
            info_spec = "Default"
        if not meta_spec:
            meta_spec = "None"
        self._layout_info_spec_display_var.set(info_spec)
        self._layout_metadata_spec_display_var.set(meta_spec)

        context_map = (self._addon_context_map_var.get() or "").strip()
        self._layout_context_map_display_var.set(context_map)

        if info_spec and info_spec != "Default":
            self._layout_info_spec_file_var.set(info_spec)
        else:
            self._layout_info_spec_file_var.set("")
        if meta_spec and meta_spec != "None":
            self._layout_metadata_spec_file_var.set(meta_spec)
        else:
            self._layout_metadata_spec_file_var.set("")

        if bool(self._layout_auto_var.get()):
            active_template = self._current_layout_template_from_sources()
            self._layout_template_var.set(active_template)
            self._slicepack_suffix_var.set(self._current_slicepack_suffix())
            self._layout_source_var.set(self._auto_layout_source())
        else:
            if self._layout_template_manual:
                if (self._layout_template_var.get() or "") != self._layout_template_manual:
                    self._layout_template_var.set(self._layout_template_manual)
            self._slicepack_suffix_var.set(self._current_slicepack_suffix())

    def _current_layout_template_from_sources(self) -> str:
        layout_template, _, _, _ = self._resolve_layout_sources(reco_id=self._current_reco_id)
        return layout_template or ""

    def _auto_layout_source(self) -> str:
        if self._layout_template_manual:
            return "GUI template"
        if self._context_map_has_layout():
            return "Context map"
        return "Config"

    def _context_map_has_layout(self) -> bool:
        if not self._has_context_map():
            return False
        path = (self._addon_context_map_var.get() or "").strip()
        try:
            meta = remapper_core.load_context_map_meta(path)
        except Exception:
            return False
        if not isinstance(meta, dict):
            return False
        layout_template = meta.get("layout_template")
        if isinstance(layout_template, str) and layout_template.strip():
            return True
        entries = meta.get("layout_entries") or meta.get("layout_fields")
        return isinstance(entries, list) and len(entries) > 0

    def _current_slicepack_suffix(self) -> str:
        _, _, slicepack_suffix, _ = self._resolve_layout_sources(reco_id=self._current_reco_id)
        return slicepack_suffix or ""

    def _config_layout_templates(self) -> list[str]:
        templates: list[str] = []
        config = config_core.load_config(root=None) or {}
        output_cfg = config.get("output", {})
        if isinstance(output_cfg, dict):
            raw_list = output_cfg.get("layout_templates", [])
            if isinstance(raw_list, list):
                for item in raw_list:
                    if isinstance(item, str) and item.strip():
                        templates.append(item)
                    elif isinstance(item, dict):
                        value = item.get("template") or item.get("value")
                        if isinstance(value, str) and value.strip():
                            templates.append(value)
        default_template = config_core.layout_template(root=None)
        if isinstance(default_template, str) and default_template.strip():
            if default_template not in templates:
                templates.insert(0, default_template)
        return templates

    def _refresh_layout_spec_selectors(self) -> None:
        return

    def _refresh_layout_spec_status(self) -> None:
        return

    def _browse_layout_spec_file(self, *, kind: str) -> None:
        return

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

    def _layout_info_spec_path(self) -> Optional[str]:
        file_path = (self._layout_info_spec_file_var.get() or "").strip()
        if file_path:
            return file_path
        return None

    def _layout_metadata_spec_path(self) -> Optional[str]:
        file_path = (self._layout_metadata_spec_file_var.get() or "").strip()
        if file_path:
            return file_path
        return None

    def _refresh_layout_keys(self) -> None:
        if self._layout_key_listbox is None or self._loader is None or self._scan is None:
            return
        scan_id = getattr(self._scan, "scan_id", None)
        if scan_id is None:
            return

        info_spec = self._layout_info_spec_path()
        metadata_spec = self._layout_metadata_spec_path()
        source_mode = self._layout_source_mode()
        signature = (
            scan_id,
            self._current_reco_id,
            info_spec or "Default",
            (self._layout_info_spec_file_var.get() or "").strip(),
            metadata_spec or "None",
            (self._layout_metadata_spec_file_var.get() or "").strip(),
            source_mode,
            bool(self._layout_auto_var.get()),
            (self._layout_template_var.get() or "").strip(),
            (self._addon_context_map_var.get() or "").strip(),
        )
        if self._layout_key_source_signature is None:
            self._layout_key_source_signature = signature
        elif self._layout_key_source_signature != signature:
            self._layout_key_source_signature = signature
            if self._layout_template_enabled() and not (self._layout_template_var.get() or "").strip():
                self._layout_template_var.set(config_core.layout_template(root=None) or "")

        context_map = self._current_context_map_path()
        try:
            info = layout_core.load_layout_info(
                self._loader,
                scan_id,
                context_map=context_map,
                root=resolve_root(None),
                reco_id=self._current_reco_id,
                override_info_spec=info_spec,
                override_metadata_spec=metadata_spec,
            )
        except Exception:
            info = {}

        # BrkRaw built-in layout keys should always be available in the picker.
        # Keep this list focused on scalar-friendly tags (for filenames).
        keys = sorted(set(self._flatten_keys(info)) | {"scan_id", "reco_id", "Counter"})
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
                if isinstance(v, (Mapping, list, tuple)):
                    continue
                yield path

    def _selected_layout_key(self) -> Optional[str]:
        if self._layout_key_listbox is None:
            return None
        selection = self._layout_key_listbox.curselection()
        if not selection:
            return None
        key = str(self._layout_key_listbox.get(int(selection[0])))
        if not key:
            return None
        return key

    def _add_selected_layout_key(self) -> None:
        key = self._selected_layout_key()
        if not key:
            return
        if not self._layout_template_enabled():
            self._status_var.set("Template is disabled for the current layout source.")
            return
        current = self._layout_template_var.get() or ""
        self._layout_template_var.set(f"{current}{{{key}}}")

    def _remove_selected_layout_key(self) -> None:
        key = self._selected_layout_key()
        if not key:
            return
        if not self._layout_template_enabled():
            self._status_var.set("Template is disabled for the current layout source.")
            return
        token = f"{{{key}}}"
        current = self._layout_template_var.get() or ""
        idx = current.rfind(token)
        if idx < 0:
            return
        self._layout_template_var.set(current[:idx] + current[idx + len(token) :])

    def _on_layout_key_double_click(self, *_: object) -> None:
        # Selection only. Use +/- buttons to edit the template.
        return

    def _on_layout_key_click(self, *_: object) -> None:
        # Selection only. Use +/- buttons to edit the template.
        return

    def _on_layout_key_mouse_down(self, *_: object) -> Optional[str]:
        if not self._layout_template_enabled():
            return "break"
        return None

    def _current_context_map_path(self) -> Optional[str]:
        if not self._has_context_map():
            return None
        path = (self._addon_context_map_var.get() or "").strip()
        mode = self._layout_source_mode()
        if mode == "Context map":
            return path
        if mode == "auto":
            gui_template = (self._layout_template_var.get() or "").strip()
            if gui_template:
                return None
            return path
        return None

    def _resolve_layout_sources(
        self,
        *,
        reco_id: Optional[int],
    ) -> tuple[Optional[str], Optional[list], str, Optional[str]]:
        root = resolve_root(None)
        layout_entries = config_core.layout_entries(root=root)
        layout_template = config_core.layout_template(root=root)
        slicepack_suffix = config_core.output_slicepack_suffix(root=root)

        mode = self._layout_source_mode()
        if mode == "auto":
            gui_template = (self._layout_template_manual or "").strip()
        else:
            gui_template = (self._layout_template_var.get() or "").strip()
        gui_suffix = (self._slicepack_suffix_var.get() or "").strip()
        context_map_path: Optional[str] = None

        if mode == "GUI template":
            if gui_template:
                layout_template = self._render_template_with_context(gui_template, reco_id=reco_id)
                layout_entries = None
                if gui_suffix:
                    slicepack_suffix = gui_suffix
            return layout_template, layout_entries, slicepack_suffix, None

        if mode == "Context map":
            context_map_path = self._current_context_map_path()
            if context_map_path:
                try:
                    meta = remapper_core.load_context_map_meta(context_map_path)
                except Exception:
                    meta = {}
                if isinstance(meta, dict):
                    map_suffix = meta.get("slicepack_suffix")
                    map_template = meta.get("layout_template")
                    map_entries = meta.get("layout_entries") or meta.get("layout_fields")
                    if isinstance(map_suffix, str) and map_suffix.strip():
                        slicepack_suffix = map_suffix
                    if isinstance(map_template, str) and map_template.strip():
                        layout_template = map_template
                        layout_entries = None
                    elif isinstance(map_entries, list):
                        layout_entries = map_entries
                        layout_template = None
            return layout_template, layout_entries, slicepack_suffix, context_map_path

        if mode == "Config":
            return layout_template, layout_entries, slicepack_suffix, None

        if gui_template:
            layout_template = self._render_template_with_context(gui_template, reco_id=reco_id)
            layout_entries = None
            if gui_suffix:
                slicepack_suffix = gui_suffix
            return layout_template, layout_entries, slicepack_suffix, None

        context_map_path = self._current_context_map_path()
        if context_map_path:
            try:
                meta = remapper_core.load_context_map_meta(context_map_path)
            except Exception:
                meta = {}
            if isinstance(meta, dict):
                map_suffix = meta.get("slicepack_suffix")
                map_template = meta.get("layout_template")
                map_entries = meta.get("layout_entries") or meta.get("layout_fields")
                if isinstance(map_suffix, str) and map_suffix.strip():
                    slicepack_suffix = map_suffix
                if isinstance(map_template, str) and map_template.strip():
                    layout_template = map_template
                    layout_entries = None
                elif isinstance(map_entries, list):
                    layout_entries = map_entries
                    layout_template = None
            return layout_template, layout_entries, slicepack_suffix, context_map_path

        return layout_template, layout_entries, slicepack_suffix, None

    def _layout_entries_active(self) -> bool:
        layout_template, layout_entries, _, _ = self._resolve_layout_sources(reco_id=self._current_reco_id)
        return layout_template is None and bool(layout_entries)

    def _convert_subject_orientation(self) -> tuple[Optional[SubjectType], Optional[SubjectPose]]:
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

    def _convert_flip_settings(self) -> tuple[bool, bool, bool]:
        if self._convert_space_var.get() != "subject_ras":
            return False, False, False
        if self._convert_use_viewer_pose_var.get():
            return (
                bool(self._affine_flip_x_var.get()),
                bool(self._affine_flip_y_var.get()),
                bool(self._affine_flip_z_var.get()),
            )
        return (
            bool(self._convert_flip_x_var.get()),
            bool(self._convert_flip_y_var.get()),
            bool(self._convert_flip_z_var.get()),
        )

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

    _COUNTER_SENTINEL = 987654321
    _COUNTER_PLACEHOLDER = "<N>"

    def _planned_output_paths(self, *, preview: bool, count: Optional[int] = None) -> list[Path]:
        if self._scan is None or self._current_reco_id is None:
            return []
        scan_id = getattr(self._scan, "scan_id", None)
        if scan_id is None:
            return []

        output_dir = self._output_dir_var.get().strip() or "output"
        output_path = Path(output_dir)

        if count is None:
            count = self._estimate_slicepack_count()
        if int(count) <= 0:
            return []
        count = int(count)

        layout_template, layout_entries, slicepack_suffix, context_map = self._resolve_layout_sources(
            reco_id=self._current_reco_id
        )

        info_spec_path = self._layout_info_spec_path()
        metadata_spec_path = self._layout_metadata_spec_path()
        root = resolve_root(None)

        try:
            info = layout_core.load_layout_info(
                self._loader,
                scan_id,
                context_map=context_map,
                root=root,
                reco_id=self._current_reco_id,
                override_info_spec=info_spec_path,
                override_metadata_spec=metadata_spec_path,
            )
        except Exception:
            info = {}

        counter_enabled = self._uses_counter_tag(
            layout_template=layout_template,
            layout_entries=layout_entries,
        )
        counter_preview: Optional[int] = self._COUNTER_SENTINEL if (preview and counter_enabled) else None

        reserved: set[Path] = set()
        base_name_base: Optional[str] = None
        for attempt in range(1, 1000):
            counter = attempt if (counter_enabled and not preview) else counter_preview
            try:
                base_name = layout_core.render_layout(
                    self._loader,
                    scan_id,
                    layout_entries=layout_entries,
                    layout_template=layout_template,
                    context_map=context_map,
                    root=root,
                    reco_id=self._current_reco_id,
                    counter=counter,
                    override_info_spec=info_spec_path,
                    override_metadata_spec=metadata_spec_path,
                )
            except Exception:
                base_name = f"scan-{scan_id}"
            base_name = str(base_name)

            if base_name_base is None:
                base_name_base = base_name

            if not counter_enabled and attempt > 1:
                base_name = f"{base_name_base}_{attempt}"

            if count > 1:
                try:
                    suffixes = layout_core.render_slicepack_suffixes(
                        info,
                        count=count,
                        template=slicepack_suffix,
                        counter=counter,
                    )
                except Exception:
                    suffixes = [f"_slpack{i + 1}" for i in range(count)]
            else:
                suffixes = [""]

            if preview and counter_enabled:
                base_name = base_name.replace(str(self._COUNTER_SENTINEL), self._COUNTER_PLACEHOLDER)
                suffixes = [
                    suffix.replace(str(self._COUNTER_SENTINEL), self._COUNTER_PLACEHOLDER) for suffix in suffixes
                ]

            paths: list[Path] = []
            for idx in range(count):
                suffix = suffixes[idx] if idx < len(suffixes) else f"_slpack{idx + 1}"
                filename = f"{base_name}{suffix}.nii.gz"
                paths.append(output_path / filename)

            if preview:
                return paths
            if self._paths_collide(paths, reserved):
                continue
            return paths
        return []

    def _render_template_with_context(self, template: str, *, reco_id: Optional[int]) -> str:
        value = "" if reco_id is None else str(int(reco_id))
        for key in ("reco_id", "recoid", "RecoID"):
            template = template.replace(f"{{{key}}}", value)
        return template

    def _uses_counter_tag(self, *, layout_template: Optional[str], layout_entries: Optional[list]) -> bool:
        if isinstance(layout_template, str) and ("{Counter}" in layout_template or "{counter}" in layout_template):
            return True
        for entry in layout_entries or []:
            if not isinstance(entry, Mapping):
                continue
            key = entry.get("key")
            if isinstance(key, str) and key.strip() in {"Counter", "counter"}:
                return True
        return False

    @staticmethod
    def _paths_collide(paths: list[Path], reserved: set[Path]) -> bool:
        if len(set(paths)) != len(paths):
            return True
        for path in paths:
            if path in reserved:
                return True
            try:
                if path.exists():
                    return True
            except OSError:
                return True
        reserved.update(paths)
        return False

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
        subject_type, subject_pose = self._convert_subject_orientation()
        flip_x, flip_y, flip_z = self._convert_flip_settings()

        planned = self._planned_output_paths(preview=True)
        if not planned:
            self._set_convert_settings("No output planned (missing data or reco).")
            self._set_convert_preview("")
            return

        meta_text = self._preview_metadata_yaml(scan_id)
        self._set_convert_settings(meta_text)

        preview_list = list(planned)
        if self._convert_sidecar_var.get():
            preview_list.extend(self._planned_sidecar_paths(planned))
        self._set_convert_preview("\n".join(str(p) for p in preview_list))

    def _preview_metadata_yaml(self, scan_id: int) -> str:
        layout_template, layout_entries, _, context_map = self._resolve_layout_sources(reco_id=self._current_reco_id)
        info_spec_path = self._layout_info_spec_path()
        metadata_spec_path = self._layout_metadata_spec_path()
        try:
            info = layout_core.load_layout_info(
                self._loader,
                scan_id,
                context_map=context_map,
                root=resolve_root(None),
                reco_id=self._current_reco_id,
                override_info_spec=info_spec_path,
                override_metadata_spec=metadata_spec_path,
            )
        except Exception as exc:
            return f"Metadata preview failed:\n{exc}"
        return yaml.safe_dump(info, sort_keys=False)

    def _planned_sidecar_paths(self, planned: list[Path]) -> list[Path]:
        suffix = ".json" if self._convert_sidecar_format_var.get() == "json" else ".yaml"
        sidecars: list[Path] = []
        for path in planned:
            sidecar = path.with_suffix(suffix)
            if path.name.endswith(".nii.gz"):
                sidecar = path.with_name(path.name[:-7] + suffix)
            sidecars.append(sidecar)
        return sidecars

    def _convert_current_scan(self) -> None:
        if self._loader is None or self._scan is None or self._current_reco_id is None:
            self._status_var.set("No scan selected.")
            return
        scan_id = getattr(self._scan, "scan_id", None)
        if scan_id is None:
            self._status_var.set("Scan id unavailable.")
            return

        subject_type, subject_pose = self._convert_subject_orientation()
        space = self._convert_space_var.get()

        flip_x, flip_y, flip_z = self._convert_flip_settings()
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
        planned = self._planned_output_paths(preview=False, count=len(nii_list))
        if not planned:
            self._status_var.set("No output planned.")
            return
        if len(nii_list) != len(planned):
            planned = planned[: len(nii_list)]

        output_path = planned[0].parent
        output_path.mkdir(parents=True, exist_ok=True)

        sidecar_meta = self._build_sidecar_metadata(scan_id, self._current_reco_id)

        for dest, img in zip(planned, nii_list):
            if flip_x or flip_y or flip_z:
                try:
                    affine = affine_resolver.flip_affine(
                        img.affine,
                        flip_x=flip_x,
                        flip_y=flip_y,
                        flip_z=flip_z,
                    )
                    img.set_qform(affine, code=int(img.header.get("qform_code", 1) or 1))
                    img.set_sform(affine, code=int(img.header.get("sform_code", 1) or 1))
                except Exception:
                    pass
            try:
                img.to_filename(str(dest))
            except Exception as exc:
                self._set_convert_preview(f"Save failed: {exc}\n\nPath: {dest}")
                self._status_var.set("Save failed.")
                return
            if sidecar_meta:
                try:
                    self._write_sidecar(dest, sidecar_meta)
                except Exception as exc:
                    self._set_convert_preview(f"Sidecar failed: {exc}\n\nPath: {dest}")
                    self._status_var.set("Sidecar failed.")
                    return
        self._status_var.set(f"Saved {len(nii_list)} file(s) to {output_path}")
        logger.info("Saved %d file(s) to %s", len(nii_list), output_path)
        try:
            from tkinter import messagebox

            messagebox.showinfo("Convert", f"Saved {len(nii_list)} file(s).\n{output_path}")
        except Exception:
            pass

    def _build_sidecar_metadata(self, scan_id: int, reco_id: Optional[int]) -> Optional[Mapping[str, Any]]:
        if not bool(self._convert_sidecar_var.get()):
            return None
        get_metadata = getattr(self._loader, "get_metadata", None)
        if not callable(get_metadata):
            self._status_var.set("Metadata sidecar unavailable.")
            return None
        metadata_spec = self._layout_metadata_spec_path()
        try:
            meta = get_metadata(
                scan_id,
                reco_id=reco_id,
                spec=metadata_spec if metadata_spec else None,
                context_map=self._current_context_map_path(),
            )
        except Exception:
            return None
        if isinstance(meta, tuple) and meta:
            meta = meta[0]
        return meta if isinstance(meta, Mapping) else None

    def _write_sidecar(self, path: Path, meta: Mapping[str, Any]) -> None:
        payload = dict(meta)
        suffix = ".json" if self._convert_sidecar_format_var.get() == "json" else ".yaml"
        sidecar = path.with_suffix(suffix)
        if path.name.endswith(".nii.gz"):
            sidecar = path.with_name(path.name[:-7] + suffix)
        if suffix == ".yaml":
            sidecar.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        else:
            sidecar.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")
