"""Pinned third-party Python dependencies used by the add-on."""

PYTHON_DEPENDENCIES = (
    "cadquery-ocp-novtk==7.9.3.1.1",
    "cadquery-ocp-proxy==7.9.3.1.1",
    "certifi==2026.7.22",
    "fast-simplification==0.1.12",
    "manifold3d==3.2.1",
    "pyclipper==1.3.0.post6",
)

# Distribution names do not always match their Python imports. In particular,
# checking for cadquery_ocp_novtk would trigger pip on every add-on reload even
# when Blender has already installed the bundled OCP wheel.
DEPENDENCY_IMPORT_NAMES = {
    "cadquery-ocp-novtk": "OCP",
}

# Runtime dependencies must be bundled as wheels so Blender can expose them
# when an extension is installed or updated without requiring network access.
# The tiny OCP proxy is a required dependency of the native no-VTK wheel, not a
# second CAD kernel. Keep both pinned because packaging downloads with --no-deps.
BUNDLED_WHEEL_DEPENDENCIES = PYTHON_DEPENDENCIES
