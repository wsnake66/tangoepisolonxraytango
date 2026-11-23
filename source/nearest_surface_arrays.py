# SPDX-FileCopyrightText: 2026 MOLDBOXER, S.L.
# SPDX-License-Identifier: MIT

"""Shared array contract for nearest-surface clients and implementations."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


EPSILON = 1.0e-12


@dataclass(frozen=True)
class NearestSurfaceResult:
    points: np.ndarray
    triangle_indices: np.ndarray
    distances: np.ndarray
    hit_mask: np.ndarray


def as_vertices(values, name: str) -> np.ndarray:
    array = np.ascontiguousarray(values, dtype=np.float32)
    if array.ndim != 2 or array.shape[1] != 3:
        raise ValueError(f"{name} must have shape (n, 3)")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} contains non-finite coordinates")
    return array


def as_triangles(values, vertex_count: int) -> np.ndarray:
    array = np.ascontiguousarray(values, dtype=np.int32)
    if array.ndim != 2 or array.shape[1] != 3:
        raise ValueError("triangles must have shape (n, 3)")
    if len(array) == 0:
        raise ValueError("target mesh must contain at least one triangle")
    if np.any(array < 0) or np.any(array >= vertex_count):
        raise ValueError("triangles contain an out-of-range vertex index")
    return array


def as_edges(values, vertex_count: int) -> np.ndarray:
    array = np.ascontiguousarray(values, dtype=np.int32)
    if array.ndim != 2 or array.shape[1] != 2:
        raise ValueError("edges must have shape (n, 2)")
    if np.any(array < 0) or np.any(array >= vertex_count):
        raise ValueError("edges contain an out-of-range vertex index")
    return array
