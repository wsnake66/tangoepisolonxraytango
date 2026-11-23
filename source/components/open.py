import logging
import bpy  # type: ignore

from .server import import_server_response, request_server, request_server_async
from ..object import Object
from ..environment import get_server_base_url

logger = logging.getLogger(__name__)


def _finish_tray_silhouette_response(response) -> Object:
    original_box = Object(bpy.data.objects.get("box"))
    original_box.remove()
    logger.debug("Received tray silhouette response from server")
    import_server_response(response)
    return Object(bpy.data.objects.get("box"))


def tray_silhouette_req(smoothing_radius: float = 0.25) -> Object:
    response = request_server(
        f"{get_server_base_url()}/tray-silhouette/",
        ["box"],
        params={"smoothing_radius": max(float(smoothing_radius), 0.0)},
    )
    return _finish_tray_silhouette_response(response)


def begin_tray_silhouette_req(
    smoothing_radius: float = 0.25,
    *,
    on_complete=None,
):
    def complete(response):
        box = _finish_tray_silhouette_response(response)
        if on_complete is not None:
            return on_complete(box)
        return box

    return request_server_async(
        f"{get_server_base_url()}/tray-silhouette/",
        ["box"],
        params={"smoothing_radius": max(float(smoothing_radius), 0.0)},
        on_complete=complete,
    )


def flat_mold_req(box_voxel_size: float = 0.8, box_thickness: float = 3.5):
    response = request_server(
        f"{get_server_base_url()}/auto-flat/",
        ["box"],
        params={
            "box_voxel_size": box_voxel_size,
            "box_thickness": box_thickness,
        },
    )
    original_box = Object(bpy.data.objects.get("box"))
    original_box.remove()
    logger.debug(f"Received response from server")
    import_server_response(response)
