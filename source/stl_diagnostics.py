from __future__ import annotations

from dataclasses import dataclass
import io
import math
from pathlib import Path
import struct
from typing import BinaryIO


_FACET = struct.Struct("<12fH")
_COUNT = struct.Struct("<I")
_SAMPLE_LIMIT = 10
Point = tuple[float, float, float]
Edge = tuple[Point, Point]


@dataclass(frozen=True)
class STLEdgeSample:
    start: Point
    end: Point
    face_count: int


@dataclass(frozen=True)
class STLDiagnostics:
    facets: int
    degenerate_facets: int
    invalid_facets: int
    duplicate_facets: int
    open_edges: int
    non_manifold_edges: int
    inconsistent_winding_edges: int
    open_edge_samples: tuple[STLEdgeSample, ...]
    non_manifold_edge_samples: tuple[STLEdgeSample, ...]
    inconsistent_winding_samples: tuple[STLEdgeSample, ...]
    problem_edges: tuple[STLEdgeSample, ...]

    @property
    def issue_count(self) -> int:
        return (
            self.non_manifold_edges
            + self.open_edges
            + self.inconsistent_winding_edges
            + self.degenerate_facets
            + self.invalid_facets
            + self.duplicate_facets
        )


def _canonical_edge(start: Point, end: Point) -> tuple[Edge, int]:
    if start <= end:
        return (start, end), 1
    return (end, start), -1


def _has_zero_area(a: Point, b: Point, c: Point) -> bool:
    ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    ac = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    cross = (
        ab[1] * ac[2] - ab[2] * ac[1],
        ab[2] * ac[0] - ab[0] * ac[2],
        ab[0] * ac[1] - ab[1] * ac[0],
    )
    return cross == (0.0, 0.0, 0.0)


def _diagnose_binary_stl(stream: BinaryIO) -> STLDiagnostics:
    header = stream.read(80)
    count_bytes = stream.read(_COUNT.size)
    if len(header) != 80 or len(count_bytes) != _COUNT.size:
        raise ValueError("The STL is too short to contain a binary header")

    facet_count = _COUNT.unpack(count_bytes)[0]
    edge_uses: dict[Edge, list[int]] = {}
    seen_facets: set[tuple[Point, Point, Point]] = set()
    degenerate_facets = 0
    invalid_facets = 0
    duplicate_facets = 0

    for facet_index in range(facet_count):
        record = stream.read(_FACET.size)
        if len(record) != _FACET.size:
            raise ValueError(
                f"The binary STL ends inside facet {facet_index + 1} of {facet_count}"
            )
        values = _FACET.unpack(record)
        vertices = (
            (values[3], values[4], values[5]),
            (values[6], values[7], values[8]),
            (values[9], values[10], values[11]),
        )
        if not all(math.isfinite(value) for vertex in vertices for value in vertex):
            invalid_facets += 1
            continue
        if len(set(vertices)) != 3 or _has_zero_area(*vertices):
            degenerate_facets += 1
            continue

        facet_key = tuple(sorted(vertices))
        if facet_key in seen_facets:
            duplicate_facets += 1
        else:
            seen_facets.add(facet_key)

        for start, end in (
            (vertices[0], vertices[1]),
            (vertices[1], vertices[2]),
            (vertices[2], vertices[0]),
        ):
            edge, direction = _canonical_edge(start, end)
            usage = edge_uses.setdefault(edge, [0, 0])
            usage[0] += 1
            usage[1] += direction

    open_samples: list[STLEdgeSample] = []
    non_manifold_samples: list[STLEdgeSample] = []
    winding_samples: list[STLEdgeSample] = []
    open_edges = 0
    non_manifold_edges = 0
    inconsistent_winding_edges = 0
    problem_edges: list[STLEdgeSample] = []
    for (start, end), (face_uses, direction_sum) in edge_uses.items():
        sample = STLEdgeSample(start, end, face_uses)
        if face_uses == 1:
            open_edges += 1
            problem_edges.append(sample)
            if len(open_samples) < _SAMPLE_LIMIT:
                open_samples.append(sample)
        elif face_uses > 2:
            non_manifold_edges += 1
            problem_edges.append(sample)
            if len(non_manifold_samples) < _SAMPLE_LIMIT:
                non_manifold_samples.append(sample)
        elif abs(direction_sum) == 2:
            inconsistent_winding_edges += 1
            problem_edges.append(sample)
            if len(winding_samples) < _SAMPLE_LIMIT:
                winding_samples.append(sample)

    return STLDiagnostics(
        facets=facet_count,
        degenerate_facets=degenerate_facets,
        invalid_facets=invalid_facets,
        duplicate_facets=duplicate_facets,
        open_edges=open_edges,
        non_manifold_edges=non_manifold_edges,
        inconsistent_winding_edges=inconsistent_winding_edges,
        open_edge_samples=tuple(open_samples),
        non_manifold_edge_samples=tuple(non_manifold_samples),
        inconsistent_winding_samples=tuple(winding_samples),
        problem_edges=tuple(problem_edges),
    )


def diagnose_binary_stl(path: str | Path) -> STLDiagnostics:
    with Path(path).open("rb") as stream:
        return _diagnose_binary_stl(stream)


def diagnose_binary_stl_bytes(data: bytes) -> STLDiagnostics:
    return _diagnose_binary_stl(io.BytesIO(data))


def _format_point(point: Point) -> str:
    return f"({point[0]:.6g}, {point[1]:.6g}, {point[2]:.6g})"


def _sample_lines(samples: tuple[STLEdgeSample, ...]) -> list[str]:
    return [
        f"  {_format_point(item.start)} -> {_format_point(item.end)} "
        f"[{item.face_count} face users]"
        for item in samples
    ]


def format_stl_diagnostics_report(
    object_name: str,
    bambu_manifold: bool,
    diagnostics: STLDiagnostics,
) -> str:
    lines = [
        f"Object: {object_name}",
        f"Bambu Studio manifold: {'YES' if bambu_manifold else 'NO'}",
        "Open-edge check: "
        f"{'PASS' if diagnostics.open_edges == 0 else 'FAIL'}",
        "Combined manifold status: "
        f"{'YES' if bambu_manifold and diagnostics.open_edges == 0 else 'NO'}",
        f"Exported facets: {diagnostics.facets}",
        f"Non-manifold edges (>2 face users): {diagnostics.non_manifold_edges}",
        f"Open edges (1 face user): {diagnostics.open_edges}",
        f"Inconsistent-winding edges: {diagnostics.inconsistent_winding_edges}",
        f"Degenerate facets: {diagnostics.degenerate_facets}",
        f"Invalid-coordinate facets: {diagnostics.invalid_facets}",
        f"Duplicate facets: {diagnostics.duplicate_facets}",
    ]
    for title, samples in (
        ("Non-manifold edge samples:", diagnostics.non_manifold_edge_samples),
        ("Open edge samples:", diagnostics.open_edge_samples),
        ("Inconsistent-winding edge samples:", diagnostics.inconsistent_winding_samples),
    ):
        if samples:
            lines.extend((title, *_sample_lines(samples)))
    return "\n".join(lines)
