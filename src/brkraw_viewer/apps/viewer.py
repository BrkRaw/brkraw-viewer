from __future__ import annotations

import logging
from collections import OrderedDict
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple, cast, List, Callable, Protocol
import datetime as dt
from pathlib import Path
import sys
import threading
import time
import json

import numpy as np
import pprint
import yaml

from brkraw.apps.loader import BrukerLoader
from brkraw.apps.loader.types import StudyLoader
from brkraw.resolver import affine as affine_resolver
from brkraw.resolver.affine import SubjectPose, SubjectType
from brkraw.apps.loader import info as info_resolver
from brkraw.core import config as config_core
from brkraw.core import layout as layout_core
from brkraw.core.config import resolve_root
from brkraw.specs import hook as converter_core
from brkraw.specs.rules import load_rules, select_rule_use
from brkraw.apps import addon as addon_app
from ..utils.orientation import reorient_to_ras
from ..frames.viewer_canvas import OrthogonalCanvas
from .config import ConfigTabMixin
from .convert import ConvertTabMixin
from ..frames.viewer_config import load_viewer_config, registry_columns, save_viewer_config, default_viewer_config
from ..registry import (
    registry_status,
    register_paths,
    unregister_paths,
    resolve_entry_value,
    load_registry,
    normalize_path,
)
from .hooks import load_viewer_hooks

ScanLike = Any

WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 760

logger = logging.getLogger("brkraw.viewer")


class ViewerRenderer(Protocol):
    def set_click_callback(self, callback: Optional[Callable[[str, int, int], None]]) -> None:
        ...

    def set_zoom_callback(self, callback: Optional[Callable[[int], None]]) -> None:
        ...

    def show_message_on(self, view: str, message: str, *, is_error: bool = False) -> None:
        ...

    def show_message(self, message: str, *, is_error: bool = False) -> None:
        ...

    def render_views(
        self,
        views: Dict[str, Tuple[np.ndarray, Tuple[float, float]]],
        titles: Dict[str, str],
        *,
        crosshair: Optional[Dict[str, Tuple[int, int]]] = None,
        show_crosshair: bool = False,
    ) -> None:
        ...


class _Tooltip:
    def __init__(self, widget: tk.Widget, text_func: Callable[[], str]) -> None:
        self._widget = widget
        self._text_func = text_func
        self._tip: Optional[tk.Toplevel] = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, _event: tk.Event) -> None:
        text = self._text_func().strip()
        if not text:
            return
        if self._tip is not None:
            return
        tip = tk.Toplevel(self._widget)
        tip.wm_overrideredirect(True)
        tip.attributes("-topmost", True)
        label = tk.Label(tip, text=text, padx=6, pady=4, background="#ffffe0", relief="solid", borderwidth=1)
        label.pack()
        x = self._widget.winfo_rootx() + 10
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 6
        tip.wm_geometry(f"+{x}+{y}")
        self._tip = tip

    def _hide(self, _event: tk.Event) -> None:
        if self._tip is None:
            return
        self._tip.destroy()
        self._tip = None


class ViewerApp(ConvertTabMixin, ConfigTabMixin, tk.Tk):
    def __init__(
        self,
        *,
        path: Optional[str],
        scan_id: Optional[int],
        reco_id: Optional[int],
        info_spec: Optional[str],
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
        self._frame_index = 0
        self._current_reco_id: Optional[int] = None
        self._slicepack_data: Optional[Tuple[np.ndarray, ...]] = None
        self._slicepack_affines: Optional[Tuple[np.ndarray, ...]] = None
        self._data_cache: "OrderedDict[Tuple[int, int], Any]" = OrderedDict()
        viewer_cfg = load_viewer_config()
        cache_cfg = viewer_cfg.get("cache", {}) if isinstance(viewer_cfg, dict) else {}
        self._cache_enabled = bool(cache_cfg.get("enabled", True))
        self._cache_prompt_on_close = bool(cache_cfg.get("prompt_on_close", True))
        max_items_raw = cache_cfg.get("max_items", None)
        if isinstance(max_items_raw, bool):
            self._cache_max_items = None
        elif isinstance(max_items_raw, (int, float)):
            self._cache_max_items = int(max_items_raw)
        elif isinstance(max_items_raw, str) and max_items_raw.strip().isdigit():
            self._cache_max_items = int(max_items_raw.strip())
        else:
            self._cache_max_items = None
        if self._cache_max_items is not None and self._cache_max_items < 0:
            self._cache_max_items = None
        self._current_subject_type: Optional[str] = None
        self._current_subject_pose: Optional[str] = None
        self._view_error: Optional[str] = None
        self._extra_dim_vars: list[tk.IntVar] = []
        self._extra_dim_scales: list[tk.Scale] = []
        self._viewer_hook_enabled_var = tk.BooleanVar(value=False)
        self._viewer_hook_name_var = tk.StringVar(value="")
        self._viewer_hook_frame: Optional[ttk.Frame] = None

        self._path_var = tk.StringVar(value=path or "")
        self._x_var = tk.IntVar(value=0)
        self._y_var = tk.IntVar(value=0)
        self._z_var = tk.IntVar(value=0)
        self._affine_flip_x_var = tk.BooleanVar(value=False)
        self._affine_flip_y_var = tk.BooleanVar(value=False)
        self._affine_flip_z_var = tk.BooleanVar(value=False)
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
        self._viewer_hook_check: Optional[ttk.Checkbutton] = None
        self._viewer_hook_label: Optional[ttk.Label] = None
        self._view_crop_origins: Dict[str, Tuple[int, int]] = {"xy": (0, 0), "xz": (0, 0), "zy": (0, 0)}

        self._subject_type_var = tk.StringVar(value="Biped")
        self._pose_primary_var = tk.StringVar(value="Head")
        self._pose_secondary_var = tk.StringVar(value="Supine")
        self._rule_text_var = tk.StringVar(value="Rule: auto")
        self._rule_enabled_var = tk.BooleanVar(value=True)
        self._rule_name_var = tk.StringVar(value="None")
        self._rule_match_var = tk.StringVar(value="None")
        self._addon_rule_file_var = tk.StringVar(value="")
        self._addon_rule_file_map: Dict[str, str] = {}
        self._addon_rule_display_by_path: Dict[str, str] = {}
        self._addon_rule_session_files: List[str] = []
        self._addon_rule_auto_var = tk.BooleanVar(value=True)
        self._addon_rule_category_var = tk.StringVar(value="None")
        self._addon_rule_desc_var = tk.StringVar(value="")
        self._addon_rule_status_var = tk.StringVar(value="skipped")
        self._addon_rule_choices: Dict[str, Dict[str, Any]] = {}

        self._addon_spec_auto_var = tk.BooleanVar(value=True)
        self._addon_spec_file_var = tk.StringVar(value="")
        self._addon_spec_name_var = tk.StringVar(value="None")
        self._addon_spec_desc_var = tk.StringVar(value="")
        self._addon_spec_status_var = tk.StringVar(value="skipped")
        self._addon_spec_choices: Dict[str, Dict[str, Any]] = {}
        self._addon_spec_display_by_path: Dict[str, str] = {}
        self._addon_spec_session_files: List[str] = []

        self._addon_context_map_var = tk.StringVar(value="")
        self._addon_context_status_var = tk.StringVar(value="skipped")
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
        self._layout_source_var = tk.StringVar(value="GUI template")
        self._layout_auto_var = tk.BooleanVar(value=True)
        self._use_context_map_var = tk.BooleanVar(value=False)
        self._layout_rule_display_var = tk.StringVar(value="")
        self._layout_info_spec_display_var = tk.StringVar(value="")
        self._layout_metadata_spec_display_var = tk.StringVar(value="")
        self._layout_context_map_display_var = tk.StringVar(value="")
        self._layout_template_manual = ""
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
        self._convert_flip_x_var = tk.BooleanVar(value=False)
        self._convert_flip_y_var = tk.BooleanVar(value=False)
        self._convert_flip_z_var = tk.BooleanVar(value=False)
        self._convert_sidecar_var = tk.BooleanVar(value=False)
        self._convert_sidecar_format_var = tk.StringVar(value="json")

        self._layout_info_spec_combo: Optional[ttk.Combobox] = None
        self._layout_metadata_spec_combo: Optional[ttk.Combobox] = None
        self._layout_key_listbox: Optional[tk.Listbox] = None
        self._layout_key_source_signature: Optional[Tuple[Any, ...]] = None
        self._convert_settings_text: Optional[tk.Text] = None
        self._convert_preview_text: Optional[tk.Text] = None
        self._addon_output_payload: Optional[Any] = None
        self._layout_template_combo: Optional[ttk.Combobox] = None
        self._layout_source_combo: Optional[ttk.Combobox] = None
        self._layout_auto_check: Optional[ttk.Checkbutton] = None
        self._addon_rule_file_combo: Optional[ttk.Combobox] = None
        self._addon_rule_browse_button: Optional[ttk.Button] = None
        self._addon_rule_new_button: Optional[ttk.Button] = None
        self._addon_rule_file_combo: Optional[ttk.Combobox] = None
        self._addon_rule_desc_tooltip: Optional[_Tooltip] = None
        self._addon_transform_file_var = tk.StringVar(value="")
        self._addon_transform_file_map: Dict[str, str] = {}
        self._addon_transform_display_by_path: Dict[str, str] = {}
        self._addon_transform_session_files: List[str] = []
        self._addon_transform_combo: Optional[ttk.Combobox] = None
        self._addon_transform_browse_button: Optional[ttk.Button] = None
        self._addon_transform_new_button: Optional[ttk.Button] = None
        self._addon_transform_edit_button: Optional[ttk.Button] = None
        self._addon_spec_name_entry: Optional[ttk.Entry] = None
        self._addon_spec_desc_tooltip: Optional[_Tooltip] = None

        self._registry_window: Optional[tk.Toplevel] = None
        self._registry_add_menu: Optional[tk.Menu] = None
        self._registry_tree: Optional[ttk.Treeview] = None
        self._registry_columns: List[Dict[str, Any]] = []
        self._registry_status_var = tk.StringVar(value="")
        self._registry_sort_key = "basename"
        self._registry_sort_ascending = True

        self._viewer_hooks = load_viewer_hooks()
        self._layout_template_var.trace_add("write", lambda *_: self._on_layout_template_change())
        self._viewer_host: Optional[ttk.Frame] = None
        self._viewer_widget: Optional[Any] = None
        self._viewer: Optional[ViewerRenderer] = None
        self._subject_window: Optional[tk.Toplevel] = None
        self._subject_entries: Dict[str, ttk.Entry] = {}
        self._subject_summary_entries: list[ttk.Entry] = []
        self._subject_button: Optional[ttk.Button] = None
        self._refresh_button: Optional[ttk.Button] = None
        self._addon_spec_browse_button: Optional[ttk.Button] = None
        self._addon_spec_new_button: Optional[ttk.Button] = None
        self._addon_context_new_button: Optional[ttk.Button] = None
        self._params_tree: Optional[ttk.Treeview] = None
        self._params_sort_key: Optional[str] = None
        self._params_sort_ascending = True
        self._params_results: list[tuple[str, str, Any]] = []
        self._params_truncated = 0
        self._params_column_titles = {
            "file": "File",
            "key": "Key",
            "type": "Type",
            "value": "Value",
        }
        self._params_summary_vars: Dict[str, tk.StringVar] = {}
        self._params_summary_entries: Dict[str, ttk.Entry] = {}
        self._subject_summary_vars = {
            "Study ID": tk.StringVar(value="None"),
            "Subject ID": tk.StringVar(value="None"),
            "Study Date": tk.StringVar(value="None"),
        }
        self._registry_column_menu_vars: list[tk.BooleanVar] = []
        self._extensions_tab: Optional[ttk.Frame] = None
        self._extensions_combo: Optional[ttk.Combobox] = None
        self._extensions_container: Optional[ttk.Frame] = None
        self._extensions_hooks: Dict[str, Any] = {}
        self._extensions_current_widget: Optional[tk.Widget] = None
        self._detached_tabs: Dict[str, Tuple[tk.Toplevel, tk.Widget]] = {}
        self._tab_titles: Dict[tk.Widget, str] = {}
        self._tab_order: list[str] = []
        self._tab_builders: Dict[str, Callable[[tk.Misc], Optional[ttk.Frame]]] = {}
        self._tab_widgets: Dict[str, tk.Widget] = {}

        self._init_ui()
        self._apply_window_presentation()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        if path:
            self._status_var.set("Opening…")
            self.after(250, lambda: self._load_path_with_spinner(path, scan_id=scan_id, reco_id=reco_id))
        else:
            self._status_var.set("Open a study folder, zip, or PvDatasets package to begin.")

    def _load_path_with_spinner(
        self,
        path: str,
        *,
        scan_id: Optional[int],
        reco_id: Optional[int],
    ) -> None:
        stop_event = threading.Event()
        spinner_thread = None
        if sys.stdout and getattr(sys.stdout, "isatty", lambda: False)():
            spinner_thread = threading.Thread(
                target=self._console_spinner,
                args=(stop_event, "Opening",),
                daemon=True,
            )
            spinner_thread.start()
        try:
            logger.debug("Opening dataset: %s", path)
            self._load_path(path, scan_id=scan_id, reco_id=reco_id)
            logger.debug("Open complete.")
        finally:
            stop_event.set()
            if spinner_thread is not None:
                spinner_thread.join(timeout=0.5)
            if sys.stdout and getattr(sys.stdout, "isatty", lambda: False)():
                try:
                    sys.stdout.write("\rOpening done.\n")
                    sys.stdout.flush()
                except Exception:
                    pass

            scans = len(self._scan_ids) if isinstance(self._scan_ids, list) else 0
            try:
                print(f"Loaded dataset with {scans} scan(s). Open complete.", flush=True)
            except Exception:
                pass

    @staticmethod
    def _console_spinner(stop_event: threading.Event, label: str) -> None:
        frames = "|/-\\"
        idx = 0
        last_emit = 0.0
        while not stop_event.is_set():
            now = time.time()
            if now - last_emit >= 0.12:
                last_emit = now
                try:
                    sys.stdout.write(f"\r{label} {frames[idx % len(frames)]}")
                    sys.stdout.flush()
                except Exception:
                    return
                idx += 1
            time.sleep(0.02)

    @staticmethod
    def _to_yaml_safe(obj: Any) -> Any:
        if obj is None:
            return None
        if isinstance(obj, (str, int, float, bool)):
            return obj
        if isinstance(obj, Path):
            return str(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.generic):
            try:
                return obj.item()
            except Exception:
                return str(obj)
        if isinstance(obj, dict):
            return {str(k): ViewerApp._to_yaml_safe(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [ViewerApp._to_yaml_safe(v) for v in obj]
        try:
            return str(obj)
        except Exception:
            return repr(obj)

    def _format_yaml(self, payload: Any) -> str:
        safe_payload = self._to_yaml_safe(payload)
        try:
            return yaml.safe_dump(
                safe_payload,
                sort_keys=False,
                allow_unicode=True,
                default_flow_style=False,
            )
        except Exception:
            return pprint.pformat(payload, sort_dicts=False, width=120)

    def _apply_window_presentation(self) -> None:
        self._set_app_icon()
        self._set_app_name()
        self.after(0, self._bring_to_front)
        self.after(250, self._bring_to_front)

    def _set_app_name(self) -> None:
        try:
            self.tk.call("tk", "appname", "BrkRaw")
        except Exception:
            pass
        try:
            self.tk.call("tk::mac::SetApplicationName", "BrkRaw")
        except Exception:
            pass

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

    def _set_viewer_widget(self, viewer: Any) -> None:
        if self._viewer_host is None:
            return
        if self._viewer_widget is not None:
            old = self._viewer_widget
            old_widget = old if isinstance(old, tk.Widget) else getattr(old, "widget", None)
            if isinstance(old_widget, tk.Widget):
                try:
                    old_widget.destroy()
                except Exception:
                    pass
        self._viewer_widget = viewer
        widget = viewer if isinstance(viewer, tk.Widget) else getattr(viewer, "widget", None)
        if not isinstance(widget, tk.Widget):
            raise TypeError("Viewer widget must be a tkinter widget or expose .widget.")
        widget.grid(row=0, column=0, sticky="nsew")
        viewer_adapter = cast(ViewerRenderer, viewer)
        self._viewer = viewer_adapter
        if hasattr(viewer_adapter, "set_click_callback"):
            viewer_adapter.set_click_callback(self._on_view_click)
        if hasattr(viewer_adapter, "set_zoom_callback"):
            viewer_adapter.set_zoom_callback(self._on_zoom_wheel)

    def _build_extensions_tab(self, parent: tk.Misc) -> Optional[ttk.Frame]:
        if not self._viewer_hooks:
            return None
        available: Dict[str, Any] = {}
        for hook in self._viewer_hooks:
            build_tab = getattr(hook, "build_tab", None)
            if callable(build_tab):
                name = getattr(hook, "name", None) or getattr(hook, "tab_title", None) or "Extension"
                available[str(name)] = hook
        if not available:
            return None

        tab = ttk.Frame(parent, padding=(6, 6))
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)
        self._extensions_tab = tab
        self._extensions_hooks = available

        header = ttk.Frame(tab)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
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
        container.grid(row=1, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)
        self._extensions_container = container
        return tab

    def _on_extension_selected(self, *_: object) -> None:
        if self._extensions_container is None or self._extensions_combo is None:
            return
        name = self._extensions_combo.get()
        if self._extensions_current_widget is not None:
            try:
                self._extensions_current_widget.destroy()
            except Exception:
                pass
            self._extensions_current_widget = None
        if not name or name == "None":
            return
        hook = self._extensions_hooks.get(name)
        if hook is None:
            return
        build_tab = getattr(hook, "build_tab", None)
        if not callable(build_tab):
            return
        try:
            widget = build_tab(self._extensions_container, self)
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

    def _notify_hooks_dataset_loaded(self) -> None:
        if not self._viewer_hooks:
            return
        for hook in self._viewer_hooks:
            callback = getattr(hook, "on_dataset_loaded", None)
            if callable(callback):
                try:
                    callback(self)
                except Exception as exc:
                    logger.warning("Viewer hook dataset callback failed: %s", exc)

    def _notify_hooks_scan_selected(self) -> None:
        if not self._viewer_hooks:
            return
        for hook in self._viewer_hooks:
            callback = getattr(hook, "on_scan_selected", None)
            if callable(callback):
                try:
                    callback(self)
                except Exception as exc:
                    logger.warning("Viewer hook scan callback failed: %s", exc)

    def _register_tab_builder(self, title: str, builder: Callable[[tk.Misc], Optional[ttk.Frame]]) -> None:
        self._tab_builders[title] = builder
        if title not in self._tab_order:
            self._tab_order.append(title)

    def _create_tab_in_notebook(self, title: str) -> Optional[ttk.Frame]:
        builder = self._tab_builders.get(title)
        if builder is None:
            return None
        tab = builder(self._notebook)
        if tab is None:
            return None
        attach_index = self._attach_index_for_title(title)
        if attach_index is None:
            self._notebook.add(tab, text=title)
        else:
            self._notebook.insert(attach_index, tab, text=title)
        self._tab_titles[tab] = title
        self._tab_widgets[title] = tab
        self._post_tab_build(title)
        return tab

    def _on_notebook_context_menu(self, event: tk.Event) -> None:
        notebook = self._notebook
        if notebook is None:
            return
        try:
            index = notebook.index(f"@{event.x},{event.y}")
        except Exception:
            return
        tabs = notebook.tabs()
        if index < 0 or index >= len(tabs):
            return
        tab_id = tabs[index]
        try:
            tab_widget = self.nametowidget(tab_id)
        except Exception:
            return
        title = self._tab_titles.get(tab_widget)
        if not title or title in self._detached_tabs:
            return
        menu = tk.Menu(notebook, tearoff=False)
        menu.add_command(label="Detach", command=lambda: self._detach_tab(title))
        menu.tk_popup(event.x_root, event.y_root)

    def _detach_tab(self, title: str) -> None:
        if title in self._detached_tabs:
            window, _ = self._detached_tabs[title]
            try:
                window.lift()
                window.focus_set()
            except Exception:
                pass
            return
        tab = self._tab_widgets.get(title)
        if tab is None:
            return
        try:
            self._notebook.forget(tab)
        except Exception:
            return
        try:
            tab.destroy()
        except Exception:
            pass
        self._tab_titles.pop(tab, None)
        self._tab_widgets.pop(title, None)

        window = tk.Toplevel(self)
        window.title(f"BrkRaw Viewer - {title}")
        window.geometry("960x700")
        window.minsize(640, 480)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)
        frame = self._tab_builders[title](window)
        if frame is None:
            try:
                window.destroy()
            except Exception:
                pass
            return
        frame.grid(row=0, column=0, sticky="nsew")
        window.protocol("WM_DELETE_WINDOW", lambda: self._attach_tab(title))
        self._detached_tabs[title] = (window, frame)
        self._post_tab_build(title)

    def _attach_tab(self, title: str) -> None:
        payload = self._detached_tabs.pop(title, None)
        if payload is None:
            return
        window, frame = payload
        try:
            frame.destroy()
        except Exception:
            pass
        if window.winfo_exists():
            try:
                window.destroy()
            except Exception:
                pass
        tab = self._create_tab_in_notebook(title)
        if tab is not None:
            try:
                self._notebook.select(tab)
            except Exception:
                pass

    def _attach_index_for_title(self, title: str) -> Optional[int]:
        try:
            desired = self._tab_order.index(title)
        except ValueError:
            return None
        attached_titles: List[str] = []
        for tab_id in self._notebook.tabs():
            try:
                widget = self.nametowidget(tab_id)
            except Exception:
                continue
            label = self._tab_titles.get(widget)
            if label:
                attached_titles.append(label)
        for idx, other in enumerate(attached_titles):
            try:
                if self._tab_order.index(other) > desired:
                    return idx
            except ValueError:
                continue
        return None

    def _post_tab_build(self, title: str) -> None:
        if title == "Viewer":
            self._viewer_dirty = True
            self._maybe_load_viewer()
            return
        if title == "Addon":
            self._refresh_addon_controls()
            if self._scan is None:
                self._set_info_output("No scan selected.")
            else:
                self._set_info_output(self._info_full or {})
            return
        if title == "Params":
            self._refresh_param_controls()
            return
        if title == "Convert":
            self._update_convert_space_controls()
            self._update_layout_controls()
            self._refresh_layout_spec_selectors()
            return
        if title == "Config":
            self._load_config_text()

    def _set_app_icon(self) -> None:
        try:
            package_root = Path(__file__).resolve().parents[1]
            assets = package_root / "assets"
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

        ttk.Button(top, text="Registry", command=self._open_registry_window).pack(side=tk.RIGHT)

        load_button = ttk.Menubutton(top, text="Load")
        load_menu = tk.Menu(load_button, tearoff=False)
        load_menu.add_command(label="Folder (Study / .PvDatasets)…", command=self._choose_dir)
        load_menu.add_command(label="Archive File (.zip / .PvDatasets)…", command=self._choose_file)
        load_button.configure(menu=load_menu)
        load_button.pack(side=tk.LEFT, padx=(0, 6))
        self._refresh_button = ttk.Button(top, text="Refresh", command=self._refresh)
        self._refresh_button.pack(side=tk.LEFT)

        ttk.Label(top, text="Path:").pack(side=tk.LEFT, padx=(12, 6))
        path_entry = ttk.Entry(top, textvariable=self._path_var, width=70)
        path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        path_entry.configure(state="readonly")

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

        subject_bar = ttk.Frame(self, padding=(10, 0, 10, 8))
        subject_bar.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(subject_bar, text="Study ID").pack(side=tk.LEFT)
        study_id_entry = ttk.Entry(
            subject_bar,
            textvariable=self._subject_summary_vars["Study ID"],
            width=14,
            state="readonly",
        )
        study_id_entry.pack(side=tk.LEFT, padx=(6, 12))
        ttk.Label(subject_bar, text="Subject ID").pack(side=tk.LEFT)
        subject_id_entry = ttk.Entry(
            subject_bar,
            textvariable=self._subject_summary_vars["Subject ID"],
            width=14,
            state="readonly",
        )
        subject_id_entry.pack(side=tk.LEFT, padx=(6, 12))
        ttk.Label(subject_bar, text="Study Date").pack(side=tk.LEFT)
        study_date_entry = ttk.Entry(
            subject_bar,
            textvariable=self._subject_summary_vars["Study Date"],
            width=18,
            state="readonly",
        )
        study_date_entry.pack(side=tk.LEFT, padx=(6, 0))
        self._subject_summary_entries = [study_id_entry, subject_id_entry, study_date_entry]
        self._subject_button = ttk.Button(subject_bar, text="Study Info", command=self._open_subject_window)
        self._subject_button.pack(side=tk.RIGHT)

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
        self._notebook.bind("<Button-3>", self._on_notebook_context_menu)
        self._notebook.bind("<Button-2>", self._on_notebook_context_menu)
        self._notebook.bind("<Control-Button-1>", self._on_notebook_context_menu)

        self._register_tab_builder("Viewer", self._build_viewer_tab)
        self._register_tab_builder("Addon", self._build_addon_tab)
        self._register_tab_builder("Params", self._build_params_tab)
        self._register_tab_builder("Convert", self._build_convert_tab_frame)
        self._register_tab_builder("Config", self._build_config_tab_frame)
        self._register_tab_builder("Extensions", self._build_extensions_tab)

        for title in ("Viewer", "Addon", "Params", "Convert", "Config", "Extensions"):
            self._create_tab_in_notebook(title)

        self._update_convert_space_controls()
        self._update_layout_controls()
        self._refresh_layout_spec_selectors()
        self._load_config_text()
        self._set_dataset_controls_enabled(False)

        status = ttk.Label(
            self,
            textvariable=self._status_var,
            relief=tk.SUNKEN,
            anchor=tk.W,
            padding=(8, 4),
        )
        status.pack(side=tk.BOTTOM, fill=tk.X)

    def _build_viewer_tab(self, parent: tk.Misc) -> ttk.Frame:
        viewer_tab = ttk.Frame(parent)
        viewer_tab.columnconfigure(0, weight=1)
        viewer_tab.rowconfigure(1, weight=1)
        self._extra_dim_vars = []
        self._extra_dim_scales = []

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

        for combo in (self._subject_type_combo, self._pose_primary_combo, self._pose_secondary_combo):
            combo.bind("<<ComboboxSelected>>", self._on_subject_change)

        preview_frame = ttk.Frame(viewer_tab, padding=(6, 6))
        preview_frame.grid(row=1, column=0, sticky="nsew")
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(2, weight=1)

        slider_bar = ttk.Frame(preview_frame)
        slider_bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        slider_bar.columnconfigure(0, weight=1)
        slider_inner = ttk.Frame(slider_bar)
        slider_inner.grid(row=0, column=0)

        def _axis_box(axis: str, var: tk.IntVar, flip_var: tk.BooleanVar, on_change):
            box = ttk.Frame(slider_inner)
            box.pack(side=tk.LEFT, padx=(0, 6))
            ttk.Checkbutton(
                box,
                text=f"Flip {axis}",
                variable=flip_var,
                command=self._on_affine_change,
            ).pack(side=tk.TOP, anchor="center")
            row = ttk.Frame(box)
            row.pack(side=tk.TOP)
            ttk.Label(row, text=axis).pack(side=tk.LEFT, padx=(0, 4))
            scale = tk.Scale(
                row,
                from_=0,
                to=0,
                orient=tk.HORIZONTAL,
                showvalue=True,
                command=on_change,
                length=140,
            )
            scale.pack(side=tk.LEFT)
            scale.configure(variable=var)
            return scale

        self._x_scale = _axis_box("X", self._x_var, self._affine_flip_x_var, self._on_x_change)
        self._y_scale = _axis_box("Y", self._y_var, self._affine_flip_y_var, self._on_y_change)
        self._z_scale = _axis_box("Z", self._z_var, self._affine_flip_z_var, self._on_z_change)

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

        self._viewer_host = ttk.Frame(preview_frame)
        self._viewer_host.grid(row=2, column=0, sticky="nsew")
        self._viewer_host.columnconfigure(0, weight=1)
        self._viewer_host.rowconfigure(0, weight=1)
        self._set_viewer_widget(OrthogonalCanvas(self._viewer_host))

        bottom_bar = ttk.Frame(preview_frame)
        bottom_bar.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        bottom_bar.columnconfigure(0, weight=1)
        hook_box = ttk.Frame(bottom_bar)
        hook_box.grid(row=0, column=0, sticky="w")
        self._viewer_hook_frame = hook_box
        self._viewer_hook_check = ttk.Checkbutton(
            hook_box,
            text="Hook",
            variable=self._viewer_hook_enabled_var,
            command=self._on_viewer_hook_toggle,
        )
        self._viewer_hook_check.pack(side=tk.LEFT, padx=(0, 6))
        self._viewer_hook_label = ttk.Label(hook_box, textvariable=self._viewer_hook_name_var)
        self._viewer_hook_label.pack(side=tk.LEFT)
        hook_box.grid_remove()
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

        return viewer_tab

    def _build_addon_tab(self, parent: tk.Misc) -> ttk.Frame:
        addon_tab = ttk.Frame(parent)
        addon_tab.columnconfigure(0, weight=1)
        addon_tab.columnconfigure(1, weight=1)
        addon_tab.rowconfigure(0, weight=1)
        addon_tab.rowconfigure(1, weight=1)

        top_left = ttk.Frame(addon_tab, padding=(6, 6))
        top_left.grid(row=0, column=0, sticky="nsew")
        top_left.columnconfigure(0, weight=1)

        top_right = ttk.Frame(addon_tab, padding=(6, 6))
        top_right.grid(row=0, column=1, sticky="nsew")
        top_right.columnconfigure(0, weight=1)
        top_right.rowconfigure(0, weight=1)

        bottom_left = ttk.Frame(addon_tab, padding=(6, 6))
        bottom_left.grid(row=1, column=0, sticky="nsew")
        bottom_left.columnconfigure(0, weight=1)

        bottom_right = ttk.Frame(addon_tab, padding=(6, 6))
        bottom_right.grid(row=1, column=1, sticky="nsew")
        bottom_right.columnconfigure(0, weight=1)
        bottom_right.rowconfigure(2, weight=1)

        rule_frame = ttk.LabelFrame(top_left, text="Rule", padding=(8, 8))
        rule_frame.grid(row=0, column=0, sticky="ew")
        rule_frame.columnconfigure(1, weight=1)

        ttk.Label(rule_frame, text="file").grid(row=0, column=0, sticky="w")
        self._addon_rule_file_combo = ttk.Combobox(
            rule_frame,
            textvariable=self._addon_rule_file_var,
            state="readonly",
            values=("None",),
        )
        self._addon_rule_file_combo.grid(row=0, column=1, columnspan=2, sticky="ew", padx=(8, 6))
        self._addon_rule_file_combo.bind("<<ComboboxSelected>>", lambda *_: self._on_rule_file_selected())
        self._addon_rule_browse_button = ttk.Button(rule_frame, text="Browse", command=self._browse_rule_file)
        self._addon_rule_browse_button.grid(row=0, column=3, sticky="e")
        self._addon_rule_new_button = ttk.Button(rule_frame, text="New", command=self._new_rule_file)

        ttk.Label(rule_frame, text="name").grid(row=1, column=0, sticky="w", pady=(8, 0))
        name_row = ttk.Frame(rule_frame)
        name_row.grid(row=1, column=1, columnspan=3, sticky="ew", padx=(8, 0), pady=(8, 0))
        name_row.columnconfigure(0, weight=1)
        self._addon_rule_combo = ttk.Combobox(
            name_row,
            textvariable=self._rule_name_var,
            state="readonly",
            values=("None",),
        )
        self._addon_rule_combo.grid(row=0, column=0, sticky="ew")
        self._addon_rule_combo.bind("<<ComboboxSelected>>", lambda *_: self._on_rule_selected())
        ttk.Checkbutton(
            name_row,
            text="Auto",
            variable=self._addon_rule_auto_var,
            command=self._on_rule_auto_toggle,
        ).grid(row=0, column=1, sticky="e", padx=(8, 0))
        self._addon_rule_desc_tooltip = _Tooltip(self._addon_rule_combo, lambda: self._addon_rule_desc_var.get())

        ttk.Label(rule_frame, text="category").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(rule_frame, textvariable=self._addon_rule_category_var, state="readonly").grid(
            row=2, column=1, columnspan=3, sticky="ew", padx=(8, 0), pady=(8, 0)
        )

        ttk.Label(rule_frame, text="status").grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Label(rule_frame, textvariable=self._addon_rule_status_var).grid(row=3, column=1, sticky="w", padx=(8, 0), pady=(8, 0))
        self._addon_rule_new_button.grid(row=3, column=2, sticky="e", padx=(0, 6), pady=(8, 0))
        ttk.Button(rule_frame, text="Edit", command=self._edit_rule_file).grid(row=3, column=3, sticky="e", pady=(8, 0))

        transform_frame = ttk.LabelFrame(top_left, text="Transform", padding=(8, 8))
        transform_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        transform_frame.columnconfigure(1, weight=1)

        ttk.Label(transform_frame, text="file").grid(row=0, column=0, sticky="w")
        self._addon_transform_combo = ttk.Combobox(
            transform_frame,
            textvariable=self._addon_transform_file_var,
            state="readonly",
            values=("None",),
        )
        self._addon_transform_combo.grid(row=0, column=1, columnspan=2, sticky="ew", padx=(8, 6))
        self._addon_transform_combo.bind("<<ComboboxSelected>>", lambda *_: self._on_transform_file_selected())
        self._addon_transform_browse_button = ttk.Button(transform_frame, text="Browse", command=self._browse_transform_file)
        self._addon_transform_browse_button.grid(row=0, column=3, sticky="e")
        self._addon_transform_new_button = ttk.Button(transform_frame, text="New", command=self._new_transform_file)

        self._addon_transform_edit_button = ttk.Button(transform_frame, text="Edit", command=self._edit_transform_file)
        self._addon_transform_edit_button.grid(row=1, column=3, sticky="e", pady=(8, 0))
        self._addon_transform_new_button.grid(row=1, column=2, sticky="e", padx=(0, 6), pady=(8, 0))

        spec_frame = ttk.LabelFrame(bottom_left, text="Spec", padding=(8, 8))
        spec_frame.grid(row=0, column=0, sticky="nsew")
        spec_frame.columnconfigure(1, weight=1)

        ttk.Checkbutton(
            spec_frame,
            text="Follow applied rule for spec selection",
            variable=self._addon_spec_auto_var,
            command=self._on_spec_auto_toggle,
        ).grid(row=0, column=0, columnspan=4, sticky="w")

        ttk.Label(spec_frame, text="file").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self._addon_spec_combo = ttk.Combobox(
            spec_frame,
            textvariable=self._addon_spec_file_var,
            state="readonly",
            values=("None",),
        )
        self._addon_spec_combo.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(8, 6), pady=(8, 0))
        self._addon_spec_combo.bind("<<ComboboxSelected>>", lambda *_: self._on_spec_file_selected())
        self._addon_spec_browse_button = ttk.Button(spec_frame, text="Browse", command=self._browse_spec_file)
        self._addon_spec_browse_button.grid(row=1, column=3, sticky="e", pady=(8, 0))
        self._addon_spec_new_button = ttk.Button(spec_frame, text="New", command=self._new_spec_file)

        ttk.Label(spec_frame, text="name").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self._addon_spec_name_entry = ttk.Entry(spec_frame, textvariable=self._addon_spec_name_var, state="readonly")
        self._addon_spec_name_entry.grid(row=2, column=1, columnspan=3, sticky="ew", padx=(8, 0), pady=(8, 0))
        self._addon_spec_desc_tooltip = _Tooltip(self._addon_spec_name_entry, lambda: self._addon_spec_desc_var.get())

        ttk.Label(spec_frame, text="status").grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Label(spec_frame, textvariable=self._addon_spec_status_var).grid(row=3, column=1, sticky="w", padx=(8, 0), pady=(8, 0))
        self._addon_spec_new_button.grid(row=3, column=2, sticky="e", padx=(0, 6), pady=(8, 0))
        ttk.Button(spec_frame, text="Edit", command=self._edit_spec_file).grid(row=3, column=3, sticky="e", pady=(8, 0))

        ttk.Button(spec_frame, text="Apply Spec", command=self._apply_selected_spec).grid(
            row=4, column=0, columnspan=4, sticky="ew", pady=(10, 0)
        )

        map_frame = ttk.LabelFrame(bottom_right, text="Context Map", padding=(8, 8))
        map_frame.grid(row=0, column=0, sticky="ew")
        map_frame.columnconfigure(1, weight=1)

        ttk.Label(map_frame, text="path").grid(row=0, column=0, sticky="w")
        ttk.Entry(map_frame, textvariable=self._addon_context_map_var, state="readonly").grid(
            row=0, column=1, columnspan=2, sticky="ew", padx=(8, 6)
        )
        ttk.Button(map_frame, text="Open", command=self._browse_context_map).grid(row=0, column=3, sticky="e")
        self._addon_context_new_button = ttk.Button(map_frame, text="New", command=self._new_context_map)

        ttk.Label(map_frame, text="status").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Label(map_frame, textvariable=self._addon_context_status_var).grid(row=1, column=1, sticky="w", padx=(8, 0), pady=(8, 0))
        self._addon_context_new_button.grid(row=1, column=2, sticky="e", padx=(0, 6), pady=(8, 0))
        ttk.Button(map_frame, text="Edit", command=self._edit_context_map).grid(row=1, column=3, sticky="e", pady=(8, 0))

        ttk.Button(map_frame, text="Apply Context Map", command=self._apply_context_map).grid(
            row=2, column=0, columnspan=4, sticky="ew", pady=(10, 0)
        )

        output_frame = ttk.LabelFrame(top_right, text="Output", padding=(8, 8))
        output_frame.grid(row=0, column=0, sticky="nsew")
        output_frame.columnconfigure(0, weight=1)
        output_frame.rowconfigure(0, weight=1)

        self._info_output_text = tk.Text(output_frame, wrap="word")
        self._info_output_text.grid(row=0, column=0, sticky="nsew")
        info_scroll = ttk.Scrollbar(output_frame, orient="vertical", command=self._info_output_text.yview)
        info_scroll.grid(row=0, column=1, sticky="ns")
        self._info_output_text.configure(yscrollcommand=info_scroll.set)
        self._info_output_text.configure(state=tk.DISABLED)

        output_actions = ttk.Frame(bottom_right)
        output_actions.grid(row=1, column=0, sticky="e", pady=(10, 0))
        ttk.Button(output_actions, text="Reset", command=self._reset_addon_state).pack(side=tk.LEFT)
        ttk.Button(output_actions, text="Save As", command=self._save_addon_output).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Frame(bottom_right).grid(row=2, column=0, sticky="nsew")

        return addon_tab

    def _build_params_tab(self, parent: tk.Misc) -> ttk.Frame:
        params_tab = ttk.Frame(parent)
        params_tab.columnconfigure(0, weight=1)
        params_tab.rowconfigure(1, weight=1)

        summary_frame = ttk.LabelFrame(params_tab, text="Scan Info", padding=(8, 8))
        summary_frame.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 0))
        for col in range(4):
            summary_frame.columnconfigure(col * 2 + 1, weight=1)

        self._params_summary_vars = {
            "Protocol": tk.StringVar(value=""),
            "Method": tk.StringVar(value=""),
            "TR (ms)": tk.StringVar(value=""),
            "TE (ms)": tk.StringVar(value=""),
            "FlipAngle (degree)": tk.StringVar(value=""),
            "Dim": tk.StringVar(value=""),
            "Shape": tk.StringVar(value=""),
            "FOV (mm)": tk.StringVar(value=""),
        }
        self._params_summary_entries = {}
        for idx, (label, var) in enumerate(self._params_summary_vars.items()):
            row = idx // 4
            col = (idx % 4) * 2
            ttk.Label(summary_frame, text=label).grid(row=row, column=col, sticky="w", padx=6, pady=3)
            entry = ttk.Entry(summary_frame, textvariable=var, width=18)
            entry.grid(row=row, column=col + 1, sticky="ew", padx=(0, 6), pady=3)
            entry.configure(state="readonly")
            self._params_summary_entries[label] = entry

        search_frame = ttk.Frame(params_tab, padding=(6, 6))
        search_frame.grid(row=1, column=0, sticky="nsew")
        search_frame.columnconfigure(0, weight=1)
        search_frame.rowconfigure(1, weight=1)

        controls = ttk.Frame(search_frame)
        controls.grid(row=0, column=0, sticky="ew")
        controls.columnconfigure(3, weight=1)
        ttk.Label(controls, text="Target").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            controls,
            textvariable=self._param_scope_var,
            values=("all", "acqp", "method", "reco", "visu_pars"),
            state="readonly",
            width=12,
        ).grid(row=0, column=1, sticky="w", padx=(8, 12))
        ttk.Label(controls, text="Query").grid(row=0, column=2, sticky="w")
        query_entry = ttk.Entry(controls, textvariable=self._param_query_var)
        query_entry.grid(row=0, column=3, sticky="ew", padx=(8, 12))
        query_entry.bind("<Return>", lambda *_: self._run_param_search())
        ttk.Button(controls, text="Search", command=self._run_param_search).grid(row=0, column=4, sticky="e")

        results_frame = ttk.Frame(search_frame)
        results_frame.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        results_frame.columnconfigure(0, weight=1)
        results_frame.rowconfigure(0, weight=1)

        columns = ("file", "key", "type", "value")
        tree = ttk.Treeview(results_frame, columns=columns, show="headings")
        tree.grid(row=0, column=0, sticky="nsew")
        tree.heading("file", text="File", anchor="w", command=lambda: self._params_sort_by("file"))
        tree.heading("key", text="Key", anchor="w", command=lambda: self._params_sort_by("key"))
        tree.heading("type", text="Type", anchor="center", command=lambda: self._params_sort_by("type"))
        tree.heading("value", text="Value", anchor="w", command=lambda: self._params_sort_by("value"))
        tree.column("file", width=110, anchor="w")
        tree.column("key", width=220, anchor="w")
        tree.column("type", width=90, anchor="center")
        tree.column("value", width=320, anchor="w")
        self._params_tree = tree
        self._update_params_sort_heading()

        vscroll = ttk.Scrollbar(results_frame, orient="vertical", command=tree.yview)
        vscroll.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=vscroll.set)

        return params_tab

    def _build_convert_tab_frame(self, parent: tk.Misc) -> ttk.Frame:
        layout_tab = ttk.Frame(parent)
        self._build_convert_tab(layout_tab)
        return layout_tab

    def _build_config_tab_frame(self, parent: tk.Misc) -> ttk.Frame:
        config_tab = ttk.Frame(parent)
        self._build_config_tab(config_tab)
        return config_tab

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

    def _open_registry_window(self) -> None:
        if self._registry_window is not None and self._registry_window.winfo_exists():
            self._registry_window.lift()
            self._registry_window.focus_set()
            self._refresh_registry_table()
            self._update_registry_add_menu_state()
            return
        self._build_registry_window()

    def _build_registry_window(self) -> None:
        window = tk.Toplevel(self)
        window.title("Dataset Registry")
        window.geometry("920x420")
        window.minsize(760, 320)
        self._registry_window = window

        toolbar = ttk.Frame(window, padding=(8, 8, 8, 4))
        toolbar.pack(side=tk.TOP, fill=tk.X)

        add_button = ttk.Menubutton(toolbar, text="+", width=3)
        add_menu = tk.Menu(add_button, tearoff=False)
        add_menu.add_command(label="Current session", command=self._registry_add_current_session)
        add_menu.add_command(label="Folder (Study / .PvDatasets)…", command=self._registry_add_folder)
        add_menu.add_command(label="Archive File (.zip / .PvDatasets)…", command=self._registry_add_archive)
        add_button.configure(menu=add_menu)
        add_button.pack(side=tk.LEFT)
        self._registry_add_menu = add_menu
        ttk.Button(toolbar, text="-", command=self._registry_remove_selected, width=3).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Refresh", command=self._refresh_registry_table).pack(side=tk.RIGHT)

        body = ttk.Frame(window, padding=(8, 0, 8, 6))
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        self._load_registry_columns()
        columns = [col["key"] for col in self._registry_visible_columns()]
        tree = ttk.Treeview(body, columns=columns, show="headings", selectmode="extended")
        self._registry_tree = tree
        tree.grid(row=0, column=0, sticky="nsew")

        vscroll = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
        vscroll.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=vscroll.set)

        hscroll = ttk.Scrollbar(body, orient="horizontal", command=tree.xview)
        hscroll.grid(row=1, column=0, sticky="ew")
        tree.configure(xscrollcommand=hscroll.set)

        tree.tag_configure("missing", foreground="#cc3333")
        tree.bind("<Double-1>", self._registry_on_double_click)
        tree.bind("<Button-3>", self._registry_show_column_menu)
        tree.bind("<Button-2>", self._registry_show_column_menu)
        tree.bind("<Control-Button-1>", self._registry_show_column_menu)
        tree.bind("<<TreeviewSelect>>", self._registry_on_select)
        tree.bind("<Motion>", self._registry_on_hover)

        status_bar = ttk.Frame(window, padding=(8, 4))
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        status_bar.columnconfigure(0, weight=1)
        status = ttk.Label(status_bar, textvariable=self._registry_status_var, anchor="w")
        status.grid(row=0, column=0, sticky="w")
        ttk.Button(status_bar, text="Load", command=self._registry_open_selected).grid(row=0, column=1, sticky="e")

        self._configure_registry_columns()
        self._refresh_registry_table()
        self._update_registry_add_menu_state()

    def _load_registry_columns(self) -> None:
        columns = registry_columns()
        normalized: List[Dict[str, Any]] = []
        for col in columns:
            if not isinstance(col, dict):
                continue
            if "key" not in col:
                continue
            entry = dict(col)
            entry.setdefault("hidden", False)
            normalized.append(entry)
        if not normalized:
            defaults = default_viewer_config().get("registry", {}).get("columns", [])
            for col in defaults:
                if not isinstance(col, dict) or "key" not in col:
                    continue
                entry = dict(col)
                entry.setdefault("hidden", False)
                normalized.append(entry)
        self._registry_columns = normalized

    def _registry_visible_columns(self) -> List[Dict[str, Any]]:
        return [col for col in self._registry_columns if not col.get("hidden")]

    def _configure_registry_columns(self) -> None:
        if self._registry_tree is None:
            return
        visible = self._registry_visible_columns()
        keys = [col["key"] for col in visible]
        self._registry_tree.configure(columns=keys)
        for col in visible:
            key = col["key"]
            title = str(col.get("title") or key)
            width = int(col.get("width") or 120)
            title = self._registry_heading_title(key, title)
            self._registry_tree.heading(key, text=title, command=lambda k=key: self._registry_sort_by(k))
            anchor = "w" if key == "basename" else "center"
            self._registry_tree.column(key, width=width, anchor=anchor, stretch=True)

    def _save_registry_columns(self) -> None:
        viewer_cfg = load_viewer_config()
        registry = viewer_cfg.get("registry", {})
        if not isinstance(registry, dict):
            registry = {}
        registry["columns"] = self._registry_columns
        viewer_cfg["registry"] = registry
        save_viewer_config(viewer_cfg)

    def _registry_show_column_menu(self, event: tk.Event) -> None:
        tree = self._registry_tree
        if tree is None:
            return
        region = tree.identify_region(event.x, event.y)
        if region != "heading":
            return
        col_id = tree.identify_column(event.x)
        try:
            index = int(col_id.lstrip("#")) - 1
        except ValueError:
            index = -1
        visible = self._registry_visible_columns()
        clicked_key = visible[index]["key"] if 0 <= index < len(visible) else None

        menu = tk.Menu(tree, tearoff=False)
        if clicked_key:
            menu.add_command(label="Move Left", command=lambda: self._registry_move_column(clicked_key, -1))
            menu.add_command(label="Move Right", command=lambda: self._registry_move_column(clicked_key, 1))
            menu.add_separator()

        self._registry_column_menu_vars = []
        for col in self._registry_columns:
            key = col["key"]
            var = tk.BooleanVar(value=not col.get("hidden"))
            self._registry_column_menu_vars.append(var)
            menu.add_checkbutton(
                label=str(col.get("title") or key),
                variable=var,
                command=lambda k=key, v=var: self._registry_toggle_column(k, v.get()),
            )

        menu.tk_popup(event.x_root, event.y_root)

    def _registry_toggle_column(self, key: str, visible: bool) -> None:
        for col in self._registry_columns:
            if col.get("key") == key:
                col["hidden"] = not visible
                break
        self._save_registry_columns()
        self._configure_registry_columns()
        self._refresh_registry_table()

    def _registry_move_column(self, key: str, offset: int) -> None:
        idx = next((i for i, col in enumerate(self._registry_columns) if col.get("key") == key), None)
        if idx is None:
            return
        new_idx = idx + offset
        if new_idx < 0 or new_idx >= len(self._registry_columns):
            return
        self._registry_columns[idx], self._registry_columns[new_idx] = (
            self._registry_columns[new_idx],
            self._registry_columns[idx],
        )
        self._save_registry_columns()
        self._configure_registry_columns()
        self._refresh_registry_table()

    def _registry_add_folder(self) -> None:
        path = filedialog.askdirectory(title="Select Bruker study folder")
        if not path:
            return
        self._registry_register_paths([Path(path)])

    def _registry_add_archive(self) -> None:
        path = filedialog.askopenfilename(
            title="Select Bruker dataset archive",
            filetypes=(
                ("Dataset archives", "*.zip *.PvDatasets *.pvdatasets"),
                ("All files", "*.*"),
            ),
        )
        if not path:
            return
        self._registry_register_paths([Path(path)])

    def _current_session_path(self) -> Optional[Path]:
        if self._loader is None or self._study is None:
            return None
        path = (self._path_var.get() or "").strip()
        if not path:
            return None
        return Path(path)

    def _is_registered_path(self, path: Path) -> bool:
        normalized = normalize_path(path)
        for entry in load_registry():
            if not isinstance(entry, dict):
                continue
            if entry.get("path") == normalized:
                return True
        return False

    def _update_registry_add_menu_state(self) -> None:
        menu = self._registry_add_menu
        if menu is None:
            return
        current = self._current_session_path()
        state = tk.NORMAL if current is not None and not self._is_registered_path(current) else tk.DISABLED
        try:
            menu.entryconfigure("Current session", state=state)
        except Exception:
            pass

    def _registry_add_current_session(self) -> None:
        path = self._current_session_path()
        if path is None:
            return
        if self._is_registered_path(path):
            return
        if not path.exists():
            messagebox.showwarning("Missing dataset", f"Dataset not found:\n{path}")
            return
        self._registry_register_paths([path])

    def _registry_register_paths(self, paths: List[Path]) -> None:
        existing = {entry.get("path") for entry in load_registry() if isinstance(entry, dict)}
        try:
            entries = register_paths(paths)
        except Exception as exc:
            messagebox.showerror("Registry error", f"Failed to register dataset:\n{exc}")
            return
        duplicates = [entry for entry in entries if entry.path in existing]
        if duplicates:
            messagebox.showinfo("Registry", "Dataset is already registered.")
        self._refresh_registry_table()

    def _registry_remove_selected(self) -> None:
        tree = self._registry_tree
        if tree is None:
            return
        selections = tree.selection()
        if not selections:
            return
        paths = [Path(item_id) for item_id in selections]
        removed = unregister_paths(paths)
        if removed:
            self._refresh_registry_table()

    def _registry_open_selected(self, *_: object) -> None:
        tree = self._registry_tree
        if tree is None:
            return
        selection = tree.selection()
        if not selection:
            return
        path = Path(selection[0])
        if not path.exists():
            messagebox.showwarning("Missing dataset", f"Dataset not found:\n{path}")
            return
        self._path_var.set(str(path))
        self._load_path(str(path), scan_id=None, reco_id=None)

    def _registry_on_double_click(self, event: tk.Event) -> None:
        tree = self._registry_tree
        if tree is None:
            return
        region = tree.identify_region(event.x, event.y)
        if region == "separator":
            column = tree.identify_column(event.x)
            if column:
                self._registry_autosize_column(column)
            return
        self._registry_open_selected()

    def _registry_autosize_column(self, column: str) -> None:
        tree = self._registry_tree
        if tree is None:
            return
        try:
            idx = int(column.lstrip("#")) - 1
        except ValueError:
            return
        columns = list(tree["columns"])
        if idx < 0 or idx >= len(columns):
            return
        key = columns[idx]
        font = tkfont.nametofont("TkDefaultFont")
        heading = tree.heading(key, "text") or ""
        max_width = font.measure(str(heading)) + 16
        for item in tree.get_children():
            values = tree.item(item, "values")
            if idx < len(values):
                max_width = max(max_width, font.measure(str(values[idx])) + 16)
        tree.column(key, width=max_width)

    def _registry_on_select(self, *_: object) -> None:
        tree = self._registry_tree
        if tree is None:
            return
        selection = tree.selection()
        if not selection:
            self._registry_status_var.set("")
            return
        path = Path(selection[0])
        if not path.exists():
            self._registry_status_var.set(f"Missing: {path}")
        else:
            self._registry_status_var.set(str(path))

    def _registry_on_hover(self, event: tk.Event) -> None:
        tree = self._registry_tree
        if tree is None:
            return
        row_id = tree.identify_row(event.y)
        if not row_id:
            return
        path = Path(row_id)
        if not path.exists():
            self._registry_status_var.set(f"Missing: {path}")
        else:
            self._registry_status_var.set(str(path))

    def _registry_sort_by(self, key: str) -> None:
        if key == self._registry_sort_key:
            self._registry_sort_ascending = not self._registry_sort_ascending
        else:
            self._registry_sort_key = key
            self._registry_sort_ascending = True
        self._configure_registry_columns()
        self._refresh_registry_table()

    def _registry_heading_title(self, key: str, title: str) -> str:
        if key != self._registry_sort_key:
            return title
        arrow = "▲" if self._registry_sort_ascending else "▼"
        return f"{title} {arrow}"

    @staticmethod
    def _registry_sort_value(value: Any) -> Tuple[int, Any]:
        if value is None:
            return (1, "")
        if isinstance(value, (int, float)):
            return (0, value)
        if isinstance(value, (dt.datetime, dt.date)):
            return (0, value.isoformat())
        return (0, str(value).lower())

    def _refresh_registry_table(self) -> None:
        tree = self._registry_tree
        if tree is None:
            return
        tree.delete(*tree.get_children())
        entries = registry_status()
        sort_key = self._registry_sort_key or "basename"
        entries = sorted(
            entries,
            key=lambda entry: self._registry_sort_value(resolve_entry_value(entry, sort_key)),
            reverse=not self._registry_sort_ascending,
        )
        visible = self._registry_visible_columns()
        keys = [col["key"] for col in visible]
        for entry in entries:
            values = [resolve_entry_value(entry, key) for key in keys]
            tags = ("missing",) if entry.get("missing") else ()
            entry_path = str(entry.get("path", ""))
            tree.insert("", tk.END, iid=entry_path, values=values, tags=tags)
        self._update_registry_add_menu_state()

    def _load_path(
        self,
        path: str,
        *,
        scan_id: Optional[int],
        reco_id: Optional[int],
    ) -> None:
        self._clear_data_cache()
        self._loader = None
        self._study = None
        candidate_paths = self._candidate_load_paths(path)
        last_exc: Optional[Exception] = None
        for candidate in candidate_paths:
            try:
                self._loader = BrukerLoader(candidate)
                self._study = cast(StudyLoader, self._loader._study)
                break
            except Exception as exc:
                logger.debug("Failed loader candidate %s: %s", candidate, exc, exc_info=True)
                last_exc = exc
        else:
            details = "\n".join(candidate_paths) if candidate_paths else path
            messagebox.showerror(
                "Load error",
                f"Failed to load dataset:\n{last_exc}\n\nTried:\n{details}",
            )
            self._status_var.set("Failed to load dataset.")
            logger.error("Failed to load dataset: %s", last_exc)
            self._update_registry_add_menu_state()
            self._set_dataset_controls_enabled(False)
            return

        self._scan_info_cache.clear()
        self._info_full = self._resolve_info_bundle()
        self._scan_ids = list(self._study.avail.keys()) if self._study else []
        if not self._scan_ids:
            self._status_var.set("No scans found.")
            logger.warning("No scans found in dataset.")
            self._set_dataset_controls_enabled(False)
            return
        logger.debug("Loaded dataset with %d scan(s).", len(self._scan_ids))
        self._detach_converter_hooks()

        self._set_viewer_tab_state(True)
        self._set_dataset_controls_enabled(True)
        self._update_subject_info()
        self._populate_scan_list()

        target_scan = scan_id if scan_id in self._scan_ids else self._scan_ids[0]
        self._select_scan(target_scan)
        if reco_id is not None:
            self._select_reco(reco_id)
        self._notify_hooks_dataset_loaded()
        self._update_registry_add_menu_state()

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
        self._update_viewer_hook_controls()
        self._refresh_addon_controls()
        self._populate_reco_list(scan_id)
        self._update_params_summary()
        reco_ids = self._current_reco_ids()
        if reco_ids:
            self._select_reco(reco_ids[0])
        else:
            self._status_var.set(f"Scan {scan_id} has no reco data.")
        self._notify_hooks_scan_selected()

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
        self._refresh_addon_controls()

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
                resolve_paths=kind in {"info_spec", "metadata_spec"},
            )
        except Exception:
            return None
        return str(path) if path else None

    def _refresh_addon_controls(self) -> None:
        self._refresh_rule_files()
        self._on_rule_auto_toggle()
        self._refresh_transform_files()
        self._refresh_spec_choices()
        self._on_spec_auto_toggle()
        self._update_rule_details()
        self._update_spec_details()
        self._update_layout_controls()

    def _refresh_param_controls(self) -> None:
        self._update_params_summary()
        self._render_param_results([])

    def _refresh_rule_files(self) -> None:
        self._addon_rule_file_map = {}
        self._addon_rule_display_by_path = {}
        try:
            installed = addon_app.list_installed(root=resolve_root(None))
        except Exception:
            installed = {}
        rules = installed.get("rules", []) if isinstance(installed, dict) else []
        paths = config_core.paths(root=None)
        seen_relpaths: set[str] = set()
        for entry in rules:
            if not isinstance(entry, dict):
                continue
            relpath = entry.get("file")
            if not relpath:
                continue
            if relpath in seen_relpaths:
                continue
            seen_relpaths.add(relpath)
            basename = Path(relpath).name
            display = basename
            if display in self._addon_rule_file_map:
                display = f"{basename} ({relpath})"
            full_path = str((paths.rules_dir / relpath).resolve())
            if display in self._addon_rule_file_map and self._addon_rule_file_map[display] == full_path:
                continue
            self._addon_rule_file_map[display] = full_path
            self._addon_rule_display_by_path[full_path] = display

        for path in self._addon_rule_session_files:
            if not path:
                continue
            if path in self._addon_rule_display_by_path:
                continue
            self._addon_rule_file_map[path] = path
            self._addon_rule_display_by_path[path] = path

        values = sorted(self._addon_rule_file_map.keys()) if self._addon_rule_file_map else ["None"]
        if self._addon_rule_file_combo is not None:
            self._addon_rule_file_combo.configure(values=values)
        current = (self._addon_rule_file_var.get() or "").strip()
        if current in ("", "None") and values:
            self._addon_rule_file_var.set(values[0])
        path = self._resolve_rule_file_selection(self._addon_rule_file_var.get())
        self._load_rule_file(path)
        self._apply_rule_combo_state()

    def _resolve_rule_file_selection(self, selection: str) -> Optional[str]:
        if not selection or selection == "None":
            return None
        path = self._addon_rule_file_map.get(selection)
        if path:
            return path
        if Path(selection).exists():
            return selection
        return None

    def _refresh_transform_files(self) -> None:
        self._addon_transform_file_map = {}
        self._addon_transform_display_by_path = {}
        try:
            installed = addon_app.list_installed(root=resolve_root(None))
        except Exception:
            installed = {}
        transforms = installed.get("transforms", []) if isinstance(installed, dict) else []
        paths = config_core.paths(root=None)
        seen_relpaths: set[str] = set()
        for entry in transforms:
            if not isinstance(entry, dict):
                continue
            relpath = entry.get("file")
            if not relpath:
                continue
            if relpath in seen_relpaths:
                continue
            seen_relpaths.add(relpath)
            basename = Path(relpath).name
            display = basename
            if display in self._addon_transform_file_map:
                display = f"{basename} ({relpath})"
            full_path = str((paths.transforms_dir / relpath).resolve())
            if display in self._addon_transform_file_map and self._addon_transform_file_map[display] == full_path:
                continue
            self._addon_transform_file_map[display] = full_path
            self._addon_transform_display_by_path[full_path] = display

        for path in self._addon_transform_session_files:
            if not path:
                continue
            if path in self._addon_transform_display_by_path:
                continue
            self._addon_transform_file_map[path] = path
            self._addon_transform_display_by_path[path] = path

        values = sorted(self._addon_transform_file_map.keys()) if self._addon_transform_file_map else ["None"]
        if self._addon_transform_combo is not None:
            self._addon_transform_combo.configure(values=values, state="readonly" if self._addon_transform_file_map else "disabled")
        current = (self._addon_transform_file_var.get() or "").strip()
        if current in ("", "None") and values:
            self._addon_transform_file_var.set(values[0])

    def _resolve_transform_file_selection(self, selection: str) -> Optional[str]:
        if not selection or selection == "None":
            return None
        path = self._addon_transform_file_map.get(selection)
        if path:
            return path
        if Path(selection).exists():
            return selection
        return None

    def _on_transform_file_selected(self) -> None:
        selection = self._addon_transform_file_var.get()
        if selection and selection != "None":
            self._addon_transform_file_var.set(selection)

    def _browse_transform_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Select transform file",
            filetypes=(("Python", "*.py"), ("All files", "*.*")),
        )
        if not path:
            return
        if path not in self._addon_transform_session_files:
            self._addon_transform_session_files.append(path)
        self._refresh_transform_files()
        self._addon_transform_file_var.set(path)

    def _new_transform_file(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Create new transform file",
            defaultextension=".py",
            filetypes=(("Python", "*.py"), ("All files", "*.*")),
        )
        if not path:
            return
        target = Path(path)
        if not target.exists():
            target.write_text("# Transform script\n", encoding="utf-8")
        if path not in self._addon_transform_session_files:
            self._addon_transform_session_files.append(path)
        self._refresh_transform_files()
        self._addon_transform_file_var.set(path)
        self._open_text_editor(path=target, title="Edit transform")

    def _edit_transform_file(self) -> None:
        path = self._resolve_transform_file_selection(self._addon_transform_file_var.get())
        if not path:
            return
        self._open_text_editor(path=Path(path), title="Edit transform")

    def _load_rule_file(self, path: Optional[str]) -> None:
        if not path:
            self._addon_rule_choices = {}
            self._rule_name_var.set("None")
            self._addon_rule_combo.configure(values=("None",))
            self._addon_rule_status_var.set("skipped")
            self._addon_rule_category_var.set("None")
            self._set_rule_description("")
            self._apply_rule_combo_state()
            return
        try:
            data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:
            self._set_info_output(f"Failed to load rule file:\n{exc}")
            return
        if not isinstance(data, dict):
            data = {}
        try:
            from brkraw.specs.rules.validator import validate_rules
            stripped = {k: v for k, v in data.items() if k != "__meta__"}
            validate_rules(stripped)
        except Exception as exc:
            messagebox.showerror("Rule", f"Rule validation failed:\n{exc}")
        choices: Dict[str, Dict[str, Any]] = {}
        for category, items in data.items():
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "Unnamed")
                display = name
                rule = dict(item)
                rule["__category__"] = category
                choices[display] = rule
        self._addon_rule_choices = choices
        values = sorted(choices.keys()) if choices else ["None"]
        self._addon_rule_combo.configure(values=values)
        if values:
            self._rule_name_var.set(values[0])
        self._update_rule_details()
        self._apply_rule_combo_state()

    def _set_rule_description(self, text: str) -> None:
        self._addon_rule_desc_var.set(text)

    def _update_rule_details(self) -> None:
        display = (self._rule_name_var.get() or "").strip()
        rule = self._addon_rule_choices.get(display)
        if rule is None:
            self._addon_rule_category_var.set("None")
            self._addon_rule_status_var.set("skipped")
            self._set_rule_description("")
            return
        category = str(rule.get("__category__", ""))
        self._addon_rule_category_var.set(category or "None")
        self._set_rule_description(str(rule.get("description") or ""))
        status = "skipped"
        if self._scan is not None:
            match = self._resolve_rule_match(category, rule)
            status = "applied" if match else "skipped"
        self._addon_rule_status_var.set(status)
        if self._addon_spec_auto_var.get():
            self._update_spec_details()
        self._apply_rule_to_output()

    def _apply_rule_to_output(self) -> None:
        display = (self._rule_name_var.get() or "").strip()
        rule = self._addon_rule_choices.get(display)
        if rule is None:
            return
        category = str(rule.get("__category__", ""))
        if not self._addon_spec_auto_var.get():
            self._set_info_output({"rule": rule.get("name"), "status": self._addon_rule_status_var.get()})
            return
        if category not in {"info_spec", "metadata_spec"}:
            self._set_info_output({"rule": rule.get("name"), "status": self._addon_rule_status_var.get()})
            return
        path = self._resolve_rule_match(category, rule)
        if not path:
            self._set_info_output("Rule did not match for the current scan.")
            return
        display = self._addon_spec_display_by_path.get(str(path), str(path))
        self._addon_spec_file_var.set(display)
        self._update_spec_details()
        data = self._apply_spec_to_scan(kind=category, spec_path=str(path), reco_id=self._current_reco_id)
        self._set_info_output(data)

    def _on_rule_selected(self) -> None:
        if bool(self._addon_rule_auto_var.get()):
            self._apply_auto_rule_selection()
            return
        self._update_rule_details()

    def _on_rule_auto_toggle(self) -> None:
        auto = bool(self._addon_rule_auto_var.get())
        if self._addon_rule_combo is not None:
            try:
                self._addon_rule_combo.state(["disabled"] if auto else ["!disabled"])
            except Exception:
                self._addon_rule_combo.configure(state="disabled" if auto else "readonly")
        if self._addon_rule_file_combo is not None:
            try:
                self._addon_rule_file_combo.state(["disabled"] if auto else ["!disabled"])
            except Exception:
                self._addon_rule_file_combo.configure(state="disabled" if auto else "readonly")
        for btn in (self._addon_rule_browse_button, self._addon_rule_new_button):
            if btn is None:
                continue
            btn.configure(state=tk.DISABLED if auto else tk.NORMAL)
        if auto:
            self._apply_auto_rule_selection()
        self._update_rule_details()
        self._apply_rule_combo_state()

    def _apply_auto_rule_selection(self) -> None:
        rule = self._auto_applied_rule()
        if rule is None:
            self._addon_rule_file_var.set("None")
            self._rule_name_var.set("None")
            self._load_rule_file(None)
            return
        rule_name = str(rule.get("name") or "None")
        category = str(rule.get("__category__", ""))
        use = str(rule.get("use") or "")
        match = self._find_rule_entry_file(rule_name, category, use)
        if match:
            file_path = match
            display = self._addon_rule_display_by_path.get(file_path, file_path)
            self._addon_rule_file_var.set(display)
            self._load_rule_file(file_path)
        else:
            self._addon_rule_file_var.set("None")
            self._load_rule_file(None)
        if self._addon_rule_combo is not None:
            if rule_name in self._addon_rule_combo["values"]:
                self._rule_name_var.set(rule_name)
            else:
                self._rule_name_var.set(rule_name)

    def _apply_rule_combo_state(self) -> None:
        auto = bool(self._addon_rule_auto_var.get())
        if self._addon_rule_file_combo is not None:
            has_files = bool(self._addon_rule_file_map)
            state = "disabled" if auto else ("readonly" if has_files else "disabled")
            try:
                self._addon_rule_file_combo.state(["disabled"] if state == "disabled" else ["!disabled"])
            except Exception:
                pass
            self._addon_rule_file_combo.configure(state=state)
        if self._addon_rule_combo is not None:
            has_choices = bool(self._addon_rule_choices)
            state = "disabled" if auto else ("readonly" if has_choices else "disabled")
            try:
                self._addon_rule_combo.state(["disabled"] if state == "disabled" else ["!disabled"])
            except Exception:
                pass
            self._addon_rule_combo.configure(state=state)

    def _find_rule_entry_file(self, name: str, category: str, use: str) -> Optional[str]:
        try:
            installed = addon_app.list_installed(root=resolve_root(None))
        except Exception:
            return None
        rules = installed.get("rules", []) if isinstance(installed, dict) else []
        paths = config_core.paths(root=None)
        for entry in rules:
            if not isinstance(entry, dict):
                continue
            if entry.get("name") != name:
                continue
            if category and entry.get("category") != category:
                continue
            if use and entry.get("use") != use:
                continue
            relpath = entry.get("file")
            if relpath:
                return str((paths.rules_dir / relpath).resolve())
        return None
    def _on_rule_file_selected(self) -> None:
        path = self._resolve_rule_file_selection(self._addon_rule_file_var.get())
        self._load_rule_file(path)

    def _refresh_spec_choices(self) -> None:
        specs = self._installed_specs()
        choices: Dict[str, Dict[str, Any]] = {}
        self._addon_spec_display_by_path = {}
        paths = config_core.paths(root=None)
        for spec in specs:
            file_name = spec.get("file") or ""
            if not file_name:
                continue
            basename = Path(file_name).name
            display = basename
            if display in choices:
                display = f"{basename} ({file_name})"
            spec_path = str((paths.specs_dir / file_name).resolve())
            record = dict(spec)
            record["path"] = spec_path
            choices[display] = record
            self._addon_spec_display_by_path[spec_path] = display

        for path in self._addon_spec_session_files:
            if not path:
                continue
            if path in self._addon_spec_display_by_path:
                continue
            choices[path] = {"path": path}
            self._addon_spec_display_by_path[path] = path

        self._addon_spec_choices = choices
        values = sorted(choices.keys()) if choices else ["None"]
        self._addon_spec_combo.configure(values=values, state="readonly" if choices else "disabled")
        if values and (self._addon_spec_file_var.get() or "").strip() in ("", "None"):
            self._addon_spec_file_var.set(values[0])

    def _on_spec_auto_toggle(self) -> None:
        if self._addon_spec_combo is not None:
            try:
                self._addon_spec_combo.state(["disabled"] if self._addon_spec_auto_var.get() else ["!disabled"])
            except Exception:
                state = "disabled" if self._addon_spec_auto_var.get() else "readonly"
                try:
                    self._addon_spec_combo.configure(state=state)
                except Exception:
                    pass
        for btn in (self._addon_spec_browse_button, self._addon_spec_new_button):
            if btn is None:
                continue
            try:
                btn.configure(state=tk.DISABLED if self._addon_spec_auto_var.get() else tk.NORMAL)
            except Exception:
                pass
        self._update_spec_details()

    def _on_spec_file_selected(self) -> None:
        if self._addon_spec_auto_var.get():
            self._addon_spec_auto_var.set(False)
        self._update_spec_details()

    def _set_spec_description(self, text: str) -> None:
        self._addon_spec_desc_var.set(text)

    def _format_name_version(self, name: str, version: str) -> str:
        name = name.strip() if name else ""
        version = version.strip() if version else ""
        if not name:
            return "None"
        if not version or version in {"<Unknown>", "None"}:
            return name
        prefix = "" if version.startswith("v") else "v"
        return f"{name} {prefix}{version}"

    def _spec_record_from_path(self, path: Optional[str]) -> Dict[str, Any]:
        if not path:
            return {}
        try:
            raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        except Exception:
            return {"path": path}
        if not isinstance(raw, dict):
            return {"path": path}
        meta = raw.get("__meta__")
        if not isinstance(meta, dict):
            meta = {}
        record: Dict[str, Any] = {"path": path}
        for key in ("name", "version", "description", "category"):
            value = meta.get(key)
            if value is not None:
                record[key] = str(value)
        return record

    def _update_spec_details(self) -> None:
        if self._addon_spec_auto_var.get():
            display = (self._rule_name_var.get() or "").strip()
            rule = self._addon_rule_choices.get(display)
            if rule is None:
                self._addon_spec_status_var.set("skipped")
                self._addon_spec_name_var.set("None")
                self._set_spec_description("")
                return
            category = str(rule.get("__category__", ""))
            path = self._resolve_rule_match(category, rule) if self._scan is not None else None
            if path:
                display_name = self._addon_spec_display_by_path.get(str(path), str(path))
                self._addon_spec_file_var.set(display_name)
                self._addon_spec_status_var.set("applied")
            else:
                self._addon_spec_status_var.set("skipped")
            record = self._spec_record_from_path(path)
            if record:
                self._addon_spec_name_var.set(
                    self._format_name_version(record.get("name", ""), record.get("version", ""))
                )
                self._set_spec_description(str(record.get("description") or ""))
            else:
                self._addon_spec_name_var.set(Path(path).name if path else "None")
                self._set_spec_description("")
            return

        selection = (self._addon_spec_file_var.get() or "").strip()
        record = self._addon_spec_choices.get(selection)
        if record:
            path = record.get("path") or ""
            self._addon_spec_name_var.set(
                self._format_name_version(str(record.get("name", "")), str(record.get("version", "")))
            )
            self._set_spec_description(str(record.get("description") or ""))
        else:
            path = selection if selection not in ("None", "") else None
            record = self._spec_record_from_path(path)
            if record:
                self._addon_spec_name_var.set(
                    self._format_name_version(record.get("name", ""), record.get("version", ""))
                )
                self._set_spec_description(str(record.get("description") or ""))
            else:
                self._addon_spec_name_var.set(Path(path).name if path else "None")
                self._set_spec_description("")
        self._addon_spec_status_var.set("skipped")

    def _apply_selected_spec(self) -> None:
        if self._scan is None:
            self._set_info_output("No scan selected.")
            return
        spec_path = self._resolve_spec_path()
        if not spec_path:
            self._set_info_output("No spec selected.")
            return
        kind = "info_spec"
        if self._addon_spec_auto_var.get():
            display = (self._rule_name_var.get() or "").strip()
            rule = self._addon_rule_choices.get(display)
            if rule is not None:
                candidate = str(rule.get("__category__", "info_spec"))
                if candidate in {"info_spec", "metadata_spec"}:
                    kind = candidate
        else:
            record = self._spec_record_from_path(spec_path)
            candidate = str(record.get("category", "")).strip()
            if candidate in {"info_spec", "metadata_spec"}:
                kind = candidate
        self._apply_spec_file_with_validation(kind=kind, path=spec_path)

    def _resolve_spec_path(self) -> Optional[str]:
        if self._addon_spec_auto_var.get():
            display = (self._rule_name_var.get() or "").strip()
            rule = self._addon_rule_choices.get(display)
            if rule is None:
                return None
            category = str(rule.get("__category__", ""))
            return self._resolve_rule_match(category, rule)
        selection = (self._addon_spec_file_var.get() or "").strip()
        if not selection or selection == "None":
            return None
        record = self._addon_spec_choices.get(selection)
        if record:
            path = record.get("path")
            if path:
                return str(path)
        if Path(selection).exists():
            return selection
        return None

    def _apply_spec_file_with_validation(self, *, kind: str, path: str) -> None:
        if not Path(path).exists():
            messagebox.showwarning("Spec", f"Spec file not found:\n{path}")
            return
        try:
            from brkraw.specs import remapper as remapper_core
            raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
            remapper_core.validate_spec(raw)
        except Exception as exc:
            messagebox.showerror("Spec", f"Spec validation failed:\n{exc}")
            return
        data = self._apply_spec_to_scan(kind=kind, spec_path=path, reco_id=self._current_reco_id)
        self._addon_spec_status_var.set("applied" if data else "skipped")
        self._set_info_output(data)

    def _browse_rule_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Select rule YAML",
            filetypes=(("YAML", "*.yaml *.yml"), ("All files", "*.*")),
        )
        if not path:
            return
        if path not in self._addon_rule_session_files:
            self._addon_rule_session_files.append(path)
        self._refresh_rule_files()
        self._addon_rule_file_var.set(path)
        self._load_rule_file(path)

    def _new_rule_file(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Create new rule file",
            defaultextension=".yaml",
            filetypes=(("YAML", "*.yaml *.yml"), ("All files", "*.*")),
        )
        if not path:
            return
        if path not in self._addon_rule_session_files:
            self._addon_rule_session_files.append(path)
        self._refresh_rule_files()
        self._addon_rule_file_var.set(path)
        self._open_yaml_editor(path=Path(path), kind="rule")

    def _edit_rule_file(self) -> None:
        path = self._resolve_rule_file_selection(self._addon_rule_file_var.get())
        if not path:
            return
        self._open_yaml_editor(path=Path(path), kind="rule")

    def _browse_spec_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Select spec YAML",
            filetypes=(("YAML", "*.yaml *.yml"), ("All files", "*.*")),
        )
        if not path:
            return
        self._addon_spec_auto_var.set(False)
        if path not in self._addon_spec_session_files:
            self._addon_spec_session_files.append(path)
        self._refresh_spec_choices()
        self._addon_spec_file_var.set(path)
        self._update_spec_details()

    def _new_spec_file(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Create new spec file",
            defaultextension=".yaml",
            filetypes=(("YAML", "*.yaml *.yml"), ("All files", "*.*")),
        )
        if not path:
            return
        self._addon_spec_auto_var.set(False)
        if path not in self._addon_spec_session_files:
            self._addon_spec_session_files.append(path)
        self._refresh_spec_choices()
        self._addon_spec_file_var.set(path)
        self._open_yaml_editor(path=Path(path), kind="spec")

    def _edit_spec_file(self) -> None:
        path = self._resolve_spec_path()
        if not path:
            return
        self._open_yaml_editor(path=Path(path), kind="spec")

    def _browse_context_map(self) -> None:
        path = filedialog.askopenfilename(
            title="Select context map YAML",
            filetypes=(("YAML", "*.yaml *.yml"), ("All files", "*.*")),
        )
        if not path:
            return
        self._addon_context_map_var.set(path)
        self._update_layout_controls()

    def _new_context_map(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Create new context map",
            defaultextension=".yaml",
            filetypes=(("YAML", "*.yaml *.yml"), ("All files", "*.*")),
        )
        if not path:
            return
        self._addon_context_map_var.set(path)
        self._update_layout_controls()
        self._open_yaml_editor(path=Path(path), kind="context_map")

    def _edit_context_map(self) -> None:
        path = (self._addon_context_map_var.get() or "").strip()
        if not path or path == "None":
            return
        self._open_yaml_editor(path=Path(path), kind="context_map")

    def _apply_context_map(self) -> None:
        path = (self._addon_context_map_var.get() or "").strip()
        if not path or path == "None":
            self._set_info_output("No context map selected.")
            return
        if not Path(path).exists():
            messagebox.showwarning("Context Map", f"Context map not found:\n{path}")
            return
        spec_path = self._resolve_spec_path()
        if not spec_path:
            self._set_info_output("No spec selected.")
            return

        kind = "info_spec"
        if self._addon_spec_auto_var.get():
            display = (self._rule_name_var.get() or "").strip()
            rule = self._addon_rule_choices.get(display)
            if rule is not None:
                candidate = str(rule.get("__category__", "info_spec"))
                if candidate in {"info_spec", "metadata_spec"}:
                    kind = candidate
        else:
            record = self._spec_record_from_path(spec_path)
            candidate = str(record.get("category", "")).strip()
            if candidate in {"info_spec", "metadata_spec"}:
                kind = candidate

        try:
            from brkraw.specs import remapper as remapper_core
            raw = yaml.safe_load(Path(spec_path).read_text(encoding="utf-8"))
            remapper_core.validate_spec(raw)
        except Exception as exc:
            messagebox.showerror("Spec", f"Spec validation failed:\n{exc}")
            return
        current = self._apply_spec_to_scan(kind=kind, spec_path=spec_path, reco_id=self._current_reco_id)
        self._addon_spec_status_var.set("applied" if current else "skipped")

        try:
            remapper_core.validate_context_map(Path(path))
            map_data = remapper_core.load_context_map(path)
        except Exception as exc:
            messagebox.showerror("Context Map", f"Context map validation failed:\n{exc}")
            return
        target = None
        if self._addon_spec_auto_var.get():
            display = (self._rule_name_var.get() or "").strip()
            rule = self._addon_rule_choices.get(display)
            if rule is not None:
                target = rule.get("__category__")
        else:
            selection = (self._addon_spec_file_var.get() or "").strip()
            record = self._addon_spec_choices.get(selection)
            if record is not None:
                target = record.get("category")
                if not target:
                    meta_record = self._spec_record_from_path(record.get("path"))
                    target = meta_record.get("category")
        if target and not self._context_map_has_targets(map_data):
            target = None
        try:
            remapped = remapper_core.apply_context_map(current, map_data, target=target, context=None)
        except Exception as exc:
            messagebox.showerror("Context Map", f"Failed to apply context map:\n{exc}")
            return
        self._addon_context_status_var.set("applied")
        self._set_info_output(remapped)

    def _context_map_has_targets(self, map_data: Mapping[str, Any]) -> bool:
        for raw_rule in map_data.values():
            if self._context_rule_targets(raw_rule):
                return True
        return False

    def _context_rule_targets(self, raw_rule: Any) -> bool:
        if isinstance(raw_rule, Mapping):
            if isinstance(raw_rule.get("target"), str):
                return True
            cases = raw_rule.get("cases")
            if isinstance(cases, list):
                return any(self._context_rule_targets(case) for case in cases)
            return False
        if isinstance(raw_rule, list):
            return any(self._context_rule_targets(item) for item in raw_rule)
        return False

    def _open_yaml_editor(self, *, path: Path, kind: str) -> None:
        window = tk.Toplevel(self)
        window.title(f"Edit {kind.replace('_', ' ').title()}")
        window.geometry("900x700")
        window.minsize(720, 520)

        container = ttk.Frame(window, padding=(10, 10))
        container.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(2, weight=1)

        meta_frame = ttk.LabelFrame(container, text="Metadata", padding=(8, 8))
        meta_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        meta_frame.columnconfigure(1, weight=1)
        meta_frame.grid_remove()

        meta_fields = self._build_meta_form(meta_frame, kind=kind)
        show_meta = tk.BooleanVar(value=False)

        def _toggle_meta() -> None:
            if show_meta.get():
                meta_frame.grid()
            else:
                meta_frame.grid_remove()

        header = ttk.Frame(container)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Checkbutton(header, text="Metadata", variable=show_meta, command=_toggle_meta).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(header, text="Update", command=lambda: _save_editor(path)).grid(row=0, column=1, sticky="e")
        ttk.Button(header, text="Save As", command=lambda: _save_as_editor()).grid(
            row=0, column=2, sticky="e", padx=(6, 0)
        )

        body_text = tk.Text(container, wrap="none")
        body_text.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        body_scroll = ttk.Scrollbar(container, orient="vertical", command=body_text.yview)
        body_scroll.grid(row=2, column=1, sticky="ns", pady=(10, 0))
        body_text.configure(yscrollcommand=body_scroll.set)

        snippet_frame = ttk.Frame(container)
        snippet_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        snippet_frame.columnconfigure(1, weight=1)
        ttk.Label(snippet_frame, text="Snippets").grid(row=0, column=0, sticky="w")
        snippet_buttons = ttk.Frame(snippet_frame)
        snippet_buttons.grid(row=0, column=1, sticky="e")

        def _apply_snippet(name: str) -> None:
            snippets = self._load_snippets(kind)
            snippet = snippets.get(name)
            if snippet is None:
                return
            body_text.insert(tk.INSERT, snippet)

        def _delete_snippet(name: str) -> None:
            target = self._snippets_dir(kind) / f"{name}.yaml"
            if not target.exists():
                return
            if not messagebox.askyesno("Snippet", f"Delete snippet '{name}'?"):
                return
            try:
                target.unlink()
            except Exception as exc:
                messagebox.showerror("Snippet", f"Failed to delete:\n{exc}")
                return
            _render_snippets()

        def _open_snippet_editor(*, name: Optional[str], content: str) -> None:
            editor = tk.Toplevel(window)
            editor.title("Register Snippet" if name is None else f"Modify Snippet: {name}")
            editor.geometry("640x480")
            editor.minsize(520, 360)

            frame = ttk.Frame(editor, padding=(10, 10))
            frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
            frame.columnconfigure(1, weight=1)
            frame.rowconfigure(1, weight=1)

            ttk.Label(frame, text="Name").grid(row=0, column=0, sticky="w")
            name_var = tk.StringVar(value=name or "")
            name_entry = ttk.Entry(frame, textvariable=name_var)
            name_entry.grid(row=0, column=1, sticky="ew", padx=(8, 0))

            body = tk.Text(frame, wrap="none")
            body.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
            body.insert("1.0", content)

            def _register() -> None:
                new_name = name_var.get().strip()
                if not new_name:
                    messagebox.showwarning("Snippet", "Snippet name is required.")
                    return
                target = self._snippets_dir(kind) / f"{new_name}.yaml"
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists() and new_name != name:
                    if not messagebox.askyesno("Snippet", f"Overwrite snippet '{new_name}'?"):
                        return
                try:
                    target.write_text(body.get("1.0", tk.END), encoding="utf-8")
                except Exception as exc:
                    messagebox.showerror("Snippet", f"Failed to save:\n{exc}")
                    return
                _render_snippets()
                editor.destroy()

            ttk.Button(frame, text="Register", command=_register).grid(row=2, column=1, sticky="e", pady=(8, 0))

        def _load_editor() -> None:
            if path.exists():
                raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            else:
                raw = {}
            if isinstance(raw, dict):
                raw_dict = cast(Dict[str, Any], raw)
            else:
                raw_dict = {}
            meta: Dict[str, Any] = (
                cast(Dict[str, Any], raw_dict.get("__meta__"))
                if isinstance(raw_dict.get("__meta__"), dict)
                else {}
            )
            body = {k: v for k, v in raw_dict.items() if k != "__meta__"}
            self._set_meta_form_values(meta_fields, meta)
            body_text.delete("1.0", tk.END)
            body_text.insert(tk.END, self._format_yaml(body))

        def _collect_body() -> Dict[str, Any]:
            content = body_text.get("1.0", tk.END)
            data = yaml.safe_load(content) if content.strip() else {}
            if data is None:
                data = {}
            if not isinstance(data, dict):
                raise ValueError("YAML body must be a mapping.")
            return data

        def _collect_meta() -> Dict[str, Any]:
            return self._collect_meta_form_values(meta_fields)

        def _validate(kind: str, data: Dict[str, Any]) -> None:
            if kind == "rule":
                from brkraw.specs.rules.validator import validate_rules
                stripped = {k: v for k, v in data.items() if k != "__meta__"}
                validate_rules(stripped)
                from brkraw.specs.meta.validator import validate_meta
                meta = data.get("__meta__", {})
                if meta:
                    validate_meta(meta, raise_on_error=True)
                return
            if kind == "spec":
                from brkraw.specs.remapper.validator import validate_spec
                validate_spec(data)
                return
            if kind == "context_map":
                from brkraw.specs.remapper.validator import validate_map_data
                validate_map_data(data)
                return

        def _save_editor(target: Path) -> None:
            try:
                body = _collect_body()
                meta = _collect_meta()
                payload = dict(body)
                if meta:
                    payload["__meta__"] = meta
                _validate(kind, payload)
            except Exception as exc:
                messagebox.showerror("Editor", f"Validation failed:\n{exc}")
                return
            try:
                target.write_text(self._format_yaml(payload), encoding="utf-8")
            except Exception as exc:
                messagebox.showerror("Editor", f"Failed to save:\n{exc}")
                return
            messagebox.showinfo("Editor", f"Saved:\n{target}")
            self._refresh_addon_controls()

        def _save_as_editor() -> None:
            target = filedialog.asksaveasfilename(
                title="Save As",
                defaultextension=".yaml",
                filetypes=(("YAML", "*.yaml *.yml"), ("All files", "*.*")),
            )
            if not target:
                return
            _save_editor(Path(target))

        def _add_snippet() -> None:
            _open_snippet_editor(name=None, content="")

        def _render_snippets() -> None:
            for child in snippet_buttons.winfo_children():
                child.destroy()
            snippets = self._load_snippets(kind)
            custom_names = {path.stem for path in self._snippets_dir(kind).glob("*.yaml")}
            col = 0
            for name in snippets:
                btn = ttk.Button(snippet_buttons, text=name, command=lambda n=name: _apply_snippet(n))
                btn.grid(row=0, column=col, padx=(0, 6), sticky="e")
                if name in custom_names:
                    def _show_menu(event: tk.Event, snippet_name: str) -> None:
                        menu = tk.Menu(snippet_buttons, tearoff=0)
                        menu.add_command(
                            label="Modify",
                            command=lambda: _open_snippet_editor(
                                name=snippet_name,
                                content=(self._snippets_dir(kind) / f"{snippet_name}.yaml").read_text(encoding="utf-8"),
                            ),
                        )
                        menu.add_command(label="Delete", command=lambda: _delete_snippet(snippet_name))
                        menu.tk_popup(event.x_root, event.y_root)

                    btn.bind("<Button-3>", lambda evt, n=name: _show_menu(evt, n))
                    btn.bind("<Button-2>", lambda evt, n=name: _show_menu(evt, n))
                    btn.bind("<Control-Button-1>", lambda evt, n=name: _show_menu(evt, n))
                col += 1
            ttk.Button(snippet_buttons, text="Add Snippet", command=_add_snippet).grid(
                row=0, column=col, padx=(0, 6), sticky="e"
            )

        if kind == "spec" and "transforms_source" in meta_fields:
            field_type, widget = meta_fields["transforms_source"]
            if field_type == "text" and isinstance(widget, tk.Text):
                picker = ttk.Frame(meta_frame)
                picker.grid(row=len(meta_fields), column=0, columnspan=2, sticky="ew", pady=(6, 0))
                picker.columnconfigure(1, weight=1)
                ttk.Label(picker, text="transform").grid(row=0, column=0, sticky="w")
                transform_var = tk.StringVar(value="")
                combo = ttk.Combobox(
                    picker,
                    textvariable=transform_var,
                    state="readonly",
                    values=self._installed_transform_choices(),
                )
                combo.grid(row=0, column=1, sticky="ew", padx=(8, 6))

                def _add_transform(value: str) -> None:
                    self._append_transform_source(widget, value)

                def _browse_transform() -> None:
                    choice = self._browse_transform_source(base_dir=path.parent)
                    if choice:
                        _add_transform(choice)

                ttk.Button(picker, text="Add", command=lambda: _add_transform(transform_var.get())).grid(
                    row=0, column=2, sticky="e"
                )
                ttk.Button(picker, text="Browse", command=_browse_transform).grid(row=0, column=3, sticky="e")

        _load_editor()
        _render_snippets()

    def _open_text_editor(self, *, path: Path, title: str) -> None:
        window = tk.Toplevel(self)
        window.title(title)
        window.geometry("900x700")
        window.minsize(720, 520)

        container = ttk.Frame(window, padding=(10, 10))
        container.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(1, weight=1)

        header = ttk.Frame(container)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Button(header, text="Update", command=lambda: _save_editor(path)).grid(row=0, column=1, sticky="e")
        ttk.Button(header, text="Save As", command=lambda: _save_as_editor()).grid(
            row=0, column=2, sticky="e", padx=(6, 0)
        )

        body_text = tk.Text(container, wrap="none")
        body_text.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        body_scroll = ttk.Scrollbar(container, orient="vertical", command=body_text.yview)
        body_scroll.grid(row=1, column=1, sticky="ns", pady=(10, 0))
        body_text.configure(yscrollcommand=body_scroll.set)

        def _load_editor() -> None:
            if path.exists():
                body_text.delete("1.0", tk.END)
                body_text.insert(tk.END, path.read_text(encoding="utf-8"))

        def _save_editor(target: Path) -> None:
            try:
                target.write_text(body_text.get("1.0", tk.END), encoding="utf-8")
            except Exception as exc:
                messagebox.showerror("Editor", f"Failed to save:\n{exc}")
                return
            messagebox.showinfo("Editor", f"Saved:\n{target}")
            self._refresh_transform_files()

        def _save_as_editor() -> None:
            target = filedialog.asksaveasfilename(
                title="Save As",
                defaultextension=path.suffix or ".py",
                filetypes=(("Python", "*.py"), ("All files", "*.*")),
            )
            if not target:
                return
            _save_editor(Path(target))

        _load_editor()

    def _build_meta_form(self, parent: tk.Widget, *, kind: str) -> Dict[str, Tuple[str, tk.Widget]]:
        fields = self._meta_fields_for_kind(kind)
        widgets: Dict[str, Tuple[str, tk.Widget]] = {}
        row = 0
        for key, field_type in fields:
            ttk.Label(parent, text=key).grid(row=row, column=0, sticky="nw", pady=4)
            if field_type == "text":
                widget = tk.Text(parent, height=3, wrap="word")
                widget.grid(row=row, column=1, sticky="ew", pady=4)
            else:
                widget = ttk.Entry(parent)
                widget.grid(row=row, column=1, sticky="ew", pady=4)
            widgets[key] = (field_type, widget)
            row += 1
        return widgets

    def _set_meta_form_values(self, widgets: Dict[str, Tuple[str, tk.Widget]], meta: Dict[str, Any]) -> None:
        for key, (field_type, widget) in widgets.items():
            value = meta.get(key)
            if field_type == "text":
                text_widget = cast(tk.Text, widget)
                text_widget.delete("1.0", tk.END)
                if value is not None:
                    text_widget.insert(tk.END, self._format_yaml(value))
            else:
                entry = cast(ttk.Entry, widget)
                entry.delete(0, tk.END)
                if value is not None:
                    entry.insert(0, str(value))

    def _collect_meta_form_values(self, widgets: Dict[str, Tuple[str, tk.Widget]]) -> Dict[str, Any]:
        meta: Dict[str, Any] = {}
        for key, (field_type, widget) in widgets.items():
            if field_type == "text":
                text_widget = cast(tk.Text, widget)
                raw = text_widget.get("1.0", tk.END).strip()
                if not raw:
                    continue
                value = yaml.safe_load(raw)
                meta[key] = value
            else:
                entry = cast(ttk.Entry, widget)
                value = entry.get().strip()
                if value:
                    meta[key] = value
        return meta

    def _meta_fields_for_kind(self, kind: str) -> list[Tuple[str, str]]:
        meta_props = self._load_schema_props("meta.yaml")
        fields: list[Tuple[str, str]] = []
        if kind in {"rule", "spec"}:
            fields.extend(self._schema_props_to_fields(meta_props))
        if kind == "spec":
            remapper_meta = self._load_schema_props("remapper.yaml", path=("properties", "__meta__", "properties"))
            fields.extend(self._schema_props_to_fields(remapper_meta))
        if kind == "context_map":
            map_meta = self._load_schema_props("context_map.yaml", path=("properties", "__meta__", "properties"))
            fields.extend(self._schema_props_to_fields(map_meta))
        return fields

    def _load_schema_props(
        self,
        name: str,
        *,
        path: Tuple[str, ...] = ("properties",),
    ) -> Dict[str, Any]:
        try:
            from importlib import resources
        except Exception:
            return {}
        try:
            with resources.files("brkraw.schema").joinpath(name).open("r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle)
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        for key in path:
            if not isinstance(data, dict):
                return {}
            data = data.get(key, {})
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _schema_props_to_fields(props: Dict[str, Any]) -> list[Tuple[str, str]]:
        fields: list[Tuple[str, str]] = []
        for key, spec in props.items():
            field_type = "entry"
            if isinstance(spec, dict):
                spec_type = spec.get("type")
                if spec_type in {"array", "object"} or "anyOf" in spec or "oneOf" in spec:
                    field_type = "text"
            fields.append((key, field_type))
        return fields

    def _snippets_dir(self, kind: str) -> Path:
        root = resolve_root(None)
        return root / "viewer" / "snippets" / kind

    def _installed_transform_choices(self) -> list[str]:
        try:
            installed = addon_app.list_installed(root=resolve_root(None))
        except Exception:
            installed = {}
        transforms = installed.get("transforms", []) if isinstance(installed, dict) else []
        choices: list[str] = []
        for entry in transforms:
            if not isinstance(entry, dict):
                continue
            relpath = entry.get("file")
            if relpath:
                choices.append(relpath)
        return choices or ["None"]

    def _browse_transform_source(self, *, base_dir: Path) -> Optional[str]:
        path = filedialog.askopenfilename(
            title="Select transform file",
            initialdir=str(base_dir),
            filetypes=(("Python", "*.py"), ("All files", "*.*")),
        )
        if not path:
            return None
        return self._normalize_transform_source(Path(path))

    def _normalize_transform_source(self, path: Path) -> str:
        transforms_dir = config_core.paths(root=None).transforms_dir
        try:
            return str(path.resolve().relative_to(transforms_dir))
        except Exception:
            return path.name

    def _append_transform_source(self, widget: tk.Text, value: str) -> None:
        if not value or value == "None":
            return
        raw = widget.get("1.0", tk.END).strip()
        if not raw:
            data: Any = value
        else:
            try:
                data = yaml.safe_load(raw)
            except Exception:
                data = raw
            if isinstance(data, list):
                if value not in data:
                    data.append(value)
            elif isinstance(data, str):
                data = [data, value] if data != value else data
            else:
                data = [value]
        widget.delete("1.0", tk.END)
        widget.insert(tk.END, self._format_yaml(data))

    def _load_snippets(self, kind: str) -> Dict[str, str]:
        snippets: Dict[str, str] = dict(self._load_default_snippets(kind))
        folder = self._snippets_dir(kind)
        if folder.exists():
            for path in sorted(folder.glob("*.yaml"), key=lambda p: p.name):
                try:
                    snippets[path.stem] = path.read_text(encoding="utf-8")
                except Exception:
                    continue
        return snippets

    def _load_default_snippets(self, kind: str) -> Dict[str, str]:
        try:
            from importlib import resources
        except Exception:
            return {}
        snippets: Dict[str, str] = {}
        try:
            base = resources.files("brkraw_viewer").joinpath("snippets").joinpath(kind)
        except Exception:
            return {}
        if not base.is_dir():
            return {}
        for path in sorted(base.iterdir(), key=lambda p: p.name):
            if not path.name.endswith(".yaml"):
                continue
            try:
                stem = path.name.rsplit(".", 1)[0]
                snippets[stem] = path.read_text(encoding="utf-8")
            except Exception:
                continue
        return snippets

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
            self._render_param_results([])
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

        self._render_param_results(matches[:500], truncated=max(len(matches) - 500, 0))

    def _render_param_results(
        self,
        matches: list[tuple[str, str, Any]],
        *,
        truncated: int = 0,
    ) -> None:
        self._params_results = list(matches)
        self._params_truncated = truncated
        self._render_param_results_from_cache()

    def _render_param_results_from_cache(self) -> None:
        tree = getattr(self, "_params_tree", None)
        if tree is None:
            return
        tree.delete(*tree.get_children())
        matches = list(self._params_results)
        sort_key = self._params_sort_key
        if sort_key:
            matches = sorted(
                matches,
                key=lambda item: self._params_sort_value(item, sort_key),
                reverse=not self._params_sort_ascending,
            )
        for src, path, value in matches:
            value_text = self._format_value(value)
            type_name = type(value).__name__
            tree.insert("", tk.END, values=(src, path, type_name, value_text))
        if self._params_truncated:
            tree.insert("", tk.END, values=("", "", "", f"... {self._params_truncated} more result(s)"))

    def _params_sort_by(self, key: str) -> None:
        if key == self._params_sort_key:
            self._params_sort_ascending = not self._params_sort_ascending
        else:
            self._params_sort_key = key
            self._params_sort_ascending = True
        self._update_params_sort_heading()
        self._render_param_results_from_cache()

    def _update_params_sort_heading(self) -> None:
        tree = getattr(self, "_params_tree", None)
        if tree is None:
            return
        for key, title in self._params_column_titles.items():
            label = title
            if key == self._params_sort_key:
                arrow = "▲" if self._params_sort_ascending else "▼"
                label = f"{title} {arrow}"
            tree.heading(key, text=label)

    def _params_sort_value(self, item: tuple[str, str, Any], key: str) -> Tuple[int, float, str]:
        src, path, value = item
        if key == "file":
            return self._params_sort_scalar(src)
        if key == "key":
            return self._params_sort_scalar(path)
        if key == "type":
            return self._params_sort_scalar(type(value).__name__)
        if key == "value":
            return self._params_sort_scalar(self._format_value(value))
        return self._params_sort_scalar("")

    @staticmethod
    def _params_sort_scalar(value: Any) -> Tuple[int, float, str]:
        if value is None:
            return (2, 0.0, "")
        if isinstance(value, (int, float)):
            return (0, float(value), "")
        text = str(value)
        try:
            return (0, float(text), text.casefold())
        except Exception:
            return (1, 0.0, text.casefold())

    def _update_params_summary(self) -> None:
        if self._scan is None:
            for var in self._params_summary_vars.values():
                var.set("")
            return
        _, scan_yaml = self._layout_builtin_info_spec_paths()
        info: Dict[str, Any] = {}
        if scan_yaml:
            try:
                info = info_resolver.scan(cast(Any, self._scan), spec_source=scan_yaml)
            except Exception:
                info = {}
        for key, var in self._params_summary_vars.items():
            var.set(self._format_value(info.get(key, "")))

    def _set_info_output(self, payload: Any) -> None:
        self._addon_output_payload = payload
        if isinstance(payload, str):
            text = payload
        else:
            text = self._format_yaml(payload)
        self._info_output_text.configure(state=tk.NORMAL)
        self._info_output_text.delete("1.0", tk.END)
        self._info_output_text.insert(tk.END, text)
        self._info_output_text.configure(state=tk.DISABLED)

    def _save_addon_output(self) -> None:
        payload = self._addon_output_payload
        if payload is None:
            messagebox.showinfo("Save Output", "No output to save.")
            return
        target = filedialog.asksaveasfilename(
            title="Save output",
            defaultextension=".json",
            filetypes=(
                ("JSON", "*.json"),
                ("YAML", "*.yaml *.yml"),
                ("Text", "*.txt"),
                ("All files", "*.*"),
            ),
        )
        if not target:
            return
        path = Path(target)
        try:
            if isinstance(payload, dict):
                if path.suffix.lower() in {".yaml", ".yml"}:
                    content = self._format_yaml(payload)
                else:
                    content = json.dumps(payload, indent=2, sort_keys=False)
            else:
                content = str(payload)
            path.write_text(content, encoding="utf-8")
        except Exception as exc:
            messagebox.showerror("Save Output", f"Failed to save:\n{exc}")
            return
        messagebox.showinfo("Save Output", f"Saved:\n{path}")

    def _reset_addon_state(self) -> None:
        self._addon_rule_file_var.set("")
        self._rule_name_var.set("None")
        self._addon_rule_category_var.set("None")
        self._addon_rule_status_var.set("skipped")
        self._addon_spec_auto_var.set(True)
        self._addon_spec_file_var.set("")
        self._addon_spec_name_var.set("None")
        self._addon_spec_status_var.set("skipped")
        self._addon_context_map_var.set("")
        self._addon_context_status_var.set("skipped")
        self._refresh_addon_controls()
        if self._scan is None:
            self._set_info_output("No scan selected.")
        else:
            self._set_info_output(self._info_full or {})

    def _auto_applied_rule(self) -> Optional[Dict[str, Any]]:
        if self._scan is None:
            return None
        try:
            from brkraw.specs.rules.logic import rule_matches
        except Exception:
            return None
        try:
            rules = load_rules(root=resolve_root(None), validate=False)
        except Exception:
            return None
        base = resolve_root(None)
        for category in ("info_spec", "metadata_spec", "converter_hook"):
            selected = None
            for rule in rules.get(category, []):
                if not isinstance(rule, dict):
                    continue
                try:
                    matched = rule_matches(self._scan, rule, base=base)
                except Exception:
                    continue
                if matched:
                    selected = rule
            if selected is not None:
                return selected
        return None

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

    def _layout_info_spec_path(self) -> Optional[str]:
        return super()._layout_info_spec_path()

    def _layout_metadata_spec_path(self) -> Optional[str]:
        return super()._layout_metadata_spec_path()

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

    def _convert_subject_orientation(self) -> tuple[Optional[SubjectType], Optional[SubjectPose]]:
        return super()._convert_subject_orientation()

    def _estimate_slicepack_count(self) -> int:
        return super()._estimate_slicepack_count()

    def _planned_output_paths(self, *, preview: bool, count: Optional[int] = None) -> list[Path]:
        return super()._planned_output_paths(preview=preview, count=count)

    def _preview_convert_outputs(self) -> None:
        super()._preview_convert_outputs()

    def _convert_current_scan(self) -> None:
        super()._convert_current_scan()

    def _open_subject_window(self) -> None:
        if self._subject_window is not None and self._subject_window.winfo_exists():
            self._subject_window.lift()
            self._subject_window.focus_set()
            return
        self._build_subject_window()

    def _build_subject_window(self) -> None:
        window = tk.Toplevel(self)
        window.title("Study Info")
        window.geometry("720x280")
        window.minsize(560, 220)
        window.protocol("WM_DELETE_WINDOW", self._close_subject_window)
        self._subject_window = window

        frame = ttk.Frame(window, padding=(10, 10))
        frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(3, weight=1)

        self._subject_entries = {}
        for idx, (label, _) in enumerate(self._subject_fields):
            row = idx // 2
            col = (idx % 2) * 2
            ttk.Label(frame, text=label).grid(row=row, column=col, sticky="w", padx=6, pady=3)
            entry = ttk.Entry(frame, width=22)
            entry.grid(row=row, column=col + 1, sticky="ew", padx=(0, 6), pady=3)
            entry.configure(state="readonly")
            self._subject_entries[label] = entry

        self._update_subject_info()

    def _close_subject_window(self) -> None:
        if self._subject_window is None:
            return
        if self._subject_window.winfo_exists():
            try:
                self._subject_window.destroy()
            except Exception:
                pass
        self._subject_window = None
        self._subject_entries = {}

    def _update_subject_info(self) -> None:
        info = self._info_full or {}
        study_id = self._lookup_nested(info, ("Study", "ID"))
        subject_id = self._lookup_nested(info, ("Subject", "ID"))
        study_date = self._lookup_nested(info, ("Study", "Date"))
        summary_study_id = self._format_value(study_id) if study_id not in (None, "") else "None"
        summary_subject_id = self._format_value(subject_id) if subject_id not in (None, "") else "None"
        summary_study_date = self._format_study_date(study_date) or "None"
        self._subject_summary_vars["Study ID"].set(summary_study_id)
        self._subject_summary_vars["Subject ID"].set(summary_subject_id)
        self._subject_summary_vars["Study Date"].set(summary_study_date)
        for label, paths in self._subject_fields:
            value = None
            for path in paths:
                value = self._lookup_nested(info, path)
                if value not in (None, ""):
                    break
            entry = self._subject_entries.get(label)
            if entry is None:
                continue
            if label == "Study Date":
                value = self._format_study_date(value)
            entry.configure(state="normal")
            entry.delete(0, tk.END)
            entry.insert(0, self._format_value(value) if value is not None else "")
            entry.configure(state="readonly")

    @staticmethod
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

    def _on_subject_change(self, *_: object) -> None:
        if self._space_var.get() != "subject_ras":
            return
        if self._current_reco_id is None:
            return
        self._mark_viewer_dirty()
        self._maybe_load_viewer()

    def _on_tab_changed(self, *_: object) -> None:
        self._maybe_load_viewer()

    def _is_viewer_tab_active(self) -> bool:
        if "Viewer" in self._detached_tabs:
            return True
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
            bool(self._affine_flip_x_var.get()),
            bool(self._affine_flip_y_var.get()),
            bool(self._affine_flip_z_var.get()),
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

        extra = {
            "flip_x": bool(self._affine_flip_x_var.get()),
            "flip_y": bool(self._affine_flip_y_var.get()),
            "flip_z": bool(self._affine_flip_z_var.get()),
        }
        selected_space = (self._space_var.get() or "").strip()
        if selected_space not in {"raw", "scanner", "subject_ras"}:
            selected_space = "scanner"

        if selected_space in {"raw", "scanner"}:
            try:
                return self._safe_get_affine(
                    reco_id=reco_id,
                    space=selected_space,
                    override_subject_type=None,
                    override_subject_pose=None,
                    **extra,
                )
            except Exception:
                pass

            raw_affine = self._safe_get_affine(
                reco_id=reco_id,
                space="raw",
                override_subject_type=None,
                override_subject_pose=None,
                **extra,
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

        subject_type = self._cast_subject_type((self._subject_type_var.get() or "").strip())
        subject_pose = self._cast_subject_pose(
            f"{(self._pose_primary_var.get() or '').strip()}_{(self._pose_secondary_var.get() or '').strip()}"
        )

        for space_candidate in ("subject_ras", "subject", "scanner"):
            try:
                affine = self._safe_get_affine(
                    reco_id=reco_id,
                    space=space_candidate,
                    override_subject_type=subject_type,
                    override_subject_pose=subject_pose,
                    **extra,
                )
                if affine is not None:
                    return affine
            except Exception:
                continue

        raw_affine = self._safe_get_affine(
            reco_id=reco_id,
            space="raw",
            override_subject_type=None,
            override_subject_pose=None,
            **extra,
        )
        if raw_affine is None:
            return None
        affines = list(raw_affine) if isinstance(raw_affine, tuple) else [raw_affine]
        affines_subject = [
            affine_resolver.unwrap_to_scanner_xyz(np.asarray(aff), subject_type, subject_pose)
            for aff in affines
        ]
        return tuple(affines_subject) if isinstance(raw_affine, tuple) else affines_subject[0]

    def _safe_get_affine(self, *, reco_id: int, **kwargs: Any) -> Any:
        if self._scan is None:
            return None
        try:
            return self._scan.get_affine(reco_id=reco_id, **kwargs)
        except TypeError:
            return self._scan.get_affine(reco_id=reco_id)

    def _on_affine_change(self) -> None:
        self._maybe_load_viewer()

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
        if not self._widget_exists(self._extra_frame):
            self._extra_dim_vars = []
            self._extra_dim_scales = []
            return
        for widget in self._extra_frame.winfo_children():
            widget.destroy()
        self._extra_dim_vars = []
        self._extra_dim_scales = []

    @staticmethod
    def _widget_exists(widget: Optional[tk.Widget]) -> bool:
        if widget is None:
            return False
        try:
            return bool(widget.winfo_exists())
        except Exception:
            return False

    def _update_extra_dims(self) -> None:
        if self._data is None:
            self._clear_extra_dims()
            return
        if not self._widget_exists(self._extra_frame):
            return
        extra_dims = self._data.shape[4:] if self._data.ndim > 4 else ()
        if len(extra_dims) == len(self._extra_dim_scales):
            try:
                for idx, size in enumerate(extra_dims):
                    self._extra_dim_scales[idx].configure(from_=0, to=max(size - 1, 0))
                return
            except Exception:
                self._clear_extra_dims()

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
            dataobj = self._get_cached_dataobj(reco_id)
            affine = self._resolve_affine_for_space(reco_id=reco_id)
        except Exception as exc:
            self._view_error = f"Failed to load data:\n{exc}"
            self._status_var.set("Failed to load scan data.")
            self._update_plot()
            return

        if dataobj is None or affine is None:
            self._view_error = "Scan data unavailable for this reco."
            self._status_var.set("Scan data unavailable for this reco.")
            self._update_plot()
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
                self._view_error = "Scan data unavailable for this reco."
                self._status_var.set("Scan data unavailable for this reco.")
                self._update_plot()
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

    def _get_cached_dataobj(self, reco_id: int) -> Any:
        scan = self._scan
        if scan is None:
            return None
        if not self._cache_enabled or self._cache_max_items == 0:
            return scan.get_dataobj(reco_id=reco_id)
        key = self._cache_key(reco_id)
        if key is not None and key in self._data_cache:
            self._data_cache.move_to_end(key)
            return self._data_cache[key]
        dataobj = scan.get_dataobj(reco_id=reco_id)
        if key is not None:
            self._data_cache[key] = dataobj
            self._data_cache.move_to_end(key)
            if self._cache_max_items is not None:
                while len(self._data_cache) > self._cache_max_items:
                    self._data_cache.popitem(last=False)
        return dataobj

    def _cache_key(self, reco_id: int) -> Optional[Tuple[int, int]]:
        if self._scan is None:
            return None
        scan_id = getattr(self._scan, "scan_id", None)
        if scan_id is None:
            return None
        return (int(scan_id), int(reco_id))

    def _clear_data_cache(self) -> None:
        self._data_cache.clear()
        self._data = None
        self._affine = None
        self._res = None
        self._slicepack_data = None
        self._slicepack_affines = None

    def _clear_scan_cache(self, scan_id: int) -> None:
        keys = [key for key in self._data_cache.keys() if key[0] == scan_id]
        for key in keys:
            self._data_cache.pop(key, None)
        current_scan_id = getattr(self._scan, "scan_id", None)
        if current_scan_id == scan_id:
            self._data = None
            self._affine = None
            self._res = None
            self._slicepack_data = None
            self._slicepack_affines = None

    def _detach_converter_hooks(self) -> None:
        if self._loader is None or self._study is None:
            return
        for scan_id, scan in self._study.avail.items():
            if getattr(scan, "_converter_hook", None) is None:
                continue
            try:
                self._loader.restore_converter(scan_id)
            except Exception as exc:
                logger.debug("Failed to restore converter for scan %s: %s", scan_id, exc, exc_info=True)

    def _update_viewer_hook_controls(self) -> None:
        hook_frame = self._viewer_hook_frame
        if hook_frame is None:
            return
        scan = self._scan
        if scan is None:
            self._viewer_hook_enabled_var.set(False)
            hook_frame.grid_remove()
            return
        hook_name = getattr(scan, "_converter_hook_name", None)
        if not isinstance(hook_name, str) or not hook_name.strip():
            self._viewer_hook_enabled_var.set(False)
            hook_frame.grid_remove()
            return
        self._viewer_hook_name_var.set(hook_name)
        attached = getattr(scan, "_converter_hook", None) is not None
        self._viewer_hook_enabled_var.set(attached)
        hook_frame.grid()

    def _on_viewer_hook_toggle(self) -> None:
        scan = self._scan
        if self._loader is None or scan is None:
            return
        scan_id = getattr(scan, "scan_id", None)
        if scan_id is None:
            return
        hook_name = getattr(scan, "_converter_hook_name", None)
        if not isinstance(hook_name, str) or not hook_name.strip():
            self._viewer_hook_enabled_var.set(False)
            return

        if self._viewer_hook_enabled_var.get():
            try:
                entry = converter_core.resolve_hook(hook_name)
            except Exception as exc:
                self._viewer_hook_enabled_var.set(False)
                logger.warning("Viewer hook %r resolve failed: %s", hook_name, exc)
                return
            try:
                self._loader.override_converter(scan_id, entry)
            except Exception as exc:
                self._viewer_hook_enabled_var.set(False)
                logger.warning("Viewer hook %r attach failed: %s", hook_name, exc)
                return
        else:
            try:
                self._loader.restore_converter(scan_id)
            except Exception as exc:
                self._viewer_hook_enabled_var.set(True)
                logger.warning("Viewer hook %r detach failed: %s", hook_name, exc)
                return

        self._clear_scan_cache(scan_id)
        self._mark_viewer_dirty()
        self._maybe_load_viewer()

    def _on_close(self) -> None:
        if self._cache_enabled and self._cache_prompt_on_close and self._data_cache:
            try:
                from tkinter import messagebox

                if messagebox.askyesno("BrkRaw Viewer", "Clear cached data before closing?"):
                    self._clear_data_cache()
            except Exception:
                pass
        self.destroy()

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
            self._view_error = "Scan data is not at least 3D."
            self._status_var.set("Scan data is not at least 3D.")
            self._update_plot()
            return
        try:
            data_ras, affine_ras = reorient_to_ras(data, affine)
        except Exception as exc:
            self._view_error = f"Orientation error:\n{exc}"
            self._update_plot()
            return

        if self._is_invalid_image_shape(data_ras.shape):
            self._data = None
            self._affine = None
            self._res = None
            self._view_error = None
            self._status_var.set("Not image dataset.")
            self._set_viewer_tab_state(False)
            return

        self._data = data_ras
        self._affine = affine_ras
        self._res = np.linalg.norm(np.asarray(affine_ras)[:3, :3], axis=0)

        self._view_error = None
        self._set_viewer_tab_state(True)
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

    @staticmethod
    def _is_invalid_image_shape(shape: Tuple[int, ...]) -> bool:
        if len(shape) < 3:
            return True
        small_axes = sum(1 for size in shape[:3] if int(size) < 2)
        return small_axes >= 2

    def _set_viewer_tab_state(self, enabled: bool) -> None:
        if self._notebook is None:
            return
        tab = self._tab_widgets.get("Viewer")
        if tab is None:
            return
        state = "normal" if enabled else "disabled"
        try:
            self._notebook.tab(tab, state=state)
        except Exception:
            return
        if enabled:
            return
        try:
            current = self._notebook.tab(self._notebook.select(), "text")
        except Exception:
            current = None
        if current == "Viewer":
            fallback = self._tab_widgets.get("Info") or self._tab_widgets.get("Convert")
            if fallback is not None:
                try:
                    self._notebook.select(fallback)
                except Exception:
                    pass

    def _set_dataset_controls_enabled(self, enabled: bool) -> None:
        if self._notebook is not None:
            for title, tab in self._tab_widgets.items():
                state = "normal" if enabled else "disabled"
                try:
                    self._notebook.tab(tab, state=state)
                except Exception:
                    pass
            if enabled:
                try:
                    current_tab = self._notebook.select()
                    current_title = self._notebook.tab(current_tab, "text")
                except Exception:
                    current_title = None
                if current_title is None or current_title not in self._tab_widgets:
                    current_title = None
                if current_title is None or self._notebook.tab(self._tab_widgets[current_title], "state") == "disabled":
                    for title in self._tab_order:
                        tab = self._tab_widgets.get(title)
                        if tab is None:
                            continue
                        try:
                            if self._notebook.tab(tab, "state") != "disabled":
                                self._notebook.select(tab)
                                break
                        except Exception:
                            continue
        listbox_state = tk.NORMAL if enabled else tk.DISABLED
        for box in (getattr(self, "_scan_listbox", None), getattr(self, "_reco_listbox", None)):
            if box is None:
                continue
            try:
                box.configure(state=listbox_state)
            except Exception:
                pass
        summary_state = "readonly" if enabled else "disabled"
        for entry in self._subject_summary_entries:
            try:
                entry.configure(state=summary_state)
            except Exception:
                pass
        if self._subject_button is not None:
            try:
                self._subject_button.configure(state=tk.NORMAL if enabled else tk.DISABLED)
            except Exception:
                pass
        if self._refresh_button is not None:
            try:
                self._refresh_button.configure(state=tk.NORMAL if enabled else tk.DISABLED)
            except Exception:
                pass
        if not enabled and self._subject_window is not None and self._subject_window.winfo_exists():
            self._close_subject_window()

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
        viewer = self._viewer
        if viewer is None:
            return
        if self._view_error:
            if hasattr(viewer, "show_message_on"):
                viewer.show_message_on("xy", self._view_error, is_error=True)
            else:
                viewer.show_message(self._view_error, is_error=True)
            return
        slices = self._orth_slices()
        if self._data is None or slices is None:
            viewer.show_message("No data loaded", is_error=False)
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

        viewer.render_views(
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
) -> int:
    config_core.configure_logging()
    if isinstance(path, str) and path.strip():
        path = str(Path(path).expanduser())
        candidate = Path(path)
        suffix_lower = candidate.suffix.lower()
        variants = [candidate]
        if suffix_lower == ".zip":
            variants.append(candidate.with_suffix(".zip"))
        elif suffix_lower == ".pvdatasets":
            variants.append(candidate.with_suffix(".PvDatasets"))
            variants.append(candidate.with_suffix(".pvdatasets"))
        exists = False
        for variant in variants:
            try:
                if variant.exists():
                    exists = True
                    path = str(variant)
                    break
            except OSError:
                continue
        if not exists:
            print(f"Error: path not found: {path}", file=sys.stderr)
            return 2
    if path and sys.stdout and getattr(sys.stdout, "isatty", lambda: False)():
        try:
            print(f"Loading: {path}", flush=True)
            print("Opening |", end="", flush=True)
        except Exception:
            pass
    app = ViewerApp(
        path=path,
        scan_id=scan_id,
        reco_id=reco_id,
        info_spec=info_spec,
    )
    app.mainloop()
    return 0
