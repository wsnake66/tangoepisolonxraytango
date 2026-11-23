class Modifier:
    def __init__(self, name: str, properties: dict) -> None:
        self.name = name
        self.properties = properties

    def __repr__(self) -> str:
        return f"Modifier(name={self.name}, properties={self.properties})"


diff_mod = Modifier("BOOLEAN", {"operation": "DIFFERENCE", "solver": "MANIFOLD"})
diff_material_transfer_mod = Modifier(
    "BOOLEAN",
    {
        "operation": "DIFFERENCE",
        "solver": "MANIFOLD",
        "material_mode": "TRANSFER",
    },
)
diff_no_material_transfer_mod = Modifier(
    "BOOLEAN",
    {"operation": "DIFFERENCE", "solver": "MANIFOLD", "material_mode": "INDEX"},
)
intersect_mod = Modifier("BOOLEAN", {"operation": "INTERSECT", "solver": "MANIFOLD"})
union_mod = Modifier(
    "BOOLEAN",
    {"operation": "UNION", "solver": "MANIFOLD"},
)
union_no_material_transfer_mod = Modifier(
    "BOOLEAN",
    {"operation": "UNION", "solver": "MANIFOLD", "material_mode": "INDEX"},
)
union_material_transfer_mod = Modifier(
    "BOOLEAN",
    {"operation": "UNION", "solver": "MANIFOLD", "material_mode": "TRANSFER"},
)


def build_array_modifier(n_copies: int, distance: list[float]):
    if len(distance) != 3:
        raise ValueError("Distance must be a list of 3 floats")
    return Modifier(
        "ARRAY",
        {
            "count": n_copies,
            "use_constant_offset": True,
            "use_relative_offset": False,
            "constant_offset_displace": distance,
            "use_merge_vertices": True,
        },
    )


def build_z_projection_modifier(
    vertex_group: str,
    *,
    offset: float = 1,
    wrap_mode: str = "INSIDE",
    use_positive_direction: bool = True,
    use_negative_direction: bool = False,
) -> Modifier:
    return Modifier(
        "SHRINKWRAP",
        {
            "offset": offset,
            "wrap_mode": wrap_mode,
            "wrap_method": "PROJECT",
            "vertex_group": vertex_group,
            "use_project_x": False,
            "use_project_y": False,
            "use_project_z": True,
            "use_positive_direction": use_positive_direction,
            "use_negative_direction": use_negative_direction,
        },
    )


def build_voxel_modifier(
    voxel_size: float = 0.2, smooth_shading: bool = False, adaptivity: float = 0
) -> Modifier:
    return Modifier(
        "REMESH",
        {
            "mode": "VOXEL",
            "voxel_size": voxel_size,
            "adaptivity": adaptivity,
            "use_smooth_shade": smooth_shading,
        },
    )


def build_sharp_modifier(octree_depth: int = 8) -> Modifier:
    return Modifier(
        "REMESH",
        {
            "mode": "SHARP",
            "octree_depth": octree_depth,
            "use_remove_disconnected": False,
        },
    )
