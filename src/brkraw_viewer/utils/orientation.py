from __future__ import annotations

from typing import Tuple
import numpy as np
import nibabel as nib


def reorient_to_ras(data: np.ndarray, affine: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    data = np.asarray(data)
    affine = np.asarray(affine, dtype=float)

    ornt = nib.orientations.io_orientation(affine)
    ras_ornt = np.array([[0, 1], [1, 1], [2, 1]])  # RAS
    transform = nib.orientations.ornt_transform(ornt, ras_ornt)
    new_data = nib.orientations.apply_orientation(data, transform)
    new_affine = affine @ nib.orientations.inv_ornt_aff(transform, data.shape)
    return new_data, new_affine
