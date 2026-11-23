from __future__ import annotations
import bpy  # type: ignore
from pathlib import Path
import bmesh  # type: ignore
import mathutils  # type: ignore
import logging
import time
from contextlib import contextmanager
from typing import Literal, Optional

from .modifiers import *
from .bl_utils import *
from .primitives import *
from .materials import prepare_material_transfer
from .progress import breathe_viewport, _hidden_during_redraw
from .slicer_mesh_cleanup import clean_mesh_for_manifold_boolean
from .boolean_safety import boolean_inputs_are_empty, safe_boolean_properties

logger = logging.getLogger(__name__)

UI_BREATHE_MODIFIERS = {"BOOLEAN", "REMESH", "SHRINKWRAP"}
DIRECT_BOOLEAN_RETRY_SCENE_KEY = "_moldboxer_direct_boolean_retry"
SPLIT_PLANE_CUT_THICKNESS = 0.01
SPLIT_PLANE_CUT_HALF_THICKNESS = SPLIT_PLANE_CUT_THICKNESS / 2.0
_SUPPRESS_UI_BREATHE_DEPTH = 0


def remove_unused_meshes(meshes) -> int:
    """Release only supplied local meshes that no Blender datablock still uses.

    Never sweep all orphan data during an operation: other code may be holding
    an unlinked mesh as a rollback copy. Invalidated references are harmless.
    """
    removed = 0
    for mesh in meshes:
        try:
            if (
                isinstance(mesh, bpy.types.Mesh)
                and mesh.users == 0
                and not mesh.use_fake_user
                and mesh.library is None
                and bpy.data.meshes.get(mesh.name) == mesh
            ):
                bpy.data.meshes.remove(mesh)
                removed += 1
        except ReferenceError:
            pass
    return removed


def remove_objects_safely(objects) -> None:
    """Remove live objects without leaving UI context references between deletes.

    Moldboxer performs many object replacements from timer-driven modal operators.
    Releasing active/selection references first and deleting a group in one Blender
    batch prevents dependency-graph redraws from observing an object part-way
    through teardown.
    """

    live_objects = []
    seen_pointers = set()
    for obj in objects:
        if obj is None:
            continue
        try:
            pointer = obj.as_pointer()
            current = bpy.data.objects.get(obj.name)
            if (
                not pointer
                or pointer in seen_pointers
                or current is None
                or current.as_pointer() != pointer
            ):
                continue
        except (AttributeError, ReferenceError, RuntimeError):
            continue
        seen_pointers.add(pointer)
        live_objects.append(obj)

    if not live_objects:
        return

    live_pointers = seen_pointers
    view_layer = getattr(bpy.context, "view_layer", None)
    if view_layer is not None:
        try:
            active = view_layer.objects.active
            if active is not None and active.as_pointer() in live_pointers:
                view_layer.objects.active = None
        except (AttributeError, ReferenceError, RuntimeError):
            pass

    for obj in live_objects:
        try:
            obj.select_set(False)
        except (AttributeError, ReferenceError, RuntimeError):
            pass

    meshes = [getattr(obj, "data", None) for obj in live_objects]
    batch_remove = getattr(bpy.data, "batch_remove", None)
    if callable(batch_remove):
        batch_remove(ids=live_objects)
        remove_unused_meshes(meshes)
        return

    # Blender versions supported by this extension provide batch_remove. Keep
    # the fallback for source reloads under test doubles and older dev builds.
    for obj in live_objects:
        try:
            current = bpy.data.objects.get(obj.name)
            if current is not None and current.as_pointer() == obj.as_pointer():
                bpy.data.objects.remove(obj, do_unlink=True)
        except ReferenceError:
            pass
    remove_unused_meshes(meshes)


class ModifierApplyError(Exception):
    def __init__(
        self,
        modifier_name: str,
        failed_object: Object,
        target: Optional[Object] = None,
    ) -> None:
        super().__init__(f"Could not apply modifier {modifier_name}")
        self.modifier_name = modifier_name
        self.failed_object = failed_object.object
        self.target_object = target.object if target is not None else None


@contextmanager
def suppress_ui_breathe():
    global _SUPPRESS_UI_BREATHE_DEPTH

    _SUPPRESS_UI_BREATHE_DEPTH += 1
    try:
        yield
    finally:
        _SUPPRESS_UI_BREATHE_DEPTH -= 1


class Object:

    @property
    def hide_during_ui_breathe(self):
        return self in _hidden_during_redraw

    @hide_during_ui_breathe.setter
    def hide_during_ui_breathe(self, hidden):
        if hidden:
            _hidden_during_redraw.add(self)
        else:
            _hidden_during_redraw.discard(self)

    def __init__(self, object, name: Optional[str] = None):
        self.object = object
        self.hide_during_ui_breathe = False
        if name is not None:
            if name in bpy.data.objects:
                i = 1
                while name + str(i) in bpy.data.objects:
                    i += 1
                name += str(i)
            self.object.name = name
        self._vertex_groups = {}

    @property
    def name(self):
        return self.object.name

    @name.setter
    def name(self, value):
        self.object.name = value

    @property
    def vertex_groups(self):
        return self._vertex_groups

    def __add__(self, other: Object):
        self.apply_modifier(union_mod, target=other)
        return self

    def add_without_material_transfer(self, other: Object):
        self.apply_modifier(union_no_material_transfer_mod, target=other)
        return self

    def add_with_material_transfer(
        self,
        other: Object,
        *,
        retry_remesh: Optional[Modifier] = None,
        retry_remesh_on: Literal["self", "target", "both"] = "self",
    ):
        material_start = time.perf_counter()
        prepare_material_transfer(self.object, other.object)
        logger.debug(
            "Prepared Boolean material transfer from %s to %s in %.3fs",
            other.name,
            self.name,
            time.perf_counter() - material_start,
        )
        self.apply_boolean_modifier(
            union_material_transfer_mod,
            target=other,
            retry_remesh=retry_remesh,
            retry_remesh_on=retry_remesh_on,
        )
        return self

    def __sub__(self, other: Object):
        self.apply_modifier(diff_mod, target=other)
        return self

    def __and__(self, other: Object):
        self.apply_modifier(intersect_mod, target=other)
        return self

    @property
    def world_cords_bound_box(self):
        self.select()
        world_coords = [
            (self.object.matrix_world @ mathutils.Vector(coord[:3]))
            for coord in self.bound_box
        ]
        return world_coords

    @property
    def matrix_world(self):
        return self.object.matrix_world

    @property
    def inverse_matrix_world(self):
        return self.matrix_world.inverted()

    @property
    def inverse_transpose_matrix_world(self):
        return self.inverse_matrix_world.transposed()

    @property
    def translation_matrix(self):
        return mathutils.Matrix.Translation(self.object.location)

    @property
    def bound_box(self):
        return self.object.bound_box

    @property
    def max_z(self):
        return max([coord[2] for coord in self.world_cords_bound_box])

    @property
    def min_z(self):
        return min([coord[2] for coord in self.world_cords_bound_box])

    @property
    def max_x(self):
        return max([coord[0] for coord in self.world_cords_bound_box])

    @property
    def min_x(self):
        return min([coord[0] for coord in self.world_cords_bound_box])

    @property
    def max_y(self):
        return max([coord[1] for coord in self.world_cords_bound_box])

    @property
    def min_y(self):
        return min([coord[1] for coord in self.world_cords_bound_box])

    @property
    def center_coords(self):
        return mathutils.Vector(
            [
                self.min_x + self.width / 2,
                self.min_y + self.depth / 2,
                self.min_z + self.height / 2,
            ]
        )

    @property
    def width(self):
        return max([coord[0] for coord in self.world_cords_bound_box]) - min(
            [coord[0] for coord in self.world_cords_bound_box]
        )

    @property
    def height(self):
        return self.max_z - self.min_z

    @property
    def depth(self):
        return max([coord[1] for coord in self.world_cords_bound_box]) - min(
            [coord[1] for coord in self.world_cords_bound_box]
        )

    @property
    def volume(self):
        mesh = bmesh.new()
        try:
            mesh.from_mesh(self.object.data)
            return mesh.calc_volume() / 1000
        except Exception:
            return 0
        finally:
            mesh.free()

    def get_limit_face_idx(
        self, axis: int = 2, max_co: bool = True, flat: bool = False
    ) -> int:
        from .components.geometry_adapter import plan_limit_face_with_worker

        face_idx, _center = plan_limit_face_with_worker(
            self.object,
            axis=axis,
            max_co=max_co,
            flat=flat,
        )
        return face_idx

    def get_limit_face_co(
        self, axis: int = 2, max_co: bool = True, flat: bool = False
    ) -> mathutils.Vector:
        from .components.geometry_adapter import plan_limit_face_with_worker

        _face_idx, center = plan_limit_face_with_worker(
            self.object,
            axis=axis,
            max_co=max_co,
            flat=flat,
            world_space=True,
        )
        return mathutils.Vector(center)

    def scale(self, factor: float, axis: int):
        axis_vector = mathutils.Vector((0, 0, 0))
        axis_vector[axis] = 1
        scale_matrix = mathutils.Matrix.Scale(factor, 4, axis_vector)
        with BMeshObj(self) as bm:
            bm.transform(
                matrix=scale_matrix,
            )
            if factor < 0:
                # Reflection reverses orientation; flip directly, without a
                # connectivity-based winding repair.
                bmesh.ops.reverse_faces(bm, faces=bm.faces)

    def scale_face(
        self,
        factor: float,
        axis: int,
        face_idx: int,
        *,
        around_center: bool = False,
    ):
        axis_vector: list[float] = [1, 1, 1]
        axis_vector[axis] = factor
        with BMeshObj(self) as bm:
            verts = bm.faces[face_idx].verts
            if around_center:
                face_center = bm.faces[face_idx].calc_center_median()
                for vert in verts:
                    vert.co[axis] = face_center[axis] + (
                        vert.co[axis] - face_center[axis]
                    ) * factor
            else:
                bmesh.ops.scale(bm, verts=verts, vec=axis_vector)

    def scale_face_to(self, size: float, axis: int, face_idx: int):
        """Scale one face to an exact local-axis size around its own center."""
        with BMeshObj(self) as bm:
            face = bm.faces[face_idx]
            verts = face.verts
            axis_coords = [vert.co[axis] for vert in verts]
            current_size = max(axis_coords) - min(axis_coords)
            if current_size <= 1e-9:
                raise ValueError(
                    f"Cannot scale zero-size face {face_idx} on axis {axis}"
                )
            face_center = face.calc_center_median()
            factor = size / current_size
            for vert in verts:
                vert.co[axis] = face_center[axis] + (
                    vert.co[axis] - face_center[axis]
                ) * factor

    def translate_face(self, face_idx: int, vector: mathutils.Vector):
        """Translate one face and its vertices by a local-space vector."""
        with BMeshObj(self) as bm:
            bmesh.ops.translate(
                bm,
                vec=vector,
                verts=bm.faces[face_idx].verts,
            )

    def scale_normals(self, offset: float):
        if self.object.type != "MESH":
            raise TypeError("Normal scaling requires a mesh object")
        from .components.geometry_adapter import (
            edit_object_vertices_with_worker,
        )

        edit_object_vertices_with_worker(
            self.object,
            normal_offset=float(offset),
        )
        return self

    def begin_scale_normals(self, offset: float):
        if self.object.type != "MESH":
            raise TypeError("Normal scaling requires a mesh object")
        from .components.geometry_adapter import (
            begin_edit_object_vertices_with_worker,
        )

        return begin_edit_object_vertices_with_worker(
            self.object,
            normal_offset=float(offset),
        ).then(lambda _result: self)

    def smooth_geometry(self, factor: float = 0.5, repeat: int = 5):
        if self.object.type != "MESH":
            raise TypeError("Geometry smoothing requires a mesh object")
        from .components.geometry_adapter import (
            edit_object_vertices_with_worker,
        )

        edit_object_vertices_with_worker(
            self.object,
            smooth_factor=float(factor),
            smooth_repeat=int(repeat),
        )
        return self

    def begin_smooth_geometry(self, factor: float = 0.5, repeat: int = 5):
        if self.object.type != "MESH":
            raise TypeError("Geometry smoothing requires a mesh object")
        from .components.geometry_adapter import (
            begin_edit_object_vertices_with_worker,
        )

        return begin_edit_object_vertices_with_worker(
            self.object,
            smooth_factor=float(factor),
            smooth_repeat=int(repeat),
        ).then(lambda _result: self)

    def scale_to(self, size: float, axis: int):
        if axis == 0:
            scale_factor = size / self.width
        elif axis == 1:
            scale_factor = size / self.depth
        elif axis == 2:
            scale_factor = size / self.height
        self.scale(scale_factor, axis)

    def _create_wire_cage(self) -> Object:
        cage_object = self.object.copy()
        cage_object.data = self.object.data.copy()
        cage_object.animation_data_clear()
        cage_object.name = f"{self.object.name}_wire_cage"
        cage_object.matrix_world = self.object.matrix_world.copy()
        cage_object.display_type = "WIRE"
        cage_object.show_in_front = True
        cage_object.hide_render = True
        bpy.context.collection.objects.link(cage_object)
        return Object(cage_object)

    def _scale_bottom_vertices(self, bottom_scale_factor: float) -> None:
        object_height = self.height
        if object_height <= 1e-6:
            raise ValueError("Selected object height must be greater than zero")

        center_x = self.min_x + self.width / 2
        center_y = self.min_y + self.depth / 2
        min_z = self.min_z
        inverse_world = self.inverse_matrix_world

        with BMeshObj(self) as bm:
            for vert in bm.verts:
                world_co = self.matrix_world @ vert.co
                height_ratio = min(max((world_co.z - min_z) / object_height, 0.0), 1.0)
                scale_factor = 1.0 + (bottom_scale_factor - 1.0) * (1.0 - height_ratio)
                scaled_world = mathutils.Vector(
                    (
                        center_x + (world_co.x - center_x) * scale_factor,
                        center_y + (world_co.y - center_y) * scale_factor,
                        world_co.z,
                    )
                )
                vert.co = inverse_world @ scaled_world

    def scale_bottom_proportional(self, bottom_scale_factor: float) -> None:
        cage = self._create_wire_cage()
        cage_mesh = cage.object.data
        surface_deform = None

        try:
            surface_deform = self.object.modifiers.new(
                name="BottomScaleCage", type="SURFACE_DEFORM"
            )
            surface_deform.target = cage.object
            bpy.context.view_layer.update()

            self.select()
            bpy.ops.object.surfacedeform_bind(modifier=surface_deform.name)

            cage._scale_bottom_vertices(bottom_scale_factor)
            bpy.context.view_layer.update()

            self.select()
            bpy.ops.object.modifier_apply(modifier=surface_deform.name)
        except Exception:
            if (
                surface_deform is not None
                and self.object.modifiers.get(surface_deform.name) is not None
            ):
                self.object.modifiers.remove(surface_deform)
            raise
        finally:
            cage.remove()
            if getattr(cage_mesh, "users", 0) == 0:
                bpy.data.meshes.remove(cage_mesh)

    def get_face_verts_idxs(self, face_idx: int):
        return list(self.object.data.polygons[face_idx].vertices)

    def _remove_loose_vertex_indices(self, loose_indices) -> int:
        loose_indices = set(int(value) for value in loose_indices)
        if not loose_indices:
            return 0
        with BMeshObj(self) as bm:
            loose_vertices = [
                vertex for vertex in bm.verts if vertex.index in loose_indices
            ]
            removed_count = len(loose_vertices)
            if loose_vertices:
                bmesh.ops.delete(bm, geom=loose_vertices, context="VERTS")
        if removed_count:
            logger.info(
                "Removed %d loose vertices from %s before mesh processing",
                removed_count,
                self.name,
            )
        return removed_count

    def remove_loose_vertices_and_check_islands(self) -> tuple[int, bool]:
        """Remove loose vertices and report real mesh islands in one analysis."""
        from .components.geometry_adapter import (
            inspect_object_mesh_connectivity_with_worker,
        )

        inspection = inspect_object_mesh_connectivity_with_worker(self.object)
        removed_count = self._remove_loose_vertex_indices(
            inspection.loose_vertices
        )
        return removed_count, inspection.multiple_components

    def remove_loose_vertices(self) -> int:
        """Remove vertices which do not belong to an edge or face."""
        # Basic import cleanup is local: it must not authorize the licensed
        # geometry worker merely to discard unconnected vertices.
        with BMeshObj(self) as bm:
            loose_vertices = [
                vertex for vertex in bm.verts
                if not vertex.link_edges and not vertex.link_faces
            ]
            removed_count = len(loose_vertices)
            if loose_vertices:
                bmesh.ops.delete(bm, geom=loose_vertices, context="VERTS")
        return removed_count

    def split_isolated_meshes(self) -> list[Object]:
        self.select()
        original_objects = set(bpy.context.scene.objects)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.separate(type="LOOSE")
        bpy.ops.object.mode_set(mode="OBJECT")
        self.select()
        new_objects = set(bpy.context.scene.objects) - original_objects
        # Blender keeps one loose part on the original object and spawns
        # additional objects for the remaining disconnected meshes.
        return [self, *[Object(obj) for obj in new_objects]]

    def has_multiple_isolated_meshes(self) -> bool:
        """Return whether the mesh contains more than one connected island."""
        from .components.geometry_adapter import (
            inspect_object_mesh_connectivity_with_worker,
        )

        return inspect_object_mesh_connectivity_with_worker(
            self.object
        ).multiple_components

    def create_vertex_group(self, name: str, vertex_idxs: list[int]):
        if name in self.object.vertex_groups:
            self.object.vertex_groups.remove(self.object.vertex_groups[name])
        self.object.vertex_groups.new(name=name)
        for vertex_idx in vertex_idxs:
            self.object.vertex_groups[name].add([vertex_idx], 1, "ADD")
        self._vertex_groups[name] = vertex_idxs

    def get_face_normal(self, face_idx: int):
        face_normal = self.object.data.polygons[face_idx].normal.copy()
        face_normal = self.matrix_world.inverted() @ face_normal
        return face_normal.normalized()

    def translate_face_to_point(self, face_idx: int, point: mathutils.Vector):
        with BMeshObj(self, update_normals=False) as bm:
            face = bm.faces[face_idx]
            face_co = face.calc_center_median()
            to_point_vector = point - (self.matrix_world @ face_co)
            bmesh.ops.translate(bm, vec=to_point_vector, verts=bm.verts)

    def translate_whole(self, vector: mathutils.Vector):
        with BMeshObj(self, update_normals=False) as bm:
            bmesh.ops.translate(bm, vec=vector, verts=bm.verts)

    def rotate_whole(
        self,
        rotation_matrix: mathutils.Matrix,
        center: mathutils.Vector = mathutils.Vector((0, 0, 0)),
    ):
        with BMeshObj(self) as bm:
            bmesh.ops.rotate(
                bm,
                cent=center,
                matrix=rotation_matrix,
                verts=bm.verts,
                space=self.object.matrix_world,
            )

    def geometry_to_origin(self):
        self.select()
        bpy.ops.object.origin_set(type="GEOMETRY_ORIGIN", center="BOUNDS")

    def origin_to_geometry(self):
        self.select()
        bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="MEDIAN")

    def origin_to_cursor(self):
        self.select()
        bpy.ops.object.origin_set(type="ORIGIN_CURSOR")

    def _modifier_retry_objects(
        self,
        target: Optional[Object],
        retry_remesh_on: Literal["self", "target", "both"],
    ) -> list[Object]:
        retry_objects = []
        if retry_remesh_on in {"self", "both"}:
            retry_objects.append(self)
        if retry_remesh_on in {"target", "both"} and target is not None:
            retry_objects.append(target)
        return retry_objects

    def _apply_modifier_once(self, modifier: Modifier, target: Optional[Object] = None):
        if modifier.name == "BOOLEAN":
            safe_boolean_properties(
                self.object, target.object if target is not None else None, modifier.properties
            )
            if boolean_inputs_are_empty(self.object, target.object):
                # All three set operations on two empty meshes are empty. Avoid
                # native evaluation and older Blender leaving the modifier live.
                logger.info("Skipped Boolean on two empty operands: %s", self.name)
                return
        self.select()
        bpy.context.view_layer.objects.active = self.object
        direct_boolean_redraw = (
            modifier.name == "BOOLEAN" and self._direct_boolean_retry_enabled()
        )
        should_breathe = (
            modifier.name in UI_BREATHE_MODIFIERS
            and (
                _SUPPRESS_UI_BREATHE_DEPTH <= 0
                or direct_boolean_redraw
            )
        )
        if should_breathe:
            # Refresh before creating the modifier so redraw cannot evaluate it
            # once here and again when it is applied.
            self._breathe_around_operation(target)
        new_mod = self.add_modifier(modifier, target)
        new_mod_name = new_mod.name
        try:
            bpy.ops.object.modifier_apply(modifier=new_mod_name)
            if self.object.modifiers.get(new_mod_name) is not None:
                self.object.modifiers.remove(self.object.modifiers[new_mod_name])
                raise ModifierApplyError(new_mod_name, self, target)
        except ModifierApplyError:
            raise
        except Exception as exc:
            if self.object.modifiers.get(new_mod_name) is not None:
                self.object.modifiers.remove(self.object.modifiers[new_mod_name])
            raise ModifierApplyError(new_mod_name, self, target) from exc
        finally:
            deselect_all_objects()
            if should_breathe:
                self._breathe_around_operation(target)

    @staticmethod
    def _is_manifold_boolean(modifier: Modifier) -> bool:
        return (
            modifier.name == "BOOLEAN"
            and str(modifier.properties.get("solver", "")).upper() == "MANIFOLD"
        )

    @staticmethod
    def _clean_for_manifold_boolean_retry(obj: Object) -> bool:
        cleanup_start = time.perf_counter()
        try:
            stats = clean_mesh_for_manifold_boolean(obj.object.data)
        except Exception:
            logger.warning(
                "Geometry cleanup failed for %s before MANIFOLD Boolean retry; "
                "continuing to remesh fallback; elapsed=%.3fs",
                obj.name,
                time.perf_counter() - cleanup_start,
                exc_info=True,
            )
            return False
        logger.info(
            "Light-cleaned %s before MANIFOLD Boolean retry: "
            "welded_vertices=%d dissolved_micro_edges=%d "
            "degenerate_faces=%d duplicate_faces=%d boundary_loops_filled=%d "
            "flat_boundary_loops_stitched=%d "
            "elapsed=%.3fs",
            obj.name,
            stats.welded_vertices,
            stats.dissolved_micro_edges,
            stats.degenerate_faces_removed,
            stats.duplicate_faces_removed,
            stats.boundary_loops_filled,
            stats.flat_boundary_loops_stitched,
            time.perf_counter() - cleanup_start,
        )
        return True

    def _apply_boolean_with_staged_both_retry(
        self,
        modifier: Modifier,
        target: Object,
        retry_remesh: Modifier,
        *,
        clean_before_remesh_retry: bool = True,
    ) -> None:
        self_is_manifold = self.is_manifold()
        retry_objects = [target] if self_is_manifold else [self, target]
        if clean_before_remesh_retry:
            for retry_index, retry_object in enumerate(retry_objects):
                cleaned = self._clean_for_manifold_boolean_retry(retry_object)
                if not cleaned:
                    continue
                try:
                    self._apply_modifier_once(modifier, target)
                    return
                except Exception:
                    next_name = (
                        retry_objects[retry_index + 1].name
                        if retry_index + 1 < len(retry_objects)
                        else None
                    )
                    logger.warning(
                        "MANIFOLD Boolean still failed after cleaning %s%s",
                        retry_object.name,
                        (
                            f"; cleaning {next_name} next"
                            if next_name
                            else "; using remesh fallback"
                        ),
                        exc_info=True,
                    )

        if not self_is_manifold:
            logger.debug(
                "Boolean retry: %s is non-manifold; applying retry remesh %s to %s",
                self.name,
                retry_remesh.properties,
                self.name,
            )
            self.apply_modifier(retry_remesh)
            try:
                self._apply_modifier_once(modifier, target)
                return
            except Exception:
                logger.debug(
                    "Boolean retry still failed after remeshing %s; applying retry remesh %s to %s",
                    self.name,
                    retry_remesh.properties,
                    target.name,
                    exc_info=True,
                )
                target.apply_modifier(retry_remesh)
                self._apply_modifier_once(modifier, target)
                return

        logger.debug(
            "Boolean retry: %s is manifold; applying retry remesh %s to target %s",
            self.name,
            retry_remesh.properties,
            target.name,
        )
        target.apply_modifier(retry_remesh)
        self._apply_modifier_once(modifier, target)

    def _breathe_around_operation(self, target: Optional[Object] = None) -> None:
        hidden_objects = [
            obj
            for obj in (self, target)
            if obj is not None and obj.hide_during_ui_breathe
        ]
        if not hidden_objects:
            breathe_viewport()
            return

        visibility_states = []
        try:
            for hidden_object in hidden_objects:
                raw_object = hidden_object.object
                visibility_states.append(
                    (
                        raw_object,
                        raw_object.hide_get(),
                        bool(getattr(raw_object, "hide_viewport", False)),
                        bool(getattr(raw_object, "hide_render", False)),
                    )
                )
                raw_object.hide_set(True)
                raw_object.hide_viewport = True
                raw_object.hide_render = True
            breathe_viewport()
        finally:
            for raw_object, was_hidden, was_hide_viewport, was_hide_render in (
                visibility_states
            ):
                try:
                    raw_object.hide_set(was_hidden)
                    raw_object.hide_viewport = was_hide_viewport
                    raw_object.hide_render = was_hide_render
                except ReferenceError:
                    pass

    def _apply_modifier_with_configured_retry(
        self,
        modifier: Modifier,
        target: Optional[Object] = None,
        *,
        retry_remesh: Optional[Modifier] = None,
        retry_remesh_on: Literal["self", "target", "both"] = "self",
        clean_before_remesh_retry: bool = True,
    ):
        start_time = time.perf_counter()
        try:
            self._apply_modifier_once(modifier, target)
        except Exception:
            if retry_remesh is None:
                logger.debug(
                    "Modifier %s with properties %s failed on object %s after %.3fs",
                    modifier.name,
                    modifier.properties,
                    self.name,
                    time.perf_counter() - start_time,
                    exc_info=True,
                )
                raise
            retry_objects = self._modifier_retry_objects(target, retry_remesh_on)
            if not retry_objects:
                logger.debug(
                    "Modifier %s with properties %s failed on object %s after %.3fs; no retry objects available",
                    modifier.name,
                    modifier.properties,
                    self.name,
                    time.perf_counter() - start_time,
                    exc_info=True,
                )
                raise
            should_clean_manifold_boolean = (
                clean_before_remesh_retry
                and self._is_manifold_boolean(modifier)
            )
            if (
                self._is_manifold_boolean(modifier)
                and retry_remesh_on == "both"
                and target is not None
            ):
                logger.debug(
                    "Could not apply modifier %s with properties %s to %s; checking manifold state before retry remesh %s",
                    modifier.name,
                    modifier.properties,
                    self.name,
                    retry_remesh.properties,
                    exc_info=True,
                )
                self._apply_boolean_with_staged_both_retry(
                    modifier,
                    target,
                    retry_remesh,
                    clean_before_remesh_retry=clean_before_remesh_retry,
                )
                logger.debug(
                    "Applied modifier %s with properties %s to object %s in %.3fs",
                    modifier.name,
                    modifier.properties,
                    self.name,
                    time.perf_counter() - start_time,
                )
                return
            if should_clean_manifold_boolean:
                cleaned_any = False
                for retry_object in retry_objects:
                    cleaned_any = (
                        self._clean_for_manifold_boolean_retry(retry_object)
                        or cleaned_any
                    )
                if cleaned_any:
                    try:
                        self._apply_modifier_once(modifier, target)
                        logger.info(
                            "Applied MANIFOLD Boolean to %s after geometry cleanup; "
                            "skipped remesh fallback",
                            self.name,
                        )
                        return
                    except Exception:
                        logger.warning(
                            "MANIFOLD Boolean still failed on %s after geometry "
                            "cleanup; applying configured remesh fallback",
                            self.name,
                            exc_info=True,
                        )
            logger.debug(
                "Could not apply modifier %s with properties %s to %s; applying retry remesh %s to %s and trying again",
                modifier.name,
                modifier.properties,
                self.name,
                retry_remesh.properties,
                ", ".join(obj.name for obj in retry_objects),
                exc_info=True,
            )
            for obj in retry_objects:
                obj.apply_modifier(retry_remesh)
            self._apply_modifier_once(modifier, target)
        logger.debug(
            "Applied modifier %s with properties %s to object %s in %.3fs",
            modifier.name,
            modifier.properties,
            self.name,
            time.perf_counter() - start_time,
        )

    @staticmethod
    def _is_original_master(obj: Object) -> bool:
        master = bpy.data.objects.get("master")
        if master is not None:
            return obj.object == master

        # Workflows which do not create a build-time proxy keep the imported
        # master under the legacy ``patron`` name.
        return obj.object == bpy.data.objects.get("patron")

    @staticmethod
    def _direct_boolean_retry_enabled() -> bool:
        scene = getattr(bpy.context, "scene", None)
        return bool(
            scene is not None and scene.get(DIRECT_BOOLEAN_RETRY_SCENE_KEY, False)
        )

    def _remesh_for_direct_boolean_retry(self, obj: Object) -> None:
        if self._is_original_master(obj):
            # Import locally to avoid the voxel_size -> Object module cycle.
            from .voxel_size import get_master_voxel_size

            quality = bpy.context.scene.master_quality
            voxel_size = get_master_voxel_size(quality, obj)
            remesh = build_voxel_modifier(voxel_size)
            logger.warning(
                "Direct-mold Boolean failed; voxel-remeshing original master "
                "%s with quality=%s voxel_size=%.6f",
                obj.name,
                quality,
                voxel_size,
            )
        else:
            remesh = build_sharp_modifier(8)
            logger.warning(
                "Direct-mold Boolean failed; sharp-remeshing problematic object %s",
                obj.name,
            )
        obj.apply_modifier(remesh)

    def _retry_direct_boolean(self, modifier: Modifier, target: Optional[Object]) -> None:
        retry_objects = [self]
        if target is not None and target.object != self.object:
            retry_objects.append(target)

        last_error = None
        for retry_object in retry_objects:
            self._remesh_for_direct_boolean_retry(retry_object)
            try:
                self._apply_modifier_once(modifier, target)
                return
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Direct-mold Boolean still failed after remeshing %s",
                    retry_object.name,
                    exc_info=True,
                )

        if last_error is not None:
            raise last_error

    def _retry_manifold_boolean_after_cleanup(
        self,
        modifier: Modifier,
        target: Optional[Object],
        retry_objects: list[Object],
    ) -> bool:
        """Clean operands one at a time and retry a MANIFOLD Boolean."""
        if not self._is_manifold_boolean(modifier):
            return False

        for retry_index, retry_object in enumerate(retry_objects):
            if not self._clean_for_manifold_boolean_retry(retry_object):
                continue
            try:
                self._apply_modifier_once(modifier, target)
                logger.info(
                    "Applied MANIFOLD Boolean to %s after cleaning %s",
                    self.name,
                    retry_object.name,
                )
                return True
            except Exception:
                next_name = (
                    retry_objects[retry_index + 1].name
                    if retry_index + 1 < len(retry_objects)
                    else None
                )
                logger.warning(
                    "MANIFOLD Boolean still failed after cleaning %s%s",
                    retry_object.name,
                    (
                        f"; cleaning {next_name} next"
                        if next_name
                        else "; cleanup retries exhausted"
                    ),
                    exc_info=True,
                )
        return False

    def _retry_manifold_boolean_after_default_remesh(
        self,
        modifier: Modifier,
        target: Optional[Object],
        retry_objects: list[Object],
    ) -> bool:
        """Remesh operands lazily after cleanup could not recover a Boolean."""
        if not self._is_manifold_boolean(modifier):
            return False

        for retry_index, retry_object in enumerate(retry_objects, start=1):
            retry_modifier = retry_object._geometry_fallback_remesh_modifier()
            remesh_mode = str(
                retry_modifier.properties.get("mode", "UNKNOWN")
            ).lower()
            logger.warning(
                "MANIFOLD Boolean fallback %d/%d: %s-remeshing %s only "
                "after cleanup retries failed",
                retry_index,
                len(retry_objects),
                remesh_mode,
                retry_object.name,
            )
            retry_object.apply_modifier(retry_modifier)
            try:
                self._apply_modifier_once(modifier, target)
                logger.info(
                    "Applied MANIFOLD Boolean to %s after lazy remesh of %s",
                    self.name,
                    retry_object.name,
                )
                return True
            except Exception:
                logger.warning(
                    "MANIFOLD Boolean still failed after lazy remesh of %s",
                    retry_object.name,
                    exc_info=True,
                )
        return False

    def apply_modifier(
        self,
        modifier: Modifier,
        target: Optional[Object] = None,
        *,
        retry_remesh: Optional[Modifier] = None,
        retry_remesh_on: Literal["self", "target", "both"] = "self",
        clean_before_remesh_retry: bool = True,
    ):
        try:
            self._apply_modifier_with_configured_retry(
                modifier,
                target,
                retry_remesh=retry_remesh,
                retry_remesh_on=retry_remesh_on,
                clean_before_remesh_retry=clean_before_remesh_retry,
            )
        except Exception:
            if retry_remesh is None and self._is_manifold_boolean(modifier):
                if (
                    target is not None
                    and target.object != self.object
                    and self.is_manifold()
                ):
                    cleanup_objects = [target]
                else:
                    cleanup_objects = [self]
                    if target is not None and target.object != self.object:
                        cleanup_objects.append(target)
                if self._retry_manifold_boolean_after_cleanup(
                    modifier, target, cleanup_objects
                ):
                    return
                if (
                    not self._direct_boolean_retry_enabled()
                    and self._retry_manifold_boolean_after_default_remesh(
                        modifier,
                        target,
                        cleanup_objects,
                    )
                ):
                    return
            if modifier.name != "BOOLEAN" or not self._direct_boolean_retry_enabled():
                raise
            logger.warning(
                "Catching failed direct-mold Boolean %s on %s (operand %s)",
                modifier.properties.get("operation", "UNKNOWN"),
                self.name,
                target.name if target is not None else "none",
                exc_info=True,
            )
            self._retry_direct_boolean(modifier, target)

    def apply_boolean_modifier(
        self,
        modifier: Modifier,
        target: Object,
        *,
        retry_remesh: Optional[Modifier] = None,
        retry_remesh_on: Literal["self", "target", "both"] = "both",
        clean_before_remesh_retry: bool = True,
    ):
        if modifier.name != "BOOLEAN":
            raise ValueError("apply_boolean_modifier only accepts BOOLEAN modifiers")
        self.apply_modifier(
            modifier,
            target=target,
            retry_remesh=retry_remesh,
            retry_remesh_on=retry_remesh_on,
            clean_before_remesh_retry=clean_before_remesh_retry,
        )

    def apply_boolean_modifier_with_target_manifold_retry(
        self,
        modifier: Modifier,
        target: Object,
        *,
        self_remesh: Modifier,
        target_remesh: Modifier,
    ) -> None:
        """Retry a Boolean with cleanup first, then operand-specific remeshing.

        The target is checked first because it is generally cheaper than the
        Boolean receiver. Cleanup is attempted in diagnosis order before any
        remesh. If cleanup is insufficient, a non-manifold target is remeshed
        first; otherwise the receiver is remeshed first. The remaining operand
        is remeshed only for the final attempt.
        """
        if modifier.name != "BOOLEAN":
            raise ValueError(
                "apply_boolean_modifier_with_target_manifold_retry only accepts "
                "BOOLEAN modifiers"
            )

        start_time = time.perf_counter()
        try:
            self._apply_modifier_once(modifier, target)
        except Exception:
            target_is_manifold = target.is_manifold()
            if target_is_manifold:
                retry_steps = (
                    (self, self_remesh),
                    (target, target_remesh),
                )
            else:
                retry_steps = (
                    (target, target_remesh),
                    (self, self_remesh),
                )

            logger.warning(
                "Boolean %s failed on %s with target %s; target manifold=%s; "
                "trying geometry cleanup before remeshing",
                modifier.properties.get("operation", "UNKNOWN"),
                self.name,
                target.name,
                target_is_manifold,
                exc_info=True,
            )
            cleanup_objects = [retry_object for retry_object, _ in retry_steps]
            recovered = self._retry_manifold_boolean_after_cleanup(
                modifier, target, cleanup_objects
            )
            if not recovered:
                logger.warning(
                    "Geometry cleanup did not recover Boolean %s on %s; "
                    "using remesh fallback on %s first",
                    modifier.properties.get("operation", "UNKNOWN"),
                    self.name,
                    retry_steps[0][0].name,
                )
                for retry_index, (retry_object, retry_modifier) in enumerate(
                    retry_steps
                ):
                    logger.warning(
                        "Boolean remesh fallback %d: applying %s to %s",
                        retry_index + 1,
                        retry_modifier.properties,
                        retry_object.name,
                    )
                    retry_object.apply_modifier(retry_modifier)
                    try:
                        self._apply_modifier_once(modifier, target)
                        break
                    except Exception:
                        if retry_index + 1 == len(retry_steps):
                            raise
                        logger.warning(
                            "Boolean retry still failed after remeshing %s; "
                            "remeshing the remaining operand",
                            retry_object.name,
                            exc_info=True,
                        )

        logger.debug(
            "Applied modifier %s with properties %s to object %s in %.3fs",
            modifier.name,
            modifier.properties,
            self.name,
            time.perf_counter() - start_time,
        )

    def _geometry_fallback_remesh_modifier(self) -> Modifier:
        """Use voxel remesh for the imported master and sharp for generated parts."""
        if self._is_original_master(self):
            # Import locally to avoid the voxel_size -> Object module cycle.
            from .voxel_size import get_master_voxel_size

            scene = bpy.context.scene
            quality = str(getattr(scene, "master_quality", "MID"))
            return build_voxel_modifier(get_master_voxel_size(quality, self))
        return build_sharp_modifier(8)

    def apply_boolean_modifier_with_geometry_fallback(
        self,
        modifier: Modifier,
        target: Object,
    ) -> None:
        """Apply a MANIFOLD Boolean with cleanup, then operand-aware remeshing."""
        self.apply_boolean_modifier_with_target_manifold_retry(
            modifier,
            target,
            self_remesh=self._geometry_fallback_remesh_modifier(),
            target_remesh=target._geometry_fallback_remesh_modifier(),
        )

    def add_with_material_transfer_and_geometry_fallback(
        self,
        other: Object,
    ) -> Object:
        """Union material-bearing geometry using the standard recovery policy."""
        prepare_material_transfer(self.object, other.object)
        self.apply_boolean_modifier_with_geometry_fallback(
            union_material_transfer_mod,
            other,
        )
        return self

    def apply_all_modifiers(self):
        self.select()
        bpy.context.view_layer.objects.active = self.object
        for mod in list(self.object.modifiers):
            print(f"Applying modifier {mod.name}")
            bpy.ops.object.modifier_apply(modifier=mod.name)

    def add_modifier(
        self,
        modifier: Modifier,
        target: Optional[Object] = None,
        index_first: bool = True,
        show_viewport: bool = True,
    ):
        properties = modifier.properties
        if modifier.name == "BOOLEAN":
            properties = safe_boolean_properties(
                self.object, target.object if target is not None else None, properties,
                index_first=index_first,
            )
        new_mod = self.object.modifiers.new(modifier.name, type=modifier.name)
        try:
            if not show_viewport:
                new_mod.show_viewport = False
            if target:
                try:
                    new_mod.target = target.object
                except AttributeError:
                    new_mod.object = target.object
            for key, value in properties.items():
                if key == "material_mode" and not hasattr(new_mod, key):
                    logger.debug(
                        "Modifier %s does not support material_mode; skipping",
                        modifier.name,
                    )
                    continue
                try:
                    setattr(new_mod, key, value)
                except (AttributeError, TypeError):
                    if key != "material_mode":
                        raise
                    logger.debug(
                        "Could not set material_mode=%s on modifier %s; skipping",
                        value,
                        modifier.name,
                        exc_info=True,
                    )
            if index_first:
                last_index = len(self.object.modifiers) - 1
                self.object.modifiers.move(last_index, 0)
        except Exception:
            # Do not leave a partially configured live modifier for the next
            # dependency-graph update or a retry to evaluate.
            self.object.modifiers.remove(new_mod)
            raise
        return new_mod

    def select(self):
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
            deselect_all_objects()
        except Exception:
            pass
        self.object.select_set(True)
        self.object.select_set(True)
        bpy.context.view_layer.objects.active = self.object

    def remove(self):
        remove_objects_safely((self.object,))

    def duplicate(self, name_adder: str = "") -> Object:
        name_adder = "_copy" if not name_adder else name_adder
        duplicate_obj = self.object.copy()
        if self.object.data is not None:
            duplicate_obj.data = self.object.data.copy()
        collection = (
            self.object.users_collection[0]
            if self.object.users_collection
            else bpy.context.collection
        )
        collection.objects.link(duplicate_obj)
        duplicate_obj.matrix_world = self.object.matrix_world.copy()
        duplicate_obj.hide_set(False)
        duplicate_obj.hide_viewport = False
        duplicate_obj.hide_render = False
        duplicated = Object(duplicate_obj, self.object.name + name_adder)
        duplicated.select()
        return duplicated

    def is_manifold(self):
        start_time = time.perf_counter()
        from .components.geometry_adapter import (
            is_object_mesh_manifold_lightweight,
        )

        is_manifold = is_object_mesh_manifold_lightweight(self.object)
        logger.debug(
            f"Object {self.name} is {is_manifold=} in {time.perf_counter() - start_time:.3f}s"
        )
        return is_manifold

    def begin_is_manifold(self):
        from .components.geometry_adapter import (
            begin_is_object_mesh_manifold_lightweight,
        )

        return begin_is_object_mesh_manifold_lightweight(self.object)

    def _select_mesh_faces(self, face_indices):
        """Change selection only, without rebuilding or reorienting the mesh."""
        import numpy as np

        mesh = self.object.data
        selected = np.zeros(len(mesh.polygons), dtype=np.bool_)
        selected[list(face_indices)] = True
        # These attributes back Blender's .select properties. Clear stale
        # vertex/edge flags so edit-mode entry cannot select unrelated faces.
        for name in (".select_vert", ".select_edge"):
            attribute = mesh.attributes.get(name)
            if attribute is not None:
                mesh.attributes.remove(attribute)
        attribute = mesh.attributes.get(".select_poly")
        if attribute is None:
            attribute = mesh.attributes.new(".select_poly", "BOOLEAN", "FACE")
        attribute.data.foreach_set("value", selected)

    def select_face(self, face_idx: int):
        self._select_mesh_faces((face_idx,))

    def select_linked_flat_faces(self):
        self.select()
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.faces_select_linked_flat()
        bpy.ops.object.mode_set(mode="OBJECT")

    def select_limit_flat_faces(
        self, max_co: bool = True, tolerance: float = 5e-4
    ) -> int:
        from .components.geometry_adapter import (
            select_limit_flat_faces_with_worker,
        )

        selected_indices = set(
            int(value)
            for value in select_limit_flat_faces_with_worker(
                self.object,
                max_co=max_co,
                tolerance=tolerance,
            )
        )
        self._select_mesh_faces(selected_indices)
        return len(selected_indices)

    def extrude_selected(self, distance: float):
        self.select()
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.extrude_region_move(
            TRANSFORM_OT_translate={"value": (0.0, 0.0, distance)}
        )
        bpy.ops.object.mode_set(mode="OBJECT")

    def move_selected(self, distance: float):
        self.select()
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.transform.translate(value=(0.0, 0.0, distance))
        bpy.ops.object.mode_set(mode="OBJECT")

    def cut_plane(
        self,
        plane_normal: mathutils.Vector = mathutils.Vector((1, 0, 0)),
        plane_point: mathutils.Vector = mathutils.Vector((0, 0, 0)),
        *,
        retry_remesh: Optional[Modifier] = None,
    ):
        from .components.geometry_adapter import (
            plan_reference_object_cutter_with_worker,
        )

        result = plan_reference_object_cutter_with_worker(
            self,
            "CUT",
            plane_normal=[float(value) for value in plane_normal],
            plane_point=[float(value) for value in plane_point],
        )
        with suppress_ui_breathe():
            cutter_cube_r = self._cutter_from_worker_recipe(
                result["cutters"][0],
                "cutter_cube_r",
            )
            cutter_cube_r.hide_during_ui_breathe = True
            try:
                if retry_remesh is None:
                    self -= cutter_cube_r
                else:
                    self.apply_boolean_modifier(
                        diff_mod,
                        target=cutter_cube_r,
                        retry_remesh=retry_remesh,
                        retry_remesh_on="self",
                        clean_before_remesh_retry=True,
                    )
            finally:
                cutter_cube_r.remove()

    @staticmethod
    def _cutter_from_worker_recipe(recipe: dict, name: str) -> Object:
        cutter = Object(create_cube_primitive(1.0), name)
        cutter.hide_during_ui_breathe = True
        cutter.object.dimensions = mathutils.Vector(recipe["dimensions"])
        cutter.object.rotation_mode = "QUATERNION"
        cutter.object.rotation_quaternion = mathutils.Quaternion(
            recipe["rotation_quaternion"]
        )
        cutter.object.location = mathutils.Vector(recipe["center"])
        return cutter

    def split(
        self,
        plane_normal: mathutils.Vector = mathutils.Vector((1, 0, 0)),
        plane_point: mathutils.Vector = mathutils.Vector((0, 0, 0)),
    ) -> tuple[Object, Object]:
        from .components.geometry_adapter import (
            plan_reference_object_cutter_with_worker,
        )

        result = plan_reference_object_cutter_with_worker(
            self,
            "SPLIT",
            plane_normal=[float(value) for value in plane_normal],
            plane_point=[float(value) for value in plane_point],
            split_tolerance=0.001,
        )
        with suppress_ui_breathe():
            cutter_cube_l = self._cutter_from_worker_recipe(
                result["cutters"][0],
                "cutter_cube_l",
            )
            cutter_cube_r = self._cutter_from_worker_recipe(
                result["cutters"][1],
                "cutter_cube_r",
            )
            cutter_cube_l.hide_during_ui_breathe = True
            cutter_cube_r.hide_during_ui_breathe = True
            self_copy_l = None
            self_copy_r = None
            try:
                self_copy_l = self.duplicate(name_adder="_l")
                self_copy_r = self.duplicate(name_adder="_r")
                self_copy_l.apply_boolean_modifier(
                    diff_mod,
                    target=cutter_cube_r,
                    retry_remesh=build_sharp_modifier(8),
                    retry_remesh_on="self",
                )
                if self_copy_l.has_empty_boolean:
                    raise Exception("Boolean modifier without target failed")
                self_copy_r.apply_boolean_modifier(
                    diff_mod,
                    target=cutter_cube_l,
                    retry_remesh=build_sharp_modifier(8),
                    retry_remesh_on="self",
                )
                if self_copy_r.has_empty_boolean:
                    raise Exception("Boolean modifier without target failed")
                return self_copy_l, self_copy_r
            except Exception:
                if self_copy_l is not None:
                    self_copy_l.remove()
                if self_copy_r is not None:
                    self_copy_r.remove()
                raise
            finally:
                cutter_cube_l.remove()
                cutter_cube_r.remove()

    def _create_split_plane_cutter(
        self,
        plane_normal: mathutils.Vector,
        plane_point: mathutils.Vector,
        thickness: float,
    ) -> Object:
        from .components.geometry_adapter import (
            plan_reference_object_cutter_with_worker,
        )

        result = plan_reference_object_cutter_with_worker(
            self,
            "SLAB",
            plane_normal=[float(value) for value in plane_normal],
            plane_point=[float(value) for value in plane_point],
            thickness=float(thickness),
        )
        return self._cutter_from_worker_recipe(
            result["cutters"][0],
            "split_plane",
        )

    @staticmethod
    def _breathe_with_hidden_object(hidden_obj: Object) -> None:
        try:
            was_hidden = hidden_obj.object.hide_get()
            was_hide_viewport = bool(getattr(hidden_obj.object, "hide_viewport", False))
            was_hide_render = bool(getattr(hidden_obj.object, "hide_render", False))
        except ReferenceError:
            breathe_viewport()
            return

        try:
            hidden_obj.object.hide_set(True)
            hidden_obj.object.hide_viewport = True
            hidden_obj.object.hide_render = True
            breathe_viewport()
        finally:
            try:
                hidden_obj.object.hide_set(was_hidden)
                hidden_obj.object.hide_viewport = was_hide_viewport
                hidden_obj.object.hide_render = was_hide_render
            except ReferenceError:
                pass

    @staticmethod
    def _has_mesh_geometry(obj: Object) -> bool:
        data = getattr(obj.object, "data", None)
        return bool(
            data is not None
            and getattr(data, "vertices", None) is not None
            and len(data.vertices) > 0
            and getattr(data, "polygons", None) is not None
            and len(data.polygons) > 0
        )

    @staticmethod
    def _keep_largest_split_side(parts: list[Object], name: str) -> Object:
        if not parts:
            raise ValueError(f"No mesh parts found for split side {name}")

        def size_key(part: Object) -> tuple[float, int, int]:
            data = part.object.data
            return (
                abs(float(part.volume)),
                len(data.polygons),
                len(data.vertices),
            )

        largest = max(parts, key=size_key)
        discarded_names = []
        for part in parts:
            if part.object == largest.object:
                continue
            discarded_names.append(part.name)
            if part.object.name in bpy.data.objects:
                part.remove()

        largest.name = name
        if discarded_names:
            logger.debug(
                "Split side %s kept largest isolated mesh and removed %d: %s",
                name,
                len(discarded_names),
                ", ".join(discarded_names),
            )
        return largest

    @staticmethod
    def _join_split_side(parts: list[Object], name: str) -> Object:
        """Keep every isolated mesh on a split side in one object."""
        started = time.perf_counter()
        if not parts:
            raise ValueError(f"No mesh parts found for split side {name}")

        def size_key(part: Object) -> tuple[float, int, int]:
            data = part.object.data
            return (
                abs(float(part.volume)),
                len(data.polygons),
                len(data.vertices),
            )

        joined = max(parts, key=size_key)
        joined_count = len(parts) - 1
        if joined_count:
            # Keep the same active object (and its properties), but evaluate
            # the joined mesh only once instead of once per loose island.
            bpy.ops.object.mode_set(mode="OBJECT")
            deselect_all_objects()
            for part in parts:
                part.object.select_set(True)
            bpy.context.view_layer.objects.active = joined.object
            meshes = [part.object.data for part in parts]
            bpy.ops.object.join()
            remove_unused_meshes(meshes)

        joined.name = name
        if joined_count:
            logger.debug(
                "Split side %s preserved and joined %d additional isolated mesh%s "
                "in one join: total=%.3fs",
                name,
                joined_count,
                "" if joined_count == 1 else "es",
                time.perf_counter() - started,
            )
        return joined

    def split_optimized(
        self,
        plane_normal: mathutils.Vector = mathutils.Vector((1, 0, 0)),
        plane_point: mathutils.Vector = mathutils.Vector((0, 0, 0)),
        *,
        preserve_isolated_meshes: bool = False,
        retry_remesh: Optional[Modifier] = None,
        allow_empty_sides: bool = False,
    ) -> tuple[Optional[Object], Optional[Object]]:
        """Cut a slab; optionally return None for sides with no surviving mesh."""
        with suppress_ui_breathe():
            original_name = self.name
            if plane_normal.length <= 1e-9:
                raise ValueError("Split plane normal cannot be zero")
            normalized_plane_normal = plane_normal.normalized()
            if allow_empty_sides and not self._has_mesh_geometry(self):
                self.remove()
                return None, None
            signed_bounds = [
                (
                    self.object.matrix_world @ mathutils.Vector(corner)
                    - plane_point
                ).dot(normalized_plane_normal)
                for corner in self.object.bound_box
            ]
            if allow_empty_sides:
                # Match the planner's existing one-sided no-op behavior, even
                # when a small part of the mesh overlaps the cut slab.
                if max(signed_bounds) <= -SPLIT_PLANE_CUT_HALF_THICKNESS:
                    return self, None
                if min(signed_bounds) >= SPLIT_PLANE_CUT_HALF_THICKNESS:
                    return None, self
                # A rotated bounding box can straddle a plane that misses its
                # mesh. A bulk vertex projection resolves this cheaply, without
                # triangulating, clipping polygons, or building temporary caps.
                import numpy as np

                coordinates = np.empty(
                    len(self.object.data.vertices) * 3, dtype=np.float32,
                )
                self.object.data.vertices.foreach_get("co", coordinates)
                local_normal = (
                    self.object.matrix_world.to_3x3().transposed()
                    @ normalized_plane_normal
                )
                origin_distance = (
                    self.object.matrix_world.translation - plane_point
                ).dot(normalized_plane_normal)
                distances = np.einsum(
                    "ij,j->i", coordinates.reshape(-1, 3),
                    np.asarray(local_normal, dtype=np.float32),
                ) + origin_distance
                if not np.all(np.isfinite(distances)):
                    raise ValueError("Split mesh contains non-finite coordinates")
                limit = SPLIT_PLANE_CUT_HALF_THICKNESS + 1.0e-6
                has_negative = float(distances.min()) < -limit
                has_positive = float(distances.max()) > limit
                if not has_negative and not has_positive:
                    self.remove()
                    return None, None
                if not has_negative:
                    return None, self
                if not has_positive:
                    return self, None
            elif (
                min(signed_bounds) >= -SPLIT_PLANE_CUT_HALF_THICKNESS
                or max(signed_bounds) <= SPLIT_PLANE_CUT_HALF_THICKNESS
            ):
                raise ValueError(
                    f"Split plane does not cross {original_name} beyond the "
                    f"{SPLIT_PLANE_CUT_THICKNESS:.3f}-unit cut slab"
                )
            cutter = self._create_split_plane_cutter(
                normalized_plane_normal,
                plane_point,
                SPLIT_PLANE_CUT_THICKNESS,
            )
            cutter.hide_during_ui_breathe = True
            self._breathe_with_hidden_object(cutter)
            try:
                boolean_started = time.perf_counter()
                self.apply_boolean_modifier(
                    diff_mod,
                    target=cutter,
                    retry_remesh=retry_remesh or build_sharp_modifier(8),
                    retry_remesh_on="self",
                )
                boolean_elapsed = time.perf_counter() - boolean_started
                self._breathe_with_hidden_object(cutter)
                if self.has_empty_boolean:
                    raise Exception("Boolean modifier without target failed")
                if allow_empty_sides and not self._has_mesh_geometry(self):
                    self.remove()
                    return None, None

                negative_side: list[Object] = []
                positive_side: list[Object] = []
                separate_started = time.perf_counter()
                isolated_parts = self.split_isolated_meshes()
                separate_elapsed = time.perf_counter() - separate_started
                self._breathe_with_hidden_object(cutter)
                classify_started = time.perf_counter()
                for part in isolated_parts:
                    if not self._has_mesh_geometry(part):
                        if part.object.name in bpy.data.objects:
                            part.remove()
                        continue

                    signed_distance = (
                        part.center_coords - plane_point
                    ).dot(normalized_plane_normal)
                    if signed_distance < 0:
                        negative_side.append(part)
                    else:
                        positive_side.append(part)

                classify_elapsed = time.perf_counter() - classify_started
                finish_started = time.perf_counter()
                finish_side = (
                    self._join_split_side
                    if preserve_isolated_meshes
                    else self._keep_largest_split_side
                )
                split_l = (
                    finish_side(negative_side, f"{original_name}_l")
                    if negative_side or not allow_empty_sides else None
                )
                split_r = (
                    finish_side(positive_side, f"{original_name}_r")
                    if positive_side or not allow_empty_sides else None
                )
                logger.debug(
                    "Split side timing: object=%s islands=%d boolean=%.3fs "
                    "separate=%.3fs classify=%.3fs finish=%.3fs",
                    original_name, len(isolated_parts), boolean_elapsed,
                    separate_elapsed, classify_elapsed,
                    time.perf_counter() - finish_started,
                )
                return split_l, split_r
            finally:
                cutter.remove()

    def join(self, other: Object):
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
        deselect_all_objects()
        self.object.select_set(True)
        other.object.select_set(True)
        bpy.context.view_layer.objects.active = self.object
        meshes = (self.object.data, other.object.data)
        bpy.ops.object.join()
        remove_unused_meshes(meshes)
        return self

    def apply_all_transforms(self):
        self.select()
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        return self

    def recalculate_normals(self):
        with BMeshObj(self, repair_winding=True):
            pass
        self.object.data.update()
        return self

    def clean_top(
        self, height: float, extra_extrussion: float = 0, *, strict_top: bool = False
    ) -> bool:
        """Cut and restore the top height; retain the original mesh on failure."""
        from .components.geometry_adapter import plan_reference_object_cutter_with_worker

        original_mesh = self.object.data
        original_name = original_mesh.name
        original_top = float(self.max_z)
        stage = "planning"
        logger.info("Clean top started: object=%s height=%.6f original_top=%.6f strict=%s",
                    self.name, height, original_top, strict_top)
        try:
            result = plan_reference_object_cutter_with_worker(
                self, "CLEAN_TOP", height=float(height), extra_extrusion=float(extra_extrussion),
            )
            cut_z = float(result["cut_z"])
            extrusion = float(result["extrusion_distance"])
            if extrusion <= 0:
                raise ValueError("Top cleanup requires a positive extrusion distance")
            # Retain the exact original datablock, including UVs and attributes.
            self.object.data = original_mesh.copy()
            stage = "cutting"
            with suppress_ui_breathe():
                cutter = self._cutter_from_worker_recipe(result["cutters"][0], "clean_top_cutter")
                cutter.hide_during_ui_breathe = True
                try:
                    self -= cutter
                finally:
                    cutter.remove()
            stage = "selecting cap"
            # Boolean cuts can shift the cap slightly through float rounding.
            # This tolerance identifies the cut cap; it does not move the cut.
            tolerance = max(0.001, abs(float(height)) * 1e-5)
            if strict_top:
                matrix = self.object.matrix_world
                normal_matrix = matrix.to_3x3().inverted().transposed()
                selected_indices = []
                for face in self.object.data.polygons:
                    normal = (normal_matrix @ face.normal).normalized()
                    if normal.z > 0.99 and all(
                        abs((matrix @ self.object.data.vertices[index].co).z - cut_z) <= tolerance
                        for index in face.vertices
                    ):
                        selected_indices.append(face.index)
                self._select_mesh_faces(selected_indices)
                selected_count = len(selected_indices)
            else:
                selected_count = self.select_limit_flat_faces(max_co=True)
            logger.info(
                "Clean top cap selection: object=%s cut_z=%.6f actual_top=%.6f "
                "selected_faces=%d tolerance=%.9f extrusion=%.6f strict=%s",
                self.name, cut_z, self.max_z, selected_count, tolerance, extrusion, strict_top,
            )
            if selected_count <= 0:
                raise ValueError("No cut cap faces selected; mandatory extrusion cannot run")
            stage = "extruding"
            before_vertices = len(self.object.data.vertices)
            self.extrude_selected(extrusion)
            stage = "verifying extrusion"
            actual_top = float(self.max_z)
            expected_top = cut_z + extrusion
            height_tolerance = max(abs(float(height)) * 4e-5, abs(expected_top) * 1e-6, 1e-4)
            added_vertices = len(self.object.data.vertices) - before_vertices
            logger.info(
                "Clean top extrusion result: object=%s added_vertices=%d "
                "expected_top=%.6f actual_top=%.6f tolerance=%.9f",
                self.name, added_vertices, expected_top, actual_top, height_tolerance,
            )
            if added_vertices <= 0 or abs(actual_top - expected_top) > height_tolerance:
                raise ValueError("Mandatory extrusion did not restore the expected top height")
            self.recalculate_normals()
        except Exception as exc:
            if self.object.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            failed_mesh = self.object.data
            self.object.data = original_mesh
            if failed_mesh is not original_mesh and failed_mesh.users == 0:
                bpy.data.meshes.remove(failed_mesh)
            logger.warning(
                "Clean top cancelled; original mesh restored: object=%s stage=%s "
                "original_top=%.6f restored_top=%.6f reason=%s",
                self.name, stage, original_top, self.max_z, exc,
            )
            return False
        if original_mesh.users == 0:
            bpy.data.meshes.remove(original_mesh)
            self.object.data.name = original_name
        logger.info("Clean top completed: object=%s selected_faces=%d extrusion=%.6f final_top=%.6f",
                    self.name, selected_count, extrusion, self.max_z)
        return True

    def clean_bot(
        self, height: float, custom_cut_point: Optional[mathutils.Vector] = None
    ):
        self.select()
        if custom_cut_point is not None:
            self.cut_plane(
                mathutils.Vector((0, 0, -1)),
                custom_cut_point,
            )
            extrusion_distance = -height
        else:
            from .components.geometry_adapter import (
                plan_reference_object_cutter_with_worker,
            )

            result = plan_reference_object_cutter_with_worker(
                self,
                "CLEAN_BOTTOM",
                height=float(height),
            )
            with suppress_ui_breathe():
                cutter = self._cutter_from_worker_recipe(
                    result["cutters"][0],
                    "clean_bottom_cutter",
                )
                cutter.hide_during_ui_breathe = True
                try:
                    self -= cutter
                finally:
                    cutter.remove()
            extrusion_distance = float(result["extrusion_distance"])
        selected_count = self.select_limit_flat_faces(max_co=False)
        if selected_count > 0:
            self.extrude_selected(extrusion_distance)
        self.recalculate_normals()

    def grid_obj(self, rows, columns, distance):
        selected_object = Object(bpy.context.active_object)
        selected_object.apply_modifier(
            build_array_modifier(rows, [0, distance + selected_object.depth, 0])
        )
        selected_object.apply_modifier(
            build_array_modifier(columns, [distance + selected_object.width, 0, 0])
        )

    @property
    def has_empty_boolean(self):
        """Check if the object has any boolean modifier without a target
        result of failed booleans"""
        for mod in self.object.modifiers:
            if mod.type == "BOOLEAN":
                try:
                    target = mod.target
                except AttributeError:
                    target = mod.object
                if not target:
                    self.object.modifiers.remove(mod)
                    return True
        return False

    def export_stl(
        self, path_folder=Path(".") / "data" / "mold_boxes", name_adder: str = ""
    ) -> str:
        path_str = str(path_folder / (self.name + name_adder + ".stl"))
        deselect_all_objects()
        self.select()
        bpy.ops.wm.stl_export(
            filepath=path_str,
            export_selected_objects=True,
        )
        return path_str

    def export_tmp_ply(self, dir: str):
        was_hidden = self.object.hide_get()
        was_hide_viewport = bool(getattr(self.object, "hide_viewport", False))
        was_hide_render = bool(getattr(self.object, "hide_render", False))
        try:
            self.object.hide_viewport = False
            self.object.hide_set(False)
            self.object.hide_render = False
            deselect_all_objects()
            self.select()

            filepath = f"{dir}/{self.name}.ply"

            bpy.ops.wm.ply_export(
                filepath=filepath,
                export_selected_objects=True,
                ascii_format=True,
                export_normals=True,
                export_uv=False,
                export_colors="NONE",
            )
        finally:
            self.object.hide_set(was_hidden)
            self.object.hide_viewport = was_hide_viewport
            self.object.hide_render = was_hide_render

    def shade_flat(self):
        deselect_all_objects()
        self.select()
        bpy.ops.object.shade_flat()
        mesh = getattr(self.object, "data", None)
        if mesh is None:
            return
        for polygon in mesh.polygons:
            polygon.use_smooth = False
        if hasattr(mesh, "use_auto_smooth"):
            mesh.use_auto_smooth = False
        if getattr(mesh, "has_custom_normals", False):
            try:
                bpy.ops.mesh.customdata_custom_splitnormals_clear()
            except Exception:
                pass
        mesh.update()
