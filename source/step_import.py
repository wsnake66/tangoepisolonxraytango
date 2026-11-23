"""Convert STEP CAD surfaces to a triangle mesh in millimeters, without Blender.

Assemblies are flattened with their placements. CAD history, colors and part
names are not retained. Open shells remain open for the normal repair workflow.
"""

from dataclasses import dataclass
from itertools import product
import math
from pathlib import Path


class StepImportError(ValueError):
    """The STEP file could not be converted into usable mesh geometry."""


@dataclass(frozen=True)
class StepGeometry:
    name: str
    vertices: tuple[tuple[float, float, float], ...]
    triangles: tuple[tuple[int, int, int], ...]


def load_step_geometry(path, *, linear_deflection=0.05, angular_deflection=0.2):
    """Tessellate with absolute deflection in mm and angular deflection in radians."""
    path = Path(path)
    if not path.is_file():
        raise StepImportError(f"STEP file does not exist: {path.name}")
    if not (math.isfinite(linear_deflection) and linear_deflection > 0):
        raise StepImportError("STEP mesh tolerance must be positive and finite")
    if not (math.isfinite(angular_deflection) and 0 < angular_deflection < math.pi):
        raise StepImportError("STEP angular tolerance must be between 0 and pi")
    try:
        from OCP.BRep import BRep_Tool
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.STEPControl import STEPControl_Reader
        from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopLoc import TopLoc_Location
        from OCP.TopoDS import TopoDS
    except (ImportError, OSError) as exc:
        raise StepImportError(
            "The STEP conversion library is unavailable. Reinstall Moldboxer "
            "with its bundled CAD dependencies."
        ) from exc

    try:
        reader = STEPControl_Reader()
        if reader.ReadFile(str(path)) != IFSelect_RetDone:
            raise StepImportError("Could not read STEP file; it may be invalid or damaged")
        # Set after ReadFile, once the STEP model exists. OCCT converts declared
        # file units to this target unit (1 mm), matching Moldboxer's mesh units.
        reader.SetSystemLengthUnit(1.0)
        roots = reader.NbRootsForTransfer()
        if not roots:
            raise StepImportError("STEP file contains no transferable geometry")
        for root in range(1, roots + 1):
            if not reader.TransferRoot(root):
                raise StepImportError(f"Could not convert STEP part {root}")
        shape = reader.OneShape()
        if shape.IsNull():
            raise StepImportError("STEP file contains no geometry")
        mesher = BRepMesh_IncrementalMesh(
            shape, linear_deflection, False, angular_deflection, True
        )
        if not mesher.IsDone():
            raise StepImportError("Could not tessellate STEP surfaces")

        vertices, triangles = [], []
        cells = {}
        # CAD faces have separate triangulations. Weld their coincident seam
        # vertices so closed CAD solids also produce connected, closed meshes.
        weld_tolerance = min(1e-7, linear_deflection * 1e-4)

        def vertex_index(point):
            xyz = (point.X(), point.Y(), point.Z())
            if not all(math.isfinite(value) for value in xyz):
                raise StepImportError("STEP file contains non-finite coordinates")
            cell = tuple(math.floor(value / weld_tolerance) for value in xyz)
            for offset in product((-1, 0, 1), repeat=3):
                neighbor = tuple(cell[i] + offset[i] for i in range(3))
                for index in cells.get(neighbor, ()):
                    if math.dist(vertices[index], xyz) <= weld_tolerance:
                        return index
            index = len(vertices)
            vertices.append(xyz)
            cells.setdefault(cell, []).append(index)
            return index

        faces = TopExp_Explorer(shape, TopAbs_FACE)
        while faces.More():
            face = TopoDS.Face_s(faces.Current())
            location = TopLoc_Location()
            mesh = BRep_Tool.Triangulation_s(face, location)
            if mesh is None or mesh.NbTriangles() == 0:
                raise StepImportError("A STEP surface could not be meshed")
            transform = location.Transformation()
            indices = [vertex_index(mesh.Node(i).Transformed(transform))
                       for i in range(1, mesh.NbNodes() + 1)]
            reverse = (face.Orientation() == TopAbs_REVERSED) != transform.IsNegative()
            for i in range(1, mesh.NbTriangles() + 1):
                a, b, c = (indices[n - 1] for n in mesh.Triangle(i).Get())
                if a != b and b != c and c != a:
                    triangles.append((a, c, b) if reverse else (a, b, c))
            faces.Next()
        if not triangles:
            raise StepImportError("STEP file contains no meshable surfaces")
        return StepGeometry(path.stem, tuple(vertices), tuple(triangles))
    except StepImportError:
        raise
    except Exception as exc:
        raise StepImportError(f"Could not convert STEP geometry: {exc}") from exc
