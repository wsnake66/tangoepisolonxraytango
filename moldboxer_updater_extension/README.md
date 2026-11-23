# Moldboxer Updater

Copyright (C) 2026 MOLDBOXER, S.L.

This updater is licensed under GNU GPL version 3 or any later version. The
release archive includes the complete license as `LICENSE`.

This is a separate Blender extension whose only responsibility is updating the
`moldboxer_silicone` extension from the remote repository where Moldboxer is
currently installed.

Keeping the update operator in this package is intentional. Blender disables
and unregisters Moldboxer while replacing its files, but the updater stays
registered and Blender's native extension installation can complete normally.

## Build

Build the exact plain-Python release archive used by the server:

```bash
python3 scripts/package_updater.py
```

Or build and validate it with Blender 4.5 or newer:

```bash
blender --command extension build \
  --source-dir moldboxer_updater_extension \
  --output-dir dist/updater
```

Moldboxer installs download this plain ZIP from their repository's
`/updater/download` endpoint and install it automatically when the updater is
missing.
The updater then checks on startup and every 20 minutes. When Moldboxer is
missing or a newer release is available, it starts Blender's native installer
without requiring a button click and displays a staged progress overlay in
every 3D viewport. On Windows, an enabled Moldboxer install is disabled and
saved first; the user restarts Blender, then installation continues before any
protected `.pyd` file is loaded. This avoids Windows file-lock failures while
replacing PyArmor and other native modules.

For manual testing, install the resulting ZIP once with **Preferences >
Extensions > Install from Disk** and leave the updater enabled.

After a Moldboxer update finishes, restart Blender before using Moldboxer. This
ensures that native and protected Python modules are loaded from the new build.
