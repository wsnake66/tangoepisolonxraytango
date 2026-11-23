import bpy  # type: ignore
from concurrent.futures import Future, ThreadPoolExecutor
import io
import tempfile
import zipfile
import os
import logging
import time
import json
from urllib.parse import urlsplit

from ..background_worker import BackgroundTaskSequence
from ..components.geometry_adapter import acquire_geometry_worker
from ..environment import is_dev_mode
from ..nearest_surface_worker_client import NearestSurfaceWorkerError
from ..object import DIRECT_BOOLEAN_RETRY_SCENE_KEY, Object, remove_unused_meshes
from ..bl_utils import deselect_all_objects, import_model
from ..materials import assign_generated_material
from ..mold_types import is_slip_casting_type
from ..progress import breathe_viewport
from ..modifiers import build_voxel_modifier
from .auth import (
    begin_get_valid_access_token,
    get_valid_access_token,
    get_addon_preferences,
)
from .base_substracter_visibility import (
    is_base_substracter_object,
    set_base_substracter_hidden,
    set_object_hidden,
)

logger = logging.getLogger(__name__)

SERVER_REQUEST_TIMEOUT_SECONDS = 600
SERVER_JSON_REQUEST_TIMEOUT_SECONDS = 30
SERVER_REQUEST_MAX_ATTEMPTS = 3
SERVER_REQUEST_RETRY_BACKOFF_SECONDS = 2
SERVER_REQUEST_REDRAW_INTERVAL_SECONDS = 0.1
BARRIER_DIAMETER_LIMIT_SAFEGUARD = 1.0
DISTANCE_FROM_EDGE = 1.0
CLAMP_BARRIER_DISTANCE_FROM_EDGE = 2.0
_SERVER_REQUEST_EXECUTOR = ThreadPoolExecutor(
    max_workers=2,
    thread_name_prefix="moldboxer-server",
)
WORKER_DIAGNOSTICS_FILENAME = "_moldboxer_worker_diagnostics.json"


def _direct_mold_ui_redraws_enabled() -> bool:
    scene = getattr(bpy.context, "scene", None)
    return bool(
        scene is not None and scene.get(DIRECT_BOOLEAN_RETRY_SCENE_KEY, False)
    )


class AuthorizationError(RuntimeError):
    """Raised when server/auth token authorization fails."""


class ServerTokenRejectedError(AuthorizationError):
    """The service rejected an access token; refresh once before asking for login."""


class ServerConnectionError(RuntimeError):
    """Raised when a server request cannot complete due to connectivity."""


class BackgroundServerRequest:
    """HTTP-only background request; Blender data is prepared/finalized on main."""

    def __init__(
        self,
        future: Future,
        *,
        on_complete=None,
        on_finish=None,
    ) -> None:
        self._future = future
        self._on_complete = on_complete
        self._on_finish = on_finish

    @property
    def redraw_interval(self) -> float:
        """Keep Blender responsive while the modal loop polls this request."""

        return SERVER_REQUEST_REDRAW_INTERVAL_SECONDS

    def done(self) -> bool:
        return self._future.done()

    def finish(self):
        try:
            response = self._future.result()
            if self._on_complete is None:
                return response
            return self._on_complete(response)
        finally:
            if self._on_finish is not None:
                self._on_finish()


def _log_imported_object_names(imported_objects: list[Object]) -> None:
    imported_names = [
        obj.name for obj in imported_objects if getattr(obj, "name", None)
    ]
    if imported_names:
        logger.debug("Imported server objects: %s", ", ".join(imported_names))
    else:
        logger.debug("Imported server objects: none")


def _is_base_pin_lock_name(name: str) -> bool:
    normalized = name.lower()
    return (
        normalized in {"base_pin_male", "base_pin_female"}
        or normalized.startswith("base_pin_male.")
        or normalized.startswith("base_pin_female.")
    )


def _is_base_female_barrier_clean_base_cutter_name(name: str) -> bool:
    normalized = name.lower()
    return normalized == "base_barrier_female_clean_base_cutter" or normalized.startswith(
        "base_barrier_female_clean_base_cutter."
    )


def _barrier_voxel_size(
    imported_obj,
    *,
    box_thickness: float,
    base_thickness: float,
    wing_width: float,
    clamp_width: float,
    clamp_depth: float,
    base_type: str = "classic",
    mold_type_identifier: str = "",
) -> float:
    if "base_barrier" in imported_obj.name.lower():
        if base_type == "optimized":
            barrier_diameter = base_thickness
        else:
            barrier_diameter = min(
                base_thickness - BARRIER_DIAMETER_LIMIT_SAFEGUARD,
                wing_width + box_thickness - DISTANCE_FROM_EDGE * 2,
            )
    else:
        barrier_diameter = min(
            box_thickness
            + clamp_depth
            - CLAMP_BARRIER_DISTANCE_FROM_EDGE * 2,
            clamp_width - BARRIER_DIAMETER_LIMIT_SAFEGUARD,
        )

    # Slip casting needs a slightly finer surface on mating barrier profiles.
    return barrier_diameter / (9 if is_slip_casting_type(mold_type_identifier) else 7)


def _normalize_imported_object_geometry(imported_obj) -> None:
    """Apply required import normalization without scanning mesh topology.

    Imported geometry is otherwise consumed as returned.  Failed MANIFOLD
    Booleans perform cleanup and remesh retries lazily, so a full topology
    analysis is not charged for every successful server object.
    """
    imported_obj_bl = Object(imported_obj)
    if imported_obj.type == "MESH" and (
        _is_base_pin_lock_name(imported_obj.name)
        or _is_base_female_barrier_clean_base_cutter_name(imported_obj.name)
    ):
        return

    if imported_obj.type == "MESH" and "barrier" in imported_obj.name.lower():
        scene = bpy.context.scene
        voxel_size = _barrier_voxel_size(
            imported_obj,
            box_thickness=scene.box_thickness,
            base_thickness=scene.base_thickness,
            base_type=getattr(scene, "base_type", "classic"),
            wing_width=scene.wing_width,
            clamp_width=scene.clamp_width,
            clamp_depth=scene.clamp_depth,
            mold_type_identifier=getattr(scene, "mold_type_preview", ""),
        )
        logger.warning(
            "Imported barrier object %s; applying voxel remesh size %.6f",
            imported_obj_bl.name,
            voxel_size,
        )
        imported_obj_bl.apply_modifier(build_voxel_modifier(voxel_size))


def _remesh_imported_barrier(
    imported_obj,
    *,
    box_thickness: float,
    base_thickness: float,
    wing_width: float,
    clamp_width: float,
    clamp_depth: float,
    base_type: str = "classic",
    barrier_diameter: float | None = None,
) -> None:
    if imported_obj.type != "MESH":
        return
    if barrier_diameter is None and "barrier" not in imported_obj.name.lower():
        return
    if _is_base_female_barrier_clean_base_cutter_name(imported_obj.name):
        return

    imported_obj_bl = Object(imported_obj)
    start_time = time.perf_counter()
    voxel_size = _barrier_voxel_size(
        imported_obj,
        box_thickness=box_thickness,
        base_thickness=base_thickness,
        base_type=base_type,
        wing_width=wing_width,
        clamp_width=clamp_width,
        clamp_depth=clamp_depth,
        mold_type_identifier=getattr(bpy.context.scene, "mold_type_preview", ""),
    )
    if barrier_diameter is not None:
        voxel_size = max(float(barrier_diameter), 0.001) / 7.0
    logger.debug(
        "Imported barrier object %s; applying voxel remesh size %.6f",
        imported_obj.name,
        voxel_size,
    )
    imported_obj_bl.apply_modifier(build_voxel_modifier(voxel_size))
    assign_generated_material(imported_obj)
    logger.debug(
        "Remeshed imported barrier object %s in %.3fs",
        imported_obj.name,
        time.perf_counter() - start_time,
    )


def _join_imported_object_group(objects: list, name: str):
    if not objects:
        return None

    deselect_all_objects()
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    if len(objects) > 1:
        consumed_meshes = [obj.data for obj in objects]
        bpy.ops.object.join()
        remove_unused_meshes(consumed_meshes)

    joined_object = bpy.context.view_layer.objects.active
    joined_object.name = name
    joined_object.data.name = name
    if is_base_substracter_object(joined_object):
        set_object_hidden(joined_object, True)
    return joined_object


def _matches_imported_name(
    obj_name: str,
    name_part: str,
    *,
    prefix: bool = False,
) -> bool:
    if not prefix:
        return name_part in obj_name
    if not obj_name.startswith(name_part):
        return False
    if len(obj_name) == len(name_part):
        return True
    return obj_name[len(name_part)] in "._-"


def _join_imported_objects_by_name(imported_objects: list) -> list:
    normalized_objects = list(imported_objects)
    object_groups = (
        ("base_substracter", "base_substracter", False, True),
        ("base_barrier_female", "base_barrier_female", True, True),
        ("base_pin_female", "base_pin_female", True, True),
        ("base_pin_male", "base_pin_male", True, True),
        ("clamp_l", "clamp_l", False, True),
        ("clamp_r", "clamp_r", False, True),
        ("clamp_optimized_y", "clamp_optimized_y", False, True),
        ("clamp_optimized_x", "clamp_optimized_x", False, True),
        ("clamp_stepper_y", "clamp_stepper_y", False, True),
        ("clamp_stepper_x", "clamp_stepper_x", False, True),
        (
            "clamp_stepper_substracter_y",
            "clamp_stepper_substracter_y",
            False,
            True,
        ),
        (
            "clamp_stepper_substracter_x",
            "clamp_stepper_substracter_x",
            False,
            True,
        ),
        ("clamp_pin_female_x", "clamp_pin_female_x", False, True),
        ("clamp_pin_male_x", "clamp_pin_male_x", False, True),
        ("clamp_pin_female_y", "clamp_pin_female_y", False, True),
        ("clamp_pin_male_y", "clamp_pin_male_y", False, True),
        (
            "barrier_vertical_reinforcement_y",
            "barrier_vertical_reinforcement_y",
            True,
            True,
        ),
        (
            "barrier_vertical_reinforcement_x",
            "barrier_vertical_reinforcement_x",
            True,
            True,
        ),
        ("wing", "wing", False, False),
        ("base", "base", False, False),
    )
    for target_name, name_part, include_barriers, prefix in object_groups:
        name_part = name_part.lower()
        matching_objects = []
        for obj in normalized_objects:
            if obj is None or obj.type != "MESH":
                continue
            obj_name = obj.name.lower()
            if _is_base_female_barrier_clean_base_cutter_name(obj_name):
                continue
            if not _matches_imported_name(obj_name, name_part, prefix=prefix):
                continue
            if not include_barriers and "barrier" in obj_name:
                continue
            matching_objects.append(obj)

        if not matching_objects:
            continue

        joined = _join_imported_object_group(matching_objects, target_name)
        normalized_objects = [
            obj for obj in normalized_objects if obj not in matching_objects
        ]
        normalized_objects.append(joined)
        logger.debug(
            "Joined %s imported server object%s into %s",
            len(matching_objects),
            "" if len(matching_objects) == 1 else "s",
            target_name,
        )

    return [obj for obj in normalized_objects if obj is not None]


def _require_server_access_token(token) -> str:
    if token:
        return token
    prefs = get_addon_preferences()
    if prefs is not None and getattr(prefs, "auth_refresh_token", ""):
        raise ServerConnectionError(
            "Could not renew the Moldboxer session. Please try again."
        )
    raise AuthorizationError("Your Moldboxer session has expired. Please log in again.")


def _get_server_access_token(force_refresh=False) -> str:
    token = get_valid_access_token(force_refresh=force_refresh)
    prefs = get_addon_preferences()
    if not token and prefs is not None and getattr(prefs, "auth_refresh_token", ""):
        token = get_valid_access_token(force_refresh=True)
    return _require_server_access_token(token)


def _begin_server_access_token(force_refresh=False):
    def steps():
        if force_refresh:
            token = yield begin_get_valid_access_token(force_refresh=True)
        else:
            token = yield begin_get_valid_access_token()
        prefs = get_addon_preferences()
        if not token and prefs is not None and getattr(prefs, "auth_refresh_token", ""):
            token = yield begin_get_valid_access_token(force_refresh=True)
        return _require_server_access_token(token)

    return BackgroundTaskSequence(steps())


def _format_bearer_header(access_token: str) -> str:
    token = str(access_token or "").strip()
    if not token:
        raise AuthorizationError("Missing access token. Please log in again.")
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token:
        raise AuthorizationError("Invalid access token. Please log in again.")
    return f"Bearer {token}"


def _normalize_query_params(params: dict) -> dict:
    normalized: dict = {}
    for key, value in params.items():
        if isinstance(value, bool):
            normalized[key] = "true" if value else "false"
        else:
            normalized[key] = value
    return normalized


def _service_path(url_or_path: str) -> str:
    value = str(url_or_path or "").strip()
    parsed = urlsplit(value)
    if parsed.scheme:
        if parsed.scheme not in {"http", "https"} or not parsed.path:
            raise ValueError("Invalid Moldboxer service URL")
        if parsed.query or parsed.fragment:
            raise ValueError("Moldboxer service URL must not contain a query")
        value = parsed.path
    if not value.startswith("/") or value.startswith("//"):
        raise ValueError("Moldboxer service path must be absolute")
    return value


def _extract_response_detail(response) -> str:
    try:
        payload = response.json()
    except Exception:
        return response.text.strip() or "no detail"

    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
    return str(payload)


def _format_file_size(size_bytes: int) -> str:
    units = ("B", "KB", "MB", "GB")
    size = float(size_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size_bytes} B"


def _log_remote_worker_diagnostics(raw_diagnostics: bytes) -> None:
    try:
        diagnostics = json.loads(raw_diagnostics.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
        logger.warning("Could not decode server Blender worker diagnostics: %s", error)
        return
    if not isinstance(diagnostics, dict):
        logger.warning("Ignoring invalid server Blender worker diagnostics payload")
        return

    process_seconds = diagnostics.get("process_seconds")
    return_code = diagnostics.get("return_code")
    if isinstance(process_seconds, (int, float)):
        logger.info(
            "Server Blender worker completed in %.3fs with return code %s",
            process_seconds,
            return_code,
        )
    else:
        logger.info("Server Blender worker completed with return code %s", return_code)

    # Ignore private streams from older services as well.


def _build_export_zip(temp_dir: str, obj_names: list[str]) -> str:
    expected_files = [f"{obj_name}.ply" for obj_name in obj_names]
    temp_entries = sorted(os.listdir(temp_dir))
    logger.debug("Exported objects to %s: %s", temp_dir, temp_entries)

    unexpected_entries = [
        entry
        for entry in temp_entries
        if entry not in expected_files and entry != "exported.zip"
    ]
    if unexpected_entries:
        logger.warning(
            "Ignoring unexpected temp files for upload: %s", unexpected_entries
        )

    missing_files = [
        filename
        for filename in expected_files
        if not os.path.isfile(os.path.join(temp_dir, filename))
    ]
    if missing_files:
        raise FileNotFoundError(
            f"Missing exported PLY files before upload: {', '.join(missing_files)}"
        )

    zip_path = os.path.join(temp_dir, "exported.zip")
    raw_total_size = 0
    with zipfile.ZipFile(
        zip_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
    ) as zipf:
        for filename in expected_files:
            file_path = os.path.join(temp_dir, filename)
            file_size = os.path.getsize(file_path)
            raw_total_size += file_size
            logger.debug(
                "Adding %s to upload zip (%s)", filename, _format_file_size(file_size)
            )
            zipf.write(file_path, arcname=filename)

    zip_size = os.path.getsize(zip_path)
    if raw_total_size > 0:
        compression_ratio = zip_size / raw_total_size
        logger.debug(
            "Prepared upload zip %s (%s) from %d files totaling %s (ratio %.1f%%)",
            zip_path,
            _format_file_size(zip_size),
            len(expected_files),
            _format_file_size(raw_total_size),
            compression_ratio * 100,
        )
    else:
        logger.debug(
            "Prepared upload zip %s (%s)", zip_path, _format_file_size(zip_size)
        )
    return zip_path


def _prepare_server_request(
    url: str,
    obj_names: list[str],
    params: dict | None = None,
    *,
    authenticate: bool = True,
):
    request_start_time = time.perf_counter()
    params = _normalize_query_params(params or {})
    form_fields = {}
    organic_split_planes = params.pop("organic_split_planes", None)
    if organic_split_planes not in (None, "", "[]"):
        form_fields["organic_split_planes"] = str(organic_split_planes)
    access_token = _get_server_access_token() if authenticate else None
    if authenticate:
        _format_bearer_header(access_token or "")
    worker = acquire_geometry_worker()

    with tempfile.TemporaryDirectory() as temp_dir:
        export_start_time = time.perf_counter()
        for obj_name in obj_names:
            obj = Object(bpy.data.objects.get(obj_name))
            obj.export_tmp_ply(temp_dir)
        zip_path = _build_export_zip(temp_dir, obj_names)
        logger.debug(
            "Prepared server request payload for %s in %.3fs",
            ", ".join(obj_names),
            time.perf_counter() - export_start_time,
        )
        with open(zip_path, "rb") as f_zip:
            zip_bytes = f_zip.read()
        logger.debug(
            "Prepared request zip size %s",
            _format_file_size(len(zip_bytes)),
        )

    return (
        worker,
        _service_path(url),
        zip_bytes,
        params,
        form_fields,
        access_token or "",
        is_dev_mode(),
        request_start_time,
    )


def _raise_for_server_error(response) -> None:
    if response.ok:
        return

    detail = _extract_response_detail(response)
    if response.status_code == 401:
        raise ServerTokenRejectedError(
            f"Unauthorized ({response.status_code}): {detail}. Please log in again."
        )
    raise RuntimeError(f"Server request failed ({response.status_code}): {detail}")


def _raise_worker_service_error(error: NearestSurfaceWorkerError) -> None:
    if "Development access required" in str(error):
        raise AuthorizationError("Development access required") from error
    raise ServerConnectionError("Connection error") from error


def _send_server_zip(
    worker,
    path: str,
    zip_bytes: bytes,
    params: dict,
    form_fields: dict,
    access_token: str,
    dev_requested: bool,
    request_start_time: float,
):
    logger.debug(
        "Sending request with zip size %s",
        _format_file_size(len(zip_bytes)),
    )
    try:
        response = worker.service_zip_request(
            path,
            zip_bytes,
            query=params,
            form_fields=form_fields,
            access_token=access_token,
            dev_requested=dev_requested,
            timeout_seconds=SERVER_REQUEST_TIMEOUT_SECONDS,
            max_attempts=SERVER_REQUEST_MAX_ATTEMPTS,
            retry_backoff_seconds=SERVER_REQUEST_RETRY_BACKOFF_SECONDS,
        )
    except NearestSurfaceWorkerError as error:
        _raise_worker_service_error(error)
    _raise_for_server_error(response)
    logger.debug(
        "Protected worker service request completed in %.3fs",
        time.perf_counter() - request_start_time,
    )
    return response


def request_server(url: str, obj_names: list[str], params: dict | None = None):
    prepared = _prepare_server_request(url, obj_names, params)
    try:
        return _send_server_zip(*prepared)
    except ServerTokenRejectedError:
        token = _get_server_access_token(force_refresh=True)
        return _send_server_zip(*prepared[:5], token, *prepared[6:])


def request_server_async(
    url: str,
    obj_names: list[str],
    params: dict | None = None,
    *,
    on_complete=None,
    on_finish=None,
) -> BackgroundTaskSequence:
    prepared = _prepare_server_request(
        url,
        obj_names,
        params,
        authenticate=False,
    )
    return _begin_server_request(
        prepared,
        on_complete=on_complete,
        on_finish=on_finish,
    )


def _prepare_server_payload_request(
    url: str,
    payload: dict,
    attachments: dict[str, bytes] | None = None,
    params: dict | None = None,
    *,
    authenticate: bool = True,
):
    """Build the standard zip transport without exporting Blender objects."""

    request_start_time = time.perf_counter()
    normalized_params = _normalize_query_params(params or {})
    access_token = _get_server_access_token() if authenticate else None
    if authenticate:
        _format_bearer_header(access_token or "")
    worker = acquire_geometry_worker()
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(
        archive_buffer,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        archive.writestr(
            "payload.json",
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
        )
        for filename, content in (attachments or {}).items():
            if not filename or filename != os.path.basename(filename):
                raise ValueError("Payload attachment names must be plain filenames")
            archive.writestr(filename, content)
    return (
        worker,
        _service_path(url),
        archive_buffer.getvalue(),
        normalized_params,
        {},
        access_token or "",
        is_dev_mode(),
        request_start_time,
    )


def request_server_payload(
    url: str,
    payload: dict,
    *,
    attachments: dict[str, bytes] | None = None,
    params: dict | None = None,
):
    """POST JSON and optional files through the existing authenticated zip path."""

    prepared = _prepare_server_payload_request(
        url,
        payload,
        attachments,
        params,
    )
    try:
        return _send_server_zip(*prepared)
    except ServerTokenRejectedError:
        token = _get_server_access_token(force_refresh=True)
        return _send_server_zip(*prepared[:5], token, *prepared[6:])


def request_server_payload_async(
    url: str,
    payload: dict,
    *,
    attachments: dict[str, bytes] | None = None,
    params: dict | None = None,
    on_complete=None,
    on_finish=None,
) -> BackgroundTaskSequence:
    prepared = _prepare_server_payload_request(
        url,
        payload,
        attachments,
        params,
        authenticate=False,
    )
    return _begin_server_request(
        prepared,
        on_complete=on_complete,
        on_finish=on_finish,
    )


def _begin_server_request(
    prepared,
    *,
    on_complete=None,
    on_finish=None,
) -> BackgroundTaskSequence:
    def steps():
        try:
            access_token = yield _begin_server_access_token()
            for attempt in range(2):
                authenticated_request = (*prepared[:5], access_token, *prepared[6:])
                try:
                    response = yield BackgroundServerRequest(
                        _SERVER_REQUEST_EXECUTOR.submit(
                            _send_server_zip, *authenticated_request,
                        )
                    )
                    break
                except ServerTokenRejectedError:
                    if attempt:
                        raise
                    access_token = yield _begin_server_access_token(force_refresh=True)
            if on_complete is not None:
                return on_complete(response)
            return response
        finally:
            if on_finish is not None:
                on_finish()

    sequence = BackgroundTaskSequence(steps())
    sequence.redraw_interval = SERVER_REQUEST_REDRAW_INTERVAL_SECONDS
    return sequence


def request_server_json(url: str, payload: dict) -> dict:
    """POST a small authenticated JSON payload with the standard retry policy."""
    started = time.perf_counter()
    setup_seconds = service_seconds = 0.0
    attempts = 0
    outcome = "error"
    operation = payload.get("o")
    if operation not in ("m0", "m1", "m2", "m3", "m4", "m5"):
        operation = "other"
    path = _service_path(url).split("?", 1)[0]
    logger.debug("Server JSON request started: path=%s operation=%s", path, operation)
    try:
        access_token = _get_server_access_token()
        worker = acquire_geometry_worker()
        setup_seconds = time.perf_counter() - started
        for attempt in range(2):
            attempts += 1
            service_started = time.perf_counter()
            try:
                response = worker.service_json_request(
                    "geometry",
                    _service_path(url),
                    payload,
                    access_token=access_token,
                    dev_requested=is_dev_mode(),
                    timeout_seconds=SERVER_JSON_REQUEST_TIMEOUT_SECONDS,
                    max_attempts=SERVER_REQUEST_MAX_ATTEMPTS,
                    retry_backoff_seconds=SERVER_REQUEST_RETRY_BACKOFF_SECONDS,
                )
            except NearestSurfaceWorkerError as error:
                _raise_worker_service_error(error)
            finally:
                service_seconds += time.perf_counter() - service_started
            try:
                _raise_for_server_error(response)
                break
            except ServerTokenRejectedError:
                if attempt:
                    raise
                access_token = _get_server_access_token(force_refresh=True)
        try:
            result = response.json()
        except Exception as error:
            raise RuntimeError("Server returned an invalid JSON response") from error
        if not isinstance(result, dict):
            raise RuntimeError("Server JSON response must be an object")
        outcome = "ok"
        return result
    finally:
        logger.debug(
            "Server JSON request timing: path=%s operation=%s outcome=%s "
            "attempts=%d setup=%.6fs service=%.6fs total=%.6fs",
            path, operation, outcome, attempts, setup_seconds, service_seconds,
            time.perf_counter() - started,
        )


def import_server_response(
    response,
    *,
    remesh_imported_objects: bool = True,
    decorate_imported_objects: bool = True,
) -> list[Object]:
    """Import the response from the server
    don't apply any operations here rather than import
    and materials"""
    start_time = time.perf_counter()
    zip_temp_file = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    zip_temp_file.write(response.content)
    zip_temp_file.flush()
    zip_temp_file.close()  # IMPORTANT: close so zipfile can open it
    with tempfile.TemporaryDirectory() as extract_dir:
        with zipfile.ZipFile(zip_temp_file.name, "r") as zip_ref:
            if WORKER_DIAGNOSTICS_FILENAME in zip_ref.namelist():
                _log_remote_worker_diagnostics(
                    zip_ref.read(WORKER_DIAGNOSTICS_FILENAME)
                )
            zip_ref.extractall(extract_dir)
        imported_objects = []
        logger.debug(f"Importing objects from {extract_dir}")
        for filename in os.listdir(extract_dir):
            if filename in {WORKER_DIAGNOSTICS_FILENAME, "result.json"}:
                continue
            import_start_time = time.perf_counter()
            file_path = os.path.join(extract_dir, filename)
            imported_obj = import_model(file_path)
            if is_base_substracter_object(imported_obj):
                set_object_hidden(imported_obj, True)
            imported_obj_bl = Object(imported_obj)
            if remesh_imported_objects:
                _normalize_imported_object_geometry(imported_obj)
            if decorate_imported_objects:
                imported_obj_bl.shade_flat()
                assign_generated_material(imported_obj)
            if imported_obj.name.lower().startswith("debug_organic_cut_loop"):
                imported_obj.show_in_front = True
            if is_base_substracter_object(imported_obj):
                set_object_hidden(imported_obj, True)
            imported_objects.append(imported_obj)
            logger.debug(
                "Imported server object %s from %s in %.3fs",
                imported_obj.name,
                filename,
                time.perf_counter() - import_start_time,
            )
            if _direct_mold_ui_redraws_enabled():
                breathe_viewport()
    os.remove(zip_temp_file.name)
    set_base_substracter_hidden(True)
    if _direct_mold_ui_redraws_enabled():
        # Commit the final imported state after response cleanup as well as the
        # per-object draws above. This also refreshes an empty response.
        breathe_viewport()
    logger.debug(
        "Imported %d server object%s in %.3fs",
        len(imported_objects),
        "" if len(imported_objects) == 1 else "s",
        time.perf_counter() - start_time,
    )

    return imported_objects
