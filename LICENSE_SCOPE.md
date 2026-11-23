# Moldboxer license scope

Copyright (C) 2026 MOLDBOXER, S.L.

This repository and its release archives contain separately licensed
components. A license applying to one component does not change the license of
another component.

## Blender add-on — GPL-3.0-or-later

The Blender-dependent add-on, updater, Blender UI, operators, adapters and
worker-launching client are licensed under GNU GPL version 3 or any later
version. This includes:

- the root add-on Python modules;
- `source/`, except for the files expressly classified below;
- `source/components/geometry_adapter.py`;
- `source/nearest_surface_worker_client.py`;
- `moldboxer_updater_extension/`;
- `setup_cython.py` and `cython_build_config.py`;
- other add-on build, installation and test tooling, except worker-only build
  files.

The complete terms are in `LICENSES/GPL-3.0-or-later.txt`.

## External worker — Moldboxer Worker Commercial License 1.0

The following Blender-independent worker implementation is proprietary and is
licensed by MOLDBOXER, S.L. under the Moldboxer Worker Commercial License
Agreement version 1.0:

- `source/nearest_surface_worker.py`;
- `source/nearest_surface.py`;
- `source/voxel_remesh.py`;
- `source/geometry_core.py`;
- `source/custom_face_geometry.py`;
- `source/geometry_policy.py`;
- `source/hollowing_geometry.py`;
- `source/mesh_simplification.py`;
- `source/mesh_processing.py`;
- `source/manifold_boolean.py`;
- `source/pin_placement.py`;
- `source/rounded_funnel_placement.py`;
- `source/orientation_math.py`;
- `source/organic_plane_math.py`;
- `source/slicer_cleanup_geometry.py`;
- `source/service_transport.py`;
- `source/spatial_partition.py`;
- `source/undercut_core.py`;
- `source/undercut_geometry.py`;
- `source/watermark_geometry.py`;
- `source/nearest_surface_native.pyx`;
- `source/native/clearance_core.cpp`;
- `source/native/clearance_core.hpp`;
- `source/native/section_split_core.cpp`;
- `source/native/section_split_core.hpp`;
- `source/native/air_trap_core.cpp`;
- `source/native/air_trap_core.hpp`;
- `source/native/nearest_surface_core.cpp`;
- `source/native/nearest_surface_core.hpp`;
- `setup_nearest_surface_native.py`.

The worker is designed to execute in a separate operating-system process. It
does not import Blender APIs and communicates with the GPL client only through
the documented framed array protocol. Packaging the programs in the same
installer or archive is intended solely as aggregation for distribution
convenience and does not itself grant GPL rights in the proprietary worker.
This classification depends on maintaining that technical boundary.

The complete terms are in
`LICENSES/MOLDBOXER-WORKER-COMMERCIAL-1.0.txt`.

For a concise external-facing explanation of the Blender/add-on/Worker/service
relationship, see `BLENDER_WORKER_BOUNDARY.md`.

## Shared boundary modules — MIT

These small, Blender-independent interface modules are available under the MIT
License so both the GPL client and proprietary worker may use the same data
contract without changing either program's license:

- `source/nearest_surface_arrays.py`;
- `source/nearest_surface_protocol.py`;
- `source/tls_context.py`.

The complete terms are in `LICENSES/MIT.txt`.

## Generated files and third-party materials

The worker-only head template in `source/custom_face_template.py` retains its
CC0 1.0 asset provenance. `scripts/bake_custom_face_template.py` is offline
Blender tooling for preparing that data and is never imported by the worker.

Generated source files and binaries retain the license of the corresponding
source component and should not be treated as independently licensed merely
because they lack a handwritten SPDX header.
Bundled dependencies, fonts, runtimes and other third-party materials remain
under their respective licenses. See `THIRD_PARTY_NOTICES.md` and the license
metadata shipped with each dependency.

No statement in this file changes rights that cannot be excluded under
applicable law. This scope document describes MOLDBOXER, S.L.'s licensing
intent; it should be reviewed whenever code crosses one of the boundaries
above.
