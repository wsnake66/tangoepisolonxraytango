"""One content-addressed clearance proxy, without retained Blender data-blocks."""

from array import array
import hashlib


_entry = None


def clearance_proxy_key(mesh, matrix_world, quality, voxel_size):
    digest = hashlib.blake2b(digest_size=32)
    # Preserve polygon boundaries: remeshing consumes the original polygons.
    for collection, attribute, typecode, width in (
        (mesh.vertices, "co", "f", 3),
        (mesh.loops, "vertex_index", "i", 1),
        (mesh.polygons, "loop_total", "i", 1),
    ):
        values = array(typecode, [0]) * (len(collection) * width)
        collection.foreach_get(attribute, values)
        digest.update(len(values).to_bytes(8, "little"))
        digest.update(values)
    return (
        digest.digest(),
        tuple(value for row in matrix_world for value in row),
        str(quality), float(voxel_size),
    )


def get_clearance_proxy(key):
    if _entry is None or _entry[0] != key:
        return None
    # Callers own their arrays and may freely modify the restored proxy.
    return _entry[1].copy(), _entry[2].copy()


def store_clearance_proxy(key, vertices, triangles):
    global _entry
    _entry = (key, vertices.copy(), triangles.copy())
