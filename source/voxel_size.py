import bpy  # type: ignore
import json
import logging
from functools import lru_cache
from typing import Mapping, Optional, Union

from .object import Object

logger = logging.getLogger(__name__)

# Public reference values retained for logging and API compatibility. The
# selection/scaling policy itself is evaluated by the commercial worker.
REFERENCE_MAX_DIMENSION = 150.0
MIN_BOX_VOXEL_SIZE = 0.5
MIN_MASTER_VOXEL_SIZE = 0.025
MIN_UNDERCUTS_VOXEL_SIZE = 0.1
BOX_BOOLEAN_RETRY_REFERENCE_OFFSET = 1.0
# Above the 150 mm reference, scale box voxels by 1.5x whenever the patron's
# longest dimension doubles.
BOX_DIMENSION_SCALE_EXPONENT = 0.5849625007211562


def _worker_policy(operation: str, **arguments) -> dict:
    serialized_arguments = json.dumps(
        arguments, sort_keys=True, separators=(",", ":")
    )
    return _cached_worker_policy(operation, serialized_arguments)


@lru_cache(maxsize=128)
def _cached_worker_policy(operation: str, serialized_arguments: str) -> dict:
    from .components.geometry_adapter import acquire_geometry_worker

    return acquire_geometry_worker().geometry_policy(
        operation, **json.loads(serialized_arguments)
    )


def _worker_voxel_size(
    kind: str,
    quality: str,
    candidate: Optional[Union[Object, bpy.types.Object]],
) -> float:
    result = _worker_policy(
        "adaptive_voxel_size",
        kind=kind,
        quality=quality,
        max_dimension=get_object_max_dimension(candidate),
    )
    logger.debug(
        "Worker adaptive voxel size: kind=%s quality=%s max_dimension=%s "
        "reference_max_dimension=%.3f base_voxel_size=%.6f "
        "large_dimension_scale_exponent=%.6f raw=%.6f voxel_size=%.6f",
        kind,
        quality,
        result["max_dimension"],
        result["reference_max_dimension"],
        result["base_value"],
        result["large_dimension_scale_exponent"],
        result["raw_value"],
        result["value"],
    )
    return float(result["value"])


def _as_object(candidate: Optional[Union[Object, bpy.types.Object]]) -> Optional[Object]:
    if candidate is None:
        return None
    if isinstance(candidate, Object):
        return candidate
    return Object(candidate)


def get_patron_for_voxel_size(
    candidate: Optional[Union[Object, bpy.types.Object]] = None,
) -> Optional[Object]:
    candidate_object = _as_object(candidate)
    if candidate_object is not None:
        return candidate_object
    patron = bpy.data.objects.get("patron")
    if patron is not None:
        return Object(patron)
    return _as_object(bpy.context.active_object)


def get_object_max_dimension(
    candidate: Optional[Union[Object, bpy.types.Object]] = None,
) -> Optional[float]:
    obj = get_patron_for_voxel_size(candidate)
    if obj is None:
        return None
    max_dimension = max(obj.width, obj.depth, obj.height)
    if max_dimension <= 0:
        return None
    return max_dimension


def get_adaptive_voxel_size(
    quality: str,
    quality_map: Mapping[str, float],
    candidate: Optional[Union[Object, bpy.types.Object]] = None,
    large_dimension_scale_exponent: float = 1.0,
) -> float:
    result = _worker_policy(
        "adaptive_voxel_custom",
        base_value=float(quality_map[quality]),
        max_dimension=get_object_max_dimension(candidate),
        large_dimension_scale_exponent=float(large_dimension_scale_exponent),
    )
    return float(result["value"])


def get_adaptive_voxel_size_from_reference(
    reference_voxel_size: float,
    candidate: Optional[Union[Object, bpy.types.Object]] = None,
) -> float:
    result = _worker_policy(
        "adaptive_voxel_from_reference",
        reference_value=float(reference_voxel_size),
        max_dimension=get_object_max_dimension(candidate),
    )
    return float(result["value"])


def get_master_voxel_size(
    quality: str,
    candidate: Optional[Union[Object, bpy.types.Object]] = None,
) -> float:
    return _worker_voxel_size("master", quality, candidate)


def get_box_voxel_size(
    quality: str,
    candidate: Optional[Union[Object, bpy.types.Object]] = None,
) -> float:
    return _worker_voxel_size("box", quality, candidate)


def get_undercuts_voxel_size(
    quality: str,
    candidate: Optional[Union[Object, bpy.types.Object]] = None,
) -> float:
    return _worker_voxel_size("undercuts", quality, candidate)


def get_box_boolean_retry_voxel_size(
    quality: str,
    candidate: Optional[Union[Object, bpy.types.Object]] = None,
) -> float:
    return _worker_voxel_size("box_boolean_retry", quality, candidate)


def get_filler_voxel_size(
    quality: str,
    candidate: Optional[Union[Object, bpy.types.Object]] = None,
) -> float:
    return _worker_voxel_size("filler", quality, candidate)


def get_filler_voxel_size_reference(quality: str) -> float:
    result = _worker_policy(
        "adaptive_voxel_size",
        kind="filler",
        quality=quality,
        max_dimension=None,
    )
    return float(result["base_value"])
