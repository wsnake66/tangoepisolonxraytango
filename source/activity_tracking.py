"""Best-effort PostHog tracking for per-model mold activity.

Every successful mold generation and utility run is captured as a user event. A
persistent pseudonymous model ID and per-model counters make repeat behavior
queryable without treating the model itself as a PostHog user.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import secrets
import struct
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)
_FALLBACK_INSTALLATION_ID = uuid.uuid4().hex
_FREE_TRIAL_LICENSE_STATUSES = frozenset(
    {
        "FREE_BASIC_GOOGLE",
        "FREE_PRO_TRIAL_GOOGLE",
    }
)

MODEL_ID_KEY = "_moldboxer_activity_model_id"
MOLD_TYPE_KEY = "_moldboxer_activity_mold_type"
UTILITIES_KEY = "_moldboxer_activity_utilities"
MOLD_GENERATION_COUNT_KEY = "_moldboxer_activity_mold_generation_count"
UTILITY_COUNTS_KEY = "_moldboxer_activity_utility_counts"
LINEAGE_SOURCE_EXPORT_ID_KEY = "_moldboxer_lineage_source_export_id"
IMPORT_FILE_FORMAT_KEY = "_moldboxer_import_file_format"
_LINEAGE_RECORD_SIZE = 64
_LINEAGE_FACET_WORDS = _LINEAGE_RECORD_SIZE // 2
_LINEAGE_RECORD_KEY = hashlib.sha256(
    b"Moldboxer opaque STL lineage record v2"
).digest()

MOLD_GENERATION_OPERATORS = frozenset(
    {
        "silicone.auto_box",
        "silicone.slip_casting_auto_box",
        "silicone.flat_auto_box",
        "silicone.automatic_mold",
        "silicone.confirm",
        "silicone.confirm_slip_casting",
        "silicone.confirm_tray",
        "silicone.confirm_direct_mold",
        "silicone.generate_fixture",
        "silicone.generate_protective_shell",
    }
)

UTILITY_OPERATORS = {
    "silicone.add_casting_input": "add_sprue",
    "silicone.auto_orient_model": "auto_level",
    "silicone.center_obj": "center",
    "silicone.clean": "clean",
    "silicone.cut": "cut",
    "silicone.decimate": "decimate",
    "silicone.grid": "grid",
    "silicone.heal_patron": "heal",
    "silicone.hollow": "hollow",
    "silicone.new_clear_undercuts": "clear_undercuts",
    "silicone.orient_face_to_base": "pick_base_face",
    "silicone.scale_height": "scale_height",
    "silicone.convert_to_planter": "convert_to_planter",
}

SILICONE_MOLD_TYPES = frozenset(
    {
        "ADAPTED_BOX",
        "TRAY_MOLD",
        "TWO_PART_SILICONE",
        "SILICONE_MULTIPART",
        "INNER_CAVITY",
    }
)


@dataclass(frozen=True)
class ActivitySnapshot:
    model_id: str
    mold_type: str
    utilities: frozenset[str]
    mold_generation_count: int
    utility_counts: tuple[tuple[str, int], ...]


def _property_get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    try:
        return obj.get(key, default)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        return default


def _property_set(obj: Any, key: str, value: Any) -> bool:
    if obj is None:
        return False
    try:
        obj[key] = value
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        return False


def _scene_object(scene: Any, name: str) -> Any | None:
    objects = getattr(scene, "objects", None)
    if objects is None:
        return None
    try:
        return objects.get(name)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        return None


def resolve_model_object(context: Any, *, prefer_active: bool = False) -> Any | None:
    """Find the durable source model rather than a generated mold component."""
    if prefer_active:
        for attribute in ("active_object", "object"):
            candidate = getattr(context, attribute, None)
            if candidate is not None:
                return candidate

    scene = getattr(context, "scene", None)
    for name in ("master", "patron"):
        candidate = _scene_object(scene, name)
        if candidate is not None:
            return candidate

    for attribute in ("object", "active_object"):
        candidate = getattr(context, attribute, None)
        if candidate is not None:
            return candidate

    view_layer = getattr(context, "view_layer", None)
    objects = getattr(view_layer, "objects", None)
    return getattr(objects, "active", None)


def _read_utilities(obj: Any) -> frozenset[str]:
    raw_value = _property_get(obj, UTILITIES_KEY, "[]")
    if isinstance(raw_value, str):
        try:
            raw_value = json.loads(raw_value)
        except (TypeError, ValueError):
            raw_value = []
    if not isinstance(raw_value, (list, tuple, set, frozenset)):
        return frozenset()
    return frozenset(
        str(value).strip() for value in raw_value if str(value).strip()
    )


def _read_utility_counts(obj: Any) -> dict[str, int]:
    raw_value = _property_get(obj, UTILITY_COUNTS_KEY, "{}")
    if isinstance(raw_value, str):
        try:
            raw_value = json.loads(raw_value)
        except (TypeError, ValueError):
            raw_value = {}
    if not isinstance(raw_value, dict):
        return {}
    counts = {}
    for name, value in raw_value.items():
        try:
            count = max(0, int(value))
        except (TypeError, ValueError):
            continue
        normalized_name = str(name).strip()
        if normalized_name:
            counts[normalized_name] = count
    return counts


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _nonnegative_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(number, 0.0) if math.isfinite(number) else 0.0


def _mold_metric_properties(context: Any, mold_type: str) -> dict[str, float]:
    scene = getattr(context, "scene", None)
    properties = {
        "casting_volume_ml": _nonnegative_float(
            getattr(scene, "casting_volume_ml", 0.0)
        )
    }
    material_volume_ml = _nonnegative_float(getattr(scene, "volume", 0.0))
    if mold_type.startswith("SLIP_CASTING"):
        water = _nonnegative_float(getattr(scene, "plaster_mix_water_ml", 70.0))
        plaster = max(_nonnegative_float(getattr(scene, "plaster_mix_plaster_g", 100.0)), 0.1)
        mix_volume = max(_nonnegative_float(getattr(scene, "plaster_mix_volume_ml", 102.0)), 0.1)
        batch_scale = material_volume_ml / mix_volume
        properties["estimated_plaster_weight_g"] = plaster * batch_scale
        properties["estimated_plaster_water_ml"] = water * batch_scale
    elif mold_type in SILICONE_MOLD_TYPES:
        silicone_density_g_per_ml = _nonnegative_float(
            getattr(scene, "silicone_density", 0.0)
        )
        properties["estimated_silicone_weight_g"] = (
            material_volume_ml * silicone_density_g_per_ml
        )
    return properties


def _utility_counts(snapshot: ActivitySnapshot) -> dict[str, int]:
    return dict(snapshot.utility_counts)


def _write_snapshot(obj: Any, snapshot: ActivitySnapshot) -> None:
    _property_set(obj, MODEL_ID_KEY, snapshot.model_id)
    _property_set(obj, MOLD_TYPE_KEY, snapshot.mold_type)
    _property_set(obj, UTILITIES_KEY, json.dumps(sorted(snapshot.utilities)))
    _property_set(
        obj,
        MOLD_GENERATION_COUNT_KEY,
        snapshot.mold_generation_count,
    )
    _property_set(
        obj,
        UTILITY_COUNTS_KEY,
        json.dumps(_utility_counts(snapshot), sort_keys=True),
    )


def ensure_model_id(obj: Any) -> str:
    model_id = str(_property_get(obj, MODEL_ID_KEY, "") or "").strip()
    if model_id:
        return model_id
    model_id = uuid.uuid4().hex
    _property_set(obj, MODEL_ID_KEY, model_id)
    return model_id


def _normalized_uuid_hex(value: Any) -> str:
    try:
        return uuid.UUID(str(value)).hex
    except (AttributeError, TypeError, ValueError):
        return ""


def _lineage_record(model_id: str, source_export_id: str) -> bytes:
    plaintext = uuid.UUID(model_id).bytes + uuid.UUID(source_export_id).bytes
    nonce = secrets.token_bytes(16)
    mask = hashlib.blake2s(
        nonce,
        key=_LINEAGE_RECORD_KEY,
        digest_size=len(plaintext),
    ).digest()
    ciphertext = bytes(
        value ^ mask_value for value, mask_value in zip(plaintext, mask)
    )
    tag = hashlib.blake2s(
        nonce + ciphertext,
        key=_LINEAGE_RECORD_KEY,
        digest_size=16,
    ).digest()
    return nonce + ciphertext + tag


def _decode_lineage_record(record: bytes) -> tuple[str, str] | None:
    if len(record) != _LINEAGE_RECORD_SIZE:
        return None
    nonce = record[:16]
    ciphertext = record[16:48]
    tag = record[48:64]
    expected_tag = hashlib.blake2s(
        nonce + ciphertext,
        key=_LINEAGE_RECORD_KEY,
        digest_size=16,
    ).digest()
    if not secrets.compare_digest(tag, expected_tag):
        return None
    mask = hashlib.blake2s(
        nonce,
        key=_LINEAGE_RECORD_KEY,
        digest_size=len(ciphertext),
    ).digest()
    plaintext = bytes(
        value ^ mask_value for value, mask_value in zip(ciphertext, mask)
    )
    try:
        return uuid.UUID(bytes=plaintext[:16]).hex, uuid.UUID(
            bytes=plaintext[16:]
        ).hex
    except ValueError:
        return None


def _lineage_facet_indices(model_file, triangle_count: int) -> tuple[int, ...]:
    if triangle_count < _LINEAGE_FACET_WORDS:
        return ()
    geometry_hash = hashlib.blake2b(digest_size=32)
    model_file.seek(84)
    for _triangle_index in range(triangle_count):
        facet = model_file.read(50)
        if len(facet) != 50:
            return ()
        geometry_hash.update(facet[:48])
    geometry_digest = geometry_hash.digest()
    indices: list[int] = []
    used: set[int] = set()
    counter = 0
    while len(indices) < _LINEAGE_FACET_WORDS:
        candidate_digest = hashlib.blake2s(
            geometry_digest + counter.to_bytes(4, "little"),
            digest_size=8,
        ).digest()
        candidate = int.from_bytes(candidate_digest, "little") % triangle_count
        if candidate not in used:
            used.add(candidate)
            indices.append(candidate)
        counter += 1
    return tuple(indices)


def _write_redundant_lineage_record(
    model_file,
    triangle_count: int,
    record: bytes,
) -> None:
    for facet_index, word_offset in zip(
        _lineage_facet_indices(model_file, triangle_count),
        range(0, len(record), 2),
    ):
        model_file.seek(84 + facet_index * 50 + 48)
        model_file.write(record[word_offset : word_offset + 2])


def _read_redundant_lineage_record(
    model_file,
    triangle_count: int,
) -> bytes | None:
    indices = _lineage_facet_indices(model_file, triangle_count)
    if not indices:
        return None
    words = []
    for facet_index in indices:
        model_file.seek(84 + facet_index * 50 + 48)
        word = model_file.read(2)
        if len(word) != 2:
            return None
        words.append(word)
    return b"".join(words)


def write_model_lineage_metadata(
    model_path: str | Path,
    obj: Any,
) -> dict[str, Any] | None:
    """Embed opaque lineage redundantly in a binary STL without changing shape."""
    path = Path(model_path)
    if path.suffix.lower() != ".stl":
        return None
    model_id = _normalized_uuid_hex(ensure_model_id(obj))
    if not model_id:
        return None
    source_export_id = uuid.uuid4().hex
    lineage_record = _lineage_record(model_id, source_export_id)
    record = {
        "model_id": model_id,
        "source_export_id": source_export_id,
        "metadata_transport": "stl_opaque_redundant_v2",
    }
    try:
        file_size = path.stat().st_size
        with path.open("r+b") as model_file:
            prefix = model_file.read(84)
            if len(prefix) != 84:
                return None
            triangle_count = struct.unpack("<I", prefix[80:84])[0]
            if file_size != 84 + triangle_count * 50:
                return None
            model_file.seek(0)
            model_file.write(lineage_record + secrets.token_bytes(16))
            _write_redundant_lineage_record(
                model_file,
                triangle_count,
                lineage_record,
            )
    except (OSError, struct.error):
        logger.warning(
            "Could not embed Moldboxer model lineage metadata: path=%s",
            path,
            exc_info=True,
        )
        return None
    return record


def read_model_lineage_metadata(model_path: str | Path) -> dict[str, Any] | None:
    path = Path(model_path)
    if path.suffix.lower() != ".stl":
        return None
    try:
        file_size = path.stat().st_size
        with path.open("rb") as model_file:
            header = model_file.read(80)
            triangle_count_bytes = model_file.read(4)
            if len(triangle_count_bytes) != 4:
                return None
            triangle_count = struct.unpack("<I", triangle_count_bytes)[0]
            if file_size != 84 + triangle_count * 50:
                return None
            decoded = _decode_lineage_record(header[:_LINEAGE_RECORD_SIZE])
            if decoded is None:
                redundant_record = _read_redundant_lineage_record(
                    model_file,
                    triangle_count,
                )
                decoded = _decode_lineage_record(redundant_record or b"")
    except (OSError, struct.error):
        return None
    if decoded is None:
        return None
    model_id, source_export_id = decoded
    return {
        "model_id": model_id,
        "source_export_id": source_export_id,
        "metadata_transport": "stl_opaque_redundant_v2",
    }


def restore_model_lineage(model_path: str | Path, obj: Any) -> dict[str, Any] | None:
    file_format = Path(model_path).suffix.lstrip(".").upper()
    _property_set(obj, IMPORT_FILE_FORMAT_KEY, file_format)
    record = read_model_lineage_metadata(model_path)
    if record is None:
        return None
    _property_set(obj, MODEL_ID_KEY, record["model_id"])
    _property_set(
        obj,
        LINEAGE_SOURCE_EXPORT_ID_KEY,
        record["source_export_id"],
    )
    return record


def _operator_is_tracked(operator_id: str) -> bool:
    return operator_id in MOLD_GENERATION_OPERATORS or operator_id in UTILITY_OPERATORS


def begin_operator_activity(operator_id: str, context: Any) -> ActivitySnapshot | None:
    """Capture model identity/state before an operator can replace its object."""
    if not _operator_is_tracked(operator_id):
        return None

    model = resolve_model_object(
        context,
        prefer_active=operator_id in UTILITY_OPERATORS,
    )
    if model is None:
        return None

    model_id = ensure_model_id(model)

    snapshot = ActivitySnapshot(
        model_id=model_id,
        mold_type=str(_property_get(model, MOLD_TYPE_KEY, "") or "").strip(),
        utilities=_read_utilities(model),
        mold_generation_count=_nonnegative_int(
            _property_get(model, MOLD_GENERATION_COUNT_KEY, 0)
        ),
        utility_counts=tuple(sorted(_read_utility_counts(model).items())),
    )
    _write_snapshot(model, snapshot)
    return snapshot


def _successful(result: Any) -> bool:
    try:
        return "FINISHED" in result
    except (TypeError, AttributeError):
        return False


def _current_mold_type(context: Any) -> str:
    scene = getattr(context, "scene", None)
    identifier = str(getattr(scene, "mold_type_preview", "") or "").strip()
    if not identifier:
        return ""
    try:
        from .mold_types import get_mold_type

        return get_mold_type(identifier).identifier
    except (ImportError, AttributeError, KeyError, TypeError):
        return identifier


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _get_addon_preferences() -> Any | None:
    try:
        from .environment import get_addon_preferences

        return get_addon_preferences()
    except (ImportError, AttributeError, ReferenceError, RuntimeError):
        return None


def _installation_id(prefs: Any | None) -> str:
    if prefs is None:
        return _FALLBACK_INSTALLATION_ID
    existing = str(
        getattr(prefs, "analytics_installation_id", "")
    ).strip()
    if existing:
        return existing
    generated = uuid.uuid4().hex
    try:
        prefs.analytics_installation_id = generated
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        pass
    return generated


def _account_email() -> str:
    prefs = _get_addon_preferences()
    return str(
        getattr(prefs, "auth_user_email", "") if prefs is not None else ""
    ).strip().lower()


def _account_id() -> str:
    prefs = _get_addon_preferences()
    email = _account_email()
    identity = f"account:{email}" if email else f"installation:{_installation_id(prefs)}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _license_type() -> str:
    prefs = _get_addon_preferences()
    if prefs is None or not bool(getattr(prefs, "auth_logged_in", False)):
        return "unknown"
    stripe_status = str(getattr(prefs, "auth_stripe_status", "")).strip().upper()
    if stripe_status in _FREE_TRIAL_LICENSE_STATUSES:
        return "free_trial"
    return "license_owner"


def _person_properties(
    snapshot: ActivitySnapshot,
    *,
    account_id: str,
    activity_at: str,
    extra: dict[str, Any],
) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "entity_type": "moldboxer_user",
        "account_id": account_id,
        "license_type": _license_type(),
        "last_activity_at": activity_at,
        "last_model_id": snapshot.model_id,
    }
    email = _account_email()
    if email:
        properties["email"] = email
    properties.update(extra)
    return properties


def _event_payload(
    snapshot: ActivitySnapshot,
    *,
    event: str,
    account_id: str,
    person_properties: dict[str, Any],
    event_properties: dict[str, Any],
) -> dict[str, Any]:
    properties = {
        "model_id": snapshot.model_id,
        "account_id": account_id,
        "license_type": person_properties["license_type"],
        "$insert_id": uuid.uuid4().hex,
        **event_properties,
        "$set": person_properties,
        "$set_once": {
            "entity_type": "moldboxer_user",
            "account_id": account_id,
            "first_seen_at": person_properties["last_activity_at"],
        },
    }
    return {
        "event": event,
        "distinct_id": f"moldboxer_user:{account_id}",
        "properties": properties,
        "timestamp": person_properties["last_activity_at"],
    }


def _send_payload(worker, payload: dict[str, Any]) -> None:
    try:
        response = worker.activity_event_request(payload, timeout_seconds=5.0)
        if not response.ok:
            raise RuntimeError(
                f"activity service returned HTTP {response.status_code}"
            )
    except Exception as error:
        logger.warning("Could not send Moldboxer activity: %s", error)


def _dispatch_payload(payload: dict[str, Any]) -> None:
    try:
        from .components.geometry_adapter import acquire_geometry_worker

        worker = acquire_geometry_worker(authorize=False)
        threading.Thread(
            target=_send_payload,
            args=(worker, payload),
            name="moldboxer-activity",
            daemon=True,
        ).start()
    except Exception:
        logger.warning("Could not start Moldboxer activity delivery", exc_info=True)


def _snapshot_for_model(context: Any) -> ActivitySnapshot | None:
    model = resolve_model_object(context)
    if model is None:
        return None
    return ActivitySnapshot(
        model_id=ensure_model_id(model),
        mold_type=str(_property_get(model, MOLD_TYPE_KEY, "") or "").strip(),
        utilities=_read_utilities(model),
        mold_generation_count=_nonnegative_int(
            _property_get(model, MOLD_GENERATION_COUNT_KEY, 0)
        ),
        utility_counts=tuple(sorted(_read_utility_counts(model).items())),
    )


def record_model_exported(
    context: Any,
    *,
    file_format: str,
    exported_object_count: int,
    lineage_records: list[dict[str, Any]],
) -> bool:
    snapshot = _snapshot_for_model(context)
    if snapshot is None:
        return False
    mold_type = snapshot.mold_type or _current_mold_type(context)
    activity_at = _utc_now()
    account_id = _account_id()
    properties = _person_properties(
        snapshot,
        account_id=account_id,
        activity_at=activity_at,
        extra={"last_export_at": activity_at},
    )
    _dispatch_payload(
        _event_payload(
            snapshot,
            event="mold_system_exported",
            account_id=account_id,
            person_properties=properties,
            event_properties={
                "file_format": str(file_format).upper(),
                "exported_object_count": max(0, int(exported_object_count)),
                "generation_index_for_model": snapshot.mold_generation_count,
                "patron_lineage_count": len(lineage_records),
                "lineage_metadata_written": bool(lineage_records),
                "source_export_ids": [
                    record["source_export_id"] for record in lineage_records
                ],
                "mold_type": mold_type or None,
                **_mold_metric_properties(context, mold_type),
            },
        )
    )
    return True


def record_model_imported(
    context: Any,
    *,
    file_format: str,
    lineage_record: dict[str, Any] | None,
) -> bool:
    snapshot = _snapshot_for_model(context)
    if snapshot is None:
        return False
    activity_at = _utc_now()
    account_id = _account_id()
    is_reimport = lineage_record is not None
    properties = _person_properties(
        snapshot,
        account_id=account_id,
        activity_at=activity_at,
        extra={"last_import_at": activity_at},
    )
    _dispatch_payload(
        _event_payload(
            snapshot,
            event="model_imported",
            account_id=account_id,
            person_properties=properties,
            event_properties={
                "file_format": str(file_format).upper(),
                "is_reimport": is_reimport,
                "lineage_restored": is_reimport,
                "source_export_id": (
                    lineage_record.get("source_export_id")
                    if lineage_record is not None
                    else None
                ),
            },
        )
    )
    return True


def record_operator_activity(
    operator_id: str,
    context: Any,
    result: Any,
    snapshot: ActivitySnapshot | None,
) -> bool:
    """Persist and send a successful model-state change.

    Returns whether a PostHog event was dispatched. Every successful tracked
    operation is dispatched, including repeats on the same model.
    """
    if snapshot is None or not _successful(result):
        return False

    model = resolve_model_object(
        context,
        prefer_active=operator_id in UTILITY_OPERATORS,
    )
    if operator_id in MOLD_GENERATION_OPERATORS:
        mold_type = _current_mold_type(context)
        if not mold_type:
            return False
        generation_index = snapshot.mold_generation_count + 1
        updated = ActivitySnapshot(
            snapshot.model_id,
            mold_type,
            snapshot.utilities,
            generation_index,
            snapshot.utility_counts,
        )
        _write_snapshot(model, updated)
        activity_at = _utc_now()
        account_id = _account_id()
        properties = _person_properties(
            updated,
            account_id=account_id,
            activity_at=activity_at,
            extra={
                "last_mold_type": mold_type,
                "last_mold_generation_at": activity_at,
            },
        )
        _dispatch_payload(
            _event_payload(
                updated,
                event="mold_generated",
                account_id=account_id,
                person_properties=properties,
                event_properties={
                    "operator_id": operator_id,
                    "mold_type": mold_type,
                    **_mold_metric_properties(context, mold_type),
                    "previous_mold_type": snapshot.mold_type or None,
                    "generation_index_for_model": generation_index,
                    "has_previous_generation": snapshot.mold_generation_count > 0,
                    "is_same_mold_type_as_previous": (
                        bool(snapshot.mold_type)
                        and mold_type == snapshot.mold_type
                    ),
                    "mold_type_changed": (
                        bool(snapshot.mold_type)
                        and mold_type != snapshot.mold_type
                    ),
                },
            )
        )
        return True

    utility = UTILITY_OPERATORS.get(operator_id)
    if not utility:
        return False
    utilities = frozenset((*snapshot.utilities, utility))
    utility_counts = _utility_counts(snapshot)
    previous_usage_count = utility_counts.get(utility, 0)
    usage_index = previous_usage_count + 1
    utility_counts[utility] = usage_index
    updated = ActivitySnapshot(
        snapshot.model_id,
        snapshot.mold_type,
        utilities,
        snapshot.mold_generation_count,
        tuple(sorted(utility_counts.items())),
    )
    _write_snapshot(model, updated)
    activity_at = _utc_now()
    account_id = _account_id()
    properties = _person_properties(
        updated,
        account_id=account_id,
        activity_at=activity_at,
        extra={
            f"used_{utility}": True,
            "last_utility": utility,
            "last_utility_at": activity_at,
        },
    )
    _dispatch_payload(
        _event_payload(
            updated,
            event="model_utility_used",
            account_id=account_id,
            person_properties=properties,
            event_properties={
                "operator_id": operator_id,
                "utility": utility,
                "usage_index_for_model": usage_index,
                "previous_usage_count": previous_usage_count,
                "is_repeat_for_model": previous_usage_count > 0,
                "mold_type": snapshot.mold_type or None,
            },
        )
    )
    return True
