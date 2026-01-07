from __future__ import annotations

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Optional, Tuple

import numpy as np
import matplotlib

matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from brkraw.apps.loader import BrukerLoader
from .orientation import reorient_to_ras, aff2axcodes


class ViewerApp(tk.Tk):
    def __init__(
        self,
        *,
        path: Optional[str],
        scan_id: Optional[int],
        reco_id: Optional[int],
        axis: str,
        slice_index: Optional[int],
    ) -> None:
        super().__init__()
        self.title("BrkRaw Viewer")
        self.geometry("1100x720")

        self._loader: Optional[BrukerLoader] = None
        self._study = None
        self._scan = None
        self._data: Optional[np.ndarray] = None
        self._affine: Optional[np.ndarray] = None
        self._res: Optional[np.ndarray] = None
        self._qc_message: Optional[str] = None
        self._slice_hint: Optional[int] = slice_index

        self._path_var = tk.StringVar(value=path or "")
        self._scan_var = tk.StringVar(value="")
        self._reco_var = tk.StringVar(value="")
        self._axis_var = tk.StringVar(value=axis)
        self._slice_var = tk.IntVar(value=0)
        self._status_var = tk.StringVar(value="Ready")

        self._init_ui()

        if path:
            self._load_path(path, scan_id=scan_id, reco_id=reco_id)
        else:
            self._status_var.set("Open a study folder to begin.")

    def _init_ui(self) -> None:
        top = ttk.Frame(self, padding=(12, 10, 12, 6))
        top.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(top, text="Study Path:").pack(side=tk.LEFT)
        ttk.Entry(top, textvariable=self._path_var, width=70).pack(
            side=tk.LEFT, padx=(8, 8)
        )
        ttk.Button(top, text="Open...", command=self._choose_path).pack(side=tk.LEFT)

        body = ttk.Frame(self, padding=(12, 6, 12, 10))
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        control = ttk.Frame(body)
        control.pack(side=tk.LEFT, fill=tk.Y)

        ttk.Label(control, text="Scan").pack(anchor=tk.W)
        self._scan_box = ttk.Combobox(
            control,
            textvariable=self._scan_var,
            state="readonly",
            width=12,
        )
        self._scan_box.pack(anchor=tk.W, pady=(4, 12))
        self._scan_box.bind("<<ComboboxSelected>>", self._on_scan_change)

        ttk.Label(control, text="Reco").pack(anchor=tk.W)
        self._reco_box = ttk.Combobox(
            control,
            textvariable=self._reco_var,
            state="readonly",
            width=12,
        )
        self._reco_box.pack(anchor=tk.W, pady=(4, 12))
        self._reco_box.bind("<<ComboboxSelected>>", self._on_reco_change)

        ttk.Label(control, text="Axis").pack(anchor=tk.W, pady=(12, 4))
        axis_frame = ttk.Frame(control)
        axis_frame.pack(anchor=tk.W)
        for name in ("axial", "coronal", "sagittal"):
            ttk.Radiobutton(
                axis_frame,
                text=name.capitalize(),
                value=name,
                variable=self._axis_var,
                command=self._on_axis_change,
            ).pack(anchor=tk.W)

        ttk.Label(control, text="Slice").pack(anchor=tk.W, pady=(12, 4))
        self._slice_scale = tk.Scale(
            control,
            from_=0,
            to=0,
            orient=tk.HORIZONTAL,
            showvalue=True,
            command=self._on_slice_change,
            length=180,
        )
        self._slice_scale.pack(anchor=tk.W)

        self._info_label = ttk.Label(
            control,
            text="",
            justify=tk.LEFT,
            wraplength=220,
        )
        self._info_label.pack(anchor=tk.W, pady=(16, 0))

        plot_frame = ttk.Frame(body)
        plot_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(18, 0))

        self._figure = Figure(figsize=(7, 6), dpi=100)
        self._ax = self._figure.add_subplot(111)
        self._ax.set_facecolor("#111111")
        self._ax.set_title("No data loaded")
        self._ax.axis("off")

        self._canvas = FigureCanvasTkAgg(self._figure, master=plot_frame)
        self._canvas.draw()
        self._canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self._toolbar = NavigationToolbar2Tk(self._canvas, plot_frame)
        self._toolbar.update()

        status = ttk.Label(
            self,
            textvariable=self._status_var,
            relief=tk.SUNKEN,
            anchor=tk.W,
            padding=(8, 4),
        )
        status.pack(side=tk.BOTTOM, fill=tk.X)

    def _choose_path(self) -> None:
        path = filedialog.askdirectory(title="Select Bruker study folder")
        if not path:
            return
        self._path_var.set(path)
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

        scan_ids = list(self._study.avail.keys()) if self._study else []
        scan_values = [str(sid) for sid in scan_ids]
        self._scan_box["values"] = scan_values
        if not scan_ids:
            self._status_var.set("No scans found.")
            return

        target_scan = scan_id if scan_id in scan_ids else scan_ids[0]
        self._scan_var.set(str(target_scan))
        self._on_scan_change()

        if reco_id is not None:
            self._reco_var.set(str(reco_id))
            self._on_reco_change()

    def _on_scan_change(self, *_: object) -> None:
        if self._study is None:
            return
        scan_id = int(self._scan_var.get())
        self._scan = self._study.avail.get(scan_id)
        reco_ids = list(self._scan.avail.keys()) if self._scan else []
        self._reco_box["values"] = [str(rid) for rid in reco_ids]
        if reco_ids:
            self._reco_var.set(str(reco_ids[0]))
            self._on_reco_change()
        else:
            self._status_var.set(f"Scan {scan_id} has no reco data.")

    def _on_reco_change(self, *_: object) -> None:
        if self._scan is None:
            return
        reco_id = int(self._reco_var.get())
        self._load_data(reco_id=reco_id)

    def _on_axis_change(self) -> None:
        self._update_slice_range()
        self._update_plot()

    def _on_slice_change(self, value: str) -> None:
        try:
            self._slice_var.set(int(float(value)))
        except ValueError:
            return
        self._update_plot()

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
        if data.ndim > 3:
            data = data[..., 0]
            self._status_var.set("4D data detected; showing the first volume.")

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
        self._update_plot()
        self._update_info()

    def _update_slice_range(self) -> None:
        if self._data is None:
            self._slice_scale.configure(from_=0, to=0)
            self._slice_var.set(0)
            return
        axis = self._axis_var.get()
        shape = self._data.shape
        axis_size = {"axial": shape[2], "coronal": shape[1], "sagittal": shape[0]}
        max_index = axis_size.get(axis, shape[2]) - 1
        self._slice_scale.configure(from_=0, to=max_index)
        if self._slice_hint is not None:
            value = min(max(self._slice_hint, 0), max_index)
            self._slice_var.set(value)
            self._slice_hint = None
        else:
            self._slice_var.set(max_index // 2)

    def _update_info(self) -> None:
        if self._data is None:
            self._info_label.configure(text="")
            return
        shape = self._data.shape
        res = self._res if self._res is not None else np.diag(self._affine)[:3]
        axcodes = aff2axcodes(self._affine)
        lines = [
            f"Shape: {shape}",
            f"Resolution: {np.round(res, 4)}",
            f"Axcodes: {axcodes}",
        ]
        if self._qc_message:
            lines.append(self._qc_message)
        self._info_label.configure(text="\n".join(lines))

    def _get_slice(self) -> Tuple[Optional[np.ndarray], Optional[Tuple[float, float, float, float]]]:
        if self._data is None or self._res is None:
            return None, None
        axis = self._axis_var.get()
        idx = int(self._slice_var.get())
        nx, ny, nz = self._data.shape
        rx, ry, rz = self._res
        if axis == "axial":
            img = self._data[:, :, idx]
            extent = (0.0, nx * rx, 0.0, ny * ry)
        elif axis == "coronal":
            img = self._data[:, idx, :]
            extent = (0.0, nx * rx, 0.0, nz * rz)
        else:
            img = self._data[idx, :, :]
            extent = (0.0, ny * ry, 0.0, nz * rz)
        return img, extent

    def _update_plot(self) -> None:
        if self._data is None:
            self._ax.clear()
            self._ax.set_title("No data loaded")
            self._ax.axis("off")
            self._canvas.draw_idle()
            return
        img, extent = self._get_slice()
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
        self._ax.set_title(
            f"{axis.capitalize()} | slice {int(self._slice_var.get())}"
        )
        self._ax.set_xlabel("mm")
        self._ax.set_ylabel("mm")
        self._canvas.draw_idle()


def launch(
    *,
    path: Optional[str],
    scan_id: Optional[int],
    reco_id: Optional[int],
    axis: str,
    slice_index: Optional[int],
) -> int:
    app = ViewerApp(
        path=path,
        scan_id=scan_id,
        reco_id=reco_id,
        axis=axis,
        slice_index=slice_index,
    )
    app.mainloop()
    return 0
