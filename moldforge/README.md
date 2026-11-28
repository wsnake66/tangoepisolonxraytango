# MoldForge

Offline, open-source silicone mold system generator for Blender 4.2+. No
account, no login, no network access — ever.

## Features (v0.2)

- Mold presets: silicone two-part, silicone one-piece, protective shell,
  fixture frame, plaster mold, slip casting box
- Quality setting (LOW / MID / HIGH) controlling round-feature resolution
- One-click mold generation with configurable gap and wall thickness
- Multi-part stacked molds (up to 5 parts via extra splits)
- Registration keys per interface with tolerance, automatic or manual ring
- Master base pin (center cone alignment) with socket
- Up to 3 pour funnels reaching into the cavity
- Air vents and horizontal channel grooves (plaster/slip casting)
- Casting feet, grip notches, clamp bolt holes through all parts
- Rigid casting box generation with bolt holes
- Hollow shell creation (solidify based)
- Split-height analysis: raycast cross-section scan finds the widest
  section and sets the split height automatically
- Batch export to STL / OBJ / glTF
- Full Blender UNDO support; original object is never modified

## Install

1. Zip the `moldforge/` folder contents (select the files inside the folder,
   not the folder itself) or copy the folder to your Blender extensions
   directory (`.../Blender/4.2/extensions/user_default/moldforge/`).
2. Enable **MoldForge** in Edit > Preferences > Add-ons.
3. Open the N-panel in the 3D viewport → **MoldForge** tab.

## Usage

1. Select a mesh object.
2. Pick a preset, adjust parameters (or press **Analyze Split Height** to
   auto-place the split).
3. Press **Generate Mold**. Parts are created as `MoldForge_Part_XX`.
4. Optionally add a **Casting Box**, **Hollow Shell**, or **Export**.

## License

GPL-3.0-or-later. Original code — no Moldboxer source or binaries included.
