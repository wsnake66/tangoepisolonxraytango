import bpy  # type: ignore
import logging
import math
import mathutils  # type: ignore
import os
import struct
import tempfile
import time
from pathlib import Path

from ..activity_tracking import write_model_lineage_metadata
from ..export_naming import export_subfolder, friendly_export_name
from ..operator_access import is_lite_tier
from ..mold_types import is_multipart_type
from ..object import Object
from ..slicer_mesh_cleanup import (
    is_generated_box_name,
)
from .box_parts import get_effective_casting_box_type
from .geometry_adapter import clean_export_mesh_with_worker
from .geometry_adapter import begin_clean_export_mesh_with_worker
from .silicone_mold import calculate_silicone_weight


logger = logging.getLogger(__name__)

MASTER_EXPORT_NAME = "patron"
MASTER_SCENE_NAME = "master"
MASTER_BASE_EXPORT_NAME = "master_base"
SILICONE_MOLD_PREVIEW_NAME = "silicone_mold"
TWO_PART_CLEANUP_EXCLUDED_OBJECT_NAMES = frozenset(
    {
        "left_master",
        "right_master",
        "left_silicone_mold",
        "right_silicone_mold",
    }
)
MAX_EXPORT_CLEANUP_PASSES = 2
MAX_EXPORT_CLEANUP_POLYGONS = 1_000_000
NON_EXPORTABLE_OBJECT_NAMES = {"backup"}
INNER_CAVITY_CORE_PREFIX = "inner_cavity_standalone_core_"
INNER_CAVITY_ATTACHER_PREFIX = "attacher_"
INNER_CAVITY_CORE_PIN_PREFIX = "core_pin_"
DIRECT_OPEN_BASE_MOLD_TYPE = "DIRECT_MOLD_OPEN_BASE"
DIRECT_SKIN_MOLD_TYPE = "DIRECT_MOLD_SKIN"
DIRECT_BOX_PART_PREFIX = "box_part_"
SKIN_CORE_NAME = "skin_core"
SKIN_CORE_ATTACHER_PREFIX = "skin_core_attacher"
SKIN_CORE_PIN_NAME = "skin_core_pin"
CASTING_BOX_PREFIX = "casting_box"
OPTIMIZED_CASTING_BOX_TYPE = "OPTIMIZED"
TOP_CASTING_BOX_INTERSECTION = "TOP"


def inner_cavity_export_y_rotation(scene, object_name: str) -> float:
    """Return the temporary Y rotation used for inner-cavity print exports."""

    if not bool(getattr(scene, "pro_inner_cavity", False)):
        return 0.0

    normalized_name = str(object_name).lower()
    if normalized_name.startswith(INNER_CAVITY_CORE_PIN_PREFIX):
        return math.radians(45.0)

    core_type = str(
        getattr(scene, "pro_inner_cavity_core_type", "SINGLE_PART")
    )
    if core_type == "MULTI_PART":
        if normalized_name.startswith(INNER_CAVITY_CORE_PREFIX):
            return math.radians(180.0)
        return 0.0

    if normalized_name.startswith(INNER_CAVITY_ATTACHER_PREFIX):
        return math.radians(180.0)
    return 0.0


def direct_mold_export_y_rotation(scene, object_name: str) -> float:
    """Return temporary print orientation for Open Base and Skin exports."""

    mold_type = str(getattr(scene, "mold_type_preview", ""))
    if mold_type not in {DIRECT_OPEN_BASE_MOLD_TYPE, DIRECT_SKIN_MOLD_TYPE}:
        return 0.0

    normalized_name = str(object_name).lower()
    if normalized_name == "box" or normalized_name.startswith(
        DIRECT_BOX_PART_PREFIX
    ):
        return math.radians(180.0)

    if mold_type != DIRECT_SKIN_MOLD_TYPE:
        return 0.0

    core_type = str(getattr(scene, "direct_skin_core_type", "MULTI_PART"))
    if core_type == "MULTI_PART":
        if normalized_name.startswith(SKIN_CORE_ATTACHER_PREFIX):
            return math.radians(180.0)
        if normalized_name == SKIN_CORE_PIN_NAME:
            return math.radians(45.0)
        return 0.0

    if normalized_name == SKIN_CORE_NAME:
        return math.radians(180.0)
    return 0.0


def casting_box_export_y_rotation(scene, object_name: str) -> float:
    """Turn top-ring casting boxes over for print-ready exports."""

    if get_effective_casting_box_type(scene) != OPTIMIZED_CASTING_BOX_TYPE:
        return 0.0
    if (
        str(
            getattr(
                scene,
                "optimized_casting_box_horizontal_intersection",
                TOP_CASTING_BOX_INTERSECTION,
            )
        )
        != TOP_CASTING_BOX_INTERSECTION
    ):
        return 0.0
    if not str(object_name).lower().startswith(CASTING_BOX_PREFIX):
        return 0.0
    return math.radians(180.0)


def object_export_y_rotation(scene, object_name: str) -> float:
    """Resolve the temporary print orientation for one exported object."""

    for resolver in (
        inner_cavity_export_y_rotation,
        direct_mold_export_y_rotation,
        casting_box_export_y_rotation,
    ):
        rotation_y = resolver(scene, object_name)
        if rotation_y:
            return rotation_y
    return 0.0


def apply_temporary_export_y_rotation(obj, rotation_y: float):
    """Rotate an object around its world-space geometry center for export."""

    original_matrix = obj.matrix_world.copy()
    center = Object(obj).center_coords.copy()
    rotation = (
        mathutils.Matrix.Translation(center)
        @ mathutils.Matrix.Rotation(rotation_y, 4, "Y")
        @ mathutils.Matrix.Translation(-center)
    )
    obj.matrix_world = rotation @ original_matrix
    bpy.context.view_layer.update()
    return original_matrix


def _export_directory_path(path: str) -> Path:
    dir_path = Path(bpy.path.abspath(path))
    # Blender's file browser can prefill the current .blend filename.
    # Users can also type a filename like "export.stl" in the folder picker.
    # Export expects a directory, so map file-like paths to their parent folder.
    if dir_path.exists():
        if not dir_path.is_dir():
            dir_path = dir_path.parent
    elif dir_path.suffix:
        dir_path = dir_path.parent
    return dir_path


def _export_object_name(obj) -> str:
    system = obj.get("moldboxer_plaster_silicone_system")
    if system:
        component = obj.get("moldboxer_plaster_silicone_component", obj.name)
        return f"{system}_{friendly_export_name(component)}"
    return friendly_export_name(obj.name)


def _export_glb_like_stl(export_path: str, source_obj):
    context = bpy.context
    depsgraph = context.evaluated_depsgraph_get()
    evaluated_obj = source_obj.evaluated_get(depsgraph)
    mesh = evaluated_obj.to_mesh()
    temp_mesh = None
    temp_obj = None
    original_active = context.view_layer.objects.active
    original_selection = list(context.selected_objects)

    try:
        temp_mesh = mesh.copy()
        temp_mesh.transform(source_obj.matrix_world)
        temp_mesh.update()
        if not temp_mesh.materials:
            for material in getattr(source_obj.data, "materials", ()):
                temp_mesh.materials.append(material)

        temp_obj = bpy.data.objects.new(source_obj.name, temp_mesh)
        context.collection.objects.link(temp_obj)
        temp_obj.matrix_world.identity()
        temp_obj.parent = None

        for obj in list(context.selected_objects):
            obj.select_set(False)
        temp_obj.select_set(True)
        context.view_layer.objects.active = temp_obj

        kwargs = {
            "filepath": export_path,
            "export_format": "GLB",
            "use_selection": True,
            # Match Blender's STL import/export basis after a GLB roundtrip.
            "export_yup": True,
        }
        try:
            bpy.ops.export_scene.gltf(**kwargs, export_materials="EXPORT")
        except TypeError:
            bpy.ops.export_scene.gltf(**kwargs)
    finally:
        evaluated_obj.to_mesh_clear()
        if temp_obj is not None:
            bpy.data.objects.remove(temp_obj, do_unlink=True)
        if temp_mesh is not None:
            bpy.data.meshes.remove(temp_mesh)
        for obj in list(context.selected_objects):
            obj.select_set(False)
        for obj in original_selection:
            if obj.name in bpy.data.objects:
                obj.select_set(True)
        if original_active is not None and original_active.name in bpy.data.objects:
            context.view_layer.objects.active = original_active


def _export_cleanup_is_excluded(source_obj) -> bool:
    saved_exclusion = source_obj.get("moldboxer_source_export_cleanup_excluded")
    if saved_exclusion is not None:
        return bool(saved_exclusion)
    normalized_name = str(source_obj.get(
        "moldboxer_plaster_silicone_component", source_obj.name
    )).casefold()
    if normalized_name == "plaster_mold" or normalized_name.startswith(
        ("plaster_mold_part_", "plaster_mold.", "silicone_mold_part_")
    ):
        return True
    if normalized_name == MASTER_BASE_EXPORT_NAME:
        # With an unfixed master the base is an independent printable part.
        # It must receive the same conservative export cleanup as other parts;
        # exact duplicate facets otherwise survive as four-user edges. Keep
        # the historical exclusion for a fixed master, where the base belongs
        # to the joined master system.
        if is_multipart_type(getattr(bpy.context.scene, "mold_type_preview", "")):
            return True
        return bool(getattr(bpy.context.scene, "wing_join_patron", True))
    return normalized_name in {
        MASTER_EXPORT_NAME,
        MASTER_SCENE_NAME,
        SILICONE_MOLD_PREVIEW_NAME,
    } or normalized_name in TWO_PART_CLEANUP_EXCLUDED_OBJECT_NAMES


def _export_cleanup_skip_reason(source_obj) -> str | None:
    if _export_cleanup_is_excluded(source_obj):
        return "excluded"
    if len(source_obj.data.polygons) > MAX_EXPORT_CLEANUP_POLYGONS:
        return "polygon_limit"
    return None


def _log_export_cleanup_skip(source_obj, reason: str) -> None:
    polygon_count = len(source_obj.data.polygons)
    if reason == "polygon_limit":
        logger.info(
            "STL cleanup skipped for %s: reason=polygon_limit polygons=%d "
            "limit=%d elapsed=0.000s",
            source_obj.name,
            polygon_count,
            MAX_EXPORT_CLEANUP_POLYGONS,
        )
        return
    logger.info(
        "STL cleanup skipped for %s: reason=%s polygons=%d elapsed=0.000s",
        source_obj.name,
        reason,
        polygon_count,
    )


def _log_export_cleanup_result(source_obj, result, cleanup_start: float) -> None:
    generated_box = is_generated_box_name(source_obj.name)
    cleanup_mode = "adaptive" if generated_box else "standard"
    initial = result.initial
    logger.info(
        "Worker STL cleanup preflight for %s: required=%s reason=%s "
        "vertices=%d edges=%d faces=%d elapsed=%.3fs",
        source_obj.name,
        bool(initial["cleanup_required"]),
        initial["reason"],
        int(initial["vertex_count"]),
        int(initial["edge_count"]),
        int(initial["face_count"]),
        result.preflight_seconds,
    )
    if not initial["cleanup_required"]:
        logger.info(
            "Worker STL cleanup for %s: skipped=already_clean "
            "preflight=%.3fs pipeline=%.3fs roundtrip=%.3fs",
            source_obj.name,
            result.preflight_seconds,
            result.pipeline_seconds,
            result.roundtrip_seconds,
        )
        return

    for cleanup_pass in result.passes:
        phase_seconds = cleanup_pass.get("phase_seconds", {})
        phase_summary = ",".join(
            f"{name}={float(seconds):.3f}s"
            for name, seconds in phase_seconds.items()
        )
        phase_details = cleanup_pass.get("phase_details", {})
        detail_summary = ";".join(
            f"{name}["
            + ",".join(
                f"{metric}={int(value)}"
                for metric, value in details.items()
            )
            + "]"
            for name, details in phase_details.items()
        )
        logger.info(
            "Worker STL cleanup for %s: mode=%s pass=%d "
            "input_vertices=%d input_faces=%d output_vertices=%d "
            "output_faces=%d changed=%s start_reason=%s reason=%s elapsed=%.3fs "
            "overhead=%.3fs phases=%s details=%s",
            source_obj.name,
            cleanup_mode,
            int(cleanup_pass["pass"]),
            int(cleanup_pass["input_vertices"]),
            int(cleanup_pass["input_faces"]),
            int(cleanup_pass["output_vertices"]),
            int(cleanup_pass["output_faces"]),
            bool(cleanup_pass.get("changed", True)),
            cleanup_pass.get("start_reason", initial["reason"]),
            cleanup_pass["reason"],
            float(cleanup_pass.get("seconds", 0.0)),
            float(cleanup_pass.get("overhead_seconds", 0.0)),
            phase_summary or "none",
            detail_summary or "none",
        )
    final = result.final
    logger.info(
        "Worker STL cleanup complete for %s: mode=%s changed=%s "
        "passes=%d required=%s reason=%s facets=%d preflight=%.3fs "
        "pipeline=%.3fs worker=%.3fs roundtrip=%.3fs total=%.3fs",
        source_obj.name,
        cleanup_mode,
        result.changed,
        len(result.passes),
        bool(final["cleanup_required"]),
        final["reason"],
        int(final["face_count"]),
        result.preflight_seconds,
        result.pipeline_seconds,
        result.worker_seconds,
        result.roundtrip_seconds,
        time.perf_counter() - cleanup_start,
    )
    if final["cleanup_required"]:
        logger.warning(
            "STL cleanup for %s still requires repair after %d "
            "passes: reason=%s",
            source_obj.name,
            len(result.passes),
            final["reason"],
        )


def _write_selected_stl(export_path: str, source_obj) -> None:
    write_start = time.perf_counter()
    context = bpy.context
    original_selection = list(context.selected_objects)
    original_active = context.view_layer.objects.active
    was_hidden = source_obj.hide_get()
    was_hide_viewport = source_obj.hide_viewport
    was_hide_select = source_obj.hide_select
    temporary_path = None
    try:
        # Modal redraw temporarily hides construction objects, clearing their
        # selection even after visibility is restored. Bind the native export
        # to this object after cleanup, at the point of writing.
        source_obj.hide_viewport = False
        source_obj.hide_select = False
        source_obj.hide_set(False)
        context.view_layer.update()
        for obj in context.view_layer.objects:
            obj.select_set(False)
        source_obj.select_set(True)
        context.view_layer.objects.active = source_obj
        if not source_obj.select_get() or not source_obj.visible_get():
            raise RuntimeError(f"Cannot select visible STL export target: {source_obj.name}")

        destination = Path(export_path)
        with tempfile.NamedTemporaryFile(
            dir=destination.parent, prefix=f".{destination.stem}-", suffix=".stl",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        result = bpy.ops.wm.stl_export(
            filepath=str(temporary_path),
            export_selected_objects=True,
            ascii_format=False,
        )
        if result != {"FINISHED"}:
            raise RuntimeError(f"STL export failed for {source_obj.name}: {result}")
        byte_count = temporary_path.stat().st_size
        with temporary_path.open("rb") as exported:
            header = exported.read(84)
        triangle_count = struct.unpack_from("<I", header, 80)[0] if len(header) == 84 else 0
        if triangle_count == 0 or byte_count != 84 + 50 * triangle_count:
            raise RuntimeError(
                f"STL export for {source_obj.name} produced an empty or invalid file "
                f"({triangle_count} triangles, {byte_count} bytes)"
            )
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        for obj in context.view_layer.objects:
            obj.select_set(False)
        source_obj.hide_set(was_hidden)
        source_obj.hide_viewport = was_hide_viewport
        source_obj.hide_select = was_hide_select
        for obj in original_selection:
            obj.select_set(True)
        context.view_layer.objects.active = original_active
    logger.info(
        "STL file write for %s: triangles=%d bytes=%d elapsed=%.3fs path=%s",
        source_obj.name,
        triangle_count,
        byte_count,
        time.perf_counter() - write_start,
        export_path,
    )


class BackgroundSlicerCleanSTL:
    def __init__(self, export_path: str, source_obj) -> None:
        self._export_path = export_path
        self._source_obj = source_obj
        self._cleanup_start = time.perf_counter()
        self._cleanup_task = None
        self._finished = False

        skip_reason = _export_cleanup_skip_reason(source_obj)
        if skip_reason is not None:
            _log_export_cleanup_skip(source_obj, skip_reason)
        else:
            generated_box = is_generated_box_name(source_obj.name)
            self._cleanup_task = begin_clean_export_mesh_with_worker(
                source_obj,
                generated_box=generated_box,
                max_passes=MAX_EXPORT_CLEANUP_PASSES,
            )

    def done(self) -> bool:
        return self._cleanup_task is None or self._cleanup_task.done()

    def finish(self) -> None:
        if self._finished:
            return
        if self._cleanup_task is not None:
            result = self._cleanup_task.finish()
            _log_export_cleanup_result(
                self._source_obj,
                result,
                self._cleanup_start,
            )
        _write_selected_stl(self._export_path, self._source_obj)
        self._finished = True


def begin_export_slicer_clean_stl(
    export_path: str,
    source_obj,
) -> BackgroundSlicerCleanSTL:
    return BackgroundSlicerCleanSTL(export_path, source_obj)


def export_slicer_clean_stl(export_path: str, source_obj) -> None:
    """Clean the real scene mesh in place, then export that object."""

    skip_reason = _export_cleanup_skip_reason(source_obj)
    if skip_reason is not None:
        _log_export_cleanup_skip(source_obj, skip_reason)
    else:
        cleanup_start = time.perf_counter()
        generated_box = is_generated_box_name(source_obj.name)
        result = clean_export_mesh_with_worker(
            source_obj,
            generated_box=generated_box,
            max_passes=MAX_EXPORT_CLEANUP_PASSES,
        )
        _log_export_cleanup_result(source_obj, result, cleanup_start)

    _write_selected_stl(export_path, source_obj)


def _export_selected_object(export_path: str, file_format: str, obj):
    if file_format == "STL":
        export_slicer_clean_stl(export_path, obj)
        return

    if file_format == "GLB":
        _export_glb_like_stl(export_path, obj)
        return

    raise ValueError(f"Unsupported export format: {file_format}")


def _is_exportable_object(obj) -> bool:
    component_name = obj.get("moldboxer_plaster_silicone_component", obj.name)
    normalized_name = str(component_name).casefold()
    return bool(
        obj.type == "MESH"
        and not obj.get("moldboxer_slip_casting_restart_master", False)
        and component_name not in NON_EXPORTABLE_OBJECT_NAMES
        and not normalized_name.startswith("base_barrier_female")
        and normalized_name != "female_base"
        and not normalized_name.startswith(("female_base_", "female_base."))
        and ("funnel" not in normalized_name or obj.get("moldboxer_rounded_funnel_mold", False))
        and not normalized_name.startswith("temp_")
    )


def _object_export_path(dir_path: Path, file_format: str, obj, lite_tier: bool) -> str:
    component_name = obj.get("moldboxer_plaster_silicone_component", obj.name)
    dir_path = dir_path / export_subfolder(component_name)
    extension = file_format.lower()
    export_name = _export_object_name(obj)
    if "patron" in obj.name or obj.name == "master":
        bl_obj = Object(obj)
        bl_obj.apply_all_transforms()
        if lite_tier:
            return str(dir_path / f"{export_name}.{extension}")
        return str(dir_path / f"{export_name}_{bl_obj.volume:.0f}ml.{extension}")
    if "silicone" in obj.name:
        bl_obj = Object(obj)
        bl_obj.apply_all_transforms()
        if lite_tier:
            return str(dir_path / f"{export_name}.{extension}")
        density = getattr(bpy.context.scene, "silicone_density", 1.12)
        weight = calculate_silicone_weight(bl_obj.volume, density)
        return str(dir_path / f"{export_name}_{weight:.0f}g.{extension}")
    return str(dir_path / f"{export_name}.{extension}")


class BackgroundExportSession:
    """Advance one Blender export at a time while worker cleanup stays async."""

    def __init__(self, dir: str, file_format: str = "STL") -> None:
        self._dir_path = _export_directory_path(dir)
        self._dir_path.mkdir(parents=True, exist_ok=True)
        for folder in ("print", "reference"):
            (self._dir_path / folder).mkdir(exist_ok=True)
        self._file_format = file_format.upper()
        self._lite_tier = is_lite_tier()
        self._objects = [obj for obj in bpy.data.objects if _is_exportable_object(obj)]
        self._object_index = 0
        self._pending_stl_task = None
        self._pending_object_state = None
        self._exported_object_count = 0
        self._lineage_records = []
        self._failed_objects = []
        self._skipped_objects = []
        self._finished = False
        for obj in bpy.data.objects:
            obj.select_set(False)

    @property
    def summary(self) -> dict:
        return {
            "exported_object_count": self._exported_object_count,
            "lineage_records": list(self._lineage_records),
            "failed_objects": list(self._failed_objects),
            "skipped_objects": list(self._skipped_objects),
        }

    def _prepare_object(self, obj):
        state = {
            "obj": obj,
            "was_hidden": obj.hide_get(),
            "was_hide_viewport": bool(obj.hide_viewport),
            "was_hide_render": bool(obj.hide_render),
            "original_matrix": None,
            "export_path": _object_export_path(
                self._dir_path,
                self._file_format,
                obj,
                self._lite_tier,
            ),
        }
        try:
            obj.hide_set(False)
            obj.hide_viewport = False
            obj.hide_render = False
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            export_rotation_y = obj.get(
                "moldboxer_source_export_y_rotation",
                object_export_y_rotation(bpy.context.scene, obj.name),
            )
            if export_rotation_y:
                state["original_matrix"] = apply_temporary_export_y_rotation(
                    obj,
                    export_rotation_y,
                )
        except Exception:
            self._finalize_object(state, exported=False)
            raise
        return state

    def _finalize_object(self, state, *, exported: bool) -> None:
        obj = state["obj"]
        original_matrix = state["original_matrix"]
        if original_matrix is not None:
            obj.matrix_world = original_matrix
            bpy.context.view_layer.update()
        obj.hide_set(state["was_hidden"])
        obj.hide_viewport = state["was_hide_viewport"]
        obj.hide_render = state["was_hide_render"]
        if exported:
            self._exported_object_count += 1
            if obj.name in {"patron", "master"}:
                lineage_record = write_model_lineage_metadata(
                    state["export_path"],
                    obj,
                )
                if lineage_record is not None:
                    self._lineage_records.append(lineage_record)
        obj.select_set(False)

    def _record_failure(self, obj, exc) -> None:
        self._failed_objects.append({"name": obj.name, "error": str(exc)})
        logger.exception("Export failed for %s; continuing with remaining objects", obj.name)

    def done(self) -> bool:
        if self._finished:
            return True

        if self._pending_stl_task is not None:
            state = self._pending_object_state
            exported = False
            completed = False
            try:
                if not self._pending_stl_task.done():
                    return False
                completed = True
                self._pending_stl_task.finish()
                exported = True
            except Exception as exc:
                completed = True
                self._record_failure(state["obj"], exc)
            finally:
                # Keep the state while the asynchronous cleanup is still running.
                if completed:
                    self._pending_stl_task = None
                    self._pending_object_state = None
                    self._finalize_object(state, exported=exported)
            return False

        if self._object_index >= len(self._objects):
            self._finished = True
            return True

        obj = self._objects[self._object_index]
        self._object_index += 1
        # Modifiers can generate faces from an empty source mesh.
        if not len(obj.data.polygons) and not len(obj.modifiers):
            self._skipped_objects.append({"name": obj.name, "reason": "empty mesh"})
            logger.warning("Skipping empty export object %s", obj.name)
            return False
        state = None
        exported = False
        try:
            state = self._prepare_object(obj)
            if self._file_format == "STL":
                self._pending_stl_task = begin_export_slicer_clean_stl(
                    state["export_path"], obj,
                )
                self._pending_object_state = state
                return False
            _export_selected_object(state["export_path"], self._file_format, obj)
            exported = True
        except Exception as exc:
            self._record_failure(obj, exc)
        finally:
            if state is not None and self._pending_stl_task is None:
                self._finalize_object(state, exported=exported)
        return False

    def finish(self) -> dict:
        if not self._finished:
            raise RuntimeError("Background export finished before all parts completed")
        return self.summary


def begin_export(dir: str, file_format: str = "STL") -> BackgroundExportSession:
    return BackgroundExportSession(dir, file_format=file_format)


def export(dir: str, file_format: str = "STL"):
    session = begin_export(dir, file_format=file_format)
    while not session.done():
        time.sleep(0.01)
    return session.finish()
