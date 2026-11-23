from .source.login_resume import clear_pending_generation, require_generation_login
import mathutils  # type: ignore
import bpy  # type: ignore
import bmesh  # type: ignore
import json
import logging
import math
import struct
import sys
import tempfile
import time
from pathlib import Path
from bpy.app.handlers import persistent  # type: ignore
from bpy.props import (  # type: ignore
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    StringProperty,
)
from bpy_extras.io_utils import ImportHelper  # type: ignore

from .source.background_worker import BackgroundTaskSequence, finish_task_sync
from .source.components import preparation_settings

try:
    from moldboxer_silicone_native.source.components.export import (  # type: ignore  # noqa: F401
        begin_export,
        export,
    )
    from moldboxer_silicone_native.source.object import *
    from moldboxer_silicone_native.source.components.grip import *
    from moldboxer_silicone_native.source.components.mesh_envelope import *
    from moldboxer_silicone_native.source.components.geometry_adapter import (
        WorkerEnvelopeTest,
    )
    from moldboxer_silicone_native.source.components.filler_v2 import (
        build_all_fillers_async,
        build_all_fillers,
        confirm_filler,
        remove_fillers_by_type,
    )
    from moldboxer_silicone_native.source.components.master_air_traps import (
        DEFAULT_MASTER_AIR_TRAP_BRIDGE_OVERLAP,
        DEFAULT_MASTER_AIR_TRAP_BRIDGE_RADIUS,
        DEFAULT_MASTER_AIR_TRAP_MIN_AREA,
        DEFAULT_MASTER_AIR_TRAP_MINIMA_MERGE_HEIGHT,
        begin_build_master_air_trap_cylinders,
        build_master_air_trap_cylinders,
        confirm_master_air_trap_pillars,
        scene_has_master_air_trap_pillars,
    )
    from moldboxer_silicone_native.source.components.channels_deposit import *
    from moldboxer_silicone_native.source.components.silicone_mold import *
    from moldboxer_silicone_native.source.components.split_connector import (
        split_with_connector,
    )

    from moldboxer_silicone_native.source.components.casting_input import (
        CASTING_INPUT_AXIS,
        CASTING_INPUT_DIAMETER,
        CASTING_INPUT_HEIGHT,
        begin_confirm_casting_input,
        begin_create_casting_input,
        confirm_casting_input,
        create_casting_input,
    )
    from moldboxer_silicone_native.source.components.watermark_payload import (
        calculate_casting_volume,
    )
    from moldboxer_silicone_native.source.components.two_parts import (
        build_two_parts_box,
        confirm_two_parts,
        iter_build_two_parts_box_steps,
        iter_confirm_two_parts_steps,
    )
    from moldboxer_silicone_native.source.constants import *
    from moldboxer_silicone_native.source.components.extraction import *
    from moldboxer_silicone_native.source.components.clear_undercuts import (
        begin_clear_undercuts,
        bottom_reference_plane,
    )
    from moldboxer_silicone_native.source.components.clear_undercuts_overlay import (
        clear_extraction_direction_arrows,
        set_extraction_direction_overlay_visible,
    )
    from moldboxer_silicone_native.source.components.preprocess import *
    from moldboxer_silicone_native.source.devtools import (
        BatchTestSession,
        BatchTestsError,
        reload_addon_from_repo,
        _addon_module_name,
        _loaded_addon_module_name,
    )
    from moldboxer_silicone_native.source.mesh_decimation import (
        mesh_manifold_edge_counts,
    )
    from moldboxer_silicone_native.source.bambu_manifold import (
        check_stl_with_bambu,
        find_bambu_studio_executable,
    )
    from moldboxer_silicone_native.source.stl_diagnostics import (
        diagnose_binary_stl,
        format_stl_diagnostics_report,
    )
    from moldboxer_silicone_native.source.slicer_mesh_cleanup import (
        clean_generated_box_mesh,
        clean_mesh_for_slicer,
        cleanup_ui_refresh_callback,
        is_generated_box_name,
    )
    from moldboxer_silicone_native.source.bl_utils import (
        enable_moldboxer_movement_gizmos,
        ensure_moldboxer_background,
        import_model,
        reset_background_to_default,
        show_popup,
        configure_metric_millimeter_units,
        heal_active_patron,
        heal_active_patron_sharp,
        is_valid_utility_target,
        resolve_utility_target,
        MASTER_FILLER_BUILDING_KEY,
        sync_patron_selection_for_master_filler,
        draw_modal_progress_overlay,
        set_modal_progress_overlay_active,
    )
    from moldboxer_silicone_native.source.components.confirm_mold import (
        CONFIRM_SKIP_REDRAW_STEPS,
        confirm,
        create_clip_from_scene,
        iter_confirm_steps,
        place_clips_left_of_patron,
    )
    from moldboxer_silicone_native.source.components.slip_casting_confirm_mold import (
        confirm as confirm_slip_casting,
        iter_confirm_steps as iter_slip_casting_confirm_steps,
    )
    from moldboxer_silicone_native.source.components.slip_casting_cavity_filler import (
        SLIP_CASTING_VASE_BASE_KEY,
        SLIP_CASTING_VASE_BASE_NAME,
        SLIP_CASTING_VASE_BASE_ROLE_KEY,
        begin_detect_slip_casting_cores,
        restore_slip_casting_preparation_orientation,
        ensure_slip_casting_restart_master,
        begin_prepare_slip_casting_vase_with_cores,
        slip_casting_cavities_filled,
        slip_casting_has_prepared_parts,
        slip_casting_initial_stage_complete,
        slip_casting_vase_prepared,
    )
    from moldboxer_silicone_native.source.components.auto_flat import (
        auto_flat,
        build_tray,
        confirm_tray,
        iter_auto_flat_steps,
        iter_build_tray_steps,
        iter_confirm_tray_steps,
    )
    from moldboxer_silicone_native.source.components.box import (
        BOX_SKIP_REDRAW_STEPS,
        build_box_operator,
        build_slip_casting_box_operator,
        iter_build_box_operator_steps,
        iter_slip_casting_build_box_operator_steps,
    )
    from moldboxer_silicone_native.source.components.direct_mold import (
        apply_foundation,
        begin_apply_foundation,
        build_direct_automatic_mold,
        build_direct_mold,
        confirm_direct_mold,
        ensure_direct_patron_backup,
        iter_build_direct_automatic_mold_steps,
        iter_build_direct_mold_steps,
        iter_confirm_direct_mold_steps,
        remove_skin_master_half_preview,
        store_direct_undercut_paths,
        load_direct_undercut_paths,
    )
    from moldboxer_silicone_native.source.components.direct_split_planes import (
        begin_foundation_reference_guide,
        center_direct_split_planes,
        iter_direct_split_plane_objects,
        direct_split_plane_specs,
        foundation_reference_guide_active,
        foundation_reference_guide_available,
        foundation_reference_target_object,
        foundation_threshold_angle_degrees,
        remove_skin_base_reference_guide,
        reset_direct_split_planes,
        reset_direct_split_planes_to_defaults,
        preserve_direct_split_counts,
        set_direct_split_planes_overlay_visible,
        set_keep_silicone_split_planes_after_build,
        stored_silicone_split_plane_specs,
        sync_direct_split_planes_with_scene,
    )
    from moldboxer_silicone_native.source.components.funnel_reference_line import (
        set_reference_guides_overlay_visible,
        sync_funnel_reference_line,
    )
    from moldboxer_silicone_native.source.components.auth import (
        consume_trial_export,
        get_login_status_text,
        get_trial_exports_remaining,
        logout_user,
        start_google_device_login,
        start_patreon_device_login,
        start_pro_trial,
        is_free_trial_status,
    )
    from moldboxer_silicone_native.source.environment import get_addon_preferences
    from moldboxer_silicone_native.source.materials import (
        assign_generated_material,
        refresh_generated_object_materials,
        refresh_viewport_material_display,
    )
    from moldboxer_silicone_native.source.components.server import (
        AuthorizationError,
        ServerConnectionError,
    )
    from moldboxer_silicone_native.source.operator_access import (
        UPGRADE_LICENSE_URL,
        WEBSITE_URL,
        apply_lite_access_defaults,
        has_basic_server_access,
        has_export_access,
        has_active_server_access,
        has_pro_server_access,
        is_lite_tier,
        show_active_membership_required,
        show_basic_membership_required,
        show_export_license_required,
        show_pro_membership_required,
    )
    from moldboxer_silicone_native.source.extension_updates import (
        block_if_extension_update_available,
        get_extension_update_status,
        open_extension_updates,
    )
    from moldboxer_silicone_native.source.i18n import t
    from moldboxer_silicone_native.source.operator_logs import (
        begin_operator_log,
        end_operator_log,
        get_last_operator_log_path,
        read_last_operator_log,
    )
    from moldboxer_silicone_native.source.voxel_size import (
        get_box_voxel_size,
        get_master_voxel_size,
        get_undercuts_voxel_size,
    )
    from moldboxer_silicone_native.source.mesh_decimation import (
        begin_direct_undercuts_target_reduction,
        begin_fast_simplification_available,
        begin_create_fast_simplified_object,
        create_fast_simplified_object,
        get_adaptive_target_reduction,
        get_direct_undercuts_target_reduction,
    )
    from moldboxer_silicone_native.source.patron_lifecycle import (
        create_simplified_reference_for_operation,
        finalize_master_as_patron,
        prepare_decimated_patron_for_operation,
        prepare_imported_patron,
    )
    from moldboxer_silicone_native.source.patron_state import (
        DECIMATED_PATRON_KEY,
        IMPORTED_VOLUME_ML_KEY,
    )
    from moldboxer_silicone_native.source.model_orientation import (
        AUTO_ORIENT_MAX_TILT_DEGREES,
        auto_orient_imported_model,
        begin_auto_orient_imported_model,
        begin_orient_selected_faces_to_base,
        raycast_face,
        selected_edit_face_indices,
    )
    from moldboxer_silicone_native.source.progress import (
        breathe_viewport,
        force_viewport_redraw,
    )
    from moldboxer_silicone_native.source.nearest_surface_worker_client import (
        NearestSurfaceWorkerError,
    )
    from moldboxer_silicone_native.source.activity_tracking import (
        IMPORT_FILE_FORMAT_KEY,
        LINEAGE_SOURCE_EXPORT_ID_KEY,
        begin_operator_activity,
        record_model_exported,
        record_model_imported,
        record_operator_activity,
        restore_model_lineage,
    )
except ImportError:
    from .source.components.export import (  # type: ignore  # noqa: F401
        begin_export,
        export,
    )
    from .source.object import *
    from .source.components.grip import *
    from .source.components.mesh_envelope import *
    from .source.components.geometry_adapter import (
        WorkerEnvelopeTest,
    )
    from .source.components.filler_v2 import (
        build_all_fillers_async,
        build_all_fillers,
        confirm_filler,
        remove_fillers_by_type,
    )
    from .source.components.master_air_traps import (
        DEFAULT_MASTER_AIR_TRAP_BRIDGE_OVERLAP,
        DEFAULT_MASTER_AIR_TRAP_BRIDGE_RADIUS,
        DEFAULT_MASTER_AIR_TRAP_MIN_AREA,
        DEFAULT_MASTER_AIR_TRAP_MINIMA_MERGE_HEIGHT,
        begin_build_master_air_trap_cylinders,
        build_master_air_trap_cylinders,
        confirm_master_air_trap_pillars,
        scene_has_master_air_trap_pillars,
    )
    from .source.components.channels_deposit import *
    from .source.components.silicone_mold import *
    from .source.components.split_connector import split_with_connector

    from .source.components.casting_input import (
        CASTING_INPUT_AXIS,
        CASTING_INPUT_DIAMETER,
        CASTING_INPUT_HEIGHT,
        begin_confirm_casting_input,
        begin_create_casting_input,
        confirm_casting_input,
        create_casting_input,
    )
    from .source.components.watermark_payload import calculate_casting_volume
    from .source.components.two_parts import (
        build_two_parts_box,
        confirm_two_parts,
        iter_build_two_parts_box_steps,
        iter_confirm_two_parts_steps,
    )
    from .source.constants import *
    from .source.components.extraction import *
    from .source.components.clear_undercuts import (
        begin_clear_undercuts,
        bottom_reference_plane,
    )
    from .source.components.clear_undercuts_overlay import (
        clear_extraction_direction_arrows,
        set_extraction_direction_overlay_visible,
    )
    from .source.components.preprocess import *
    from .source.devtools import (
        BatchTestSession,
        BatchTestsError,
        reload_addon_from_repo,
        _addon_module_name,
        _loaded_addon_module_name,
    )
    from .source.mesh_decimation import (
        mesh_manifold_edge_counts,
    )
    from .source.bambu_manifold import (
        check_stl_with_bambu,
        find_bambu_studio_executable,
    )
    from .source.stl_diagnostics import (
        diagnose_binary_stl,
        format_stl_diagnostics_report,
    )
    from .source.slicer_mesh_cleanup import (
        clean_generated_box_mesh,
        clean_mesh_for_slicer,
        cleanup_ui_refresh_callback,
        is_generated_box_name,
    )
    from .source.bl_utils import (
        enable_moldboxer_movement_gizmos,
        ensure_moldboxer_background,
        import_model,
        reset_background_to_default,
        show_popup,
        configure_metric_millimeter_units,
        heal_active_patron,
        heal_active_patron_sharp,
        is_valid_utility_target,
        resolve_utility_target,
        MASTER_FILLER_BUILDING_KEY,
        sync_patron_selection_for_master_filler,
        draw_modal_progress_overlay,
        set_modal_progress_overlay_active,
    )
    from .source.components.confirm_mold import (
        CONFIRM_SKIP_REDRAW_STEPS,
        confirm,
        create_clip_from_scene,
        iter_confirm_steps,
        place_clips_left_of_patron,
    )
    from .source.components.slip_casting_confirm_mold import (
        confirm as confirm_slip_casting,
        iter_confirm_steps as iter_slip_casting_confirm_steps,
    )
    from .source.components.slip_casting_cavity_filler import (
        SLIP_CASTING_VASE_BASE_KEY,
        SLIP_CASTING_VASE_BASE_NAME,
        SLIP_CASTING_VASE_BASE_ROLE_KEY,
        begin_detect_slip_casting_cores,
        restore_slip_casting_preparation_orientation,
        ensure_slip_casting_restart_master,
        begin_prepare_slip_casting_vase_with_cores,
        slip_casting_cavities_filled,
        slip_casting_has_prepared_parts,
        slip_casting_initial_stage_complete,
        slip_casting_vase_prepared,
    )
    from .source.components.auto_flat import (
        auto_flat,
        build_tray,
        confirm_tray,
        iter_auto_flat_steps,
        iter_build_tray_steps,
        iter_confirm_tray_steps,
    )
    from .source.components.box import (
        BOX_SKIP_REDRAW_STEPS,
        build_box_operator,
        build_slip_casting_box_operator,
        iter_build_box_operator_steps,
        iter_slip_casting_build_box_operator_steps,
    )
    from .source.components.direct_mold import (
        apply_foundation,
        begin_apply_foundation,
        build_direct_automatic_mold,
        build_direct_mold,
        confirm_direct_mold,
        ensure_direct_patron_backup,
        iter_build_direct_automatic_mold_steps,
        iter_build_direct_mold_steps,
        iter_confirm_direct_mold_steps,
        remove_skin_master_half_preview,
        store_direct_undercut_paths,
        load_direct_undercut_paths,
    )
    from .source.components.direct_split_planes import (
        begin_foundation_reference_guide,
        center_direct_split_planes,
        iter_direct_split_plane_objects,
        direct_split_plane_specs,
        foundation_reference_guide_active,
        foundation_reference_guide_available,
        foundation_reference_target_object,
        foundation_threshold_angle_degrees,
        remove_skin_base_reference_guide,
        reset_direct_split_planes,
        reset_direct_split_planes_to_defaults,
        preserve_direct_split_counts,
        set_direct_split_planes_overlay_visible,
        set_keep_silicone_split_planes_after_build,
        stored_silicone_split_plane_specs,
        sync_direct_split_planes_with_scene,
    )
    from .source.components.funnel_reference_line import (
        set_reference_guides_overlay_visible,
        sync_funnel_reference_line,
    )
    from .source.components.auth import (
        consume_trial_export,
        get_login_status_text,
        get_trial_exports_remaining,
        logout_user,
        start_google_device_login,
        start_patreon_device_login,
        start_pro_trial,
        is_free_trial_status,
    )
    from .source.environment import get_addon_preferences
    from .source.materials import (
        assign_generated_material,
        refresh_generated_object_materials,
        refresh_viewport_material_display,
    )
    from .source.components.server import AuthorizationError, ServerConnectionError
    from .source.operator_access import (
        UPGRADE_LICENSE_URL,
        WEBSITE_URL,
        apply_lite_access_defaults,
        has_basic_server_access,
        has_export_access,
        has_active_server_access,
        has_pro_server_access,
        is_lite_tier,
        show_active_membership_required,
        show_basic_membership_required,
        show_export_license_required,
        show_pro_membership_required,
    )
    from .source.extension_updates import (
        block_if_extension_update_available,
        get_extension_update_status,
        open_extension_updates,
    )
    from .source.i18n import t
    from .source.operator_logs import (
        begin_operator_log,
        end_operator_log,
        get_last_operator_log_path,
        read_last_operator_log,
    )
    from .source.voxel_size import (
        get_box_voxel_size,
        get_master_voxel_size,
        get_undercuts_voxel_size,
    )
    from .source.mesh_decimation import (
        begin_direct_undercuts_target_reduction,
        begin_fast_simplification_available,
        begin_create_fast_simplified_object,
        create_fast_simplified_object,
        get_adaptive_target_reduction,
        get_direct_undercuts_target_reduction,
    )
    from .source.patron_lifecycle import (
        create_simplified_reference_for_operation,
        finalize_master_as_patron,
        prepare_decimated_patron_for_operation,
        prepare_imported_patron,
    )
    from .source.patron_state import DECIMATED_PATRON_KEY, IMPORTED_VOLUME_ML_KEY
    from .source.model_orientation import (
        AUTO_ORIENT_MAX_TILT_DEGREES,
        auto_orient_imported_model,
        begin_auto_orient_imported_model,
        begin_orient_selected_faces_to_base,
        raycast_face,
        selected_edit_face_indices,
    )
    from .source.progress import breathe_viewport, force_viewport_redraw
    from .source.nearest_surface_worker_client import NearestSurfaceWorkerError
    from .source.activity_tracking import (
        IMPORT_FILE_FORMAT_KEY,
        LINEAGE_SOURCE_EXPORT_ID_KEY,
        begin_operator_activity,
        record_model_exported,
        record_model_imported,
        record_operator_activity,
        restore_model_lineage,
    )

from .source.mold_types import (
    is_silicone_multipart_type,
    is_slip_casting_type,

    default_clamp_depth,
    get_mold_type,
    is_direct_mold_type,
    is_multipart_type,
    is_slip_casting_vase_type,
    mark_slip_casting_undercuts_cleared,
    slip_casting_undercuts_cleared,
    resolve_direct_mold_opening,
)
from .source.components.fixture import (
    iter_generate_fixture_steps,
    remove_fixture_height_guide,
    sync_fixture_height_guide,
)
from .source.components.protective_shell import (
    iter_generate_protective_shell_steps,
)

logger = logging.getLogger(__name__)
_UPDATE_WARNING_SHOWN = False
DIRECT_UNDERCUT_CLEARANCE_BUILD_OVERTRAVEL = 0.25
_SCALE_REFRESH_DELAY_SECONDS = 0.25
_SCALE_REFRESH_TOOL_IDS = {"builtin.scale", "builtin.scale_cage"}
_SCALE_REFRESH_SIGNATURES: dict[int, tuple[float, float, float]] = {}
_SCALE_REFRESH_PENDING_OBJECT_NAME = ""
_SCALE_REFRESH_LAST_CHANGE = 0.0
_SCALE_REFRESH_TIMER_PENDING = False


def reset_mold_metrics(context):
    context.scene.volume = 0
    context.scene.casting_volume_ml = 0


def select_canonical_patron(context):
    """Make patron the sole selected and active object after lifecycle work."""
    scene_objects = getattr(getattr(context, "scene", None), "objects", None)
    patron = scene_objects.get("patron") if scene_objects is not None else None
    if patron is None or patron.type != "MESH":
        return None
    patron.hide_select = False
    patron.hide_set(False)
    patron.hide_viewport = False
    Object(patron).select()
    return patron


def refresh_casting_volume(context):
    context.scene.casting_volume_ml = calculate_casting_volume()


def refresh_casting_volume_after_build_box(context):
    if not context.scene.pro_two_part_silicone:
        refresh_casting_volume(context)
        return

    casting_volume = 0.0
    for object_name in ("left", "right"):
        patron_part = bpy.data.objects.get(object_name)
        if patron_part is None:
            continue
        world_volume_scale = abs(
            patron_part.matrix_world.to_3x3().determinant()
        )
        casting_volume += Object(patron_part).volume * world_volume_scale
    context.scene.casting_volume_ml = casting_volume


def update_mold_metrics(context, silicone_volume: float):
    context.scene.volume = silicone_volume
    refresh_casting_volume(context)


SETTINGS_SCENE_PROPERTIES = (
    "box_gap",
    "fixture_fit_tolerance",
    "fixture_thickness",
    "fixture_shape_type",
    "slip_casting_shape_type",
    "slip_casting_box_faces",
    "silicone_multipart_opening",
    "fixture_box_quality",
    "protective_shell_fit_tolerance",
    "protective_shell_thickness",
    "protective_shell_shape_type",
    "protective_shell_box_quality",
    "fixture_base",
    "fixture_base_thickness",
    "fixture_base_span",
    "fixture_base_screw_holes",
    "fixture_base_screw_body_diameter",
    "fixture_base_screw_head_diameter",
    "fixture_base_screw_head_height",
    "silicone_density",
    "silicone_mix_part_a",
    "silicone_mix_part_b",
    "casting_material_preset",
    "casting_material_mode",
    "casting_material_density",
    "casting_material_part_a",
    "casting_material_part_b",
    "casting_material_powder_g",
    "casting_material_water_ml",
    "casting_material_yield_ml",
    "plaster_mix_volume_ml",
    "plaster_mix_water_ml",
    "plaster_mix_plaster_g",
    "slip_casting_funnel_type",
    "slip_casting_adapted_variant",
    "slip_casting_internal_model_type",
    "slip_casting_flat_region_inset",
    "slip_casting_internal_top_expansion",
    "slip_casting_rounded_bottom_diameter",
    "slip_casting_rounded_top_diameter",
    "slip_casting_rounded_extension",
    "slip_casting_rounded_detection_detail",
    "slip_casting_rounded_count_mode",
    "slip_casting_rounded_count",
    "slip_casting_funnel_span",
    "slip_casting_funnel_extension",
    "slip_casting_generate_base",
    "slip_casting_master_base_mode",
    "silicone_split_base_key_type",
    "silicone_split_base_key_diameter",
    "silicone_split_base_key_tolerance",
    "split_base_pin_diameter",
    "plaster_locking_tolerance",
    "plaster_locking_pin_type",
    "box_thickness",
    "direct_mold_thickness",
    "direct_split_x",
    "direct_split_y",
    "direct_split_z",
    "skin_thickness",
    "skin_base_reference_height",
    "direct_skin_core_generation_mode",
    "custom_face_head_height",
    "custom_face_head_width",
    "custom_face_head_depth",
    "custom_face_cheek_width",
    "custom_face_neck_circumference",
    "custom_face_neck_width",
    "custom_face_neck_length",
    "custom_face_neck_offset",
    "custom_face_neck_flare",
    "custom_face_comfort_clearance",
    "custom_face_ear_clearance",
    "custom_face_hair_allowance",
    "custom_face_forehead_width",
    "custom_face_jaw_width",
    "custom_face_chin_length",
    "custom_face_nose_length",
    "custom_face_nose_width",
    "custom_face_nose_height",
    "direct_skin_core_type",
    "direct_mold_opening",
    "direct_funnel_top_diameter",
    "direct_funnel_bottom_diameter",
    "direct_funnel_reference_height",
    "direct_funnel_depth",
    "direct_support_pilars",
    "direct_support_pilar_width",
    "direct_support_pilar_depth",
    "n_splits_xy",
    "n_splits_z",
    "funneler",
    "funneler_ref_height",
    "funneler_offset",
    "funneler_size_factor",
    "box_quality",
    "build_from_sphere",
    "clear_extraction",
    "undercuts_quality",
    "wing_width",
    "base_thickness",
    "base_type",
    "base_pin_type",
    "wing_join_patron",
    "master_base_pin",
    "master_base_pin_tolerance",
    "master_base_pin_height",
    "casting_feet",
    "casting_feet_height",
    "casting_feet_size_factor",
    "casting_grip",
    "casting_grip_width",
    "casting_grip_depth",
    "channels",
    "silicone_support_pilars",
    "channels_type",
    "channel_width",
    "channel_depth",
    "channel_end_shape",
    "horizontal_channels_count",
    "channels_contact_scale",
    "channel_adjustment",
    "channel_back_larger",
    "clamp_width",
    "clamp_depth",
    "clamp_tolerance",
    "clamp_pin_type",
    "clamp_pin_system_type",
    "clip_height",
    "clip_thickness",
    "clip_tolerance",
    "clip_closing_pressure",
    "clamp_screw_diameter",
    "flat_grip",
    "tray_type",
    "tray_casting_volume",
)


def reset_scene_properties_to_defaults(scene, prop_names):
    if scene is None:
        return

    from .source.mold_types import SLIP_CASTING_SETTINGS_DEFAULTS

    overrides = (
        {"box_gap": 4.5, "base_pin_type": "barrier",
         "slip_casting_master_base_mode": "ONE_PIECE", "channel_width": 8.0, "channel_end_shape": "CUBIC", "pro_casting_box": False}
        if is_silicone_multipart_type(getattr(scene, "mold_type_preview", ""))
        else SLIP_CASTING_SETTINGS_DEFAULTS
        if is_slip_casting_type(getattr(scene, "mold_type_preview", ""))
        else {}
    )
    previous_guard = bool(scene.get("_moldboxer_access_guard", False))
    scene["_moldboxer_access_guard"] = True
    try:
        for prop_name in prop_names:
            if not hasattr(scene, prop_name):
                continue

            if prop_name in overrides:
                setattr(scene, prop_name, overrides[prop_name])
                continue
            try:
                scene.property_unset(prop_name)
            except Exception:
                rna_prop = scene.bl_rna.properties.get(prop_name)
                if rna_prop is not None and hasattr(rna_prop, "default"):
                    setattr(scene, prop_name, rna_prop.default)
    finally:
        scene["_moldboxer_access_guard"] = previous_guard

    apply_lite_access_defaults(scene)


def maybe_show_update_warning() -> None:
    global _UPDATE_WARNING_SHOWN

    if _UPDATE_WARNING_SHOWN:
        return

    update_available, update_version = get_extension_update_status()
    if not update_available:
        return
    if _moldboxer_updater_available():
        # The independent updater checks automatically and owns the progress UI.
        return

    try:
        bpy.ops.silicone.update_available_dialog("INVOKE_DEFAULT")
    except Exception:
        version_suffix = f" ({update_version})" if update_version else ""
        show_popup(
            t(
                "Moldboxer update available{version_suffix}. Warning: Moldboxer may fail if not updated.",
                version_suffix=version_suffix,
            ),
            title=t("Update Available"),
        )
    _UPDATE_WARNING_SHOWN = True


def _moldboxer_updater_available() -> bool:
    """Return whether the separately installed updater owns its operator."""
    try:
        operator = bpy.ops.moldboxer_updater.install_update
        operator.get_rna_type()
        return True
    except (AttributeError, KeyError, RuntimeError):
        return False


class ModalProcessingOperator(bpy.types.Operator):
    requires_current_extension = False
    copy_operator_log_to_clipboard_on_finish = False
    modal_enabled = True
    modal_show_progress_overlay = False
    modal_log_redraw_timing = False
    modal_refresh_materials_on_redraw = True
    modal_wait_redraw_interval = 0.1
    modal_skip_redraw_steps = frozenset()
    modal_skip_before_redraw_steps = frozenset()
    _modal_timer = None
    _modal_draw_handler = None
    _modal_started_at = None
    _modal_has_run = False
    _modal_step_iterator = None
    _modal_step_iterator_initialized = False
    _modal_status_label = None
    _modal_pending_task = None
    _modal_pending_task_label = None
    _modal_last_wait_redraw_at = 0.0
    _modal_processing_active = False
    _operator_log_started = False
    _activity_snapshot = None
    _execution_depth = 0

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        execute_fn = cls.__dict__.get("execute")
        if execute_fn is None:
            return
        if getattr(execute_fn, "_modal_wrapped", False):
            return

        cls._execute_impl = execute_fn

        def wrapped_execute(self, context):
            top_level = ModalProcessingOperator._execution_depth == 0
            if top_level and not require_generation_login(self, context):
                return {"CANCELLED"}
            if (
                top_level
                and getattr(type(self), "requires_current_extension", False)
                and block_if_extension_update_available(context, self.report)
            ):
                return {"CANCELLED"}
            if top_level:
                self._begin_operator_log_capture()
                self._begin_activity_tracking(context)
                maybe_show_update_warning()
            self._ensure_scene_visuals(context)
            if (
                not getattr(type(self), "modal_enabled", True)
                or getattr(self, "_modal_processing_active", False)
                or ModalProcessingOperator._execution_depth > 0
            ):
                try:
                    result = cls._execute_impl(self, context)
                    return result
                except Exception as e:
                    result = self._handle_execute_exception(context, e)
                    return result
                finally:
                    if top_level:
                        self._record_activity(context, locals().get("result"))
                        self._end_operator_log_capture(locals().get("result"))
            result = self._start_modal(context)
            return result

        wrapped_execute._modal_wrapped = True
        cls.execute = wrapped_execute

    def _operator_log_id(self) -> str:
        return getattr(type(self), "bl_idname", type(self).__name__)

    def _operator_log_label(self) -> str:
        return getattr(type(self), "bl_label", type(self).__name__)

    def _begin_operator_log_capture(self) -> None:
        self._operator_log_started = begin_operator_log(
            self._operator_log_id(),
            self._operator_log_label(),
        )

    def _end_operator_log_capture(self, result=None) -> None:
        if not getattr(self, "_operator_log_started", False):
            return
        end_operator_log(
            self._operator_log_id(),
            self._operator_log_label(),
            result,
        )
        self._operator_log_started = False
        if getattr(
            type(self), "copy_operator_log_to_clipboard_on_finish", False
        ):
            log_text = read_last_operator_log()
            window_manager = getattr(bpy.context, "window_manager", None)
            if log_text and window_manager is not None:
                window_manager.clipboard = log_text

    def _begin_activity_tracking(self, context) -> None:
        self._activity_snapshot = begin_operator_activity(
            self._operator_log_id(),
            context,
        )

    def _record_activity(self, context, result=None) -> None:
        snapshot = getattr(self, "_activity_snapshot", None)
        self._activity_snapshot = None
        record_operator_activity(
            self._operator_log_id(),
            context,
            result,
            snapshot,
        )

    def _status_text(self):
        label = self._modal_status_label or getattr(type(self), "bl_label", "Operator")
        from .source.i18n import translate_progress_label
        label = translate_progress_label(label)
        elapsed = self._modal_elapsed_seconds()
        elapsed_text = f" ({elapsed:.1f}s)" if elapsed is not None else ""
        return t("Processing: {label}...", label=label) + elapsed_text

    def _set_processing_ui(self, context, active: bool):
        if context.window is not None:
            context.window.cursor_set("WAIT" if active else "DEFAULT")
        if getattr(type(self), "modal_show_progress_overlay", False):
            return
        workspace = getattr(context, "workspace", None)
        if workspace is not None:
            workspace.status_text_set(self._status_text() if active else None)

    def _ensure_scene_visuals(self, context):
        ensure_moldboxer_background(context)

    def _finish_modal(self, context):
        if self._modal_timer is not None:
            context.window_manager.event_timer_remove(self._modal_timer)
            self._modal_timer = None
        self._remove_progress_overlay()
        self._modal_started_at = None
        self._modal_step_iterator = None
        self._modal_step_iterator_initialized = False
        self._modal_status_label = None
        self._modal_pending_task = None
        self._modal_pending_task_label = None
        self._modal_last_wait_redraw_at = 0.0
        self._set_processing_ui(context, False)

    def _is_authorization_error(self, error: Exception) -> bool:
        if isinstance(error, AuthorizationError):
            return True
        message = str(error).lower()
        return (
            "unauthorized" in message
            or "access token" in message
            or "log in again" in message
        )

    def _is_server_connection_error(self, error: Exception) -> bool:
        if isinstance(error, ServerConnectionError):
            return True
        return bool(
            isinstance(error, NearestSurfaceWorkerError)
            and "serviceconnectionerror:" in str(error).casefold()
        )

    def _handle_authorization_error(self, context, error: Exception) -> None:
        self.report({"WARNING"}, str(error))
        show_active_membership_required(self)

    def _show_connection_error_dialog(self) -> None:
        try:
            bpy.ops.silicone.connection_error_dialog("INVOKE_DEFAULT")
        except Exception:
            show_popup(
                (
                    t("There was a connection error.")
                    + " "
                    + t("VPNs are known for creating connection issues.")
                    + " "
                    + t("If you are using a VPN, please disable it and restart.")
                ),
                title=t("Connection Error"),
            )

    def _handle_server_connection_error(self, error: Exception) -> None:
        self.report({"ERROR"}, t("Connection error"))
        logger.warning(
            "Server connection error",
            exc_info=(type(error), error, error.__traceback__),
        )
        self._show_connection_error_dialog()

    def _handle_execute_exception(self, context, error: Exception):
        if self._is_authorization_error(error):
            self._handle_authorization_error(context, error)
        elif self._is_server_connection_error(error):
            self._handle_server_connection_error(error)
        else:
            logger.exception("Operator failed during execution")
            self.report({"ERROR"}, str(error))
        return {"CANCELLED"}

    def _start_modal(self, context):
        self._modal_has_run = False
        self._modal_step_iterator = None
        self._modal_step_iterator_initialized = False
        self._modal_status_label = None
        self._modal_started_at = time.perf_counter()
        self._add_progress_overlay()
        self._set_processing_ui(context, True)
        self._modal_timer = context.window_manager.event_timer_add(
            0.01,
            window=context.window,
        )
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def _modal_elapsed_seconds(self):
        if self._modal_started_at is None:
            return None
        return time.perf_counter() - self._modal_started_at

    def _add_progress_overlay(self):
        if not getattr(type(self), "modal_show_progress_overlay", False):
            return
        if self._modal_draw_handler is not None:
            return
        self._modal_draw_handler = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_progress_overlay,
            (),
            "WINDOW",
            "POST_PIXEL",
        )
        set_modal_progress_overlay_active(True)

    def _remove_progress_overlay(self):
        if self._modal_draw_handler is None:
            return
        try:
            bpy.types.SpaceView3D.draw_handler_remove(
                self._modal_draw_handler,
                "WINDOW",
            )
        finally:
            self._modal_draw_handler = None
            set_modal_progress_overlay_active(False)

    def _draw_progress_overlay(self):
        elapsed = self._modal_elapsed_seconds()
        if elapsed is None:
            return

        label = self._modal_status_label or getattr(type(self), "bl_label", "Operator")
        from .source.i18n import translate_progress_label
        label = translate_progress_label(label)
        region = getattr(bpy.context, "region", None)
        draw_modal_progress_overlay(label, elapsed, region)

    def _get_modal_step_iterator(self, context):
        if self._modal_step_iterator_initialized:
            return self._modal_step_iterator
        self._modal_step_iterator_initialized = True
        step_factory = getattr(self, "_create_modal_step_iterator", None)
        if step_factory is None:
            return None
        self._modal_step_iterator = iter(step_factory(context))
        return self._modal_step_iterator

    def _is_modal_wait_task(self, value) -> bool:
        return (
            value is not None
            and callable(getattr(value, "done", None))
            and callable(getattr(value, "finish", None))
        )

    def _redraw_waiting_ui(self, context) -> None:
        now = time.perf_counter()
        pending_interval = getattr(
            getattr(self, "_modal_pending_task", None),
            "redraw_interval",
            None,
        )
        redraw_interval = (
            float(pending_interval)
            if pending_interval is not None
            else float(getattr(type(self), "modal_wait_redraw_interval", 0.25))
        )
        if now - self._modal_last_wait_redraw_at < redraw_interval:
            return
        self._modal_last_wait_redraw_at = now
        force_viewport_redraw(context)
        self._log_modal_redraw_timing("waiting")

    def _run_pending_modal_task(self, context):
        pending_task = self._modal_pending_task
        if pending_task is None:
            return None

        self._modal_status_label = self._modal_pending_task_label
        self._set_processing_ui(context, True)
        self._redraw_waiting_ui(context)
        if not pending_task.done():
            return {"RUNNING_MODAL"}

        try:
            pending_task.finish()
        finally:
            self._modal_pending_task = None
            self._modal_pending_task_label = None
            self._modal_last_wait_redraw_at = 0.0
        self._redraw_after_materials(context)
        return {"RUNNING_MODAL"}

    def _run_modal_step_iterator(self, context, step_iterator):
        pending_result = self._run_pending_modal_task(context)
        if pending_result is not None:
            return pending_result

        try:
            step = next(step_iterator)
        except StopIteration as stop:
            result = stop.value or {"FINISHED"}
            self._finish_modal(context)
            self._record_activity(context, result)
            self._end_operator_log_capture(result)
            return result

        label = None
        callback = step
        if isinstance(step, tuple):
            label, callback = step

        self._modal_status_label = label
        self._set_processing_ui(context, True)
        skip_redraw = self._should_skip_modal_redraw(label)
        skip_before_redraw = self._should_skip_before_modal_redraw(label)
        if not skip_before_redraw:
            self._redraw_after_materials(context)
        if callback is not None:
            callback_result = callback()
            if self._is_modal_wait_task(callback_result):
                self._modal_pending_task = callback_result
                self._modal_pending_task_label = label
                self._modal_last_wait_redraw_at = 0.0
                self._redraw_waiting_ui(context)
                return {"RUNNING_MODAL"}
        if not skip_redraw:
            self._redraw_after_materials(context)
        return {"RUNNING_MODAL"}

    def _should_skip_modal_redraw(self, label) -> bool:
        return label in getattr(type(self), "modal_skip_redraw_steps", set())

    def _should_skip_before_modal_redraw(self, label) -> bool:
        return label in getattr(
            type(self),
            "modal_skip_before_redraw_steps",
            set(),
        )

    def _redraw_after_materials(self, context):
        if getattr(type(self), "modal_refresh_materials_on_redraw", True):
            refresh_generated_object_materials()
            refresh_viewport_material_display(context)
        force_viewport_redraw(context)
        self._log_modal_redraw_timing("step")

    def _log_modal_redraw_timing(self, phase: str) -> None:
        return

    def invoke(self, context, event):
        top_level = ModalProcessingOperator._execution_depth == 0
        if top_level and not require_generation_login(self, context):
            return {"CANCELLED"}
        if (
            top_level
            and getattr(type(self), "requires_current_extension", False)
            and block_if_extension_update_available(context, self.report)
        ):
            return {"CANCELLED"}
        if top_level:
            self._begin_operator_log_capture()
            self._begin_activity_tracking(context)
            maybe_show_update_warning()
        self._ensure_scene_visuals(context)
        if (
            not getattr(type(self), "modal_enabled", True)
            or ModalProcessingOperator._execution_depth > 0
        ):
            self._modal_processing_active = True
            ModalProcessingOperator._execution_depth += 1
            try:
                result = type(self)._execute_impl(self, context)
                return result
            except Exception as e:
                result = self._handle_execute_exception(context, e)
                return result
            finally:
                ModalProcessingOperator._execution_depth -= 1
                self._modal_processing_active = False
                if top_level:
                    self._record_activity(context, locals().get("result"))
                    self._end_operator_log_capture(locals().get("result"))
        return self._start_modal(context)

    def modal(self, context, event):
        if event.type == "ESC" and not self._modal_has_run:
            self._finish_modal(context)
            self._record_activity(context, {"CANCELLED"})
            self._end_operator_log_capture({"CANCELLED"})
            return {"CANCELLED"}

        if event.type != "TIMER":
            return {"RUNNING_MODAL"}

        step_iterator = self._get_modal_step_iterator(context)
        if step_iterator is not None:
            self._modal_has_run = True
            self._modal_processing_active = True
            ModalProcessingOperator._execution_depth += 1
            auth_error = None
            connection_error = None
            try:
                return self._run_modal_step_iterator(context, step_iterator)
            except Exception as e:
                if self._is_authorization_error(e):
                    auth_error = e
                elif self._is_server_connection_error(e):
                    connection_error = e
                else:
                    logger.exception("Operator failed during modal step")
                    self.report({"ERROR"}, str(e))
                result = {"CANCELLED"}
            finally:
                ModalProcessingOperator._execution_depth -= 1
                self._modal_processing_active = False
            self._finish_modal(context)
            if auth_error is not None:
                self._handle_authorization_error(context, auth_error)
            elif connection_error is not None:
                self._handle_server_connection_error(connection_error)
            self._record_activity(context, result)
            self._end_operator_log_capture(result)
            return result

        if self._modal_has_run:
            return {"RUNNING_MODAL"}

        self._modal_has_run = True
        self._modal_processing_active = True
        ModalProcessingOperator._execution_depth += 1
        auth_error = None
        connection_error = None
        try:
            result = type(self)._execute_impl(self, context)
        except Exception as e:
            if self._is_authorization_error(e):
                auth_error = e
            elif self._is_server_connection_error(e):
                connection_error = e
            else:
                logger.exception("Operator failed during modal processing")
                self.report({"ERROR"}, str(e))
            result = {"CANCELLED"}
        finally:
            ModalProcessingOperator._execution_depth -= 1
            self._modal_processing_active = False
            self._finish_modal(context)
        if auth_error is not None:
            self._handle_authorization_error(context, auth_error)
        elif connection_error is not None:
            self._handle_server_connection_error(connection_error)
        self._end_operator_log_capture(result)
        self._record_activity(context, result)
        return result


class SelectedFaceOperator(ModalProcessingOperator):
    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == "MESH"


class CenteredOperator(ModalProcessingOperator):
    def execute(self, context):
        cursor_to_origin(context)


class MoldboxerOperator(CenteredOperator):
    requires_current_extension = True

    def execute(self, context):
        return _prepare_moldboxer_operation(self, context)


def _prepare_moldboxer_operation(operator, context):
    cursor_to_origin(context)
    mold_type = get_mold_type(
        getattr(context.scene, "mold_type_preview", "")
    )
    if (
        mold_type.requires_pro
        or getattr(context.scene, "pro_two_part_silicone", False)
        or getattr(context.scene, "pro_inner_cavity", False)
    ) and not has_pro_server_access():
        show_pro_membership_required()
        return False
    if not has_active_server_access():
        show_active_membership_required(operator)
        return False
    return True


class SelectedObjectOperator(CenteredOperator):
    @classmethod
    def poll(cls, context):
        return context.object is not None

    def execute(self, context):
        super().execute(context)


class UtilityTargetOperator(SelectedObjectOperator):
    """Selected-object operator that never modifies viewport helper objects."""

    @classmethod
    def poll(cls, context):
        patron = getattr(context, "scene", None)
        patron = patron.objects.get("patron") if patron is not None else None
        return context.object is not None or patron is not None

    def execute(self, context):
        if resolve_utility_target(context) is None:
            message = t("Select a valid mesh object")
            self.report({"ERROR"}, message)
            show_popup(message, title=t("Invalid Selection"))
            return False
        super().execute(context)
        return True


class SelectedMoldboxerOperator(MoldboxerOperator):
    @classmethod
    def poll(cls, context):
        return _mold_operation_target(context) is not None

    def execute(self, context):
        return _prepare_selected_moldboxer_operation(self, context)


def _prepare_selected_moldboxer_operation(operator, context):
    join_multi_model_patrons(context)
    _select_scene_patron_for_mold_operation(context)
    if not _prepare_moldboxer_operation(operator, context):
        return False
    if (
        not is_multipart_type(context.scene.mold_type_preview)
        and not bool(context.scene.wing_join_patron)
    ):
        ensure_direct_patron_backup()
    preprocess_patron(center=False, check_manifold=False)
    configure_metric_millimeter_units()
    return True


def _mold_operation_target(context):
    scene = getattr(context, "scene", None)
    objects = getattr(scene, "objects", None)
    if objects is not None:
        for name in ("patron", "master"):
            target = objects.get(name)
            if target is not None and target.type == "MESH":
                return target
    return getattr(context, "object", None)


def _select_scene_patron_for_mold_operation(context):
    patron_target = _mold_operation_target(context)
    scene_objects = getattr(getattr(context, "scene", None), "objects", None)
    is_scene_patron = (
        scene_objects is not None
        and patron_target is not None
        and patron_target
        in (scene_objects.get("patron"), scene_objects.get("master"))
    )
    if is_scene_patron:
        Object(patron_target).select()
        logger.info(
            "Mold preprocessing target: name=%s source=scene patron",
            patron_target.name,
        )
    return patron_target


class HealPatron(UtilityTargetOperator):
    bl_idname = "silicone.heal_patron"
    bl_label = "Heal"
    bl_description = "Heal the object with an organic voxel or sharp remesh"
    bl_options = {"REGISTER", "UNDO"}

    heal_type: EnumProperty(  # type: ignore
        name="Type",
        description="Choose the remesh style used to heal the object",
        items=(
            ("ORGANIC", "Organic (Voxel)", "Voxel remesh for organic models"),
            ("SHARP", "Sharp", "Sharp remesh for hard-surface models"),
        ),
        default="ORGANIC",
    )
    heal_quality: EnumProperty(  # type: ignore
        name="Quality",
        description="Heal processing quality",
        items=(
            ("DRAFT", "Draft", "Lowest detail, fastest processing"),
            ("FAST", "Fast", "Low detail, fast processing"),
            ("MID", "Balanced", "Medium detail"),
            ("HIGH", "High Detail", "Slow but detailed"),
            ("VERY HIGH", "Very High Detail", "Very detailed"),
            ("ULTRA", "Ultra Detail", "Very detailed"),
            ("EXTREME", "Extreme Detail", "Maximum detail, slowest processing"),
        ),
        default="MID",
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        type_row = layout.row(align=True)
        type_row.prop(self, "heal_type", expand=True)
        layout.prop(self, "heal_quality")

    def execute(self, context):
        if not super().execute(context):
            return {"CANCELLED"}
        if self.heal_type == "SHARP":
            healed = heal_active_patron_sharp(
                context,
                quality=self.heal_quality,
            )
        else:
            healed = heal_active_patron(
                context,
                quality=self.heal_quality,
            )
        if not healed:
            self.report(
                {"INFO"},
                t("Skipping heal for decimated patron proxy."),
            )
        return {"FINISHED"}


def _mold_generation_operator(context):
    selected_type = get_mold_type(
        getattr(context.scene, "mold_type_preview", "")
    )
    operator_group, operator_name = selected_type.generate_operator.split(".", 1)
    return selected_type, getattr(getattr(bpy.ops, operator_group), operator_name)


class GenerateMold(bpy.types.Operator):
    bl_idname = "silicone.generate_mold"
    bl_label = "Generate Mold"
    bl_description = "Generate the currently selected mold type"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        try:
            _selected_type, operator = _mold_generation_operator(context)
            return operator.poll()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False

    def execute(self, context):
        if not require_generation_login(self, context):
            return {"CANCELLED"}
        if block_if_extension_update_available(context, self.report):
            return {"CANCELLED"}
        try:
            _selected_type, operator = _mold_generation_operator(context)
            return operator("INVOKE_DEFAULT")
        except (AttributeError, RuntimeError, TypeError, ValueError) as error:
            self.report(
                {"ERROR"},
                t("Could not generate the selected mold: {error}", error=error),
            )
            return {"CANCELLED"}


class AutoBox(SelectedMoldboxerOperator):
    bl_idname = "silicone.auto_box"
    bl_label = "Automatic Box"
    bl_description = "Auto Box"
    bl_options = {"REGISTER", "UNDO"}
    modal_show_progress_overlay = True
    modal_log_redraw_timing = True
    modal_skip_redraw_steps = frozenset(
        {
            *BOX_SKIP_REDRAW_STEPS,
            *CONFIRM_SKIP_REDRAW_STEPS,
        }
    )
    modal_skip_before_redraw_steps = frozenset(
        {
            "Generating box",
        }
    )

    def _can_auto_box(self, context):
        return _prepare_auto_box_operation(self, context)

    def _create_modal_step_iterator(self, context):
        return (yield from _iter_auto_box_generation_steps(self, context))

    def execute(self, context):
        if not self._can_auto_box(context):
            return {"CANCELLED"}

        if context.scene.pro_two_part_silicone:
            build_two_parts_box(context)
            confirm_two_parts(context)
            finalize_master_as_patron()
        else:
            build_box_operator(context)
            confirm(context)
            finalize_master_as_patron()
        enable_moldboxer_movement_gizmos(context)

        return {"FINISHED"}


def _prepare_auto_box_operation(operator, context):
    patron_target = _select_scene_patron_for_mold_operation(context)
    if not _prepare_selected_moldboxer_operation(operator, context):
        return False
    set_keep_silicone_split_planes_after_build(False, context.scene)
    apply_lite_access_defaults(context.scene)
    if not prepare_decimated_patron_for_operation(
        context=context,
        target=patron_target,
    ):
        operator.report({"ERROR"}, t("No mesh object available for mold generation."))
        return False
    if context.scene.pro_inner_cavity and not has_pro_server_access():
        context.scene.pro_inner_cavity = False
        show_pro_membership_required()
        return False
    return True


def _iter_auto_box_generation_steps(operator, context):
    if not _prepare_auto_box_operation(operator, context):
        return {"CANCELLED"}

    if context.scene.pro_two_part_silicone:
        yield from iter_build_two_parts_box_steps(context)
        yield from iter_confirm_two_parts_steps(context)
        yield "Finalizing patron", lambda: finalize_master_as_patron()
    else:
        yield from iter_build_box_operator_steps(context, async_server=True)
        yield from iter_confirm_steps(context, async_server=True)
        yield "Finalizing patron", lambda: finalize_master_as_patron()
    yield "Enabling movement gizmos", lambda: enable_moldboxer_movement_gizmos(
        context
    )
    return {"FINISHED"}


SLIP_CASTING_CHANNELS_DEPOSIT_PATH = "/slip-casting/channels-deposit/"
SLIP_CASTING_VASE_BASE_DIRECT_MOLD_KEY = (
    "moldboxer_slip_casting_vase_base_direct_open_mold"
)
SLIP_CASTING_VASE_BASE_DIRECT_MOLD_PREFIX = (
    "vase_base_direct_open_mold"
)


def _slip_casting_male_vase_bases(scene) -> list[Object]:
    return sorted(
        (
            Object(obj)
            for obj in scene.objects
            if obj.type == "MESH"
            and bool(obj.get(SLIP_CASTING_VASE_BASE_KEY, False))
            and str(obj.get(SLIP_CASTING_VASE_BASE_ROLE_KEY, "")).upper()
            == "MALE"
        ),
        key=lambda part: (
            part.name != SLIP_CASTING_VASE_BASE_NAME,
            part.name.lower(),
        ),
    )


def _prepare_slip_casting_vase_base_direct_mold(
    context, *, companion=None, split_specs_override=None,
    paths_override=None, boundary_override=None,
    output_key=SLIP_CASTING_VASE_BASE_DIRECT_MOLD_KEY,
    output_prefix=SLIP_CASTING_VASE_BASE_DIRECT_MOLD_PREFIX,
) -> dict:
    male_bases = [companion] if companion is not None else _slip_casting_male_vase_bases(context.scene)
    if not male_bases:
        raise RuntimeError(
            "Slip Casting Vase mold generation requires a prepared male base"
        )

    male_base = male_bases[0]
    split_specs = (split_specs_override if split_specs_override is not None
                   else stored_silicone_split_plane_specs(context.scene))
    easy_extraction = True
    master_paths = paths_override if paths_override is not None else load_direct_undercut_paths(
        male_base.object, split_specs,
        easy_extraction=easy_extraction, precise_cost=False,
        restrict_bottom_extraction=easy_extraction and len(split_specs) != 1,
    )
    if not master_paths:
        raise RuntimeError("Run Clear Undercuts before generating the base's Direct Open Base mold")
    if any(float(path["direction"][2]) != 0.0 for path in master_paths.values()):
        raise RuntimeError("Run Clear Undercuts again to calculate horizontal base extraction paths")
    boundary_specs = (boundary_override if boundary_override is not None else
                      ([] if len(split_specs) == 1 else [bottom_reference_plane(male_base)]))
    for extra_base in male_bases[1:]:
        male_base.join(extra_base)
    companion_name = companion.name if companion is not None else SLIP_CASTING_VASE_BASE_NAME
    male_base.name = companion_name
    companion_visibility = None
    if companion is not None:
        companion_visibility = dict(
            hidden=male_base.object.hide_get(),
            hide_viewport=bool(male_base.object.hide_viewport),
            hide_render=bool(male_base.object.hide_render),
            hide_select=bool(male_base.object.hide_select),
            selected=bool(male_base.object.select_get()),
        )
        male_base.object.hide_viewport = False
        male_base.object.hide_set(False)
        male_base.object.hide_select = False
    male_base.apply_all_transforms()

    view_layer = context.view_layer
    preserved = []
    for index, raw in enumerate(tuple(bpy.data.objects)):
        in_view_layer = view_layer.objects.get(raw.name) is raw
        preserved.append(
            {
                "object": raw,
                "name": raw.name,
                "hidden": raw.hide_get(view_layer=view_layer) if in_view_layer else True,
                "hide_viewport": bool(raw.hide_viewport),
                "hide_render": bool(raw.hide_render),
                "hide_select": bool(raw.hide_select),
                "selected": bool(raw.select_get(view_layer=view_layer)) if in_view_layer else False,
            }
        )
        if companion_visibility is not None and raw == male_base.object:
            preserved[-1].update(companion_visibility)
        raw.name = f"_slip_casting_preserved_{index:04d}"
        if in_view_layer:
            raw.select_set(False, view_layer=view_layer)
        if raw != male_base.object:
            if in_view_layer:
                raw.hide_set(True, view_layer=view_layer)
            raw.hide_viewport = True
            raw.hide_render = True

    male_base.name = "patron"
    male_base.object.hide_set(False)
    male_base.object.hide_viewport = False
    male_base.object.hide_render = False
    male_base.object.hide_select = False
    male_base.select()
    bpy.context.view_layer.update()

    scene = context.scene
    original_opening = getattr(scene, "direct_mold_opening", "base_open")
    scene.direct_mold_opening = "base_open"
    companion_layout_key = "_moldboxer_companion_open_base"
    original_companion_layout = scene.get(companion_layout_key, None)
    scene[companion_layout_key] = True
    return {
        "original_companion_layout": original_companion_layout,
        "male_base": male_base,
        "companion_name": companion_name,
        "output_key": output_key,
        "output_prefix": output_prefix,
        "undercut_paths": master_paths,
        "undercut_boundary_specs": boundary_specs,
        "preserved": preserved,
        "preserved_objects": {item["object"] for item in preserved},
        "original_opening": original_opening,
        "male_base_matrix": male_base.object.matrix_world.copy(),
        "split_plane_specs": split_specs,
        "finished": False,
    }


def _restore_slip_casting_objects_after_vase_base_mold(
    context,
    state: dict,
    *,
    keep_direct_outputs: bool,
) -> list[Object]:
    preserved_objects = state["preserved_objects"]
    new_objects = [
        raw for raw in tuple(bpy.data.objects) if raw not in preserved_objects
    ]
    direct_outputs: list[Object] = []
    mold_part_index = 0
    component_index = 0
    for raw in new_objects:
        if bpy.data.objects.get(raw.name) is not raw:
            continue
        if not keep_direct_outputs or raw.name == "backup":
            bpy.data.objects.remove(raw, do_unlink=True)
            continue
        if context.view_layer.objects.get(raw.name) is raw:
            raw.hide_set(False, view_layer=context.view_layer)
        raw.hide_viewport = False
        raw.hide_render = False
        raw.hide_select = False
        raw[state.get("output_key", SLIP_CASTING_VASE_BASE_DIRECT_MOLD_KEY)] = True
        if raw.type == "MESH" and raw.name.lower().startswith(
            ("box", "left_box", "right_box")
        ):
            mold_part_index += 1
            raw.name = (
                state.get("output_prefix", SLIP_CASTING_VASE_BASE_DIRECT_MOLD_PREFIX)
                if mold_part_index == 1
                else (
                    f"{state.get('output_prefix', SLIP_CASTING_VASE_BASE_DIRECT_MOLD_PREFIX)}_part_"
                    f"{mold_part_index:03d}"
                )
            )
        else:
            component_index += 1
            raw.name = (
                f"{state.get('output_prefix', SLIP_CASTING_VASE_BASE_DIRECT_MOLD_PREFIX)}_component_"
                f"{component_index:03d}"
            )
        direct_outputs.append(Object(raw))

    state["male_base"].name = (
        f"_slip_casting_male_base_restore_"
        f"{state['male_base'].object.as_pointer()}"
    )
    for item in state["preserved"]:
        raw = item["object"]
        try:
            if bpy.data.objects.get(raw.name) is not raw:
                continue
            raw.name = item["name"]
            in_view_layer = context.view_layer.objects.get(raw.name) is raw
            if in_view_layer:
                raw.hide_set(item["hidden"], view_layer=context.view_layer)
            raw.hide_viewport = item["hide_viewport"]
            raw.hide_render = item["hide_render"]
            raw.hide_select = item["hide_select"]
            if in_view_layer:
                raw.select_set(item["selected"], view_layer=context.view_layer)
        except ReferenceError:
            continue

    state["male_base"].name = state.get("companion_name", SLIP_CASTING_VASE_BASE_NAME)
    if not keep_direct_outputs:
        state["male_base"].object.matrix_world = state["male_base_matrix"]
    context.scene.direct_mold_opening = state["original_opening"]
    companion_layout_key = "_moldboxer_companion_open_base"
    if state.get("original_companion_layout") is None:
        if companion_layout_key in context.scene:
            del context.scene[companion_layout_key]
    else:
        context.scene[companion_layout_key] = state["original_companion_layout"]
    bpy.context.view_layer.update()
    force_viewport_redraw(context)
    return direct_outputs


def _space_slip_casting_vase_base_direct_mold(context, state, outputs) -> None:
    """Move the finished companion assembly beyond the visible slip-cast system."""
    assembly = [state["male_base"], *outputs]
    reference_parts = []
    for item in state["preserved"]:
        raw = item["object"]
        try:
            # Generation can consume preserved objects. Use only survivors,
            # just as the preceding restoration step does.
            if bpy.data.objects.get(raw.name) is not raw:
                continue
            if (
                raw != state["male_base"].object
                and raw.type == "MESH"
                and not item["hidden"]
                and not item["hide_viewport"]
            ):
                reference_parts.append(Object(raw))
        except ReferenceError:
            continue
    if not reference_parts:
        return
    assembly_min_y = min(part.min_y for part in assembly)
    reference_max_y = max(part.max_y for part in reference_parts)
    clearance = max(10.0, float(context.scene.clamp_depth))
    offset_y = max(0.0, reference_max_y + clearance - assembly_min_y)
    translation = mathutils.Matrix.Translation((0.0, offset_y, 0.0))
    # Preserve every component's relative placement in world coordinates.
    placements = [
        (part.object, translation @ part.object.matrix_world)
        for part in assembly
    ]
    for raw, matrix in placements:
        raw.matrix_world = matrix
    bpy.context.view_layer.update()


def _iter_build_slip_casting_foot_direct_mold_steps(
    context,
    *,
    async_server: bool = False,
):
    """Generate a separate Direct Open Base mold around the flipped male base."""

    if not is_slip_casting_vase_type(context.scene.mold_type_preview):
        return []
    if not _slip_casting_male_vase_bases(context.scene):
        return []
    if any(
        bool(obj.get(SLIP_CASTING_VASE_BASE_DIRECT_MOLD_KEY, False))
        for obj in context.scene.objects
    ):
        return []

    state = _prepare_slip_casting_vase_base_direct_mold(context)
    try:
        yield from iter_build_direct_automatic_mold_steps(
            context,
            async_server=async_server,
            split_plane_specs_override=state["split_plane_specs"],
            locked_extraction_paths_override=state["undercut_paths"],
            undercut_boundary_specs_override=state["undercut_boundary_specs"],
        )
        outputs = _restore_slip_casting_objects_after_vase_base_mold(
            context,
            state,
            keep_direct_outputs=True,
        )
        _space_slip_casting_vase_base_direct_mold(context, state, outputs)
        state["finished"] = True
        return outputs
    finally:
        if not state["finished"]:
            _restore_slip_casting_objects_after_vase_base_mold(
                context,
                state,
                keep_direct_outputs=False,
            )


def iter_build_slip_casting_vase_base_direct_mold_steps(context, *, async_server=False):
    """Generate all open-base companions at the end of mold generation."""
    if not is_slip_casting_vase_type(context.scene.mold_type_preview):
        return []
    outputs = yield from _iter_build_slip_casting_foot_direct_mold_steps(
        context, async_server=async_server)
    outputs = list(outputs or [])
    from .source.components.slip_casting_rounded import iter_build_rounded_funnel_mold_steps
    outputs.extend((yield from iter_build_rounded_funnel_mold_steps(
        context, async_server=async_server)))
    return outputs


def build_slip_casting_vase_base_direct_mold(context) -> list[Object]:
    steps = iter_build_slip_casting_vase_base_direct_mold_steps(context)
    while True:
        try:
            _label, step = next(steps)
        except StopIteration as completed:
            return completed.value or []
        finish_task_sync(step())


def _prepare_slip_casting_generation(operator, context):
    if is_silicone_multipart_type(context.scene.mold_type_preview):
        return _prepare_auto_box_operation(operator, context)
    if not slip_casting_initial_stage_complete(context.scene):
        operator.report({"WARNING"}, t("Run Prepare Casting before generating the mold."))
        return False
    if not _prepare_auto_box_operation(operator, context):
        return False
    from .source.components.slip_casting_rounded import capture_rounded_funnel_references
    ensure_slip_casting_restart_master(context)
    capture_rounded_funnel_references(context)
    if not slip_casting_has_prepared_parts(context.scene):
        # Preparation stays valid after deleting all optional parts.
        # Set the saved option directly without rotating the user's model.
        context.scene.slip_casting_generate_base = False
    return True


def _iter_slip_casting_auto_box_generation_steps(operator, context):
    if not _prepare_slip_casting_generation(operator, context):
        return {"CANCELLED"}
    undercuts_result = {}

    def remember_undercuts_result(result):
        undercuts_result["status"] = result
        return result

    if not is_silicone_multipart_type(context.scene.mold_type_preview):
        yield "Clearing undercuts", lambda: _begin_automatic_slip_casting_undercuts(
            operator, context
        ).then(remember_undercuts_result)
        if undercuts_result.get("status") != {"FINISHED"}:
            return {"CANCELLED"}
    yield from iter_slip_casting_build_box_operator_steps(
        context,
        async_server=True,
        channels_deposit_path=SLIP_CASTING_CHANNELS_DEPOSIT_PATH,
        channels_step_label="Generating funneler",
    )
    result = yield from iter_slip_casting_confirm_steps(context, async_server=True)
    if result == "DEBUG_GAP_PREVIEW":
        return {"FINISHED"}
    yield "Finalizing patron", lambda: finalize_master_as_patron()
    if is_slip_casting_vase_type(context.scene.mold_type_preview):
        yield from iter_build_slip_casting_vase_base_direct_mold_steps(
            context,
            async_server=True,
        )
    if not is_silicone_multipart_type(context.scene.mold_type_preview):
        yield "Preparing silicone mold settings", lambda: _enable_plaster_silicone_settings(context)
    yield "Enabling movement gizmos", lambda: enable_moldboxer_movement_gizmos(
        context
    )
    return {"FINISHED"}


def _enable_plaster_silicone_settings(context):
    if is_silicone_multipart_type(context.scene.mold_type_preview):
        return
    from .source.components.slip_casting_silicone import enable_plaster_silicone_settings
    enable_plaster_silicone_settings(context)


class GeneratePlasterSiliconeMolds(MoldboxerOperator):
    bl_idname = "silicone.generate_plaster_silicone_molds"
    bl_label = "Generate Silicone Mold"
    bl_description = "Replace the slip-cast system with adapted silicone mold boxes for each plaster part and base"
    bl_options = {"REGISTER", "UNDO"}
    modal_show_progress_overlay = True
    modal_refresh_materials_on_redraw = False

    @classmethod
    def poll(cls, context):
        return (is_slip_casting_type(context.scene.mold_type_preview)
                or context.scene.mold_type_preview == "ADAPTED_BOX") and any(
            obj.type == "MESH" and (obj.name == "plaster_mold" or
                                    obj.name.startswith("plaster_mold_part_"))
            for obj in context.scene.objects
        )

    def _create_modal_step_iterator(self, context):
        from .source.components.slip_casting_silicone import iter_convert_plaster

        if not _prepare_moldboxer_operation(self, context):
            return {"CANCELLED"}

        def orient(raw):
            raw.data.calc_loop_triangles()
            return BackgroundTaskSequence(_iter_import_orientation_steps(
                context, Object(raw), len(raw.data.loop_triangles)
            ))

        def prepare(raw):
            prepare_imported_patron(context, Object(raw))
            reset_direct_split_planes()

        yield from iter_convert_plaster(
            context, orient=orient, prepare=prepare,
            generate=lambda: _iter_auto_box_generation_steps(self, context),
        )
        yield "Updating materials", refresh_generated_object_materials
        return {"FINISHED"}

    def _finish_modal(self, context):
        iterator = self._modal_step_iterator
        if iterator is not None:
            iterator.close()
        super()._finish_modal(context)

    def execute(self, context):
        steps = self._create_modal_step_iterator(context)
        try:
            while True:
                try:
                    _label, step = next(steps)
                except StopIteration as result:
                    return result.value or {"FINISHED"}
                finish_task_sync(step())
        finally:
            steps.close()


class SlipCastingAutoBox(SelectedMoldboxerOperator):
    bl_idname = "silicone.slip_casting_auto_box"
    bl_label = "Automatic Slip Casting Mold"
    bl_description = "Generate a slip-casting mold system"
    bl_options = {"REGISTER", "UNDO"}
    modal_show_progress_overlay = True
    modal_log_redraw_timing = True
    modal_skip_redraw_steps = frozenset(
        {
            *BOX_SKIP_REDRAW_STEPS,
            *CONFIRM_SKIP_REDRAW_STEPS,
        }
    )
    modal_skip_before_redraw_steps = frozenset({"Generating box"})

    @classmethod
    def poll(cls, context):
        return (
            is_multipart_type(context.scene.mold_type_preview)
            and slip_casting_initial_stage_complete(context.scene)
            and super().poll(context)
        )

    def _can_generate(self, context):
        return _prepare_slip_casting_generation(self, context)

    def _create_modal_step_iterator(self, context):
        return (yield from _iter_slip_casting_auto_box_generation_steps(self, context))

    def execute(self, context):
        if not self._can_generate(context):
            return {"CANCELLED"}
        if not is_silicone_multipart_type(context.scene.mold_type_preview):
            result = finish_task_sync(_begin_automatic_slip_casting_undercuts(self, context))
            if result != {"FINISHED"}:
                return {"CANCELLED"}
        build_slip_casting_box_operator(
            context,
            channels_deposit_path=SLIP_CASTING_CHANNELS_DEPOSIT_PATH,
        )
        if confirm_slip_casting(context) == "DEBUG_GAP_PREVIEW":
            return {"FINISHED"}
        finalize_master_as_patron()
        if is_slip_casting_vase_type(context.scene.mold_type_preview):
            build_slip_casting_vase_base_direct_mold(context)
        _enable_plaster_silicone_settings(context)
        enable_moldboxer_movement_gizmos(context)
        return {"FINISHED"}


class Fixture(SelectedMoldboxerOperator):
    bl_idname = "silicone.generate_fixture"
    bl_label = "Generate Fixture"
    bl_description = "Generate the selected fixture shape around the model"
    bl_options = {"REGISTER", "UNDO"}
    modal_show_progress_overlay = True
    modal_refresh_materials_on_redraw = False
    modal_skip_before_redraw_steps = frozenset(
        {"Generating clearance wrapper", "Generating fixture body"}
    )

    @classmethod
    def poll(cls, context):
        return (
            get_mold_type(context.scene.mold_type_preview).identifier == "FIXTURE"
            and super().poll(context)
        )

    def _can_generate_fixture(self, context):
        return _prepare_fixture_operation(self, context)

    def _create_modal_step_iterator(self, context):
        return (yield from _iter_fixture_generation_steps(self, context))

    def execute(self, context):
        if not self._can_generate_fixture(context):
            return {"CANCELLED"}
        for _label, step in iter_generate_fixture_steps(
            context,
            target_object=self._fixture_target,
        ):
            finish_task_sync(step())
        return {"FINISHED"}


def _prepare_fixture_operation(self, context):
    join_multi_model_patrons(context)
    patron_target = _select_scene_patron_for_mold_operation(context)
    if patron_target is None or getattr(patron_target, "type", None) != "MESH":
        self.report(
            {"ERROR"},
            t("No mesh object available for fixture generation."),
        )
        return False
    Object(patron_target).select()
    if not MoldboxerOperator.execute(self, context):
        return False
    configure_metric_millimeter_units()
    self._fixture_target = patron_target
    return True


def _iter_fixture_generation_steps(operator, context):
    if not _prepare_fixture_operation(operator, context):
        return {"CANCELLED"}
    yield from iter_generate_fixture_steps(
        context,
        target_object=operator._fixture_target,
    )
    return {"FINISHED"}


class ProtectiveShell(SelectedMoldboxerOperator):
    bl_idname = "silicone.generate_protective_shell"
    bl_label = "Generate Protective Shell"
    bl_description = "Generate a split protective shell around the model"
    bl_options = {"REGISTER", "UNDO"}
    modal_show_progress_overlay = True
    modal_refresh_materials_on_redraw = False
    modal_skip_before_redraw_steps = frozenset(
        {
            "Generating Protective Shell clearance wrapper",
            "Generating Protective Shell body",
        }
    )

    @classmethod
    def poll(cls, context):
        return (
            get_mold_type(context.scene.mold_type_preview).identifier
            == "PROTECTIVE_SHELL"
            and super().poll(context)
        )

    def _can_generate_protective_shell(self, context):
        return _prepare_protective_shell_operation(self, context)

    def _create_modal_step_iterator(self, context):
        return (yield from _iter_protective_shell_generation_steps(self, context))

    def execute(self, context):
        if not self._can_generate_protective_shell(context):
            return {"CANCELLED"}
        for _label, step in iter_generate_protective_shell_steps(
            context,
            target_object=self._protective_shell_target,
            async_server=False,
        ):
            finish_task_sync(step())
        return {"FINISHED"}


def _prepare_protective_shell_operation(operator, context):
    join_multi_model_patrons(context)
    patron_target = _select_scene_patron_for_mold_operation(context)
    if (
        patron_target is None
        or getattr(patron_target, "type", None) != "MESH"
    ):
        operator.report(
            {"ERROR"},
            t("No mesh object available for Protective Shell generation."),
        )
        return False
    Object(patron_target).select()
    if not MoldboxerOperator.execute(operator, context):
        return False
    configure_metric_millimeter_units()
    operator._protective_shell_target = patron_target
    return True


def _iter_protective_shell_generation_steps(operator, context):
    if not _prepare_protective_shell_operation(operator, context):
        return {"CANCELLED"}
    yield from iter_generate_protective_shell_steps(
        context,
        target_object=operator._protective_shell_target,
        async_server=True,
    )
    return {"FINISHED"}


class FlatAutoBox(SelectedMoldboxerOperator):
    bl_idname = "silicone.flat_auto_box"
    bl_label = "Automatic Tray"
    bl_description = "Automatic Tray"
    bl_options = {"REGISTER", "UNDO"}
    modal_show_progress_overlay = True
    modal_skip_before_redraw_steps = frozenset(
        {"Generating tray box", "Clearing undercuts and air traps"}
    )

    def _can_flat_auto_box(self, context):
        return _prepare_flat_auto_box_operation(self, context)

    def _create_modal_step_iterator(self, context):
        return (yield from _iter_flat_auto_box_generation_steps(self, context))

    def _refresh_flat_auto_box_display(self, context):
        refresh_generated_object_materials()
        refresh_viewport_material_display(context)

    def execute(self, context):
        if not self._can_flat_auto_box(context):
            return {"CANCELLED"}
        auto_flat(context)
        self._refresh_flat_auto_box_display(context)
        return {"FINISHED"}


def _prepare_flat_auto_box_operation(operator, context):
    if not _prepare_selected_moldboxer_operation(operator, context):
        return False
    apply_lite_access_defaults(context.scene)
    return True


def _refresh_flat_auto_box_display(context):
    refresh_generated_object_materials()
    refresh_viewport_material_display(context)


def _iter_flat_auto_box_generation_steps(operator, context):
    if not _prepare_flat_auto_box_operation(operator, context):
        return {"CANCELLED"}
    yield from iter_auto_flat_steps(context)
    yield "Refreshing display", lambda: _refresh_flat_auto_box_display(context)
    return {"FINISHED"}


class BuildTray(SelectedMoldboxerOperator):
    bl_idname = "silicone.build_tray"
    bl_label = "Build Tray"
    bl_description = (
        "Build the tray and leave its grip separate for editing and custom "
        "watermark placement before confirmation"
    )
    bl_options = {"REGISTER", "UNDO"}
    modal_show_progress_overlay = True
    modal_skip_before_redraw_steps = frozenset(
        {"Generating tray box", "Clearing undercuts and air traps"}
    )

    @classmethod
    def poll(cls, context):
        return (
            get_mold_type(context.scene.mold_type_preview).identifier
            == "TRAY_MOLD"
            and super().poll(context)
        )

    def _can_build_tray(self, context):
        if not super().execute(context):
            return False
        apply_lite_access_defaults(context.scene)
        return True

    def _create_modal_step_iterator(self, context):
        if not self._can_build_tray(context):
            return {"CANCELLED"}
        yield from iter_build_tray_steps(context)
        return {"FINISHED"}

    def execute(self, context):
        if not self._can_build_tray(context):
            return {"CANCELLED"}
        build_tray(context)
        return {"FINISHED"}


class ConfirmTray(MoldboxerOperator):
    bl_idname = "silicone.confirm_tray"
    bl_label = "Confirm"
    bl_description = (
        "Merge the edited tray grip and finish the tray mold system"
    )
    bl_options = {"REGISTER", "UNDO"}
    modal_show_progress_overlay = True

    @classmethod
    def poll(cls, context):
        return (
            get_mold_type(context.scene.mold_type_preview).identifier
            == "TRAY_MOLD"
            and context.scene.objects.get("box") is not None
        )

    def _can_confirm_tray(self, context):
        if not super().execute(context):
            return False
        apply_lite_access_defaults(context.scene)
        return True

    def _create_modal_step_iterator(self, context):
        if not self._can_confirm_tray(context):
            return {"CANCELLED"}
        yield from iter_confirm_tray_steps(context)
        return {"FINISHED"}

    def execute(self, context):
        if not self._can_confirm_tray(context):
            return {"CANCELLED"}
        confirm_tray(context)
        return {"FINISHED"}


class AutomaticMold(SelectedMoldboxerOperator):
    bl_idname = "silicone.automatic_mold"
    bl_label = "Automatic Mold"
    bl_description = "Automatic Mold"
    bl_options = {"REGISTER", "UNDO"}
    modal_show_progress_overlay = True
    modal_log_redraw_timing = True
    # Direct-mold imports assign their generated material as each object is
    # imported, while Boolean operations only need a viewport redraw. Avoid a
    # full material rescan before and after every direct-mold step.
    modal_refresh_materials_on_redraw = False
    modal_skip_redraw_steps = BOX_SKIP_REDRAW_STEPS
    modal_skip_before_redraw_steps = frozenset({"Generating box"})

    @classmethod
    def poll(cls, context):
        patron = context.scene.objects.get("patron")
        return (
            patron is not None and patron.type == "MESH"
        ) or context.object is not None

    def _can_build_automatic_mold(self, context):
        return _prepare_automatic_mold_operation(self, context)

    def _create_modal_step_iterator(self, context):
        if not self._can_build_automatic_mold(context):
            return {"CANCELLED"}
        skin_core_only = yield from iter_build_direct_automatic_mold_steps(
            context,
            async_server=True,
        )
        if not skin_core_only:
            yield "Updating casting volume", lambda: refresh_casting_volume(context)
        return {"FINISHED"}

    def execute(self, context):
        if not self._can_build_automatic_mold(context):
            return {"CANCELLED"}
        skin_core_only = build_direct_automatic_mold(context)
        if not skin_core_only:
            refresh_casting_volume(context)
        return {"FINISHED"}


def _prepare_automatic_mold_operation(operator, context):
    join_multi_model_patrons(context)
    patron = context.scene.objects.get("patron")
    if patron is not None and patron.type == "MESH":
        ensure_direct_patron_backup()
        Object(patron).select()
        logger.info(
            "Automatic Mold preprocessing target: name=%s source=scene patron",
            patron.name,
        )
    elif context.object is not None:
        logger.info(
            "Automatic Mold preprocessing target: name=%s source=active object",
            context.object.name,
        )
    return _prepare_selected_moldboxer_operation(operator, context)


def _iter_automatic_mold_generation_steps(operator, context):
    if not _prepare_automatic_mold_operation(operator, context):
        return {"CANCELLED"}
    skin_core_only = yield from iter_build_direct_automatic_mold_steps(
        context,
        async_server=True,
    )
    if not skin_core_only:
        yield "Updating casting volume", lambda: refresh_casting_volume(context)
    return {"FINISHED"}


_MOLD_GENERATION_STEP_FACTORIES = {
    "silicone.auto_box": _iter_auto_box_generation_steps,
    "silicone.slip_casting_auto_box": _iter_slip_casting_auto_box_generation_steps,
    "silicone.flat_auto_box": _iter_flat_auto_box_generation_steps,
    "silicone.automatic_mold": _iter_automatic_mold_generation_steps,
    "silicone.generate_fixture": _iter_fixture_generation_steps,
    "silicone.generate_protective_shell": _iter_protective_shell_generation_steps,
}

_MOLD_GENERATION_OPERATOR_CLASSES = {
    "silicone.auto_box": AutoBox,
    "silicone.slip_casting_auto_box": SlipCastingAutoBox,
    "silicone.flat_auto_box": FlatAutoBox,
    "silicone.automatic_mold": AutomaticMold,
    "silicone.generate_fixture": Fixture,
    "silicone.generate_protective_shell": ProtectiveShell,
}


def _iter_selected_mold_generation_steps(operator, context, mold_type):
    try:
        step_factory = _MOLD_GENERATION_STEP_FACTORIES[mold_type.generate_operator]
    except KeyError as exc:
        raise RuntimeError(
            f"Unsupported batch mold generator: {mold_type.generate_operator}"
        ) from exc
    return (yield from step_factory(operator, context))


class BuildDirectMold(SelectedMoldboxerOperator):
    bl_idname = "silicone.build_direct_mold"
    bl_label = "Build"
    bl_description = (
        "Build the Direct mold box and leave its pillars and funnels separate "
        "for editing and custom watermark placement before confirmation"
    )
    bl_options = {"REGISTER", "UNDO"}
    modal_show_progress_overlay = True
    modal_log_redraw_timing = True
    modal_refresh_materials_on_redraw = False
    modal_skip_redraw_steps = BOX_SKIP_REDRAW_STEPS
    modal_skip_before_redraw_steps = frozenset({"Generating box"})

    @classmethod
    def poll(cls, context):
        patron = context.scene.objects.get("patron")
        return (
            patron is not None and patron.type == "MESH"
        ) or context.object is not None

    def _can_build_automatic_mold(self, context):
        join_multi_model_patrons(context)
        patron = context.scene.objects.get("patron")
        if patron is not None and patron.type == "MESH":
            ensure_direct_patron_backup()
            Object(patron).select()
            logger.info(
                "Direct mold Build preprocessing target: name=%s "
                "source=scene patron",
                patron.name,
            )
        elif context.object is not None:
            logger.info(
                "Direct mold Build preprocessing target: name=%s "
                "source=active object",
                context.object.name,
            )
        return super().execute(context)

    def _create_modal_step_iterator(self, context):
        if not self._can_build_automatic_mold(context):
            return {"CANCELLED"}
        yield from iter_build_direct_mold_steps(
            context,
            async_server=True,
        )
        yield "Updating casting volume", lambda: refresh_casting_volume(context)
        return {"FINISHED"}

    def execute(self, context):
        if not self._can_build_automatic_mold(context):
            return {"CANCELLED"}
        build_direct_mold(context)
        refresh_casting_volume(context)
        return {"FINISHED"}


class ConfirmDirectMold(MoldboxerOperator):
    bl_idname = "silicone.confirm_direct_mold"
    bl_label = "Confirm"
    bl_description = (
        "Merge the edited Direct mold pillars and funnels, then finish the "
        "printable mold system"
    )
    bl_options = {"REGISTER", "UNDO"}
    modal_show_progress_overlay = True
    modal_log_redraw_timing = True
    modal_refresh_materials_on_redraw = False
    modal_skip_redraw_steps = BOX_SKIP_REDRAW_STEPS

    @classmethod
    def poll(cls, context):
        box = context.scene.objects.get("box")
        return (
            get_mold_type(
                getattr(context.scene, "mold_type_preview", "")
            ).generate_operator
            == "silicone.automatic_mold"
            and box is not None
            and box.type == "MESH"
        )

    def _can_confirm_direct_mold(self, context):
        return bool(super().execute(context))

    def _create_modal_step_iterator(self, context):
        if not self._can_confirm_direct_mold(context):
            return {"CANCELLED"}
        yield from iter_confirm_direct_mold_steps(
            context,
            async_server=True,
        )
        yield "Updating casting volume", lambda: refresh_casting_volume(context)
        return {"FINISHED"}

    def execute(self, context):
        if not self._can_confirm_direct_mold(context):
            return {"CANCELLED"}
        confirm_direct_mold(context)
        refresh_casting_volume(context)
        return {"FINISHED"}


class CenterObj(UtilityTargetOperator):
    bl_idname = "silicone.center_obj"
    bl_label = "Center"
    bl_description = "Center the selected object to the world origin"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if not super().execute(context):
            return {"CANCELLED"}
        bpy.ops.object.origin_set(type="GEOMETRY_ORIGIN", center="BOUNDS")
        for obj_ in context.selected_objects:
            wrapped_obj = Object(obj_)
            obj_.location.x = 0
            obj_.location.y = 0
            obj_.location.z -= wrapped_obj.min_z
        return {"FINISHED"}


class _BuildBoxBehavior:
    requires_current_extension = True
    bl_idname = "silicone.build_box"
    bl_label = "Build Box"
    bl_description = (
        "Generate the raw mold system components for custom setup and "
        "placement. This step only creates the initial components. Use "
        "'Confirm' to finish the mold generation"
    )
    bl_options = {"REGISTER", "UNDO"}
    modal_show_progress_overlay = True
    modal_skip_redraw_steps = frozenset(BOX_SKIP_REDRAW_STEPS)
    modal_skip_before_redraw_steps = frozenset(
        {
            "Generating box",
        }
    )

    @classmethod
    def poll(cls, context):
        return _mold_operation_target(context) is not None

    def _can_build_box(self, context):
        join_multi_model_patrons(context)
        patron_target = _select_scene_patron_for_mold_operation(context)
        super().execute(context)
        if not has_active_server_access():
            show_active_membership_required(self)
            return False
        if not has_basic_server_access():
            show_basic_membership_required()
            return False
        set_keep_silicone_split_planes_after_build(
            not context.scene.pro_two_part_silicone,
            context.scene,
        )
        if not prepare_decimated_patron_for_operation(
            context=context,
            target=patron_target,
        ):
            self.report({"ERROR"}, t("No mesh object available for mold generation."))
            return False
        return True

    def _create_modal_step_iterator(self, context):
        if not self._can_build_box(context):
            return {"CANCELLED"}
        if context.scene.pro_two_part_silicone:
            yield from iter_build_two_parts_box_steps(context)
        else:
            yield from iter_build_box_operator_steps(context, async_server=True)
        yield "Updating casting volume", lambda: (
            refresh_casting_volume_after_build_box(context)
        )
        return {"FINISHED"}

    def execute(self, context):
        if not self._can_build_box(context):
            return {"CANCELLED"}
        if context.scene.pro_two_part_silicone:
            build_two_parts_box(context)
        else:
            build_box_operator(context)
        refresh_casting_volume_after_build_box(context)

        return {"FINISHED"}


class BuildBox(_BuildBoxBehavior, SelectedObjectOperator):
    pass


class _ConfirmBehavior:
    bl_idname = "silicone.confirm"
    bl_label = "Confirm"
    bl_description = "Confirm"
    bl_options = {"REGISTER", "UNDO"}
    modal_show_progress_overlay = True
    modal_log_redraw_timing = True
    modal_skip_redraw_steps = frozenset(CONFIRM_SKIP_REDRAW_STEPS)
    modal_skip_before_redraw_steps = frozenset()

    def _can_confirm(self, context):
        if not super().execute(context):
            return False
        if not has_basic_server_access():
            show_basic_membership_required()
            return False
        if context.scene.pro_inner_cavity and not has_pro_server_access():
            context.scene.pro_inner_cavity = False
            show_pro_membership_required()
            return False
        return True

    def _create_modal_step_iterator(self, context):
        if not self._can_confirm(context):
            return {"CANCELLED"}

        if context.scene.pro_two_part_silicone:
            yield from iter_confirm_two_parts_steps(context)
        else:
            yield from iter_confirm_steps(context, async_server=True)
        yield "Finalizing patron", lambda: finalize_master_as_patron()
        yield "Enabling movement gizmos", lambda: enable_moldboxer_movement_gizmos(
            context
        )
        return {"FINISHED"}

    def execute(self, context):
        if not self._can_confirm(context):
            return {"CANCELLED"}
        if context.scene.pro_two_part_silicone:
            confirm_two_parts(context)
            finalize_master_as_patron()
        else:
            confirm(context)
            finalize_master_as_patron()
        enable_moldboxer_movement_gizmos(context)
        return {"FINISHED"}


class Confirm(_ConfirmBehavior, MoldboxerOperator):
    pass


class BuildSlipCastingBox(_BuildBoxBehavior, SelectedObjectOperator):
    bl_idname = "silicone.build_slip_casting_box"
    bl_label = "Build Box"
    bl_description = (
        "Build the editable slip-casting mold box before its dedicated "
        "confirmation stage"
    )

    @classmethod
    def poll(cls, context):
        return (
            is_multipart_type(context.scene.mold_type_preview)
            and slip_casting_initial_stage_complete(context.scene)
            and super().poll(context)
        )

    def _can_build_box(self, context):
        if not has_pro_server_access():
            show_pro_membership_required()
            return False
        return super()._can_build_box(context)

    def _create_modal_step_iterator(self, context):
        if not self._can_build_box(context):
            return {"CANCELLED"}
        yield from iter_slip_casting_build_box_operator_steps(
            context,
            async_server=True,
            channels_deposit_path=SLIP_CASTING_CHANNELS_DEPOSIT_PATH,
            channels_step_label="Generating funneler",
        )
        yield "Updating casting volume", lambda: (
            refresh_casting_volume_after_build_box(context)
        )
        return {"FINISHED"}

    def execute(self, context):
        if not self._can_build_box(context):
            return {"CANCELLED"}
        build_slip_casting_box_operator(
            context,
            channels_deposit_path=SLIP_CASTING_CHANNELS_DEPOSIT_PATH,
        )
        refresh_casting_volume_after_build_box(context)
        return {"FINISHED"}


class ConfirmSlipCasting(_ConfirmBehavior, MoldboxerOperator):
    bl_idname = "silicone.confirm_slip_casting"
    bl_label = "Confirm"
    bl_description = "Finish the editable slip-casting mold system"

    @classmethod
    def poll(cls, context):
        return (
            is_multipart_type(context.scene.mold_type_preview)
            and context.scene.objects.get("box") is not None
        )

    def _create_modal_step_iterator(self, context):
        if not self._can_confirm(context):
            return {"CANCELLED"}
        result = yield from iter_slip_casting_confirm_steps(context, async_server=True)
        if result == "DEBUG_GAP_PREVIEW":
            return {"FINISHED"}
        yield "Finalizing patron", lambda: finalize_master_as_patron()
        if is_slip_casting_vase_type(context.scene.mold_type_preview):
            yield from iter_build_slip_casting_vase_base_direct_mold_steps(
                context,
                async_server=True,
            )
        if not is_silicone_multipart_type(context.scene.mold_type_preview):
            yield "Preparing silicone mold settings", lambda: _enable_plaster_silicone_settings(context)
        yield "Enabling movement gizmos", lambda: enable_moldboxer_movement_gizmos(
            context
        )
        return {"FINISHED"}

    def execute(self, context):
        if not self._can_confirm(context):
            return {"CANCELLED"}
        if confirm_slip_casting(context) == "DEBUG_GAP_PREVIEW":
            return {"FINISHED"}
        finalize_master_as_patron()
        if is_slip_casting_vase_type(context.scene.mold_type_preview):
            build_slip_casting_vase_base_direct_mold(context)
        _enable_plaster_silicone_settings(context)
        enable_moldboxer_movement_gizmos(context)
        return {"FINISHED"}


class SmoothMasterSeal(ModalProcessingOperator):
    bl_idname = "silicone.smooth_master_seal"
    bl_label = "Smooth"
    bl_description = "Smooth the selected mesh geometry"
    bl_options = {"REGISTER", "UNDO"}
    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == "MESH"

    def execute(self, context):
        if not has_pro_server_access():
            show_pro_membership_required()
            return {"CANCELLED"}

        Object(context.object).smooth_geometry()
        return {"FINISHED"}

    def _create_modal_step_iterator(self, context):
        if not has_pro_server_access():
            show_pro_membership_required()
            return {"CANCELLED"}
        task = Object(context.object).begin_smooth_geometry()
        yield t("Smoothing mesh..."), lambda: task
        return {"FINISHED"}






class DetectSlipCastingCores(ModalProcessingOperator):
    bl_idname = "silicone.detect_slip_casting_cores"
    bl_label = "Prepare Casting"
    bl_description = (
        "Prepare the model for slip casting"
    )
    bl_options = {"REGISTER", "UNDO"}
    modal_show_progress_overlay = True
    modal_wait_redraw_interval = 0.1

    def _begin_operator_log_capture(self) -> None:
        super()._begin_operator_log_capture()
        now = time.perf_counter()
        self._build_funnels_operator_started = now
        self._build_funnels_last_checkpoint = now

    def _log_build_funnels_outer_timing(self, phase: str) -> None:
        started = getattr(self, "_build_funnels_operator_started", None)
        previous = getattr(self, "_build_funnels_last_checkpoint", None)
        if started is None or previous is None:
            return
        now = time.perf_counter()
        logger.info(
            "Build Funnels outer timing: phase=%s elapsed=%.3fs total=%.3fs",
            phase,
            now - previous,
            now - started,
        )
        self._build_funnels_last_checkpoint = now

    def _end_operator_log_capture(self, result=None) -> None:
        self._log_build_funnels_outer_timing("final_modal_cleanup")
        super()._end_operator_log_capture(result)

    def _start_modal(self, context):
        result = super()._start_modal(context)
        self._log_build_funnels_outer_timing("operator_setup_and_modal_start")
        return result

    @classmethod
    def poll(cls, context):
        scene = getattr(context, "scene", None)
        return bool(
            scene is not None
            and is_slip_casting_vase_type(scene.mold_type_preview)
            and scene.objects.get("patron") is not None
            and not slip_casting_has_prepared_parts(scene)
        )

    def _can_detect(self) -> bool:
        if not has_pro_server_access():
            show_pro_membership_required()
            return False
        return True

    def _refresh_result(self, context) -> None:
        refresh_generated_object_materials()
        refresh_viewport_material_display(context)
        area = getattr(context, "area", None)
        if area is not None:
            area.tag_redraw()

    def _begin_timed_detection_task(self, context):
        self._log_build_funnels_outer_timing("pre_inspection_framework_redraw")
        task = begin_detect_slip_casting_cores(context)
        self._log_build_funnels_outer_timing("inspection_task_creation")
        return task

    def _refresh_timed_detection_result(self, context) -> None:
        self._log_build_funnels_outer_timing("pre_result_framework_redraw")
        self._refresh_result(context)
        self._log_build_funnels_outer_timing("explicit_result_refresh")

    def _create_modal_step_iterator(self, context):
        if not self._can_detect():
            return {"CANCELLED"}
        self._log_build_funnels_outer_timing("first_modal_dispatch")
        yield t("Preparing Funnels"), lambda: self._begin_timed_detection_task(
            context
        )
        self._log_build_funnels_outer_timing(
            "inspection_wait_and_post_task_redraw"
        )
        yield t("Preparing Funnels"), lambda: (
            self._refresh_timed_detection_result(context)
        )
        self._log_build_funnels_outer_timing(
            "post_result_redraw_and_modal_dispatch"
        )
        # The registered preview timer starts after this modal operation ends.
        return {"FINISHED"}

    def execute(self, context):
        if not self._can_detect():
            return {"CANCELLED"}
        self._log_build_funnels_outer_timing("synchronous_detection_start")
        finish_task_sync(begin_detect_slip_casting_cores(context))
        self._log_build_funnels_outer_timing("synchronous_detection_task")
        self._refresh_result(context)
        self._log_build_funnels_outer_timing("synchronous_result_refresh")
        # Leave preview calculation to its background timer after completion.
        return {"FINISHED"}


class EnableSlipCastingCavityFillerWithCores(ModalProcessingOperator):
    bl_idname = "silicone.enable_slip_casting_cavity_filler_with_cores"
    bl_label = "Prepare Vase with Cores"
    bl_description = (
        "Run the preserved Slip Casting preparation workflow with server cores"
    )
    bl_options = {"REGISTER", "UNDO"}
    modal_show_progress_overlay = True
    modal_wait_redraw_interval = 0.1

    @classmethod
    def poll(cls, context):
        scene = getattr(context, "scene", None)
        return bool(
            scene is not None
            and is_slip_casting_vase_type(scene.mold_type_preview)
            and scene.objects.get("patron") is not None
            and not slip_casting_cavities_filled(scene)
        )

    def _can_fill(self, context) -> bool:
        if not has_pro_server_access():
            show_pro_membership_required()
            return False
        return True

    def _refresh_result(self, context) -> None:
        refresh_generated_object_materials()
        refresh_viewport_material_display(context)
        area = getattr(context, "area", None)
        if area is not None:
            area.tag_redraw()

    def _create_modal_step_iterator(self, context):
        if not self._can_fill(context):
            return {"CANCELLED"}
        yield "Preparing Vase with Cores", lambda: (
            begin_prepare_slip_casting_vase_with_cores(context)
        )
        yield "Preparing Vase with Cores", lambda: (
            self._refresh_result(context)
        )
        return {"FINISHED"}

    def execute(self, context):
        if not self._can_fill(context):
            return {"CANCELLED"}
        finish_task_sync(begin_prepare_slip_casting_vase_with_cores(context))
        self._refresh_result(context)
        return {"FINISHED"}

class BuildMasterFiller(SelectedObjectOperator):
    bl_idname = "silicone.build_master_filler"
    bl_label = "1. Build Master Filler"
    bl_description = "Create the sealer"
    bl_options = {"REGISTER", "UNDO"}
    modal_show_progress_overlay = True
    modal_log_redraw_timing = True
    modal_skip_redraw_steps = frozenset(
        {
            "Preparing sealer reference",
            "Building sealer",
        }
    )

    filler_quality: EnumProperty(  # type: ignore
        name="Detail",
        description="Master filler generation speed and detail",
        items=(
            ("DRAFT", "Draft", "Lowest detail, fastest processing"),
            ("FAST", "Fast", "Lower detail, faster processing"),
            ("MID", "Balanced", "Balanced speed and detail"),
            ("HIGH", "High Detail", "Higher detail, slower processing"),
        ),
        default="MID",
    )

    def draw(self, context):
        del context
        self.layout.prop(self, "filler_quality")

    def invoke(self, context, event):
        self.filler_quality = context.scene.pro_master_filler_quality
        return context.window_manager.invoke_props_dialog(self)

    @classmethod
    def poll(cls, context):
        patron = bpy.data.objects.get("patron")
        active = getattr(context, "active_object", None) or getattr(
            context, "object", None
        )
        return is_valid_utility_target(active) or is_valid_utility_target(patron)

    def _build_target(self, context):
        if not has_pro_server_access():
            show_pro_membership_required()
            return None

        target = resolve_utility_target(context)
        if target is None:
            self.report({"ERROR"}, t("No mesh object selected"))
            return None
        return target

    def _set_build_object_hidden(self, obj, hidden: bool) -> None:
        blender_obj = getattr(obj, "object", obj)
        if blender_obj is None or blender_obj.name not in bpy.data.objects:
            return
        blender_obj.hide_set(hidden)
        blender_obj.hide_viewport = hidden
        blender_obj.hide_render = hidden

    def _create_modal_step_iterator(self, context):
        target = self._build_target(context)
        if target is None:
            return {"CANCELLED"}

        context.scene[MASTER_FILLER_BUILDING_KEY] = True
        patron = bpy.data.objects.get("patron")
        if patron is not None:
            patron.hide_select = False
        reference_state = {"reference": None}

        def prepare_reference() -> None:
            reference = create_simplified_reference_for_operation(
                Object(target),
                context,
                name="master_filler_reference",
            )
            reference.hide_during_ui_breathe = True
            reference_state["reference"] = reference

        try:
            build_state = {"finished": False}

            def mark_finished() -> None:
                build_state["finished"] = True

            def cleanup_build() -> None:
                reference = reference_state["reference"]
                if reference is not None and reference.object.name in bpy.data.objects:
                    remove_objects_safely((reference.object,))
                if MASTER_FILLER_BUILDING_KEY in context.scene:
                    del context.scene[MASTER_FILLER_BUILDING_KEY]
                if build_state["finished"]:
                    sync_patron_selection_for_master_filler(
                        context,
                        deselect_patron=True,
                    )

            def start_hidden_build():
                reference = reference_state["reference"]
                if reference is None:
                    raise RuntimeError("Sealer reference was not prepared")
                try:
                    request = build_all_fillers_async(
                        reference,
                        context,
                        quality=self.filler_quality,
                        hide_until_complete=True,
                        on_complete=mark_finished,
                        on_finish=cleanup_build,
                    )
                    self._set_build_object_hidden(reference, True)
                    return request
                except Exception:
                    cleanup_build()
                    raise

            yield "Preparing sealer reference", prepare_reference
            yield "Building sealer", start_hidden_build
            yield "Refreshing materials", lambda: (
                refresh_generated_object_materials(),
                refresh_viewport_material_display(context),
            )
        except Exception:
            reference = reference_state["reference"]
            if reference is not None and reference.object.name in bpy.data.objects:
                remove_objects_safely((reference.object,))
            if MASTER_FILLER_BUILDING_KEY in context.scene:
                del context.scene[MASTER_FILLER_BUILDING_KEY]
            raise
        return {"FINISHED"}

    def execute(self, context):
        target = self._build_target(context)
        if target is None:
            return {"CANCELLED"}

        context.scene[MASTER_FILLER_BUILDING_KEY] = True
        patron = bpy.data.objects.get("patron")
        if patron is not None:
            patron.hide_select = False
        build_finished = False
        reference = None
        try:
            reference = create_simplified_reference_for_operation(
                Object(target),
                context,
                name="master_filler_reference",
            )
            reference.hide_during_ui_breathe = True
            build_all_fillers(
                reference,
                context,
                quality=self.filler_quality,
                hide_until_complete=True,
            )
            build_finished = True
        finally:
            if reference is not None and reference.object.name in bpy.data.objects:
                reference.remove()
            if MASTER_FILLER_BUILDING_KEY in context.scene:
                del context.scene[MASTER_FILLER_BUILDING_KEY]
        if build_finished:
            sync_patron_selection_for_master_filler(context, deselect_patron=True)
        refresh_generated_object_materials()
        refresh_viewport_material_display(context)
        return {"FINISHED"}


class ConfirmMasterFiller(SelectedObjectOperator):
    bl_idname = "silicone.confirm_master_filler"
    bl_label = "2. Confirm Master Filler"
    bl_description = "Add the sealer to the master"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        patron = bpy.data.objects.get("patron")
        if patron is None or patron.type != "MESH":
            return False
        return any(
            obj.type == "MESH" and "filler" in obj.name.casefold()
            for obj in bpy.data.objects
        )

    def execute(self, context):
        if not has_pro_server_access():
            show_pro_membership_required()
            return {"CANCELLED"}

        confirm_filler(context)
        sync_patron_selection_for_master_filler(context)
        refresh_viewport_material_display(context)
        self.report({"INFO"}, t("Confirmed master filler"))
        return {"FINISHED"}


def _get_selected_master_filler_target(context):
    target = getattr(context, "object", None)
    if (
        target is None
        or getattr(target, "type", None) != "MESH"
        or "filler" not in str(getattr(target, "name", "")).casefold()
    ):
        return None
    try:
        return target if target.select_get() else None
    except (AttributeError, RuntimeError):
        return None


def _get_selected_crop_target(context):
    """Return the selected active mesh when it is safe for Utils to modify."""

    target = getattr(context, "active_object", None) or getattr(
        context,
        "object",
        None,
    )
    if not is_valid_utility_target(target):
        return None
    try:
        return target if target.select_get() else None
    except (AttributeError, RuntimeError):
        return None


class CropMasterFillerGesture(bpy.types.Operator):
    bl_idname = "silicone.crop_master_filler_gesture"
    bl_label = "Crop"
    bl_description = "Draw a shape to crop the selected mesh"
    # The chooser finishes before drawing starts. Record the completed edit here,
    # after modal() restores Object Mode, so the mesh gets a global undo snapshot.
    bl_options = {"INTERNAL", "UNDO"}

    crop_shape: EnumProperty(  # type: ignore
        items=(
            ("BOX", "Box", "Draw a rectangular trim area"),
            ("CIRCLE", "Circle", "Draw a circular trim area"),
            ("LASSO", "Lasso", "Draw a freehand trim area"),
        ),
        default="BOX",
        options={"HIDDEN"},
    )

    _draw_handler = None
    _drawing = False
    _start_point = None
    _current_point = None
    _stroke_points = None

    @classmethod
    def poll(cls, context):
        return (
            getattr(getattr(context, "area", None), "type", None) == "VIEW_3D"
            and getattr(getattr(context, "region", None), "type", None) == "WINDOW"
            and getattr(context, "mode", "") == "SCULPT"
            and _get_selected_crop_target(context) is not None
        )

    def _tag_redraw(self, context):
        area = getattr(context, "area", None)
        if area is not None:
            area.tag_redraw()

    def _outline_points(self):
        if self._start_point is None:
            return []
        current = self._current_point or self._start_point
        if self.crop_shape == "BOX":
            x1, y1 = self._start_point
            x2, y2 = current
            return [(x1, y1), (x2, y1), (x2, y2), (x1, y2), (x1, y1)]
        if self.crop_shape == "CIRCLE":
            center_x, center_y = self._start_point
            radius = math.hypot(current[0] - center_x, current[1] - center_y)
            return [
                (
                    center_x + radius * math.cos((2.0 * math.pi * index) / 64),
                    center_y + radius * math.sin((2.0 * math.pi * index) / 64),
                )
                for index in range(65)
            ]
        points = list(self._stroke_points or ())
        if len(points) > 1:
            points.append(points[0])
        return points

    def _draw_overlay(self):
        points = self._outline_points()
        if len(points) < 2:
            return
        try:
            import gpu  # type: ignore
            from gpu_extras.batch import batch_for_shader  # type: ignore

            shader = gpu.shader.from_builtin("UNIFORM_COLOR")
            batch = batch_for_shader(shader, "LINE_STRIP", {"pos": points})
            gpu.state.blend_set("ALPHA")
            gpu.state.line_width_set(2.0)
            shader.bind()
            shader.uniform_float("color", (0.95, 0.55, 0.08, 1.0))
            batch.draw(shader)
        except Exception:
            pass
        finally:
            try:
                import gpu  # type: ignore

                gpu.state.line_width_set(1.0)
                gpu.state.blend_set("NONE")
            except Exception:
                pass

    def _finish(self, context):
        if self._draw_handler is not None:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(
                    self._draw_handler,
                    "WINDOW",
                )
            except Exception:
                pass
            self._draw_handler = None
        area = getattr(context, "area", None)
        if area is not None:
            try:
                area.header_text_set(None)
            except Exception:
                pass
        window = getattr(context, "window", None)
        if window is not None:
            try:
                window.cursor_modal_restore()
            except Exception:
                pass
        self._tag_redraw(context)

    def _restore_object_mode(self):
        if getattr(bpy.context, "mode", "") != "SCULPT":
            return
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass

    @staticmethod
    def _mouse_point(event):
        return (
            int(getattr(event, "mouse_region_x", 0)),
            int(getattr(event, "mouse_region_y", 0)),
        )

    def _append_lasso_point(self, point, *, force=False):
        points = self._stroke_points
        if points is None:
            points = []
            self._stroke_points = points
        if not points:
            points.append(point)
            return
        dx = point[0] - points[-1][0]
        dy = point[1] - points[-1][1]
        if force or (dx * dx) + (dy * dy) >= 4:
            points.append(point)

    def _trim_kwargs(self, location):
        return {
            "location": tuple(int(value) for value in location),
            "trim_mode": "DIFFERENCE",
            "trim_orientation": "VIEW",
            "trim_extrude_mode": "FIXED",
            "trim_solver": getattr(self, "_active_trim_solver", "MANIFOLD"),
            "use_cursor_depth": False,
            "use_front_faces_only": False,
        }

    def _apply_crop(self):
        try:
            self._apply_crop_with_solver("MANIFOLD")
            return
        except RuntimeError:
            logger.warning(
                "MANIFOLD crop failed; retrying with the EXACT solver",
                exc_info=True,
            )

        # MANIFOLD is deliberately restricted to watertight meshes. EXACT can
        # crop non-manifold imports without changing their geometry first and,
        # importantly, while the original valid Sculpt/VIEW_3D context is still
        # active.
        try:
            self._apply_crop_with_solver("EXACT")
            return
        except RuntimeError:
            logger.warning("EXACT crop failed; trying geometry cleanup", exc_info=True)

        # Native trim leaves the geometry intact on solver failure. Keep that
        # mesh for rollback and repair a private copy outside Sculpt Mode.
        target = bpy.context.active_object
        bpy.ops.object.mode_set(mode="OBJECT")
        original_mesh = target.data
        recovered = False
        try:
            target.data = original_mesh.copy()
            wrapped = Object(target)
            if wrapped._clean_for_manifold_boolean_retry(wrapped):
                self._activate_crop_target(target)
                try:
                    self._apply_crop_with_solver("EXACT")
                    recovered = True
                    return
                except RuntimeError:
                    logger.warning(
                        "Crop Boolean still failed after cleanup; trying remesh",
                        exc_info=True,
                    )

            bpy.ops.object.mode_set(mode="OBJECT")
            wrapped.apply_modifier(wrapped._geometry_fallback_remesh_modifier())
            self._activate_crop_target(target)
            self._apply_crop_with_solver("EXACT")
            recovered = True
        finally:
            if not recovered:
                bpy.ops.object.mode_set(mode="OBJECT")
                failed_mesh = target.data
                target.data = original_mesh
                if failed_mesh != original_mesh and failed_mesh.users == 0:
                    bpy.data.meshes.remove(failed_mesh)
                target.select_set(True)
                bpy.context.view_layer.objects.active = target
            elif original_mesh.users == 0:
                bpy.data.meshes.remove(original_mesh)

    def _apply_crop_with_solver(self, solver):
        previous = getattr(self, "_active_trim_solver", None)
        self._active_trim_solver = solver
        try:
            self._apply_crop_once()
        finally:
            if previous is None:
                try:
                    del self._active_trim_solver
                except AttributeError:
                    pass
            else:
                self._active_trim_solver = previous

    @staticmethod
    def _activate_crop_target(target):
        # Modifier application deselects its operand; native trim needs an
        # active, selected object and a rebuilt sculpt session after repair.
        target.select_set(True)
        bpy.context.view_layer.objects.active = target
        bpy.ops.object.mode_set(mode="SCULPT")

    def _apply_crop_once(self):
        start = self._start_point
        current = self._current_point
        if start is None or current is None:
            raise ValueError("Draw a crop area first")

        if self.crop_shape == "BOX":
            if abs(current[0] - start[0]) < 3 or abs(current[1] - start[1]) < 3:
                raise ValueError(
                    "Draw a larger crop area with LMB; Esc or RMB cancels"
                )
            result = bpy.ops.sculpt.trim_box_gesture(
                "EXEC_DEFAULT",
                xmin=min(start[0], current[0]),
                xmax=max(start[0], current[0]),
                ymin=min(start[1], current[1]),
                ymax=max(start[1], current[1]),
                **self._trim_kwargs(start),
            )
        else:
            if self.crop_shape == "CIRCLE":
                path_points = self._outline_points()
                if math.hypot(current[0] - start[0], current[1] - start[1]) < 3:
                    raise ValueError(
                        "Draw a larger crop area with LMB; Esc or RMB cancels"
                    )
            else:
                path_points = list(self._stroke_points or ())
                if len(path_points) < 3:
                    raise ValueError(
                        "Draw a larger crop area with LMB; Esc or RMB cancels"
                    )
            path = [
                {
                    "name": str(index),
                    "loc": (float(x), float(y)),
                    "time": float(index),
                }
                for index, (x, y) in enumerate(path_points)
            ]
            result = bpy.ops.sculpt.trim_lasso_gesture(
                "EXEC_DEFAULT",
                path=path,
                **self._trim_kwargs(start),
            )

        if "FINISHED" not in result:
            raise RuntimeError("Blender could not crop the selected mesh")

    def invoke(self, context, _event):
        self._drawing = False
        self._start_point = None
        self._current_point = None
        self._stroke_points = []
        self._draw_handler = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_overlay,
            (),
            "WINDOW",
            "POST_PIXEL",
        )
        try:
            context.window.cursor_modal_set("CROSSHAIR")
        except Exception:
            pass
        context.area.header_text_set(
            t("Draw the crop area with LMB; Esc or RMB cancels")
        )
        context.window_manager.modal_handler_add(self)
        self._tag_redraw(context)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            self._finish(context)
            self._restore_object_mode()
            return {"CANCELLED"}
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            point = self._mouse_point(event)
            self._start_point = point
            self._current_point = point
            self._stroke_points = [point]
            self._drawing = True
            self._tag_redraw(context)
            return {"RUNNING_MODAL"}
        if event.type == "MOUSEMOVE" and self._drawing:
            point = self._mouse_point(event)
            self._current_point = point
            if self.crop_shape == "LASSO":
                self._append_lasso_point(point)
            self._tag_redraw(context)
            return {"RUNNING_MODAL"}
        if event.type == "LEFTMOUSE" and event.value == "RELEASE" and self._drawing:
            point = self._mouse_point(event)
            self._current_point = point
            if self.crop_shape == "LASSO":
                self._append_lasso_point(point, force=True)
            self._drawing = False
            try:
                self._apply_crop()
            except ValueError as exc:
                self.report({"WARNING"}, t(str(exc)))
                self._start_point = None
                self._current_point = None
                self._stroke_points = []
                context.area.header_text_set(
                    t("Draw a larger crop area with LMB; Esc or RMB cancels")
                )
                self._tag_redraw(context)
                return {"RUNNING_MODAL"}
            except Exception as exc:
                self.report(
                    {"ERROR"},
                    t("Could not crop sealer: {error}", error=exc),
                )
                self._finish(context)
                self._restore_object_mode()
                return {"CANCELLED"}

            self._finish(context)
            self._restore_object_mode()
            refresh_generated_object_materials()
            refresh_viewport_material_display(context)
            self.report({"INFO"}, t("Cropped selected sealer"))
            return {"FINISHED"}
        return {"RUNNING_MODAL"}


class CropMasterFiller(SelectedObjectOperator):
    bl_idname = "silicone.crop_master_filler"
    bl_label = "Crop"
    bl_description = "Crop the selected mesh with a box, circle, or lasso"
    bl_options = {"REGISTER"}

    crop_shape: EnumProperty(  # type: ignore
        name="Crop Shape",
        description="Shape used to crop the selected mesh",
        items=(
            ("BOX", "Box", "Draw a rectangular crop area"),
            ("CIRCLE", "Circle", "Draw a circular crop area"),
            ("LASSO", "Lasso", "Draw a freehand crop area"),
        ),
        default="BOX",
    )

    @classmethod
    def poll(cls, context):
        return _get_selected_crop_target(context) is not None

    def invoke(self, context, _event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        if not has_pro_server_access():
            show_pro_membership_required()
            return {"CANCELLED"}
        target = _get_selected_crop_target(context)
        if target is None:
            self.report({"ERROR"}, t("Select a valid mesh object"))
            return {"CANCELLED"}
        try:
            context.view_layer.objects.active = target
            target.select_set(True)
            if getattr(context, "mode", "") != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            bpy.ops.object.mode_set(mode="SCULPT")
            result = bpy.ops.silicone.crop_master_filler_gesture(
                "INVOKE_DEFAULT",
                crop_shape=self.crop_shape,
            )
        except Exception as exc:
            if getattr(bpy.context, "mode", "") == "SCULPT":
                try:
                    bpy.ops.object.mode_set(mode="OBJECT")
                except Exception:
                    pass
            self.report({"ERROR"}, t("Could not start crop tool: {error}", error=exc))
            return {"CANCELLED"}
        if "RUNNING_MODAL" not in result:
            if getattr(bpy.context, "mode", "") == "SCULPT":
                try:
                    bpy.ops.object.mode_set(mode="OBJECT")
                except Exception:
                    pass
            self.report({"ERROR"}, t("Could not start crop tool"))
            return {"CANCELLED"}
        return {"FINISHED"}


class FillMasterBase(SelectedObjectOperator):
    bl_idname = "silicone.fill_master_base"
    bl_label = "Fill to Base"
    bl_description = "Run Foundation on the selected sealer"
    bl_options = {"REGISTER", "UNDO"}

    threshold_angle: FloatProperty(  # type: ignore
        name="Threshold Angle",
        description=(
            "Minimum downward face angle included in the generated foundation"
        ),
        default=math.radians(35.0),
        min=0.0,
        max=math.radians(90.0),
        subtype="ANGLE",
    )
    target_name: StringProperty(options={"HIDDEN"})  # type: ignore

    def invoke(self, context, event):
        del event
        target = self._fill_target(context)
        if target is None:
            return {"CANCELLED"}
        self.target_name = target.name
        self.threshold_angle = math.radians(
            foundation_threshold_angle_degrees(context.scene)
        )
        return context.window_manager.invoke_props_dialog(self, width=340)

    def draw(self, context):
        del context
        self.layout.prop(self, "threshold_angle")

    @classmethod
    def poll(cls, context):
        return _get_selected_master_filler_target(context) is not None

    def _fill_target(self, context):
        if not has_pro_server_access():
            show_pro_membership_required()
            return None

        target = bpy.data.objects.get(self.target_name) if self.target_name else None
        if (
            target is None
            or getattr(target, "type", None) != "MESH"
            or "filler" not in str(getattr(target, "name", "")).casefold()
        ):
            target = _get_selected_master_filler_target(context)
        if target is None:
            message = t("Select a sealer object first")
            show_popup(message)
            self.report({"ERROR"}, message)
            return None
        return target

    def execute(self, context):
        target = self._fill_target(context)
        if target is None:
            return {"CANCELLED"}

        try:
            begin_foundation_reference_guide(
                context.scene,
                target=target,
                angle_threshold_degrees=math.degrees(self.threshold_angle),
            )
        except Exception as error:
            logger.exception("Could not begin Foundation for selected sealer")
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

        force_viewport_redraw(context)
        self.report(
            {"INFO"},
            t(
                "Position the yellow circle to set the foundation base "
                "reference, then press Confirm Foundation"
            ),
        )
        return {"FINISHED"}


class RemoveMasterFillerType(SelectedObjectOperator):
    bl_idname = "silicone.remove_master_filler_type"
    bl_label = "Bulk Remove"
    bl_description = "Remove filler objects for the selected filler type"
    bl_options = {"REGISTER", "UNDO"}

    filler_type: EnumProperty(  # type: ignore
        name="Filler Type",
        description="Filler type to remove",
        items=(
            ("GREEN", "Green", "Remove tight filler objects"),
            ("BLUE", "Blue", "Remove cavity filler objects"),
            ("ORANGE", "Orange", "Remove air-trap filler objects"),
        ),
        default="ORANGE",
    )

    def invoke(self, context, event):
        self.filler_type = context.scene.master_filler_remove_type
        return context.window_manager.invoke_props_dialog(self)

    @classmethod
    def poll(cls, context):
        return any(
            keyword in obj.name.casefold()
            for keyword in ("air", "tight", "cavity")
            for obj in bpy.data.objects
        )

    def execute(self, context):
        if not has_pro_server_access():
            show_pro_membership_required()
            return {"CANCELLED"}

        removed_count = remove_fillers_by_type(self.filler_type)
        if removed_count == 0:
            self.report({"ERROR"}, t("No matching filler objects found"))
            return {"CANCELLED"}

        refresh_generated_object_materials()
        refresh_viewport_material_display(context)
        sync_patron_selection_for_master_filler(context)
        self.report(
            {"INFO"},
            t("Removed {count} filler objects", count=removed_count),
        )
        return {"FINISHED"}


class SplitFillerMeshes(SelectedObjectOperator):
    bl_idname = "silicone.split_filler_meshes"
    bl_label = "Split Filler Meshes"
    bl_description = "Split loose isolated meshes for all filler objects"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return any(
            obj.type == "MESH" and "filler" in obj.name.casefold()
            for obj in bpy.data.objects
        )

    def execute(self, context):
        if not has_pro_server_access():
            show_pro_membership_required()
            return {"CANCELLED"}

        filler_objects = [
            obj
            for obj in bpy.data.objects
            if obj.type == "MESH" and "filler" in obj.name.casefold()
        ]
        if not filler_objects:
            self.report({"ERROR"}, t("No filler objects found"))
            return {"CANCELLED"}

        split_count = 0
        for obj in filler_objects:
            if obj.name not in bpy.data.objects:
                continue
            isolated_meshes = Object(obj).split_isolated_meshes()
            split_count += max(0, len(isolated_meshes) - 1)
            for mesh_obj in isolated_meshes:
                mesh_obj.origin_to_geometry()

        refresh_generated_object_materials()
        refresh_viewport_material_display(context)
        sync_patron_selection_for_master_filler(context)
        self.report({"INFO"}, t("Split {count} filler mesh parts", count=split_count))
        return {"FINISHED"}


class AddCastingInput(UtilityTargetOperator):
    bl_idname = "silicone.add_casting_input"
    bl_label = "Add Casting Input"
    bl_description = (
        "Generate and place a casting input cylinder using the configured face axis"
    )
    bl_options = {"REGISTER", "UNDO"}

    input_shape: EnumProperty(  # type: ignore
        name="Shape",
        description="Shape used to create the casting input",
        items=(
            ("CYLINDER", "Cylinder", "Create a cylindrical casting input"),
            ("CUBE", "Cube", "Create a cube casting input"),
        ),
        default="CYLINDER",
    )
    project_top: BoolProperty(  # type: ignore
        name="Project",
        description="Project the casting sprue top face to the patron along Z",
        default=True,
    )
    base_offset: FloatProperty(  # type: ignore
        name="Base Offset",
        description="Offset from the patron base for the sprue projection plane",
        default=0.0,
        min=0.0,
        subtype="DISTANCE",
    )

    def invoke(self, context, event):
        self.input_shape = context.scene.casting_input_shape
        self.project_top = context.scene.casting_input_project_top
        self.base_offset = context.scene.casting_input_base_offset
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "input_shape")
        layout.prop(self, "project_top")
        offset_row = layout.row()
        offset_row.enabled = self.project_top
        offset_row.prop(self, "base_offset")

    @classmethod
    def poll(cls, context):
        patron = bpy.data.objects.get("patron")
        return patron is not None or context.object is not None

    def execute(self, context):
        if not super().execute(context):
            return {"CANCELLED"}
        create_casting_input(
            context,
            shape=self.input_shape,
            project_top=self.project_top,
            base_offset=self.base_offset,
        )
        self.report(
            {"INFO"},
            (
                t("Added casting input") + " "
                f"(H={CASTING_INPUT_HEIGHT:.3f} mm, "
                f"D={CASTING_INPUT_DIAMETER:.3f} mm, "
                f"axis={CASTING_INPUT_AXIS})"
            ),
        )

        return {"FINISHED"}

    def _create_modal_step_iterator(self, context):
        if not super().execute(context):
            return {"CANCELLED"}
        task = begin_create_casting_input(
            context,
            shape=self.input_shape,
            project_top=self.project_top,
            base_offset=self.base_offset,
        )
        yield t("Placing casting input..."), lambda: task
        self.report(
            {"INFO"},
            t("Added casting input"),
        )
        return {"FINISHED"}


class ConfirmCastingInput(SelectedObjectOperator):
    bl_idname = "silicone.confirm_casting_input"
    bl_label = "Confirm Casting Input"
    bl_description = "Confirm the placed casting input and add it to the patron"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        patron = bpy.data.objects.get("patron")
        return patron is not None and patron.type == "MESH"

    def execute(self, context):
        super().execute(context)
        confirm_casting_input(context)
        self.report({"INFO"}, t("Confirmed casting input"))

        return {"FINISHED"}

    def _create_modal_step_iterator(self, context):
        super().execute(context)
        task = begin_confirm_casting_input(context)
        yield t("Projecting casting input..."), lambda: task
        self.report({"INFO"}, t("Confirmed casting input"))
        return {"FINISHED"}


class Clean(UtilityTargetOperator):
    bl_idname = "silicone.clean"
    bl_label = "Clean"
    bl_description = "Clean the top or bottom of the object"
    bl_options = {"REGISTER", "UNDO"}

    clean_side: EnumProperty(  # type: ignore
        name="Side",
        description="Choose which side of the object to clean",
        items=(
            ("TOP", "Top", "Clean the top of the object"),
            ("BOTTOM", "Bottom", "Clean the bottom of the object"),
        ),
        default="TOP",
    )
    cut_clean_height: FloatProperty(  # type: ignore
        name="Height",
        description="Height to clean",
        default=1,
        min=0.1,
        subtype="DISTANCE",
    )
    clean_all_top: BoolProperty(  # type: ignore
        name="Clean All Top",
        description="Clean the full height of the selected object",
        default=False,
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        side_row = layout.row(align=True)
        side_row.prop(self, "clean_side", expand=True)
        if self.clean_side == "TOP":
            layout.prop(self, "clean_all_top")
        height_row = layout.row()
        height_row.enabled = not (self.clean_side == "TOP" and self.clean_all_top)
        height_row.prop(self, "cut_clean_height")

    @retry_after_heal
    def execute(self, context):
        if not super().execute(context):
            return {"CANCELLED"}
        selected_object = Object(bpy.context.active_object)
        selected_object.select()
        selected_object.apply_all_transforms()
        if self.clean_side == "TOP":
            clean_height = (
                selected_object.height - 0.1
                if self.clean_all_top
                else self.cut_clean_height
            )
            selected_object.clean_top(clean_height)
        else:
            selected_object.clean_bot(self.cut_clean_height)
        selected_object.select()
        if selected_object.has_empty_boolean:
            raise Exception("Boolean modifier without target failed")
        return {"FINISHED"}


class Cut(UtilityTargetOperator):
    bl_idname = "silicone.cut"
    bl_label = "Cut"
    bl_description = "Cut the top or bottom of the object"
    bl_options = {"REGISTER", "UNDO"}

    cut_side: EnumProperty(  # type: ignore
        name="Side",
        description="Choose which side of the object to cut",
        items=(
            ("TOP", "Top", "Cut the top of the object"),
            ("BOTTOM", "Bottom", "Cut the bottom of the object"),
        ),
        default="TOP",
    )
    cut_clean_height: FloatProperty(  # type: ignore
        name="Height",
        description="Height to cut",
        default=1,
        min=0.1,
        subtype="DISTANCE",
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        side_row = layout.row(align=True)
        side_row.prop(self, "cut_side", expand=True)
        layout.prop(self, "cut_clean_height")

    @retry_after_heal
    def execute(self, context):
        if not super().execute(context):
            return {"CANCELLED"}
        selected_obj = Object(bpy.context.active_object)
        selected_obj.select()
        selected_obj.apply_all_transforms()
        cut_top = self.cut_side == "TOP"
        direction = mathutils.Vector((0, 0, 1 if cut_top else -1))
        cut_z = (
            selected_obj.max_z - self.cut_clean_height
            if cut_top
            else selected_obj.min_z + self.cut_clean_height
        )
        selected_obj.cut_plane(
            direction,
            mathutils.Vector((0, 0, cut_z)),
        )
        selected_obj.select()
        if selected_obj.has_empty_boolean:
            raise Exception("Boolean modifier without target")
        return {"FINISHED"}


class BuildGrip(ModalProcessingOperator):
    bl_idname = "silicone.build_grip"
    bl_label = "Build Grip"
    bl_description = "Build Grip"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        cursor_to_origin(context)
        build_grip(context.scene.grip_height)
        return {"FINISHED"}


class AddGrip(ModalProcessingOperator):
    bl_idname = "silicone.add_grip"
    bl_label = "Add Grip"
    bl_description = "Add Grip"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        cursor_to_origin(context)
        add_grip(get_box_voxel_size(context.scene.box_quality))
        return {"FINISHED"}


class Grid(UtilityTargetOperator):
    bl_idname = "silicone.grid"
    bl_label = "Grid"
    bl_description = "Grid the object with arrays"
    bl_options = {"REGISTER", "UNDO"}

    grid_rows: IntProperty(  # type: ignore
        name="Rows",
        description="Number of rows of the grid",
        default=3,
    )
    grid_columns: IntProperty(  # type: ignore
        name="Columns",
        description="Number of columns of the grid",
        default=3,
    )
    grid_distance: FloatProperty(  # type: ignore
        name="Distance",
        description="Distance between the grid objects",
        default=4,
        subtype="DISTANCE",
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        if not super().execute(context):
            return {"CANCELLED"}
        if not has_basic_server_access():
            show_basic_membership_required()
            return {"CANCELLED"}
        """Grid the object with arrays"""
        active_obj = Object(bpy.context.active_object)
        active_obj.apply_all_transforms()
        active_obj.grid_obj(
            self.grid_rows,
            self.grid_columns,
            self.grid_distance,
        )
        active_obj.select()
        bpy.ops.silicone.center_obj()

        return {"FINISHED"}


class BuildMasterAirTrapBridges(UtilityTargetOperator):
    bl_idname = "silicone.build_master_air_trap_bridges"
    bl_label = "1. Build Air Trap Pillars"
    bl_description = (
        "Detect unsupported underside islands and place cylinders from their "
        "bottom tips to the master base plane"
    )
    bl_options = {"REGISTER", "UNDO"}
    modal_show_progress_overlay = True
    modal_wait_redraw_interval = 0.1

    bridge_radius: FloatProperty(  # type: ignore
        name="Cylinder Radius",
        description="Radius of each generated air-trap bridge cylinder",
        default=DEFAULT_MASTER_AIR_TRAP_BRIDGE_RADIUS,
        min=0.01,
        subtype="DISTANCE",
    )
    bridge_overlap: FloatProperty(  # type: ignore
        name="Overlap",
        description="Distance embedded into the master at each island tip",
        default=DEFAULT_MASTER_AIR_TRAP_BRIDGE_OVERLAP,
        min=0.0,
        subtype="DISTANCE",
    )
    min_projected_area: FloatProperty(  # type: ignore
        name="Minimum Island Area",
        description="Ignore smaller downward-facing regions as mesh noise",
        default=DEFAULT_MASTER_AIR_TRAP_MIN_AREA,
        min=0.0,
    )
    minima_merge_height: FloatProperty(  # type: ignore
        name="Merge Minima Height",
        description=(
            "Merge neighboring air-trap minima within this height into one "
            "island and place its pillar at the deepest minimum"
        ),
        default=DEFAULT_MASTER_AIR_TRAP_MINIMA_MERGE_HEIGHT,
        min=0.0,
        subtype="DISTANCE",
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "bridge_radius")
        layout.prop(self, "bridge_overlap")
        layout.prop(self, "min_projected_area")
        layout.prop(self, "minima_merge_height")

    def execute(self, context):
        if not super().execute(context):
            return {"CANCELLED"}
        if not has_pro_server_access():
            show_pro_membership_required()
            return {"CANCELLED"}
        if scene_has_master_air_trap_pillars(context):
            self.report(
                {"ERROR"},
                t("Confirm or remove the existing air-trap pillars first"),
            )
            return {"CANCELLED"}

        target_raw = resolve_utility_target(context)
        if target_raw is None or target_raw.type != "MESH":
            self.report({"ERROR"}, t("Select a valid mesh object"))
            return {"CANCELLED"}

        target = Object(target_raw)
        try:
            bridges = build_master_air_trap_cylinders(
                target,
                target.min_z,
                radius=self.bridge_radius,
                overlap=self.bridge_overlap,
                min_projected_area=self.min_projected_area,
                minima_merge_height=self.minima_merge_height,
            )
        except Exception as exc:
            logger.exception("Could not build master air-trap bridges")
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        if not bridges:
            target.select()
            self.report({"INFO"}, t("No master air traps detected"))
            return {"FINISHED"}

        deselect_all_objects()
        for bridge in bridges:
            bridge.object.select_set(True)
        context.view_layer.objects.active = bridges[0].object
        self.report(
            {"INFO"},
            t(
                "Created {count} editable air-trap pillar(s)",
                count=len(bridges),
            ),
        )
        return {"FINISHED"}

    def _create_modal_step_iterator(self, context):
        if not super().execute(context):
            return {"CANCELLED"}
        if not has_pro_server_access():
            show_pro_membership_required()
            return {"CANCELLED"}
        if scene_has_master_air_trap_pillars(context):
            self.report(
                {"ERROR"},
                t("Confirm or remove the existing air-trap pillars first"),
            )
            return {"CANCELLED"}
        target_raw = resolve_utility_target(context)
        if target_raw is None or target_raw.type != "MESH":
            self.report({"ERROR"}, t("Select a valid mesh object"))
            return {"CANCELLED"}

        target = Object(target_raw)
        task = begin_build_master_air_trap_cylinders(
            target,
            target.min_z,
            radius=self.bridge_radius,
            overlap=self.bridge_overlap,
            min_projected_area=self.min_projected_area,
            minima_merge_height=self.minima_merge_height,
        )
        yield t("Detecting master air traps..."), lambda: task
        bridges = task.finish()
        if not bridges:
            target.select()
            self.report({"INFO"}, t("No master air traps detected"))
            return {"FINISHED"}

        deselect_all_objects()
        for bridge in bridges:
            bridge.object.select_set(True)
        context.view_layer.objects.active = bridges[0].object
        self.report(
            {"INFO"},
            t(
                "Created {count} editable air-trap pillar(s)",
                count=len(bridges),
            ),
        )
        return {"FINISHED"}


class BeginFoundation(ModalProcessingOperator):
    bl_idname = "silicone.begin_foundation"
    bl_label = "Foundation"
    bl_description = "Create a base-reference circle for a solid master foundation"
    bl_options = {"REGISTER", "UNDO"}
    modal_enabled = False

    threshold_angle: FloatProperty(  # type: ignore
        name="Threshold Angle",
        description=(
            "Minimum downward face angle included in the generated foundation"
        ),
        default=math.radians(35.0),
        min=0.0,
        max=math.radians(90.0),
        subtype="ANGLE",
    )

    @classmethod
    def poll(cls, context):
        return foundation_reference_guide_available(
            getattr(context, "scene", None)
        )

    def invoke(self, context, event):
        del event
        if not has_pro_server_access():
            show_pro_membership_required()
            return {"CANCELLED"}
        self.threshold_angle = math.radians(
            foundation_threshold_angle_degrees(context.scene)
        )
        return context.window_manager.invoke_props_dialog(self, width=340)

    def draw(self, context):
        del context
        self.layout.prop(self, "threshold_angle")

    def execute(self, context):
        if not has_pro_server_access():
            show_pro_membership_required()
            return {"CANCELLED"}
        try:
            begin_foundation_reference_guide(
                context.scene,
                angle_threshold_degrees=math.degrees(self.threshold_angle),
            )
        except Exception as exc:
            logger.exception("Could not begin Foundation")
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        force_viewport_redraw(context)
        self.report(
            {"INFO"},
            t(
                "Position the yellow circle to set the foundation base "
                "reference, then press Confirm Foundation"
            ),
        )
        return {"FINISHED"}


class ConfirmFoundation(ModalProcessingOperator):
    bl_idname = "silicone.confirm_foundation"
    bl_label = "Confirm Foundation"
    bl_description = "Generate and join a solid foundation into the target object"
    bl_options = {"REGISTER", "UNDO"}
    modal_show_progress_overlay = True

    @classmethod
    def poll(cls, context):
        return foundation_reference_guide_active(
            getattr(context, "scene", None)
        )

    def _create_modal_step_iterator(self, context):
        if not has_pro_server_access():
            show_pro_membership_required()
            return {"CANCELLED"}
        target = foundation_reference_target_object(context.scene)
        completion_message = (
            "Foundation applied to the selected sealer"
            if target is not None and "filler" in target.name.casefold()
            else "Foundation applied to the original master"
        )
        task = begin_apply_foundation(context)
        yield t("Generating Foundation..."), lambda: task
        self.report({"INFO"}, t(completion_message))
        return {"FINISHED"}

    def execute(self, context):
        if not has_pro_server_access():
            show_pro_membership_required()
            return {"CANCELLED"}
        target = foundation_reference_target_object(context.scene)
        completion_message = (
            "Foundation applied to the selected sealer"
            if target is not None and "filler" in target.name.casefold()
            else "Foundation applied to the original master"
        )
        apply_foundation(context)
        self.report({"INFO"}, t(completion_message))
        return {"FINISHED"}


class ConfirmMasterAirTrapPillars(ModalProcessingOperator):
    bl_idname = "silicone.confirm_master_air_trap_pillars"
    bl_label = "2. Confirm Air Trap Pillars"
    bl_description = (
        "Boolean-union the editable air-trap pillars into the master"
    )
    bl_options = {"REGISTER", "UNDO"}
    modal_enabled = False

    @classmethod
    def poll(cls, context):
        return scene_has_master_air_trap_pillars(context)

    def execute(self, context):
        if not has_pro_server_access():
            show_pro_membership_required()
            return {"CANCELLED"}

        try:
            master = confirm_master_air_trap_pillars(context)
        except Exception as exc:
            logger.exception("Could not confirm master air-trap pilars")
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        refresh_generated_object_materials()
        refresh_viewport_material_display(context)
        self.report({"INFO"}, t("Confirmed master air-trap pillars"))
        master.select()
        return {"FINISHED"}

class Decimate(UtilityTargetOperator):
    bl_idname = "silicone.decimate"
    bl_label = "Decimate"
    bl_description = "Decimate"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if not super().execute(context):
            return {"CANCELLED"}
        source_obj = bpy.context.active_object
        if source_obj is None or source_obj.type != "MESH":
            self.report({"ERROR"}, t("No active mesh object found"))
            return {"CANCELLED"}

        original_name = source_obj.name
        original_mesh_name = source_obj.data.name if source_obj.data else None
        collection = (
            source_obj.users_collection[0]
            if source_obj.users_collection
            else context.collection
        )
        keep_ratio = 0.5
        target_reduction = 1.0 - keep_ratio

        try:
            decimated_obj = create_fast_simplified_object(
                source_obj,
                collection,
                name=f"{original_name}_fast_decimate",
                target_reduction=target_reduction,
            )
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        remove_objects_safely((source_obj,))
        decimated_obj.name = original_name
        if original_mesh_name is not None:
            decimated_obj.data.name = original_mesh_name
        assign_generated_material(decimated_obj)
        Object(decimated_obj).select()
        self.report(
            {"INFO"},
            t(
                "Fast decimated {name} with keep factor {keep_ratio:.2f}",
                name=original_name,
                keep_ratio=keep_ratio,
            ),
        )
        return {"FINISHED"}

    def _create_modal_step_iterator(self, context):
        if not super().execute(context):
            return {"CANCELLED"}
        source_obj = bpy.context.active_object
        if source_obj is None or source_obj.type != "MESH":
            self.report({"ERROR"}, t("No active mesh object found"))
            return {"CANCELLED"}
        original_name = source_obj.name
        original_mesh_name = source_obj.data.name if source_obj.data else None
        collection = (
            source_obj.users_collection[0]
            if source_obj.users_collection
            else context.collection
        )
        keep_ratio = 0.5
        availability_task = begin_fast_simplification_available()
        yield t("Checking simplification worker..."), lambda: availability_task
        if not availability_task.finish():
            self.report({"ERROR"}, t("Fast simplification is not available"))
            return {"CANCELLED"}
        task = begin_create_fast_simplified_object(
            source_obj,
            collection,
            name=f"{original_name}_fast_decimate",
            target_reduction=1.0 - keep_ratio,
        )
        yield t("Decimating model..."), lambda: task
        decimated_obj = task.finish()

        remove_objects_safely((source_obj,))
        decimated_obj.name = original_name
        if original_mesh_name is not None:
            decimated_obj.data.name = original_mesh_name
        assign_generated_material(decimated_obj)
        Object(decimated_obj).select()
        self.report(
            {"INFO"},
            t(
                "Fast decimated {name} with keep factor {keep_ratio:.2f}",
                name=original_name,
                keep_ratio=keep_ratio,
            ),
        )
        return {"FINISHED"}


class ImportModel(ImportHelper, ModalProcessingOperator):
    requires_current_extension = True
    bl_idname = "silicone.import_model"
    bl_label = "Import"
    bl_description = "Import the master model you want to mold (STL, OBJ, 3MF, or STEP)"
    bl_options = {"REGISTER", "UNDO"}

    filepath: StringProperty(
        subtype="FILE_PATH",
        options={"SKIP_SAVE"},
    )  # type: ignore
    files: CollectionProperty(  # type: ignore
        type=bpy.types.OperatorFileListElement,
        options={"HIDDEN", "SKIP_SAVE"},
    )
    directory: StringProperty(  # type: ignore
        subtype="DIR_PATH",
        options={"HIDDEN", "SKIP_SAVE"},
    )
    filter_glob: StringProperty(  # type: ignore
        default="*.stl;*.obj;*.3mf;*.step;*.stp",
        options={"HIDDEN"},
    )
    reset_direct_planes: BoolProperty(default=False, options={"HIDDEN"})  # type: ignore
    mold_type_confirmed: BoolProperty(default=False, options={"HIDDEN"})  # type: ignore
    clear_project_before_import: BoolProperty(  # type: ignore
        default=False,
        options={"HIDDEN"},
    )

    def _invoke_mold_type_selection(self):
        result = bpy.ops.silicone.change_mold_type(
            "INVOKE_DEFAULT",
            continue_to_import=True,
            reset_direct_planes=self.reset_direct_planes,
            clear_project_before_import=self.clear_project_before_import,
            import_filepath=self.filepath,
        )
        if "RUNNING_MODAL" in result or "FINISHED" in result:
            return {"FINISHED"}
        return result

    def _clear_project_if_requested(self, context):
        if not self.clear_project_before_import:
            return
        self.clear_project_before_import = False
        reset_mold_metrics(context)
        with preserve_direct_split_counts(context.scene):
            remove_objects_safely(tuple(bpy.data.objects))

    def _selected_filepaths(self):
        selected_names = [entry.name for entry in self.files if entry.name]
        if not selected_names:
            return [self.filepath] if self.filepath else []
        directory = self.directory or str(Path(self.filepath).parent)
        return [str(Path(directory) / name) for name in selected_names]

    def _import_selected_models(self):
        imported = []
        try:
            for filepath in self._selected_filepaths():
                model = Object(import_model(filepath))
                lineage_record = restore_model_lineage(filepath, model.object)
                imported.append((filepath, model, lineage_record))
        except Exception:
            remove_objects_safely(
                model.object for _filepath, model, _lineage_record in imported
            )
            raise

        # Move every imported object out of the patron namespace first so a
        # source file already named patron_1 cannot force Blender to append
        # .001 to one of the stable batch names.
        for index, (_filepath, model, _lineage_record) in enumerate(imported):
            model.name = f"__moldboxer_batch_import_{index}"
        imported_objects = {model.object for _filepath, model, _lineage in imported}
        remove_objects_safely(
            obj
            for obj in tuple(bpy.data.objects)
            if (
                obj not in imported_objects
                and patron_part_index(obj.name) not in (None, 0)
            )
        )
        for index, (_filepath, model, _lineage_record) in enumerate(imported[1:], 1):
            model.name = f"patron_{index}"
            if model.object.data is not None:
                model.object.data.name = f"patron_{index}_mesh"
        return imported

    def _record_imports(self, context, imported):
        for filepath, _model, lineage_record in imported:
            record_model_imported(
                context,
                file_format=str(filepath).rsplit(".", 1)[-1].upper(),
                lineage_record=lineage_record,
            )

    def invoke(self, context, event):
        clear_pending_generation()
        if not self.mold_type_confirmed:
            return self._invoke_mold_type_selection()

        return ImportHelper.invoke(self, context, event)

    def execute(self, context):
        clear_pending_generation()
        if not self.mold_type_confirmed:
            return self._invoke_mold_type_selection()

        self._clear_project_if_requested(context)
        filepaths = self._selected_filepaths()
        if len(filepaths) > 1:
            start_time = time.perf_counter()
            try:
                imported = self._import_selected_models()
                process_imported_models(
                    context,
                    [model for _filepath, model, _lineage_record in imported],
                    reset_direct_planes=self.reset_direct_planes,
                )
            except Exception as exc:
                logger.exception("Could not import multiple models")
                self.report({"ERROR"}, t("Could not import models: {error}", error=exc))
                return {"CANCELLED"}
            self._record_imports(context, imported)
            logger.info(
                "Multi-model import completed in %.3fs: models=%d",
                time.perf_counter() - start_time,
                len(imported),
            )
            return {"FINISHED"}

        start_time = time.perf_counter()
        phase_start = start_time
        try:
            new_obj = Object(import_model(self.filepath))
        except Exception as exc:
            logger.exception("Could not import model: %s", self.filepath)
            self.report({"ERROR"}, t("Could not import model: {error}", error=exc))
            return {"CANCELLED"}
        lineage_record = restore_model_lineage(self.filepath, new_obj.object)
        raw_import_elapsed = time.perf_counter() - phase_start

        phase_start = time.perf_counter()
        process_imported_model(
            context,
            new_obj,
            reset_direct_planes=self.reset_direct_planes,
        )
        process_elapsed = time.perf_counter() - phase_start
        logger.info(
            "Import operator completed in %.3fs: raw_import=%.3fs, process=%.3fs",
            time.perf_counter() - start_time,
            raw_import_elapsed,
            process_elapsed,
        )
        import_format = str(self.filepath).rsplit(".", 1)[-1].upper()
        record_model_imported(
            context,
            file_format=import_format,
            lineage_record=lineage_record,
        )
        return {"FINISHED"}

    def _create_modal_step_iterator(self, context):
        if not self.mold_type_confirmed:
            return self._invoke_mold_type_selection()
        self._clear_project_if_requested(context)
        filepaths = self._selected_filepaths()
        if len(filepaths) > 1:
            start_time = time.perf_counter()
            try:
                imported = self._import_selected_models()
            except Exception as exc:
                logger.exception("Could not import multiple models")
                self.report({"ERROR"}, t("Could not import models: {error}", error=exc))
                return {"CANCELLED"}
            task = begin_process_imported_models(
                context,
                [model for _filepath, model, _lineage_record in imported],
                reset_direct_planes=self.reset_direct_planes,
            )
            if task is not None:
                yield t("Analyzing imported models..."), lambda: task
            self._record_imports(context, imported)
            logger.info(
                "Multi-model import completed in %.3fs: models=%d",
                time.perf_counter() - start_time,
                len(imported),
            )
            return {"FINISHED"}

        start_time = time.perf_counter()
        try:
            new_obj = Object(import_model(self.filepath))
        except Exception as exc:
            logger.exception("Could not import model: %s", self.filepath)
            self.report({"ERROR"}, t("Could not import model: {error}", error=exc))
            return {"CANCELLED"}
        lineage_record = restore_model_lineage(self.filepath, new_obj.object)
        task = begin_process_imported_model(
            context,
            new_obj,
            reset_direct_planes=self.reset_direct_planes,
        )
        if task is not None:
            yield t("Analyzing imported model..."), lambda: task
        logger.info(
            "Import operator completed in %.3fs",
            time.perf_counter() - start_time,
        )
        record_model_imported(
            context,
            file_format=str(self.filepath).rsplit(".", 1)[-1].upper(),
            lineage_record=lineage_record,
        )
        return {"FINISHED"}


def _model_orientation_target(context):
    return resolve_utility_target(context)


def _has_model_orientation_target(context):
    active = getattr(context, "active_object", None) or getattr(
        context,
        "object",
        None,
    )
    if is_valid_utility_target(active):
        return True
    scene = getattr(context, "scene", None)
    scene_objects = getattr(scene, "objects", None)
    patron = scene_objects.get("patron") if scene_objects is not None else None
    if patron is None:
        patron = bpy.data.objects.get("patron")
    return is_valid_utility_target(patron)


def _auto_orient_with_worker(
    context,
    target,
    *,
    max_tilt_degrees=AUTO_ORIENT_MAX_TILT_DEGREES,
    min_footprint_ratio=0.03,
):
    """Fuse optional fast simplification and Auto Level in one worker call."""

    target.data.calc_loop_triangles()
    triangle_count = len(target.data.loop_triangles)
    target_reduction = get_direct_undercuts_target_reduction(triangle_count)
    result = auto_orient_imported_model(
        target,
        max_tilt_degrees=max_tilt_degrees,
        min_footprint_ratio=min_footprint_ratio,
        target_reduction=target_reduction,
    )
    if result is not None:
        logger.info(
            "Auto-level worker analysis: target=%s source_triangles=%d "
            "analysis_triangles=%d target_reduction=%.2f%%",
            target.name,
            result.source_triangle_count,
            result.analysis_triangle_count,
            result.target_reduction * 100.0,
        )
    return result


class AutoOrientModel(ModalProcessingOperator):
    bl_idname = "silicone.auto_orient_model"
    bl_label = "Auto Level Base"
    bl_description = (
        "Find the largest flat section at any angle, make it the base, then rotate "
        "only around Z so the largest lateral bounding-box face points along X"
    )
    bl_options = {"REGISTER", "UNDO"}
    @classmethod
    def poll(cls, context):
        return _has_model_orientation_target(context)

    def execute(self, context):
        target = _model_orientation_target(context)
        if target is None:
            self.report({"ERROR"}, t("Select a mesh model to orient"))
            return {"CANCELLED"}
        if getattr(target, "mode", "OBJECT") != "OBJECT":
            self.report({"ERROR"}, t("Use Auto Level Base in Object Mode"))
            return {"CANCELLED"}

        result = _auto_orient_with_worker(
            context,
            target,
            max_tilt_degrees=180.0,
            min_footprint_ratio=0.0,
        )
        if result is None:
            self.report(
                {"INFO"},
                t("No usable flat section was found"),
            )
            return {"CANCELLED"}
        refresh_casting_volume(context)
        self.report(
            {"INFO"},
            t(
                "Leveled base by {base_angle:.2f} degrees and aligned the largest "
                "lateral bounding-box face to X with a {z_angle:.2f} degree Z rotation",
                base_angle=result.base_tilt_degrees,
                z_angle=result.z_rotation_degrees,
            ),
        )
        return {"FINISHED"}

    def _create_modal_step_iterator(self, context):
        target = _model_orientation_target(context)
        if target is None:
            self.report({"ERROR"}, t("Select a mesh model to orient"))
            return {"CANCELLED"}
        if getattr(target, "mode", "OBJECT") != "OBJECT":
            self.report({"ERROR"}, t("Use Auto Level Base in Object Mode"))
            return {"CANCELLED"}

        target.data.calc_loop_triangles()
        triangle_count = len(target.data.loop_triangles)
        policy_task = begin_direct_undercuts_target_reduction(triangle_count)
        yield t("Preparing orientation analysis..."), lambda: policy_task
        target_reduction = policy_task.finish()
        task = begin_auto_orient_imported_model(
            target,
            max_tilt_degrees=180.0,
            min_footprint_ratio=0.0,
            target_reduction=target_reduction,
        )
        if task is None:
            self.report({"INFO"}, t("No usable flat section was found"))
            return {"CANCELLED"}

        yield t("Analyzing model orientation..."), lambda: task
        result = task.finish()
        if result is None:
            self.report({"INFO"}, t("No usable flat section was found"))
            return {"CANCELLED"}
        refresh_casting_volume(context)
        self.report(
            {"INFO"},
            t(
                "Leveled base by {base_angle:.2f} degrees and aligned the largest "
                "lateral bounding-box face to X with a {z_angle:.2f} degree Z rotation",
                base_angle=result.base_tilt_degrees,
                z_angle=result.z_rotation_degrees,
            ),
        )
        return {"FINISHED"}


class OrientFaceToBase(ModalProcessingOperator):
    bl_idname = "silicone.orient_face_to_base"
    bl_label = "Pick Base Face"
    bl_description = (
        "Choose a model face as the base, then rotate around Z so the largest "
        "lateral bounding-box face points along X"
    )
    bl_options = {"REGISTER", "UNDO"}
    object_name: StringProperty(options={"HIDDEN"})  # type: ignore

    @classmethod
    def poll(cls, context):
        return _has_model_orientation_target(context)

    def _finish_picker(self, context):
        try:
            context.window.cursor_modal_restore()
        except Exception:
            pass
        workspace = getattr(context, "workspace", None)
        if workspace is not None:
            try:
                workspace.status_text_set(None)
            except Exception:
                pass
        area = getattr(context, "area", None)
        if area is not None:
            area.tag_redraw()

    def _complete_orientation(self, context, target, orientation):
        if orientation is None:
            self.report({"ERROR"}, t("Could not use the selected model face"))
            return {"CANCELLED"}
        refresh_casting_volume(context)
        self.report(
            {"INFO"},
            t(
                "Oriented selected face to the base ({base_angle:.2f} degrees) and "
                "aligned the largest lateral bounding-box face to X "
                "({z_angle:.2f} degree Z rotation)",
                base_angle=orientation.base_tilt_degrees,
                z_angle=orientation.z_rotation_degrees,
            ),
        )
        return {"FINISHED"}

    def _begin_orientation_wait(
        self, context, target, polygon_indices, *, register_handler=True
    ):
        try:
            task = begin_orient_selected_faces_to_base(
                target,
                polygon_indices,
            )
        except Exception:
            logger.exception("Could not orient %s from selected base face", target.name)
            self.report({"ERROR"}, t("Could not orient the selected model face"))
            return {"CANCELLED"}
        if task is None:
            self.report({"ERROR"}, t("Could not use the selected model face"))
            return {"CANCELLED"}

        self._orientation_target = target
        self._orientation_task = task
        self._modal_started_at = time.perf_counter()
        self._modal_status_label = t("Analyzing selected base face...")
        self._modal_last_wait_redraw_at = 0.0
        self._modal_timer = context.window_manager.event_timer_add(
            0.01,
            window=context.window,
        )
        if register_handler:
            context.window_manager.modal_handler_add(self)
        self._set_processing_ui(context, True)
        return {"RUNNING_MODAL"}

    def _finish_orientation_wait(self, context):
        if self._modal_timer is not None:
            context.window_manager.event_timer_remove(self._modal_timer)
            self._modal_timer = None
        self._modal_started_at = None
        self._modal_status_label = None
        self._modal_last_wait_redraw_at = 0.0
        self._set_processing_ui(context, False)

    def _poll_orientation_wait(self, context):
        task = getattr(self, "_orientation_task", None)
        if task is None:
            return None
        self._redraw_waiting_ui(context)
        if not task.done():
            return {"RUNNING_MODAL"}
        try:
            orientation = task.finish()
            result = self._complete_orientation(
                context,
                self._orientation_target,
                orientation,
            )
        except Exception:
            logger.exception("Could not orient the selected model face")
            self.report({"ERROR"}, t("Could not orient the selected model face"))
            result = {"CANCELLED"}
        self._orientation_task = None
        self._orientation_target = None
        self._finish_orientation_wait(context)
        self._record_activity(context, result)
        return result

    def invoke(self, context, event):
        target = _model_orientation_target(context)
        if target is None:
            return {"CANCELLED"}

        self._activity_snapshot = begin_operator_activity(
            self.bl_idname,
            context,
        )

        if getattr(target, "mode", "OBJECT") == "EDIT":
            selected_faces = selected_edit_face_indices(target)
            if not selected_faces:
                self.report({"ERROR"}, t("Select one or more mesh faces first"))
                return {"CANCELLED"}
            result = self._begin_orientation_wait(
                context,
                target,
                selected_faces,
            )
            if result != {"RUNNING_MODAL"}:
                self._record_activity(context, result)
            return result

        if getattr(target, "mode", "OBJECT") != "OBJECT":
            self.report({"ERROR"}, t("Switch to Object or Edit Mode to orient the model"))
            return {"CANCELLED"}
        if getattr(getattr(context, "area", None), "type", None) != "VIEW_3D":
            self.report({"ERROR"}, t("Run Pick Base Face from the 3D View"))
            return {"CANCELLED"}

        self.object_name = target.name
        context.window_manager.modal_handler_add(self)
        try:
            context.window.cursor_modal_set("EYEDROPPER")
        except Exception:
            pass
        workspace = getattr(context, "workspace", None)
        if workspace is not None:
            workspace.status_text_set(
                t("Click the face that should become the base • Esc to cancel")
            )
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if getattr(self, "_orientation_task", None) is not None:
            if event.type != "TIMER":
                return {"RUNNING_MODAL"}
            return self._poll_orientation_wait(context)

        if event.type in {"ESC", "RIGHTMOUSE"}:
            self._finish_picker(context)
            self._record_activity(context, {"CANCELLED"})
            return {"CANCELLED"}
        if event.type in {
            "MIDDLEMOUSE",
            "WHEELUPMOUSE",
            "WHEELDOWNMOUSE",
            "NUMPAD_1",
            "NUMPAD_2",
            "NUMPAD_3",
            "NUMPAD_4",
            "NUMPAD_5",
            "NUMPAD_6",
            "NUMPAD_7",
            "NUMPAD_8",
            "NUMPAD_9",
        }:
            return {"PASS_THROUGH"}
        if event.type != "LEFTMOUSE" or event.value != "PRESS":
            return {"RUNNING_MODAL"}

        target = bpy.data.objects.get(self.object_name)
        if target is None or target.type != "MESH":
            self._finish_picker(context)
            self.report({"ERROR"}, t("The model is no longer available"))
            self._record_activity(context, {"CANCELLED"})
            return {"CANCELLED"}
        hit = raycast_face(context, event, target)
        if hit is None:
            self.report({"WARNING"}, t("Click directly on a model face"))
            return {"RUNNING_MODAL"}

        self._finish_picker(context)
        # The picker already owns a modal handler. Reuse it while orienting so
        # finishing removes the only handler and releases normal mouse selection.
        result = self._begin_orientation_wait(
            context, target, (hit,), register_handler=False
        )
        if result != {"RUNNING_MODAL"}:
            self._record_activity(context, result)
        return result


IMPORT_SMALL_SCALE_WARNING_DIMENSION_MM = 10.0
IMPORT_SMALL_SCALE_TARGET_MIN_DIMENSION_MM = 40.0
IMPORT_LARGE_SCALE_WARNING_DIMENSION_MM = 2000.0
IMPORT_LARGE_SCALE_TARGET_DIMENSION_MM = 100.0
IMPORT_SCALE_WARNING_LIST_LIMIT = 6


def _suggest_import_scale_factor(max_dimension: float):
    """Return a corrective import scale, or None when the size looks plausible."""

    dimension = float(max_dimension)
    if dimension <= 0.0:
        return None
    if dimension < IMPORT_SMALL_SCALE_WARNING_DIMENSION_MM:
        scale_factor = 1.0
        while (
            dimension * scale_factor
            < IMPORT_SMALL_SCALE_TARGET_MIN_DIMENSION_MM
        ):
            scale_factor *= 10.0
        return scale_factor
    if dimension > IMPORT_LARGE_SCALE_WARNING_DIMENSION_MM:
        return IMPORT_LARGE_SCALE_TARGET_DIMENSION_MM / dimension
    return None


def _build_import_scale_plan(models: list[Object]) -> list[dict]:
    plans = []
    for model in models:
        max_dimension = max(model.width, model.depth, model.height)
        scale_factor = _suggest_import_scale_factor(max_dimension)
        if scale_factor is None:
            continue
        plans.append(
            {
                "object_name": model.name,
                "detected_max_dimension": max_dimension,
                "suggested_scale_factor": scale_factor,
                "target_max_dimension": max_dimension * scale_factor,
                "direction": "SMALL" if scale_factor > 1.0 else "LARGE",
            }
        )
    return plans


def _invoke_import_scale_warning(
    models: list[Object],
    *,
    reset_direct_planes: bool,
) -> bool:
    scale_plan = _build_import_scale_plan(models)
    if not scale_plan:
        return False

    first_plan = scale_plan[0]
    bpy.ops.silicone.import_scale_warning_dialog(
        "INVOKE_DEFAULT",
        object_name=models[0].name,
        object_names_json=json.dumps([model.name for model in models]),
        scale_plan_json=json.dumps(scale_plan),
        detected_max_dimension=first_plan["detected_max_dimension"],
        suggested_scale_factor=first_plan["suggested_scale_factor"],
        reset_direct_planes=reset_direct_planes,
    )
    return True


def process_imported_model(
    context,
    model: Object,
    *,
    reset_direct_planes: bool = False,
):
    start_time = time.perf_counter()
    configure_metric_millimeter_units()
    model.select()
    max_dimension = max(model.width, model.depth, model.height)
    dimension_elapsed = time.perf_counter() - start_time
    logger.info(
        "Import model preprocessing started: object=%s max_dimension=%.3f "
        "dimension_check=%.3fs",
        model.name,
        max_dimension,
        dimension_elapsed,
    )
    if _invoke_import_scale_warning(
        [model],
        reset_direct_planes=reset_direct_planes,
    ):
        logger.info(
            "Import processing paused for scale warning after %.3fs",
            time.perf_counter() - start_time,
        )
        return

    finalize_imported_model(
        context,
        model,
        reset_direct_planes=reset_direct_planes,
    )
    logger.info(
        "Import model processing completed in %.3fs",
        time.perf_counter() - start_time,
    )


def process_imported_models(
    context,
    models: list[Object],
    *,
    reset_direct_planes: bool = False,
):
    """Validate and finalize an import batch without separating its models."""

    configure_metric_millimeter_units()
    if not models:
        raise ValueError("No models selected for import")
    models[0].select()
    if _invoke_import_scale_warning(
        models,
        reset_direct_planes=reset_direct_planes,
    ):
        logger.info(
            "Batch import processing paused for scale warning: models=%d",
            len(models),
        )
        return
    finalize_imported_models(
        context,
        models,
        reset_direct_planes=reset_direct_planes,
    )


def begin_process_imported_model(
    context,
    model: Object,
    *,
    reset_direct_planes: bool = False,
):
    """Prepare an import and return its pollable orientation/finalization task."""

    start_time = time.perf_counter()
    configure_metric_millimeter_units()
    model.select()
    if _invoke_import_scale_warning(
        [model],
        reset_direct_planes=reset_direct_planes,
    ):
        logger.info(
            "Import processing paused for scale warning after %.3fs",
            time.perf_counter() - start_time,
        )
        return None
    return begin_finalize_imported_model(
        context,
        model,
        reset_direct_planes=reset_direct_planes,
    )


def begin_process_imported_models(
    context,
    models: list[Object],
    *,
    reset_direct_planes: bool = False,
):
    """Validate an import batch and return its pollable finalization task."""

    configure_metric_millimeter_units()
    if not models:
        raise ValueError("No models selected for import")
    models[0].select()
    if _invoke_import_scale_warning(
        models,
        reset_direct_planes=reset_direct_planes,
    ):
        logger.info(
            "Batch import processing paused for scale warning: models=%d",
            len(models),
        )
        return None
    return begin_finalize_imported_models(
        context,
        models,
        reset_direct_planes=reset_direct_planes,
    )


class ProcessDetectedImport(ModalProcessingOperator):
    bl_idname = "silicone.process_detected_import"
    bl_label = "Process Imported Model"
    bl_description = "Apply Moldboxer preprocessing to an imported STL or OBJ"
    bl_options = {"INTERNAL", "UNDO"}
    object_name: StringProperty(options={"HIDDEN"})  # type: ignore

    def execute(self, context):
        start_time = time.perf_counter()
        imported_object = bpy.data.objects.get(self.object_name)
        if imported_object is None or imported_object.type != "MESH":
            return {"CANCELLED"}

        import_format = str(
            imported_object.get(IMPORT_FILE_FORMAT_KEY, "UNKNOWN")
        )
        source_export_id = str(
            imported_object.get(LINEAGE_SOURCE_EXPORT_ID_KEY, "")
        )
        lineage_record = (
            {"source_export_id": source_export_id}
            if source_export_id
            else None
        )
        imported_object.hide_set(False)
        process_imported_model(context, Object(imported_object))
        record_model_imported(
            context,
            file_format=import_format,
            lineage_record=lineage_record,
        )
        logger.info(
            "Detected import processing completed in %.3fs for %s",
            time.perf_counter() - start_time,
            self.object_name,
        )
        return {"FINISHED"}

    def _create_modal_step_iterator(self, context):
        start_time = time.perf_counter()
        imported_object = bpy.data.objects.get(self.object_name)
        if imported_object is None or imported_object.type != "MESH":
            return {"CANCELLED"}
        import_format = str(
            imported_object.get(IMPORT_FILE_FORMAT_KEY, "UNKNOWN")
        )
        source_export_id = str(
            imported_object.get(LINEAGE_SOURCE_EXPORT_ID_KEY, "")
        )
        lineage_record = (
            {"source_export_id": source_export_id}
            if source_export_id
            else None
        )
        imported_object.hide_set(False)
        task = begin_process_imported_model(context, Object(imported_object))
        if task is not None:
            yield t("Analyzing imported model..."), lambda: task
        record_model_imported(
            context,
            file_format=import_format,
            lineage_record=lineage_record,
        )
        logger.info(
            "Detected import processing completed in %.3fs for %s",
            time.perf_counter() - start_time,
            imported_object.name,
        )
        return {"FINISHED"}


def _invoke_detected_import_mold_type(object_name: str):
    """Open the mold selector from a stable 3D-view context.

    Native file drops are detected from an application timer.  The context
    left behind by the STL import dialog is not guaranteed to contain a
    window, area, or region, which makes ``invoke_popup`` unreliable.  Find a
    live 3D viewport explicitly before invoking the selector.
    """

    window_manager = getattr(bpy.context, "window_manager", None)
    windows = getattr(window_manager, "windows", ()) if window_manager else ()
    for window in windows:
        screen = getattr(window, "screen", None)
        for area in getattr(screen, "areas", ()) if screen else ():
            if getattr(area, "type", None) != "VIEW_3D":
                continue
            window_region = next(
                (
                    region
                    for region in getattr(area, "regions", ())
                    if getattr(region, "type", None) == "WINDOW"
                ),
                None,
            )
            if window_region is None:
                continue
            try:
                with bpy.context.temp_override(
                    window=window,
                    area=area,
                    region=window_region,
                ):
                    return bpy.ops.silicone.change_mold_type(
                        "INVOKE_DEFAULT",
                        detected_import_object=object_name,
                    )
            except (AttributeError, RuntimeError, TypeError):
                logger.debug(
                    "Could not invoke the detected-import selector in a 3D view",
                    exc_info=True,
                )

    try:
        return bpy.ops.silicone.change_mold_type(
            "INVOKE_DEFAULT",
            detected_import_object=object_name,
        )
    except (AttributeError, RuntimeError, TypeError):
        logger.exception(
            "Could not open the mold selector for imported object %s",
            object_name,
        )
        return {"CANCELLED"}


def process_detected_import(imported_object, import_filepath="") -> None:
    clear_pending_generation()
    if import_filepath:
        restore_model_lineage(import_filepath, imported_object)
    # Keep the successfully imported mesh visible while the user chooses a
    # workflow.  Previously it was hidden before opening the popup, so any
    # context failure made a valid STL appear to vanish.
    imported_object.hide_set(False)
    result = _invoke_detected_import_mold_type(imported_object.name)
    if "RUNNING_MODAL" not in result and "FINISHED" not in result:
        imported_object.hide_set(False)
        logger.warning(
            "Mold selector did not open; leaving imported object visible: %s",
            imported_object.name,
        )


def _open_moldboxer_panel_timer():
    window_manager = getattr(bpy.context, "window_manager", None)
    windows = getattr(window_manager, "windows", ()) if window_manager else ()
    for window in windows:
        screen = getattr(window, "screen", None)
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            space = area.spaces.active
            if hasattr(space, "show_region_ui"):
                space.show_region_ui = True
            for region in area.regions:
                if region.type != "UI":
                    continue
                if hasattr(region, "active_panel_category"):
                    try:
                        region.active_panel_category = "Moldboxer"
                    except (AttributeError, TypeError):
                        pass
                region.tag_redraw()
            area.tag_redraw()
    return None


def open_moldboxer_panel(_context) -> None:
    is_registered = getattr(bpy.app.timers, "is_registered", None)
    if callable(is_registered) and is_registered(_open_moldboxer_panel_timer):
        return
    bpy.app.timers.register(_open_moldboxer_panel_timer, first_interval=0.0)


IMPORTED_MODEL_FRAME_DISTANCE_SCALE = 1.2


def frame_imported_model_in_viewports(model) -> None:
    """Frame an imported model once the file browser returns to the 3D view."""
    object_name = model.name
    attempts_remaining = 20

    def _frame_imported_model_timer():
        nonlocal attempts_remaining
        attempts_remaining -= 1

        target = bpy.data.objects.get(object_name)
        if target is None:
            return None

        # The view_selected operator resolves a Python context from this timer.
        # That path can crash Blender while the file browser is closing, so
        # calculate the view from the object's world-space bounds instead.
        try:
            corners = tuple(
                target.matrix_world @ mathutils.Vector(corner)
                for corner in target.bound_box
            )
            if not corners:
                return None
            bounds_min = tuple(
                min(corner[axis] for corner in corners) for axis in range(3)
            )
            bounds_max = tuple(
                max(corner[axis] for corner in corners) for axis in range(3)
            )
            center = tuple(
                (low + high) / 2 for low, high in zip(bounds_min, bounds_max)
            )
            size = max(high - low for low, high in zip(bounds_min, bounds_max))
            if not math.isfinite(size) or size <= 0:
                return None
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            logger.debug(
                "Could not read bounds for imported model %s",
                object_name,
                exc_info=True,
            )
            return None

        window_manager = getattr(bpy.context, "window_manager", None)
        windows = getattr(window_manager, "windows", ()) if window_manager else ()
        framed = False
        for window in windows:
            screen = getattr(window, "screen", None)
            for area in getattr(screen, "areas", ()) if screen else ():
                if area.type != "VIEW_3D":
                    continue
                try:
                    space = area.spaces.active
                    region_3d = getattr(space, "region_3d", None)
                    window_region = next(
                        (
                            region
                            for region in area.regions
                            if region.type == "WINDOW"
                        ),
                        None,
                    )
                    if region_3d is None or window_region is None:
                        continue
                    aspect = max(
                        1.0,
                        window_region.width / max(window_region.height, 1),
                        window_region.height / max(window_region.width, 1),
                    )
                    lens = max(float(space.lens), 1.0)
                    region_3d.view_location = center
                    if region_3d.view_perspective == "CAMERA":
                        region_3d.view_perspective = "PERSP"
                    region_3d.view_distance = max(
                        size
                        * 1.5
                        * aspect
                        * lens
                        / 32.0
                        * IMPORTED_MODEL_FRAME_DISTANCE_SCALE,
                        float(space.clip_start) * 2,
                    )
                    area.tag_redraw()
                    framed = True
                except (AttributeError, ReferenceError, RuntimeError, TypeError):
                    logger.debug(
                        "Could not frame imported model %s in a 3D viewport",
                        object_name,
                        exc_info=True,
                    )

        if framed or attempts_remaining <= 0:
            return None
        return 0.05

    bpy.app.timers.register(
        _frame_imported_model_timer,
        first_interval=0.05,
    )


def _scale_refresh_object(model):
    return model.object if isinstance(model, Object) else model


def _scale_refresh_signature(obj) -> tuple[float, float, float]:
    return tuple(round(float(value), 9) for value in obj.scale)


def _scale_refresh_pointer(obj) -> int:
    try:
        return int(obj.as_pointer())
    except Exception:
        return id(obj)


def _remember_scale_refresh_signature(obj) -> None:
    _SCALE_REFRESH_SIGNATURES[_scale_refresh_pointer(obj)] = (
        _scale_refresh_signature(obj)
    )


def refresh_after_utility_scale(context, model) -> None:
    """Refresh patron-sized helpers and frame the newly scaled mesh."""
    global _SCALE_REFRESH_PENDING_OBJECT_NAME
    try:
        context.view_layer.update()
    except (AttributeError, RuntimeError):
        pass

    raw_model = _scale_refresh_object(model)
    model = model if isinstance(model, Object) else Object(raw_model)
    _remember_scale_refresh_signature(raw_model)
    if _SCALE_REFRESH_PENDING_OBJECT_NAME == raw_model.name:
        _SCALE_REFRESH_PENDING_OBJECT_NAME = ""
    patron_targets = tuple(
        target
        for name in ("patron", "master", "backup")
        if (target := bpy.data.objects.get(name)) is not None
    )
    if any(raw_model is target for target in patron_targets):
        # Restart removes these objects and lets them be recreated from the
        # patron bounds. Do the same after an in-place utility scale so their
        # size, center, and percentage-based heights use the new dimensions.
        remove_skin_base_reference_guide()
        reset_direct_split_planes()
        sync_direct_split_planes_with_scene()
        sync_funnel_reference_line(
            "direct" if is_direct_mold_type(context.scene) else "silicone"
        )
        remove_fixture_height_guide()
        sync_fixture_height_guide(context.scene)
        if bpy.data.objects.get("patron") is not None:
            refresh_casting_volume(context)

    model.select()
    frame_imported_model_in_viewports(model)


def _scale_refresh_timer():
    global _SCALE_REFRESH_PENDING_OBJECT_NAME, _SCALE_REFRESH_TIMER_PENDING
    quiet_time = time.monotonic() - _SCALE_REFRESH_LAST_CHANGE
    if quiet_time < _SCALE_REFRESH_DELAY_SECONDS:
        return max(0.01, _SCALE_REFRESH_DELAY_SECONDS - quiet_time)

    object_name = _SCALE_REFRESH_PENDING_OBJECT_NAME
    _SCALE_REFRESH_PENDING_OBJECT_NAME = ""
    _SCALE_REFRESH_TIMER_PENDING = False
    obj = bpy.data.objects.get(object_name)
    if obj is None or not is_valid_utility_target(obj):
        return None
    try:
        refresh_after_utility_scale(bpy.context, obj)
    except Exception:
        logger.exception("Could not refresh viewport after scaling %s", object_name)
    return None


def schedule_refresh_after_scale(model) -> None:
    """Debounce a helper and camera refresh after a scale interaction."""
    global _SCALE_REFRESH_PENDING_OBJECT_NAME
    global _SCALE_REFRESH_LAST_CHANGE, _SCALE_REFRESH_TIMER_PENDING
    obj = _scale_refresh_object(model)
    if obj is None or not is_valid_utility_target(obj):
        return
    _remember_scale_refresh_signature(obj)
    _SCALE_REFRESH_PENDING_OBJECT_NAME = obj.name
    _SCALE_REFRESH_LAST_CHANGE = time.monotonic()
    if _SCALE_REFRESH_TIMER_PENDING:
        return
    _SCALE_REFRESH_TIMER_PENDING = True
    try:
        bpy.app.timers.register(
            _scale_refresh_timer,
            first_interval=_SCALE_REFRESH_DELAY_SECONDS,
        )
    except Exception:
        _SCALE_REFRESH_TIMER_PENDING = False
        refresh_after_utility_scale(bpy.context, obj)


def _is_active_utils_scale_target(context, obj) -> bool:
    """Limit automatic framing to the active Moldboxer scale-tool target."""

    if obj is None or bool(obj.get("moldboxer_pending_logo", False)):
        return False
    active = getattr(getattr(context, "view_layer", None), "objects", None)
    if getattr(active, "active", None) is not obj:
        return False
    workspace = getattr(context, "workspace", None)
    tools = getattr(workspace, "tools", None)
    if tools is None:
        return False
    try:
        active_tool = tools.from_space_view3d_mode(
            getattr(context, "mode", "OBJECT"),
            create=False,
        )
    except Exception:
        return False
    return str(getattr(active_tool, "idname", "") or "") in (
        _SCALE_REFRESH_TOOL_IDS
    )


@persistent
def _detect_utility_target_scale_change(scene, _depsgraph) -> None:
    live_pointers = set()
    active = getattr(getattr(bpy.context, "view_layer", None), "objects", None)
    active = getattr(active, "active", None)
    changed_objects = []
    for obj in getattr(scene, "objects", ()):
        if not is_valid_utility_target(obj):
            continue
        pointer = _scale_refresh_pointer(obj)
        live_pointers.add(pointer)
        signature = _scale_refresh_signature(obj)
        previous = _SCALE_REFRESH_SIGNATURES.get(pointer)
        _SCALE_REFRESH_SIGNATURES[pointer] = signature
        if previous is not None and signature != previous:
            changed_objects.append(obj)

    for pointer in tuple(_SCALE_REFRESH_SIGNATURES):
        if pointer not in live_pointers:
            _SCALE_REFRESH_SIGNATURES.pop(pointer, None)
    if (
        changed_objects
        and active in changed_objects
        and _is_active_utils_scale_target(bpy.context, active)
    ):
        target = active
        schedule_refresh_after_scale(target)


def register_scale_refresh_handler() -> None:
    unregister_scale_refresh_handler()
    _SCALE_REFRESH_SIGNATURES.clear()
    scene = getattr(bpy.context, "scene", None)
    for obj in getattr(scene, "objects", ()) if scene is not None else ():
        if is_valid_utility_target(obj):
            _remember_scale_refresh_signature(obj)
    bpy.app.handlers.depsgraph_update_post.append(
        _detect_utility_target_scale_change
    )


def unregister_scale_refresh_handler() -> None:
    global _SCALE_REFRESH_PENDING_OBJECT_NAME, _SCALE_REFRESH_TIMER_PENDING
    handlers = bpy.app.handlers.depsgraph_update_post
    for handler in tuple(handlers):
        if getattr(handler, "__name__", "") == "_detect_utility_target_scale_change":
            handlers.remove(handler)
    is_registered = getattr(bpy.app.timers, "is_registered", None)
    if callable(is_registered) and is_registered(_scale_refresh_timer):
        bpy.app.timers.unregister(_scale_refresh_timer)
    _SCALE_REFRESH_SIGNATURES.clear()
    _SCALE_REFRESH_PENDING_OBJECT_NAME = ""
    _SCALE_REFRESH_TIMER_PENDING = False


def _finish_imported_model_after_orientation(
    context,
    model: Object,
    *,
    reset_direct_planes: bool = False,
    start_time: float | None = None,
):
    start_time = start_time or time.perf_counter()
    phase_start = time.perf_counter()
    patron = prepare_imported_patron(context, model)
    lifecycle_elapsed = time.perf_counter() - phase_start
    cached_import_volume = patron.get(IMPORTED_VOLUME_ML_KEY)
    if cached_import_volume is not None:
        del patron[IMPORTED_VOLUME_ML_KEY]

    phase_start = time.perf_counter()
    assign_generated_material(patron)
    patron_material_elapsed = time.perf_counter() - phase_start

    phase_start = time.perf_counter()
    if reset_direct_planes:
        reset_direct_split_planes_to_defaults(context.scene)
    plane_reset_elapsed = time.perf_counter() - phase_start

    phase_start = time.perf_counter()
    refresh_viewport_material_display(context)
    viewport_elapsed = time.perf_counter() - phase_start

    phase_start = time.perf_counter()
    bpy.ops.silicone.restart(
        "EXEC_DEFAULT",
        reload_dev_addon=False,
        preserve_slip_casting_vase_bases=False,
    )
    reset_elapsed = time.perf_counter() - phase_start
    phase_start = time.perf_counter()
    if cached_import_volume is None:
        refresh_casting_volume(context)
        volume_source = "bmesh"
    else:
        context.scene.casting_volume_ml = max(float(cached_import_volume), 0.0)
        volume_source = "orientation_worker_cache"
    volume_elapsed = time.perf_counter() - phase_start

    phase_start = time.perf_counter()
    open_moldboxer_panel(context)
    frame_imported_model_in_viewports(patron)
    select_canonical_patron(context)
    post_setup_elapsed = time.perf_counter() - phase_start
    logger.info(
        "Finalized imported model in %.3fs: lifecycle=%.3fs, "
        "patron_material=%.3fs, plane_reset=%.3fs, viewport=%.3fs, "
        "reset=%.3fs, casting_volume=%.3fs volume_source=%s, "
        "post_setup=%.3fs",
        time.perf_counter() - start_time,
        lifecycle_elapsed,
        patron_material_elapsed,
        plane_reset_elapsed,
        viewport_elapsed,
        reset_elapsed,
        volume_elapsed,
        volume_source,
        post_setup_elapsed,
    )


def _iter_import_orientation_steps(context, model: Object, triangle_count: int):
    """Best-effort worker orientation that must never discard a valid import."""

    if not has_active_server_access():
        return
    try:
        target_reduction = yield begin_direct_undercuts_target_reduction(
            triangle_count
        )
        # All imports use the normal base-down orientation. Slip casting
        # chooses its final assembly orientation only after preparation.
        place_base_on_top = False
        orientation_task = begin_auto_orient_imported_model(
            model.object,
            target_reduction=target_reduction,
            place_base_on_top=place_base_on_top,
        )
        if orientation_task is not None:
            yield orientation_task
    except NearestSurfaceWorkerError as error:
        # Importing and retaining the user's mesh is more important than the
        # optional automatic orientation pass. Licensed worker commands remain
        # fail-closed; this only falls back to the existing Blender-side import
        # finalization and volume calculation.
        logger.warning(
            "Skipping automatic orientation for imported model %s because "
            "the geometry worker is unavailable: %s",
            model.name,
            error,
        )



def begin_finalize_imported_model(
    context,
    model: Object,
    *,
    reset_direct_planes: bool = False,
):
    """Auto-orient an import off-thread, then finish Blender setup on main."""

    start_time = time.perf_counter()
    reset_mold_metrics(context)
    model.object.data.calc_loop_triangles()
    triangle_count = len(model.object.data.loop_triangles)

    def steps():
        yield from _iter_import_orientation_steps(context, model, triangle_count)
        return _finish_imported_model_after_orientation(
            context,
            model,
            reset_direct_planes=reset_direct_planes,
            start_time=start_time,
        )

    return BackgroundTaskSequence(steps())


MULTI_MODEL_X_GAP = 5.0


def _place_additional_patron(model: Object, first_min_z: float, rightmost_x: float):
    model.object.location.z += first_min_z - model.min_z
    model.object.location.x += rightmost_x + MULTI_MODEL_X_GAP - model.min_x
    return model.max_x


def _assign_patron_material(source, target):
    """Use the canonical patron's exact material datablocks on another model."""
    source_materials = list(source.data.materials)
    target.data.materials.clear()
    for material in source_materials:
        if material is not None:
            target.data.materials.append(material)
    if target.data.materials:
        for polygon in target.data.polygons:
            polygon.material_index = 0


def _finish_additional_imported_model(context, model: Object, index: int):
    first = Object(bpy.data.objects["patron"])
    existing_parts = [
        Object(obj)
        for obj in context.scene.objects
        if (
            patron_part_index(obj.name) is not None
            and patron_part_index(obj.name) < index
        )
    ]
    rightmost_x = max(part.max_x for part in existing_parts)
    patron = prepare_imported_patron(
        context,
        model,
        name=f"patron_{index}",
        replace_existing=False,
        center=True,
    )
    _place_additional_patron(Object(patron), first.min_z, rightmost_x)
    _assign_patron_material(first.object, patron)
    return patron


def begin_finalize_imported_models(
    context,
    models: list[Object],
    *,
    reset_direct_planes: bool = False,
):
    """Finalize a selected import batch in order without discarding later models."""
    if not models:
        raise ValueError("No models selected for import")

    def steps():
        yield begin_finalize_imported_model(
            context,
            models[0],
            reset_direct_planes=reset_direct_planes,
        )
        for index, model in enumerate(models[1:], 1):
            model.object.data.calc_loop_triangles()
            triangle_count = len(model.object.data.loop_triangles)
            yield from _iter_import_orientation_steps(context, model, triangle_count)
            _finish_additional_imported_model(context, model, index)

        Object(bpy.data.objects["patron"]).select()
        refresh_viewport_material_display(context)
        return tuple(model.object for model in models)

    return BackgroundTaskSequence(steps())


def finalize_imported_models(
    context,
    models: list[Object],
    *,
    reset_direct_planes: bool = False,
):
    return finish_task_sync(
        begin_finalize_imported_models(
            context,
            models,
            reset_direct_planes=reset_direct_planes,
        )
    )


def finalize_imported_model(
    context,
    model: Object,
    *,
    reset_direct_planes: bool = False,
):
    return finish_task_sync(
        begin_finalize_imported_model(
            context,
            model,
            reset_direct_planes=reset_direct_planes,
        )
    )


class ImportScaleWarningDialog(ModalProcessingOperator):
    bl_idname = "silicone.import_scale_warning_dialog"
    bl_label = "Possible Scale Mismatch"
    bl_description = "Warn when an imported model looks much smaller or larger than expected"
    bl_options = {"INTERNAL", "UNDO"}

    object_name: StringProperty(options={"HIDDEN"})  # type: ignore
    object_names_json: StringProperty(default="", options={"HIDDEN"})  # type: ignore
    scale_plan_json: StringProperty(default="", options={"HIDDEN"})  # type: ignore
    detected_max_dimension: FloatProperty(options={"HIDDEN"})  # type: ignore
    suggested_scale_factor: FloatProperty(options={"HIDDEN"}, default=10.0)  # type: ignore
    reset_direct_planes: BoolProperty(default=False, options={"HIDDEN"})  # type: ignore
    apply_scale_change: BoolProperty(  # type: ignore
        name="Scale imported model",
        description=t("Scale the imported model before preprocessing"),
        default=True,
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=420)

    def _object_names(self):
        try:
            names = json.loads(self.object_names_json)
        except (TypeError, ValueError, json.JSONDecodeError):
            names = []
        if not isinstance(names, list) or not all(
            isinstance(name, str) for name in names
        ):
            names = []
        return names or [self.object_name]

    def _scale_plan(self):
        try:
            plan = json.loads(self.scale_plan_json)
        except (TypeError, ValueError, json.JSONDecodeError):
            plan = []
        if isinstance(plan, list) and plan:
            return plan
        return [
            {
                "object_name": self.object_name,
                "detected_max_dimension": self.detected_max_dimension,
                "suggested_scale_factor": self.suggested_scale_factor,
                "target_max_dimension": (
                    self.detected_max_dimension * self.suggested_scale_factor
                ),
                "direction": (
                    "SMALL" if self.suggested_scale_factor > 1.0 else "LARGE"
                ),
            }
        ]

    def _imported_models(self):
        models = []
        for object_name in self._object_names():
            imported_object = bpy.data.objects.get(object_name)
            if imported_object is None:
                raise ValueError(t("Imported model not found"))
            models.append(Object(imported_object))
        return models

    def _apply_scale_changes(self, models):
        models_by_name = {model.name: model for model in models}
        for item in self._scale_plan():
            imported_model = models_by_name.get(str(item.get("object_name", "")))
            if imported_model is None:
                continue
            scale_factor = float(item["suggested_scale_factor"])
            for axis in range(3):
                imported_model.scale(scale_factor, axis=axis)
            logger.info(
                "Import scale correction applied: object=%s factor=%.6f",
                imported_model.name,
                scale_factor,
            )

    def _begin_finalization(self, context, models):
        if len(models) == 1:
            return begin_finalize_imported_model(
                context,
                models[0],
                reset_direct_planes=self.reset_direct_planes,
            )
        return begin_finalize_imported_models(
            context,
            models,
            reset_direct_planes=self.reset_direct_planes,
        )

    def _finalize_sync(self, context, models):
        if len(models) == 1:
            return finalize_imported_model(
                context,
                models[0],
                reset_direct_planes=self.reset_direct_planes,
            )
        return finalize_imported_models(
            context,
            models,
            reset_direct_planes=self.reset_direct_planes,
        )

    def draw(self, context):
        layout = self.layout
        scale_plan = self._scale_plan()
        if len(self._object_names()) > 1:
            layout.label(
                text=t("Possible Scale Mismatch"),
                icon="ERROR",
            )
            for item in scale_plan[:IMPORT_SCALE_WARNING_LIST_LIMIT]:
                layout.label(
                    text=(
                        f'{item["object_name"]}: '
                        f'{float(item["detected_max_dimension"]):.2f} mm '
                        f'\u2192 {float(item["target_max_dimension"]):.2f} mm'
                    )
                )
            hidden_count = len(scale_plan) - IMPORT_SCALE_WARNING_LIST_LIMIT
            if hidden_count > 0:
                layout.label(text=f"… +{hidden_count}")
            layout.label(text=t("Scale these models before preprocessing?"))
            layout.prop(
                self,
                "apply_scale_change",
                text=t("Scale imported models"),
            )
            return

        item = scale_plan[0]
        layout.label(
            text=t(
                "Imported model max dimension: {dimension:.2f} mm",
                dimension=float(item["detected_max_dimension"]),
            ),
            icon="ERROR",
        )
        if item.get("direction") == "SMALL":
            layout.label(
                text=t("This model is probably imported at a smaller scale.")
            )
            layout.label(
                text=t(
                    "Apply a {scale:.0f}x scale before preprocessing?",
                    scale=float(item["suggested_scale_factor"]),
                )
            )
        else:
            layout.label(
                text=t("This model is probably imported at a larger scale.")
            )
            layout.label(
                text=t(
                    "Scale its largest dimension to {dimension:.0f} mm before preprocessing?",
                    dimension=float(item["target_max_dimension"]),
                )
            )
        layout.prop(self, "apply_scale_change", text=t("Scale imported model"))

    def execute(self, context):
        start_time = time.perf_counter()
        try:
            imported_models = self._imported_models()
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        imported_models[0].select()

        if self.apply_scale_change:
            scale_start = time.perf_counter()
            self._apply_scale_changes(imported_models)
            logger.info(
                "Import scale corrections applied in %.3fs: models=%d",
                time.perf_counter() - scale_start,
                len(self._scale_plan()),
            )

        self._finalize_sync(context, imported_models)
        logger.info(
            "Scale warning import flow completed in %.3fs: models=%d applied=%s",
            time.perf_counter() - start_time,
            len(imported_models),
            self.apply_scale_change,
        )
        return {"FINISHED"}

    def _create_modal_step_iterator(self, context):
        start_time = time.perf_counter()
        try:
            imported_models = self._imported_models()
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        imported_models[0].select()
        if self.apply_scale_change:
            self._apply_scale_changes(imported_models)
        task = self._begin_finalization(context, imported_models)
        progress_message = (
            t("Analyzing imported model...")
            if len(imported_models) == 1
            else t("Analyzing imported models...")
        )
        yield progress_message, lambda: task
        logger.info(
            "Scale warning import flow completed in %.3fs: models=%d applied=%s",
            time.perf_counter() - start_time,
            len(imported_models),
            self.apply_scale_change,
        )
        return {"FINISHED"}

    def cancel(self, context):
        start_time = time.perf_counter()
        try:
            imported_models = self._imported_models()
        except ValueError:
            return

        task = self._begin_finalization(context, imported_models)

        def poll_finalization():
            if not task.done():
                for window in getattr(bpy.context.window_manager, "windows", ()):
                    for area in getattr(window.screen, "areas", ()):
                        area.tag_redraw()
                return 0.25
            try:
                task.finish()
                logger.info(
                    "Scale warning cancelled; import finalized without dialog "
                    "action in %.3fs",
                    time.perf_counter() - start_time,
                )
            except Exception:
                logger.exception("Could not finalize the imported model")
            return None

        bpy.app.timers.register(poll_finalization, first_interval=0.0)


class ExportSTL(ImportHelper, ModalProcessingOperator):
    bl_idname = "silicone.export_stl"
    bl_label = "Export"
    bl_description = (
        "Export all generated mold system parts as separate ready-to-print "
        "files. Select the folder to export to, then click Export"
    )
    bl_options = {"REGISTER", "UNDO"}
    modal_show_progress_overlay = True
    modal_refresh_materials_on_redraw = False

    file_format: StringProperty(default="STL", options={"HIDDEN"})  # type: ignore

    def _normalized_file_format(self):
        return str(getattr(self, "file_format", "STL")).upper()

    def invoke(self, context, event):
        file_format = self._normalized_file_format()
        if file_format == "GLB":
            prefs = get_addon_preferences()
            if not prefs or not getattr(prefs, "dev_mode", False):
                return {"CANCELLED"}
        elif not has_export_access():
            show_export_license_required()
            return {"CANCELLED"}
        return ImportHelper.invoke(self, context, event)

    def _perform_export(self, context):
        file_format = self._normalized_file_format()
        if file_format == "GLB":
            prefs = get_addon_preferences()
            if not prefs or not getattr(prefs, "dev_mode", False):
                return {"CANCELLED"}
        elif not has_export_access():
            show_export_license_required()
            return {"CANCELLED"}
        export_summary = export(self.filepath, file_format=file_format) or {}
        return self._complete_export(context, export_summary, file_format)

    def _begin_background_export(self, context):
        file_format = self._normalized_file_format()
        if file_format == "GLB":
            prefs = get_addon_preferences()
            if not prefs or not getattr(prefs, "dev_mode", False):
                return None
        elif not has_export_access():
            show_export_license_required()
            return None
        return begin_export(self.filepath, file_format=file_format)

    def _complete_export(self, context, export_summary, file_format):
        exported_object_count = int(
            export_summary.get("exported_object_count", 0)
        )
        self._exported_object_count = exported_object_count
        failures = export_summary.get("failed_objects", [])
        skipped = export_summary.get("skipped_objects", [])
        if failures or skipped:
            names = ", ".join(item["name"] for item in [*failures, *skipped])
            self.report(
                {"WARNING"},
                t("Exported {count} objects; {failed} failed, {skipped} skipped: {names}",
                  count=exported_object_count, failed=len(failures), skipped=len(skipped), names=names),
            )
        if exported_object_count == 0:
            self.report({"WARNING"}, t("No objects were exported"))
            return {"CANCELLED"}
        record_model_exported(
            context,
            file_format=file_format,
            exported_object_count=exported_object_count,
            lineage_records=list(export_summary.get("lineage_records", ())),
        )
        prefs = get_addon_preferences()
        if (
            file_format == "STL"
            and prefs
            and is_free_trial_status(getattr(prefs, "auth_stripe_status", ""))
        ):
            consume_trial_export(prefs)
        return {"FINISHED"}

    @staticmethod
    def _clear_export_completed(context):
        if "_moldboxer_export_completed" in context.scene:
            del context.scene["_moldboxer_export_completed"]

    @staticmethod
    def _set_export_in_progress(context, active):
        if active:
            context.scene["_moldboxer_export_in_progress"] = True
        elif "_moldboxer_export_in_progress" in context.scene:
            del context.scene["_moldboxer_export_in_progress"]

    def _mark_export_completed(self, context):
        if getattr(self, "_exported_object_count", 0) > 0:
            context.scene["_moldboxer_export_completed"] = True

    def _create_modal_step_iterator(self, context):
        self._clear_export_completed(context)
        self._set_export_in_progress(context, True)
        self._exported_object_count = 0
        result_holder = {}

        def run_export():
            try:
                export_task = self._begin_background_export(context)
                result_holder["task"] = export_task
                return export_task
            except Exception:
                self._set_export_in_progress(context, False)
                raise

        yield t("Exporting..."), run_export
        export_task = result_holder.get("task")
        if export_task is None:
            result = {"CANCELLED"}
        else:
            result = self._complete_export(
                context,
                export_task.summary,
                self._normalized_file_format(),
            )
        try:
            if result == {"FINISHED"}:
                self._mark_export_completed(context)
            return result
        finally:
            self._set_export_in_progress(context, False)

    def execute(self, context):
        self._clear_export_completed(context)
        self._set_export_in_progress(context, False)
        self._exported_object_count = 0
        result = self._perform_export(context)
        if result == {"FINISHED"}:
            self._mark_export_completed(context)
        return result


class ReloadFromRepo(ModalProcessingOperator):
    bl_idname = "silicone.reload_from_repo"
    bl_label = "Reload From Repo"
    bl_description = "Sync add-on files from dev repo and reload"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        mod = _loaded_addon_module_name(_addon_module_name()) or _addon_module_name()
        addon = context.preferences.addons.get(mod)
        if not addon:
            self.report({"ERROR"}, t("Addon '{mod}' is not loaded", mod=mod))
            return {"CANCELLED"}

        repo_path = addon.preferences.dev_repo_path
        self.report({"INFO"}, t("Repo sync + reload scheduled"))
        # The scheduled reload owns native-package activation. Doing it here
        # would bypass its native-extension preservation and could initialize a
        # second PyArmor runtime before the timer runs.
        return reload_addon_from_repo(repo_path)


class RestoreRecordingWindowLayout(bpy.types.Operator):
    bl_idname = "silicone.restore_recording_window_layout"
    bl_label = "Restore OBS Window"
    bl_description = (
        "Exit fullscreen and restore the Moldboxer main window to the saved "
        "OBS recording size and position"
    )
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        prefs = get_addon_preferences()
        return bool(
            sys.platform == "darwin"
            and prefs
            and getattr(prefs, "dev_mode", False)
        )

    def execute(self, context):
        try:
            from moldboxer_silicone_native.source.recording_window_layout import (
                restore_recording_window_layout,
            )
        except ImportError:
            from .source.recording_window_layout import (
                restore_recording_window_layout,
            )

        try:
            x, y, width, height = restore_recording_window_layout(context)
        except Exception as exc:
            logger.exception("Could not restore the OBS recording window layout")
            self.report({"ERROR"}, t("Could not restore OBS window: {error}", error=exc))
            return {"CANCELLED"}

        self.report(
            {"INFO"},
            t(
                "OBS window restored: {width} x {height} at ({x}, {y})",
                width=width,
                height=height,
                x=x,
                y=y,
            ),
        )
        return {"FINISHED"}


class ClampLockersGenerator(bpy.types.Operator):
    bl_idname = "silicone.generate_clamp_lockers"
    bl_label = "Generate Locking Clamps"
    bl_description = "Generate locking clamp clips from the current clamp settings"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        clamp_clips = create_clip_from_scene(context.scene)
        place_clips_left_of_patron()
        refresh_generated_object_materials()
        refresh_viewport_material_display(context)
        clamp_clips.select()
        return {"FINISHED"}


class ScaleHeight(UtilityTargetOperator):
    bl_idname = "silicone.scale_height"
    bl_label = "Scale Z"
    bl_description = "Scale the object to a target height using the chosen unit"
    bl_options = {"REGISTER", "UNDO"}

    scale_unit: EnumProperty(  # type: ignore
        name="Units",
        description="Measurement unit for the target height",
        items=(
            ("MM", "Millimeters", "Enter the target height in millimeters"),
            ("CM", "Centimeters", "Enter the target height in centimeters"),
            ("IN", "Inches", "Enter the target height in inches"),
        ),
        default="CM",
    )
    scale_height: FloatProperty(  # type: ignore
        name="Height",
        description="Target object height in the selected unit",
        default=10,
        min=0.001,
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        del context
        column = self.layout.column(align=True)
        column.prop(self, "scale_unit")
        column.prop(self, "scale_height")

    def execute(self, context):
        if not super().execute(context):
            return {"CANCELLED"}
        selected_obj = Object(bpy.context.active_object)
        millimeters_per_unit = {
            "MM": 1.0,
            "CM": 10.0,
            "IN": 25.4,
        }
        target_height = self.scale_height * millimeters_per_unit[self.scale_unit]
        scale = target_height / selected_obj.height
        for axis in range(3):
            selected_obj.scale(scale, axis=axis)
        refresh_after_utility_scale(context, selected_obj)
        return {"FINISHED"}


class SplitWithConnector(SelectedObjectOperator):
    bl_idname = "silicone.split_with_connector"
    bl_label = "Split + Connector"
    bl_description = "Split the selected mesh in half and add a 5 mm tall, 10 mm diameter cylindrical connector"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == "MESH"

    @retry_after_heal
    def execute(self, context):
        super().execute(context)
        target_obj = Object(context.active_object)
        original_name = target_obj.name
        tolerance = context.scene.split_connector_tolerance

        target_obj.apply_all_transforms()
        bottom_half, top_half = split_with_connector(target_obj, tolerance)

        bottom_half.name = f"{original_name}_bottom"
        top_half.name = f"{original_name}_top"

        deselect_all_objects()
        bottom_half.object.select_set(True)
        top_half.object.select_set(True)
        context.view_layer.objects.active = bottom_half.object

        self.report(
            {"INFO"},
            t(
                "Split '{name}' with connector tolerance {tolerance:.3f} mm",
                name=original_name,
                tolerance=tolerance,
            ),
        )
        return {"FINISHED"}


class LoginWithGoogle(bpy.types.Operator):
    bl_idname = "silicone.login_google"
    bl_label = "Login with Google"
    bl_description = "Sign in to Moldboxer with Google"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        ok, message = start_google_device_login()
        if not ok:
            clear_pending_generation()
            self.report({"ERROR"}, message)
            show_popup(message, title=t("Google Login"))
            return {"CANCELLED"}
        self.report({"INFO"}, t("Opened browser and started login polling"))
        return {"FINISHED"}


class LoginWithPatreon(bpy.types.Operator):
    bl_idname = "silicone.login_patreon"
    bl_label = "Login with Patreon"
    bl_description = "Sign in to Moldboxer with Patreon"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        ok, message = start_patreon_device_login()
        if not ok:
            clear_pending_generation()
            self.report({"ERROR"}, message)
            show_popup(message, title=t("Patreon Login"))
            return {"CANCELLED"}
        self.report({"INFO"}, t("Opened browser and started login polling"))
        return {"FINISHED"}


class LogoutAccount(bpy.types.Operator):
    bl_idname = "silicone.logout"
    bl_label = "Logout"
    bl_description = "Log out from Moldboxer account"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        if not logout_user():
            self.report({"ERROR"}, t("Unable to clear account state"))
            return {"CANCELLED"}
        self.report({"INFO"}, t("Logged out"))
        return {"FINISHED"}


class StartProTrial(bpy.types.Operator):
    bl_idname = "silicone.start_pro_trial"
    bl_label = "Start 1-Day Pro Trial"
    bl_description = "Enable Pro tools for one day"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        ok, message = start_pro_trial()
        if not ok:
            clear_pending_generation()
            self.report({"ERROR"}, message)
            show_popup(message, title=t("Pro Trial"))
            return {"CANCELLED"}
        self.report({"INFO"}, t("Your 1-day Pro trial is now active"))
        return {"FINISHED"}


class OpenExtensionUpdates(bpy.types.Operator):
    bl_idname = "silicone.open_extension_updates"
    bl_label = "Update"
    bl_description = "Open update settings, enabling online access when possible"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        return open_extension_updates(context, self.report)


class OpenUpgradeLicense(bpy.types.Operator):
    bl_idname = "silicone.open_upgrade_license"
    bl_label = "Open Upgrade License"
    bl_description = "Open the Moldboxer upgrade page"
    bl_options = {"INTERNAL"}

    license_target: EnumProperty(  # type: ignore
        name="License Target",
        items=[
            ("CORE", "Core", "Unlock with Moldboxer Core or higher"),
            ("PRO", "Pro", "Unlock with Moldboxer Pro"),
        ],
        default="CORE",
        options={"HIDDEN"},
    )

    @classmethod
    def description(cls, context, properties):
        if getattr(properties, "license_target", "CORE") == "PRO":
            return t("Unlock with Pro to access this feature")
        return t("Unlock with Core or higher to access this feature")

    def execute(self, context):
        bpy.ops.wm.url_open(url=UPGRADE_LICENSE_URL)
        return {"FINISHED"}


class UpdateAvailableDialog(bpy.types.Operator):
    bl_idname = "silicone.update_available_dialog"
    bl_label = "Update Available"
    bl_description = "Warn when a Moldboxer update is available"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=420)

    def execute(self, context):
        return {"FINISHED"}

    def draw(self, context):
        layout = self.layout
        update_available, update_version = get_extension_update_status()
        version_suffix = (
            f" ({update_version})" if update_available and update_version else ""
        )

        layout.label(
            text=t(
                "Moldboxer update available{version_suffix}.",
                version_suffix=version_suffix,
            ),
            icon="ERROR",
        )
        layout.label(text=t("This version cannot start a new mold until updated."))
        layout.label(text=t("Update Moldboxer before starting or generating a mold."))
        layout.label(text=t("Install the latest version, then restart Blender."))

        if _moldboxer_updater_available():
            layout.operator(
                "moldboxer_updater.install_update",
                text=t("Install Update"),
                icon="IMPORT",
            )
        else:
            box = layout.box()
            box.alert = True
            box.label(text=t("Moldboxer Updater is not installed."), icon="ERROR")
            box.label(text=t("It will be downloaded and installed automatically."))
        layout.operator(
            "silicone.open_extension_updates",
            text=t("Open Extensions"),
            icon="PREFERENCES",
        )


class ConnectionErrorDialog(bpy.types.Operator):
    bl_idname = "silicone.connection_error_dialog"
    bl_label = "Connection Error"
    bl_description = "Warn when Moldboxer cannot connect to the server"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=430)

    def execute(self, context):
        return {"FINISHED"}

    def draw(self, context):
        layout = self.layout
        layout.label(text=t("There was a connection error."), icon="ERROR")
        layout.label(text=t("VPNs are known for creating connection issues."))
        layout.label(text=t("If you are using a VPN, please disable it and restart."))


class CopyLastOperatorLogs(bpy.types.Operator):
    bl_idname = "silicone.copy_last_operator_logs"
    bl_label = "Copy Last Operator Logs"
    bl_description = "Copy the last Moldboxer operator execution log to the clipboard"

    def execute(self, context):
        log_text = read_last_operator_log()
        log_path = get_last_operator_log_path()
        if not log_text:
            self.report({"WARNING"}, t("No operator logs found"))
            return {"CANCELLED"}

        context.window_manager.clipboard = log_text
        self.report(
            {"INFO"},
            t("Copied last operator logs from {path}", path=str(log_path)),
        )
        return {"FINISHED"}


class ResetBackgroundColor(bpy.types.Operator):
    bl_idname = "silicone.reset_background_color"
    bl_label = "Reset Background"
    bl_description = "Reset the world background color"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        reset_background_to_default(context)
        return {"FINISHED"}


class ResetSettingsToDefault(bpy.types.Operator):
    bl_idname = "silicone.reset_settings_to_default"
    bl_label = "Reset Settings"
    bl_description = "Reset all settings panel values to their defaults"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        reset_scene_properties_to_defaults(
            context.scene, SETTINGS_SCENE_PROPERTIES + preparation_settings.setting_keys(),
        )
        context.scene.clamp_depth = default_clamp_depth(
            context.scene.mold_type_preview
        )
        if is_direct_mold_type(context.scene.mold_type_preview):
            context.scene.undercuts_quality = "FAST"
        reset_direct_split_planes()
        return {"FINISHED"}


class AccountDialog(bpy.types.Operator):
    bl_idname = "silicone.account_dialog"
    bl_label = "Account"
    bl_description = "Manage your Moldboxer account"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=260)

    def execute(self, context):
        return {"FINISHED"}

    def draw(self, context):
        layout = self.layout
        prefs = get_addon_preferences()

        identity = layout.box()
        identity.label(text=f"Moldboxer {VERSION}", icon="INFO")

        if prefs is None:
            identity.label(
                text=t("Unable to access account state"),
                icon="ERROR",
            )
            return

        if getattr(prefs, "auth_polling_active", False):
            status_text = t("Waiting for login confirmation...")
            status_icon = "SORTTIME"
        elif getattr(prefs, "auth_logged_in", False):
            status_text = get_login_status_text(
                str(getattr(prefs, "auth_provider", "")),
                str(getattr(prefs, "auth_tier", "")),
                str(getattr(prefs, "auth_stripe_status", "")),
            )
            status_icon = "CHECKMARK"
        else:
            status_text = t("Not logged in")
            status_icon = "USER"
        identity.label(text=status_text, icon=status_icon)

        col = layout.column(align=True)
        if getattr(prefs, "auth_logged_in", False):
            col.operator("silicone.logout", text=t("Logout"), icon="LOOP_BACK")
            if bool(getattr(prefs, "auth_pro_trial_available", False)):
                col.operator(
                    "silicone.start_pro_trial",
                    text=t("Start 1-Day Pro Trial"),
                    icon="SOLO_ON",
                )
        else:
            if getattr(prefs, "dev_mode", False):
                col.operator(
                    "silicone.login_google",
                    text=t("Login with Google"),
                    icon="URL",
                )
            else:
                col.operator(
                    "silicone.login_google",
                    text=t("Start Free Trial"),
                    icon="URL",
                )
                col.operator(
                    "silicone.login_google",
                    text=t("Login with Google"),
                    icon="URL",
                )
            col.operator(
                "silicone.login_patreon",
                text=t("Login with Patreon"),
                icon="URL",
            )
            join = col.operator("wm.url_open", text=t("Get License"), icon="URL")
            join.url = "https://moldboxer.com/buy"

        col.prop(prefs, "language", text=t("Language"), icon="WORLD")
        col.prop(prefs, "material_units", text=t("Unit System"))

        update_available, update_version = get_extension_update_status()
        update_row = col.row(align=True)
        update_row.alert = update_available
        update_text = t("Update")
        if update_available:
            update_text = t("Update Available")
            if update_version:
                update_text = f"{t('Update Available')} ({update_version})"
        update_row.operator(
            "silicone.open_extension_updates",
            text=update_text,
            icon="ERROR" if update_available else "FILE_REFRESH",
        )


_AUTH_REQUIRED_DIALOG_DELAY_SECONDS = 0.25
_auth_required_dialog_pending = False


def _open_auth_required_dialog_deferred():
    global _auth_required_dialog_pending
    _auth_required_dialog_pending = False
    bpy.ops.silicone.auth_required_dialog("INVOKE_DEFAULT", deferred=True)
    return None


class AuthRequiredDialog(bpy.types.Operator):
    bl_idname = "silicone.auth_required_dialog"
    bl_label = "Login Required"
    bl_description = "This feature requires account login"
    bl_options = {"INTERNAL"}

    deferred: BoolProperty(options={"HIDDEN", "SKIP_SAVE"})  # type: ignore

    def invoke(self, context, event):
        global _auth_required_dialog_pending
        if not self.deferred:
            if not _auth_required_dialog_pending:
                _auth_required_dialog_pending = True
                bpy.app.timers.register(
                    _open_auth_required_dialog_deferred,
                    first_interval=_AUTH_REQUIRED_DIALOG_DELAY_SECONDS,
                )
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(self, width=360)

    def _cancel_unstarted_login(self):
        prefs = get_addon_preferences()
        if prefs is None or (
            not getattr(prefs, "auth_polling_active", False)
            and not getattr(prefs, "auth_refresh_token", "")
        ):
            clear_pending_generation()

    def cancel(self, context):
        self._cancel_unstarted_login()

    def execute(self, context):
        self._cancel_unstarted_login()
        return {"FINISHED"}

    def draw(self, context):
        layout = self.layout
        prefs = get_addon_preferences()

        if prefs is None:
            layout.label(text=t("Unable to access account state"), icon="ERROR")
            return

        if getattr(prefs, "auth_polling_active", False):
            pending_provider = str(getattr(prefs, "auth_pending_provider", "")).title()
            wait_text = t("Waiting for login confirmation...")
            if pending_provider:
                wait_text = t(
                    "Waiting for {provider} login confirmation...",
                    provider=pending_provider,
                )
            layout.label(text=wait_text, icon="SORTTIME")
            layout.operator("silicone.logout", text=t("Cancel Login"), icon="X")
            return

        if getattr(prefs, "auth_logged_in", False):
            provider = str(getattr(prefs, "auth_provider", ""))
            tier = str(getattr(prefs, "auth_tier", ""))
            stripe_status = str(getattr(prefs, "auth_stripe_status", ""))
            status_text = get_login_status_text(provider, tier, stripe_status)
            layout.label(text=status_text, icon="CHECKMARK")
            if bool(getattr(prefs, "auth_pro_trial_available", False)):
                layout.operator(
                    "silicone.start_pro_trial",
                    text=t("Start 1-Day Pro Trial"),
                    icon="SOLO_ON",
                )
            layout.operator("silicone.logout", text=t("Logout"), icon="LOOP_BACK")
            return

        col = layout.column(align=True)
        if getattr(prefs, "dev_mode", False):
            col.operator(
                "silicone.login_google",
                text=t("Login with Google"),
                icon="URL",
            )
        else:
            col.operator(
                "silicone.login_google",
                text=t("Start Free Trial"),
                icon="URL",
            )
            col.operator(
                "silicone.login_google", text=t("Login with Google"), icon="URL"
            )
        col.operator(
            "silicone.login_patreon", text=t("Login with Patreon"), icon="URL"
        )
        join = col.operator("wm.url_open", text=t("Get License"), icon="URL")
        join.url = "https://moldboxer.com/buy"


class ProRequiredDialog(bpy.types.Operator):
    bl_idname = "silicone.pro_required_dialog"
    bl_label = "Pro Membership Required"
    bl_description = "This feature requires a Pro membership"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=360)

    def execute(self, context):
        return {"FINISHED"}

    def draw(self, context):
        layout = self.layout
        layout.label(text=t("Moldboxer Pro license required."), icon="LOCKED")
        layout.label(text=t("This feature is enabled with the Pro tier."))
        layout.label(text=t("Buy Pro or log in to a Pro account."))
        join = layout.operator("wm.url_open", text=t("Buy Pro License"), icon="URL")
        join.url = UPGRADE_LICENSE_URL
        prefs = get_addon_preferences()

        if prefs is None:
            layout.label(text=t("Unable to access account state"), icon="ERROR")
            return

        if getattr(prefs, "auth_polling_active", False):
            pending_provider = str(getattr(prefs, "auth_pending_provider", "")).title()
            wait_text = t("Waiting for login confirmation...")
            if pending_provider:
                wait_text = t(
                    "Waiting for {provider} login confirmation...",
                    provider=pending_provider,
                )
            layout.label(text=wait_text, icon="SORTTIME")
            layout.operator("silicone.logout", text=t("Cancel Login"), icon="X")
            return

        if getattr(prefs, "auth_logged_in", False):
            provider = str(getattr(prefs, "auth_provider", ""))
            tier = str(getattr(prefs, "auth_tier", ""))
            stripe_status = str(getattr(prefs, "auth_stripe_status", ""))
            status_text = get_login_status_text(provider, tier, stripe_status)
            layout.label(text=status_text, icon="CHECKMARK")
            layout.operator("silicone.logout", text=t("Logout"), icon="LOOP_BACK")
            return

        layout.operator(
            "silicone.login_google", text=t("Login with Google"), icon="URL"
        )
        layout.operator(
            "silicone.login_patreon", text=t("Login with Patreon"), icon="URL"
        )


class BasicRequiredDialog(bpy.types.Operator):
    bl_idname = "silicone.basic_required_dialog"
    bl_label = "Core License Required"
    bl_description = "This feature requires the Moldboxer Core license or higher"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=360)

    def execute(self, context):
        return {"FINISHED"}

    def draw(self, context):
        layout = self.layout
        layout.label(text=t("Moldboxer Core license required."), icon="LOCKED")
        layout.label(text=t("This feature requires Moldboxer Core or higher."))
        layout.label(text=t("Upgrade at moldboxer.com or log in to a higher tier."))
        join = layout.operator("wm.url_open", text=t("Go to Website"), icon="URL")
        join.url = WEBSITE_URL
        prefs = get_addon_preferences()

        if prefs is None:
            layout.label(text=t("Unable to access account state"), icon="ERROR")
            return

        if getattr(prefs, "auth_polling_active", False):
            pending_provider = str(getattr(prefs, "auth_pending_provider", "")).title()
            wait_text = t("Waiting for login confirmation...")
            if pending_provider:
                wait_text = t(
                    "Waiting for {provider} login confirmation...",
                    provider=pending_provider,
                )
            layout.label(text=wait_text, icon="SORTTIME")
            layout.operator("silicone.logout", text=t("Cancel Login"), icon="X")
            return

        if getattr(prefs, "auth_logged_in", False):
            provider = str(getattr(prefs, "auth_provider", ""))
            tier = str(getattr(prefs, "auth_tier", ""))
            stripe_status = str(getattr(prefs, "auth_stripe_status", ""))
            status_text = get_login_status_text(provider, tier, stripe_status)
            layout.label(text=status_text, icon="CHECKMARK")
            layout.operator("silicone.logout", text=t("Logout"), icon="LOOP_BACK")
            return

        layout.operator(
            "silicone.login_google", text=t("Login with Google"), icon="URL"
        )
        layout.operator(
            "silicone.login_patreon", text=t("Login with Patreon"), icon="URL"
        )


class ExportLicenseRequiredDialog(bpy.types.Operator):
    bl_idname = "silicone.export_license_required_dialog"
    bl_label = "Moldboxer License Required"
    bl_description = "This function requires a Moldboxer License"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=380)

    def execute(self, context):
        return {"FINISHED"}

    def draw(self, context):
        layout = self.layout
        prefs = get_addon_preferences()
        stripe_status = (
            str(getattr(prefs, "auth_stripe_status", "")).upper() if prefs else ""
        )
        trial_exports_remaining = get_trial_exports_remaining(prefs)

        if is_free_trial_status(stripe_status):
            layout.label(text=t("Free Trial exports are exhausted."), icon="LOCKED")
            layout.label(
                text=t(
                    "Free Trial exports remaining: {remaining}.",
                    remaining=trial_exports_remaining,
                )
            )
            layout.label(text=t("Upgrade your membership to keep exporting files."))
        else:
            layout.label(
                text=t("This function is available only with a Moldboxer License."),
                icon="LOCKED",
            )
            layout.label(text=t("Get it on the website."))
        join = layout.operator("wm.url_open", text=t("Go to Website"), icon="URL")
        join.url = WEBSITE_URL


class NewProject(ModalProcessingOperator):
    requires_current_extension = True
    bl_idname = "silicone.new_project"
    bl_label = "New"
    bl_description = "Clear the current project and import a new master model"
    bl_options = {"REGISTER"}
    modal_enabled = False

    def execute(self, context):
        """Choose the mold type, then clear the project and import a model."""
        clear_pending_generation()
        if "_moldboxer_export_completed" in context.scene:
            del context.scene["_moldboxer_export_completed"]
        if "_moldboxer_export_in_progress" in context.scene:
            del context.scene["_moldboxer_export_in_progress"]
        clear_extraction_direction_arrows()
        bpy.ops.silicone.import_model(
            "INVOKE_DEFAULT",
            False,
            reset_direct_planes=True,
            clear_project_before_import=True,
        )
        return {"FINISHED"}


class Restart(ModalProcessingOperator):
    bl_idname = "silicone.restart"
    bl_label = "Restart"
    bl_description = (
        "Remove everything except the patron; in dev mode, reload from the repo"
    )
    bl_options = {"REGISTER", "UNDO"}

    reload_dev_addon: BoolProperty(  # type: ignore
        name="Reload Dev Add-on",
        default=True,
        options={"HIDDEN"},
    )
    preserve_slip_casting_vase_bases: BoolProperty(  # type: ignore
        name="Preserve Slip Casting Vase Bases",
        default=False,
        options={"HIDDEN"},
    )
    keep_object_name: StringProperty(default="", options={"HIDDEN"})  # type: ignore

    def execute(self, context):
        """Remove everything except the patron"""
        from .properties import sync_slip_casting_settings

        from .source.components.slip_casting_silicone import restore_slip_casting_panel_on_restart

        restore_slip_casting_panel_on_restart(context.scene)
        sync_slip_casting_settings(context.scene)
        if "_moldboxer_export_completed" in context.scene:
            del context.scene["_moldboxer_export_completed"]
        if "_moldboxer_export_in_progress" in context.scene:
            del context.scene["_moldboxer_export_in_progress"]
        clear_extraction_direction_arrows()
        reset_mold_metrics(context)
        remove_skin_master_half_preview()
        remove_skin_base_reference_guide()
        backup = bpy.data.objects.get("backup")
        patron = bpy.data.objects.get("patron")
        master = bpy.data.objects.get("master")
        clean_master = bpy.data.objects.get("_slip_casting_restart_master")
        target = clean_master or backup or master or patron
        keep_names = {target.name} if target is not None else set()
        keep_names.update(
            obj.name
            for obj in bpy.data.objects
            if patron_part_index(obj.name) not in (None, 0)
        )
        if (
            self.preserve_slip_casting_vase_bases
            and is_slip_casting_vase_type(context.scene.mold_type_preview)
        ):
            keep_names.update(
                obj.name
                for obj in bpy.data.objects
                if bool(obj.get(SLIP_CASTING_VASE_BASE_KEY, False))
            )
        if self.keep_object_name in bpy.data.objects:
            keep_names.add(self.keep_object_name)
        with preserve_direct_split_counts(context.scene):
            remove_objects_safely(
                obj for obj in tuple(bpy.data.objects) if obj.name not in keep_names
            )

        if target is not None:
            restore_slip_casting_preparation_orientation(target)
            context.view_layer.update()
            target.name = "patron"
            if "moldboxer_slip_casting_restart_master" in target:
                del target["moldboxer_slip_casting_restart_master"]
            if target.data is not None:
                target.data.name = "patron_mesh"
            if DECIMATED_PATRON_KEY in target:
                del target[DECIMATED_PATRON_KEY]
            if "moldboxer_slip_casting_funnels_built" in target:
                del target["moldboxer_slip_casting_funnels_built"]
            target.hide_select = False
            target.hide_set(False)
            target.hide_viewport = False
            target.hide_render = False
            obj_ = Object(target)
            obj_.select()
            bpy.ops.silicone.center_obj()
        sync_patron_selection_for_master_filler(context)
        reset_direct_split_planes()

        prefs = get_addon_preferences()
        if (
            self.reload_dev_addon
            and prefs
            and getattr(prefs, "dev_mode", False)
        ):
            reload_result = reload_addon_from_repo(
                getattr(prefs, "dev_repo_path", "")
            )
            if reload_result != {"FINISHED"}:
                self.report({"ERROR"}, t("Could not schedule repo sync + reload"))
                return reload_result
            self.report({"INFO"}, t("Repo sync + reload scheduled"))
        select_canonical_patron(context)
        return {"FINISHED"}


class TestOperator(ModalProcessingOperator):
    bl_idname = "silicone.test_operator"
    bl_label = "Test Operator"
    bl_description = "Build a worker-generated box envelope"
    bl_options = {"REGISTER", "UNDO"}
    copy_operator_log_to_clipboard_on_finish = True
    modal_enabled = False

    @classmethod
    def poll(cls, context):
        obj = context.view_layer.objects.active
        return bool(obj is not None and obj.type == "MESH" and obj.select_get())

    def execute(self, context):
        obj = context.view_layer.objects.active or context.object
        if obj is None or obj.type != "MESH":
            self.report({"ERROR"}, t("No active mesh object found"))
            return {"CANCELLED"}

        start_time = time.perf_counter()
        source_target = Object(obj)
        voxel_size = get_box_voxel_size(context.scene.box_quality)
        source_target.object.data.calc_loop_triangles()
        source_triangle_count = len(source_target.object.data.loop_triangles)
        logger.info(
            "Worker envelope test operator start: source_target=%s "
            "vertices=%d polygons=%d triangles=%d voxel_size=%.6f "
            "offset=%.6f wraps=2 build_from_sphere=%s",
            source_target.name,
            len(source_target.object.data.vertices),
            len(source_target.object.data.polygons),
            source_triangle_count,
            voxel_size,
            float(context.scene.box_gap),
            bool(context.scene.build_from_sphere),
        )

        simplification_start = time.perf_counter()
        reused_build_patron = bool(
            source_target.object.get(DECIMATED_PATRON_KEY, False)
        )
        target = source_target
        simplify_target_reduction = (
            None
            if reused_build_patron
            else get_adaptive_target_reduction(source_triangle_count)
        )
        simplification_elapsed = time.perf_counter() - simplification_start
        comparison_triangle_count = (
            source_triangle_count
            if simplify_target_reduction is None
            else round(
                source_triangle_count * (1.0 - simplify_target_reduction)
            )
        )
        logger.info(
            "Worker envelope fused target requested: source=%s "
            "source_triangles=%d requested_target_triangles=%d "
            "target_reduction=%s reused_build_patron=%s elapsed=%.3fs",
            source_target.name,
            source_triangle_count,
            comparison_triangle_count,
            (
                "none"
                if simplify_target_reduction is None
                else f"{simplify_target_reduction * 100.0:.2f}%"
            ),
            reused_build_patron,
            simplification_elapsed,
        )

        worker_start = time.perf_counter()
        envelope = WorkerEnvelopeTest(
            target,
            voxel_size,
            distance=context.scene.box_gap,
            n_wraps=2,
            build_from_sphere=context.scene.build_from_sphere,
            cut_bot=False,
            target_cache_object=source_target.object,
            simplify_target_reduction=simplify_target_reduction,
        )
        worker_elapsed = time.perf_counter() - worker_start
        comparison_triangle_count = envelope.worker_target_triangle_count
        assign_generated_material(envelope.object)
        logger.info(
            "Worker envelope benchmark complete: target=%s "
            "target_triangles=%d output=%s vertices=%d polygons=%d "
            "target_extract=%.3fs target_build=%.3fs pipeline=%.3fs "
            "total=%.3fs",
            target.name,
            comparison_triangle_count,
            envelope.name,
            len(envelope.object.data.vertices),
            len(envelope.object.data.polygons),
            envelope.worker_target_extraction_seconds,
            envelope.worker_target_build_seconds,
            envelope.worker_pipeline_seconds,
            worker_elapsed,
        )

        refresh_viewport_material_display(context)

        deselect_all_objects()
        source_target.object.hide_set(False)
        source_target.object.hide_viewport = False
        source_target.object.select_set(True)
        context.view_layer.objects.active = source_target.object
        force_viewport_redraw(context)

        elapsed = time.perf_counter() - start_time
        logger.info(
            "Worker envelope test operator complete: source_target=%s "
            "target_triangles=%d fused_target_build=%.3fs "
            "worker_output=%s worker=%.3fs total=%.3fs",
            source_target.name,
            comparison_triangle_count,
            envelope.worker_target_build_seconds,
            envelope.name,
            worker_elapsed,
            elapsed,
        )
        self.report(
            {"INFO"},
            t(
                "Target {target:.2f}s; worker {worker:.2f}s",
                target=envelope.worker_target_build_seconds,
                worker=worker_elapsed,
            ),
        )
        return {"FINISHED"}


class _ClearUndercutsBehavior:
    bl_idname = "silicone.new_clear_undercuts"
    bl_label = "Clear Undercuts"
    bl_description = "Clear undercuts on the selected target object"
    bl_options = {"REGISTER", "UNDO"}
    modal_show_progress_overlay = True
    modal_wait_redraw_interval = 0.1

    extraction_type: EnumProperty(  # type: ignore
        name="Extraction",
        description="Direction used to clear undercuts",
        items=(
            ("LATERAL", "Lateral", "Clear undercuts in both lateral directions"),
            ("VERTICAL", "Vertical", "Clear undercuts vertically upward"),
        ),
        default="LATERAL",
    )
    extraction_mode: EnumProperty(  # type: ignore
        name=t("Type"),
        description=(
            "Choose the extraction-direction policy and candidate-cost "
            "precision"
        ),
        items=(
            (
                "OPTIMIZED",
                t("Optimized (Beta)"),
                "Minimize silicone while preserving a valid extraction path",
            ),
            (
                "EASY_EXTRACTION",
                t("Easy Extraction"),
                "Use either a purely lateral direction or straight upward",
            ),
        ),
        default="EASY_EXTRACTION",
    )
    undercuts_quality: EnumProperty(  # type: ignore
        name="Detail",
        description="Voxel detail used when clearing undercuts, using the master quality sizes",
        items=(
            ("VERY_LOW", "Very Low", "Lowest detail, fastest processing", 5),
            ("DRAFT", "Draft", "Low detail, fast processing", 4),
            ("FAST", "Fast", "Low detail, fast processing", 0),
            ("MID", "Balanced", "Medium detail", 1),
            ("HIGH", "High Detail", "Slow but detailed", 2),
            ("VERY HIGH", "Very High Detail", "Very detailed", 6),
            ("ULTRA", "Ultra Detail", "Very detailed", 3),
            ("EXTREME", "Extreme Detail", "Maximum detail, slowest processing", 7),
        ),
        default="MID",
    )

    def invoke(self, context, event):
        if is_lite_tier():
            show_basic_membership_required()
            return {"CANCELLED"}
        self.extraction_type = context.scene.undercuts_extraction_type
        stored_extraction_mode = getattr(
            context.scene,
            "clear_undercuts_mode",
            "EASY_EXTRACTION",
        )
        self.extraction_mode = (
            stored_extraction_mode
            if stored_extraction_mode in {"OPTIMIZED", "EASY_EXTRACTION"}
            else "OPTIMIZED"
        )
        self.undercuts_quality = context.scene.undercuts_quality
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        mold_type = get_mold_type(context.scene.mold_type_preview)
        if self._uses_split_plane_extraction(mold_type):
            self.layout.prop(self, "extraction_mode")
        else:
            self.layout.prop(self, "extraction_type")
        self.layout.prop(self, "undercuts_quality")

    def _uses_split_plane_extraction(self, mold_type) -> bool:
        return (
            mold_type.generate_operator == "silicone.automatic_mold"
            or is_silicone_multipart_type(mold_type.identifier)
        )

    def _split_plane_extraction_opening(self, context, mold_type) -> str:
        if is_silicone_multipart_type(mold_type.identifier):
            return "base_open"
        return resolve_direct_mold_opening(
            mold_type.identifier,
            context.scene.direct_mold_opening,
        )

    def _force_perpendicular_single_split(self, _split_plane_specs) -> bool:
        return False

    def _split_plane_boundary_specs(self, target, _split_plane_specs):
        return [bottom_reference_plane(target)]

    def _set_clear_undercuts_progress(self, context, _label: str = "") -> None:
        self._modal_status_label = "Clearing undercuts"
        force_viewport_redraw(context)

    @staticmethod
    def _remove_clear_undercuts_analysis_object(analysis_object) -> None:
        if analysis_object is None:
            return
        raw_object = getattr(analysis_object, "object", analysis_object)
        try:
            analysis_mesh = raw_object.data
            object_name = raw_object.name
        except ReferenceError:
            return
        if object_name in bpy.data.objects:
            remove_objects_safely((raw_object,))
        if (
            analysis_mesh is not None
            and getattr(analysis_mesh, "users", 0) == 0
            and analysis_mesh.name in bpy.data.meshes
        ):
            bpy.data.meshes.remove(analysis_mesh)

    @classmethod
    def poll(cls, context):
        patron = context.scene.objects.get("patron")
        obj = context.view_layer.objects.active
        return bool(
            (patron is not None and patron.type == "MESH")
            or (obj is not None and obj.type == "MESH" and obj.select_get())
        )

    def _create_modal_step_iterator(self, context):
        self._clear_undercuts_result = {"FINISHED"}

        def remember_result(result):
            self._clear_undercuts_result = result
            return result

        yield (
            "Clearing undercuts",
            lambda: self._begin_clear_undercuts_operation(context).then(
                remember_result
            ),
        )
        return self._clear_undercuts_result

    def execute(self, context):
        return finish_task_sync(self._begin_clear_undercuts_operation(context))

    def _begin_clear_undercuts_operation(self, context):
        sequence = BackgroundTaskSequence(
            self._clear_undercuts_operation_steps(context)
        )
        sequence.redraw_interval = 0.1
        return sequence

    def _clear_undercuts_operation_steps(self, context):
        if is_lite_tier():
            show_basic_membership_required()
            return {"CANCELLED"}

        operation_start = time.perf_counter()
        phase_start = time.perf_counter()
        cursor_to_origin(context)
        logger.debug(
            "Clear undercuts operator setup: elapsed=%.3fs",
            time.perf_counter() - phase_start,
        )
        phase_start = time.perf_counter()
        ensure_direct_patron_backup()
        logger.debug(
            "Clear undercuts backup preparation: elapsed=%.3fs",
            time.perf_counter() - phase_start,
        )

        phase_start = time.perf_counter()
        has_active_access = has_active_server_access()
        logger.debug(
            "Clear undercuts active-access check: allowed=%s elapsed=%.3fs",
            has_active_access,
            time.perf_counter() - phase_start,
        )
        if not has_active_access:
            show_active_membership_required(self)
            return {"CANCELLED"}

        phase_start = time.perf_counter()
        has_basic_access = has_basic_server_access()
        logger.debug(
            "Clear undercuts basic-access check: allowed=%s elapsed=%.3fs",
            has_basic_access,
            time.perf_counter() - phase_start,
        )
        if not has_basic_access:
            show_basic_membership_required()
            return {"CANCELLED"}

        temporary_analysis_object = None
        try:
            mold_type = get_mold_type(context.scene.mold_type_preview)
            is_direct_mold = self._uses_split_plane_extraction(mold_type)
            vertical = not is_direct_mold and self.extraction_type == "VERTICAL"
            direct_easy_extraction = (
                is_direct_mold and self.extraction_mode == "EASY_EXTRACTION"
            )
            direct_optimized_extraction = (
                is_direct_mold
                and self.extraction_mode in {"OPTIMIZED", "PRECISE"}
            )
            direct_precise_cost = (
                is_direct_mold and self.extraction_mode == "PRECISE"
            )
            direct_mold_opening = (
                self._split_plane_extraction_opening(context, mold_type)
                if is_direct_mold
                else ""
            )
            direct_top_funnel_opening = direct_mold_opening == "top_funnel"
            restrict_bottom_extraction = (
                direct_top_funnel_opening or not direct_optimized_extraction
                if is_direct_mold
                else True
            )
            patron = context.scene.objects.get("patron")
            master = context.scene.objects.get("master")
            obj = (
                master
                if is_direct_mold and master is not None and master.type == "MESH"
                else (
                    patron
                    if patron is not None and patron.type == "MESH"
                    else context.view_layer.objects.active
                )
            )
            if is_slip_casting_type(context.scene.mold_type_preview):
                from .source.components.slip_casting_cavity_filler import (
                    commit_slip_casting_parts_to_master,
                )

                # Rounded funnels retain their shape and join at the box stage,
                # after the master's clearance and extraction plan are complete.
                commit_slip_casting_parts_to_master(
                    context, master=Object(obj), include_rounded_funnels=False,
                )
            targets = [obj]
            if is_slip_casting_type(context.scene.mold_type_preview):
                # Male bases remain separate from the master for their open-base
                # mold. Generate their clearance using the joined master's paths.
                targets.extend(
                    part.object
                    for part in _slip_casting_male_vase_bases(context.scene)
                    if part.object != obj
                )
            shared_extraction_plan = None
            for target_index, obj in enumerate(targets):
                reuse_master_paths = target_index > 0 and is_direct_mold
                if reuse_master_paths and not shared_extraction_plan:
                    raise RuntimeError(
                        "The joined master has no extraction paths to reuse for base clearance"
                    )
                original_direct_min_z = (
                    float(Object(obj).min_z) if is_direct_mold else None
                )

                def trim_direct_bottom_after_remesh(target: Object) -> None:
                    if original_direct_min_z is None:
                        return
                    remeshed_min_z = float(target.min_z)
                    if abs(remeshed_min_z - original_direct_min_z) <= 1e-6:
                        return
                    center = target.center_coords
                    target.cut_plane(
                        mathutils.Vector((0.0, 0.0, -1.0)),
                        mathutils.Vector(
                            (center.x, center.y, original_direct_min_z)
                        ),
                    )
                    target.recalculate_normals()
                    logger.info(
                        "Applied Direct mold bottom cut at original min Z %.6f "
                        "after undercut remesh changed min Z to %.6f",
                        original_direct_min_z,
                        remeshed_min_z,
                    )

                phase_start = time.perf_counter()
                undercuts_voxel_size = get_master_voxel_size(
                    self.undercuts_quality,
                    obj,
                )
                # Use the popup selection for both clearance and final remesh.
                target_retry_voxel_size = undercuts_voxel_size
                logger.debug(
                    "Clear undercuts target and voxel setup: elapsed=%.3fs",
                    time.perf_counter() - phase_start,
                )

                split_plane_specs = []
                if reuse_master_paths:
                    split_plane_specs, boundary_plane_specs, locked_paths = shared_extraction_plan
                    logger.info(
                        "Clear undercuts reusing joined master extraction paths: target=%s paths=%d",
                        obj.name,
                        len(locked_paths),
                    )
                elif is_direct_mold:
                    sync_direct_split_planes_with_scene()
                    split_plane_specs = direct_split_plane_specs(
                        log_context="Clear undercuts extraction"
                    )
                if not reuse_master_paths:
                    locked_paths = None
                    boundary_plane_specs = (
                        self._split_plane_boundary_specs(Object(obj), split_plane_specs)
                        if is_direct_mold
                        else [bottom_reference_plane(Object(obj))]
                    )
                    preview_plan = getattr(self, "_preview_plan", None)
                    if preview_plan is not None and target_index == 0:
                        split_plane_specs = preview_plan["specs"]
                        # Prepared parts may lower the joined master's bottom;
                        # retain its current anchor while reusing the directions.
                        locked_paths = preview_plan["paths"] or None
                force_perpendicular_single_split = (
                    is_direct_mold
                    and self._force_perpendicular_single_split(split_plane_specs)
                )
                if force_perpendicular_single_split:
                    restrict_bottom_extraction = False
                    logger.info(
                        "Slip Casting Clear Undercuts has one split plane; "
                        "forcing extraction along the plane normal and its inverse"
                    )

                if is_direct_mold:
                    self._set_clear_undercuts_progress(context)
                    obj.data.calc_loop_triangles()
                    source_triangle_count = len(obj.data.loop_triangles)
                    target_reduction = get_direct_undercuts_target_reduction(
                        source_triangle_count
                    )
                    if (
                        not reuse_master_paths
                        and locked_paths is None
                        and target_reduction is not None
                        and target_reduction > 0.0
                    ):
                        breathe_viewport(context)
                        temporary_analysis_object = (
                            create_simplified_reference_for_operation(
                                Object(obj),
                                context,
                                name="clear_undercuts_reference",
                                target_reduction=target_reduction,
                            )
                        )
                        analysis_raw = temporary_analysis_object.object
                        analysis_raw.hide_set(True)
                        analysis_raw.hide_viewport = True
                        analysis_raw.hide_render = True
                        logger.info(
                            "Clear undercuts using temporary adaptive reference: "
                            "target=%s source_triangles=%d reference=%s "
                            "reference_polygons=%d target_reduction=%.2f%%",
                            obj.name,
                            source_triangle_count,
                            analysis_raw.name,
                            len(analysis_raw.data.polygons),
                            target_reduction * 100.0,
                        )
                        breathe_viewport(context)

                phase_start = time.perf_counter()
                selected_direct_paths = {} if is_direct_mold else None
                yield begin_clear_undercuts(
                    target_object=Object(obj),
                    bidirectional=not vertical,
                    voxel_size=undercuts_voxel_size,
                    target_retry_voxel_size=target_retry_voxel_size,
                    # Preserve the normal workflow's smoothing; only the dev
                    # experiment opts out to inspect the remeshed clearance.
                    smooth_target_after_remesh=not getattr(
                        self, "_dev_preserve_clearance_details", False
                    ),
                    target_point=mathutils.Vector((0, 0, 0)),
                    plane_direction=mathutils.Vector(
                        (0, 0, 1) if vertical else (1, 0, 0)
                    ),
                    progress_callback=lambda label: self._set_clear_undercuts_progress(
                        context,
                        label,
                    ),
                    ui_refresh_callback=(
                        (lambda: breathe_viewport(context))
                        if is_direct_mold
                        else None
                    ),
                    split_plane_specs=split_plane_specs,
                    boundary_plane_specs=boundary_plane_specs,
                    temporary_analysis_object=temporary_analysis_object,
                    easy_extraction=direct_easy_extraction,
                    precise_cost=direct_precise_cost,
                    horizontal_extraction=is_slip_casting_type(context.scene.mold_type_preview),
                    mid_horizontal_extraction=is_slip_casting_type(context.scene.mold_type_preview),
                    restrict_bottom_extraction=restrict_bottom_extraction,
                    split_plane_overtravel_override=(
                        0.0 if is_direct_mold else None
                    ),
                    clearance_build_overtravel_override=(
                        DIRECT_UNDERCUT_CLEARANCE_BUILD_OVERTRAVEL
                        if is_direct_mold
                        else None
                    ),
                    after_target_remesh=(
                        trim_direct_bottom_after_remesh
                        if is_direct_mold
                        else None
                    ),
                    selected_paths_out=selected_direct_paths,
                    locked_extraction_paths=locked_paths,
                )
                if target_index == 0 and selected_direct_paths:
                    shared_extraction_plan = (
                        split_plane_specs,
                        boundary_plane_specs,
                        dict(selected_direct_paths),
                    )
                if is_direct_mold:
                    store_direct_undercut_paths(
                        obj,
                        split_plane_specs,
                        # The later companion box may span sections absent
                        # from this base, so preserve the full master plan.
                        locked_paths if reuse_master_paths else (selected_direct_paths or {}),
                        easy_extraction=direct_easy_extraction,
                        precise_cost=direct_precise_cost,
                        restrict_bottom_extraction=restrict_bottom_extraction,
                    )
                temporary_analysis_object = None
                logger.debug(
                    "Clear undercuts extraction call: elapsed=%.3fs",
                    time.perf_counter() - phase_start,
                )

            self._set_clear_undercuts_progress(
                context,
                "Updating casting volume",
            )
            phase_start = time.perf_counter()
            refresh_casting_volume(context)
            logger.debug(
                "Clear undercuts casting-volume refresh: elapsed=%.3fs",
                time.perf_counter() - phase_start,
            )
            self._set_clear_undercuts_progress(context, "Clear undercuts complete")
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        finally:
            self._remove_clear_undercuts_analysis_object(
                temporary_analysis_object
            )
        logger.info(
            "Clear undercuts operator body completed in %.3fs",
            time.perf_counter() - operation_start,
        )
        return {"FINISHED"}


class NewClearUndercuts(_ClearUndercutsBehavior, SelectedObjectOperator):
    __annotations__ = dict(_ClearUndercutsBehavior.__annotations__)

    def execute(self, context):
        return _ClearUndercutsBehavior.execute(self, context)


class _SlipCastingClearUndercutsBehavior(_ClearUndercutsBehavior):
    def _uses_split_plane_extraction(self, _mold_type) -> bool:
        return True

    def _split_plane_extraction_opening(self, _context, _mold_type) -> str:
        return "base_open"

    def _force_perpendicular_single_split(self, split_plane_specs) -> bool:
        return len(split_plane_specs) == 1

    def _split_plane_boundary_specs(self, target, split_plane_specs):
        if self._force_perpendicular_single_split(split_plane_specs):
            return []
        return super()._split_plane_boundary_specs(target, split_plane_specs)

    def _clear_undercuts_operation_steps(self, context):
        if not has_pro_server_access():
            show_pro_membership_required()
            return {"CANCELLED"}
        self.extraction_mode = "EASY_EXTRACTION"
        self.undercuts_quality = context.scene.master_quality
        result = yield from super()._clear_undercuts_operation_steps(context)
        if result == {"FINISHED"}:
            mark_slip_casting_undercuts_cleared(
                context.scene,
                direct_split_plane_specs(
                    log_context="Slip Casting undercuts complete"
                ),
            )
        return result


class ClearSlipCastingUndercuts(
    _SlipCastingClearUndercutsBehavior,
    SelectedObjectOperator,
):
    __annotations__ = dict(_ClearUndercutsBehavior.__annotations__)
    bl_idname = "silicone.clear_slip_casting_undercuts"
    bl_label = "Clear Undercuts"
    bl_description = (
        "Clear the slip-casting master and male base undercuts using the "
        "configured split planes"
    )

    @classmethod
    def poll(cls, context):
        return (
            is_slip_casting_type(context.scene.mold_type_preview)
            and slip_casting_initial_stage_complete(context.scene)
            and super().poll(context)
        )

    def invoke(self, context, _event):
        if is_lite_tier():
            show_basic_membership_required()
            return {"CANCELLED"}
        self.extraction_mode = "EASY_EXTRACTION"
        self.undercuts_quality = context.scene.master_quality
        return self.execute(context)

    def execute(self, context):
        return _ClearUndercutsBehavior.execute(self, context)


class DevClearSlipCastingUndercuts(_SlipCastingClearUndercutsBehavior, SelectedObjectOperator):
    """Allow inspection/rework of a final master without preparation markers."""
    _dev_preserve_clearance_details = True
    __annotations__ = dict(_ClearUndercutsBehavior.__annotations__)
    bl_idname = "silicone.dev_clear_slip_casting_undercuts"
    bl_label = "Clear Undercuts (Slip Cast)"
    bl_description = "Run one slip-casting clearance pass, then measure remaining undercuts"

    @classmethod
    def poll(cls, context):
        prefs = get_addon_preferences()
        if not prefs or not getattr(prefs, "dev_mode", False):
            cls.poll_message_set("Enable Dev Mode")
            return False
        if not is_slip_casting_type(context.scene.mold_type_preview):
            cls.poll_message_set("Select a Slip Cast mold type")
            return False
        from .source.components.dev_undercut_preview import master_for_preview
        master = master_for_preview(context.scene)
        if master is None or master.mode != "OBJECT":
            cls.poll_message_set("A master mesh in Object Mode is required")
            return False
        return True

    def _clear_undercuts_operation_steps(self, context):
        from .source.components.dev_undercut_preview import (
            master_for_preview, log_diagnostic, log_mesh_state, log_stored_paths, begin_preview,
        )
        started = time.perf_counter()
        source = master_for_preview(context.scene)
        log_diagnostic("clearance started: mode=%s master_quality=%s",
                       context.scene.mold_type_preview, context.scene.master_quality)
        log_mesh_state("clearance before", source)
        log_diagnostic("clearance requested_split_planes=%s", direct_split_plane_specs())
        result = None
        try:
            # Build a fresh adaptive reference from the current master.
            self._preview_plan = None
            result = yield from super()._clear_undercuts_operation_steps(context)
            if result == {"FINISHED"}:
                self._set_clear_undercuts_progress(context, "Checking remaining undercuts")
                self._modal_status_label = "Checking remaining undercuts"
                log_diagnostic("post-clearance analysis started: plan=fresh; compare selected directions with stored_clearance_plan")
                try:
                    remaining = yield begin_preview(context)
                except Exception as exc:
                    log_diagnostic("post-clearance analysis failed: error=%r; clearance completed", exc)
                    self.report({"WARNING"}, t("Clearance completed, but remaining undercuts could not be measured. See logs."))
                else:
                    log_diagnostic("post-clearance result: remaining_affected_split_faces=%d", remaining)
                    self.report({"INFO"}, t("Clearance completed: {remaining} remaining undercut faces", remaining=remaining))
            return result
        except Exception as exc:
            log_diagnostic("clearance failed: error=%r", exc)
            logger.exception("Dev undercuts clearance traceback")
            raise
        finally:
            source = master_for_preview(context.scene)
            log_mesh_state("clearance after", source)
            if source is not None:
                log_stored_paths(source, "clearance result")
            log_diagnostic("clearance finished: result=%s elapsed=%.3fs",
                           result, time.perf_counter() - started)

    def invoke(self, context, event):
        return ClearSlipCastingUndercuts.invoke(self, context, event)

    def execute(self, context):
        return _ClearUndercutsBehavior.execute(self, context)


class StepDevSlipCastingUndercuts(ModalProcessingOperator):
    bl_idname = "silicone.step_dev_slip_casting_undercuts"
    bl_label = "Step Through Clearance"
    bl_description = "Advance one clearance stage on a temporary copy; the original master is preserved"
    bl_options = {"INTERNAL"}
    modal_show_progress_overlay = True

    @classmethod
    def poll(cls, context):
        from .source.components.dev_undercut_steps import can_advance
        return DevClearSlipCastingUndercuts.poll(context) and can_advance()

    def _task(self, context):
        if not has_pro_server_access():
            show_pro_membership_required()
            return None
        from .source.components.dev_undercut_steps import begin_next
        return begin_next(context)

    def _create_modal_step_iterator(self, context):
        task = self._task(context)
        if task is None:
            return {"CANCELLED"}
        yield "Debugging clearance stage", lambda: task
        self.report({"INFO"}, task.finish())
        return {"FINISHED"}

    def execute(self, context):
        task = self._task(context)
        if task is None:
            return {"CANCELLED"}
        self.report({"INFO"}, finish_task_sync(task))
        return {"FINISHED"}


class ResetDevSlipCastingUndercuts(bpy.types.Operator):
    bl_idname = "silicone.reset_dev_slip_casting_undercuts"
    bl_label = "Reset Clearance Debug"
    bl_description = "Remove the temporary debug meshes and restore the original master view"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        from .source.components.dev_undercut_steps import reset
        reset()
        return {"FINISHED"}


class _AutomaticSlipCastingUndercuts(_SlipCastingClearUndercutsBehavior):
    """Run the same clearing tasks inside the parent generation progress flow."""

    def __init__(self, operator):
        self._generation_operator = operator
        self.report = operator.report

    def _set_clear_undercuts_progress(self, context, _label=""):
        self._generation_operator._modal_status_label = "Clearing undercuts"
        force_viewport_redraw(context)


def _begin_plan_slip_casting_foot_paths(context):
    """Save companion extraction directions without clearing any geometry."""
    def steps():
        feet = _slip_casting_male_vase_bases(context.scene)
        if not feet:
            return
        sync_direct_split_planes_with_scene()
        specs = direct_split_plane_specs(log_context="Slip Casting foot path planning")
        master = Object(context.scene.objects.get("patron"))
        paths = {}
        restricted = len(specs) != 1
        yield begin_clear_undercuts(
            target_object=master, bidirectional=True,
            voxel_size=get_undercuts_voxel_size(context.scene.undercuts_quality, master),
            split_plane_specs=specs,
            boundary_plane_specs=[bottom_reference_plane(master)] if restricted else [],
            easy_extraction=True, precise_cost=False,
            horizontal_extraction=True, mid_horizontal_extraction=True,
            restrict_bottom_extraction=restricted,
            split_plane_overtravel_override=0.0,
            planning_only=True, display_extraction_directions=False,
            selected_paths_out=paths,
        )
        if not paths:
            raise RuntimeError("Could not calculate extraction paths for the foot mold")
        for foot in feet:
            store_direct_undercut_paths(
                foot.object, specs, paths, easy_extraction=True,
                precise_cost=False, restrict_bottom_extraction=restricted,
            )
        logger.info("Planned foot companion extraction without clearance: feet=%d paths=%d", len(feet), len(paths))
    return BackgroundTaskSequence(steps())


def _begin_automatic_slip_casting_undercuts(operator, context):
    def clear_master_steps():
        if not getattr(context.scene, "clear_extraction", True):
            from .source.components.slip_casting_undercut_preview import _clear_display
            _clear_display()
            logger.info("Slip Cast master undercut clearance disabled; box clearance remains enabled")
            yield _begin_plan_slip_casting_foot_paths(context)
            return {"FINISHED"}
        sync_direct_split_planes_with_scene()
        specs = direct_split_plane_specs(log_context="Slip Casting automatic undercuts")
        if slip_casting_undercuts_cleared(context.scene, specs):
            return {"FINISHED"}
        runner = _AutomaticSlipCastingUndercuts(operator)
        from .source.components.slip_casting_undercut_preview import begin_generation_plan
        runner._preview_plan = yield begin_generation_plan(context)
        return (yield runner._begin_clear_undercuts_operation(context))

    def steps():
        result = yield from clear_master_steps()
        if result == {"FINISHED"}:
            from .source.components.slip_casting_rounded import begin_prepare_rounded_funnel_reference_plans
            yield begin_prepare_rounded_funnel_reference_plans(context)
        return result

    sequence = BackgroundTaskSequence(steps())
    sequence.redraw_interval = 0.1
    return sequence


def _iter_guarded_batch_generation_steps(operator, context, session):
    generation_count = 2 if session.mold_type.identifier == "DIRECT_MOLD_SKIN" else 1
    for generation_index in range(generation_count):
        try:
            steps = iter(
                _iter_selected_mold_generation_steps(
                    operator,
                    context,
                    session.mold_type,
                )
            )
            while True:
                try:
                    step = next(steps)
                except StopIteration as completed:
                    result = completed.value or {"FINISHED"}
                    break

                label = None
                callback = step
                if isinstance(step, tuple):
                    label, callback = step
                stage_prefix = (
                    f"Skin stage {generation_index + 1}: "
                    if generation_count > 1
                    else ""
                )
                yield (
                    session.label(f"{stage_prefix}{label or 'Generating mold'}"),
                    session.guard(callback),
                )
        except Exception as exc:
            session.fail_active_model(exc)
            raise

        if "FINISHED" not in result:
            stage = (
                "skin core"
                if session.mold_type.identifier == "DIRECT_MOLD_SKIN"
                and generation_index == 0
                else "mold system"
            )
            error = BatchTestsError(
                f"{session.mold_type.label} {stage} generation failed"
            )
            session.fail_active_model(error)
            raise error


class BatchTestsOperator(ModalProcessingOperator):
    bl_idname = "silicone.batch_tests_operator"
    bl_label = "Run Batch Tests"
    bl_description = (
        "Import every model in the batch tests folder, generate the selected "
        "mold type, save the blend, and export the mold system"
    )
    bl_options = {"REGISTER"}
    requires_current_extension = True
    modal_show_progress_overlay = True
    modal_log_redraw_timing = True
    modal_wait_redraw_interval = 0.1

    slip_casting_all_options: BoolProperty(
        name="All Slip Casting Options",
        description="Run all 24 foot, mold shape, and funnel combinations for every model",
        default=False,
        options={"SKIP_SAVE"},
    )

    multipart_all_shapes: BoolProperty(
        name="All Multipart Shape and Base Options",
        description="Run all 6 shape and fully enclosed/open base combinations for every model",
        default=False,
        options={"SKIP_SAVE"},
    )

    all_generators: BoolProperty(
        name="All Generators with Default Settings",
        description="Run every available mold generator with default settings for every model",
        default=False,
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        prefs = get_addon_preferences()
        return bool(prefs and getattr(prefs, "dev_mode", False))

    def _redraw_after_materials(self, context):
        generation_operator_class = self._batch_generation_operator_class()
        refresh_materials = generation_operator_class is None or bool(
            getattr(
                generation_operator_class,
                "modal_refresh_materials_on_redraw",
                True,
            )
        )
        if refresh_materials:
            return super()._redraw_after_materials(context)
        force_viewport_redraw(context)
        self._log_modal_redraw_timing("step")

    def _batch_generation_operator_class(self):
        if not getattr(self, "_batch_generation_active", False):
            return None
        session = getattr(self, "_batch_test_session", None)
        if session is None:
            return None
        return _MOLD_GENERATION_OPERATOR_CLASSES.get(
            session.mold_type.generate_operator
        )

    @staticmethod
    def _unprefixed_batch_generation_label(label):
        if not isinstance(label, str):
            return label
        return label.rsplit(": ", 1)[-1]

    def _should_skip_modal_redraw(self, label) -> bool:
        generation_operator_class = self._batch_generation_operator_class()
        if generation_operator_class is None:
            return super()._should_skip_modal_redraw(label)
        generation_label = self._unprefixed_batch_generation_label(label)
        return generation_label in getattr(
            generation_operator_class,
            "modal_skip_redraw_steps",
            set(),
        )

    def _should_skip_before_modal_redraw(self, label) -> bool:
        generation_operator_class = self._batch_generation_operator_class()
        if generation_operator_class is None:
            return super()._should_skip_before_modal_redraw(label)
        generation_label = self._unprefixed_batch_generation_label(label)
        return generation_label in getattr(
            generation_operator_class,
            "modal_skip_before_redraw_steps",
            set(),
        )

    def _create_modal_step_iterator(self, context):
        try:
            session = BatchTestSession(
                context,
                getattr(context.scene, "dev_batch_tests_path", ""),
                begin_import_finalization=begin_finalize_imported_model,
                slip_casting_all_options=self.slip_casting_all_options,
                multipart_all_shapes=self.multipart_all_shapes,
                all_generators=self.all_generators,
            )
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self._batch_test_session = session

        for model_path, variant, settings, mold_type in session.test_cases:
            yield (
                f"{model_path.name}{f' [{variant}]' if variant else ''}: Starting",
                session.guard(
                    lambda path=model_path, name=variant, options=settings, mode=mold_type:
                    session.start_model(path, name, options, mode)
                ),
            )
            yield session.label("Clearing scene"), session.guard(session.clear_scene)
            if self.all_generators:
                def reset_defaults():
                    scene = context.scene
                    reset_scene_properties_to_defaults(
                        scene,
                        SETTINGS_SCENE_PROPERTIES + preparation_settings.setting_keys(),
                    )
                    scene.mold_advanced_mode = False
                    scene.property_unset("master_quality")
                    scene.property_unset("scale_height")
                    scene.clamp_depth = default_clamp_depth(scene.mold_type_preview)
                    if is_direct_mold_type(scene.mold_type_preview):
                        scene.undercuts_quality = "FAST"

                yield session.label("Restoring default settings"), session.guard(reset_defaults)
            yield session.label("Applying test options"), session.guard(session.apply_variant)
            yield session.label("Importing model"), session.guard(session.import_model)
            yield session.label("Restoring guides"), session.guard(session.restore_guides)
            if is_slip_casting_type(session.mold_type.identifier):
                yield (
                    session.label("Preparing casting"),
                    session.guard(lambda: begin_detect_slip_casting_cores(context)),
                )
                yield (
                    session.label("Updating materials"),
                    session.guard(refresh_generated_object_materials),
                )
            if session.mold_type.generate_operator == "silicone.automatic_mold":
                yield (
                    session.label("Clearing undercuts"),
                    session.guard(session.clear_direct_undercuts),
                )

            self._batch_generation_active = True
            try:
                yield from _iter_guarded_batch_generation_steps(
                    self,
                    context,
                    session,
                )
            finally:
                self._batch_generation_active = False
            yield (
                session.label("Generation complete"),
                session.guard(session.mark_generation_complete),
            )
            yield session.label("Saving blend"), session.guard(session.save_blend)
            yield session.label("Exporting parts"), session.guard(session.begin_export)
            yield (
                session.label("Checking cleaned exports manifold status"),
                session.guard(session.inspect_manifold_statuses),
            )
            yield (
                session.label("Recording result"),
                session.guard(session.complete_model),
            )

        yield (
            t("Batch tests complete"),
            lambda: self.report(
                {"INFO"},
                t(
                    "Batch tests completed: {count} test case(s) in {path}",
                    count=session.completed_count,
                    path=session.run_dir,
                ),
            ),
        )
        return {"FINISHED"}

    def execute(self, context):
        self.report(
            {"ERROR"},
            t("Batch tests cannot be nested inside another running operation."),
        )
        return {"CANCELLED"}


_MANIFOLD_CHECK_EXCLUDED_MARKERS = (
    "moldboxer_direct_split_plane",
    "moldboxer_direct_split_plane_contour",
    "moldboxer_funnel_reference_height_guide",
    "moldboxer_funnel_extension_height_guide",
    "moldboxer_fixture_height_guide",
)
_MANIFOLD_CHECK_REQUIRED_OBJECT_NAMES = frozenset({"master", "master_base"})
_MANIFOLD_CHECK_IGNORED_OBJECT_NAMES = frozenset(
    {
        "backup",
        "silicone_mold",
        "left_silicone_mold",
        "right_silicone_mold",
    }
)
_MANIFOLD_FIX_EXCLUDED_OBJECT_NAMES = frozenset(
    {
        "master_base",
        "left_master",
        "right_master",
    }
)


def _is_manifold_check_helper_object(obj) -> bool:
    name = str(getattr(obj, "name", "")).casefold()
    if name in _MANIFOLD_CHECK_IGNORED_OBJECT_NAMES:
        return True

    try:
        if any(bool(obj.get(marker)) for marker in _MANIFOLD_CHECK_EXCLUDED_MARKERS):
            return True
    except Exception:
        pass

    return "split_plane" in name or "guide" in name


def _manifold_status_check_objects(context):
    """Return scene meshes plus the required master artifacts by exact name."""
    candidates = {obj.name: obj for obj in context.scene.objects}
    for object_name in _MANIFOLD_CHECK_REQUIRED_OBJECT_NAMES:
        required_obj = bpy.data.objects.get(object_name)
        if required_obj is not None:
            candidates[required_obj.name] = required_obj

    return sorted(
        (
            obj
            for obj in candidates.values()
            if obj.type == "MESH"
            and (
                obj.name.casefold() in _MANIFOLD_CHECK_REQUIRED_OBJECT_NAMES
                or not _is_manifold_check_helper_object(obj)
            )
        ),
        key=lambda obj: obj.name.casefold(),
    )


def _float32_point(coordinate) -> tuple[float, float, float]:
    return struct.unpack(
        "<3f",
        struct.pack(
            "<3f",
            float(coordinate[0]),
            float(coordinate[1]),
            float(coordinate[2]),
        ),
    )


def _coordinate_edge_key(start, end, decimals=None):
    if decimals is not None:
        start = tuple(round(float(value), decimals) for value in start)
        end = tuple(round(float(value), decimals) for value in end)
    return tuple(sorted((tuple(start), tuple(end))))


def _clean_scene_object_for_manifold_fix(context, obj) -> bool | None:
    """Persist export-style cleanup on one scene object."""
    if str(obj.name).casefold() in _MANIFOLD_FIX_EXCLUDED_OBJECT_NAMES:
        logger.debug(
            "Skipping scene manifold-fix cleanup for %s to avoid processing "
            "excluded patron geometry",
            obj.name,
        )
        return None

    cleanup_start = time.perf_counter()
    ui_refresh_callback = cleanup_ui_refresh_callback(
        obj.data,
        lambda: breathe_viewport(context),
    )
    if is_generated_box_name(obj.name):
        stats, weld_distance = clean_generated_box_mesh(
            obj.data,
            stl_matrix_world=obj.matrix_world,
            ui_refresh_callback=ui_refresh_callback,
        )
        logger.info(
            "Scene manifold-fix cleanup for %s: mode=adaptive "
            "weld_distance=%.6f changed=%s elapsed=%.3fs",
            obj.name,
            weld_distance,
            stats.changed,
            time.perf_counter() - cleanup_start,
        )
    else:
        stats = clean_mesh_for_slicer(
            obj.data,
            stl_matrix_world=obj.matrix_world,
            ui_refresh_callback=ui_refresh_callback,
        )
        logger.info(
            "Scene manifold-fix cleanup for %s: mode=standard changed=%s "
            "elapsed=%.3fs",
            obj.name,
            stats.changed,
            time.perf_counter() - cleanup_start,
        )
    return stats.changed


def _select_export_problem_edges(obj, problem_edges) -> int:
    """Store the exported problem-edge selection on one mesh object.

    Mesh element selections persist while the object is in Object Mode, so the
    operator can prepare every failing object without entering multi-object
    Edit Mode.  The caller activates the worst object only after all selections
    have been stored.
    """
    exact_keys = {
        _coordinate_edge_key(edge.start, edge.end)
        for edge in problem_edges
    }
    rounded_keys = {
        decimals: {
            _coordinate_edge_key(edge.start, edge.end, decimals)
            for edge in problem_edges
        }
        for decimals in (5, 4)
    }

    # Worker-rebuilt meshes can legitimately lack Blender's internal
    # .select_vert/.select_edge/.select_poly custom-data layers. Assigning
    # MeshEdge.select on such a mesh dereferences a null selection layer in
    # Blender 5.0 instead of raising a Python exception. BMesh creates those
    # layers when it writes the selection state back and avoids the unsafe RNA
    # element setter entirely.
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        for face in bm.faces:
            face.select_set(False)
        for edge in bm.edges:
            edge.select_set(False)
        for vertex in bm.verts:
            vertex.select_set(False)

        selected_count = 0
        matrix = obj.matrix_world
        for edge in bm.edges:
            start = _float32_point(matrix @ edge.verts[0].co)
            end = _float32_point(matrix @ edge.verts[1].co)
            exact_key = _coordinate_edge_key(start, end)
            matches = exact_key in exact_keys
            if not matches:
                matches = any(
                    _coordinate_edge_key(start, end, decimals)
                    in rounded_keys[decimals]
                    for decimals in (5, 4)
                )
            if matches:
                edge.select_set(True)
                selected_count += 1

        bm.to_mesh(obj.data)
    finally:
        bm.free()
    obj.data.update()
    return selected_count


def _activate_export_problem_object(context, obj) -> None:
    active = context.view_layer.objects.active
    if active is not None and active.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for selected_obj in list(context.selected_objects):
        selected_obj.select_set(False)
    obj.hide_set(False)
    obj.hide_viewport = False
    obj.select_set(True)
    context.view_layer.objects.active = obj
    context.tool_settings.mesh_select_mode = (False, True, False)
    bpy.ops.object.mode_set(mode="EDIT")


class FixManifold(bpy.types.Operator):
    bl_idname = "silicone.fix_manifold"
    bl_label = "Fix Manifold"
    bl_description = (
        "Apply export-style geometry cleanup directly to scene mesh objects"
    )
    bl_options = {"INTERNAL", "UNDO"}

    def execute(self, context):
        active = context.view_layer.objects.active
        if active is not None and active.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        objects = sorted(
            (
                obj
                for obj in context.scene.objects
                if obj.type == "MESH" and not _is_manifold_check_helper_object(obj)
            ),
            key=lambda obj: obj.name.casefold(),
        )
        cleaned_count = 0
        changed_count = 0
        skipped_count = 0
        failed_count = 0
        for obj in objects:
            try:
                changed = _clean_scene_object_for_manifold_fix(context, obj)
            except Exception:
                logger.exception("Manifold fix failed for %s", obj.name)
                failed_count += 1
                continue
            if changed is None:
                skipped_count += 1
                continue
            cleaned_count += 1
            changed_count += int(changed)

        self.report(
            {"WARNING"} if failed_count else {"INFO"},
            t(
                "Manifold cleanup finished: {cleaned} cleaned, "
                "{changed} changed, {skipped} skipped, {failed} failed",
                cleaned=cleaned_count,
                changed=changed_count,
                skipped=skipped_count,
                failed=failed_count,
            ),
        )
        return {"FINISHED"}


class CheckManifoldStatus(bpy.types.Operator):
    bl_idname = "silicone.check_manifold_status"
    bl_label = "Check Manifold Status"
    bl_description = (
        "Check current STL topology without cleaning or modifying geometry, "
        "using Bambu Studio when installed"
    )
    bl_options = {"INTERNAL"}

    def execute(self, context):
        active = context.view_layer.objects.active
        if active is not None and active.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        objects = _manifold_status_check_objects(context)
        statuses = []
        report_sections = []
        problem_candidates = []
        worst_problem_candidate = None
        bambu_executable = find_bambu_studio_executable()
        checker_name = "Bambu Studio" if bambu_executable else "Blender topology"

        if bambu_executable:
            original_selection = list(context.selected_objects)
            original_active = context.view_layer.objects.active
            hidden_states = {
                obj: (obj.hide_get(), obj.hide_viewport, obj.hide_render)
                for obj in objects
            }
            try:
                with tempfile.TemporaryDirectory(prefix="moldboxer-manifold-") as temp_dir:
                    for index, obj in enumerate(objects):
                        try:
                            for selected_obj in list(context.selected_objects):
                                selected_obj.select_set(False)
                            obj.hide_set(False)
                            obj.hide_viewport = False
                            obj.hide_render = False
                            obj.select_set(True)
                            context.view_layer.objects.active = obj
                            stl_path = f"{temp_dir}/{index:04d}.stl"
                            bpy.ops.wm.stl_export(
                                filepath=stl_path,
                                export_selected_objects=True,
                                ascii_format=False,
                            )
                            result = check_stl_with_bambu(
                                bambu_executable,
                                stl_path,
                            )
                            try:
                                diagnostics = diagnose_binary_stl(stl_path)
                                effective_manifold = (
                                    result.manifold and diagnostics.open_edges == 0
                                )
                                statuses.append(
                                    (
                                        obj.name,
                                        effective_manifold,
                                        len(diagnostics.problem_edges),
                                        None,
                                    )
                                )
                                report_sections.append(
                                    format_stl_diagnostics_report(
                                        obj.name,
                                        result.manifold,
                                        diagnostics,
                                    )
                                )
                                if not effective_manifold:
                                    candidate = (
                                        diagnostics.issue_count,
                                        len(diagnostics.problem_edges),
                                        obj,
                                        diagnostics.problem_edges,
                                    )
                                    problem_candidates.append(candidate)
                                    if (
                                        worst_problem_candidate is None
                                        or candidate[:2] > worst_problem_candidate[:2]
                                    ):
                                        worst_problem_candidate = candidate
                            except Exception as diagnostics_exc:
                                logger.exception(
                                    "Detailed STL diagnostics failed for %s",
                                    obj.name,
                                )
                                statuses.append(
                                    (obj.name, result.manifold, None, None)
                                )
                                report_sections.append(
                                    f"Object: {obj.name}\n"
                                    f"Bambu Studio manifold: "
                                    f"{'YES' if result.manifold else 'NO'}\n"
                                    f"Detailed diagnostics failed: {diagnostics_exc}"
                                )
                        except Exception as exc:
                            logger.exception(
                                "Bambu Studio manifold check failed for %s",
                                obj.name,
                            )
                            statuses.append((obj.name, False, None, str(exc)))
                            report_sections.append(
                                f"Object: {obj.name}\nCheck failed: {exc}"
                            )
            finally:
                for obj, hidden_state in hidden_states.items():
                    obj.hide_set(hidden_state[0])
                    obj.hide_viewport = hidden_state[1]
                    obj.hide_render = hidden_state[2]
                for selected_obj in list(context.selected_objects):
                    selected_obj.select_set(False)
                for selected_obj in original_selection:
                    if selected_obj.name in bpy.data.objects:
                        selected_obj.select_set(True)
                if original_active is not None and original_active.name in bpy.data.objects:
                    context.view_layer.objects.active = original_active
                else:
                    context.view_layer.objects.active = None
        else:
            depsgraph = context.evaluated_depsgraph_get()
            for obj in objects:
                try:
                    evaluated_obj = obj.evaluated_get(depsgraph)
                    mesh = evaluated_obj.to_mesh()
                    try:
                        (
                            is_manifold,
                            non_manifold_edges,
                            open_edges,
                        ) = mesh_manifold_edge_counts(mesh)
                    finally:
                        evaluated_obj.to_mesh_clear()
                    statuses.append(
                        (obj.name, is_manifold, non_manifold_edges, None)
                    )
                    report_sections.append(
                        f"Object: {obj.name}\n"
                        f"Blender topology manifold: "
                        f"{'YES' if is_manifold else 'NO'}\n"
                        f"Non-manifold edges (including open): "
                        f"{non_manifold_edges}\n"
                        f"Open edges (1 face user): {open_edges}"
                    )
                except Exception as exc:
                    logger.exception("Manifold status check failed for %s", obj.name)
                    statuses.append((obj.name, False, 0, str(exc)))
                    report_sections.append(
                        f"Object: {obj.name}\nCheck failed: {exc}"
                    )

        report_header = [
            "Moldboxer manifold diagnostics",
            f"Checker: {checker_name}",
        ]
        if bambu_executable:
            report_header.append(
                "Detailed counts are measured from the exact binary STL sent "
                "to Bambu Studio; Bambu's CLI exposes only its final YES/NO verdict."
            )
        context.window_manager.clipboard = "\n".join(report_header) + "\n\n" + (
            "\n\n".join(report_sections) if report_sections else "No mesh objects found."
        )

        selection_summary = None
        if problem_candidates:
            active = context.view_layer.objects.active
            if active is not None and active.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")

            selection_lines = ["Problem-edge selections:"]
            selected_object_count = 0
            selected_counts = {}
            for _score, _edge_count, problem_obj, problem_edges in problem_candidates:
                selected_edge_count = _select_export_problem_edges(
                    problem_obj,
                    problem_edges,
                )
                selected_counts[problem_obj] = selected_edge_count
                if selected_edge_count:
                    selected_object_count += 1
                    selection_lines.append(
                        f"  {problem_obj.name}: {selected_edge_count} edges selected"
                    )
                else:
                    selection_lines.append(
                        f"  {problem_obj.name}: exported edges could not be mapped"
                    )

            if worst_problem_candidate is not None:
                _score, _edge_count, problem_obj, _problem_edges = (
                    worst_problem_candidate
                )
                if selected_counts.get(problem_obj, 0):
                    _activate_export_problem_object(context, problem_obj)
                    selection_lines.append(
                        f"Active Edit Mode object: {problem_obj.name}"
                    )

            selection_summary = t(
                "Selected problematic edges on {count} object(s)",
                count=selected_object_count,
            )
            context.window_manager.clipboard += (
                "\n\n" + "\n".join(selection_lines)
            )

        manifold_count = sum(
            1
            for _name, is_manifold, _edge_count, error in statuses
            if is_manifold and error is None
        )

        def draw(popup, _context):
            layout = popup.layout
            if not statuses:
                layout.label(text=t("No mesh objects found"), icon="INFO")
                return

            layout.label(
                text=t(
                    "{manifold} of {total} objects are manifold",
                    manifold=manifold_count,
                    total=len(statuses),
                )
            )
            layout.label(text=t("Checked with: {checker}", checker=checker_name))
            layout.label(text=t("Detailed report copied to clipboard"), icon="COPYDOWN")
            if selection_summary is not None:
                layout.label(text=selection_summary, icon="EDGESEL")
            layout.separator()
            for name, is_manifold, non_manifold_edges, error in statuses:
                if error is not None:
                    layout.label(
                        text=t("{name}: Check failed", name=name),
                        icon="ERROR",
                    )
                elif is_manifold:
                    layout.label(
                        text=t("{name}: Manifold", name=name),
                        icon="CHECKMARK",
                    )
                elif non_manifold_edges is None:
                    layout.label(
                        text=t("{name}: Non-manifold", name=name),
                        icon="ERROR",
                    )
                else:
                    layout.label(
                        text=t(
                            "{name}: Non-manifold/open ({count} edges)",
                            name=name,
                            count=non_manifold_edges,
                        ),
                        icon="ERROR",
                    )

        context.window_manager.popup_menu(
            draw,
            title=t("Manifold Status"),
            icon="INFO",
        )
        return {"FINISHED"}


class PreviewMasterUndercuts(ModalProcessingOperator):
    bl_idname = "silicone.preview_master_undercuts"
    bl_label = "Show Master Undercuts"
    bl_description = "Highlight the master's undercut faces against the current split planes without changing the mesh"
    bl_options = {"INTERNAL"}
    modal_show_progress_overlay = True

    @classmethod
    def poll(cls, context):
        from .source.components.dev_undercut_preview import master_for_preview
        prefs = get_addon_preferences()
        master = master_for_preview(context.scene)
        return bool(prefs and prefs.dev_mode and master is not None and master.mode == "OBJECT")

    def _create_modal_step_iterator(self, context):
        from .source.components.dev_undercut_steps import begin_inspection as begin_preview
        task = begin_preview(context)
        yield "Analyzing master undercuts", lambda: task
        self.report({"INFO"}, t("Master undercuts: {count} affected faces", count=task.finish()))
        return {"FINISHED"}

    def execute(self, context):
        from .source.components.dev_undercut_steps import begin_inspection as begin_preview
        count = finish_task_sync(begin_preview(context))
        self.report({"INFO"}, t("Master undercuts: {count} affected faces", count=count))
        return {"FINISHED"}


class HideMasterUndercuts(bpy.types.Operator):
    bl_idname = "silicone.hide_master_undercuts"
    bl_label = "Hide Master Undercuts"
    bl_description = "Remove the development undercut overlay"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        from .source.components.dev_undercut_preview import clear_preview, log_diagnostic
        clear_preview()
        log_diagnostic("overlay hidden by dev button")
        return {"FINISHED"}


class ToggleDevMeshOverlays(bpy.types.Operator):
    bl_idname = "silicone.toggle_dev_mesh_overlays"
    bl_label = "Face Orientation & Statistics"
    bl_description = (
        "Toggle the Face Orientation and Statistics overlays together in "
        "the active 3D View"
    )
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        prefs = get_addon_preferences()
        overlay = getattr(getattr(context, "space_data", None), "overlay", None)
        return bool(
            prefs
            and getattr(prefs, "dev_mode", False)
            and overlay is not None
            and hasattr(overlay, "show_face_orientation")
            and hasattr(overlay, "show_stats")
        )

    def execute(self, context):
        overlay = context.space_data.overlay
        enable = not (
            bool(overlay.show_face_orientation)
            and bool(overlay.show_stats)
        )
        overlay.show_face_orientation = enable
        overlay.show_stats = enable
        return {"FINISHED"}


class CenterSplitPlanes(bpy.types.Operator):
    bl_idname = "silicone.center_split_planes"
    bl_label = "Center Split Planes"
    bl_description = (
        "Move all editable flat split planes to the model center, preserving "
        "their rotation and size so they share a rotation pivot"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and any(
            obj.name in context.scene.objects
            and not obj.get("moldboxer_organic_plane", False)
            and not all(obj.lock_location)
            for obj in iter_direct_split_plane_objects()
        )

    def execute(self, context):
        center_direct_split_planes(context)
        for area in getattr(context.screen, "areas", ()):
            area.tag_redraw()
        return {"FINISHED"}


class ToggleViewportOverlays(bpy.types.Operator):
    bl_idname = "silicone.toggle_viewport_overlays"
    bl_label = "Viewport Overlays"
    bl_description = (
        "Show or hide viewport overlays, including grids, labels, split planes, "
        "and reference guides"
    )
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        overlay = getattr(getattr(context, "space_data", None), "overlay", None)
        if (
            getattr(getattr(context, "area", None), "type", "") == "VIEW_3D"
            and overlay is not None
            and hasattr(overlay, "show_overlays")
        ):
            return True
        return any(
            getattr(area, "type", "") == "VIEW_3D"
            and hasattr(
                getattr(getattr(area, "spaces", None), "active", None),
                "overlay",
            )
            for area in getattr(getattr(context, "screen", None), "areas", ())
        )

    def execute(self, context):
        area = getattr(context, "area", None)
        space = getattr(context, "space_data", None)
        overlay = getattr(space, "overlay", None)
        if getattr(area, "type", "") != "VIEW_3D" or overlay is None:
            area = next(
                (
                    candidate
                    for candidate in getattr(
                        getattr(context, "screen", None),
                        "areas",
                        (),
                    )
                    if getattr(candidate, "type", "") == "VIEW_3D"
                    and hasattr(
                        getattr(
                            getattr(candidate, "spaces", None),
                            "active",
                            None,
                        ),
                        "overlay",
                    )
                ),
                None,
            )
            space = getattr(getattr(area, "spaces", None), "active", None)
            overlay = getattr(space, "overlay", None)
        if area is None or overlay is None or not hasattr(overlay, "show_overlays"):
            return {"CANCELLED"}

        overlay.show_overlays = not bool(overlay.show_overlays)
        set_extraction_direction_overlay_visible(overlay.show_overlays)
        set_direct_split_planes_overlay_visible(
            overlay.show_overlays,
            context.scene,
        )
        set_reference_guides_overlay_visible(
            overlay.show_overlays,
            context.scene,
        )
        area.tag_redraw()
        return {"FINISHED"}


class TestAllFillersOperator(ModalProcessingOperator):
    bl_idname = "silicone.test_all_fillers_operator"
    bl_label = "Test All Fillers"
    bl_description = "Build inner splitter, tight filler, and cavity filler geometry for the selected mesh"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        patron = bpy.data.objects.get("patron")
        return (context.object is not None and context.object.type == "MESH") or (
            patron is not None and patron.type == "MESH"
        )

    def execute(self, context):
        target = (
            context.object
            if context.object is not None and context.object.type == "MESH"
            else None
        )
        if target is None:
            target = bpy.data.objects.get("patron")

        if target is None or target.type != "MESH":
            self.report({"ERROR"}, t("No mesh object selected"))
            return {"CANCELLED"}

        build_all_fillers(
            Object(target),
            context,
        )
        refresh_generated_object_materials()
        refresh_viewport_material_display(context)
        return {"FINISHED"}


class TestAddFillerToPatron(ModalProcessingOperator):
    bl_idname = "silicone.test_add_filler_to_patron"
    bl_label = "Add Filler to Patron"
    bl_description = "Boolean-add filler objects to the patron without remeshing"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        patron = bpy.data.objects.get("patron")
        return (
            patron is not None
            and patron.type == "MESH"
            and any(
                obj.type == "MESH" and "filler" in obj.name.casefold()
                for obj in bpy.data.objects
            )
        )

    def execute(self, context):
        patron_raw = bpy.data.objects.get("patron")
        if patron_raw is None or patron_raw.type != "MESH":
            self.report({"ERROR"}, t("No patron object found"))
            return {"CANCELLED"}

        filler_objects = [
            obj
            for obj in bpy.data.objects
            if obj.type == "MESH" and "filler" in obj.name.casefold()
        ]
        if not filler_objects:
            self.report({"ERROR"}, t("No filler objects found"))
            return {"CANCELLED"}

        patron = Object(patron_raw)
        added_count = 0
        for filler_raw in filler_objects:
            if filler_raw.name not in bpy.data.objects:
                continue
            filler = Object(filler_raw)
            patron += filler
            if patron.has_empty_boolean:
                self.report({"ERROR"}, t("Boolean modifier without target failed"))
                return {"CANCELLED"}
            filler.remove()
            added_count += 1

        patron.select()
        refresh_generated_object_materials()
        refresh_viewport_material_display(context)
        self.report(
            {"INFO"}, t("Added {count} filler objects to patron", count=added_count)
        )
        return {"FINISHED"}
