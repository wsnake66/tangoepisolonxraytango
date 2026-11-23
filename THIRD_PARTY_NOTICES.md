# Third-party notices

Moldboxer distributions include or use third-party components. Those
components are licensed by their respective copyright holders, not under the
Moldboxer Worker Commercial License Agreement.

| Component | Version/source | License and included notice |
| --- | --- | --- |
| Blender | Compatible versions stated in `blender_manifest.toml` | GNU GPL; supplied independently by Blender and not owned by MOLDBOXER, S.L. |
| Blender Studio Human Base Meshes | Bundle `v1.4.1`; `Head - Sculpting, Realistic` / `GEO-head_sculpting_realistic`, normalized and trimmed to a capped neck base in `source/custom_face_template.py` | CC0 1.0 Universal; source: <https://download.blender.org/demo/asset-bundles/human-base-meshes/> |
| Python | Runtime selected by the installed product | Python Software Foundation License; the runtime distribution contains its license |
| OCP (`cadquery-ocp-novtk`, `cadquery-ocp-proxy`) | `7.9.3.1.1`; <https://github.com/CadQuery/ocp-build-system> and <https://github.com/CadQuery/OCP> | Apache License 2.0; included in `LICENSES/OCP-Apache-2.0.txt` |
| Open CASCADE Technology (inside OCP wheels) | `7.9.3`; source: <https://github.com/Open-Cascade-SAS/OCCT/tree/V7_9_3> | LGPL 2.1 with the Open CASCADE exception; included in `LICENSES/OCCT-LGPL-2.1.txt` and `LICENSES/OCCT-LGPL-EXCEPTION.txt`. Preserve platform wheel dependency notices when distributing. |
| certifi | `2026.7.22` | Mozilla Public License 2.0; Mozilla-derived CA bundle and license metadata are contained in the bundled wheel |
| NumPy | Runtime dependency | BSD 3-Clause; its distribution contains license and copyright notices |
| OpenVDB | Version supplied by the supported Blender/Python runtime; not bundled in the current worker wheel | Mozilla Public License 2.0; the runtime distribution supplies the applicable OpenVDB and dependency notices. Any future separately bundled OpenVDB build must be inventoried here with its exact version and complete notices before release. |
| fast-simplification | `0.1.12` | MIT; license is contained in the bundled wheel metadata |
| Manifold (`manifold3d`) | `3.2.1` | Apache License 2.0; license and copyright notices are contained in the bundled wheel metadata |
| pyclipper | `1.3.0.post6` | MIT; license is contained in the bundled wheel metadata |
| PyArmor runtime | Release-build version | PyArmor commercial/runtime terms; distributed only under MOLDBOXER, S.L.'s applicable PyArmor entitlement |
| Inter, Montserrat, Bebas Neue and Noto Sans Arabic fonts | Files under `assets/fonts/` | SIL Open Font License 1.1; full notices are adjacent to each font |
| Roboto Slab font | File under `assets/fonts/roboto_slab/` | Apache License 2.0; full notice is adjacent to the font |

The authoritative notice for a bundled Python wheel is its `.dist-info`
license metadata inside that wheel. A release must preserve that metadata.
This inventory must be updated before adding, removing or changing a bundled
dependency.
