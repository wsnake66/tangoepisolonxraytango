# MoldForge

Offline, open-source silicone mold box generator for Blender 4.2+. No account,
no login, no network access — ever.

## Features (v0.1)

- One-click mold box around any mesh object (configurable gap and wall thickness)
- Two-part split mold with a height-adjustable split plane
- Circular registration keys with matching sockets and adjustable tolerance
- Pour funnel reaching into the cavity
- Air vents
- One-piece mold mode

## Install

1. Zip the `moldforge/` folder contents (select the files inside the folder,
   not the folder itself) or copy the folder to your Blender extensions
   directory (`.../Blender/4.2/extensions/user_default/moldforge/`).
2. Enable **MoldForge** in Edit > Preferences > Add-ons.
3. Open the N-panel in the 3D viewport → **MoldForge** tab.

## Usage

1. Select a mesh object.
2. Set gap, wall thickness, split position, and key/funnel parameters.
3. Press **Generate Mold**. The two halves are created as
   `MoldForge_TopHalf` / `MoldForge_BottomHalf`.

The original object is never modified.

## Roadmap

- Multi-object cavities in a single mold
- Casting box generation around the finished mold
- Hollow shell generation via solidify
- Simple heuristic undercut analysis (raycast based)
- Batch export to STL/3MF

## License

GPL-3.0-or-later. Original code — no Moldboxer source or binaries included.
