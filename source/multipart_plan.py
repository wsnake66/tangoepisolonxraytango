"""Validate remote multipart instructions before changing Blender objects."""
import math


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("Invalid multipart plan number")


def _vector(value):
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError("Invalid multipart plan vector")
    for coordinate in value:
        _number(coordinate)


def _records(result, key, count):
    records = result.get(key)
    if not isinstance(records, list) or len(records) != count:
        raise ValueError("Incomplete multipart plan")
    return records


def validate_plan(response, operation, arguments):
    if not isinstance(response, dict) or type(response.get("version")) is not int or response["version"] != 1 or response.get("operation") != operation:
        raise ValueError("Unsupported multipart plan response")
    result = response.get("result")
    if not isinstance(result, dict):
        raise ValueError("Invalid multipart plan result")
    if operation == "locking":
        for key in ("effective_pin_diameter", "female_cap_height", "pin_clearance", "gap_thickness",
                    "center_keepout_diameter", "gap_center_offset", "pin_keepout_diameter", "split_base_thickness"):
            _number(result.get(key))
            if result[key] < 0:
                raise ValueError("Negative locking dimension")
    elif operation == "base_sections":
        for routes in _records(result, "sections", len(arguments["parts"])):
            if not isinstance(routes, list):
                raise ValueError("Invalid base section routes")
            seen = set()
            for route in routes:
                index = route.get("section_index")
                if type(index) is not int or not 0 <= index < len(arguments["sections"]) or index in seen:
                    raise ValueError("Invalid base section owner")
                seen.add(index)
                cuts = route.get("cuts")
                if not isinstance(cuts, list) or len(cuts) > len(arguments["plane_specs"]):
                    raise ValueError("Invalid base section cuts")
                for cut in cuts:
                    _vector(cut.get("normal"))
                    _vector(cut.get("center"))
                    if sum(v*v for v in cut["normal"]) <= 1e-18:
                        raise ValueError("Invalid base section normal")
    elif operation == "placements":
        for movement in _records(result, "movements", len(arguments["parts"])):
            _vector(movement)
    elif operation == "routes":
        count = len(arguments["split_base_bounds"])
        for route in _records(result, "routes", len(arguments["plaster_bounds"])):
            if not isinstance(route, list) or any(type(i) is not int or not 0 <= i < count for i in route):
                raise ValueError("Invalid multipart route")
            if len(set(route)) != len(route):
                raise ValueError("Duplicate multipart route")
    elif operation in ("gaps", "gap_candidates"):
        is_gap = operation == "gaps"
        count = len(arguments["parts"] if is_gap else arguments["plane_specs"])
        for record in _records(result, "gaps" if is_gap else "cutters", count):
            if record is None and is_gap:
                continue
            if not isinstance(record, dict):
                raise ValueError("Invalid multipart cutter")
            for key in ("normal", "center", "bridge_center") if is_gap else ("normal", "center"):
                _vector(record.get(key))
            if sum(v*v for v in record["normal"]) <= 1e-18:
                raise ValueError("Invalid cutter normal")
            for key in ("thickness", "bridge_height", "bridge_radius", "pin_radius") if is_gap else ("thickness",):
                _number(record.get(key))
                if record[key] < 0:
                    raise ValueError("Negative cutter dimension")
    else:
        raise ValueError("Unknown multipart operation")
    return result
