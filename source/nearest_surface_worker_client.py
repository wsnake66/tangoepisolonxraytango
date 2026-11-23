# SPDX-FileCopyrightText: 2026 MOLDBOXER, S.L.
# SPDX-License-Identifier: GPL-3.0-or-later

"""Client for a persistent Blender-free nearest-surface subprocess."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import numpy as np

from .nearest_surface_arrays import (
    EPSILON,
    NearestSurfaceResult,
    as_edges,
    as_triangles,
    as_vertices,
)
from .nearest_surface_protocol import authorization_clock, read_message, write_message


logger = logging.getLogger(__name__)


_WINDOWS_DLL_NOT_FOUND_STATUS = 0xC0000135
_WINDOWS_DLL_LOAD_HELP = (
    "The Moldboxer geometry worker could not start because Windows could not "
    "load a required DLL (0xC0000135). First repair or install the Microsoft "
    "Visual C++ 2015-2022 Redistributable (x64), restart Windows, and try "
    "again. If the error continues, reinstall the latest Moldboxer version. "
    "Download: https://aka.ms/vs/17/release/vc_redist.x64.exe"
)
_WORKER_DLL_DIRS_ENV = "MOLDBOXER_WORKER_DLL_DIRS"


class NearestSurfaceWorkerError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkerServiceResponse:
    status_code: int
    content: bytes
    headers: dict[str, str]

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.content.decode("utf-8"))


@dataclass(frozen=True)
class WorkerMeshResult:
    vertices: np.ndarray
    triangles: np.ndarray
    quads: np.ndarray


@dataclass(frozen=True)
class WorkerPointClearanceResult:
    mesh: WorkerMeshResult
    selected_face_count: int
    component_count: int
    worker_seconds: float
    roundtrip_seconds: float


@dataclass(frozen=True)
class WorkerWatermarkImagePreparation:
    pixels: np.ndarray
    width: int
    height: int
    suggested_color: tuple[float, float, float]


@dataclass(frozen=True)
class WorkerWatermarkTrace:
    mask: np.ndarray
    preview: np.ndarray
    contours: tuple[np.ndarray, ...]
    selected_pixels: int
    islands: int


@dataclass(frozen=True)
class WorkerWatermarkConformResult:
    valid: bool
    vertices: np.ndarray
    matrix: np.ndarray
    embed_depth: float


@dataclass(frozen=True)
class WorkerPreparedWatermarkMesh:
    vertices: np.ndarray
    triangles: np.ndarray
    planar_points: np.ndarray
    vertex_point_indices: np.ndarray
    depth_fractions: np.ndarray
    cache_revision: int


@dataclass(frozen=True)
class WorkerHollowSurfaceResult:
    vertices: np.ndarray
    triangles: np.ndarray
    quads: np.ndarray
    voxel_size: float
    requested_voxel_size: float
    estimated_voxels: int
    dimensions: tuple[int, int, int]
    half_width: int


@dataclass(frozen=True)
class WorkerHollowCutterResult:
    vertices: np.ndarray
    triangles: np.ndarray
    quads: np.ndarray
    voxel_size: float
    requested_voxel_size: float
    estimated_voxels: int
    dimensions: tuple[int, int, int]
    half_width: int
    opening_mode: str
    cavity_cut_z: float | None
    source_cut_z: float | None
    applied_top_cut: float | None
    cavity_area: float | None
    source_area: float | None
    selected_source: str | None
    construction_seconds: float
    worker_seconds: float
    roundtrip_seconds: float


@dataclass(frozen=True)
class WorkerHollowOpeningResult:
    vertices: np.ndarray
    loop_offsets: np.ndarray
    region_offsets: np.ndarray


@dataclass(frozen=True)
class WorkerSimplificationResult:
    vertices: np.ndarray
    triangles: np.ndarray
    backend: str
    version: str
    simplification_seconds: float
    worker_seconds: float
    roundtrip_seconds: float


@dataclass(frozen=True)
class WorkerSimplifiedEnvelopeResult:
    mesh: WorkerMeshResult
    input_vertex_count: int
    input_triangle_count: int
    target_vertex_count: int
    target_triangle_count: int
    simplification_seconds: float
    bvh_seconds: float
    pipeline_seconds: float
    worker_seconds: float
    roundtrip_seconds: float


@dataclass(frozen=True)
class WorkerSplitPlanResult:
    cells: np.ndarray
    worker_seconds: float
    roundtrip_seconds: float


@dataclass(frozen=True)
class WorkerBarrierRouteResult:
    male_targets: np.ndarray
    mirrored_targets: np.ndarray
    female_offsets: np.ndarray
    female_targets: np.ndarray
    worker_seconds: float
    roundtrip_seconds: float


@dataclass(frozen=True)
class WorkerMasterBasePinResult:
    accepted: bool
    checker_failed: bool
    failed_stage: str | None
    bottom_inside: int | None
    bottom_total: int
    bottom_crossings: tuple[int, ...] | None
    top_inside: int | None
    top_total: int
    top_crossings: tuple[int, ...] | None
    center: tuple[float, float] | None
    pin_size: float | None
    female_bottom_z: float | None
    female_height: float | None
    male_height: float | None
    worker_seconds: float
    roundtrip_seconds: float


@dataclass(frozen=True)
class WorkerSlicerCleanupResult:
    vertices: np.ndarray
    triangles: np.ndarray
    face_sources: np.ndarray
    changed: bool
    initial: dict
    final: dict
    stats: dict
    passes: tuple[dict, ...]
    weld_distance: float
    preflight_seconds: float
    pipeline_seconds: float
    worker_seconds: float
    roundtrip_seconds: float


@dataclass(frozen=True)
class WorkerOrientationPlan:
    x_rotation_radians: float
    y_rotation_radians: float
    z_rotation_degrees: float
    pivot: tuple[float, float, float]
    base_normal: tuple[float, float, float]
    base_area: float
    base_tilt_degrees: float
    world_transform: np.ndarray
    source_vertex_count: int
    source_triangle_count: int
    analysis_vertex_count: int
    analysis_triangle_count: int
    target_reduction: float
    simplification_seconds: float
    simplification_backend: str
    worker_seconds: float
    roundtrip_seconds: float


@dataclass(frozen=True)
class WorkerOrientationAnalysis:
    plan: WorkerOrientationPlan | None
    source_volume: float


@dataclass(frozen=True)
class WorkerPolygonMeshResult:
    vertices: np.ndarray
    face_offsets: np.ndarray
    face_indices: np.ndarray


@dataclass(frozen=True)
class WorkerClearUndercutResult:
    mesh: WorkerPolygonMeshResult
    selected_paths: tuple[dict, ...]
    candidate_scores: tuple[dict, ...]
    unresolved_sections: tuple[tuple[int, ...], ...]
    source_face_count: int
    analyzed_face_count: int
    split_seconds: float
    split_backend: str
    ray_target_seconds: float
    candidate_request_seconds: float
    selection_request_seconds: float
    scoring_seconds: float
    build_seconds: float
    precise_ray_count: int
    worker_seconds: float
    roundtrip_seconds: float
    native_seconds: float
    backend: str
    selected_face_count: int
    propagated_face_count: int


@dataclass(frozen=True)
class WorkerNativeClearanceResult:
    mesh: WorkerPolygonMeshResult
    selected_face_count: int
    propagated_face_count: int
    classify_seconds: float
    build_seconds: float
    propagation_seconds: float
    native_seconds: float
    worker_seconds: float
    roundtrip_seconds: float
    input_bytes: int
    output_bytes: int


@dataclass(frozen=True)
class WorkerMeshAnalysis:
    component_ids: np.ndarray
    components: tuple[dict, ...]
    boundary_edges: np.ndarray
    non_manifold_edges: np.ndarray
    loose_vertices: np.ndarray
    manifold: bool
    bounds_min: tuple[float, float, float]
    bounds_max: tuple[float, float, float]
    worker_seconds: float
    roundtrip_seconds: float


@dataclass(frozen=True)
class WorkerMeshConnectivity:
    loose_vertices: np.ndarray
    multiple_components: bool
    worker_seconds: float
    roundtrip_seconds: float


@dataclass(frozen=True)
class WorkerAirTrapResult:
    tips: np.ndarray
    projected_areas: np.ndarray
    face_offsets: np.ndarray
    face_indices: np.ndarray
    supported_base_z: float
    backend: str
    worker_seconds: float
    roundtrip_seconds: float


@dataclass(frozen=True)
class WorkerFunnelExtensionResult:
    vertices: np.ndarray
    selected_face_count: int
    movement_distance: float
    worker_seconds: float
    roundtrip_seconds: float


@dataclass(frozen=True)
class WorkerSectionMeshResult:
    vertices: np.ndarray
    face_offsets: np.ndarray
    face_indices: np.ndarray
    centers: np.ndarray
    normals: np.ndarray
    areas: np.ndarray
    sections: np.ndarray
    plane_distances: np.ndarray
    plane_bounds: np.ndarray
    plane_contacts: np.ndarray
    splitting_planes: np.ndarray
    propagation_record_indices: tuple[int, ...] = ()
    propagation_counts: tuple[int, ...] = ()
    built_vertices: np.ndarray | None = None
    built_face_offsets: np.ndarray | None = None
    built_face_indices: np.ndarray | None = None


@dataclass(frozen=True)
class WorkerUndercutResult:
    face_indices: np.ndarray
    split_distances: np.ndarray
    direction: np.ndarray
    affected_area: float
    swept_volume: float
    total_distance: float
    candidate_id: str | None = None
    plane_index: int | None = None
    side: int | None = None
    path_section_ids: tuple[str, ...] = ()


def _analysis_areas(values, face_count: int) -> np.ndarray:
    areas = np.ascontiguousarray(values, dtype=np.float32)
    if areas.ndim != 1 or len(areas) != face_count:
        raise ValueError("face_areas must have shape (face_count,)")
    if not np.all(np.isfinite(areas)) or np.any(areas < 0.0):
        raise ValueError("face_areas contains invalid values")
    return areas


def _polygon_input(face_offsets, face_indices, vertex_count: int):
    offsets = np.ascontiguousarray(face_offsets, dtype=np.int32)
    indices = np.ascontiguousarray(face_indices, dtype=np.int32)
    if offsets.ndim != 1 or len(offsets) == 0:
        raise ValueError("face_offsets must contain at least one value")
    if indices.ndim != 1 or offsets[0] != 0 or offsets[-1] != len(indices):
        raise ValueError("polygon index arrays are inconsistent")
    if np.any(offsets[1:] < offsets[:-1]):
        raise ValueError("face_offsets must be nondecreasing")
    if np.any(indices < 0) or np.any(indices >= vertex_count):
        raise ValueError("face_indices contain an invalid vertex")
    return offsets, indices


def _opening_input(loop_offsets, points):
    vertices = as_vertices(points, "opening_points")
    offsets = np.ascontiguousarray(loop_offsets, dtype=np.int32)
    if (
        offsets.ndim != 1
        or len(offsets) < 2
        or offsets[0] != 0
        or offsets[-1] != len(vertices)
        or np.any(offsets[1:] < offsets[:-1])
    ):
        raise ValueError("opening loop offsets are inconsistent")
    if np.any(np.diff(offsets) < 3):
        raise ValueError("each opening loop must contain at least three points")
    return offsets, vertices


def _parse_undercut_results(response: dict, payload: bytes):
    value_count = int(response["value_count"])
    expected_bytes = value_count * (4 + 4)
    if len(payload) != expected_bytes:
        raise NearestSurfaceWorkerError(
            "geometry worker returned an invalid undercut payload"
        )
    face_indices = np.frombuffer(
        payload,
        dtype=np.int32,
        count=value_count,
    )
    split_distances = np.frombuffer(
        payload,
        dtype=np.float32,
        count=value_count,
        offset=value_count * 4,
    )
    results = []
    for metadata in response.get("results", ()):
        start = int(metadata["value_offset"])
        count = int(metadata["value_count"])
        stop = start + count
        if start < 0 or stop > value_count:
            raise NearestSurfaceWorkerError(
                "geometry worker returned invalid undercut result offsets"
            )
        results.append(
            WorkerUndercutResult(
                face_indices=face_indices[start:stop].copy(),
                split_distances=split_distances[start:stop].copy(),
                direction=np.ascontiguousarray(
                    metadata["direction"],
                    dtype=np.float32,
                ),
                affected_area=float(metadata["affected_area"]),
                swept_volume=float(metadata["swept_volume"]),
                total_distance=float(metadata["total_distance"]),
                candidate_id=(
                    None
                    if metadata.get("candidate_id") is None
                    else str(metadata["candidate_id"])
                ),
                plane_index=(
                    None
                    if metadata.get("plane_index") is None
                    else int(metadata["plane_index"])
                ),
                side=(
                    None
                    if metadata.get("side") is None
                    else int(metadata["side"])
                ),
                path_section_ids=tuple(
                    str(value) for value in metadata.get("path_section_ids", ())
                ),
            )
        )
    return tuple(results)


def _parse_polygon_mesh(response: dict, payload: bytes):
    vertex_count = int(response["vertex_count"])
    face_count = int(response["face_count"])
    value_count = int(response["face_value_count"])
    offset = 0
    vertices = np.frombuffer(
        payload, dtype=np.float32, count=vertex_count * 3, offset=offset
    ).reshape((vertex_count, 3))
    offset += vertex_count * 3 * 4
    face_offsets = np.frombuffer(
        payload, dtype=np.int32, count=face_count + 1, offset=offset
    )
    offset += (face_count + 1) * 4
    face_indices = np.frombuffer(
        payload, dtype=np.int32, count=value_count, offset=offset
    )
    offset += value_count * 4
    if not response.get("include_records"):
        if offset != len(payload):
            raise NearestSurfaceWorkerError("worker returned an invalid polygon mesh")
        return WorkerPolygonMeshResult(vertices, face_offsets, face_indices)
    plane_count = int(response["plane_count"])
    centers = np.frombuffer(
        payload, dtype=np.float32, count=face_count * 3, offset=offset
    ).reshape((face_count, 3))
    offset += face_count * 3 * 4
    normals = np.frombuffer(
        payload, dtype=np.float32, count=face_count * 3, offset=offset
    ).reshape((face_count, 3))
    offset += face_count * 3 * 4
    areas = np.frombuffer(
        payload, dtype=np.float32, count=face_count, offset=offset
    )
    offset += face_count * 4
    sections = np.frombuffer(
        payload, dtype=np.int8, count=face_count * plane_count, offset=offset
    ).reshape((face_count, plane_count))
    offset += face_count * plane_count
    plane_distances = np.frombuffer(
        payload,
        dtype=np.float32,
        count=face_count * plane_count,
        offset=offset,
    ).reshape((face_count, plane_count))
    offset += face_count * plane_count * 4
    plane_bounds = np.frombuffer(
        payload,
        dtype=np.float32,
        count=face_count * plane_count * 2,
        offset=offset,
    ).reshape((face_count, plane_count, 2))
    offset += face_count * plane_count * 2 * 4
    plane_contacts = np.frombuffer(
        payload,
        dtype=np.uint8,
        count=face_count * plane_count,
        offset=offset,
    ).reshape((face_count, plane_count))
    offset += face_count * plane_count
    splitting_planes = np.frombuffer(
        payload,
        dtype=np.uint8,
        count=plane_count,
        offset=offset,
    )
    offset += plane_count
    built_vertices = None
    built_face_offsets = None
    built_face_indices = None
    if "built_vertex_count" in response:
        built_vertex_count = int(response["built_vertex_count"])
        built_face_count = int(response["built_face_count"])
        built_value_count = int(response["built_face_value_count"])
        built_vertices = np.frombuffer(
            payload,
            dtype=np.float32,
            count=built_vertex_count * 3,
            offset=offset,
        ).reshape((built_vertex_count, 3))
        offset += built_vertex_count * 3 * 4
        built_face_offsets = np.frombuffer(
            payload,
            dtype=np.int32,
            count=built_face_count + 1,
            offset=offset,
        )
        offset += (built_face_count + 1) * 4
        built_face_indices = np.frombuffer(
            payload,
            dtype=np.int32,
            count=built_value_count,
            offset=offset,
        )
        offset += built_value_count * 4
    propagation_index_count = int(response.get("propagation_index_count", 0))
    propagation_count_count = int(response.get("propagation_count_count", 0))
    propagation_record_indices = np.frombuffer(
        payload,
        dtype=np.int32,
        count=propagation_index_count,
        offset=offset,
    )
    offset += propagation_index_count * 4
    propagation_counts = np.frombuffer(
        payload,
        dtype=np.int32,
        count=propagation_count_count,
        offset=offset,
    )
    offset += propagation_count_count * 4
    if offset != len(payload):
        raise NearestSurfaceWorkerError("worker returned invalid section records")
    return WorkerSectionMeshResult(
        vertices,
        face_offsets,
        face_indices,
        centers,
        normals,
        areas,
        sections,
        plane_distances,
        plane_bounds,
        plane_contacts,
        splitting_planes,
        tuple(int(value) for value in propagation_record_indices),
        tuple(int(value) for value in propagation_counts),
        built_vertices,
        built_face_offsets,
        built_face_indices,
    )


def _parse_clear_undercut_result(response, payload, *, roundtrip_seconds):
    mesh = _parse_polygon_mesh(response, payload)
    if not isinstance(mesh, WorkerPolygonMeshResult):
        raise NearestSurfaceWorkerError(
            "worker returned invalid clear-undercut geometry"
        )
    selected_paths = response.get("selected_paths")
    candidate_scores = response.get("candidate_scores", [])
    unresolved = response.get("unresolved_sections")
    if (
        not isinstance(selected_paths, list)
        or not isinstance(candidate_scores, list)
        or not isinstance(unresolved, list)
    ):
        raise NearestSurfaceWorkerError(
            "worker returned invalid clear-undercut planning metadata"
        )
    return WorkerClearUndercutResult(
        mesh=mesh,
        selected_paths=tuple(dict(value) for value in selected_paths),
        candidate_scores=tuple(dict(value) for value in candidate_scores),
        unresolved_sections=tuple(
            tuple(int(side) for side in section) for section in unresolved
        ),
        source_face_count=int(response.get("source_face_count", 0)),
        analyzed_face_count=int(response.get("analyzed_face_count", 0)),
        split_seconds=float(response.get("split_seconds", 0.0)),
        split_backend=str(response.get("split_backend", "python")),
        ray_target_seconds=float(response.get("ray_target_seconds", 0.0)),
        candidate_request_seconds=float(response["candidate_request_seconds"]),
        selection_request_seconds=float(response["selection_request_seconds"]),
        scoring_seconds=float(response["scoring_seconds"]),
        build_seconds=float(response["build_seconds"]),
        precise_ray_count=int(response["precise_ray_count"]),
        worker_seconds=float(response["worker_seconds"]),
        roundtrip_seconds=float(roundtrip_seconds),
        native_seconds=float(response.get("native_seconds", 0.0)),
        backend=str(response.get("backend", "python")),
        selected_face_count=int(response.get("selected_face_count", 0)),
        propagated_face_count=int(response.get("propagated_face_count", 0)),
    )


def _undercut_plan_header(
    server_request_config,
    *,
    requested_plane_count,
    boundary_plane_indices,
    local_sections_only,
    easy_extraction,
    restrict_bottom_extraction,
    restrict_bottom_vertical_extraction,
    horizontal_extraction=False,
    mid_horizontal_extraction=False,
    split_overtravel,
    clearance_overtravel,
    precise_cost,
    ray_epsilon,
    ray_max_hits,
    planning_only,
):
    config = dict(server_request_config)
    return {
        "access_token": str(config["access_token"]),
        "dev_requested": bool(config.get("dev_requested", False)),
        "timeout_seconds": float(config["timeout_seconds"]),
        "max_attempts": int(config["max_attempts"]),
        "retry_backoff_seconds": float(config["retry_backoff_seconds"]),
        "requested_plane_count": int(requested_plane_count),
        "boundary_plane_indices": sorted(
            int(value) for value in boundary_plane_indices
        ),
        "local_sections_only": bool(local_sections_only),
        "easy_extraction": bool(easy_extraction),
        "horizontal_extraction": bool(horizontal_extraction),
        "mid_horizontal_extraction": bool(mid_horizontal_extraction),
        "restrict_bottom_extraction": bool(restrict_bottom_extraction),
        "restrict_bottom_vertical_extraction": bool(
            restrict_bottom_vertical_extraction
        ),
        "split_overtravel": float(split_overtravel),
        "clearance_overtravel": float(clearance_overtravel),
        "precise_cost": bool(precise_cost),
        "ray_epsilon": float(ray_epsilon),
        "ray_max_hits": int(ray_max_hits),
        "planning_only": bool(planning_only),
    }


def _default_python_executable() -> Path:
    executable = Path(sys.executable).resolve()
    if executable.name.casefold().startswith("python") and executable.is_file():
        return executable

    candidates = []
    if os.name == "nt":
        candidates.extend(
            (Path(sys.prefix) / "python.exe", Path(sys.prefix) / "bin/python.exe")
        )
    else:
        candidates.extend(
            (
                Path(sys.prefix)
                / "bin"
                / f"python{sys.version_info.major}.{sys.version_info.minor}",
                Path(sys.prefix) / "bin" / "python3",
            )
        )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError("could not locate Blender's bundled Python worker executable")


def _windows_worker_dll_directories(
    python_executable: Path,
    *,
    prefix: Path | None = None,
    platform_name: str | None = None,
) -> tuple[Path, ...]:
    """Return existing Blender/Python directories needed for Windows DLL loading.

    Moldboxer keeps Blender's private Microsoft runtime beside the application in
    ``blender.crt``.  The GUI executable activates that directory itself, but the
    standalone Python worker does not inherit the GUI process' DLL search state.
    Include it explicitly so ``python.exe`` can load before the worker bootstrap
    has a chance to call :func:`os.add_dll_directory`.
    """

    if (os.name if platform_name is None else platform_name) != "nt":
        return ()

    executable = Path(python_executable).resolve()
    python_root = executable.parent.parent
    version_root = python_root.parent
    install_root = version_root.parent
    active_prefix = Path(sys.prefix if prefix is None else prefix).resolve()
    candidates = (
        executable.parent,
        active_prefix,
        active_prefix / "DLLs",
        active_prefix / "Library" / "bin",
        python_root,
        python_root / "DLLs",
        python_root / "Library" / "bin",
        version_root,
        install_root / "blender.crt",
        install_root,
    )
    directories = []
    seen = set()
    for candidate in candidates:
        if not candidate.is_dir():
            continue
        normalized = os.path.normcase(str(candidate))
        if normalized in seen:
            continue
        seen.add(normalized)
        directories.append(candidate)
    return tuple(directories)


def _worker_exit_message(return_code: int | None) -> str:
    if return_code is not None:
        windows_status = int(return_code) & 0xFFFFFFFF
        if windows_status == _WINDOWS_DLL_NOT_FOUND_STATUS:
            return _WINDOWS_DLL_LOAD_HELP
        return f"nearest-surface worker exited unexpectedly (code {return_code})"
    return "nearest-surface worker pipe closed unexpectedly"


def _worker_return_code_after_pipe_failure(process) -> int | None:
    """Allow a just-closed worker a moment to publish its Windows exit status."""

    return_code = process.poll()
    if return_code is not None:
        return return_code
    try:
        return process.wait(timeout=0.25)
    except subprocess.TimeoutExpired:
        return None


_WINDOWS_DLL_BOOTSTRAP = f"""\
import os

_moldboxer_dll_handles = []
if os.name == "nt" and hasattr(os, "add_dll_directory"):
    for _moldboxer_dll_dir in os.environ.get({_WORKER_DLL_DIRS_ENV!r}, "").split(os.pathsep):
        if not _moldboxer_dll_dir or not os.path.isdir(_moldboxer_dll_dir):
            continue
        try:
            _moldboxer_dll_handles.append(os.add_dll_directory(_moldboxer_dll_dir))
        except OSError:
            pass
"""


def _worker_command(python_executable: Path) -> list[str]:
    package_name = __package__ or ""
    if package_name.startswith("moldboxer_silicone_native."):
        worker_module = f"{package_name}.nearest_surface_worker"
        return [
            str(python_executable),
            "-c",
            _WINDOWS_DLL_BOOTSTRAP + f"\nfrom {worker_module} import main; main()",
        ]

    # Production packages protect the worker with PyArmor. Its bootstrap uses
    # a relative import of the build-specific runtime, so executing the file as
    # a bare script leaves it without a package and makes that import fail.
    # Create only the two package shells needed by the Blender-free worker;
    # importing the real add-on package here would pull bpy into the subprocess.
    worker_path = Path(__file__).resolve().with_name("nearest_surface_worker.py")
    bootstrap = _WINDOWS_DLL_BOOTSTRAP + """\
import importlib.util
from pathlib import Path
import sys
import types

worker_path = Path(sys.argv[1]).resolve()
packages = (
    ("moldboxer_silicone", worker_path.parent.parent),
    ("moldboxer_silicone.source", worker_path.parent),
)
for package_name, package_path in packages:
    package = types.ModuleType(package_name)
    package.__package__ = package_name
    package.__path__ = [str(package_path)]
    sys.modules[package_name] = package

module_name = "moldboxer_silicone.source.nearest_surface_worker"
spec = importlib.util.spec_from_file_location(module_name, worker_path)
if spec is None or spec.loader is None:
    raise ImportError(f"could not load nearest-surface worker: {worker_path}")
module = importlib.util.module_from_spec(spec)
sys.modules[module_name] = module
spec.loader.exec_module(module)
module.main()
"""
    return [
        str(python_executable),
        "-c",
        bootstrap,
        str(worker_path),
    ]


class TriangleBVHWorker:
    """Array-only shrinkwrap accelerator hosted in a persistent subprocess."""

    def __init__(
        self,
        vertices=None,
        triangles=None,
        *,
        python_executable=None,
        require_native: bool = False,
    ) -> None:
        total_start = time.perf_counter()
        if (vertices is None) != (triangles is None):
            raise ValueError("vertices and triangles must be supplied together")
        executable = (
            Path(python_executable).resolve()
            if python_executable is not None
            else _default_python_executable()
        )

        environment = os.environ.copy()
        module_path = Path(__file__).resolve()
        import_paths = [str(module_path.parent), str(module_path.parent.parent)]
        import_paths.extend(entry for entry in sys.path if entry)
        existing_python_path = environment.get("PYTHONPATH")
        if existing_python_path:
            import_paths.append(existing_python_path)
        environment["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(import_paths))

        dll_directories = _windows_worker_dll_directories(executable)
        if dll_directories:
            dll_paths = [str(directory) for directory in dll_directories]
            existing_path = environment.get("PATH")
            if existing_path:
                dll_paths.append(existing_path)
            environment["PATH"] = os.pathsep.join(dll_paths)
            environment[_WORKER_DLL_DIRS_ENV] = os.pathsep.join(
                str(directory) for directory in dll_directories
            )

        process_start = time.perf_counter()
        try:
            self._process = subprocess.Popen(
                _worker_command(executable),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=None,
                bufsize=0,
                env=environment,
            )
        except OSError as error:
            if os.name == "nt" and getattr(error, "winerror", None) in {126, 127}:
                raise NearestSurfaceWorkerError(_WINDOWS_DLL_LOAD_HELP) from error
            raise
        self._process_start_seconds = time.perf_counter() - process_start
        self._request_id = 0
        self._lock = threading.Lock()
        self._closed = False
        self._require_native = bool(require_native)
        self.vertex_count = 0
        self.triangle_count = 0
        self.backend = "unbuilt"
        self.node_count = 0
        self._watermark_image_size = None
        self._watermark_image_pixels = None
        self._watermark_mesh_revision = None
        self._watermark_last_valid_revision = None
        self._authorization_token_digest = ""
        self._authorization_tier = ""
        self._authorization_capabilities: frozenset[str] = frozenset()
        self._authorization_deadline = 0.0
        logger.info(
            "Nearest-surface worker process start: pid=%d process_start=%.3fs",
            self._process.pid,
            self._process_start_seconds,
        )
        if vertices is not None:
            self.build_target(vertices, triangles, _total_start=total_start)

    @property
    def is_running(self) -> bool:
        return not self._closed and self._process.poll() is None

    @property
    def authorization_expires_at(self) -> float:
        # Compatibility display value only; never used for authorization.
        if not self._authorization_deadline:
            return 0.0
        return time.time() + max(
            0.0, self._authorization_deadline - authorization_clock()
        )

    def authorization_valid(self, *, minimum_seconds: float = 60.0) -> bool:
        return bool(
            self.is_running
            and self._authorization_deadline
            > authorization_clock() + max(0.0, float(minimum_seconds))
        )

    def has_authorization_capability(self, capability: str) -> bool:
        return bool(
            self.authorization_valid(minimum_seconds=0.0)
            and str(capability) in self._authorization_capabilities
        )

    def authorize_worker(
        self,
        access_token: str,
        *,
        dev_requested: bool = False,
        timeout_seconds: float = 15.0,
    ) -> frozenset[str]:
        """Refresh the server-issued capabilities cached by this worker."""

        normalized_token = str(access_token or "").strip()
        if normalized_token.casefold().startswith("bearer "):
            normalized_token = normalized_token[7:].strip()
        if not normalized_token:
            raise NearestSurfaceWorkerError(
                "Worker authorization requires an access token"
            )
        token_digest = hashlib.sha256(normalized_token.encode("utf-8")).hexdigest()
        if (
            token_digest == self._authorization_token_digest
            and self.authorization_valid()
        ):
            return self._authorization_capabilities
        request_started = authorization_clock()
        response, payload = self._request(
            {
                "command": "authorize_worker",
                "access_token": normalized_token,
                "dev_requested": bool(dev_requested),
                "timeout_seconds": float(timeout_seconds),
            }
        )
        if payload:
            raise NearestSurfaceWorkerError(
                "geometry worker returned an invalid authorization payload"
            )
        capabilities = response.get("capabilities")
        if not isinstance(capabilities, list):
            raise NearestSurfaceWorkerError(
                "geometry worker returned invalid authorization capabilities"
            )
        remaining = float(response.get("expires_in", 0.0))
        deadline = request_started + remaining
        if not math.isfinite(remaining) or deadline <= authorization_clock():
            raise NearestSurfaceWorkerError(
                "geometry worker returned expired authorization"
            )
        self._authorization_token_digest = token_digest
        self._authorization_tier = str(response.get("tier") or "").strip().upper()
        self._authorization_capabilities = frozenset(
            str(capability) for capability in capabilities
        )
        self._authorization_deadline = deadline
        return self._authorization_capabilities

    def build_target(
        self,
        vertices,
        triangles,
        *,
        _total_start: float | None = None,
    ) -> None:
        """Replace the target BVH while retaining the worker process."""

        total_start = (
            time.perf_counter() if _total_start is None else _total_start
        )
        target_vertices = as_vertices(vertices, "vertices")
        if len(target_vertices) == 0:
            raise ValueError("target mesh must contain vertices")
        target_triangles = as_triangles(triangles, len(target_vertices))
        previous_triangle_count = self.triangle_count

        try:
            response_start = time.perf_counter()
            response, _payload = self._request(
                {
                    "command": "build",
                    "vertex_count": len(target_vertices),
                    "triangle_count": len(target_triangles),
                },
                target_vertices,
                target_triangles,
            )
            roundtrip = time.perf_counter() - response_start
        except Exception:
            self.close(force=True)
            raise

        self.vertex_count = len(target_vertices)
        self.triangle_count = len(target_triangles)
        self.backend = str(response["backend"])
        self.node_count = int(response["node_count"])
        logger.info(
            "Nearest-surface worker build: pid=%d backend=%s vertices=%d "
            "triangles=%d nodes=%d input_bytes=%d process_reused=%s "
            "process_start=%.3fs worker=%.3fs roundtrip=%.3fs total=%.3fs",
            self._process.pid,
            self.backend,
            self.vertex_count,
            self.triangle_count,
            self.node_count,
            target_vertices.nbytes + target_triangles.nbytes,
            previous_triangle_count > 0,
            self._process_start_seconds,
            float(response["worker_seconds"]),
            roundtrip,
            time.perf_counter() - total_start,
        )
        if self._require_native and self.backend != "native":
            self.close()
            raise NearestSurfaceWorkerError(
                "native nearest-surface backend is unavailable; run "
                "scripts/build_nearest_surface_native_dev.sh and Reload from Repo"
            )

    def prepare_watermark_image(
        self,
        pixels,
        width: int,
        height: int,
        *,
        max_dimension: int,
    ) -> WorkerWatermarkImagePreparation:
        values = np.ascontiguousarray(pixels, dtype=np.float32).reshape(-1)
        width = int(width)
        height = int(height)
        if values.size != width * height * 4:
            raise ValueError("RGBA pixels do not match image dimensions")
        response, payload = self._request(
            {
                "command": "prepare_watermark_image",
                "width": width,
                "height": height,
                "max_dimension": int(max_dimension),
            },
            values,
        )
        output_width = int(response["width"])
        output_height = int(response["height"])
        expected_bytes = output_width * output_height * 4 * 4
        if len(payload) != expected_bytes:
            raise NearestSurfaceWorkerError(
                "geometry worker returned an invalid watermark image payload"
            )
        output_pixels = np.frombuffer(payload, dtype=np.float32)
        suggested = tuple(float(value) for value in response["suggested_color"])
        if len(suggested) != 3:
            raise NearestSurfaceWorkerError(
                "geometry worker returned an invalid watermark color"
            )
        self._watermark_image_size = (output_width, output_height)
        self._watermark_image_pixels = output_pixels
        return WorkerWatermarkImagePreparation(
            pixels=output_pixels,
            width=output_width,
            height=output_height,
            suggested_color=suggested,
        )

    def trace_watermark_image(
        self,
        pixels,
        width: int,
        height: int,
        *,
        target_color,
        color_tolerance: float,
        alpha_threshold: float,
        invert: bool,
        output_width: float,
    ) -> WorkerWatermarkTrace:
        source_pixels = pixels
        values = np.ascontiguousarray(pixels, dtype=np.float32).reshape(-1)
        width = int(width)
        height = int(height)
        if values.size != width * height * 4:
            raise ValueError("RGBA pixels do not match image dimensions")
        # Dimensions alone do not identify an image. Reusing a same-sized image
        # left by another preview can silently trace the wrong pixels.
        reuse_prepared = bool(
            source_pixels is self._watermark_image_pixels
            and self._watermark_image_size == (width, height)
        )
        request_payload = () if reuse_prepared else (values,)
        request_header = {
            "command": "trace_watermark_image",
            "width": width,
            "height": height,
            "reuse_prepared": reuse_prepared,
            "target_color": [float(value) for value in target_color],
            "color_tolerance": float(color_tolerance),
            "alpha_threshold": float(alpha_threshold),
            "invert": bool(invert),
            "output_width": float(output_width),
        }
        try:
            response, payload = self._request(request_header, *request_payload)
        except NearestSurfaceWorkerError as error:
            if not reuse_prepared or "no matching prepared watermark image" not in str(
                error
            ):
                raise
            # The subprocess may have discarded its retained image after a
            # restart or cleanup while the client still held the preview.
            # Recover transparently by sending the actual pixels once.
            logger.info("Retrying watermark trace after stale worker image cache")
            self._watermark_image_size = None
            self._watermark_image_pixels = None
            request_header["reuse_prepared"] = False
            response, payload = self._request(request_header, values)
        self._watermark_image_size = (width, height)
        self._watermark_image_pixels = source_pixels
        mask_count = int(response["mask_count"])
        preview_count = int(response["preview_count"])
        point_count = int(response["contour_point_count"])
        offset_count = int(response["contour_offset_count"])
        mask_bytes = mask_count
        preview_bytes = preview_count * 4
        point_bytes = point_count * 2 * 4
        offset_bytes = offset_count * 4
        if len(payload) != mask_bytes + preview_bytes + point_bytes + offset_bytes:
            raise NearestSurfaceWorkerError(
                "geometry worker returned an invalid watermark trace payload"
            )
        payload_offset = 0
        mask = np.frombuffer(
            payload, dtype=np.uint8, count=mask_count, offset=payload_offset
        )
        payload_offset += mask_bytes
        preview = np.frombuffer(
            payload, dtype=np.float32, count=preview_count, offset=payload_offset
        ).copy()
        payload_offset += preview_bytes
        points = np.frombuffer(
            payload,
            dtype=np.float32,
            count=point_count * 2,
            offset=payload_offset,
        ).reshape((point_count, 2))
        payload_offset += point_bytes
        offsets = np.frombuffer(
            payload,
            dtype=np.int32,
            count=offset_count,
            offset=payload_offset,
        )
        if offset_count < 1 or offsets[0] != 0 or offsets[-1] != point_count:
            raise NearestSurfaceWorkerError(
                "geometry worker returned invalid watermark contour offsets"
            )
        contours = tuple(
            points[int(start) : int(end)].copy()
            for start, end in zip(offsets[:-1], offsets[1:])
        )
        return WorkerWatermarkTrace(
            mask=mask,
            preview=preview,
            contours=contours,
            selected_pixels=int(response["selected_pixels"]),
            islands=int(response["islands"]),
        )

    def conform_watermark(
        self,
        planar_points,
        vertex_point_indices,
        depth_fractions,
        *,
        location,
        center_normal,
        rotation: float,
        placement_scale: float,
        extrusion_depth: float,
        resolution_scale: float,
        voxel_size_override: float,
        operation: str,
        cache_revision: int | None = None,
    ) -> WorkerWatermarkConformResult:
        total_start = time.perf_counter()
        points = as_vertices(planar_points, "planar_points")
        point_indices = np.ascontiguousarray(vertex_point_indices, dtype=np.int32)
        fractions = np.ascontiguousarray(depth_fractions, dtype=np.float32)
        if point_indices.ndim != 1 or fractions.shape != point_indices.shape:
            raise ValueError("watermark vertex arrays must have equal length")
        reuse_prepared = (
            cache_revision is not None
            and int(cache_revision) == self._watermark_mesh_revision
        )
        response, payload = self._request(
            {
                "command": "conform_watermark",
                "point_count": len(points),
                "vertex_count": len(point_indices),
                "location": [float(value) for value in location],
                "center_normal": [float(value) for value in center_normal],
                "rotation": float(rotation),
                "placement_scale": float(placement_scale),
                "extrusion_depth": float(extrusion_depth),
                "resolution_scale": float(resolution_scale),
                "voxel_size_override": float(voxel_size_override),
                "operation": str(operation),
                "reuse_prepared": reuse_prepared,
                "prepared_revision": int(cache_revision or 0),
            },
            *((points, point_indices, fractions) if not reuse_prepared else ()),
        )
        vertex_count = int(response["vertex_count"])
        if len(payload) != 16 * 4 + vertex_count * 3 * 4:
            raise NearestSurfaceWorkerError(
                "geometry worker returned an invalid watermark conform payload"
            )
        matrix = np.frombuffer(payload, dtype=np.float32, count=16).reshape((4, 4))
        vertices = np.frombuffer(
            payload,
            dtype=np.float32,
            count=vertex_count * 3,
            offset=16 * 4,
        ).reshape((vertex_count, 3))
        valid = bool(response["valid"])
        if valid and vertex_count != len(point_indices):
            raise NearestSurfaceWorkerError(
                "geometry worker returned the wrong watermark vertex count"
            )
        if valid and reuse_prepared:
            self._watermark_last_valid_revision = int(cache_revision)
        logger.info(
            "Worker watermark conform: pid=%d valid=%s reused_prepared=%s "
            "vertices=%d input_bytes=%d output_bytes=%d worker=%.3fs "
            "roundtrip=%.3fs",
            self._process.pid,
            valid,
            reuse_prepared,
            vertex_count,
            0 if reuse_prepared else points.nbytes + point_indices.nbytes + fractions.nbytes,
            len(payload),
            float(response["worker_seconds"]),
            time.perf_counter() - total_start,
        )
        return WorkerWatermarkConformResult(
            valid=valid,
            vertices=vertices,
            matrix=matrix,
            embed_depth=float(response["embed_depth"]),
        )

    def prepare_watermark_mesh(
        self,
        vertices,
        triangles,
        *,
        max_vertices: int,
        resolution_scale: float,
    ) -> WorkerPreparedWatermarkMesh:
        points = as_vertices(vertices, "watermark_vertices")
        faces = as_triangles(triangles, len(points))
        response, payload = self._request(
            {
                "command": "prepare_watermark_mesh",
                "point_count": len(points),
                "triangle_count": len(faces),
                "max_vertices": int(max_vertices),
                "resolution_scale": float(resolution_scale),
            },
            points,
            faces,
        )
        point_count = int(response["point_count"])
        triangle_count = int(response["triangle_count"])
        planar_point_count = int(response["planar_point_count"])
        vertex_bytes = point_count * 3 * 4
        triangle_bytes = triangle_count * 3 * 4
        planar_bytes = planar_point_count * 3 * 4
        mapping_bytes = point_count * 4
        fraction_bytes = point_count * 4
        if len(payload) != (
            vertex_bytes
            + triangle_bytes
            + planar_bytes
            + mapping_bytes
            + fraction_bytes
        ):
            raise NearestSurfaceWorkerError(
                "geometry worker returned an invalid prepared watermark payload"
            )
        payload_offset = 0
        output_vertices = np.frombuffer(
            payload,
            dtype=np.float32,
            count=point_count * 3,
            offset=payload_offset,
        ).reshape((point_count, 3))
        payload_offset += vertex_bytes
        output_triangles = np.frombuffer(
            payload,
            dtype=np.int32,
            count=triangle_count * 3,
            offset=payload_offset,
        ).reshape((triangle_count, 3))
        payload_offset += triangle_bytes
        planar_points = np.frombuffer(
            payload,
            dtype=np.float32,
            count=planar_point_count * 3,
            offset=payload_offset,
        ).reshape((planar_point_count, 3))
        payload_offset += planar_bytes
        point_indices = np.frombuffer(
            payload,
            dtype=np.int32,
            count=point_count,
            offset=payload_offset,
        )
        payload_offset += mapping_bytes
        depth_fractions = np.frombuffer(
            payload,
            dtype=np.float32,
            count=point_count,
            offset=payload_offset,
        )
        cache_revision = int(response["prepared_revision"])
        self._watermark_mesh_revision = cache_revision
        self._watermark_last_valid_revision = None
        return WorkerPreparedWatermarkMesh(
            vertices=output_vertices,
            triangles=output_triangles,
            planar_points=planar_points,
            vertex_point_indices=point_indices,
            depth_fractions=depth_fractions,
            cache_revision=cache_revision,
        )

    def remesh_watermark(
        self,
        vertices,
        triangles,
        *,
        nominal_depth: float,
        resolution_scale: float,
        voxel_size_override: float,
        cache_revision: int | None = None,
    ) -> tuple[WorkerMeshResult, float]:
        total_start = time.perf_counter()
        reuse_conformed = (
            cache_revision is not None
            and int(cache_revision) == self._watermark_mesh_revision
            and int(cache_revision) == self._watermark_last_valid_revision
        )
        if reuse_conformed:
            points = np.empty((0, 3), dtype=np.float32)
            faces = np.empty((0, 3), dtype=np.int32)
        else:
            points = as_vertices(vertices, "watermark_vertices")
            faces = as_triangles(triangles, len(points))
        response, payload = self._request(
            {
                "command": "remesh_watermark",
                "point_count": len(points),
                "triangle_count": len(faces),
                "nominal_depth": float(nominal_depth),
                "resolution_scale": float(resolution_scale),
                "voxel_size_override": float(voxel_size_override),
                "reuse_conformed": reuse_conformed,
                "prepared_revision": int(cache_revision or 0),
            },
            *((points, faces) if not reuse_conformed else ()),
        )
        point_count = int(response["point_count"])
        triangle_count = int(response["triangle_count"])
        quad_count = int(response["quad_count"])
        vertex_bytes = point_count * 3 * 4
        triangle_bytes = triangle_count * 3 * 4
        quad_bytes = quad_count * 4 * 4
        if len(payload) != vertex_bytes + triangle_bytes + quad_bytes:
            raise NearestSurfaceWorkerError(
                "geometry worker returned an invalid watermark remesh payload"
            )
        output_vertices = np.frombuffer(
            payload, dtype=np.float32, count=point_count * 3
        ).reshape((point_count, 3))
        output_triangles = np.frombuffer(
            payload,
            dtype=np.int32,
            count=triangle_count * 3,
            offset=vertex_bytes,
        ).reshape((triangle_count, 3))
        output_quads = np.frombuffer(
            payload,
            dtype=np.int32,
            count=quad_count * 4,
            offset=vertex_bytes + triangle_bytes,
        ).reshape((quad_count, 4))
        logger.info(
            "Worker watermark remesh: pid=%d reused_conformed=%s "
            "output_vertices=%d output_triangles=%d output_quads=%d "
            "input_bytes=%d output_bytes=%d worker=%.3fs roundtrip=%.3fs",
            self._process.pid,
            reuse_conformed,
            point_count,
            triangle_count,
            quad_count,
            0 if reuse_conformed else points.nbytes + faces.nbytes,
            len(payload),
            float(response["worker_seconds"]),
            time.perf_counter() - total_start,
        )
        return (
            WorkerMeshResult(output_vertices, output_triangles, output_quads),
            float(response["voxel_size"]),
        )

    def can_reuse_conformed_watermark(self, cache_revision) -> bool:
        """Return whether final remeshing can use worker-retained geometry."""

        return bool(
            cache_revision is not None
            and int(cache_revision) == self._watermark_mesh_revision
            and int(cache_revision) == self._watermark_last_valid_revision
        )

    def clear_watermark_state(self) -> None:
        """Release image and prepared/conformed mesh data retained for placement."""

        response, payload = self._request({"command": "clear_watermark_state"})
        if payload:
            raise NearestSurfaceWorkerError(
                "geometry worker returned an invalid watermark-clear payload"
            )
        self._watermark_image_size = None
        self._watermark_image_pixels = None
        self._watermark_mesh_revision = None
        self._watermark_last_valid_revision = None
        logger.info(
            "Geometry worker watermark state cleared: pid=%d worker=%.3fs",
            self._process.pid,
            float(response["worker_seconds"]),
        )

    def service_json_request(
        self,
        service: str,
        path: str,
        payload: dict,
        *,
        access_token: str = "",
        dev_requested: bool = False,
        timeout_seconds: float = 30.0,
        max_attempts: int = 3,
        retry_backoff_seconds: float = 2.0,
    ) -> WorkerServiceResponse:
        """Send one JSON service request through the protected worker."""

        response, response_payload = self._request(
            {
                "command": "service_request",
                "service": str(service),
                "path": str(path),
                "transport": "json",
                "json": dict(payload),
                "access_token": str(access_token or ""),
                "dev_requested": bool(dev_requested),
                "timeout_seconds": float(timeout_seconds),
                "max_attempts": int(max_attempts),
                "retry_backoff_seconds": float(retry_backoff_seconds),
            }
        )
        return WorkerServiceResponse(
            status_code=int(response["status_code"]),
            content=bytes(response_payload),
            headers={
                str(key): str(value)
                for key, value in dict(response.get("headers", {})).items()
            },
        )

    def country_code_request(
        self,
        *,
        dev_requested: bool = False,
        timeout_seconds: float = 10.0,
    ) -> WorkerServiceResponse:
        """Fetch the locale hint through the protected worker."""

        response, response_payload = self._request(
            {
                "command": "country_code",
                "dev_requested": bool(dev_requested),
                "timeout_seconds": float(timeout_seconds),
            }
        )
        return WorkerServiceResponse(
            status_code=int(response["status_code"]),
            content=bytes(response_payload),
            headers={
                str(key): str(value)
                for key, value in dict(response.get("headers", {})).items()
            },
        )

    def activity_event_request(
        self,
        event: dict,
        *,
        timeout_seconds: float = 5.0,
    ) -> WorkerServiceResponse:
        """Deliver one best-effort activity event through the protected worker."""

        response, response_payload = self._request(
            {
                "command": "activity_event",
                "event": dict(event),
                "timeout_seconds": float(timeout_seconds),
            }
        )
        return WorkerServiceResponse(
            status_code=int(response["status_code"]),
            content=bytes(response_payload),
            headers={
                str(key): str(value)
                for key, value in dict(response.get("headers", {})).items()
            },
        )

    def service_zip_request(
        self,
        path: str,
        zip_bytes: bytes,
        *,
        query: dict | None = None,
        form_fields: dict | None = None,
        access_token: str = "",
        dev_requested: bool = False,
        timeout_seconds: float = 600.0,
        max_attempts: int = 3,
        retry_backoff_seconds: float = 2.0,
    ) -> WorkerServiceResponse:
        """Upload one prepared ZIP through the protected geometry transport."""

        encoded_form_fields = json.dumps(
            dict(form_fields or {}),
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        response, response_payload = self._request(
            {
                "command": "service_request",
                "service": "geometry",
                "path": str(path),
                "transport": "zip",
                "query": dict(query or {}),
                "form_fields_bytes": len(encoded_form_fields),
                "access_token": str(access_token or ""),
                "dev_requested": bool(dev_requested),
                "timeout_seconds": float(timeout_seconds),
                "max_attempts": int(max_attempts),
                "retry_backoff_seconds": float(retry_backoff_seconds),
            },
            bytes(zip_bytes),
            encoded_form_fields,
        )
        return WorkerServiceResponse(
            status_code=int(response["status_code"]),
            content=bytes(response_payload),
            headers={
                str(key): str(value)
                for key, value in dict(response.get("headers", {})).items()
            },
        )

    def _request(self, header: dict, *payload_parts) -> tuple[dict, bytearray]:
        with self._lock:
            return_code = self._process.poll()
            if self._closed:
                raise NearestSurfaceWorkerError("nearest-surface worker is closed")
            if return_code is not None:
                raise NearestSurfaceWorkerError(_worker_exit_message(return_code))
            self._request_id += 1
            request_id = self._request_id
            request_header = dict(header)
            request_header["request_id"] = request_id
            input_stream = self._process.stdin
            output_stream = self._process.stdout
            if input_stream is None or output_stream is None:
                raise NearestSurfaceWorkerError(
                    "nearest-surface worker pipes are unavailable"
                )
            try:
                write_message(input_stream, request_header, *payload_parts)
                response, payload = read_message(output_stream)
            except (BrokenPipeError, EOFError, OSError) as error:
                raise NearestSurfaceWorkerError(
                    _worker_exit_message(
                        _worker_return_code_after_pipe_failure(self._process)
                    )
                ) from error
            if int(response.get("request_id", -1)) != request_id:
                raise NearestSurfaceWorkerError(
                    "nearest-surface worker response is out of order"
                )
            if response.get("status") != "ok":
                raise NearestSurfaceWorkerError(
                    f"{response.get('error_type', 'WorkerError')}: "
                    f"{response.get('message', 'nearest-surface request failed')}"
                )
            return response, payload

    def geometry_policy(self, operation: str, **arguments) -> dict:
        """Evaluate a commercial policy; geometry arguments travel in the payload."""

        response, payload = self._request(
            {
                "command": "geometry_policy",
                "operation": str(operation),
                "arguments_encoding": "json",
                "result_encoding": "json",
            },
            json.dumps(arguments, separators=(",", ":")).encode("utf-8"),
        )
        encoding = response.get("result_encoding")
        if encoding == "json":
            if "result" in response:
                raise NearestSurfaceWorkerError("geometry worker returned duplicate policy results")
            try:
                result = json.loads(payload)
            except (ValueError, UnicodeDecodeError) as exc:
                raise NearestSurfaceWorkerError("geometry worker returned invalid policy JSON") from exc
        elif encoding is None:
            if payload:
                raise NearestSurfaceWorkerError(
                    "geometry worker returned an unexpected policy payload"
                )
            result = response.get("result")
        else:
            raise NearestSurfaceWorkerError("geometry worker returned an unsupported policy encoding")
        if not isinstance(result, dict):
            raise NearestSurfaceWorkerError(
                "geometry worker returned an invalid policy result"
            )
        logger.debug(
            "Worker geometry policy: pid=%d operation=%s worker=%.6fs",
            self._process.pid,
            operation,
            float(response["worker_seconds"]),
        )
        return result

    def locking_clamp_plan(
        self,
        kind: str,
        primary_size: float,
        secondary_size: float,
        height: float,
        thickness: float,
        tolerance: float,
        closing_pressure: float,
        clip_count: int,
    ) -> dict:
        """Request the protected locking-clamp construction recipe."""

        response, payload = self._request(
            {
                "command": "locking_clamp_plan",
                "kind": str(kind).upper(),
                "primary_size": float(primary_size),
                "secondary_size": float(secondary_size),
                "height": float(height),
                "thickness": float(thickness),
                "tolerance": float(tolerance),
                "closing_pressure": float(closing_pressure),
                "clip_count": int(clip_count),
            }
        )
        result = response.get("result")
        if payload or not isinstance(result, dict):
            raise NearestSurfaceWorkerError(
                "geometry worker returned an invalid locking-clamp plan"
            )
        if not isinstance(result.get("steps"), list) or not isinstance(
            result.get("layout"), dict
        ):
            raise NearestSurfaceWorkerError(
                "geometry worker returned an incomplete locking-clamp plan"
            )
        logger.info(
            "Worker locking-clamp plan: pid=%d kind=%s steps=%d worker=%.3fs",
            self._process.pid,
            str(kind).upper(),
            len(result["steps"]),
            float(response["worker_seconds"]),
        )
        return result

    def weight_text_extension_plan(
        self,
        wing_min_x: float,
        wing_min_z: float,
        wing_max_z: float,
        text_width: float,
        text_depth: float,
        center_y: float,
        padding: float,
        outward_span: float,
        outward_shift: float,
        cutter_oversize: float,
        *,
        min_z: float | None = None,
        max_z: float | None = None,
        attachment_min_x: float | None = None,
        text_min_x: float | None = None,
        attachment_overlap: float | None = None,
    ) -> dict:
        """Request weight-label extension and casting-cutter placement."""

        response, payload = self._request(
            {
                "command": "weight_text_extension_plan",
                "wing_min_x": float(wing_min_x),
                "wing_min_z": float(wing_min_z),
                "wing_max_z": float(wing_max_z),
                "text_width": float(text_width),
                "text_depth": float(text_depth),
                "center_y": float(center_y),
                "padding": float(padding),
                "outward_span": float(outward_span),
                "outward_shift": float(outward_shift),
                "cutter_oversize": float(cutter_oversize),
                "min_z": None if min_z is None else float(min_z),
                "max_z": None if max_z is None else float(max_z),
                "attachment_min_x": (
                    None
                    if attachment_min_x is None
                    else float(attachment_min_x)
                ),
                "text_min_x": (
                    None if text_min_x is None else float(text_min_x)
                ),
                "attachment_overlap": (
                    None
                    if attachment_overlap is None
                    else float(attachment_overlap)
                ),
            }
        )
        result = response.get("result")
        if payload or not isinstance(result, dict):
            raise NearestSurfaceWorkerError(
                "geometry worker returned an invalid weight-text extension plan"
            )
        extension_bounds = result.get("extension_bounds")
        cutter_bounds = result.get("casting_cutter_bounds")
        placement = result.get("text_placement")
        if (
            not isinstance(extension_bounds, list)
            or len(extension_bounds) != 6
            or not isinstance(cutter_bounds, list)
            or len(cutter_bounds) != 6
            or not isinstance(placement, dict)
            or "min_x" not in placement
            or "center_y" not in placement
        ):
            raise NearestSurfaceWorkerError(
                "geometry worker returned an incomplete weight-text extension plan"
            )
        logger.info(
            "Worker weight-text extension plan: pid=%d worker=%.3fs",
            self._process.pid,
            float(response["worker_seconds"]),
        )
        return result

    def custom_face_core(self, dimensions=None) -> dict:
        """Request head geometry from the licensed worker; never generate locally."""
        response, payload = self._request(
            {"command": "custom_face_core", "dimensions": dimensions}
        )
        try:
            result = json.loads(payload)
        except (ValueError, UnicodeDecodeError) as error:
            raise NearestSurfaceWorkerError("geometry worker returned invalid head data") from error
        if not isinstance(result, dict) or any(
            not isinstance(result.get(key), list)
            for key in ("vertices", "faces", "ear_contour")
        ):
            raise NearestSurfaceWorkerError("geometry worker returned invalid head geometry")
        logger.info(
            "Worker custom-face core: pid=%d worker=%.3fs vertices=%d faces=%d",
            self._process.pid,
            float(response["worker_seconds"]),
            len(result["vertices"]),
            len(result["faces"]),
        )
        return result

    def organic_plane(self, operation: str, **arguments) -> dict:
        """Evaluate organic-plane math in the protected worker."""

        response, payload = self._request(
            {
                "command": "organic_plane",
                "operation": str(operation),
                "arguments": arguments,
            }
        )
        if payload or not isinstance(response.get("result"), dict):
            raise NearestSurfaceWorkerError(
                "geometry worker returned an invalid organic-plane result"
            )
        logger.debug(
            "Worker organic plane: pid=%d operation=%s worker=%.6fs",
            self._process.pid,
            operation,
            float(response["worker_seconds"]),
        )
        return response["result"]

    def nearest(
        self,
        points,
        *,
        max_distance: float | None = None,
        batch_size: int = 16_384,
        seed_triangle_indices=None,
        _emit_log: bool = True,
    ) -> NearestSurfaceResult:
        del batch_size
        query_start = time.perf_counter()
        query_points = as_vertices(points, "points")
        if max_distance is not None and max_distance < 0.0:
            raise ValueError("max_distance cannot be negative")
        point_count = len(query_points)
        if seed_triangle_indices is None:
            seeds = np.full(point_count, -1, dtype=np.int32)
            seed_mode = "none"
        else:
            seeds = np.ascontiguousarray(seed_triangle_indices, dtype=np.int32)
            if seeds.ndim != 1 or len(seeds) != point_count:
                raise ValueError(
                    "seed_triangle_indices must have shape (point_count,)"
                )
            seed_mode = "provided"
        seeded_count = int(
            np.count_nonzero((seeds >= 0) & (seeds < self.triangle_count))
        )

        response, payload = self._request(
            {
                "command": "query",
                "point_count": point_count,
                "max_distance": max_distance,
            },
            query_points,
            seeds,
        )
        expected_bytes = point_count * (3 * 4 + 4 + 4)
        if len(payload) != expected_bytes:
            raise NearestSurfaceWorkerError(
                "nearest-surface worker returned an invalid payload"
            )
        offset = point_count * 3 * 4
        nearest_points = np.frombuffer(
            payload, dtype=np.float32, count=point_count * 3
        ).reshape((point_count, 3))
        triangle_indices = np.frombuffer(
            payload, dtype=np.int32, count=point_count, offset=offset
        )
        offset += point_count * 4
        distances = np.frombuffer(
            payload, dtype=np.float32, count=point_count, offset=offset
        )
        hit_mask = triangle_indices >= 0
        elapsed = time.perf_counter() - query_start
        if _emit_log:
            logger.info(
                "Nearest-surface worker query: pid=%d backend=%s points=%d "
                "target_triangles=%d hits=%d seed_mode=%s seeded=%d "
                "input_bytes=%d output_bytes=%d worker=%.3fs roundtrip=%.3fs",
                self._process.pid,
                self.backend,
                point_count,
                self.triangle_count,
                int(np.count_nonzero(hit_mask)),
                seed_mode,
                seeded_count,
                query_points.nbytes + seeds.nbytes,
                len(payload),
                float(response["worker_seconds"]),
                elapsed,
            )
        return NearestSurfaceResult(
            points=nearest_points,
            triangle_indices=triangle_indices,
            distances=distances,
            hit_mask=hit_mask,
        )

    def project_casting_input(
        self,
        top_points,
        bottom_points,
        *,
        bottom_z: float,
        max_distance: float,
        top_offset: float = 1.0,
        top_direction=(0.0, 0.0, 1.0),
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Project both casting-input caps in one retained-target request."""

        top = as_vertices(top_points, "top_points")
        bottom = as_vertices(bottom_points, "bottom_points")
        response, payload = self._request(
            {
                "command": "project_casting_input",
                "top_count": len(top),
                "bottom_count": len(bottom),
                "bottom_z": float(bottom_z),
                "max_distance": float(max_distance),
                "top_offset": float(top_offset),
                "top_direction": [float(value) for value in top_direction],
            },
            top,
            bottom,
        )
        expected = (len(top) * 3 + len(bottom) * 3 + len(top)) * 4
        # The hit mask is uint8, so correct the expected size by three bytes/point.
        expected -= len(top) * 3
        if len(payload) != expected:
            raise NearestSurfaceWorkerError(
                "geometry worker returned an invalid casting projection"
            )
        offset = 0
        projected_top = np.frombuffer(payload, dtype=np.float32, count=len(top) * 3, offset=offset).reshape((-1, 3))
        offset += len(top) * 3 * 4
        projected_bottom = np.frombuffer(payload, dtype=np.float32, count=len(bottom) * 3, offset=offset).reshape((-1, 3))
        offset += len(bottom) * 3 * 4
        hit_mask = np.frombuffer(payload, dtype=np.uint8, count=len(top), offset=offset).astype(bool)
        logger.info(
            "Worker casting projection: pid=%d top=%d bottom=%d hits=%d "
            "input_bytes=%d output_bytes=%d worker=%.3fs",
            self._process.pid,
            len(top),
            len(bottom),
            int(np.count_nonzero(hit_mask)),
            top.nbytes + bottom.nbytes,
            len(payload),
            float(response["worker_seconds"]),
        )
        return projected_top, projected_bottom, hit_mask

    def shrinkwrap_with_result(
        self,
        source_vertices,
        *,
        offset: float = 0.0,
        max_distance: float | None = None,
        batch_size: int = 16_384,
        seed_triangle_indices=None,
    ) -> tuple[np.ndarray, NearestSurfaceResult]:
        total_start = time.perf_counter()
        source = as_vertices(source_vertices, "source_vertices")
        query_start = time.perf_counter()
        result = self.nearest(
            source,
            max_distance=max_distance,
            batch_size=batch_size,
            seed_triangle_indices=seed_triangle_indices,
        )
        query_elapsed = time.perf_counter() - query_start
        offset_start = time.perf_counter()
        wrapped = result.points.copy()
        if offset != 0.0 and np.any(result.hit_mask):
            hit_ids = np.flatnonzero(result.hit_mask)
            directions = source[hit_ids] - result.points[hit_ids]
            lengths = np.linalg.norm(directions, axis=1)
            nonzero = lengths > EPSILON
            directions[nonzero] /= lengths[nonzero, None]
            directions[~nonzero] = 0.0
            wrapped[hit_ids] += float(offset) * directions
        wrapped[~result.hit_mask] = source[~result.hit_mask]
        offset_elapsed = time.perf_counter() - offset_start
        logger.info(
            "Nearest-surface worker shrinkwrap: source_vertices=%d offset=%.6f "
            "query=%.3fs offset_apply=%.3fs total=%.3fs",
            len(source),
            float(offset),
            query_elapsed,
            offset_elapsed,
            time.perf_counter() - total_start,
        )
        return wrapped, result

    def shrinkwrap(self, source_vertices, **kwargs) -> np.ndarray:
        wrapped, _result = self.shrinkwrap_with_result(source_vertices, **kwargs)
        return wrapped

    def shrinkwrap_sequence(
        self,
        source_vertices,
        source_edges,
        *,
        wrap_count: int,
        source_triangles=None,
        normal_offset: float = 0.0,
        offset: float = 0.0,
        smooth_factor: float = 0.5,
        smooth_repeat: int = 5,
        max_distance: float | None = None,
    ) -> np.ndarray:
        """Run all wrap and between-pass smooth operations in one request."""

        total_start = time.perf_counter()
        source = as_vertices(source_vertices, "source_vertices")
        edges = as_edges(source_edges, len(source))
        triangles = (
            np.empty((0, 3), dtype=np.int32)
            if source_triangles is None
            else as_triangles(source_triangles, len(source))
        )
        wrap_count = int(wrap_count)
        smooth_repeat = int(smooth_repeat)
        smooth_factor = float(smooth_factor)
        normal_offset = float(normal_offset)
        if wrap_count < 0:
            raise ValueError("wrap_count cannot be negative")
        if not np.isfinite(normal_offset):
            raise ValueError("normal_offset must be finite")
        if normal_offset != 0.0 and len(triangles) == 0:
            raise ValueError(
                "source_triangles are required for a normal offset"
            )
        if smooth_repeat < 0:
            raise ValueError("smooth_repeat cannot be negative")
        if not np.isfinite(smooth_factor):
            raise ValueError("smooth_factor must be finite")
        if max_distance is not None and max_distance < 0.0:
            raise ValueError("max_distance cannot be negative")

        response, payload = self._request(
            {
                "command": "wrap_sequence",
                "point_count": len(source),
                "edge_count": len(edges),
                "triangle_count": len(triangles),
                "wrap_count": wrap_count,
                "normal_offset": normal_offset,
                "offset": float(offset),
                "smooth_factor": smooth_factor,
                "smooth_repeat": smooth_repeat,
                "max_distance": max_distance,
            },
            source,
            edges,
            triangles,
        )
        expected_bytes = len(source) * 3 * 4
        if len(payload) != expected_bytes:
            raise NearestSurfaceWorkerError(
                "nearest-surface worker returned an invalid sequence payload"
            )
        wrapped = np.frombuffer(payload, dtype=np.float32).reshape(
            (len(source), 3)
        )
        roundtrip = time.perf_counter() - total_start

        for pass_timing in response.get("passes", ()):
            logger.info(
                "Nearest-surface worker sequence pass: pid=%d backend=%s "
                "pass=%d/%d points=%d hits=%d seeded=%d smoothing=%.3fs "
                "query=%.3fs offset_apply=%.3fs total=%.3fs",
                self._process.pid,
                self.backend,
                int(pass_timing["pass"]),
                wrap_count,
                len(source),
                int(pass_timing["hits"]),
                int(pass_timing["seeded"]),
                float(pass_timing["smooth_seconds"]),
                float(pass_timing["query_seconds"]),
                float(pass_timing["offset_seconds"]),
                float(pass_timing["total_seconds"]),
            )
        logger.info(
            "Nearest-surface worker sequence: pid=%d backend=%s points=%d "
            "edges=%d triangles=%d wraps=%d normal_offset=%.6f "
            "normal_backend=%s normal_time=%.3fs smooth_factor=%.3f "
            "smooth_repeat=%d "
            "input_bytes=%d output_bytes=%d worker=%.3fs roundtrip=%.3fs",
            self._process.pid,
            self.backend,
            len(source),
            len(edges),
            len(triangles),
            wrap_count,
            normal_offset,
            response["normal_offset_backend"],
            float(response["normal_offset_seconds"]),
            smooth_factor,
            smooth_repeat,
            source.nbytes + edges.nbytes + triangles.nbytes,
            len(payload),
            float(response["worker_seconds"]),
            roundtrip,
        )
        return wrapped

    def fit_pin_circle(
        self,
        points,
        *,
        edges=None,
        offset: float,
        pass_count: int = 3,
    ) -> np.ndarray:
        """Fit and uniformly redistribute a closed two-part pin loop."""

        total_start = time.perf_counter()
        circle_points = as_vertices(points, "points")
        if len(circle_points) < 3:
            raise ValueError("pin circle must contain at least three points")
        circle_edges = (
            np.empty((0, 2), dtype=np.int32)
            if edges is None
            else as_edges(edges, len(circle_points))
        )
        requested_offset = float(offset)
        if not np.isfinite(requested_offset):
            raise ValueError("pin circle offset must be finite")
        pass_count = int(pass_count)
        if pass_count < 1:
            raise ValueError("pin circle pass_count must be at least one")

        response, payload = self._request(
            {
                "command": "fit_pin_circle",
                "point_count": len(circle_points),
                "edge_count": len(circle_edges),
                "offset": requested_offset,
                "pass_count": pass_count,
            },
            circle_points,
            circle_edges,
        )
        output_count = int(response["point_count"])
        expected_bytes = output_count * 3 * 4
        if len(payload) != expected_bytes:
            raise NearestSurfaceWorkerError(
                "nearest-surface worker returned an invalid pin-circle payload"
            )
        fitted = np.frombuffer(
            payload,
            dtype=np.float32,
            count=output_count * 3,
        ).reshape((output_count, 3))
        for pass_timing in response.get("passes", ()):
            logger.info(
                "Worker pin-circle pass: pid=%d pass=%d/%d points=%d "
                "hits=%d seeded=%d query=%.3fs offset=%.3fs "
                "redistribute=%.3fs total=%.3fs",
                self._process.pid,
                int(pass_timing["pass"]),
                pass_count,
                int(pass_timing["points"]),
                int(pass_timing["hits"]),
                int(pass_timing["seeded"]),
                float(pass_timing["query_seconds"]),
                float(pass_timing["offset_seconds"]),
                float(pass_timing["redistribute_seconds"]),
                float(pass_timing["total_seconds"]),
            )
        logger.info(
            "Worker pin-circle request: pid=%d backend=%s "
            "target_vertices=%d target_triangles=%d points=%d passes=%d "
            "offset=%.6f input_bytes=%d output_bytes=%d worker=%.3fs "
            "roundtrip=%.3fs",
            self._process.pid,
            self.backend,
            self.vertex_count,
            self.triangle_count,
            output_count,
            pass_count,
            requested_offset,
            circle_points.nbytes,
            len(payload),
            float(response["worker_seconds"]),
            time.perf_counter() - total_start,
        )
        return fitted

    def score_undercut_candidates(
        self,
        face_centers,
        face_normals,
        face_areas,
        *,
        section_id: str,
        section_sides,
        known_section_ids,
        eligible_plane_indices,
        plane_points,
        plane_normals,
        remote_candidates,
        local_sections_only: bool,
        split_plane_overtravel: float,
        precise_cost: bool = False,
        ray_epsilon: float = 1.0e-5,
        ray_max_hits: int = 256,
    ) -> tuple[WorkerUndercutResult, ...]:
        """Classify and score one section's server-proposed exit paths."""

        total_start = time.perf_counter()
        centers = as_vertices(face_centers, "face_centers")
        normals = as_vertices(face_normals, "face_normals")
        if len(normals) != len(centers):
            raise ValueError("face_centers and face_normals must have equal length")
        areas = _analysis_areas(face_areas, len(centers))
        points = as_vertices(plane_points, "plane_points")
        plane_normal_array = as_vertices(plane_normals, "plane_normals")
        if len(points) != len(plane_normal_array):
            raise ValueError("plane_points and plane_normals must have equal length")
        overtravel = float(split_plane_overtravel)
        if not np.isfinite(overtravel):
            raise ValueError("split_plane_overtravel must be finite")

        candidates = []
        for candidate in remote_candidates:
            if not isinstance(candidate, dict):
                candidates.append(candidate)
                continue
            candidates.append(
                {
                    "candidate_id": candidate.get("candidate_id"),
                    "plane_index": candidate.get("plane_index"),
                    "direction": list(candidate.get("direction", ())),
                    "path_section_ids": list(
                        candidate.get("path_section_ids", ())
                    ),
                }
            )
        response, payload = self._request(
            {
                "command": "score_undercut_candidates",
                "face_count": len(centers),
                "plane_count": len(points),
                "section_id": str(section_id),
                "section_sides": [int(value) for value in section_sides],
                "known_section_ids": [str(value) for value in known_section_ids],
                "eligible_plane_indices": [
                    int(value) for value in eligible_plane_indices
                ],
                "remote_candidates": candidates,
                "local_sections_only": bool(local_sections_only),
                "split_plane_overtravel": overtravel,
                "precise_cost": bool(precise_cost),
                "ray_epsilon": float(ray_epsilon),
                "ray_max_hits": int(ray_max_hits),
            },
            centers,
            normals,
            areas,
            points,
            plane_normal_array,
        )
        results = _parse_undercut_results(response, payload)
        logger.info(
            "Worker undercut scoring: pid=%d faces=%d planes=%d precise=%s "
            "precise_rays=%d candidates=%d selected_faces=%d input_bytes=%d "
            "output_bytes=%d worker=%.3fs roundtrip=%.3fs",
            self._process.pid,
            len(centers),
            len(points),
            bool(precise_cost),
            int(response.get("precise_ray_count", 0)),
            len(results),
            sum(len(result.face_indices) for result in results),
            centers.nbytes
            + normals.nbytes
            + areas.nbytes
            + points.nbytes
            + plane_normal_array.nbytes,
            len(payload),
            float(response["worker_seconds"]),
            time.perf_counter() - total_start,
        )
        return results

    def build_single_plane_undercut_mesh(
        self,
        vertices,
        face_offsets,
        face_indices,
        *,
        split_point,
        split_normal,
        bidirectional: bool,
        normal_dot_threshold: float,
        overtravel: float,
        face_limit_point=None,
        face_limit_normal=None,
        minimum_area: float = 0.0,
    ) -> WorkerPolygonMeshResult:
        """Clip, classify and build one undercut solid in one worker request."""

        total_start = time.perf_counter()
        vertex_array = as_vertices(vertices, "vertices")
        offsets, indices = _polygon_input(
            face_offsets, face_indices, len(vertex_array)
        )
        point = np.ascontiguousarray(split_point, dtype=np.float32)
        normal = np.ascontiguousarray(split_normal, dtype=np.float32)
        if point.shape != (3,) or normal.shape != (3,):
            raise ValueError("split plane values must contain three values")
        if (face_limit_point is None) != (face_limit_normal is None):
            raise ValueError(
                "face limit point and normal must be supplied together"
            )
        limit_point = (
            None
            if face_limit_point is None
            else [float(value) for value in face_limit_point]
        )
        limit_normal = (
            None
            if face_limit_normal is None
            else [float(value) for value in face_limit_normal]
        )
        response, payload = self._request(
            {
                "command": "build_single_plane_undercut_mesh",
                "vertex_count": len(vertex_array),
                "face_count": len(offsets) - 1,
                "face_value_count": len(indices),
                "split_point": [float(value) for value in point],
                "split_normal": [float(value) for value in normal],
                "bidirectional": bool(bidirectional),
                "normal_dot_threshold": float(normal_dot_threshold),
                "overtravel": float(overtravel),
                "face_limit_point": limit_point,
                "face_limit_normal": limit_normal,
                "minimum_area": float(minimum_area),
            },
            vertex_array,
            offsets,
            indices,
        )
        result = _parse_polygon_mesh(response, payload)
        if not isinstance(result, WorkerPolygonMeshResult):
            raise NearestSurfaceWorkerError(
                "worker returned invalid single-plane undercut mesh"
            )
        roundtrip = time.perf_counter() - total_start
        logger.info(
            "Worker fused single-plane undercut: pid=%d source_vertices=%d "
            "source_faces=%d analyzed_faces=%d crossing_faces=%d "
            "selected_faces=%d output_vertices=%d output_faces=%d "
            "input_bytes=%d output_bytes=%d split=%.3fs classify=%.3fs "
            "build=%.3fs worker=%.3fs roundtrip=%.3fs",
            self._process.pid,
            len(vertex_array),
            len(offsets) - 1,
            int(response["analyzed_face_count"]),
            int(response["crossing_face_count"]),
            int(response["selected_face_count"]),
            len(result.vertices),
            len(result.face_offsets) - 1,
            vertex_array.nbytes + offsets.nbytes + indices.nbytes,
            len(payload),
            float(response["split_seconds"]),
            float(response["classify_seconds"]),
            float(response["build_seconds"]),
            float(response["worker_seconds"]),
            roundtrip,
        )
        return result

    def split_undercut_sections(
        self,
        vertices,
        face_offsets,
        face_indices,
        *,
        plane_points,
        plane_normals,
        section_plane_count: int,
        ray_target_triangles=None,
        return_topology: bool = True,
    ) -> WorkerSectionMeshResult:
        """Bisect an analysis mesh and return indexed section records."""

        total_start = time.perf_counter()
        vertex_array = as_vertices(vertices, "vertices")
        offsets, indices = _polygon_input(
            face_offsets, face_indices, len(vertex_array)
        )
        points = as_vertices(plane_points, "plane_points")
        normals = as_vertices(plane_normals, "plane_normals")
        if len(points) != len(normals):
            raise ValueError("plane arrays must have equal length")
        ray_triangles = (
            np.empty((0, 3), dtype=np.int32)
            if ray_target_triangles is None
            else as_triangles(ray_target_triangles, len(vertex_array))
        )
        response, payload = self._request(
            {
                "command": "split_undercut_sections",
                "vertex_count": len(vertex_array),
                "face_count": len(offsets) - 1,
                "face_value_count": len(indices),
                "plane_count": len(points),
                "section_plane_count": int(section_plane_count),
                "ray_triangle_count": len(ray_triangles),
                "return_topology": bool(return_topology),
            },
            vertex_array,
            offsets,
            indices,
            points,
            normals,
            ray_triangles,
        )
        result = _parse_polygon_mesh(response, payload)
        if not isinstance(result, WorkerSectionMeshResult):
            raise NearestSurfaceWorkerError("worker omitted section records")
        logger.info(
            "Worker undercut section split: pid=%d input_vertices=%d "
            "input_faces=%d planes=%d ray_target_built=%s "
            "ray_triangles=%d topology_returned=%s output_vertices=%d "
            "output_faces=%d "
            "input_bytes=%d output_bytes=%d split=%.3fs split_backend=%s "
            "worker=%.3fs roundtrip=%.3fs",
            self._process.pid,
            len(vertex_array),
            len(offsets) - 1,
            len(points),
            bool(response.get("ray_target_built", False)),
            int(response.get("ray_triangle_count", 0)),
            bool(response.get("include_topology", True)),
            len(result.vertices),
            len(result.face_offsets) - 1,
            vertex_array.nbytes
            + offsets.nbytes
            + indices.nbytes
            + points.nbytes
            + normals.nbytes
            # The source vertices are shared by splitting and BVH construction.
            # Only the triangle index array is additional in the fused request.
            + ray_triangles.nbytes,
            len(payload),
            float(response.get("split_seconds", 0.0)),
            str(response.get("split_backend", "python")),
            float(response["worker_seconds"]),
            time.perf_counter() - total_start,
        )
        return result

    def split_plan_and_build_undercuts(
        self,
        vertices,
        face_offsets,
        face_indices,
        *,
        plane_points,
        plane_normals,
        section_plane_count: int,
        server_request_config: dict,
        requested_plane_count: int,
        boundary_plane_indices,
        local_sections_only: bool,
        easy_extraction: bool,
        restrict_bottom_extraction: bool,
        restrict_bottom_vertical_extraction: bool,
        horizontal_extraction: bool = False,
        mid_horizontal_extraction: bool = False,
        split_overtravel: float,
        clearance_overtravel: float,
        precise_cost: bool = False,
        ray_target_triangles=None,
        ray_epsilon: float = 1.0e-5,
        ray_max_hits: int = 256,
        planning_only: bool = False,
        preview_faces: bool = False,
    ) -> WorkerClearUndercutResult:
        """Split, plan and build while retaining all section records in-worker."""

        total_start = time.perf_counter()
        vertex_array = as_vertices(vertices, "vertices")
        offsets, indices = _polygon_input(
            face_offsets, face_indices, len(vertex_array)
        )
        points = as_vertices(plane_points, "plane_points")
        normals = as_vertices(plane_normals, "plane_normals")
        if len(points) != len(normals):
            raise ValueError("plane arrays must have equal length")
        ray_triangles = (
            np.empty((0, 3), dtype=np.int32)
            if ray_target_triangles is None
            else as_triangles(ray_target_triangles, len(vertex_array))
        )
        header = _undercut_plan_header(
            server_request_config,
            requested_plane_count=requested_plane_count,
            boundary_plane_indices=boundary_plane_indices,
            local_sections_only=local_sections_only,
            easy_extraction=easy_extraction,
            horizontal_extraction=horizontal_extraction,
            mid_horizontal_extraction=mid_horizontal_extraction,
            restrict_bottom_extraction=restrict_bottom_extraction,
            restrict_bottom_vertical_extraction=(
                restrict_bottom_vertical_extraction
            ),
            split_overtravel=split_overtravel,
            clearance_overtravel=clearance_overtravel,
            precise_cost=precise_cost,
            ray_epsilon=ray_epsilon,
            ray_max_hits=ray_max_hits,
            planning_only=planning_only,
        )
        header.update(
            {
                "command": "split_plan_and_build_undercuts",
                "preview_faces": bool(preview_faces),
                "vertex_count": len(vertex_array),
                "face_count": len(offsets) - 1,
                "face_value_count": len(indices),
                "plane_count": len(points),
                "section_plane_count": int(section_plane_count),
                "ray_triangle_count": len(ray_triangles),
            }
        )
        response, payload = self._request(
            header,
            vertex_array,
            offsets,
            indices,
            points,
            normals,
            ray_triangles,
        )
        roundtrip = time.perf_counter() - total_start
        result = _parse_clear_undercut_result(
            response,
            payload,
            roundtrip_seconds=roundtrip,
        )
        logger.info(
            "Worker fused clear-undercut: pid=%d input_vertices=%d "
            "input_faces=%d planes=%d analyzed_faces=%d paths=%d "
            "output_vertices=%d output_faces=%d input_bytes=%d output_bytes=%d "
            "split=%.3fs split_backend=%s ray_target=%.3fs "
            "candidate_request=%.3fs "
            "scoring=%.3fs selection_request=%.3fs build=%.3fs "
            "native=%.3fs backend=%s selected_faces=%d propagated_faces=%d "
            "precise_rays=%d worker=%.3fs roundtrip=%.3fs",
            self._process.pid,
            len(vertex_array),
            len(offsets) - 1,
            len(points),
            result.analyzed_face_count,
            len(result.selected_paths),
            len(result.mesh.vertices),
            len(result.mesh.face_offsets) - 1,
            vertex_array.nbytes
            + offsets.nbytes
            + indices.nbytes
            + points.nbytes
            + normals.nbytes
            + ray_triangles.nbytes,
            len(payload),
            result.split_seconds,
            result.split_backend,
            result.ray_target_seconds,
            result.candidate_request_seconds,
            result.scoring_seconds,
            result.selection_request_seconds,
            result.build_seconds,
            result.native_seconds,
            result.backend,
            result.selected_face_count,
            result.propagated_face_count,
            result.precise_ray_count,
            result.worker_seconds,
            result.roundtrip_seconds,
        )
        for path in sorted(
            result.selected_paths,
            key=lambda value: int(value.get("order", 0)),
        ):
            direction = tuple(float(value) for value in path["direction"])
            logger.info(
                "Worker fused clear-undercut winning path: order=%d "
                "section=%s plane=%d bottom_constrained=%s "
                "direction=(%.4f, %.4f, %.4f) bottom_direction_valid=%s",
                int(path.get("order", 0)),
                tuple(int(side) for side in path["section"]),
                int(path["plane_index"]),
                bool(path.get("bottom_constrained", False)),
                direction[0],
                direction[1],
                direction[2],
                (
                    not bool(path.get("bottom_constrained", False))
                    or direction[2] >= -1.0e-6
                ),
            )
        for section_score in result.candidate_scores:
            section = tuple(
                int(side) for side in section_score.get("section", ())
            )
            candidates = section_score.get("candidates", [])
            if not candidates:
                logger.debug(
                    "Worker fused clear-undercut candidate scores: "
                    "section=%s eligible_planes=%s candidates=0 winner=None",
                    section,
                    tuple(section_score.get("eligible_plane_indices", ())),
                )
                continue
            for candidate in candidates:
                direction = tuple(
                    float(value) for value in candidate["direction"]
                )
                rank = candidate["rank"]
                logger.debug(
                    "Worker fused clear-undercut candidate score: section=%s "
                    "eligible_planes=%s candidate=%s winner=%s plane=%d "
                    "direction=(%.6f, %.6f, %.6f) transit=%d "
                    "combined=%.12g affected_area=%.12g "
                    "swept_volume=%.12g total_distance=%.12g "
                    "affected_faces=%d candidate_position=%d "
                    "path=%s rank=(%d, %.12g, %.12g, %.12g, %d, %d, %d)",
                    section,
                    tuple(section_score.get("eligible_plane_indices", ())),
                    candidate["candidate_id"],
                    bool(candidate.get("selected", False)),
                    int(candidate["plane_index"]),
                    direction[0],
                    direction[1],
                    direction[2],
                    int(candidate["transit_count"]),
                    float(candidate["combined_cost"]),
                    float(candidate["affected_area"]),
                    float(candidate["swept_volume"]),
                    float(candidate["total_distance"]),
                    int(candidate["affected_faces"]),
                    int(rank[6]),
                    tuple(candidate.get("path_section_ids", ())),
                    int(rank[0]),
                    float(rank[1]),
                    float(rank[2]),
                    float(rank[3]),
                    int(rank[4]),
                    int(rank[5]),
                    int(rank[6]),
                )
        return result

    def split_and_build_locked_undercuts(
        self,
        vertices,
        face_offsets,
        face_indices,
        *,
        plane_points,
        plane_normals,
        section_plane_count: int,
        selected_paths,
        split_overtravel: float,
        clearance_overtravel: float,
        local_sections_only: bool,
    ) -> WorkerClearUndercutResult:
        """Split and realize frozen paths in one worker round trip."""

        total_start = time.perf_counter()
        vertex_array = as_vertices(vertices, "vertices")
        offsets, indices = _polygon_input(
            face_offsets, face_indices, len(vertex_array)
        )
        points = as_vertices(plane_points, "plane_points")
        normals = as_vertices(plane_normals, "plane_normals")
        if len(points) != len(normals):
            raise ValueError("plane arrays must have equal length")
        frozen_paths = [dict(path) for path in selected_paths]
        header = {
            "command": "split_and_build_locked_undercuts",
            "vertex_count": len(vertex_array),
            "face_count": len(offsets) - 1,
            "face_value_count": len(indices),
            "plane_count": len(points),
            "section_plane_count": int(section_plane_count),
            "ray_triangle_count": 0,
            "selected_paths": frozen_paths,
            "split_overtravel": float(split_overtravel),
            "clearance_overtravel": float(clearance_overtravel),
            "local_sections_only": bool(local_sections_only),
        }
        response, payload = self._request(
            header,
            vertex_array,
            offsets,
            indices,
            points,
            normals,
        )
        roundtrip = time.perf_counter() - total_start
        result = _parse_clear_undercut_result(
            response,
            payload,
            roundtrip_seconds=roundtrip,
        )
        logger.info(
            "Worker fused locked clear-undercut: pid=%d input_vertices=%d "
            "input_faces=%d planes=%d requested_paths=%d accepted_paths=%d "
            "output_vertices=%d output_faces=%d input_bytes=%d output_bytes=%d "
            "split=%.3fs split_backend=%s build=%.3fs native=%.3fs backend=%s "
            "selected_faces=%d propagated_faces=%d worker=%.3fs roundtrip=%.3fs",
            self._process.pid,
            len(vertex_array),
            len(offsets) - 1,
            len(points),
            len(frozen_paths),
            len(result.selected_paths),
            len(result.mesh.vertices),
            len(result.mesh.face_offsets) - 1,
            sum(
                array.nbytes
                for array in (vertex_array, offsets, indices, points, normals)
            ),
            len(payload),
            result.split_seconds,
            result.split_backend,
            result.build_seconds,
            result.native_seconds,
            result.backend,
            result.selected_face_count,
            result.propagated_face_count,
            result.worker_seconds,
            result.roundtrip_seconds,
        )
        return result

    def plan_preclassified_undercuts(
        self,
        *,
        centers,
        normals,
        areas,
        sections,
        plane_contacts,
        splitting_planes,
        plane_points,
        plane_normals,
        server_request_config: dict,
        requested_plane_count: int,
        boundary_plane_indices,
        local_sections_only: bool,
        easy_extraction: bool,
        restrict_bottom_extraction: bool,
        restrict_bottom_vertical_extraction: bool,
        horizontal_extraction: bool = False,
        mid_horizontal_extraction: bool = False,
        split_overtravel: float,
        clearance_overtravel: float,
        source_face_count: int,
        precise_cost: bool = False,
        ray_vertices=None,
        ray_triangles=None,
        ray_epsilon: float = 1.0e-5,
        ray_max_hits: int = 256,
    ) -> WorkerClearUndercutResult:
        """Plan from Blender's temporary section split without clipping again."""

        total_start = time.perf_counter()
        center_array = as_vertices(centers, "centers")
        normal_array = as_vertices(normals, "normals")
        face_count = len(center_array)
        area_array = np.ascontiguousarray(areas, dtype=np.float32)
        point_array = as_vertices(plane_points, "plane_points")
        plane_normal_array = as_vertices(plane_normals, "plane_normals")
        plane_count = len(point_array)
        section_array = np.ascontiguousarray(sections, dtype=np.int8)
        contact_array = np.ascontiguousarray(plane_contacts, dtype=np.uint8)
        splitting_array = np.ascontiguousarray(
            splitting_planes, dtype=np.uint8
        )
        if len(normal_array) != face_count or area_array.shape != (face_count,):
            raise ValueError("preclassified face records are inconsistent")
        if len(plane_normal_array) != plane_count:
            raise ValueError("plane arrays must have equal length")
        if section_array.shape != (face_count, plane_count):
            raise ValueError("sections must have shape (face_count, plane_count)")
        if contact_array.shape != section_array.shape:
            raise ValueError("plane_contacts must match sections")
        if splitting_array.shape != (plane_count,):
            raise ValueError("splitting_planes must have shape (plane_count,)")
        if not np.all(np.isfinite(area_array)) or np.any(area_array < 0.0):
            raise ValueError("areas contain invalid values")

        ray_vertex_array = (
            np.empty((0, 3), dtype=np.float32)
            if ray_vertices is None
            else as_vertices(ray_vertices, "ray_vertices")
        )
        ray_triangle_array = (
            np.empty((0, 3), dtype=np.int32)
            if ray_triangles is None
            else as_triangles(ray_triangles, len(ray_vertex_array))
        )
        if precise_cost and not len(ray_triangle_array):
            raise ValueError("precise planning requires ray target triangles")

        header = _undercut_plan_header(
            server_request_config,
            requested_plane_count=requested_plane_count,
            boundary_plane_indices=boundary_plane_indices,
            local_sections_only=local_sections_only,
            easy_extraction=easy_extraction,
            horizontal_extraction=horizontal_extraction,
            mid_horizontal_extraction=mid_horizontal_extraction,
            restrict_bottom_extraction=restrict_bottom_extraction,
            restrict_bottom_vertical_extraction=(
                restrict_bottom_vertical_extraction
            ),
            split_overtravel=split_overtravel,
            clearance_overtravel=clearance_overtravel,
            precise_cost=precise_cost,
            ray_epsilon=ray_epsilon,
            ray_max_hits=ray_max_hits,
            planning_only=True,
        )
        header.update(
            {
                "command": "plan_preclassified_undercuts",
                "source_face_count": int(source_face_count),
                "face_count": face_count,
                "plane_count": plane_count,
                "ray_vertex_count": len(ray_vertex_array),
                "ray_triangle_count": len(ray_triangle_array),
            }
        )
        input_arrays = (
            center_array,
            normal_array,
            area_array,
            section_array,
            contact_array,
            splitting_array,
            point_array,
            plane_normal_array,
            ray_vertex_array,
            ray_triangle_array,
        )
        response, payload = self._request(header, *input_arrays)
        roundtrip = time.perf_counter() - total_start
        result = _parse_clear_undercut_result(
            response,
            payload,
            roundtrip_seconds=roundtrip,
        )
        logger.info(
            "Worker preclassified clear-undercut plan: pid=%d "
            "source_faces=%d analyzed_faces=%d planes=%d paths=%d "
            "input_bytes=%d output_bytes=%d ray_target=%.3fs "
            "candidate_request=%.3fs scoring=%.3fs selection_request=%.3fs "
            "worker=%.3fs roundtrip=%.3fs",
            self._process.pid,
            int(source_face_count),
            face_count,
            plane_count,
            len(result.selected_paths),
            sum(array.nbytes for array in input_arrays),
            len(payload),
            result.ray_target_seconds,
            result.candidate_request_seconds,
            result.scoring_seconds,
            result.selection_request_seconds,
            result.worker_seconds,
            result.roundtrip_seconds,
        )
        return result

    def build_native_preclassified_clearance(
        self,
        *,
        vertices,
        face_offsets,
        face_indices,
        centers,
        normals,
        sections,
        plane_points,
        plane_normals,
        section_plane_count: int,
        selected_paths,
        split_overtravel: float,
        clearance_overtravel: float,
        local_sections_only: bool = False,
    ) -> WorkerNativeClearanceResult:
        """Build frozen-path clearances in the compiled native worker core."""

        total_start = time.perf_counter()
        vertex_array = as_vertices(vertices, "vertices")
        offset_array, index_array = _polygon_input(
            face_offsets, face_indices, len(vertex_array)
        )
        center_array = as_vertices(centers, "centers")
        normal_array = as_vertices(normals, "normals")
        face_count = len(offset_array) - 1
        point_array = as_vertices(plane_points, "plane_points")
        plane_normal_array = as_vertices(plane_normals, "plane_normals")
        plane_count = len(point_array)
        section_array = np.ascontiguousarray(sections, dtype=np.int8)
        if (
            len(center_array) != face_count
            or len(normal_array) != face_count
            or section_array.shape != (face_count, plane_count)
            or len(plane_normal_array) != plane_count
        ):
            raise ValueError("native clearance records are inconsistent")
        ordered_paths = sorted(
            (dict(path) for path in selected_paths),
            key=lambda path: int(path["order"]),
        )
        if not ordered_paths:
            raise ValueError("native clearance requires at least one path")
        path_sections = np.ascontiguousarray(
            [path["section"] for path in ordered_paths], dtype=np.int8
        ).reshape((len(ordered_paths), plane_count))
        path_plane_indices = np.ascontiguousarray(
            [int(path["plane_index"]) for path in ordered_paths],
            dtype=np.int32,
        )
        path_directions = as_vertices(
            [path["direction"] for path in ordered_paths], "path_directions"
        )
        projection_values = []
        projection_offsets = [0]
        route_values = []
        route_offsets = [0]
        for path in ordered_paths:
            projection_values.extend(
                int(value) for value in path["projection_plane_indices"]
            )
            projection_offsets.append(len(projection_values))
            route = list(path.get("path_sections") or [path["section"]])
            route_values.extend(route)
            route_offsets.append(len(route_values))
        projection_offset_array = np.ascontiguousarray(
            projection_offsets, dtype=np.int32
        )
        projection_index_array = np.ascontiguousarray(
            projection_values, dtype=np.int32
        )
        route_offset_array = np.ascontiguousarray(
            route_offsets, dtype=np.int32
        )
        route_section_array = np.ascontiguousarray(
            route_values, dtype=np.int8
        ).reshape((-1, plane_count))
        input_arrays = (
            vertex_array,
            offset_array,
            index_array,
            center_array,
            normal_array,
            section_array,
            point_array,
            plane_normal_array,
            path_sections,
            path_plane_indices,
            path_directions,
            projection_offset_array,
            projection_index_array,
            route_offset_array,
            route_section_array,
        )
        header = {
            "command": "build_native_preclassified_clearance",
            "vertex_count": len(vertex_array),
            "face_count": face_count,
            "face_index_count": len(index_array),
            "plane_count": plane_count,
            "section_plane_count": int(section_plane_count),
            "path_count": len(ordered_paths),
            "projection_index_count": len(projection_index_array),
            "route_section_count": len(route_section_array),
            "split_overtravel": float(split_overtravel),
            "clearance_overtravel": float(clearance_overtravel),
            "local_sections_only": bool(local_sections_only),
        }
        response, payload = self._request(header, *input_arrays)
        roundtrip_seconds = time.perf_counter() - total_start
        mesh = _parse_polygon_mesh(response, payload)
        if not isinstance(mesh, WorkerPolygonMeshResult):
            raise NearestSurfaceWorkerError(
                "worker returned invalid native clearance geometry"
            )
        input_bytes = sum(array.nbytes for array in input_arrays)
        result = WorkerNativeClearanceResult(
            mesh=mesh,
            selected_face_count=int(response["selected_face_count"]),
            propagated_face_count=int(response["propagated_face_count"]),
            classify_seconds=float(response["classify_seconds"]),
            build_seconds=float(response["build_seconds"]),
            propagation_seconds=float(response["propagation_seconds"]),
            native_seconds=float(response["native_seconds"]),
            worker_seconds=float(response["worker_seconds"]),
            roundtrip_seconds=roundtrip_seconds,
            input_bytes=input_bytes,
            output_bytes=len(payload),
        )
        logger.info(
            "Worker native clearance construction: pid=%d input_vertices=%d "
            "input_faces=%d paths=%d output_vertices=%d output_faces=%d "
            "selected_faces=%d propagated_faces=%d input_bytes=%d "
            "output_bytes=%d classify=%.3fs build=%.3fs propagation=%.3fs "
            "native=%.3fs worker=%.3fs roundtrip=%.3fs",
            self._process.pid,
            len(vertex_array),
            face_count,
            len(ordered_paths),
            len(mesh.vertices),
            len(mesh.face_offsets) - 1,
            result.selected_face_count,
            result.propagated_face_count,
            input_bytes,
            len(payload),
            result.classify_seconds,
            result.build_seconds,
            result.propagation_seconds,
            result.native_seconds,
            result.worker_seconds,
            result.roundtrip_seconds,
        )
        return result

    def plan_and_build_retained_undercuts(
        self,
        *,
        server_request_config: dict,
        requested_plane_count: int,
        boundary_plane_indices,
        local_sections_only: bool,
        easy_extraction: bool,
        restrict_bottom_extraction: bool,
        restrict_bottom_vertical_extraction: bool,
        horizontal_extraction: bool = False,
        mid_horizontal_extraction: bool = False,
        split_overtravel: float,
        clearance_overtravel: float,
        precise_cost: bool = False,
        ray_epsilon: float = 1.0e-5,
        ray_max_hits: int = 256,
        planning_only: bool = False,
    ) -> WorkerClearUndercutResult:
        """Run both server decisions and all sequential builds in the worker."""

        total_start = time.perf_counter()
        header = _undercut_plan_header(
            server_request_config,
            requested_plane_count=requested_plane_count,
            boundary_plane_indices=boundary_plane_indices,
            local_sections_only=local_sections_only,
            easy_extraction=easy_extraction,
            horizontal_extraction=horizontal_extraction,
            mid_horizontal_extraction=mid_horizontal_extraction,
            restrict_bottom_extraction=restrict_bottom_extraction,
            restrict_bottom_vertical_extraction=(
                restrict_bottom_vertical_extraction
            ),
            split_overtravel=split_overtravel,
            clearance_overtravel=clearance_overtravel,
            precise_cost=precise_cost,
            ray_epsilon=ray_epsilon,
            ray_max_hits=ray_max_hits,
            planning_only=planning_only,
        )
        header["command"] = "plan_and_build_retained_undercuts"
        response, payload = self._request(
            header
        )
        roundtrip = time.perf_counter() - total_start
        result = _parse_clear_undercut_result(
            response,
            payload,
            roundtrip_seconds=roundtrip,
        )
        logger.info(
            "Worker clear-undercut plan/build: pid=%d paths=%d "
            "output_vertices=%d output_faces=%d candidate_request=%.3fs "
            "scoring=%.3fs selection_request=%.3fs build=%.3fs "
            "precise_rays=%d output_bytes=%d worker=%.3fs roundtrip=%.3fs",
            self._process.pid,
            len(result.selected_paths),
            len(result.mesh.vertices),
            len(result.mesh.face_offsets) - 1,
            result.candidate_request_seconds,
            result.scoring_seconds,
            result.selection_request_seconds,
            result.build_seconds,
            result.precise_ray_count,
            len(payload),
            result.worker_seconds,
            result.roundtrip_seconds,
        )
        return result

    def build_retained_undercut_section(
        self,
        *,
        source_section,
        path_sections,
        extraction_direction,
        group_point,
        group_normal,
        projection_points,
        projection_normals,
        allowed_sections,
        split_overtravel: float,
        clearance_overtravel: float,
    ) -> dict:
        """Route, classify, build and propagate one retained section."""

        total_start = time.perf_counter()
        source = np.ascontiguousarray(source_section, dtype=np.int8)
        if source.ndim != 1 or not len(source):
            raise ValueError("source_section must be a non-empty vector")
        plane_count = len(source)

        def section_matrix(values, name):
            array = np.ascontiguousarray(values, dtype=np.int8)
            if array.size == 0:
                return np.empty((0, plane_count), dtype=np.int8)
            if array.ndim != 2 or array.shape[1] != plane_count:
                raise ValueError(f"{name} must match source_section")
            return array

        paths = section_matrix(path_sections, "path_sections")
        allowed = section_matrix(allowed_sections, "allowed_sections")
        direction = np.ascontiguousarray(extraction_direction, dtype=np.float32)
        point = np.ascontiguousarray(group_point, dtype=np.float32)
        normal = np.ascontiguousarray(group_normal, dtype=np.float32)
        if direction.shape != (3,) or point.shape != (3,) or normal.shape != (3,):
            raise ValueError("retained undercut vectors must contain three values")
        projection_point_array = as_vertices(
            projection_points, "projection_points"
        )
        projection_normal_array = as_vertices(
            projection_normals, "projection_normals"
        )
        if len(projection_point_array) != len(projection_normal_array):
            raise ValueError("projection plane arrays must have equal length")
        response, payload = self._request(
            {
                "command": "build_retained_undercut_section",
                "plane_count": plane_count,
                "path_count": len(paths),
                "projection_count": len(projection_point_array),
                "allowed_count": len(allowed),
                "split_overtravel": float(split_overtravel),
                "clearance_overtravel": float(clearance_overtravel),
            },
            source,
            paths,
            direction,
            point,
            normal,
            projection_point_array,
            projection_normal_array,
            allowed,
        )
        if payload:
            raise NearestSurfaceWorkerError(
                "worker returned unexpected retained-section geometry"
            )
        result = {
            key: response[key]
            for key in (
                "selected_face_count",
                "affected_area",
                "swept_volume",
                "propagated_face_count",
                "route_seconds",
                "classify_seconds",
                "build_seconds",
                "split_seconds",
                "worker_seconds",
            )
        }
        logger.info(
            "Worker retained undercut section: pid=%d selected_faces=%d "
            "propagated_faces=%d route=%.3fs classify=%.3fs build=%.3fs "
            "split=%.3fs worker=%.3fs roundtrip=%.3fs input_bytes=%d",
            self._process.pid,
            int(result["selected_face_count"]),
            int(result["propagated_face_count"]),
            float(result["route_seconds"]),
            float(result["classify_seconds"]),
            float(result["build_seconds"]),
            float(result["split_seconds"]),
            float(result["worker_seconds"]),
            time.perf_counter() - total_start,
            sum(
                array.nbytes
                for array in (
                    source,
                    paths,
                    direction,
                    point,
                    normal,
                    projection_point_array,
                    projection_normal_array,
                    allowed,
                )
            ),
        )
        return result

    def finish_retained_undercut_mesh(self) -> WorkerPolygonMeshResult:
        """Return the accumulated clearance mesh and release retained state."""

        total_start = time.perf_counter()
        response, payload = self._request(
            {"command": "finish_retained_undercut_mesh"}
        )
        result = _parse_polygon_mesh(response, payload)
        if not isinstance(result, WorkerPolygonMeshResult):
            raise NearestSurfaceWorkerError(
                "worker returned invalid retained undercut mesh"
            )
        logger.info(
            "Worker retained undercut finish: pid=%d output_vertices=%d "
            "output_faces=%d output_bytes=%d worker=%.3fs roundtrip=%.3fs",
            self._process.pid,
            len(result.vertices),
            len(result.face_offsets) - 1,
            len(payload),
            float(response["worker_seconds"]),
            time.perf_counter() - total_start,
        )
        return result

    def clear_retained_undercut_sections(self) -> None:
        self._request({"command": "clear_retained_undercut_sections"})

    def plan_split_cells(
        self,
        vertices,
        triangles,
        *,
        plane_points,
        plane_normals,
    ) -> WorkerSplitPlanResult:
        """Plan every occupied cell of a sequential plane partition."""

        total_start = time.perf_counter()
        vertex_array = as_vertices(vertices, "vertices")
        triangle_array = as_triangles(triangles, len(vertex_array))
        points = as_vertices(plane_points, "plane_points")
        normals = as_vertices(plane_normals, "plane_normals")
        if len(points) != len(normals):
            raise ValueError("plane arrays must have equal length")
        response, payload = self._request(
            {
                "command": "plan_split_cells",
                "vertex_count": len(vertex_array),
                "triangle_count": len(triangle_array),
                "plane_count": len(points),
            },
            vertex_array,
            triangle_array,
            points,
            normals,
        )
        cell_count = int(response["cell_count"])
        expected_bytes = cell_count * len(points)
        if len(payload) != expected_bytes:
            raise NearestSurfaceWorkerError(
                "geometry worker returned an invalid split plan"
            )
        cells = np.frombuffer(payload, dtype=np.int8).reshape(
            (cell_count, len(points))
        )
        roundtrip = time.perf_counter() - total_start
        logger.info(
            "Worker split-cell plan: pid=%d vertices=%d triangles=%d "
            "planes=%d cells=%d input_bytes=%d output_bytes=%d "
            "worker=%.3fs roundtrip=%.3fs",
            self._process.pid,
            len(vertex_array),
            len(triangle_array),
            len(points),
            len(cells),
            vertex_array.nbytes
            + triangle_array.nbytes
            + points.nbytes
            + normals.nbytes,
            len(payload),
            float(response["worker_seconds"]),
            roundtrip,
        )
        return WorkerSplitPlanResult(
            cells=np.ascontiguousarray(cells, dtype=np.int8),
            worker_seconds=float(response["worker_seconds"]),
            roundtrip_seconds=roundtrip,
        )

    def plan_barrier_routes(
        self,
        *,
        plane_normals,
        part_bounds,
        part_sides,
        mirrored_bounds,
        mirrored_sides,
        male_bounds,
        male_sides,
        male_plane_indices,
        female_bounds,
        female_plane_indices,
        male_on_top_for_horizontal: bool,
    ) -> WorkerBarrierRouteResult:
        """Assign all barrier operations in one metadata-only request."""

        total_start = time.perf_counter()
        normals = as_vertices(plane_normals, "plane_normals")
        plane_count = len(normals)

        def bounds_array(values, name):
            array = np.ascontiguousarray(values, dtype=np.float32)
            if array.ndim != 2 or array.shape[1] != 6:
                raise ValueError(f"{name} must have shape (count, 6)")
            return array

        def sides_array(values, count, name):
            array = np.ascontiguousarray(values, dtype=np.int8)
            if array.shape != (count, plane_count):
                raise ValueError(f"{name} has an invalid shape")
            return array

        def indices_array(values, count, name):
            array = np.ascontiguousarray(values, dtype=np.int32)
            if array.ndim != 1 or len(array) != count:
                raise ValueError(f"{name} has an invalid shape")
            return array

        parts = bounds_array(part_bounds, "part_bounds")
        part_cells = sides_array(part_sides, len(parts), "part_sides")
        mirrored = bounds_array(mirrored_bounds, "mirrored_bounds")
        mirrored_cells = sides_array(
            mirrored_sides, len(mirrored), "mirrored_sides"
        )
        males = bounds_array(male_bounds, "male_bounds")
        male_cells = sides_array(male_sides, len(males), "male_sides")
        male_planes = indices_array(
            male_plane_indices, len(males), "male_plane_indices"
        )
        females = bounds_array(female_bounds, "female_bounds")
        female_planes = indices_array(
            female_plane_indices, len(females), "female_plane_indices"
        )
        response, payload = self._request(
            {
                "command": "plan_barrier_routes",
                "plane_count": plane_count,
                "part_count": len(parts),
                "mirrored_count": len(mirrored),
                "male_count": len(males),
                "female_count": len(females),
                "male_on_top_for_horizontal": bool(
                    male_on_top_for_horizontal
                ),
            },
            normals,
            parts,
            part_cells,
            mirrored,
            mirrored_cells,
            males,
            male_cells,
            male_planes,
            females,
            female_planes,
        )
        male_count = len(males)
        female_count = len(females)
        female_assignment_count = int(response["female_assignment_count"])
        offset = 0
        male_targets = np.frombuffer(
            payload, dtype=np.int32, count=male_count, offset=offset
        )
        offset += male_count * 4
        mirrored_targets = np.frombuffer(
            payload, dtype=np.int32, count=male_count, offset=offset
        )
        offset += male_count * 4
        female_offsets = np.frombuffer(
            payload, dtype=np.int32, count=female_count + 1, offset=offset
        )
        offset += (female_count + 1) * 4
        female_targets = np.frombuffer(
            payload,
            dtype=np.int32,
            count=female_assignment_count,
            offset=offset,
        )
        offset += female_assignment_count * 4
        if offset != len(payload):
            raise NearestSurfaceWorkerError(
                "geometry worker returned an invalid barrier route plan"
            )
        if np.any(male_targets < -1) or np.any(male_targets >= len(parts)):
            raise NearestSurfaceWorkerError(
                "geometry worker returned an invalid male target"
            )
        if np.any(mirrored_targets < -1) or np.any(
            mirrored_targets >= len(mirrored)
        ):
            raise NearestSurfaceWorkerError(
                "geometry worker returned an invalid mirrored target"
            )
        if (
            female_offsets[0] != 0
            or female_offsets[-1] != len(female_targets)
            or np.any(female_offsets[1:] < female_offsets[:-1])
        ):
            raise NearestSurfaceWorkerError(
                "geometry worker returned invalid female route offsets"
            )
        if np.any(female_targets < 0) or np.any(
            female_targets >= len(parts) + len(mirrored)
        ):
            raise NearestSurfaceWorkerError(
                "geometry worker returned an invalid female target"
            )
        roundtrip = time.perf_counter() - total_start
        logger.info(
            "Worker barrier routes: pid=%d parts=%d mirrored=%d males=%d "
            "females=%d female_assignments=%d input_bytes=%d "
            "output_bytes=%d worker=%.3fs roundtrip=%.3fs",
            self._process.pid,
            len(parts),
            len(mirrored),
            len(males),
            len(females),
            len(female_targets),
            sum(
                array.nbytes
                for array in (
                    normals,
                    parts,
                    part_cells,
                    mirrored,
                    mirrored_cells,
                    males,
                    male_cells,
                    male_planes,
                    females,
                    female_planes,
                )
            ),
            len(payload),
            float(response["worker_seconds"]),
            roundtrip,
        )
        return WorkerBarrierRouteResult(
            male_targets=male_targets,
            mirrored_targets=mirrored_targets,
            female_offsets=female_offsets,
            female_targets=female_targets,
            worker_seconds=float(response["worker_seconds"]),
            roundtrip_seconds=roundtrip,
        )

    def plan_axis_barrier_routes(
        self,
        *,
        plane_axes,
        plane_coordinates,
        part_bounds,
        mirrored_bounds,
        male_bounds,
        male_plane_indices,
        female_bounds,
        female_plane_indices,
    ) -> WorkerBarrierRouteResult:
        """Route axis-aligned silicone barriers in one worker request."""

        total_start = time.perf_counter()

        def bounds_array(values, name):
            array = np.ascontiguousarray(values, dtype=np.float32)
            if array.ndim != 2 or array.shape[1] != 6:
                raise ValueError(f"{name} must have shape (count, 6)")
            return array

        axes = np.ascontiguousarray(plane_axes, dtype=np.int8)
        coordinates = np.ascontiguousarray(plane_coordinates, dtype=np.float32)
        if axes.ndim != 1 or coordinates.shape != axes.shape:
            raise ValueError("axis barrier planes must have equal array shapes")
        parts = bounds_array(part_bounds, "part_bounds")
        mirrored = bounds_array(mirrored_bounds, "mirrored_bounds")
        males = bounds_array(male_bounds, "male_bounds")
        females = bounds_array(female_bounds, "female_bounds")
        male_planes = np.ascontiguousarray(male_plane_indices, dtype=np.int32)
        female_planes = np.ascontiguousarray(female_plane_indices, dtype=np.int32)
        if male_planes.shape != (len(males),) or female_planes.shape != (len(females),):
            raise ValueError("axis barrier plane indices have an invalid shape")
        response, payload = self._request(
            {
                "command": "plan_axis_barrier_routes",
                "plane_count": len(axes),
                "part_count": len(parts),
                "mirrored_count": len(mirrored),
                "male_count": len(males),
                "female_count": len(females),
            },
            axes,
            coordinates,
            parts,
            mirrored,
            males,
            male_planes,
            females,
            female_planes,
        )
        female_assignment_count = int(response["female_assignment_count"])
        offset = 0
        male_targets = np.frombuffer(payload, dtype=np.int32, count=len(males), offset=offset)
        offset += len(males) * 4
        mirrored_targets = np.frombuffer(payload, dtype=np.int32, count=len(males), offset=offset)
        offset += len(males) * 4
        female_offsets = np.frombuffer(payload, dtype=np.int32, count=len(females) + 1, offset=offset)
        offset += (len(females) + 1) * 4
        female_targets = np.frombuffer(payload, dtype=np.int32, count=female_assignment_count, offset=offset)
        offset += female_assignment_count * 4
        if offset != len(payload):
            raise NearestSurfaceWorkerError(
                "geometry worker returned an invalid axis barrier route plan"
            )
        roundtrip = time.perf_counter() - total_start
        logger.info(
            "Worker axis barrier routes: pid=%d planes=%d parts=%d mirrored=%d "
            "males=%d females=%d assignments=%d input_bytes=%d output_bytes=%d "
            "worker=%.3fs roundtrip=%.3fs",
            self._process.pid,
            len(axes),
            len(parts),
            len(mirrored),
            len(males),
            len(females),
            len(female_targets),
            sum(array.nbytes for array in (axes, coordinates, parts, mirrored, males, male_planes, females, female_planes)),
            len(payload),
            float(response["worker_seconds"]),
            roundtrip,
        )
        return WorkerBarrierRouteResult(
            male_targets=male_targets,
            mirrored_targets=mirrored_targets,
            female_offsets=female_offsets,
            female_targets=female_targets,
            worker_seconds=float(response["worker_seconds"]),
            roundtrip_seconds=roundtrip,
        )

    def build_undercut_ray_target(self, vertices, triangles) -> None:
        """Build the worker-private target used by precise undercut scoring."""

        total_start = time.perf_counter()
        vertex_array = as_vertices(vertices, "vertices")
        triangle_array = as_triangles(triangles, len(vertex_array))
        response, _payload = self._request(
            {
                "command": "build_undercut_ray_target",
                "vertex_count": len(vertex_array),
                "triangle_count": len(triangle_array),
            },
            vertex_array,
            triangle_array,
        )
        logger.info(
            "Worker undercut ray target: pid=%d backend=%s vertices=%d "
            "triangles=%d nodes=%d input_bytes=%d worker=%.3fs roundtrip=%.3fs",
            self._process.pid,
            response["backend"],
            len(vertex_array),
            len(triangle_array),
            int(response["node_count"]),
            vertex_array.nbytes + triangle_array.nbytes,
            float(response["worker_seconds"]),
            time.perf_counter() - total_start,
        )

    def measure_undercut_rays(
        self,
        origins,
        directions,
        limits,
        *,
        epsilon: float = 1.0e-5,
        max_hits: int = 256,
    ) -> np.ndarray:
        """Measure outside-model ray distance using the worker-private BVH."""

        total_start = time.perf_counter()
        origin_array = as_vertices(origins, "origins")
        direction_array = as_vertices(directions, "directions")
        limit_array = np.ascontiguousarray(limits, dtype=np.float32)
        if len(direction_array) != len(origin_array) or limit_array.shape != (
            len(origin_array),
        ):
            raise ValueError("ray arrays must have equal length")
        response, payload = self._request(
            {
                "command": "measure_undercut_rays",
                "ray_count": len(origin_array),
                "epsilon": float(epsilon),
                "max_hits": int(max_hits),
            },
            origin_array,
            direction_array,
            limit_array,
        )
        expected_bytes = len(origin_array) * 4
        if len(payload) != expected_bytes:
            raise NearestSurfaceWorkerError("worker returned invalid ray distances")
        distances = np.frombuffer(payload, dtype=np.float32)
        logger.info(
            "Worker undercut precise rays: pid=%d rays=%d input_bytes=%d "
            "output_bytes=%d worker=%.3fs roundtrip=%.3fs",
            self._process.pid,
            len(origin_array),
            origin_array.nbytes + direction_array.nbytes + limit_array.nbytes,
            len(payload),
            float(response["worker_seconds"]),
            time.perf_counter() - total_start,
        )
        return distances

    def clear_undercut_ray_target(self) -> None:
        self._request({"command": "clear_undercut_ray_target"})

    def build_master_base_pin_target(self, vertices, triangles) -> None:
        """Build the private BVH used by master-base pin placement."""

        total_start = time.perf_counter()
        vertex_array = as_vertices(vertices, "vertices")
        triangle_array = as_triangles(triangles, len(vertex_array))
        response, _payload = self._request(
            {
                "command": "build_master_base_pin_target",
                "vertex_count": len(vertex_array),
                "triangle_count": len(triangle_array),
            },
            vertex_array,
            triangle_array,
        )
        logger.info(
            "Worker master-base pin target: pid=%d backend=%s vertices=%d "
            "triangles=%d nodes=%d input_bytes=%d worker=%.3fs "
            "roundtrip=%.3fs",
            self._process.pid,
            response["backend"],
            len(vertex_array),
            len(triangle_array),
            int(response["node_count"]),
            vertex_array.nbytes + triangle_array.nbytes,
            float(response["worker_seconds"]),
            time.perf_counter() - total_start,
        )

    def plan_master_base_pin(
        self,
        mesh_bounds,
        *,
        tolerance: float,
        requested_male_height: float,
    ) -> WorkerMasterBasePinResult:
        """Calculate one complete master-base pin placement."""

        total_start = time.perf_counter()
        bounds = np.ascontiguousarray(mesh_bounds, dtype=np.float32)
        if bounds.shape != (6,) or not np.all(np.isfinite(bounds)):
            raise ValueError("mesh_bounds must contain six finite values")
        response, payload = self._request(
            {
                "command": "plan_master_base_pin",
                "tolerance": float(tolerance),
                "requested_male_height": float(requested_male_height),
            },
            bounds,
        )
        if payload:
            raise NearestSurfaceWorkerError(
                "worker returned an invalid master-base pin payload"
            )
        accepted = bool(response["accepted"])
        center = response.get("center")
        roundtrip = time.perf_counter() - total_start
        result = WorkerMasterBasePinResult(
            accepted=accepted,
            checker_failed=bool(response["checker_failed"]),
            failed_stage=(
                str(response["failed_stage"])
                if response.get("failed_stage") is not None
                else None
            ),
            bottom_inside=(
                int(response["bottom_inside"])
                if response.get("bottom_inside") is not None
                else None
            ),
            bottom_total=int(response.get("bottom_total", 4)),
            bottom_crossings=(
                tuple(int(value) for value in response["bottom_crossings"])
                if response.get("bottom_crossings") is not None
                else None
            ),
            top_inside=(
                int(response["top_inside"])
                if response.get("top_inside") is not None
                else None
            ),
            top_total=int(
                response.get("top_total", (4 + 1) ** 2)
            ),
            top_crossings=(
                tuple(int(value) for value in response["top_crossings"])
                if response.get("top_crossings") is not None
                else None
            ),
            center=(
                (float(center[0]), float(center[1]))
                if center is not None
                else None
            ),
            pin_size=(
                float(response["pin_size"])
                if response.get("pin_size") is not None
                else None
            ),
            female_bottom_z=(
                float(response["female_bottom_z"])
                if response.get("female_bottom_z") is not None
                else None
            ),
            female_height=(
                float(response["female_height"]) if accepted else None
            ),
            male_height=(
                float(response["male_height"]) if accepted else None
            ),
            worker_seconds=float(response["worker_seconds"]),
            roundtrip_seconds=roundtrip,
        )
        bottom_summary = (
            "not_run"
            if result.bottom_inside is None
            else f"{result.bottom_inside}/{result.bottom_total}"
        )
        top_summary = (
            "not_run"
            if result.top_inside is None
            else f"{result.top_inside}/{result.top_total}"
        )
        logger.info(
            "Worker master-base pin plan: pid=%d accepted=%s "
            "checker_failed=%s failed_stage=%s bottom_inside=%s "
            "bottom_crossings=%s top_inside=%s top_crossings=%s "
            "input_bytes=%d worker=%.3fs "
            "roundtrip=%.3fs",
            self._process.pid,
            result.accepted,
            result.checker_failed,
            result.failed_stage,
            bottom_summary,
            result.bottom_crossings,
            top_summary,
            result.top_crossings,
            bounds.nbytes,
            result.worker_seconds,
            result.roundtrip_seconds,
        )
        return result

    def clear_master_base_pin_target(self) -> None:
        self._request({"command": "clear_master_base_pin_target"})

    def clean_slicer_mesh(
        self,
        vertices,
        triangles,
        matrix_world,
        *,
        generated_box: bool,
        max_passes: int = 2,
        source_polygon_count: int | None = None,
        weld_distance: float | None = None,
    ) -> WorkerSlicerCleanupResult:
        """Run fused STL preflight and repair in the geometry worker."""

        total_start = time.perf_counter()
        vertex_array = as_vertices(vertices, "vertices")
        triangle_array = np.ascontiguousarray(triangles, dtype=np.int32)
        if triangle_array.ndim != 2 or triangle_array.shape[1] != 3:
            raise ValueError("triangles must have shape (n, 3)")
        if len(triangle_array) and (
            np.any(triangle_array < 0)
            or np.any(triangle_array >= len(vertex_array))
        ):
            raise ValueError("triangles contain an out-of-range vertex")
        matrix = np.ascontiguousarray(matrix_world, dtype=np.float32)
        if matrix.shape != (4, 4) or not np.all(np.isfinite(matrix)):
            raise ValueError("matrix_world must have shape (4, 4)")
        response, payload = self._request(
            {
                "command": "clean_slicer_mesh",
                "vertex_count": len(vertex_array),
                "triangle_count": len(triangle_array),
                "source_polygon_count": int(
                    len(triangle_array)
                    if source_polygon_count is None
                    else source_polygon_count
                ),
                "generated_box": bool(generated_box),
                "max_passes": int(max_passes),
                "weld_distance": (
                    None if weld_distance is None else float(weld_distance)
                ),
            },
            vertex_array,
            triangle_array,
            matrix,
        )
        output_vertex_count = int(response["vertex_count"])
        output_triangle_count = int(response["triangle_count"])
        if bool(response.get("geometry_returned", True)):
            offset = 0
            output_vertices = np.frombuffer(
                payload,
                dtype=np.float32,
                count=output_vertex_count * 3,
                offset=offset,
            ).reshape((output_vertex_count, 3))
            offset += output_vertex_count * 3 * 4
            output_triangles = np.frombuffer(
                payload,
                dtype=np.int32,
                count=output_triangle_count * 3,
                offset=offset,
            ).reshape((output_triangle_count, 3))
            offset += output_triangle_count * 3 * 4
            face_sources = np.frombuffer(
                payload,
                dtype=np.int32,
                count=output_triangle_count,
                offset=offset,
            )
            offset += output_triangle_count * 4
            if offset != len(payload):
                raise NearestSurfaceWorkerError(
                    "worker returned an invalid slicer cleanup payload"
                )
        else:
            if payload:
                raise NearestSurfaceWorkerError(
                    "worker returned unexpected clean-mesh geometry"
                )
            if (
                output_vertex_count != len(vertex_array)
                or output_triangle_count != len(triangle_array)
            ):
                raise NearestSurfaceWorkerError(
                    "worker omitted changed slicer cleanup geometry"
                )
            output_vertices = vertex_array.copy()
            output_triangles = triangle_array.copy()
            face_sources = np.arange(
                len(output_triangles), dtype=np.int32
            )
        roundtrip = time.perf_counter() - total_start
        result = WorkerSlicerCleanupResult(
            vertices=output_vertices,
            triangles=output_triangles,
            face_sources=face_sources,
            changed=bool(response["changed"]),
            initial=dict(response["initial"]),
            final=dict(response["final"]),
            stats=dict(response["stats"]),
            passes=tuple(dict(value) for value in response.get("passes", ())),
            weld_distance=float(response["weld_distance"]),
            preflight_seconds=float(response.get("preflight_seconds", 0.0)),
            pipeline_seconds=float(response.get("pipeline_seconds", 0.0)),
            worker_seconds=float(response["worker_seconds"]),
            roundtrip_seconds=roundtrip,
        )
        logger.info(
            "Worker STL cleanup: pid=%d input_vertices=%d input_triangles=%d "
            "output_vertices=%d output_triangles=%d generated_box=%s "
            "changed=%s initial=%s final=%s passes=%d input_bytes=%d "
            "output_bytes=%d preflight=%.3fs pipeline=%.3fs worker=%.3fs "
            "roundtrip=%.3fs",
            self._process.pid,
            len(vertex_array),
            len(triangle_array),
            len(result.vertices),
            len(result.triangles),
            bool(generated_box),
            result.changed,
            result.initial.get("reason"),
            result.final.get("reason"),
            len(result.passes),
            vertex_array.nbytes + triangle_array.nbytes + matrix.nbytes,
            len(payload),
            result.preflight_seconds,
            result.pipeline_seconds,
            result.worker_seconds,
            result.roundtrip_seconds,
        )
        return result

    def analyze_model_orientation(
        self,
        vertices,
        triangles,
        matrix_world,
        *,
        selected_triangle_indices=None,
        target_reduction: float | None = None,
        max_tilt_degrees: float = 30.0,
        min_footprint_ratio: float = 0.03,
        min_tilt_degrees: float = 0.0,
        place_base_on_top: bool = False,
    ) -> WorkerOrientationAnalysis:
        """Return orientation planning plus reusable source-mesh metadata."""

        total_start = time.perf_counter()
        vertex_array = as_vertices(vertices, "vertices")
        triangle_array = as_triangles(triangles, len(vertex_array))
        matrix = np.ascontiguousarray(matrix_world, dtype=np.float32)
        if matrix.shape != (4, 4) or not np.all(np.isfinite(matrix)):
            raise ValueError("matrix_world must have shape (4, 4)")
        if selected_triangle_indices is None:
            mode = "AUTO"
            selected = np.empty(0, dtype=np.int32)
        else:
            mode = "SELECTED"
            selected = np.ascontiguousarray(
                selected_triangle_indices, dtype=np.int32
            )
            if selected.ndim != 1 or not len(selected):
                raise ValueError(
                    "selected_triangle_indices must be a non-empty vector"
                )
            if np.any(selected < 0) or np.any(selected >= len(triangle_array)):
                raise ValueError("selected triangle index is out of range")
        reduction = 0.0 if target_reduction is None else float(target_reduction)
        if not np.isfinite(reduction) or not 0.0 <= reduction < 1.0:
            raise ValueError("target_reduction must be finite and in [0, 1)")

        response, payload = self._request(
            {
                "command": "plan_model_orientation",
                "mode": mode,
                "vertex_count": len(vertex_array),
                "triangle_count": len(triangle_array),
                "selected_triangle_count": len(selected),
                "target_reduction": reduction,
                "max_tilt_degrees": float(max_tilt_degrees),
                "min_footprint_ratio": float(min_footprint_ratio),
                "min_tilt_degrees": float(min_tilt_degrees),
                "place_base_on_top": bool(place_base_on_top),
            },
            vertex_array,
            triangle_array,
            matrix,
            selected,
        )
        if payload:
            raise NearestSurfaceWorkerError(
                "worker returned an invalid model-orientation payload"
            )
        roundtrip = time.perf_counter() - total_start
        if not bool(response["found"]):
            logger.info(
                "Worker model orientation: pid=%d mode=%s found=false "
                "source_triangles=%d analysis_triangles=%d worker=%.3fs "
                "roundtrip=%.3fs",
                self._process.pid,
                mode,
                len(triangle_array),
                int(response["analysis_triangle_count"]),
                float(response["worker_seconds"]),
                roundtrip,
            )
            return WorkerOrientationAnalysis(
                plan=None,
                source_volume=float(response["source_volume"]),
            )
        plan = response["plan"]
        result = WorkerOrientationPlan(
            x_rotation_radians=float(plan["x_rotation_radians"]),
            y_rotation_radians=float(plan["y_rotation_radians"]),
            z_rotation_degrees=float(plan["z_rotation_degrees"]),
            pivot=tuple(float(value) for value in plan["pivot"]),
            base_normal=tuple(float(value) for value in plan["base_normal"]),
            base_area=float(plan["base_area"]),
            base_tilt_degrees=float(plan["base_tilt_degrees"]),
            world_transform=np.ascontiguousarray(
                plan["world_transform"], dtype=np.float32
            ).reshape((4, 4)),
            source_vertex_count=int(response["source_vertex_count"]),
            source_triangle_count=int(response["source_triangle_count"]),
            analysis_vertex_count=int(response["analysis_vertex_count"]),
            analysis_triangle_count=int(response["analysis_triangle_count"]),
            target_reduction=float(response["target_reduction"]),
            simplification_seconds=float(response["simplification_seconds"]),
            simplification_backend=str(response["simplification_backend"]),
            worker_seconds=float(response["worker_seconds"]),
            roundtrip_seconds=roundtrip,
        )
        logger.info(
            "Worker model orientation: pid=%d mode=%s found=true "
            "source_vertices=%d source_triangles=%d analysis_vertices=%d "
            "analysis_triangles=%d target_reduction=%.2f%% simplify=%.3fs "
            "worker=%.3fs roundtrip=%.3fs input_bytes=%d",
            self._process.pid,
            mode,
            result.source_vertex_count,
            result.source_triangle_count,
            result.analysis_vertex_count,
            result.analysis_triangle_count,
            result.target_reduction * 100.0,
            result.simplification_seconds,
            result.worker_seconds,
            result.roundtrip_seconds,
            vertex_array.nbytes
            + triangle_array.nbytes
            + matrix.nbytes
            + selected.nbytes,
        )
        return WorkerOrientationAnalysis(
            plan=result,
            source_volume=float(response["source_volume"]),
        )

    def plan_model_orientation(self, *args, **kwargs) -> WorkerOrientationPlan | None:
        """Compatibility wrapper returning only the requested orientation plan."""

        return self.analyze_model_orientation(*args, **kwargs).plan

    def build_undercut_mesh(
        self,
        vertices,
        face_offsets,
        face_indices,
        face_groups,
        *,
        group_points,
        group_normals,
        group_directions,
        projection_plane_offsets,
        projection_plane_points,
        projection_plane_normals,
        overtravel: float,
        split_plane_points=None,
        split_plane_normals=None,
        section_plane_count: int | None = None,
        propagation_allowed_sections=None,
        propagation_existing_sections=None,
        clearance_overtravel: float | None = None,
    ) -> WorkerPolygonMeshResult | WorkerSectionMeshResult:
        """Build grouped undercut solids and optionally split them in-worker."""

        total_start = time.perf_counter()
        vertex_array = as_vertices(vertices, "vertices")
        offsets, indices = _polygon_input(
            face_offsets, face_indices, len(vertex_array)
        )
        groups = np.ascontiguousarray(face_groups, dtype=np.int32)
        if groups.shape != (len(offsets) - 1,):
            raise ValueError("face_groups must match polygons")
        points = as_vertices(group_points, "group_points")
        normals = as_vertices(group_normals, "group_normals")
        directions = as_vertices(group_directions, "group_directions")
        projection_offsets = np.ascontiguousarray(
            projection_plane_offsets, dtype=np.int32
        )
        projection_points = as_vertices(
            projection_plane_points, "projection_plane_points"
        )
        projection_normals = as_vertices(
            projection_plane_normals, "projection_plane_normals"
        )
        split_requested = (
            split_plane_points is not None
            or split_plane_normals is not None
            or section_plane_count is not None
        )
        if split_requested and (
            split_plane_points is None
            or split_plane_normals is None
            or section_plane_count is None
        ):
            raise ValueError(
                "split plane points, normals, and section count must be provided together"
            )
        empty_planes = np.empty((0, 3), dtype=np.float32)
        split_points = as_vertices(
            empty_planes if split_plane_points is None else split_plane_points,
            "split_plane_points",
        )
        split_normals = as_vertices(
            empty_planes if split_plane_normals is None else split_plane_normals,
            "split_plane_normals",
        )
        if len(split_points) != len(split_normals):
            raise ValueError("split plane arrays must have equal length")
        command = (
            "build_split_undercut_mesh"
            if split_requested
            else "build_undercut_mesh"
        )
        propagation_requested = propagation_allowed_sections is not None
        if propagation_requested and not split_requested:
            raise ValueError("propagation routing requires an in-worker split")
        if clearance_overtravel is not None and not split_requested:
            raise ValueError("secondary clearance build requires an in-worker split")
        allowed_sections = [
            [int(value) for value in section]
            for section in (propagation_allowed_sections or ())
        ]
        existing_sections = [
            [int(value) for value in section]
            for section in (propagation_existing_sections or ())
        ]
        request = {
            "command": command,
            "vertex_count": len(vertex_array),
            "face_count": len(offsets) - 1,
            "face_value_count": len(indices),
            "group_count": len(points),
            "projection_plane_count": len(projection_points),
            "split_plane_count": len(split_points),
            "section_plane_count": (
                0 if section_plane_count is None else int(section_plane_count)
            ),
            "overtravel": float(overtravel),
            "clearance_overtravel": (
                None
                if clearance_overtravel is None
                else float(clearance_overtravel)
            ),
        }
        if propagation_requested:
            request.update(
                propagation_allowed_sections=allowed_sections,
                propagation_existing_sections=existing_sections,
            )
        response, payload = self._request(
            request,
            vertex_array,
            offsets,
            indices,
            groups,
            points,
            normals,
            directions,
            projection_offsets,
            projection_points,
            projection_normals,
            split_points,
            split_normals,
        )
        result = _parse_polygon_mesh(response, payload)
        expected_type = (
            WorkerSectionMeshResult if split_requested else WorkerPolygonMeshResult
        )
        if not isinstance(result, expected_type):
            raise NearestSurfaceWorkerError("worker returned invalid undercut mesh")
        logger.info(
            "Worker undercut mesh build%s: pid=%d source_vertices=%d "
            "source_faces=%d groups=%d output_vertices=%d output_faces=%d "
            "input_bytes=%d output_bytes=%d worker=%.3fs roundtrip=%.3fs",
            "+split" if split_requested else "",
            self._process.pid,
            len(vertex_array),
            len(offsets) - 1,
            len(points),
            len(result.vertices),
            len(result.face_offsets) - 1,
            sum(
                array.nbytes
                for array in (
                    vertex_array,
                    offsets,
                    indices,
                    groups,
                    points,
                    normals,
                    directions,
                    projection_offsets,
                    projection_points,
                    projection_normals,
                    split_points,
                    split_normals,
                )
            ),
            len(payload),
            float(response["worker_seconds"]),
            time.perf_counter() - total_start,
        )
        return result

    def classify_undercut_faces(
        self,
        face_centers,
        face_normals,
        face_areas,
        *,
        direction,
        plane_points,
        plane_normals,
        split_plane_overtravel: float,
    ) -> WorkerUndercutResult:
        """Classify owned faces for one frozen extraction path."""

        total_start = time.perf_counter()
        centers = as_vertices(face_centers, "face_centers")
        normals = as_vertices(face_normals, "face_normals")
        if len(normals) != len(centers):
            raise ValueError("face_centers and face_normals must have equal length")
        areas = _analysis_areas(face_areas, len(centers))
        points = as_vertices(plane_points, "plane_points")
        plane_normal_array = as_vertices(plane_normals, "plane_normals")
        if len(points) != len(plane_normal_array):
            raise ValueError("plane_points and plane_normals must have equal length")
        direction_values = np.ascontiguousarray(direction, dtype=np.float32)
        if direction_values.shape != (3,) or not np.all(
            np.isfinite(direction_values)
        ):
            raise ValueError("direction must contain three finite values")
        overtravel = float(split_plane_overtravel)
        if not np.isfinite(overtravel):
            raise ValueError("split_plane_overtravel must be finite")

        response, payload = self._request(
            {
                "command": "classify_undercut_faces",
                "face_count": len(centers),
                "plane_count": len(points),
                "direction": [float(value) for value in direction_values],
                "split_plane_overtravel": overtravel,
            },
            centers,
            normals,
            areas,
            points,
            plane_normal_array,
        )
        results = _parse_undercut_results(response, payload)
        if len(results) != 1:
            raise NearestSurfaceWorkerError(
                "geometry worker returned an invalid face-classification result"
            )
        result = results[0]
        logger.info(
            "Worker undercut classification: pid=%d faces=%d planes=%d "
            "selected_faces=%d input_bytes=%d output_bytes=%d "
            "worker=%.3fs roundtrip=%.3fs",
            self._process.pid,
            len(centers),
            len(points),
            len(result.face_indices),
            centers.nbytes
            + normals.nbytes
            + areas.nbytes
            + points.nbytes
            + plane_normal_array.nbytes,
            len(payload),
            float(response["worker_seconds"]),
            time.perf_counter() - total_start,
        )
        return result

    def classify_split_undercut_faces(
        self,
        face_centers,
        face_normals,
        *,
        split_point,
        split_normal,
        bidirectional: bool,
        normal_dot_threshold: float,
        face_limit_point=None,
        face_limit_normal=None,
        face_offsets=None,
        face_indices=None,
        face_areas=None,
        minimum_area: float = 0.0,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Classify the legacy one-plane undercut path in the worker."""

        total_start = time.perf_counter()
        centers = as_vertices(face_centers, "face_centers")
        normals = as_vertices(face_normals, "face_normals")
        if len(normals) != len(centers):
            raise ValueError("face_centers and face_normals must have equal length")
        point = np.ascontiguousarray(split_point, dtype=np.float32)
        normal = np.ascontiguousarray(split_normal, dtype=np.float32)
        if point.shape != (3,) or normal.shape != (3,):
            raise ValueError("split plane values must contain three values")
        limit_point = (
            None
            if face_limit_point is None
            else [float(value) for value in face_limit_point]
        )
        limit_normal = (
            None
            if face_limit_normal is None
            else [float(value) for value in face_limit_normal]
        )
        topology_parts = ()
        topology_value_count = 0
        supplied_topology = (
            face_offsets is not None
            or face_indices is not None
            or face_areas is not None
        )
        if supplied_topology:
            if face_offsets is None or face_indices is None or face_areas is None:
                raise ValueError("all face topology arrays must be supplied together")
            topology_offsets, topology_indices = _polygon_input(
                face_offsets,
                face_indices,
                max(int(np.max(face_indices)) + 1, 1) if len(face_indices) else 1,
            )
            if len(topology_offsets) - 1 != len(centers):
                raise ValueError("face topology must match analyzed faces")
            topology_areas = _analysis_areas(face_areas, len(centers))
            topology_parts = (
                topology_offsets,
                topology_indices,
                topology_areas,
            )
            topology_value_count = len(topology_indices)
        response, payload = self._request(
            {
                "command": "classify_split_undercut_faces",
                "face_count": len(centers),
                "split_point": [float(value) for value in point],
                "split_normal": [float(value) for value in normal],
                "bidirectional": bool(bidirectional),
                "normal_dot_threshold": float(normal_dot_threshold),
                "face_limit_point": limit_point,
                "face_limit_normal": limit_normal,
                "topology_value_count": topology_value_count,
                "minimum_area": float(minimum_area),
            },
            centers,
            normals,
            *topology_parts,
        )
        count = int(response["value_count"])
        expected_bytes = count * 8
        if len(payload) != expected_bytes:
            raise NearestSurfaceWorkerError(
                "geometry worker returned an invalid split-classification payload"
            )
        face_indices = np.frombuffer(
            payload, dtype=np.int32, count=count
        )
        sides = np.frombuffer(
            payload, dtype=np.int32, count=count, offset=count * 4
        )
        logger.info(
            "Worker split-undercut classification: pid=%d faces=%d "
            "selected_faces=%d bidirectional=%s input_bytes=%d "
            "output_bytes=%d worker=%.3fs roundtrip=%.3fs",
            self._process.pid,
            len(centers),
            count,
            bool(bidirectional),
            centers.nbytes + normals.nbytes,
            len(payload),
            float(response["worker_seconds"]),
            time.perf_counter() - total_start,
        )
        return face_indices, sides

    def voxel_remesh(
        self,
        source_vertices,
        source_triangles,
        *,
        voxel_size: float,
        adaptivity: float = 0.0,
    ) -> WorkerMeshResult:
        """Voxel-remesh one mesh without requiring a retained BVH target."""

        total_start = time.perf_counter()
        source = as_vertices(source_vertices, "source_vertices")
        triangles = as_triangles(source_triangles, len(source))
        voxel_size = float(voxel_size)
        adaptivity = float(adaptivity)
        if not np.isfinite(voxel_size) or voxel_size <= 0.0:
            raise ValueError("voxel_size must be finite and greater than zero")
        if not np.isfinite(adaptivity) or not 0.0 <= adaptivity <= 1.0:
            raise ValueError("adaptivity must be between zero and one")
        response, payload = self._request(
            {
                "command": "voxel_remesh",
                "point_count": len(source),
                "triangle_count": len(triangles),
                "voxel_size": voxel_size,
                "adaptivity": adaptivity,
            },
            source,
            triangles,
        )
        point_count = int(response["point_count"])
        triangle_count = int(response["triangle_count"])
        quad_count = int(response["quad_count"])
        vertex_bytes = point_count * 3 * 4
        triangle_bytes = triangle_count * 3 * 4
        quad_bytes = quad_count * 4 * 4
        if len(payload) != vertex_bytes + triangle_bytes + quad_bytes:
            raise NearestSurfaceWorkerError(
                "geometry worker returned an invalid voxel-remesh payload"
            )
        payload_offset = 0
        vertices = np.frombuffer(
            payload,
            dtype=np.float32,
            count=point_count * 3,
            offset=payload_offset,
        ).reshape((point_count, 3))
        payload_offset += vertex_bytes
        output_triangles = np.frombuffer(
            payload,
            dtype=np.int32,
            count=triangle_count * 3,
            offset=payload_offset,
        ).reshape((triangle_count, 3))
        payload_offset += triangle_bytes
        quads = np.frombuffer(
            payload,
            dtype=np.int32,
            count=quad_count * 4,
            offset=payload_offset,
        ).reshape((quad_count, 4))
        logger.info(
            "Worker voxel remesh request: pid=%d backend=%s "
            "input_vertices=%d input_triangles=%d voxel_size=%.6f "
            "output_vertices=%d output_triangles=%d output_quads=%d "
            "input_bytes=%d output_bytes=%d grid=%.3fs mesh=%.3fs "
            "voxel=%.3fs worker=%.3fs roundtrip=%.3fs",
            self._process.pid,
            response["voxel_backend"],
            len(source),
            len(triangles),
            voxel_size,
            point_count,
            triangle_count,
            quad_count,
            source.nbytes + triangles.nbytes,
            len(payload),
            float(response["voxel_grid_seconds"]),
            float(response["voxel_mesh_seconds"]),
            float(response["voxel_remesh_seconds"]),
            float(response["worker_seconds"]),
            time.perf_counter() - total_start,
        )
        return WorkerMeshResult(vertices, output_triangles, quads)

    def voxel_remesh_wrap_sequence(
        self,
        source_vertices,
        source_triangles,
        *,
        voxel_size: float,
        wrap_count: int,
        normal_offset: float = 0.0,
        offset: float = 0.0,
        smooth_factor: float = 0.5,
        smooth_repeat: int = 5,
        adaptivity: float = 0.0,
        max_distance: float | None = None,
    ) -> WorkerMeshResult:
        """Voxel-remesh once, then smooth/wrap without another round-trip."""

        total_start = time.perf_counter()
        source = as_vertices(source_vertices, "source_vertices")
        triangles = as_triangles(source_triangles, len(source))
        voxel_size = float(voxel_size)
        adaptivity = float(adaptivity)
        wrap_count = int(wrap_count)
        smooth_repeat = int(smooth_repeat)
        smooth_factor = float(smooth_factor)
        normal_offset = float(normal_offset)
        if not np.isfinite(voxel_size) or voxel_size <= 0.0:
            raise ValueError("voxel_size must be finite and greater than zero")
        if not np.isfinite(adaptivity) or not 0.0 <= adaptivity <= 1.0:
            raise ValueError("adaptivity must be between zero and one")
        if wrap_count < 0:
            raise ValueError("wrap_count cannot be negative")
        if smooth_repeat < 0:
            raise ValueError("smooth_repeat cannot be negative")
        if not np.isfinite(smooth_factor):
            raise ValueError("smooth_factor must be finite")
        if not np.isfinite(normal_offset):
            raise ValueError("normal_offset must be finite")
        if max_distance is not None and max_distance < 0.0:
            raise ValueError("max_distance cannot be negative")

        response, payload = self._request(
            {
                "command": "voxel_remesh_wrap_sequence",
                "point_count": len(source),
                "triangle_count": len(triangles),
                "voxel_size": voxel_size,
                "adaptivity": adaptivity,
                "wrap_count": wrap_count,
                "normal_offset": normal_offset,
                "offset": float(offset),
                "smooth_factor": smooth_factor,
                "smooth_repeat": smooth_repeat,
                "max_distance": max_distance,
            },
            source,
            triangles,
        )
        point_count = int(response["point_count"])
        triangle_count = int(response["triangle_count"])
        quad_count = int(response["quad_count"])
        vertex_bytes = point_count * 3 * 4
        triangle_bytes = triangle_count * 3 * 4
        quad_bytes = quad_count * 4 * 4
        expected_bytes = vertex_bytes + triangle_bytes + quad_bytes
        if len(payload) != expected_bytes:
            raise NearestSurfaceWorkerError(
                "nearest-surface worker returned an invalid remeshed payload"
            )
        payload_offset = 0
        vertices = np.frombuffer(
            payload,
            dtype=np.float32,
            count=point_count * 3,
            offset=payload_offset,
        ).reshape((point_count, 3))
        payload_offset += vertex_bytes
        output_triangles = np.frombuffer(
            payload,
            dtype=np.int32,
            count=triangle_count * 3,
            offset=payload_offset,
        ).reshape((triangle_count, 3))
        payload_offset += triangle_bytes
        quads = np.frombuffer(
            payload,
            dtype=np.int32,
            count=quad_count * 4,
            offset=payload_offset,
        ).reshape((quad_count, 4))
        roundtrip = time.perf_counter() - total_start

        for pass_timing in response.get("passes", ()):
            logger.info(
                "Nearest-surface worker remesh sequence pass: pid=%d "
                "backend=%s pass=%d/%d points=%d hits=%d seeded=%d "
                "smoothing=%.3fs query=%.3fs offset_apply=%.3fs "
                "total=%.3fs",
                self._process.pid,
                self.backend,
                int(pass_timing["pass"]),
                wrap_count,
                point_count,
                int(pass_timing["hits"]),
                int(pass_timing["seeded"]),
                float(pass_timing["smooth_seconds"]),
                float(pass_timing["query_seconds"]),
                float(pass_timing["offset_seconds"]),
                float(pass_timing["total_seconds"]),
            )
        logger.info(
            "Nearest-surface worker voxel-remesh sequence: pid=%d "
            "backend=%s voxel_backend=%s input_vertices=%d "
            "input_triangles=%d voxel_size=%.6f isovalue=%.6f "
            "normal_offset=%.6f normal_backend=%s normal_time=%.3fs "
            "output_vertices=%d "
            "output_triangles=%d output_quads=%d edges=%d wraps=%d "
            "input_bytes=%d output_bytes=%d voxel_grid=%.3fs "
            "voxel_mesh=%.3fs voxel_total=%.3fs edge_build=%.3fs "
            "worker=%.3fs roundtrip=%.3fs",
            self._process.pid,
            self.backend,
            response["voxel_backend"],
            len(source),
            len(triangles),
            voxel_size,
            float(response["voxel_isovalue"]),
            normal_offset,
            response["normal_offset_backend"],
            float(response["normal_offset_seconds"]),
            point_count,
            triangle_count,
            quad_count,
            int(response["edge_count"]),
            wrap_count,
            source.nbytes + triangles.nbytes,
            len(payload),
            float(response["voxel_grid_seconds"]),
            float(response["voxel_mesh_seconds"]),
            float(response["voxel_remesh_seconds"]),
            float(response["edge_seconds"]),
            float(response["worker_seconds"]),
            roundtrip,
        )
        return WorkerMeshResult(
            vertices=vertices,
            triangles=output_triangles,
            quads=quads,
        )

    def simplification_available(self) -> bool:
        """Return whether fast-simplification imports in the worker runtime."""

        response, payload = self._request({"command": "simplification_status"})
        if payload:
            raise NearestSurfaceWorkerError(
                "geometry worker returned an invalid simplification-status payload"
            )
        available = bool(response["available"])
        logger.info(
            "Geometry worker simplification status: pid=%d available=%s "
            "backend=%s version=%s",
            self._process.pid,
            available,
            response["backend"],
            response["version"],
        )
        return available

    def simplify_mesh(
        self,
        source_vertices,
        source_triangles,
        *,
        target_reduction: float,
    ) -> WorkerSimplificationResult:
        """Simplify one triangle mesh in the persistent geometry worker."""

        total_start = time.perf_counter()
        source = as_vertices(source_vertices, "source_vertices")
        triangles = as_triangles(source_triangles, len(source))
        target_reduction = float(target_reduction)
        if not np.isfinite(target_reduction) or not 0.0 <= target_reduction < 1.0:
            raise ValueError("target_reduction must be finite and in [0, 1)")
        response, payload = self._request(
            {
                "command": "simplify_mesh",
                "point_count": len(source),
                "triangle_count": len(triangles),
                "target_reduction": target_reduction,
            },
            source,
            triangles,
        )
        point_count = int(response["point_count"])
        triangle_count = int(response["triangle_count"])
        vertex_bytes = point_count * 3 * 4
        triangle_bytes = triangle_count * 3 * 4
        if len(payload) != vertex_bytes + triangle_bytes:
            raise NearestSurfaceWorkerError(
                "geometry worker returned an invalid simplification payload"
            )
        output_vertices = np.frombuffer(
            payload,
            dtype=np.float32,
            count=point_count * 3,
        ).reshape((point_count, 3))
        output_triangles = np.frombuffer(
            payload,
            dtype=np.int32,
            count=triangle_count * 3,
            offset=vertex_bytes,
        ).reshape((triangle_count, 3))
        roundtrip_seconds = time.perf_counter() - total_start
        logger.info(
            "Geometry worker mesh simplification: pid=%d backend=%s "
            "version=%s input_vertices=%d input_triangles=%d "
            "target_reduction=%.2f%% output_vertices=%d output_triangles=%d "
            "input_bytes=%d output_bytes=%d simplify=%.3fs worker=%.3fs "
            "roundtrip=%.3fs",
            self._process.pid,
            response["backend"],
            response["version"],
            len(source),
            len(triangles),
            target_reduction * 100.0,
            point_count,
            triangle_count,
            source.nbytes + triangles.nbytes,
            len(payload),
            float(response["simplification_seconds"]),
            float(response["worker_seconds"]),
            roundtrip_seconds,
        )
        return WorkerSimplificationResult(
            vertices=output_vertices,
            triangles=output_triangles,
            backend=str(response["backend"]),
            version=str(response["version"]),
            simplification_seconds=float(response["simplification_seconds"]),
            worker_seconds=float(response["worker_seconds"]),
            roundtrip_seconds=roundtrip_seconds,
        )

    def generate_hollow_surface(
        self,
        source_vertices,
        source_triangles,
        *,
        cavity_inset: float,
        quality: str = "NORMAL",
        max_estimated_voxels: int = 256_000_000,
    ) -> WorkerHollowSurfaceResult:
        """Generate one validated inward OpenVDB surface in the worker."""

        total_start = time.perf_counter()
        source = as_vertices(source_vertices, "source_vertices")
        triangles = as_triangles(source_triangles, len(source))
        cavity_inset = float(cavity_inset)
        quality = str(quality).upper()
        max_estimated_voxels = int(max_estimated_voxels)
        if not np.isfinite(cavity_inset) or cavity_inset <= 0.0:
            raise ValueError("cavity_inset must be finite and greater than zero")
        if quality not in {"DRAFT", "NORMAL", "FINE"}:
            raise ValueError("quality must be DRAFT, NORMAL, or FINE")
        if max_estimated_voxels <= 0:
            raise ValueError("max_estimated_voxels must be greater than zero")

        response, payload = self._request(
            {
                "command": "generate_hollow_surface",
                "point_count": len(source),
                "triangle_count": len(triangles),
                "cavity_inset": cavity_inset,
                "quality": quality,
                "max_estimated_voxels": max_estimated_voxels,
            },
            source,
            triangles,
        )
        point_count = int(response["point_count"])
        triangle_count = int(response["triangle_count"])
        quad_count = int(response["quad_count"])
        vertex_bytes = point_count * 3 * 4
        triangle_bytes = triangle_count * 3 * 4
        quad_bytes = quad_count * 4 * 4
        if len(payload) != vertex_bytes + triangle_bytes + quad_bytes:
            raise NearestSurfaceWorkerError(
                "geometry worker returned an invalid hollow-surface payload"
            )
        vertices = np.frombuffer(
            payload,
            dtype=np.float32,
            count=point_count * 3,
        ).reshape((point_count, 3))
        output_triangles = np.frombuffer(
            payload,
            dtype=np.int32,
            count=triangle_count * 3,
            offset=vertex_bytes,
        ).reshape((triangle_count, 3))
        quads = np.frombuffer(
            payload,
            dtype=np.int32,
            count=quad_count * 4,
            offset=vertex_bytes + triangle_bytes,
        ).reshape((quad_count, 4))
        dimensions = tuple(int(value) for value in response["dimensions"])
        if len(dimensions) != 3:
            raise NearestSurfaceWorkerError(
                "geometry worker returned invalid hollow domain dimensions"
            )
        roundtrip = time.perf_counter() - total_start
        logger.info(
            "Geometry worker hollow surface: pid=%d backend=%s "
            "input_vertices=%d input_triangles=%d inset=%.6g quality=%s "
            "voxel=%.6g requested_voxel=%.6g domain=%sx%sx%s "
            "estimated_voxels=%d half_width=%d isovalue=%.6g reversed=%s "
            "output_vertices=%d output_triangles=%d output_quads=%d "
            "input_bytes=%d output_bytes=%d grid=%.3fs extraction=%.3fs "
            "hollow=%.3fs worker=%.3fs roundtrip=%.3fs",
            self._process.pid,
            response["backend"],
            len(source),
            len(triangles),
            cavity_inset,
            quality,
            float(response["voxel_size"]),
            float(response["requested_voxel_size"]),
            *dimensions,
            int(response["estimated_voxels"]),
            int(response["half_width"]),
            float(response["isovalue"]),
            bool(response["used_reversed_isovalue"]),
            point_count,
            triangle_count,
            quad_count,
            source.nbytes + triangles.nbytes,
            len(payload),
            float(response["grid_seconds"]),
            float(response["extraction_seconds"]),
            float(response["hollow_seconds"]),
            float(response["worker_seconds"]),
            roundtrip,
        )
        return WorkerHollowSurfaceResult(
            vertices=vertices,
            triangles=output_triangles,
            quads=quads,
            voxel_size=float(response["voxel_size"]),
            requested_voxel_size=float(response["requested_voxel_size"]),
            estimated_voxels=int(response["estimated_voxels"]),
            dimensions=dimensions,
            half_width=int(response["half_width"]),
        )

    def generate_hollow_cutter(
        self,
        analysis_vertices,
        analysis_triangles,
        *,
        target_vertices=None,
        target_triangles=None,
        cavity_inset: float,
        quality: str = "NORMAL",
        max_estimated_voxels: int = 256_000_000,
        opening_mode: str = "NONE",
        target_min_z: float | None = None,
        target_max_z: float | None = None,
        top_cut_candidates=(),
        top_cavity_cut_depth_offset: float = 0.25,
        top_overlap_height: float = 1.0,
        top_clearance: float = 5.0,
        bottom_cut_height: float = 1.0,
        source_bottom_cut_height: float = 0.25,
        bottom_clearance: float = 5.0,
    ) -> WorkerHollowCutterResult:
        """Build and return one completed hollow cutter in one request."""

        total_start = time.perf_counter()
        analysis_points = as_vertices(analysis_vertices, "analysis_vertices")
        analysis_faces = as_triangles(
            analysis_triangles,
            len(analysis_points),
        )
        if target_vertices is None and target_triangles is None:
            target_points = np.empty((0, 3), dtype=np.float32)
            target_faces = np.empty((0, 3), dtype=np.int32)
        elif target_vertices is None or target_triangles is None:
            raise ValueError(
                "target_vertices and target_triangles must be supplied together"
            )
        else:
            target_points = as_vertices(target_vertices, "target_vertices")
            target_faces = as_triangles(target_triangles, len(target_points))
        mode = str(opening_mode).upper()
        if mode not in {"NONE", "TOP", "BOTTOM"}:
            raise ValueError("opening_mode must be NONE, TOP, or BOTTOM")

        response, payload = self._request(
            {
                "command": "generate_hollow_cutter",
                "analysis_point_count": len(analysis_points),
                "analysis_triangle_count": len(analysis_faces),
                "target_point_count": len(target_points),
                "target_triangle_count": len(target_faces),
                "cavity_inset": float(cavity_inset),
                "quality": str(quality).upper(),
                "max_estimated_voxels": int(max_estimated_voxels),
                "opening_mode": mode,
                "target_min_z": (
                    None if target_min_z is None else float(target_min_z)
                ),
                "target_max_z": (
                    None if target_max_z is None else float(target_max_z)
                ),
                "top_cut_candidates": [
                    float(value) for value in top_cut_candidates
                ],
                "top_cavity_cut_depth_offset": float(
                    top_cavity_cut_depth_offset
                ),
                "top_overlap_height": float(top_overlap_height),
                "top_clearance": float(top_clearance),
                "bottom_cut_height": float(bottom_cut_height),
                "source_bottom_cut_height": float(source_bottom_cut_height),
                "bottom_clearance": float(bottom_clearance),
            },
            analysis_points,
            analysis_faces,
            target_points,
            target_faces,
        )
        point_count = int(response["point_count"])
        triangle_count = int(response["triangle_count"])
        quad_count = int(response["quad_count"])
        vertex_bytes = point_count * 3 * 4
        triangle_bytes = triangle_count * 3 * 4
        quad_bytes = quad_count * 4 * 4
        if len(payload) != vertex_bytes + triangle_bytes + quad_bytes:
            raise NearestSurfaceWorkerError(
                "geometry worker returned an invalid hollow-cutter payload"
            )
        vertices = np.frombuffer(
            payload,
            dtype=np.float32,
            count=point_count * 3,
        ).reshape((point_count, 3))
        output_triangles = np.frombuffer(
            payload,
            dtype=np.int32,
            count=triangle_count * 3,
            offset=vertex_bytes,
        ).reshape((triangle_count, 3))
        quads = np.frombuffer(
            payload,
            dtype=np.int32,
            count=quad_count * 4,
            offset=vertex_bytes + triangle_bytes,
        ).reshape((quad_count, 4))
        dimensions = tuple(int(value) for value in response["dimensions"])
        if len(dimensions) != 3:
            raise NearestSurfaceWorkerError(
                "geometry worker returned invalid hollow-cutter dimensions"
            )
        roundtrip = time.perf_counter() - total_start
        logger.info(
            "Geometry worker fused hollow cutter: pid=%d backend=%s "
            "opening=%s analysis_vertices=%d analysis_triangles=%d "
            "target_vertices=%d target_triangles=%d inset=%.6g quality=%s "
            "voxel=%.6g output_vertices=%d output_triangles=%d "
            "output_quads=%d cavity_cut_z=%s source_cut_z=%s "
            "cavity_area=%s source_area=%s selected=%s input_bytes=%d "
            "output_bytes=%d grid=%.3fs extraction=%.3fs "
            "construction=%.3fs worker=%.3fs roundtrip=%.3fs",
            self._process.pid,
            response["backend"],
            mode,
            len(analysis_points),
            len(analysis_faces),
            len(target_points),
            len(target_faces),
            float(cavity_inset),
            str(quality).upper(),
            float(response["voxel_size"]),
            point_count,
            triangle_count,
            quad_count,
            response.get("cavity_cut_z"),
            response.get("source_cut_z"),
            response.get("cavity_area"),
            response.get("source_area"),
            response.get("selected_source"),
            analysis_points.nbytes
            + analysis_faces.nbytes
            + target_points.nbytes
            + target_faces.nbytes,
            len(payload),
            float(response["grid_seconds"]),
            float(response["extraction_seconds"]),
            float(response["construction_seconds"]),
            float(response["worker_seconds"]),
            roundtrip,
        )

        def optional_float(name):
            value = response.get(name)
            return None if value is None else float(value)

        return WorkerHollowCutterResult(
            vertices=vertices,
            triangles=output_triangles,
            quads=quads,
            voxel_size=float(response["voxel_size"]),
            requested_voxel_size=float(response["requested_voxel_size"]),
            estimated_voxels=int(response["estimated_voxels"]),
            dimensions=dimensions,
            half_width=int(response["half_width"]),
            opening_mode=str(response["opening_mode"]),
            cavity_cut_z=optional_float("cavity_cut_z"),
            source_cut_z=optional_float("source_cut_z"),
            applied_top_cut=optional_float("applied_top_cut"),
            cavity_area=optional_float("cavity_area"),
            source_area=optional_float("source_area"),
            selected_source=response.get("selected_source"),
            construction_seconds=float(response["construction_seconds"]),
            worker_seconds=float(response["worker_seconds"]),
            roundtrip_seconds=roundtrip,
        )

    def measure_hollow_opening(self, loop_offsets, points) -> float:
        """Measure one planar opening with even-odd fill topology in the worker."""

        total_start = time.perf_counter()
        offsets, vertices = _opening_input(loop_offsets, points)
        response, payload = self._request(
            {
                "command": "measure_hollow_opening",
                "point_count": len(vertices),
                "loop_count": len(offsets) - 1,
            },
            vertices,
            offsets,
        )
        if payload:
            raise NearestSurfaceWorkerError(
                "geometry worker returned an invalid opening-area payload"
            )
        logger.info(
            "Geometry worker hollow opening area: pid=%d loops=%d points=%d "
            "area=%.6g input_bytes=%d worker=%.3fs roundtrip=%.3fs",
            self._process.pid,
            len(offsets) - 1,
            len(vertices),
            float(response["area"]),
            vertices.nbytes + offsets.nbytes,
            float(response["worker_seconds"]),
            time.perf_counter() - total_start,
        )
        return float(response["area"])

    def offset_hollow_opening(
        self,
        loop_offsets,
        points,
        *,
        inset_distance: float,
    ) -> WorkerHollowOpeningResult:
        """Normalize and inset one planar opening in the worker."""

        total_start = time.perf_counter()
        offsets, vertices = _opening_input(loop_offsets, points)
        inset_distance = float(inset_distance)
        if not np.isfinite(inset_distance) or inset_distance <= 0.0:
            raise ValueError("inset_distance must be finite and greater than zero")
        response, payload = self._request(
            {
                "command": "offset_hollow_opening",
                "point_count": len(vertices),
                "loop_count": len(offsets) - 1,
                "inset_distance": inset_distance,
            },
            vertices,
            offsets,
        )
        point_count = int(response["point_count"])
        loop_count = int(response["loop_count"])
        region_count = int(response["region_count"])
        vertex_bytes = point_count * 3 * 4
        loop_offset_bytes = (loop_count + 1) * 4
        region_offset_bytes = (region_count + 1) * 4
        if len(payload) != (
            vertex_bytes + loop_offset_bytes + region_offset_bytes
        ):
            raise NearestSurfaceWorkerError(
                "geometry worker returned an invalid opening-offset payload"
            )
        output_vertices = np.frombuffer(
            payload,
            dtype=np.float32,
            count=point_count * 3,
        ).reshape((point_count, 3))
        output_offsets = np.frombuffer(
            payload,
            dtype=np.int32,
            count=loop_count + 1,
            offset=vertex_bytes,
        )
        region_offsets = np.frombuffer(
            payload,
            dtype=np.int32,
            count=region_count + 1,
            offset=vertex_bytes + loop_offset_bytes,
        )
        logger.info(
            "Geometry worker hollow opening offset: pid=%d inset=%.6g "
            "source_loops=%d source_points=%d result_regions=%d "
            "result_loops=%d result_points=%d input_bytes=%d output_bytes=%d "
            "worker=%.3fs roundtrip=%.3fs",
            self._process.pid,
            inset_distance,
            len(offsets) - 1,
            len(vertices),
            region_count,
            loop_count,
            point_count,
            vertices.nbytes + offsets.nbytes,
            len(payload),
            float(response["worker_seconds"]),
            time.perf_counter() - total_start,
        )
        return WorkerHollowOpeningResult(
            vertices=output_vertices,
            loop_offsets=output_offsets,
            region_offsets=region_offsets,
        )

    def build_simplified_envelope(
        self,
        source_vertices,
        source_triangles,
        *,
        target_reduction: float,
        algorithm: str,
        voxel_size: float,
        distance: float,
        final_wrap_distance: float | None = None,
        cut_top_before_each_wrap: bool = False,
        wrap_count: int,
        build_from_sphere: bool,
        normal_offset: float,
        remesh_scaled: bool,
        sphere_voxel_factor: float,
        sphere_size_factor: float = 1.0,
        sphere_height_factor: float | None = None,
        cut_top_before_wrap: bool,
        smooth_after_wrap: bool,
        cut_bottom_before_wrap: bool = False,
        pre_wrap_cut_offset: float = 1.0,
        finish_top_after_intermediate_remesh: bool = False,
        finish_bottom_after_intermediate_remesh: bool = False,
        remesh_between_wraps: bool = True,
        intermediate_top_clean_voxel_factor: float = 2.0,
        intermediate_top_target_offset: float = 2.0,
    ) -> WorkerSimplifiedEnvelopeResult:
        """Simplify, retain the BVH and build an envelope in one request."""

        total_start = time.perf_counter()
        source = as_vertices(source_vertices, "source_vertices")
        source_faces = as_triangles(source_triangles, len(source))
        target_reduction = float(target_reduction)
        algorithm = str(algorithm).upper()
        if not np.isfinite(target_reduction) or not 0.0 <= target_reduction < 1.0:
            raise ValueError("target_reduction must be finite and in [0, 1)")
        if algorithm not in {"BASE", "OPTIMIZED"}:
            raise ValueError("algorithm must be BASE or OPTIMIZED")
        response, payload = self._request(
            {
                "command": "build_simplified_envelope",
                "point_count": len(source),
                "triangle_count": len(source_faces),
                "target_reduction": target_reduction,
                "algorithm": algorithm,
                "voxel_size": float(voxel_size),
                "distance": float(distance),
                "final_wrap_distance": None if final_wrap_distance is None else float(final_wrap_distance),
                "cut_top_before_each_wrap": bool(cut_top_before_each_wrap),
                "wrap_count": int(wrap_count),
                "build_from_sphere": bool(build_from_sphere),
                "normal_offset": float(normal_offset),
                "remesh_scaled": bool(remesh_scaled),
                "sphere_voxel_factor": float(sphere_voxel_factor),
                "sphere_size_factor": float(sphere_size_factor),
                "sphere_height_factor": float(
                    sphere_size_factor
                    if sphere_height_factor is None
                    else sphere_height_factor
                ),
                "cut_top_before_wrap": bool(cut_top_before_wrap),
                "smooth_after_wrap": bool(smooth_after_wrap),
                "cut_bottom_before_wrap": bool(cut_bottom_before_wrap),
                "pre_wrap_cut_offset": float(pre_wrap_cut_offset),
                "finish_top_after_intermediate_remesh": bool(
                    finish_top_after_intermediate_remesh
                ),
                "finish_bottom_after_intermediate_remesh": bool(
                    finish_bottom_after_intermediate_remesh
                ),
                "remesh_between_wraps": bool(remesh_between_wraps),
                "intermediate_top_clean_voxel_factor": float(
                    intermediate_top_clean_voxel_factor
                ),
                "intermediate_top_target_offset": float(
                    intermediate_top_target_offset
                ),
            },
            source,
            source_faces,
        )
        point_count = int(response["point_count"])
        triangle_count = int(response["triangle_count"])
        quad_count = int(response["quad_count"])
        vertex_bytes = point_count * 3 * 4
        triangle_bytes = triangle_count * 3 * 4
        quad_bytes = quad_count * 4 * 4
        if len(payload) != vertex_bytes + triangle_bytes + quad_bytes:
            raise NearestSurfaceWorkerError(
                "geometry worker returned an invalid simplified-envelope payload"
            )
        vertices = np.frombuffer(
            payload,
            dtype=np.float32,
            count=point_count * 3,
        ).reshape((point_count, 3))
        triangles = np.frombuffer(
            payload,
            dtype=np.int32,
            count=triangle_count * 3,
            offset=vertex_bytes,
        ).reshape((triangle_count, 3))
        quads = np.frombuffer(
            payload,
            dtype=np.int32,
            count=quad_count * 4,
            offset=vertex_bytes + triangle_bytes,
        ).reshape((quad_count, 4))
        self.vertex_count = int(response["target_point_count"])
        self.triangle_count = int(response["target_triangle_count"])
        self.backend = str(response["bvh_backend"])
        self.node_count = int(response["bvh_node_count"])
        if self._require_native and self.backend != "native":
            self.close()
            raise NearestSurfaceWorkerError(
                "native nearest-surface backend is unavailable; run "
                "scripts/build_nearest_surface_native_dev.sh and Reload from Repo"
            )
        roundtrip = time.perf_counter() - total_start
        for pass_timing in response.get("passes", ()):
            logger.info(
                "Worker fused envelope pass: pid=%d algorithm=%s pass=%d/%d "
                "points=%d hits=%d seeded=%d smooth=%.3fs query=%.3fs "
                "offset=%.3fs remesh=%.3fs total=%.3fs",
                self._process.pid,
                algorithm,
                int(pass_timing["pass"]),
                int(wrap_count),
                int(pass_timing["points"]),
                int(pass_timing["hits"]),
                int(pass_timing["seeded"]),
                float(pass_timing["smooth_seconds"]),
                float(pass_timing["query_seconds"]),
                float(pass_timing["offset_seconds"]),
                float(pass_timing["remesh_seconds"]),
                float(pass_timing["total_seconds"]),
            )
        logger.info(
            "Worker fused simplify-envelope: pid=%d algorithm=%s "
            "input_vertices=%d input_triangles=%d target_reduction=%.2f%% "
            "simplified_vertices=%d simplified_triangles=%d "
            "simplify_backend=%s simplify_version=%s simplify=%.3fs "
            "bvh_backend=%s bvh_nodes=%d bvh=%.3fs "
            "output_vertices=%d output_triangles=%d output_quads=%d "
            "pipeline=%.3fs worker=%.3fs input_bytes=%d output_bytes=%d "
            "roundtrip=%.3fs",
            self._process.pid,
            algorithm,
            int(response["input_point_count"]),
            int(response["input_triangle_count"]),
            target_reduction * 100.0,
            self.vertex_count,
            self.triangle_count,
            response["simplification_backend"],
            response["simplification_version"],
            float(response["simplification_seconds"]),
            self.backend,
            self.node_count,
            float(response["bvh_seconds"]),
            point_count,
            triangle_count,
            quad_count,
            float(response["pipeline_seconds"]),
            float(response["worker_seconds"]),
            source.nbytes + source_faces.nbytes,
            len(payload),
            roundtrip,
        )
        return WorkerSimplifiedEnvelopeResult(
            mesh=WorkerMeshResult(vertices, triangles, quads),
            input_vertex_count=int(response["input_point_count"]),
            input_triangle_count=int(response["input_triangle_count"]),
            target_vertex_count=self.vertex_count,
            target_triangle_count=self.triangle_count,
            simplification_seconds=float(response["simplification_seconds"]),
            bvh_seconds=float(response["bvh_seconds"]),
            pipeline_seconds=float(response["pipeline_seconds"]),
            worker_seconds=float(response["worker_seconds"]),
            roundtrip_seconds=roundtrip,
        )

    def build_envelope(
        self,
        *,
        algorithm: str,
        voxel_size: float,
        distance: float,
        final_wrap_distance: float | None = None,
        cut_top_before_each_wrap: bool = False,
        wrap_count: int,
        build_from_sphere: bool,
        normal_offset: float,
        remesh_scaled: bool,
        sphere_voxel_factor: float,
        sphere_size_factor: float = 1.0,
        sphere_height_factor: float | None = None,
        cut_top_before_wrap: bool,
        smooth_after_wrap: bool,
        cut_bottom_before_wrap: bool = False,
        pre_wrap_cut_offset: float = 1.0,
        finish_top_after_intermediate_remesh: bool = False,
        finish_bottom_after_intermediate_remesh: bool = False,
        remesh_between_wraps: bool = True,
        intermediate_top_clean_voxel_factor: float = 2.0,
        intermediate_top_target_offset: float = 2.0,
    ) -> WorkerMeshResult:
        """Build a complete mesh envelope except for its final Blender remesh."""

        total_start = time.perf_counter()
        algorithm = str(algorithm).upper()
        if algorithm not in {"BASE", "OPTIMIZED"}:
            raise ValueError("algorithm must be BASE or OPTIMIZED")
        response, payload = self._request(
            {
                "command": "build_envelope",
                "algorithm": algorithm,
                "voxel_size": float(voxel_size),
                "distance": float(distance),
                "final_wrap_distance": None if final_wrap_distance is None else float(final_wrap_distance),
                "cut_top_before_each_wrap": bool(cut_top_before_each_wrap),
                "wrap_count": int(wrap_count),
                "build_from_sphere": bool(build_from_sphere),
                "normal_offset": float(normal_offset),
                "remesh_scaled": bool(remesh_scaled),
                "sphere_voxel_factor": float(sphere_voxel_factor),
                "sphere_size_factor": float(sphere_size_factor),
                "sphere_height_factor": float(
                    sphere_size_factor
                    if sphere_height_factor is None
                    else sphere_height_factor
                ),
                "cut_top_before_wrap": bool(cut_top_before_wrap),
                "smooth_after_wrap": bool(smooth_after_wrap),
                "cut_bottom_before_wrap": bool(cut_bottom_before_wrap),
                "pre_wrap_cut_offset": float(pre_wrap_cut_offset),
                "finish_top_after_intermediate_remesh": bool(
                    finish_top_after_intermediate_remesh
                ),
                "finish_bottom_after_intermediate_remesh": bool(
                    finish_bottom_after_intermediate_remesh
                ),
                "remesh_between_wraps": bool(remesh_between_wraps),
                "intermediate_top_clean_voxel_factor": float(
                    intermediate_top_clean_voxel_factor
                ),
                "intermediate_top_target_offset": float(
                    intermediate_top_target_offset
                ),
            }
        )
        point_count = int(response["point_count"])
        triangle_count = int(response["triangle_count"])
        quad_count = int(response["quad_count"])
        vertex_bytes = point_count * 3 * 4
        triangle_bytes = triangle_count * 3 * 4
        quad_bytes = quad_count * 4 * 4
        if len(payload) != vertex_bytes + triangle_bytes + quad_bytes:
            raise NearestSurfaceWorkerError(
                "nearest-surface worker returned an invalid envelope payload"
            )
        vertices = np.frombuffer(
            payload,
            dtype=np.float32,
            count=point_count * 3,
        ).reshape((point_count, 3))
        triangles = np.frombuffer(
            payload,
            dtype=np.int32,
            count=triangle_count * 3,
            offset=vertex_bytes,
        ).reshape((triangle_count, 3))
        quads = np.frombuffer(
            payload,
            dtype=np.int32,
            count=quad_count * 4,
            offset=vertex_bytes + triangle_bytes,
        ).reshape((quad_count, 4))
        roundtrip = time.perf_counter() - total_start
        for pass_timing in response.get("passes", ()):
            logger.info(
                "Worker envelope pass: pid=%d algorithm=%s pass=%d/%d "
                "points=%d hits=%d seeded=%d smooth=%.3fs query=%.3fs "
                "offset=%.3fs remesh=%.3fs total=%.3fs",
                self._process.pid,
                algorithm,
                int(pass_timing["pass"]),
                int(wrap_count),
                int(pass_timing["points"]),
                int(pass_timing["hits"]),
                int(pass_timing["seeded"]),
                float(pass_timing["smooth_seconds"]),
                float(pass_timing["query_seconds"]),
                float(pass_timing["offset_seconds"]),
                float(pass_timing["remesh_seconds"]),
                float(pass_timing["total_seconds"]),
            )
        logger.info(
            "Worker envelope request: pid=%d backend=%s algorithm=%s "
            "source=%s target_vertices=%d target_triangles=%d "
            "output_vertices=%d output_triangles=%d output_quads=%d "
            "normal=%.3fs initial_remesh=%.3fs top_cut=%.3fs bottom_cut=%.3fs "
            "intermediate_remesh=%.3fs intermediate_top_finish=%.3fs "
            "intermediate_bottom_finish=%.3fs edges=%.3fs pipeline=%.3fs "
            "worker=%.3fs output_bytes=%d roundtrip=%.3fs",
            self._process.pid,
            self.backend,
            algorithm,
            "sphere" if build_from_sphere else "retained_target",
            self.vertex_count,
            self.triangle_count,
            point_count,
            triangle_count,
            quad_count,
            float(response["normal_offset_seconds"]),
            float(response["initial_remesh_seconds"]),
            float(response["top_cut_seconds"]),
            float(response["bottom_cut_seconds"]),
            float(response["intermediate_remesh_seconds"]),
            float(response["intermediate_top_finish_seconds"]),
            float(response["intermediate_bottom_finish_seconds"]),
            float(response["edge_seconds"]),
            float(response["pipeline_seconds"]),
            float(response["worker_seconds"]),
            len(payload),
            roundtrip,
        )
        return WorkerMeshResult(
            vertices=vertices,
            triangles=triangles,
            quads=quads,
        )

    def edit_mesh_vertices(
        self,
        vertices,
        edges,
        triangles=None,
        *,
        normal_offset: float = 0.0,
        smooth_factor: float = 0.0,
        smooth_repeat: int = 0,
    ) -> np.ndarray:
        """Apply topology-preserving mesh edits without a Blender dependency."""

        total_start = time.perf_counter()
        points = as_vertices(vertices, "vertices")
        links = as_edges(edges, len(points))
        triangle_array = (
            np.empty((0, 3), dtype=np.int32)
            if triangles is None
            else as_triangles(triangles, len(points))
        )
        response, payload = self._request(
            {
                "command": "edit_mesh_vertices",
                "vertex_count": len(points),
                "edge_count": len(links),
                "triangle_count": len(triangle_array),
                "normal_offset": float(normal_offset),
                "smooth_factor": float(smooth_factor),
                "smooth_repeat": int(smooth_repeat),
            },
            points,
            links,
            triangle_array,
        )
        expected_bytes = len(points) * 3 * 4
        if len(payload) != expected_bytes:
            raise NearestSurfaceWorkerError("worker returned invalid mesh-edit data")
        result = np.frombuffer(payload, dtype=np.float32).reshape((-1, 3))
        logger.info(
            "Worker mesh edit: pid=%d vertices=%d edges=%d triangles=%d "
            "normal_offset=%.6f smooth=%d input_bytes=%d worker=%.3fs "
            "roundtrip=%.3fs",
            self._process.pid,
            len(points),
            len(links),
            len(triangle_array),
            float(normal_offset),
            int(smooth_repeat),
            points.nbytes + links.nbytes + triangle_array.nbytes,
            float(response["worker_seconds"]),
            time.perf_counter() - total_start,
        )
        return result

    def repeat_polygon_mesh_grid(
        self,
        vertices,
        face_offsets,
        face_indices,
        *,
        count: int,
        gap: float,
    ) -> WorkerPolygonMeshResult:
        """Return repeated polygon copies packed into a compact two-row grid."""

        points = as_vertices(vertices, "vertices")
        offsets, indices = _polygon_input(
            face_offsets, face_indices, len(points)
        )
        response, payload = self._request(
            {
                "command": "repeat_polygon_mesh_grid",
                "vertex_count": len(points),
                "face_count": len(offsets) - 1,
                "face_value_count": len(indices),
                "count": int(count),
                "gap": float(gap),
            },
            points,
            offsets,
            indices,
        )
        result = _parse_polygon_mesh(response, payload)
        if not isinstance(result, WorkerPolygonMeshResult):
            raise NearestSurfaceWorkerError(
                "geometry worker returned an invalid polygon grid"
            )
        logger.info(
            "Worker polygon grid: pid=%d copies=%d vertices=%d faces=%d "
            "worker=%.3fs",
            self._process.pid,
            int(count),
            len(result.vertices),
            len(result.face_offsets) - 1,
            float(response["worker_seconds"]),
        )
        return result

    def inspect_mesh_connectivity(
        self,
        vertex_count: int,
        edges,
    ) -> WorkerMeshConnectivity:
        total_start = time.perf_counter()
        count = int(vertex_count)
        if count < 0:
            raise ValueError("vertex_count must not be negative")
        links = as_edges(edges, count)
        response, payload = self._request(
            {
                "command": "inspect_mesh_connectivity",
                "vertex_count": count,
                "edge_count": len(links),
            },
            links,
        )
        loose_count = int(response["loose_vertex_count"])
        if len(payload) != loose_count * 4:
            raise NearestSurfaceWorkerError(
                "worker returned invalid mesh connectivity inspection"
            )
        loose_vertices = np.frombuffer(
            payload,
            dtype=np.int32,
            count=loose_count,
        )
        return WorkerMeshConnectivity(
            loose_vertices=loose_vertices,
            multiple_components=bool(response["multiple_components"]),
            worker_seconds=float(response["worker_seconds"]),
            roundtrip_seconds=time.perf_counter() - total_start,
        )

    def analyze_mesh(
        self,
        vertices,
        face_offsets,
        face_indices,
        edges=None,
    ) -> WorkerMeshAnalysis:
        total_start = time.perf_counter()
        points = as_vertices(vertices, "vertices")
        offsets, indices = _polygon_input(face_offsets, face_indices, len(points))
        links = (
            np.empty((0, 2), dtype=np.int32)
            if edges is None
            else as_edges(edges, len(points))
        )
        response, payload = self._request(
            {
                "command": "analyze_mesh",
                "vertex_count": len(points),
                "face_count": len(offsets) - 1,
                "face_value_count": len(indices),
                "edge_count": len(links),
            },
            points,
            offsets,
            indices,
            links,
        )
        face_count = len(offsets) - 1
        boundary_count = int(response["boundary_edge_count"])
        non_manifold_count = int(response["non_manifold_edge_count"])
        loose_count = int(response["loose_vertex_count"])
        expected_bytes = (
            face_count * 4
            + boundary_count * 2 * 4
            + non_manifold_count * 2 * 4
            + loose_count * 4
        )
        if len(payload) != expected_bytes:
            raise NearestSurfaceWorkerError("worker returned invalid mesh analysis")
        offset = 0
        component_ids = np.frombuffer(
            payload, dtype=np.int32, count=face_count, offset=offset
        )
        offset += component_ids.nbytes
        boundary_edges = np.frombuffer(
            payload, dtype=np.int32, count=boundary_count * 2, offset=offset
        ).reshape((-1, 2))
        offset += boundary_edges.nbytes
        non_manifold_edges = np.frombuffer(
            payload,
            dtype=np.int32,
            count=non_manifold_count * 2,
            offset=offset,
        ).reshape((-1, 2))
        offset += non_manifold_edges.nbytes
        loose_vertices = np.frombuffer(
            payload, dtype=np.int32, count=loose_count, offset=offset
        )
        return WorkerMeshAnalysis(
            component_ids=component_ids,
            components=tuple(response["components"]),
            boundary_edges=boundary_edges,
            non_manifold_edges=non_manifold_edges,
            loose_vertices=loose_vertices,
            manifold=bool(response["manifold"]),
            bounds_min=tuple(float(value) for value in response["bounds_min"]),
            bounds_max=tuple(float(value) for value in response["bounds_max"]),
            worker_seconds=float(response["worker_seconds"]),
            roundtrip_seconds=time.perf_counter() - total_start,
        )

    def find_master_air_traps(
        self,
        vertices,
        face_offsets,
        face_indices,
        face_normals,
        face_centers=None,
        mesh_edges=None,
        *,
        base_z: float,
        min_projected_area: float,
        contact_tolerance: float,
        minima_merge_height: float = 0.0,
    ) -> WorkerAirTrapResult:
        total_start = time.perf_counter()
        points = as_vertices(vertices, "vertices")
        offsets, indices = _polygon_input(face_offsets, face_indices, len(points))
        normals = as_vertices(face_normals, "face_normals")
        if len(normals) != len(offsets) - 1:
            raise ValueError("face_normals must match polygons")
        centers = (
            np.empty((0, 3), dtype=np.float32)
            if face_centers is None
            else as_vertices(face_centers, "face_centers")
        )
        if len(centers) not in (0, len(offsets) - 1):
            raise ValueError("face_centers must match polygons")
        edges = (
            np.empty((0, 2), dtype=np.int32)
            if mesh_edges is None
            else as_edges(mesh_edges, len(points))
        )
        response, payload = self._request(
            {
                "command": "find_master_air_traps",
                "vertex_count": len(points),
                "face_count": len(offsets) - 1,
                "face_value_count": len(indices),
                "face_center_count": len(centers),
                "edge_count": len(edges),
                "base_z": float(base_z),
                "min_projected_area": float(min_projected_area),
                "contact_tolerance": float(contact_tolerance),
                "minima_merge_height": float(minima_merge_height),
            },
            points,
            offsets,
            indices,
            normals,
            centers,
            edges,
        )
        count = int(response["island_count"])
        island_face_count = int(response.get("island_face_count", 0))
        expected_bytes = (
            count * 3 * 4
            + count * 4
            + (count + 1) * 4
            + island_face_count * 4
        )
        if len(payload) != expected_bytes:
            raise NearestSurfaceWorkerError("worker returned invalid air-trap data")
        offset = 0
        tips = (
            np.frombuffer(
                payload,
                dtype=np.float32,
                count=count * 3,
                offset=offset,
            )
            .reshape((-1, 3))
        )
        offset += count * 3 * 4
        areas = np.frombuffer(
            payload,
            dtype=np.float32,
            count=count,
            offset=offset,
        )
        offset += count * 4
        face_offsets = np.frombuffer(
            payload,
            dtype=np.int32,
            count=count + 1,
            offset=offset,
        )
        offset += (count + 1) * 4
        face_indices = np.frombuffer(
            payload,
            dtype=np.int32,
            count=island_face_count,
            offset=offset,
        )
        if (
            face_offsets[0] != 0
            or face_offsets[-1] != island_face_count
            or np.any(face_offsets[1:] < face_offsets[:-1])
            or np.any(face_indices < 0)
            or np.any(face_indices >= len(offsets) - 1)
        ):
            raise NearestSurfaceWorkerError(
                "worker returned invalid air-trap face groups"
            )
        return WorkerAirTrapResult(
            tips=tips,
            projected_areas=areas,
            face_offsets=face_offsets,
            face_indices=face_indices,
            supported_base_z=float(response["supported_base_z"]),
            backend=str(response.get("backend", "python")),
            worker_seconds=float(response["worker_seconds"]),
            roundtrip_seconds=time.perf_counter() - total_start,
        )

    def build_extraction_prisms(
        self,
        vertices,
        face_offsets,
        face_indices,
        face_centers,
        face_normals,
        *,
        selection_mode: str,
        face_normal,
        split_plane_normal,
        split_plane_point,
        side: int,
        normal_tolerance: float,
        distance_tolerance: float,
        extra_extrusion_distance: float,
        extrusion_target_point,
    ) -> WorkerPolygonMeshResult:
        points = as_vertices(vertices, "vertices")
        offsets, indices = _polygon_input(face_offsets, face_indices, len(points))
        centers = as_vertices(face_centers, "face_centers")
        normals = as_vertices(face_normals, "face_normals")
        if len(centers) != len(offsets) - 1 or len(normals) != len(centers):
            raise ValueError("face records must match polygons")
        response, payload = self._request(
            {
                "command": "build_extraction_prisms",
                "vertex_count": len(points),
                "face_count": len(offsets) - 1,
                "face_value_count": len(indices),
                "selection_mode": str(selection_mode),
                "face_normal": tuple(float(value) for value in face_normal),
                "split_plane_normal": tuple(float(value) for value in split_plane_normal),
                "split_plane_point": tuple(float(value) for value in split_plane_point),
                "side": int(side),
                "normal_tolerance": float(normal_tolerance),
                "distance_tolerance": float(distance_tolerance),
                "extra_extrusion_distance": float(extra_extrusion_distance),
                "extrusion_target_point": tuple(float(value) for value in extrusion_target_point),
            },
            points,
            offsets,
            indices,
            centers,
            normals,
        )
        result = _parse_polygon_mesh(response, payload)
        if not isinstance(result, WorkerPolygonMeshResult):
            raise NearestSurfaceWorkerError("worker returned invalid extraction prisms")
        return result

    def clear_mesh_faces_to_point(
        self,
        vertices,
        triangles,
        target_point=None,
        *,
        target_points=None,
        voxel_size: float,
        away_from_target: bool = False,
        select_all_faces: bool = False,
        extrusion_distance: float | None = None,
        extrusion_bounds=None,
        extrusion_margin: float = 0.0,
        selection_bounds=None,
        facing_epsilon: float = EPSILON,
        include_source: bool = True,
    ) -> WorkerPointClearanceResult:
        """Horizontally clear faces toward one or their nearest target axis."""

        total_start = time.perf_counter()
        points = as_vertices(vertices, "vertices")
        source_triangles = as_triangles(triangles, len(points))
        if target_points is None:
            if target_point is None:
                raise ValueError("target_point or target_points is required")
            targets = as_vertices([target_point], "target_point")
            target = targets[0]
        else:
            if target_point is not None:
                raise ValueError(
                    "target_point and target_points are mutually exclusive"
                )
            targets = as_vertices(target_points, "target_points")
            if not len(targets):
                raise ValueError("target_points must contain at least one point")
            target = None
        voxel_size = float(voxel_size)
        away_from_target = bool(away_from_target)
        select_all_faces = bool(select_all_faces)
        include_source = bool(include_source)
        if extrusion_distance is not None:
            extrusion_distance = float(extrusion_distance)
            if (
                not np.isfinite(extrusion_distance)
                or extrusion_distance < 0.0
            ):
                raise ValueError(
                    "extrusion_distance must be finite and non-negative"
                )
        bounds = None
        if extrusion_bounds is not None:
            if extrusion_distance is not None:
                raise ValueError(
                    "extrusion_distance and extrusion_bounds are mutually exclusive"
                )
            bounds = np.asarray(extrusion_bounds, dtype=np.float32)
            if bounds.shape != (2, 3) or not np.all(np.isfinite(bounds)):
                raise ValueError("extrusion_bounds must have shape (2, 3)")
            if np.any(bounds[1] < bounds[0]):
                raise ValueError(
                    "extrusion_bounds maximum must not be below minimum"
                )
        extrusion_margin = float(extrusion_margin)
        if not np.isfinite(extrusion_margin) or extrusion_margin < 0.0:
            raise ValueError(
                "extrusion_margin must be finite and non-negative"
            )
        region_bounds = None
        if selection_bounds is not None:
            region_bounds = np.asarray(selection_bounds, dtype=np.float32)
            if region_bounds.shape == (2, 3):
                region_bounds = region_bounds[None, :, :]
            if (
                region_bounds.ndim != 3
                or region_bounds.shape[1:] != (2, 3)
                or not len(region_bounds)
                or not np.all(np.isfinite(region_bounds))
            ):
                raise ValueError(
                    "selection_bounds must have shape (2, 3) or (n, 2, 3)"
                )
            if np.any(region_bounds[:, 1] < region_bounds[:, 0]):
                raise ValueError(
                    "selection_bounds maximum must not be below minimum"
                )
        facing_epsilon = float(facing_epsilon)
        if not np.isfinite(voxel_size) or voxel_size <= 0.0:
            raise ValueError("voxel_size must be finite and greater than zero")
        if not np.isfinite(facing_epsilon) or facing_epsilon < 0.0:
            raise ValueError("facing_epsilon must be finite and non-negative")
        response, payload = self._request(
            {
                "command": "clear_mesh_faces_to_point",
                "point_count": len(points),
                "triangle_count": len(source_triangles),
                "target_point": (
                    None
                    if target is None
                    else tuple(float(value) for value in target)
                ),
                "target_points": (
                    None
                    if target is not None
                    else tuple(
                        tuple(float(value) for value in row)
                        for row in targets
                    )
                ),
                "voxel_size": voxel_size,
                "away_from_target": away_from_target,
                "select_all_faces": select_all_faces,
                "extrusion_distance": extrusion_distance,
                "extrusion_bounds": (
                    None
                    if bounds is None
                    else tuple(
                        tuple(float(value) for value in row)
                        for row in bounds
                    )
                ),
                "extrusion_margin": extrusion_margin,
                "selection_bounds": (
                    None
                    if region_bounds is None
                    else tuple(
                        tuple(
                            tuple(float(value) for value in row)
                            for row in bounds
                        )
                        for bounds in region_bounds
                    )
                ),
                "facing_epsilon": facing_epsilon,
                "include_source": include_source,
            },
            points,
            source_triangles,
        )
        point_count = int(response["point_count"])
        triangle_count = int(response["triangle_count"])
        quad_count = int(response["quad_count"])
        vertex_bytes = point_count * 3 * 4
        triangle_bytes = triangle_count * 3 * 4
        quad_bytes = quad_count * 4 * 4
        if len(payload) != vertex_bytes + triangle_bytes + quad_bytes:
            raise NearestSurfaceWorkerError(
                "geometry worker returned an invalid point-clearance payload"
            )
        output_vertices = np.frombuffer(
            payload,
            dtype=np.float32,
            count=point_count * 3,
        ).reshape((point_count, 3))
        output_triangles = np.frombuffer(
            payload,
            dtype=np.int32,
            count=triangle_count * 3,
            offset=vertex_bytes,
        ).reshape((triangle_count, 3))
        quads = np.frombuffer(
            payload,
            dtype=np.int32,
            count=quad_count * 4,
            offset=vertex_bytes + triangle_bytes,
        ).reshape((quad_count, 4))
        roundtrip_seconds = time.perf_counter() - total_start
        result = WorkerPointClearanceResult(
            mesh=WorkerMeshResult(
                output_vertices,
                output_triangles,
                quads,
            ),
            selected_face_count=int(response["selected_face_count"]),
            component_count=int(response["component_count"]),
            worker_seconds=float(response["worker_seconds"]),
            roundtrip_seconds=roundtrip_seconds,
        )
        logger.info(
            "Worker point clearance: pid=%d input_vertices=%d "
            "input_triangles=%d include_source=%s selected_faces=%d components=%d "
            "output_vertices=%d output_triangles=%d worker=%.3fs "
            "roundtrip=%.3fs",
            self._process.pid,
            len(points),
            len(source_triangles),
            include_source,
            result.selected_face_count,
            result.component_count,
            len(output_vertices),
            len(output_triangles),
            result.worker_seconds,
            result.roundtrip_seconds,
        )
        return result

    def match_points_to_mesh_parts(
        self,
        vertices,
        part_offsets,
        query_points,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Assign distinct vertex ranges to their nearest query points."""

        total_start = time.perf_counter()
        points = as_vertices(vertices, "vertices")
        queries = as_vertices(query_points, "query_points")
        offsets = np.ascontiguousarray(part_offsets, dtype=np.int32)
        if offsets.ndim != 1 or len(offsets) < 2:
            raise ValueError("part_offsets must contain at least two values")
        if int(offsets[0]) != 0 or int(offsets[-1]) != len(points):
            raise ValueError("part_offsets must cover every vertex exactly")
        if np.any(np.diff(offsets) <= 0):
            raise ValueError("every mesh part must contain at least one vertex")
        part_count = len(offsets) - 1
        if len(queries) > part_count:
            raise ValueError("there are fewer mesh parts than query points")
        response, payload = self._request(
            {
                "command": "match_points_to_mesh_parts",
                "vertex_count": len(points),
                "part_count": part_count,
                "query_count": len(queries),
            },
            points,
            offsets,
            queries,
        )
        expected_bytes = len(queries) * 8
        if len(payload) != expected_bytes:
            raise NearestSurfaceWorkerError(
                "geometry worker returned invalid mesh-part assignments"
            )
        part_indices = np.frombuffer(
            payload,
            dtype=np.int32,
            count=len(queries),
        )
        distances = np.frombuffer(
            payload,
            dtype=np.float32,
            count=len(queries),
            offset=len(queries) * 4,
        )
        logger.info(
            "Worker mesh-part matching: pid=%d parts=%d queries=%d "
            "worker=%.3fs roundtrip=%.3fs",
            self._process.pid,
            part_count,
            len(queries),
            float(response["worker_seconds"]),
            time.perf_counter() - total_start,
        )
        return part_indices, distances

    def order_closed_loop(
        self,
        vertices,
        edges,
        *,
        min_z: float | None = None,
    ) -> np.ndarray:
        points = as_vertices(vertices, "vertices")
        links = as_edges(edges, len(points))
        response, payload = self._request(
            {
                "command": "order_closed_loop",
                "vertex_count": len(points),
                "edge_count": len(links),
                "min_z": None if min_z is None else float(min_z),
            },
            points,
            links,
        )
        count = int(response["point_count"])
        if len(payload) != count * 3 * 4:
            raise NearestSurfaceWorkerError("worker returned invalid loop data")
        return np.frombuffer(payload, dtype=np.float32).reshape((-1, 3))

    def resample_closed_loop(
        self,
        vertices,
        edges,
        *,
        spacing: float | None = None,
        point_count: int | None = None,
        min_z: float | None = None,
    ) -> np.ndarray:
        points = as_vertices(vertices, "vertices")
        links = as_edges(edges, len(points))
        response, payload = self._request(
            {
                "command": "resample_closed_loop",
                "vertex_count": len(points),
                "edge_count": len(links),
                "spacing": None if spacing is None else float(spacing),
                "point_count": None if point_count is None else int(point_count),
                "min_z": None if min_z is None else float(min_z),
            },
            points,
            links,
        )
        count = int(response["point_count"])
        if len(payload) != count * 3 * 4:
            raise NearestSurfaceWorkerError("worker returned invalid loop data")
        return np.frombuffer(payload, dtype=np.float32).reshape((-1, 3))

    def extend_funnel_to_plane(
        self,
        vertices,
        face_offsets,
        face_indices,
        face_centers,
        face_normals,
        *,
        object_center,
        plane_point,
        plane_normal,
        tolerance: float,
    ) -> WorkerFunnelExtensionResult:
        total_start = time.perf_counter()
        points = as_vertices(vertices, "vertices")
        offsets, indices = _polygon_input(face_offsets, face_indices, len(points))
        centers = as_vertices(face_centers, "face_centers")
        normals = as_vertices(face_normals, "face_normals")
        response, payload = self._request(
            {
                "command": "extend_funnel_to_plane",
                "vertex_count": len(points),
                "face_count": len(offsets) - 1,
                "face_value_count": len(indices),
                "object_center": tuple(float(value) for value in object_center),
                "plane_point": tuple(float(value) for value in plane_point),
                "plane_normal": tuple(float(value) for value in plane_normal),
                "tolerance": float(tolerance),
            },
            points,
            offsets,
            indices,
            centers,
            normals,
        )
        if len(payload) != len(points) * 3 * 4:
            raise NearestSurfaceWorkerError("worker returned invalid funnel data")
        return WorkerFunnelExtensionResult(
            vertices=np.frombuffer(payload, dtype=np.float32).reshape((-1, 3)),
            selected_face_count=int(response["selected_face_count"]),
            movement_distance=float(response["movement_distance"]),
            worker_seconds=float(response["worker_seconds"]),
            roundtrip_seconds=time.perf_counter() - total_start,
        )

    def plan_limit_face(
        self,
        face_centers,
        face_normals,
        *,
        axis: int,
        max_co: bool,
        flat: bool = False,
        average_ties: bool = False,
        tolerance: float = 1.0e-4,
    ) -> tuple[int, tuple[float, float, float]]:
        centers = as_vertices(face_centers, "face_centers")
        normals = as_vertices(face_normals, "face_normals")
        if len(centers) != len(normals):
            raise ValueError("face records must have equal lengths")
        response, payload = self._request(
            {
                "command": "plan_limit_face",
                "face_count": len(centers),
                "axis": int(axis),
                "max_co": bool(max_co),
                "flat": bool(flat),
                "average_ties": bool(average_ties),
                "tolerance": float(tolerance),
            },
            centers,
            normals,
        )
        if payload:
            raise NearestSurfaceWorkerError("limit-face response has a payload")
        return (
            int(response["face_index"]),
            tuple(float(value) for value in response["center"]),
        )

    def select_limit_flat_faces(
        self,
        face_centers,
        face_normals,
        *,
        max_co: bool,
        tolerance: float,
        z_range: float,
    ) -> np.ndarray:
        centers = as_vertices(face_centers, "face_centers")
        normals = as_vertices(face_normals, "face_normals")
        response, payload = self._request(
            {
                "command": "select_limit_flat_faces",
                "face_count": len(centers),
                "max_co": bool(max_co),
                "tolerance": float(tolerance),
                "z_range": float(z_range),
            },
            centers,
            normals,
        )
        count = int(response["face_count"])
        if len(payload) != count * 4:
            raise NearestSurfaceWorkerError("worker returned invalid face selection")
        return np.frombuffer(payload, dtype=np.int32)

    def analyze_top_surface_flatness(
        self,
        vertices,
        face_offsets,
        face_indices,
        face_centers,
        face_normals,
        *,
        top_band_depth: float,
        flat_normal_z: float,
        min_flat_projected_area_ratio: float,
    ) -> dict:
        points = as_vertices(vertices, "vertices")
        offsets, indices = _polygon_input(
            face_offsets, face_indices, len(points)
        )
        centers = as_vertices(face_centers, "face_centers")
        normals = as_vertices(face_normals, "face_normals")
        if len(centers) != len(offsets) - 1 or len(normals) != len(centers):
            raise ValueError("face records must match polygon topology")
        response, payload = self._request(
            {
                "command": "analyze_top_surface_flatness",
                "vertex_count": len(points),
                "face_count": len(centers),
                "face_value_count": len(indices),
                "top_band_depth": float(top_band_depth),
                "flat_normal_z": float(flat_normal_z),
                "min_flat_projected_area_ratio": float(
                    min_flat_projected_area_ratio
                ),
            },
            points,
            offsets,
            indices,
            centers,
            normals,
        )
        if payload:
            raise NearestSurfaceWorkerError(
                "top-flatness response has a payload"
            )
        return {
            "is_mostly_flat": bool(response["is_mostly_flat"]),
            "flat_projected_area_ratio": float(
                response["flat_projected_area_ratio"]
            ),
            "flat_projected_area": float(response["flat_projected_area"]),
            "total_projected_area": float(response["total_projected_area"]),
            "candidate_face_count": int(response["candidate_face_count"]),
            "flat_face_count": int(response["flat_face_count"]),
            "top_z": float(response["top_z"]),
            "band_min_z": float(response["band_min_z"]),
        }

    def close(self, *, force: bool = False) -> None:
        if getattr(self, "_closed", True):
            return
        if not force and self._process.poll() is None:
            try:
                self._request({"command": "shutdown"})
            except Exception:
                force = True
        self._closed = True
        if force and self._process.poll() is None:
            self._process.terminate()
        try:
            self._process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=2.0)
        for stream in (self._process.stdin, self._process.stdout):
            if stream is not None:
                stream.close()

    def __enter__(self):
        return self

    def __exit__(self, _error_type, _error, _traceback):
        self.close()

    def __del__(self):
        try:
            self.close(force=True)
        except Exception:
            pass
