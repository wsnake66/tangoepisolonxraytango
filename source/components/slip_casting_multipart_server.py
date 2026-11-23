"""Authenticated remote planning through an opaque wire contract."""
from ..environment import get_server_base_url
from ..multipart_plan import validate_plan
from ..split_specs import representative_split_specs


def request_multipart_plan(operation, **arguments):
    from .server import request_server_json

    if "plane_specs" in arguments:
        arguments["plane_specs"] = representative_split_specs(arguments["plane_specs"])
    operation_codes = {
        "locking": "m0", "placements": "m1", "routes": "m2",
        "gaps": "m3", "gap_candidates": "m4", "base_sections": "m5",
    }
    argument_fields = {
        "locking": ("box_wall_thickness", "requested_pin_diameter", "mold_thickness", "plaster_locking_pin_type", "master_base_mode", "silicone_multipart"),
        "placements": ("plane_specs", "parts", "distance", "mode", "cut_half_thickness"),
        "routes": ("kind", "target_plane_indices", "plaster_bounds", "plaster_sides", "split_base_bounds", "split_base_sides", "split_base_plane_indices", "bounds_tolerance"),
        "gaps": ("plane_specs", "parts", "locking_plan"),
        "gap_candidates": ("plane_specs", "distance"),
        "base_sections": ("plane_specs", "parts", "sections", "distance"),
    }
    code = operation_codes[operation]
    values = [arguments.get(name) for name in argument_fields[operation]]
    if operation in ("placements", "base_sections"):
        values[1] = [[part.get("own_plane"), part.get("sides")] for part in (values[1] or ())]
    elif operation == "gaps":
        values[1] = [[part.get("own_plane"), part.get("center"), part.get("height")]
                     for part in (values[1] or ())]
        names = ("effective_pin_diameter", "female_cap_height", "pin_clearance", "gap_thickness",
                 "center_keepout_diameter", "gap_center_offset", "pin_keepout_diameter", "split_base_thickness")
        values[2] = [values[2].get(name) for name in names] if values[2] is not None else None
    response = request_server_json(
        f"{get_server_base_url()}/v1/p/",
        {"v": 1, "o": code, "a": values},
    )
    response = _decode_response(response, operation, code)
    return validate_plan(response, operation, arguments)


def _decode_response(response, operation, code):
    if not isinstance(response, dict) or set(response) != {"v", "o", "r"}:
        raise ValueError("Unsupported remote response")
    if response["v"] != 1 or response["o"] != code:
        raise ValueError("Unsupported remote response")
    raw = response["r"]
    if operation == "locking":
        names = ("effective_pin_diameter", "female_cap_height", "pin_clearance", "gap_thickness",
                 "center_keepout_diameter", "gap_center_offset", "pin_keepout_diameter", "split_base_thickness")
        result = dict(zip(names, raw)) if isinstance(raw, list) and len(raw) == len(names) else None
    elif operation == "placements":
        result = {"movements": raw}
    elif operation == "routes":
        result = {"routes": raw}
    elif operation == "gap_candidates":
        result = {"cutters": [dict(zip(("normal", "center", "thickness"), record)) for record in raw]}
    elif operation == "gaps":
        names = ("normal", "center", "bridge_center", "thickness", "bridge_height", "bridge_radius", "pin_radius")
        result = {"gaps": [None if record is None else dict(zip(names, record)) for record in raw]}
    elif operation == "base_sections":
        result = {"sections": [[{"section_index": route[0], "cuts": [
            {"normal": cut[0], "center": cut[1]} for cut in route[1]]} for route in routes] for routes in raw]}
    else:
        result = None
    return {"version": 1, "operation": operation, "result": result}


def plan_slip_casting_split_base_subtractions_with_server(**arguments):
    return request_multipart_plan("routes", **arguments)["routes"]


def plan_slip_casting_split_base_locking_geometry_with_server(**arguments):
    return request_multipart_plan("locking", **arguments)


def plan_slip_casting_movements(plane_specs, parts, distance, *, mode="separate", cut_half_thickness=0.01):
    return request_multipart_plan(
        "placements", plane_specs=plane_specs, parts=parts, distance=float(distance),
        mode=mode, cut_half_thickness=float(cut_half_thickness),
    )["movements"]
