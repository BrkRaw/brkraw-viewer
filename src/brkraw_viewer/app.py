from __future__ import annotations

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Any, Dict, Iterable, Optional, Tuple
import datetime as dt

import numpy as np
import matplotlib

matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from brkraw.apps.loader import BrukerLoader
from brkraw.apps.loader import info as info_resolver
from .orientation import reorient_to_ras, aff2axcodes

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
        self._study = None
        self._scan = None
        self._scan_ids: list[int] = []
        self._scan_info_cache: Dict[int, Dict[str, Any]] = {}
        self._info_full: Dict[str, Any] = {}
        self._info_spec = info_spec

        self._data: Optional[np.ndarray] = None
        self._affine: Optional[np.ndarray] = None
        self._res: Optional[np.ndarray] = None
        self._qc_message: Optional[str] = None
        self._slice_hint: Optional[int] = slice_index
        self._frame_index = 0

        self._path_var = tk.StringVar(value=path or "")
        self._axis_var = tk.StringVar(value=axis)
        self._slice_var = tk.IntVar(value=0)
        self._frame_var = tk.IntVar(value=0)
        self._status_var = tk.StringVar(value="Ready")

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
        right_frame.rowconfigure(1, weight=0)

        preview_frame = ttk.LabelFrame(right_frame, text="Preview", padding=(6, 6))
        preview_frame.grid(row=0, column=0, sticky="nsew")
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(1, weight=1)

        control_bar = ttk.Frame(preview_frame)
        control_bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        ttk.Label(control_bar, text="Axis").pack(side=tk.LEFT, padx=(0, 6))
        for name in ("axial", "coronal", "sagittal"):
            ttk.Radiobutton(
                control_bar,
                text=name.capitalize(),
                value=name,
                variable=self._axis_var,
                command=self._on_axis_change,
            ).pack(side=tk.LEFT, padx=(0, 6))

        ttk.Label(control_bar, text="Slice").pack(side=tk.LEFT, padx=(12, 4))
        self._slice_scale = tk.Scale(
            control_bar,
            from_=0,
            to=0,
            orient=tk.HORIZONTAL,
            showvalue=True,
            command=self._on_slice_change,
            length=200,
        )
        self._slice_scale.pack(side=tk.LEFT)

        ttk.Label(control_bar, text="Frame").pack(side=tk.LEFT, padx=(12, 4))
        self._frame_scale = tk.Scale(
            control_bar,
            from_=0,
            to=0,
            orient=tk.HORIZONTAL,
            showvalue=True,
            command=self._on_frame_change,
            length=200,
        )
        self._frame_scale.pack(side=tk.LEFT)

        self._figure = Figure(figsize=(7, 6), dpi=100)
        self._ax = self._figure.add_subplot(111)
        self._ax.set_facecolor("#111111")
        self._ax.set_title("No data loaded")
        self._ax.axis("off")

        self._canvas = FigureCanvasTkAgg(self._figure, master=preview_frame)
        self._canvas.draw()
        self._canvas.get_tk_widget().grid(row=1, column=0, sticky="nsew")
        self._toolbar = NavigationToolbar2Tk(self._canvas, preview_frame, pack_toolbar=False)
        self._toolbar.update()
        self._toolbar.grid(row=2, column=0, sticky="ew", pady=(4, 0))

        info_frame = ttk.LabelFrame(right_frame, text="Scan Info", padding=(6, 6))
        info_frame.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        info_frame.columnconfigure(0, weight=1)
        info_frame.rowconfigure(0, weight=1)

        self._scan_info_text = tk.Text(info_frame, width=40, height=10, wrap="word")
        self._scan_info_text.grid(row=0, column=0, sticky="ew")
        self._scan_info_text.configure(state=tk.DISABLED)

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
            self._study = self._loader._study
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
        self._scan_listbox.delete(0, tk.END)
        scan_info_all = self._info_full.get("Scan(s)", {}) if self._info_full else {}
        for scan_id in self._scan_ids:
            info = scan_info_all.get(scan_id) or self._resolve_scan_info(scan_id, self._study.avail.get(scan_id))
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
        self._reco_listbox.delete(0, tk.END)
        scan = self._study.avail.get(scan_id)
        info = self._info_full.get("Scan(s)", {}).get(scan_id) or self._resolve_scan_info(scan_id, scan)
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
        self._load_data(reco_id=reco_id)

        scan_id = getattr(self._scan, "scan_id", None)
        info = self._info_full.get("Scan(s)", {}).get(scan_id) if scan_id is not None else {}
        if not info and scan_id is not None:
            info = self._resolve_scan_info(scan_id, self._scan)
        self._update_scan_info(info, reco_id)

    def _on_axis_change(self) -> None:
        self._update_slice_range()
        self._update_plot()

    def _on_slice_change(self, value: str) -> None:
        try:
            self._slice_var.set(int(float(value)))
        except ValueError:
            return
        self._update_plot()

    def _on_frame_change(self, value: str) -> None:
        try:
            self._frame_var.set(int(float(value)))
        except ValueError:
            return
        self._update_plot()

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
        scan: Any,
    ) -> Dict[str, Any]:
        if scan_id is None or scan is None:
            return {}
        if scan_id in self._scan_info_cache:
            return self._scan_info_cache[scan_id]
        try:
            if self._info_spec:
                info = info_resolver.scan(scan, spec_source=self._info_spec)
            else:
                info = info_resolver.scan(scan)
        except Exception:
            info = {}
        self._scan_info_cache[scan_id] = info
        return info

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

        if self._data is not None:
            res = self._res if self._res is not None else np.diag(self._affine)[:3]
            axcodes = aff2axcodes(self._affine)
            lines.append("")
            lines.append(f"RAS Shape: {self._data.shape}")
            lines.append(f"RAS Resolution: {self._format_value(np.round(res, 4))}")
            lines.append(f"Axcodes: {axcodes}")
            if self._qc_message:
                lines.append(self._qc_message)

        text = "\n".join([line for line in lines if line and line != "None"])
        self._scan_info_text.configure(state=tk.NORMAL)
        self._scan_info_text.delete("1.0", tk.END)
        self._scan_info_text.insert(tk.END, text)
        self._scan_info_text.configure(state=tk.DISABLED)

    def _load_data(self, *, reco_id: int) -> None:
        if self._scan is None:
            return
        try:
            dataobj = self._scan.get_dataobj(reco_id=reco_id)
            affine = self._scan.get_affine(reco_id=reco_id)
        except Exception as exc:
            messagebox.showerror("Load error", f"Failed to load data:\n{exc}")
            self._status_var.set("Failed to load scan data.")
            return

        if dataobj is None or affine is None:
            self._status_var.set("Scan data unavailable for this reco.")
            return

        if isinstance(dataobj, tuple):
            dataobj = dataobj[0]
            self._status_var.set("Multiple slice packs detected; showing the first pack.")

        if isinstance(affine, tuple):
            affine = affine[0]

        data = np.asarray(dataobj)
        if data.ndim < 3:
            self._status_var.set("Scan data is not at least 3D.")
            return

        try:
            data_ras, affine_ras, info = reorient_to_ras(data, np.asarray(affine))
        except Exception as exc:
            messagebox.showerror("Orientation error", f"Failed to reorient data:\n{exc}")
            return

        self._data = data_ras
        self._affine = affine_ras
        self._res = info.get("res_ras")
        self._qc_message = info.get("qc_message")

        self._update_slice_range()
        self._update_frame_range()
        self._update_plot()

    def _update_slice_range(self) -> None:
        if self._data is None:
            self._slice_scale.configure(from_=0, to=0, state=tk.DISABLED)
            self._slice_var.set(0)
            return
        axis = self._axis_var.get()
        shape = self._data.shape
        axis_size = {"axial": shape[2], "coronal": shape[1], "sagittal": shape[0]}
        max_index = axis_size.get(axis, shape[2]) - 1
        self._slice_scale.configure(from_=0, to=max_index, state=tk.NORMAL)
        if self._slice_hint is not None:
            value = min(max(self._slice_hint, 0), max_index)
            self._slice_var.set(value)
            self._slice_hint = None
        else:
            self._slice_var.set(max_index // 2)

    def _update_frame_range(self) -> None:
        if self._data is None or self._data.ndim < 4:
            self._frame_scale.configure(from_=0, to=0, state=tk.DISABLED)
            self._frame_var.set(0)
            return
        max_index = self._data.shape[3] - 1
        self._frame_scale.configure(from_=0, to=max_index, state=tk.NORMAL)
        self._frame_var.set(min(self._frame_var.get(), max_index))

    def _get_slice(self) -> Tuple[Optional[np.ndarray], Optional[Tuple[float, float, float, float]], str, str]:
        if self._data is None or self._res is None:
            return None, None, "", ""
        axis = self._axis_var.get()
        idx = int(self._slice_var.get())
        frame = int(self._frame_var.get())
        nx, ny, nz = self._data.shape[:3]
        rx, ry, rz = self._res
        data = self._data[..., frame] if self._data.ndim > 3 else self._data
        if axis == "axial":
            img = data[:, :, idx]
            extent = (0.0, nx * rx, 0.0, ny * ry)
            xlabel, ylabel = "x (mm)", "y (mm)"
        elif axis == "coronal":
            img = data[:, idx, :]
            extent = (0.0, nx * rx, 0.0, nz * rz)
            xlabel, ylabel = "x (mm)", "z (mm)"
        else:
            img = data[idx, :, :]
            extent = (0.0, ny * ry, 0.0, nz * rz)
            xlabel, ylabel = "y (mm)", "z (mm)"
        return img, extent, xlabel, ylabel

    def _update_plot(self) -> None:
        if self._data is None:
            self._ax.clear()
            self._ax.set_title("No data loaded")
            self._ax.axis("off")
            self._canvas.draw_idle()
            return
        img, extent, xlabel, ylabel = self._get_slice()
        if img is None or extent is None:
            return
        self._ax.clear()
        vmin, vmax = np.nanpercentile(img, (1, 99))
        self._ax.imshow(
            img.T,
            origin="lower",
            cmap="gray",
            vmin=vmin,
            vmax=vmax,
            extent=extent,
        )
        axis = self._axis_var.get()
        title = f"{axis.capitalize()} | slice {int(self._slice_var.get())}"
        if self._data is not None and self._data.ndim > 3:
            title += f" | frame {int(self._frame_var.get())}"
        self._ax.set_title(title)
        self._ax.set_xlabel(xlabel)
        self._ax.set_ylabel(ylabel)
        self._canvas.draw_idle()

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
        if self._info_spec and self._study:
            scan_info: Dict[int, Dict[str, Any]] = {}
            for scan_id in self._study.avail.keys():
                scan = self._study.avail.get(scan_id)
                if scan is None:
                    continue
                try:
                    scan_info[scan_id] = info_resolver.scan(scan, spec_source=self._info_spec)
                except Exception:
                    scan_info[scan_id] = info.get("Scan(s)", {}).get(scan_id, {})
            if scan_info:
                info["Scan(s)"] = scan_info
        return info


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
