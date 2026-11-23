# Moldboxer 2.3.2 Blender-side source

This archive is the preferred source form for the Blender-dependent Moldboxer
code distributed with the Moldboxer 2.3.2 standalone installers. It was
built from private source revision `71ceabafc955ca24629edb2406696d5aaf57a5d7`.

## Included

- GPL-3.0-or-later Blender add-on, UI, operators, adapters, updater, and the
  client that launches and exchanges data with the external Worker;
- MIT-licensed array and protocol boundary modules;
- UI assets, third-party notices, manifests, and source preparation/install
  helpers needed to inspect, modify, and run the Blender-side component.

## Intentionally not included

- the separately licensed, Blender-independent external Worker implementation
  or its native sources and build configuration;
- any Moldboxer backend/server repository, deployment configuration, private
  infrastructure, credentials, or server test fixtures;
- protected binaries, PyArmor runtime/registration material, build outputs,
  repository history, or internal release diagnostics.

Some Blender-side client adapter filenames contain `server` or `worker_client`.
Those files run inside Blender, use Blender APIs, and are therefore included as
GPL source. They are not the external Worker or Moldboxer backend implementation.

## Use in Blender

The add-on source is normal Python source. For development, place this archive's
directory in a Blender extension/add-on development location, install the Python
dependencies pinned in `dependencies.py` for Blender's Python, and load the
`moldboxer_silicone` module. The production installers applied
`scripts/prepare_production_sources.py` before protection; that helper is
included so the production transformation can be inspected and reproduced.

Worker-backed product operations still require a separately installed and
licensed Moldboxer Worker. The absence of that separate program does not prevent
inspection or modification of this Blender-side source.

See `LICENSE`, `LICENSES/MIT.txt`, `LICENSE_SCOPE.md`, and
`BLENDER_WORKER_BOUNDARY.md` for the applicable terms and component boundary.
