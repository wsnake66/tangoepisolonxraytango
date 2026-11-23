"""Read the printable core mesh geometry from a 3MF package.

This module deliberately has no Blender dependency.  It reads the primary 3D
model and flattens the model objects referenced by ``build`` into one mesh.
Materials, thumbnails, print tickets, slice data, and slicer profiles are not
imported.  Bambu/Orca part-role metadata is consulted only to omit modifier,
negative, and support volumes from the resulting model geometry.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import posixpath
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import unquote
import xml.etree.ElementTree as ET
from zipfile import BadZipFile, ZipFile


CORE_NAMESPACE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
MODEL_RELATIONSHIP_TYPE = (
    "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"
)

# These extensions can attach identity, grouping, or appearance information to
# an ordinary core mesh without changing its vertex positions or triangles.
# Geometry-producing extensions are intentionally not listed.
_NON_GEOMETRY_EXTENSION_NAMESPACES = {
    "http://schemas.microsoft.com/3dmanufacturing/material/2015/02",
    "http://schemas.microsoft.com/3dmanufacturing/production/2015/06",
    "http://schemas.microsoft.com/3dmanufacturing/trianglesets/2021/07",
}

_UNIT_TO_MILLIMETERS = {
    "micron": 0.001,
    "millimeter": 1.0,
    "centimeter": 10.0,
    "inch": 25.4,
    "foot": 304.8,
    "meter": 1000.0,
}

_NON_MODEL_PART_SUBTYPES = {
    "modifier_part",
    "negative_part",
    "parameter_modifier",
    "support_blocker",
    "support_enforcer",
}

Vector3 = tuple[float, float, float]
Triangle = tuple[int, int, int]
Matrix4 = tuple[
    tuple[float, float, float, float],
    tuple[float, float, float, float],
    tuple[float, float, float, float],
    tuple[float, float, float, float],
]

_IDENTITY: Matrix4 = (
    (1.0, 0.0, 0.0, 0.0),
    (0.0, 1.0, 0.0, 0.0),
    (0.0, 0.0, 1.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
)


class ThreeMFError(ValueError):
    """Raised when a 3MF package cannot safely produce core mesh geometry."""


@dataclass(frozen=True)
class Geometry:
    name: str
    vertices: tuple[Vector3, ...]
    triangles: tuple[Triangle, ...]


@dataclass(frozen=True)
class _Mesh:
    vertices: tuple[Vector3, ...]
    triangles: tuple[Triangle, ...]


@dataclass(frozen=True)
class _Component:
    object_id: int
    transform: Matrix4
    part_path: str | None = None
    printable: bool = True


@dataclass(frozen=True)
class _ObjectResource:
    mesh: _Mesh | None
    components: tuple[_Component, ...]
    object_type: str


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(element: ET.Element, name: str) -> ET.Element | None:
    return next((item for item in element if _local_name(item.tag) == name), None)


def _children(element: ET.Element, name: str) -> Iterable[ET.Element]:
    return (item for item in element if _local_name(item.tag) == name)


def _attribute(element: ET.Element, name: str) -> str | None:
    for attribute_name, value in element.attrib.items():
        if _local_name(attribute_name) == name:
            return value
    return None


def _package_part_name(target: str, *, relative_to: str | None = None) -> str:
    decoded = unquote(target).replace("\\", "/")
    if decoded.startswith("/") or relative_to is None:
        combined = decoded
    else:
        combined = posixpath.join(posixpath.dirname(relative_to), decoded)
    normalized = posixpath.normpath("/" + combined).lstrip("/")
    if not normalized or normalized == ".":
        raise ThreeMFError("The 3MF package has an empty model-part target")
    return normalized


def _primary_model_part(package: ZipFile) -> str:
    names_by_lowercase = {name.lower(): name for name in package.namelist()}
    relationships_name = names_by_lowercase.get("_rels/.rels")
    if relationships_name is not None:
        try:
            with package.open(relationships_name) as relationships_file:
                relationships = ET.parse(relationships_file).getroot()
        except ET.ParseError as exc:
            raise ThreeMFError("The 3MF package relationships are invalid XML") from exc

        for relationship in relationships:
            if (
                _local_name(relationship.tag) == "Relationship"
                and relationship.get("Type") == MODEL_RELATIONSHIP_TYPE
            ):
                if relationship.get("TargetMode", "Internal") == "External":
                    raise ThreeMFError("External 3MF model parts are not supported")
                target = relationship.get("Target")
                if not target:
                    raise ThreeMFError("The 3MF model relationship has no target")
                part_name = _package_part_name(target)
                actual_name = names_by_lowercase.get(part_name.lower())
                if actual_name is None:
                    raise ThreeMFError(
                        f"The 3MF model part is missing from the package: {part_name}"
                    )
                return actual_name

    conventional_name = names_by_lowercase.get("3d/3dmodel.model")
    if conventional_name is not None:
        return conventional_name
    raise ThreeMFError("The 3MF package does not contain a primary 3D model")


def _parse_model_xml(package: ZipFile, part_name: str) -> tuple[ET.Element, dict[str, str]]:
    namespaces: dict[str, str] = {}
    try:
        with package.open(part_name) as model_file:
            parser = ET.iterparse(model_file, events=("start-ns", "end"))
            for event, value in parser:
                if event == "start-ns":
                    prefix, uri = value
                    namespaces[prefix or ""] = uri
            root = parser.root
    except ET.ParseError as exc:
        raise ThreeMFError("The primary 3MF model is invalid XML") from exc
    return root, namespaces


def _slicer_non_model_resource_ids(package: ZipFile) -> frozenset[int]:
    """Read only Bambu/Orca part roles needed to identify non-model meshes."""
    config_name = next(
        (
            name
            for name in package.namelist()
            if name.lower() == "metadata/model_settings.config"
        ),
        None,
    )
    if config_name is None:
        return frozenset()
    try:
        with package.open(config_name) as config_file:
            root = ET.parse(config_file).getroot()
    except (ET.ParseError, OSError):
        # Vendor metadata is advisory.  Invalid settings must not prevent core
        # geometry from being imported.
        return frozenset()

    excluded: set[int] = set()
    for object_element in _children(root, "object"):
        for part in object_element:
            if _local_name(part.tag) not in {"part", "volume"}:
                continue
            subtype = part.get("subtype", "").strip().lower()
            if subtype not in _NON_MODEL_PART_SUBTYPES or part.get("id") is None:
                continue
            try:
                excluded.add(_integer(part.get("id"), "slicer part resource id"))
            except ThreeMFError:
                continue
    return frozenset(excluded)


def _validate_model_root(root: ET.Element, namespaces: dict[str, str]) -> None:
    if _local_name(root.tag) != "model":
        raise ThreeMFError("The primary 3MF part does not contain a model")
    namespace = root.tag.partition("}")[0].lstrip("{") if "}" in root.tag else ""
    if namespace != CORE_NAMESPACE:
        raise ThreeMFError(f"Unsupported 3MF core namespace: {namespace or 'none'}")

    unsupported: list[str] = []
    for prefix in root.get("requiredextensions", "").split():
        uri = namespaces.get(prefix)
        if uri not in _NON_GEOMETRY_EXTENSION_NAMESPACES:
            unsupported.append(prefix)
    if unsupported:
        raise ThreeMFError(
            "Unsupported required 3MF extension(s): " + ", ".join(unsupported)
        )


def _float(value: str | None, description: str) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ThreeMFError(f"Invalid {description}") from exc
    if not math.isfinite(number):
        raise ThreeMFError(f"Non-finite {description}")
    return number


def _integer(value: str | None, description: str) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ThreeMFError(f"Invalid {description}") from exc


def _boolean(value: str | None, *, default: bool = True) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true"}:
        return True
    if normalized in {"0", "false"}:
        return False
    raise ThreeMFError(f"Invalid 3MF boolean value: {value}")


def _transform(value: str | None) -> Matrix4:
    if value is None or not value.strip():
        return _IDENTITY
    values = value.split()
    if len(values) != 12:
        raise ThreeMFError("A 3MF transform must contain exactly 12 numbers")
    numbers = tuple(_float(item, "3MF transform value") for item in values)
    # 3MF serializes a row-vector matrix.  Transpose it into the conventional
    # column-vector representation used by the functions below and by Blender.
    return (
        (numbers[0], numbers[3], numbers[6], numbers[9]),
        (numbers[1], numbers[4], numbers[7], numbers[10]),
        (numbers[2], numbers[5], numbers[8], numbers[11]),
        (0.0, 0.0, 0.0, 1.0),
    )


def _multiply(left: Matrix4, right: Matrix4) -> Matrix4:
    return tuple(
        tuple(sum(left[row][k] * right[k][column] for k in range(4)) for column in range(4))
        for row in range(4)
    )  # type: ignore[return-value]


def _apply(matrix: Matrix4, vertex: Vector3) -> Vector3:
    x, y, z = vertex
    return (
        matrix[0][0] * x + matrix[0][1] * y + matrix[0][2] * z + matrix[0][3],
        matrix[1][0] * x + matrix[1][1] * y + matrix[1][2] * z + matrix[1][3],
        matrix[2][0] * x + matrix[2][1] * y + matrix[2][2] * z + matrix[2][3],
    )


def _determinant3(matrix: Matrix4) -> float:
    a, b, c = matrix[0][:3]
    d, e, f = matrix[1][:3]
    g, h, i = matrix[2][:3]
    return a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)


def _parse_mesh(mesh_element: ET.Element, object_id: int) -> _Mesh:
    vertices_element = _child(mesh_element, "vertices")
    triangles_element = _child(mesh_element, "triangles")
    if vertices_element is None or triangles_element is None:
        raise ThreeMFError(f"3MF object {object_id} has an incomplete mesh")

    vertices = tuple(
        (
            _float(vertex.get("x"), "vertex x coordinate"),
            _float(vertex.get("y"), "vertex y coordinate"),
            _float(vertex.get("z"), "vertex z coordinate"),
        )
        for vertex in _children(vertices_element, "vertex")
    )
    triangles = tuple(
        (
            _integer(triangle.get("v1"), "triangle vertex index"),
            _integer(triangle.get("v2"), "triangle vertex index"),
            _integer(triangle.get("v3"), "triangle vertex index"),
        )
        for triangle in _children(triangles_element, "triangle")
    )
    if not vertices or not triangles:
        raise ThreeMFError(f"3MF object {object_id} has an empty mesh")
    vertex_count = len(vertices)
    if any(
        index < 0 or index >= vertex_count
        for triangle in triangles
        for index in triangle
    ):
        raise ThreeMFError(f"3MF object {object_id} has an invalid triangle index")

    # Some slicers retain large vertex buffers after editing an object even
    # though most entries are no longer referenced by a triangle. Importing
    # those entries into Blender creates one loose vertex island per entry.
    # Compact each resource before flattening so only actual mesh geometry is
    # passed to Blender and triangle indices continue to address the new array.
    used_vertex_indices = sorted(
        {index for triangle in triangles for index in triangle}
    )
    if len(used_vertex_indices) != vertex_count:
        remapped_indices = [-1] * vertex_count
        for new_index, old_index in enumerate(used_vertex_indices):
            remapped_indices[old_index] = new_index
        vertices = tuple(vertices[index] for index in used_vertex_indices)
        triangles = tuple(
            (
                remapped_indices[triangle[0]],
                remapped_indices[triangle[1]],
                remapped_indices[triangle[2]],
            )
            for triangle in triangles
        )
    return _Mesh(vertices, triangles)


def _parse_resources(root: ET.Element) -> dict[int, _ObjectResource]:
    resources_element = _child(root, "resources")
    if resources_element is None:
        raise ThreeMFError("The 3MF model has no resources")

    resources: dict[int, _ObjectResource] = {}
    for object_element in _children(resources_element, "object"):
        object_id = _integer(object_element.get("id"), "object resource id")
        object_type = object_element.get("type", "model")
        if object_id in resources:
            raise ThreeMFError(f"Duplicate 3MF object resource id: {object_id}")
        mesh_element = _child(object_element, "mesh")
        components_element = _child(object_element, "components")
        if (mesh_element is None) == (components_element is None):
            raise ThreeMFError(
                f"3MF object {object_id} must contain one mesh or components element"
            )
        if mesh_element is not None:
            resource = _ObjectResource(
                _parse_mesh(mesh_element, object_id),
                (),
                object_type,
            )
        else:
            components = tuple(
                _Component(
                    _integer(component.get("objectid"), "component object id"),
                    _transform(component.get("transform")),
                    _attribute(component, "path"),
                )
                for component in _children(components_element, "component")  # type: ignore[arg-type]
            )
            if not components:
                raise ThreeMFError(f"3MF object {object_id} has no components")
            resource = _ObjectResource(None, components, object_type)
        resources[object_id] = resource
    return resources


def _build_items(root: ET.Element) -> tuple[_Component, ...]:
    build_element = _child(root, "build")
    if build_element is None:
        raise ThreeMFError("The 3MF model has no build instructions")
    items = tuple(
        _Component(
            _integer(item.get("objectid"), "build item object id"),
            _transform(item.get("transform")),
            _attribute(item, "path"),
            _boolean(_attribute(item, "printable")),
        )
        for item in _children(build_element, "item")
    )
    if not items:
        raise ThreeMFError("The 3MF build contains no objects")
    return items


def _flatten_geometry(
    primary_part: str,
    resources_for_part: Callable[[str], dict[int, _ObjectResource]],
    items: tuple[_Component, ...],
    unit_scale: float,
    excluded_resources: frozenset[tuple[str, int]],
) -> tuple[tuple[Vector3, ...], tuple[Triangle, ...]]:
    vertices: list[Vector3] = []
    triangles: list[Triangle] = []

    def add_object(
        part_name: str,
        object_id: int,
        transform: Matrix4,
        ancestors: frozenset[tuple[str, int]],
    ) -> None:
        resource_key = (part_name, object_id)
        if resource_key in excluded_resources:
            return
        if resource_key in ancestors:
            raise ThreeMFError(
                f"Cyclic 3MF component reference at {part_name} object {object_id}"
            )
        resource = resources_for_part(part_name).get(object_id)
        if resource is None:
            raise ThreeMFError(
                f"Missing 3MF object resource: {part_name} object {object_id}"
            )
        if resource.object_type != "model":
            return

        if resource.mesh is not None:
            vertex_offset = len(vertices)
            vertices.extend(
                tuple(coordinate * unit_scale for coordinate in _apply(transform, vertex))
                for vertex in resource.mesh.vertices
            )
            mirrored = _determinant3(transform) < 0.0
            triangles.extend(
                (
                    vertex_offset + triangle[0],
                    vertex_offset + triangle[2 if mirrored else 1],
                    vertex_offset + triangle[1 if mirrored else 2],
                )
                for triangle in resource.mesh.triangles
            )
            return

        next_ancestors = ancestors | {resource_key}
        for component in resource.components:
            component_part = (
                _package_part_name(component.part_path, relative_to=part_name)
                if component.part_path
                else part_name
            )
            add_object(
                component_part,
                component.object_id,
                _multiply(transform, component.transform),
                next_ancestors,
            )

    for item in items:
        if not item.printable:
            continue
        item_part = (
            _package_part_name(item.part_path, relative_to=primary_part)
            if item.part_path
            else primary_part
        )
        add_object(item_part, item.object_id, item.transform, frozenset())
    if not vertices or not triangles:
        raise ThreeMFError("The 3MF build does not resolve to mesh geometry")
    return tuple(vertices), tuple(triangles)


def load_3mf_geometry(path: str | Path) -> Geometry:
    """Load and flatten the primary 3MF build into millimeter mesh geometry."""
    source_path = Path(path)
    try:
        with ZipFile(source_path) as package:
            model_part = _primary_model_part(package)
            root, namespaces = _parse_model_xml(package, model_part)
            _validate_model_root(root, namespaces)
            unit = root.get("unit", "millimeter")
            try:
                unit_scale = _UNIT_TO_MILLIMETERS[unit]
            except KeyError as exc:
                raise ThreeMFError(f"Unsupported 3MF unit: {unit}") from exc

            names_by_lowercase = {name.lower(): name for name in package.namelist()}
            resources_by_part = {model_part: _parse_resources(root)}
            excluded_resources = frozenset(
                (model_part, object_id)
                for object_id in _slicer_non_model_resource_ids(package)
            )

            def resources_for_part(part_name: str) -> dict[int, _ObjectResource]:
                actual_name = names_by_lowercase.get(part_name.lower())
                if actual_name is None:
                    raise ThreeMFError(
                        f"The referenced 3MF model part is missing: {part_name}"
                    )
                cached = resources_by_part.get(actual_name)
                if cached is not None:
                    return cached
                part_root, part_namespaces = _parse_model_xml(package, actual_name)
                _validate_model_root(part_root, part_namespaces)
                part_unit = part_root.get("unit", "millimeter")
                if part_unit != unit:
                    raise ThreeMFError(
                        "Referenced 3MF model parts must use the same unit"
                    )
                parsed = _parse_resources(part_root)
                resources_by_part[actual_name] = parsed
                return parsed

            items = _build_items(root)
            vertices, triangles = _flatten_geometry(
                model_part,
                resources_for_part,
                items,
                unit_scale,
                excluded_resources,
            )
    except (BadZipFile, OSError) as exc:
        raise ThreeMFError("The selected file is not a readable 3MF package") from exc
    return Geometry(source_path.stem, vertices, triangles)
