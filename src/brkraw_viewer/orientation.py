import numpy as np
from functools import partial
import nibabel as nib

BRK_AXCODES = (('L', 'R'), ('A','P'), ('I', 'S'))
aff2axcodes = partial(nib.orientations.aff2axcodes, 
                      labels=BRK_AXCODES)

def _qc_nonorth(A: np.ndarray) -> tuple[float, float]:
    M = A[:3, :3]
    zooms = np.linalg.norm(M, axis=0)
    if np.any(zooms == 0):
        return np.inf, np.inf
    R = M / zooms
    gram = R.T @ R
    off = gram - np.eye(3)
    np.fill_diagonal(off, 0.0)
    return float(np.max(np.abs(off))), float(np.linalg.norm(off, ord="fro"))

def _infer_perm_flips(A: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, bool]:
    """
    Returns
    -------
    perm : (3,) int, permutation to make data axes -> world axes order
    flips : (3,) bool, whether to flip each new axis to be RAS+
    zooms : (3,) float, voxel sizes along permuted axes (RAS order)
    ambiguous : bool
    """
    M = A[:3, :3]
    zooms0 = np.linalg.norm(M, axis=0)
    if np.any(zooms0 == 0):
        raise ValueError("Invalid affine: zero column norm in linear part")
    R = M / zooms0

    # voxel axis j contributes most to world axis voxel_to_world[j]
    voxel_to_world = np.argmax(np.abs(R), axis=0)  # shape (3,)
    ambiguous = (np.unique(voxel_to_world).size != 3)

    # perm: order old axes so that new axes correspond to world x,y,z (RAS)
    perm = np.empty(3, dtype=int)
    for w in range(3):
        idx = np.where(voxel_to_world == w)[0]
        perm[w] = int(idx[0]) if idx.size else int(np.argmax(np.abs(R[w, :])))

    # flip if world axis w has negative sign along chosen old axis perm[w]
    flips = (R[np.arange(3), perm] < 0)

    # voxel sizes in the new (RAS) axis order
    zooms = zooms0[perm]
    return perm, flips, zooms, bool(ambiguous)

def _apply_perm_flips(data: np.ndarray, perm: np.ndarray, flips: np.ndarray) -> np.ndarray:
    axes = perm.tolist() + list(range(3, data.ndim))
    out = np.transpose(data, axes=axes)
    for ax in range(3):
        if flips[ax]:
            out = np.flip(out, axis=ax)
    return out

def _forced_diag_affine(res: np.ndarray, shape_xyz: tuple[int, int, int], center_mode: str, t_consistent: np.ndarray) -> np.ndarray:
    aff = np.eye(4, dtype=float)
    aff[0, 0], aff[1, 1], aff[2, 2] = map(float, res)

    nx, ny, nz = shape_xyz
    if center_mode == "fov_center":
        aff[0, 3] = -float(res[0]) * (nx - 1) / 2.0
        aff[1, 3] = -float(res[1]) * (ny - 1) / 2.0
        aff[2, 3] = -float(res[2]) * (nz - 1) / 2.0
    elif center_mode == "abs_translation":
        aff[:3, 3] = -np.abs(t_consistent)
    else:
        raise ValueError("center_mode must be 'fov_center' or 'abs_translation'")
    return aff

def reorient_to_ras(
    data: np.ndarray,
    affine: np.ndarray,
    warn_threshold: float = 0.05,
    hard_threshold: float = 0.10,
    center_mode: str = "fov_center",
):
    """
    Numpy-only reorient to RAS+ (transpose + flip), then FORCE affine to diagonal
    with negative translation.
    """
    data = np.asarray(data)
    A = np.asarray(affine, dtype=float)

    if data.ndim < 3:
        raise ValueError("data must be at least 3D")
    if A.shape != (4, 4):
        raise ValueError("affine must be (4,4)")

    max_abs_dot_in, frob_in = _qc_nonorth(A)

    perm, flips, res_ras, ambiguous = _infer_perm_flips(A)
    data_ras = _apply_perm_flips(data, perm, flips)

    # Build a minimal consistent t (optional, only for abs_translation)
    # new_idx -> old_idx mapping
    T = np.eye(4, dtype=float)
    T[:3, :3] = 0.0
    old_shape = np.array(data.shape[:3], dtype=float)
    for new_ax in range(3):
        old_ax = perm[new_ax]
        if not flips[new_ax]:
            T[old_ax, new_ax] = 1.0
            T[old_ax, 3] = 0.0
        else:
            T[old_ax, new_ax] = -1.0
            T[old_ax, 3] = old_shape[old_ax] - 1.0
    A_consistent = A @ T
    t_consistent = A_consistent[:3, 3]

    affine_forced = _forced_diag_affine(res_ras, data_ras.shape[:3], center_mode, t_consistent)

    qc_level = "ok"
    qc_msg = None
    if max_abs_dot_in > hard_threshold:
        qc_level = "high_risk"
        qc_msg = (
            "Input affine has strong non-orthogonality (shear/skew). "
            "Transpose/flip axis inference may be unreliable. "
            "If overlays look wrong, use resampling-based regrid."
        )
    elif max_abs_dot_in > warn_threshold or ambiguous:
        qc_level = "warn"
        qc_msg = (
            "Input affine shows noticeable non-orthogonality or ambiguous axis assignment. "
            "Result may be slightly off. If overlays look wrong, use resampling-based regrid."
        )

    info = {
        "perm_xyz": perm.copy(),              # old axes picked for world x,y,z
        "flips_xyz": tuple(bool(x) for x in flips),
        "res_ras": res_ras.copy(),
        "center_mode": center_mode,
        "qc_in_max_abs_dot": max_abs_dot_in,
        "qc_in_frob_offdiag": frob_in,
        "qc_level": qc_level,
        "qc_message": qc_msg,
        "ambiguous_axis_assignment": bool(ambiguous),
    }
    return data_ras, affine_forced, info

__all__ = [
    "aff2axcodes",
    "reorient_to_ras",
]
