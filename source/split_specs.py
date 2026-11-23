"""Compatibility helpers for legacy planar and organic split specs."""

from __future__ import annotations

import json
import math


def split_spec_point_normal(spec):
    if isinstance(spec, dict):
        return spec["point"], spec["normal"]
    return spec[0], spec[1]


def representative_split_specs(specs):
    return [
        [
            [float(value) for value in split_spec_point_normal(spec)[0]],
            [float(value) for value in split_spec_point_normal(spec)[1]],
        ]
        for spec in specs or []
    ]


def is_organic_split_spec(spec) -> bool:
    return isinstance(spec, dict) and spec.get("type") == "organic"


def _unit_vector(values) -> tuple[float, float, float]:
    vector = tuple(float(value) for value in values)
    length = math.sqrt(sum(value * value for value in vector))
    if length <= 1.0e-12:
        return (0.0, 0.0, 1.0)
    return tuple(value / length for value in vector)


def replace_planar_specs_with_organic(specs):
    """Treat each drawn organic split as a replacement for its closest guide."""
    specs = list(specs or [])
    organic_specs = [spec for spec in specs if is_organic_split_spec(spec)]
    resolved = [spec for spec in specs if not is_organic_split_spec(spec)]
    if not organic_specs or not resolved:
        return specs

    available_indices = set(range(len(resolved)))
    for organic_spec in organic_specs:
        if not available_indices:
            resolved.append(organic_spec)
            continue
        organic_point, organic_normal = split_spec_point_normal(organic_spec)
        organic_normal = _unit_vector(organic_normal)

        def match_key(index):
            point, normal = split_spec_point_normal(resolved[index])
            normal = _unit_vector(normal)
            alignment = abs(sum(a * b for a, b in zip(organic_normal, normal)))
            point_distance = math.sqrt(
                sum(
                    (float(a) - float(b)) ** 2
                    for a, b in zip(organic_point, point)
                )
            )
            return alignment, -point_distance

        replacement_index = max(available_indices, key=match_key)
        resolved[replacement_index] = organic_spec
        available_indices.remove(replacement_index)
    return resolved


def split_specs_query_values(specs) -> tuple[str, str]:
    """Return a legacy plane query plus indexed organic geometry overrides."""
    specs = list(specs or [])
    legacy_planes = representative_split_specs(specs)
    organic_overrides = [
        {"index": index, "spec": spec}
        for index, spec in enumerate(specs)
        if is_organic_split_spec(spec)
    ]
    return (
        json.dumps(legacy_planes, separators=(",", ":")),
        json.dumps(organic_overrides, separators=(",", ":")),
    )
