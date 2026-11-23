import os
import sys
import importlib
import addon_utils  # type: ignore
import logging
import traceback
import time
from datetime import datetime
from pathlib import Path
import shutil
import bpy  # type: ignore

logger = logging.getLogger(__name__)
SUPPORTED_BATCH_TEST_MODEL_SUFFIXES = {".3mf", ".obj", ".ply", ".stl"}
NATIVE_PACKAGE_NAME = "moldboxer_silicone_native"
_NATIVE_EXTENSION_SUFFIXES = (".so", ".pyd", ".dll", ".dylib")
_RELOAD_PENDING_KEY = "_moldboxer_repo_reload_pending"


def _addon_module_name():
    pkg = __package__ or __name__
    if pkg.endswith("_native.source"):
        return pkg[: -len("_native.source")]
    if "._native." in pkg:
        return pkg.split("._native.", 1)[0]
    if pkg.endswith(".source"):
        return pkg[: -len(".source")]
    if pkg.endswith("_native"):
        return pkg[: -len("_native")]
    if ".source." in pkg:
        return pkg.split(".source.", 1)[0]
    return pkg


def _loaded_addon_module_name(module_name: str) -> str | None:
    addons = bpy.context.preferences.addons
    if addons.get(module_name):
        return module_name

    addon_folder_name = Path(__file__).resolve().parents[1].name
    candidates = [module_name]
    if addon_folder_name and addon_folder_name not in candidates:
        candidates.append(addon_folder_name)

    for addon_key in addons.keys():
        if any(
            addon_key == candidate or addon_key.endswith(f".{candidate}")
            for candidate in candidates
        ):
            return addon_key

    return None


def _module_must_survive_reload(module_name: str, module) -> bool:
    """Keep process-global native runtimes alive across an add-on reload.

    CPython does not safely unload extension modules.  Removing one from
    ``sys.modules`` merely allows a second module instance to be initialized
    against the same process.  In Moldboxer that loaded PyArmor's runtime twice
    and eventually left Blender traversing stale Python objects during GC.
    """

    if any(part.startswith("pyarmor_runtime_") for part in module_name.split(".")):
        return True
    module_file = str(getattr(module, "__file__", "") or "").casefold()
    return module_file.endswith(_NATIVE_EXTENSION_SUFFIXES)


def _purge_package_from_sys(package_name: str):
    prefix = package_name + "."
    to_delete = [
        module_name
        for module_name, module in list(sys.modules.items())
        if (module_name == package_name or module_name.startswith(prefix))
        and not _module_must_survive_reload(module_name, module)
    ]
    for module_name in to_delete:
        sys.modules.pop(module_name, None)


def _activate_repo_source_imports() -> None:
    """Force add-on imports to use the repository source for this session."""
    _purge_package_from_sys(NATIVE_PACKAGE_NAME)
    # The add-on entry points intentionally try the protected native package
    # first and fall back to their local source on ImportError. Keeping this
    # sentinel in sys.modules makes that first import fail without modifying or
    # uninstalling the packaged wheel.
    sys.modules[NATIVE_PACKAGE_NAME] = None


def _resolve_repo_path(repo_path: str) -> Path:
    expanded = bpy.path.abspath(repo_path or "").strip()
    if not expanded:
        raise ValueError("Dev repo path is empty")
    path = Path(expanded).expanduser().resolve()
    if not path.is_dir():
        raise ValueError(f"Dev repo path does not exist: {path}")
    if not (path / "__init__.py").exists():
        raise ValueError(f"Not an add-on repo (missing __init__.py): {path}")
    return path


def _addon_root_dir(module_name: str | None = None) -> Path:
    """Resolve the installed extension root, even from the native wheel."""

    loaded_name = module_name or _loaded_addon_module_name(
        _addon_module_name()
    )
    loaded_module = sys.modules.get(loaded_name)
    loaded_file = getattr(loaded_module, "__file__", None)
    if loaded_file:
        return Path(loaded_file).resolve().parent

    # Source-only development loads this module from <addon>/source. Retain
    # that fallback, but never prefer it over the actual loaded extension: in
    # production this module may live in moldboxer_silicone_native instead.
    return Path(__file__).resolve().parent.parent


def _sync_repo_to_addon(repo_root: Path, addon_root: Path):
    if repo_root.samefile(addon_root):
        return

    # Keep package entrypoint last: a partial sync must never install an
    # __init__.py that imports runtime modules which have not been copied yet.
    runtime_root_files = (
        "dependencies.py",
        "hollower.py",
        "logo_extrusion.py",
        "operators.py",
        "panels.py",
        "properties.py",
        "__init__.py",
    )
    runtime_root_dirs = {"assets", "source"}
    runtime_asset_files = {"logo.png", "logo_ico_v2.ico"}
    runtime_asset_dirs = {"fonts", "mold_types", "settings", "tools"}
    obsolete_runtime_files = (
        Path("source/components") / "auto_box.py",
        Path("source/components") / "blender_clearance_construction.py",
        Path("source/components") / "box_postprocess.py",
        Path("source/components") / "clear_extraction_optimized.py",
        Path("source/components") / "funnel_split_planes.py",
        Path("source/components") / "wrapper.py",
        Path("source/components") / "nearest_surface_wrapper.py",
        Path("source/components") / "clear_undercuts_core.py",
        Path("source/components") / "hollower_core.py",
        Path("source") / "dev_geometry_comparisons.py",
        Path("source") / "redistribution.py",
        Path("source") / "wrapper_pipeline.py",
    )
    ignored_dirs = {
        ".git",
        ".github",
        ".codex",
        ".cython_build",
        ".eggs",
        ".pyarmor",
        ".pyarmor_build",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".venv",
        "build",
        "develop-eggs",
        "dist",
        "downloads",
        "eggs",
        "target",
        "wheels",
    }
    ignored_files = {".DS_Store"}
    ignored_dir_suffixes = {".egg-info"}
    ignored_file_suffixes = {
        ".a",
        ".c",
        ".cpp",
        ".dll",
        ".dmg",
        ".egg",
        ".dylib",
        ".o",
        ".pyc",
        ".pyd",
        ".pyo",
        ".pyx",
        ".so",
        ".whl",
        ".zip",
    }

    def is_ignored_dir(name: str) -> bool:
        return name in ignored_dirs or any(
            name.endswith(suffix) for suffix in ignored_dir_suffixes
        )

    def is_ignored_file(name: str) -> bool:
        suffix = Path(name).suffix.casefold()
        if (
            name.startswith("nearest_surface_native.")
            and suffix in {".so", ".pyd"}
        ):
            return False
        return (
            name in ignored_files
            or suffix in ignored_file_suffixes
        )

    def copy_if_changed(source: Path, destination: Path) -> None:
        source_stat = source.stat()
        try:
            destination_stat = destination.stat()
        except FileNotFoundError:
            destination_stat = None
        if (
            destination_stat is not None
            and source_stat.st_size == destination_stat.st_size
            # APFS may round copy2 timestamps by a few hundred nanoseconds.
            and abs(source_stat.st_mtime_ns - destination_stat.st_mtime_ns) <= 1_000
        ):
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    def copy_runtime_tree(relative_tree: Path) -> None:
        source_tree = repo_root / relative_tree
        if not source_tree.is_dir():
            return
        for current_root, dirnames, filenames in os.walk(source_tree):
            # Generated trees are pruned before os.walk can inspect their
            # contents, even when they appear inside an allowed runtime tree.
            dirnames[:] = [name for name in dirnames if not is_ignored_dir(name)]
            current_path = Path(current_root)
            relative_root = current_path.relative_to(repo_root)
            for filename in filenames:
                if is_ignored_file(filename):
                    continue
                copy_if_changed(
                    current_path / filename,
                    addon_root / relative_root / filename,
                )

    # Start only from explicit runtime roots. In particular, never walk the
    # repository root: build, dist, tests, packaging, virtual environments, and
    # future development-only directories must not affect reload time.
    if (repo_root / "__init__.py").is_file() and not (
        repo_root / "logo_extrusion.py"
    ).is_file():
        raise FileNotFoundError(
            "Missing required logo operator module: "
            f"{repo_root / 'logo_extrusion.py'}"
        )
    for filename in runtime_root_files:
        source = repo_root / filename
        if source.is_file() and not is_ignored_file(filename):
            copy_if_changed(source, addon_root / filename)

    for dirname in runtime_root_dirs - {"assets"}:
        copy_runtime_tree(Path(dirname))

    for filename in runtime_asset_files:
        source = repo_root / "assets" / filename
        if source.is_file() and not is_ignored_file(filename):
            copy_if_changed(source, addon_root / "assets" / filename)

    for dirname in runtime_asset_dirs:
        copy_runtime_tree(Path("assets") / dirname)

    # Renamed runtime modules are not discovered by the copy-only sync. Remove
    # these exact legacy paths so Reload from Repo cannot retain old sources.
    for relative_path in obsolete_runtime_files:
        stale_path = addon_root / relative_path
        if stale_path.is_file() or stale_path.is_symlink():
            stale_path.unlink()
        # Also remove importable cached/compiled versions of retired modules.
        for pattern in (stale_path.stem + ".*.pyc", stale_path.stem + ".pyc",
                        stale_path.stem + ".*.so", stale_path.stem + ".so",
                        stale_path.stem + ".*.pyd", stale_path.stem + ".pyd"):
            for directory in (stale_path.parent, stale_path.parent / "__pycache__"):
                for artifact in directory.glob(pattern):
                    artifact.unlink()

    # Opaque migration IDs keep obsolete implementation names out of runtime
    # code while still removing exact legacy modules and their import caches.
    import hashlib
    retired_module_ids = {
        "source": {
            "0d829cfcd24ba4f171c17a7aafabff7fb350c6ec6e062ac9d32fe517b725f7f8",
            "026fcd52baf8bde58e85832cf5f920a6b74e93fbe98f7615c7018d2924e3afc8",
            "a854bc4ffc1a78ae3ebb919b869e657ec30fa1ac3ef075b260e1fe0c6d458de5",
        },
        "source/components": {
            "149728d06a943c0426896943cc274fd0751a88992529122db352ea3ede362f59",
        },
    }
    for relative_directory, identifiers in retired_module_ids.items():
        parent = addon_root / relative_directory
        for directory in (parent, parent / "__pycache__"):
            for artifact in directory.glob("*"):
                if artifact.suffix not in {".py", ".pyc", ".pyo", ".so", ".pyd"}:
                    continue
                module_id = hashlib.sha256(artifact.name.split(".")[0].encode()).hexdigest()
                if module_id in identifiers and (artifact.is_file() or artifact.is_symlink()):
                    artifact.unlink()

    missing_runtime_files = [
        filename
        for filename in runtime_root_files
        if (repo_root / filename).is_file()
        and not (addon_root / filename).is_file()
    ]
    if missing_runtime_files:
        raise FileNotFoundError(
            "Repository reload did not install required runtime modules: "
            + ", ".join(missing_runtime_files)
        )


def _perform_reload(mod: str, *, activate_repo_source: bool = False):
    dev_mode = None
    dev_repo_path = None
    loaded_mod = _loaded_addon_module_name(mod) or mod

    addon = bpy.context.preferences.addons.get(loaded_mod)
    if addon and hasattr(addon, "preferences"):
        prefs = addon.preferences
        dev_mode = getattr(prefs, "dev_mode", None)
        dev_repo_path = getattr(prefs, "dev_repo_path", None)

    try:
        addon_utils.disable(loaded_mod, default_set=False, handle_error=None)
        _purge_package_from_sys(loaded_mod)
        if loaded_mod != mod:
            _purge_package_from_sys(mod)
        if activate_repo_source:
            _activate_repo_source_imports()
        addon_utils.enable(loaded_mod, default_set=False, persistent=True, handle_error=None)

        addon = bpy.context.preferences.addons.get(loaded_mod)
        if addon and hasattr(addon, "preferences"):
            prefs = addon.preferences
            if prefs is not None and dev_mode is not None:
                prefs.dev_mode = dev_mode
            if prefs is not None and dev_repo_path is not None:
                prefs.dev_repo_path = dev_repo_path

        print(f"[Moldboxer Silicone] Reloaded add-on: {loaded_mod}")
    except Exception:
        traceback.print_exc()


def _schedule_reload(
    mod: str,
    repo_path: str | None = None,
    *,
    activate_repo_source: bool = False,
):
    reload_state = bpy.app.driver_namespace
    if reload_state.get(_RELOAD_PENDING_KEY):
        logger.info("Moldboxer add-on reload is already scheduled")
        return False
    reload_state[_RELOAD_PENDING_KEY] = True

    def _reload_callback():
        try:
            if repo_path:
                repo_root = _resolve_repo_path(repo_path)
                addon_root = _addon_root_dir(mod)
                _sync_repo_to_addon(repo_root, addon_root)
                importlib.invalidate_caches()
            _perform_reload(
                mod,
                activate_repo_source=activate_repo_source,
            )
        except Exception:
            traceback.print_exc()
        finally:
            reload_state.pop(_RELOAD_PENDING_KEY, None)
        return None

    try:
        bpy.app.timers.register(_reload_callback, first_interval=0.05)
    except Exception:
        reload_state.pop(_RELOAD_PENDING_KEY, None)
        raise
    return True


def reload_addon_from_repo(repo_path: str):
    try:
        _resolve_repo_path(repo_path)
    except Exception:
        traceback.print_exc()
        return {"CANCELLED"}

    mod = _loaded_addon_module_name(_addon_module_name()) or _addon_module_name()
    _schedule_reload(
        mod,
        repo_path=repo_path,
        activate_repo_source=True,
    )
    return {"FINISHED"}


class BatchTestsError(RuntimeError):
    pass


def _resolve_batch_tests_path(batch_tests_path: str) -> Path:
    path = Path(bpy.path.abspath(batch_tests_path or "")).expanduser()
    if not path.is_dir():
        raise BatchTestsError("Batch tests path must be an existing folder")
    return path


def _batch_test_model_paths(root_path: Path) -> list[Path]:
    return sorted(
        path
        for path in root_path.iterdir()
        if path.is_file()
        and path.suffix.casefold() in SUPPORTED_BATCH_TEST_MODEL_SUFFIXES
    )


def _clear_scene_for_batch_test(context) -> None:
    from .object import remove_objects_safely

    context.scene.volume = 0
    context.scene.casting_volume_ml = 0
    remove_objects_safely(tuple(bpy.data.objects))


def _restore_batch_test_mold_type(context, mold_type) -> None:
    """Restore the batch's starting mode before orienting the next import."""
    scene = context.scene
    if scene.mold_type_preview != mold_type.identifier:
        logger.info(
            "Restoring batch test mold mode: %s -> %s",
            scene.mold_type_preview, mold_type.identifier,
        )
        scene.mold_type_preview = mold_type.identifier
    if scene.mold_type_preview != mold_type.identifier:
        raise BatchTestsError(
            f"Could not restore batch mold mode {mold_type.identifier}"
        )


def _capture_batch_test_split_plane_specs() -> list[list[list[float]]]:
    """Freeze editable split-plane transforms before batch scene cleanup."""
    try:
        from moldboxer_silicone_native.source.components.direct_split_planes import (
            direct_split_plane_specs,
            sync_direct_split_planes_with_scene,
        )
    except ImportError:
        from .components.direct_split_planes import (
            direct_split_plane_specs,
            sync_direct_split_planes_with_scene,
        )

    sync_direct_split_planes_with_scene()
    return direct_split_plane_specs(log_context="Batch tests initial capture")


def _restore_batch_test_split_plane_specs(
    context,
    plane_specs: list[list[list[float]]],
) -> None:
    """Apply the initial batch split-plane transforms to recreated planes."""
    try:
        from moldboxer_silicone_native.source.components.direct_split_planes import (
            iter_direct_split_plane_objects,
            sync_direct_split_planes_with_scene,
        )
    except ImportError:
        from .components.direct_split_planes import (
            iter_direct_split_plane_objects,
            sync_direct_split_planes_with_scene,
        )
    import mathutils  # type: ignore

    sync_direct_split_planes_with_scene()
    planes = list(iter_direct_split_plane_objects())
    if not plane_specs:
        # A previously generated box can hide/remove the editable plane objects
        # even though the scene split counters are still configured. Once the
        # batch cleanup removes that box, sync recreates the requested planes
        # against the newly imported patron. With no transforms captured there
        # is nothing further to restore, and those fresh planes are the correct
        # fallback.
        return
    if len(planes) != len(plane_specs):
        raise BatchTestsError(
            "Could not restore batch split planes: "
            f"captured {len(plane_specs)}, recreated {len(planes)}"
        )

    for plane, plane_spec in zip(planes, plane_specs):
        try:
            point = mathutils.Vector(plane_spec[0])
            normal = mathutils.Vector(plane_spec[1])
        except (IndexError, TypeError, ValueError) as exc:
            raise BatchTestsError("Captured batch split plane is invalid") from exc
        if len(point) != 3 or len(normal) != 3 or normal.length <= 1e-9:
            raise BatchTestsError("Captured batch split plane is invalid")

        plane.location = point
        plane.rotation_euler = normal.normalized().to_track_quat(
            "Z",
            "Y",
        ).to_euler()

    try:
        context.view_layer.update()
    except Exception:
        pass


def _capture_batch_test_fixture_height_plane_spec(mold_type):
    if mold_type.identifier != "FIXTURE":
        return None
    try:
        from moldboxer_silicone_native.source.components.fixture import (
            fixture_height_plane,
        )
    except ImportError:
        from .components.fixture import fixture_height_plane

    point, normal = fixture_height_plane()
    return [
        [float(value) for value in point],
        [float(value) for value in normal],
    ]


def _restore_batch_test_fixture_height_plane_spec(
    context,
    plane_spec,
) -> None:
    if plane_spec is None:
        return
    try:
        from moldboxer_silicone_native.source.components.fixture import (
            fixture_height_guide_object,
            sync_fixture_height_guide,
        )
    except ImportError:
        from .components.fixture import (
            fixture_height_guide_object,
            sync_fixture_height_guide,
        )
    import mathutils  # type: ignore

    try:
        point = mathutils.Vector(plane_spec[0])
        normal = mathutils.Vector(plane_spec[1])
    except (IndexError, TypeError, ValueError) as exc:
        raise BatchTestsError("Captured fixture height plane is invalid") from exc
    if len(point) != 3 or len(normal) != 3 or normal.length <= 1e-9:
        raise BatchTestsError("Captured fixture height plane is invalid")

    sync_fixture_height_guide(context.scene)
    guide = fixture_height_guide_object()
    if guide is None:
        raise BatchTestsError("Could not restore the fixture height plane")
    guide.location = point
    guide.rotation_euler = normal.normalized().to_track_quat(
        "Z",
        "Y",
    ).to_euler()
    try:
        context.view_layer.update()
    except Exception:
        pass


def _finalize_batch_test_import(
    context,
    imported_obj,
    *,
    begin_import_finalization=None,
):
    try:
        from moldboxer_silicone_native.source.object import Object
        from moldboxer_silicone_native.source.bl_utils import (
            configure_metric_millimeter_units,
        )
    except ImportError:
        from .object import Object
        from .bl_utils import configure_metric_millimeter_units

    model = Object(imported_obj)
    configure_metric_millimeter_units()
    model.select()

    max_dimension = max(model.width, model.depth, model.height)
    if 0 < max_dimension < 10:
        scale_factor = 1.0
        while max_dimension * scale_factor < 40:
            scale_factor *= 10.0
        for axis in range(3):
            model.scale(scale_factor, axis=axis)
        logger.info(
            "Batch test import scale correction applied: object=%s factor=%.3f",
            model.name,
            scale_factor,
        )

    context.scene.volume = 0
    context.scene.casting_volume_ml = 0
    if begin_import_finalization is not None:
        # Use the exact finalization pipeline used by the regular Import
        # operator. Besides canonical patron setup, this performs the normal
        # auto-orientation and restart pass before mold generation. Bypassing
        # it made batch-only base and wing geometry depend on the source file's
        # raw transform/orientation.
        return begin_import_finalization(
            context,
            model,
            reset_direct_planes=False,
        )

    # The synchronous runner must apply the same orientation and placement
    # rules as modal batches and regular imports, including Slip Casting.
    operators = importlib.import_module(f"{_addon_module_name()}.operators")
    operators.finish_task_sync(
        operators.begin_finalize_imported_model(
            context, model, reset_direct_planes=False,
        )
    )
    return None


def _run_direct_batch_test_clear_undercuts(context, mold_type) -> None:
    if mold_type.generate_operator != "silicone.automatic_mold":
        return

    extraction_mode = getattr(
        context.scene,
        "clear_undercuts_mode",
        "EASY_EXTRACTION",
    )
    undercuts_quality = getattr(
        context.scene,
        "undercuts_quality",
        "MID",
    )
    logger.info(
        "Batch test clearing Direct Mold undercuts: mode=%s quality=%s",
        extraction_mode,
        undercuts_quality,
    )
    result = bpy.ops.silicone.new_clear_undercuts(
        extraction_mode=extraction_mode,
        undercuts_quality=undercuts_quality,
    )
    if "FINISHED" not in result:
        raise BatchTestsError("Clear Undercuts failed before Direct Mold generation")


def _run_slip_casting_batch_test_clear_undercuts() -> None:
    result = bpy.ops.silicone.clear_slip_casting_undercuts()
    if "FINISHED" not in result:
        raise BatchTestsError("Clear Undercuts failed before Slip Casting generation")


def _run_batch_test_generation(mold_type, generation_operator) -> None:
    if mold_type.identifier in {"SLIP_CASTING", "SLIP_CASTING_VASE"}:
        result = bpy.ops.silicone.detect_slip_casting_cores()
        if "FINISHED" not in result:
            raise BatchTestsError("Prepare Casting failed before Slip Casting generation")

    generation_count = 2 if mold_type.identifier == "DIRECT_MOLD_SKIN" else 1
    for generation_index in range(generation_count):
        generation_result = generation_operator()
        if "FINISHED" in generation_result:
            continue
        stage = (
            "skin core"
            if mold_type.identifier == "DIRECT_MOLD_SKIN"
            and generation_index == 0
            else "mold system"
        )
        raise BatchTestsError(
            f"{mold_type.label} {stage} generation failed"
        )


def _write_batch_test_report_header(
    report_path: Path,
    target_path: Path,
    run_dir: Path,
    model_count: int,
    mold_type_label: str,
) -> None:
    report_path.write_text(
        "\n".join(
            [
                "Moldboxer Silicone batch tests report",
                f"Run started: {datetime.now().isoformat(timespec='seconds')}",
                f"Source folder: {target_path}",
                f"Run folder: {run_dir}",
                f"Model count: {model_count}",
                f"Mold type: {mold_type_label}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _batch_test_output_dir(
    run_dir: Path,
    mold_type,
    variant: str | None = None,
    *,
    all_generators: bool = False,
) -> Path:
    """Group artifacts by mold generator and the settings used for its case."""
    settings_name = "defaults" if all_generators else variant or "current_settings"
    return run_dir / mold_type.identifier / settings_name


def _batch_test_mesh_manifold_statuses(context) -> list[dict[str, object]]:
    try:
        from moldboxer_silicone_native.source.mesh_decimation import (
            mesh_manifold_state,
        )
    except ImportError:
        from .mesh_decimation import mesh_manifold_state

    depsgraph = context.evaluated_depsgraph_get()
    statuses = []
    for obj in sorted(
        (obj for obj in bpy.data.objects if obj.type == "MESH"),
        key=lambda obj: obj.name.casefold(),
    ):
        check_start = time.perf_counter()
        try:
            evaluated_obj = obj.evaluated_get(depsgraph)
            mesh = evaluated_obj.to_mesh()
            try:
                is_manifold, non_manifold_edges = mesh_manifold_state(mesh)
            finally:
                evaluated_obj.to_mesh_clear()

            statuses.append(
                {
                    "name": obj.name,
                    "is_manifold": is_manifold,
                    "non_manifold_edges": non_manifold_edges,
                    "check_elapsed": time.perf_counter() - check_start,
                }
            )
        except Exception as exc:
            logger.exception("Batch test manifold check failed for %s", obj.name)
            statuses.append(
                {
                    "name": obj.name,
                    "error": str(exc),
                    "check_elapsed": time.perf_counter() - check_start,
                }
            )
    return statuses


def _append_batch_test_report_entry(
    report_path: Path,
    *,
    model_path: Path,
    status: str,
    execution_elapsed: float,
    mold_elapsed: float | None = None,
    blend_path: Path | None = None,
    export_dir: Path | None = None,
    manifold_statuses: list[dict[str, object]] | None = None,
    error: Exception | None = None,
    variant: str | None = None,
) -> None:
    lines = [
        f"Model: {model_path.name}",
        f"Status: {status}",
        f"Execution time: {execution_elapsed:.3f}s",
    ]
    if variant is not None:
        lines.append(f"Options: {variant}")
    if mold_elapsed is not None:
        lines.append(f"Mold system completed in: {mold_elapsed:.3f}s")
    if blend_path is not None:
        lines.append(f"Blend file: {blend_path}")
    if export_dir is not None:
        lines.append(f"Export folder: {export_dir}")
    if error is not None:
        lines.append(f"Error: {error}")

    lines.append("Post-export cleaned object manifold status:")
    if manifold_statuses:
        for item in manifold_statuses:
            if "error" in item:
                lines.append(
                    "  - "
                    f"{item['name']}: "
                    f"check_error={item['error']} "
                    f"check_time={item['check_elapsed']:.3f}s"
                )
                continue
            lines.append(
                "  - "
                f"{item['name']}: "
                f"manifold={item['is_manifold']} "
                f"non_manifold_edges={item['non_manifold_edges']} "
                f"check_time={item['check_elapsed']:.3f}s"
            )
    else:
        lines.append("  - Not checked")
    lines.append("")

    with report_path.open("a", encoding="utf-8") as report_file:
        report_file.write("\n".join(lines))
        report_file.write("\n")


class _GuardedBatchTestTask:
    """Record the active model failure before a modal task propagates it."""

    def __init__(self, session, task) -> None:
        self._session = session
        self._task = task

    @property
    def redraw_interval(self):
        return getattr(self._task, "redraw_interval", None)

    def done(self) -> bool:
        try:
            return self._task.done()
        except Exception as exc:
            self._session.fail_active_model(exc)
            raise

    def finish(self):
        try:
            return self._task.finish()
        except Exception as exc:
            self._session.fail_active_model(exc)
            raise


def _slip_casting_batch_variants():
    """The complete 2 × 3 × 4 slip-casting option matrix."""
    funnels = (
        ("adapted_external", "ADAPTED", "EXTERNAL", "CAVITY"),
        ("internal_hollow", "ADAPTED", "INTERNAL", "CAVITY"),
        ("internal_solid", "ADAPTED", "INTERNAL", "FILLED"),
        ("rounded", "ROUNDED", "EXTERNAL", "CAVITY"),
    )
    return [
        (
            f"{'foot' if foot else 'no_foot'}_{shape_label}_{funnel_label}",
            {
                "slip_casting_generate_base": foot,
                "slip_casting_shape_type": shape,
                "slip_casting_funnel_type": funnel,
                "slip_casting_adapted_variant": placement,
                "slip_casting_internal_model_type": model_type,
            },
        )
        for foot in (True, False)
        for shape_label, shape in (
            ("cubic", "cube"), ("round", "cylinder"), ("adapted", "adapted")
        )
        for funnel_label, funnel, placement, model_type in funnels
    ]


def _multipart_batch_variants():
    """Exercise all three multipart shapes with both base layouts."""
    # Stored opening identifiers predate the current UI labels; keep this
    # mapping aligned with the silicone_multipart_opening enum in properties.py.
    openings = (("fully_enclosed", "OPEN_BASE"), ("open_base", "ENCLOSED"))
    return [
        (
            f"{label}_{opening_label}",
            {
                "slip_casting_shape_type": shape,
                "silicone_multipart_opening": opening,
            },
        )
        for label, shape in (
            ("cubic", "cube"), ("round", "cylinder"), ("adapted", "adapted")
        )
        for opening_label, opening in openings
    ]


class BatchTestSession:
    """State and guarded callbacks for the modal batch-test workflow."""

    def __init__(
        self,
        context,
        batch_tests_path: str,
        *,
        begin_import_finalization=None,
        slip_casting_all_options=False,
        multipart_all_shapes=False,
        all_generators=False,
    ) -> None:
        try:
            from moldboxer_silicone_native.source.bl_utils import import_model
            from moldboxer_silicone_native.source.components.export import begin_export
            from moldboxer_silicone_native.source.mold_types import get_mold_type, MOLD_TYPE_OPTIONS
        except ImportError:
            from .bl_utils import import_model
            from .components.export import begin_export
            from .mold_types import get_mold_type, MOLD_TYPE_OPTIONS

        self.context = context
        self._import_model = import_model
        self._begin_export = begin_export
        self._begin_import_finalization = begin_import_finalization
        self.target_path = _resolve_batch_tests_path(batch_tests_path)
        self.model_paths = _batch_test_model_paths(self.target_path)
        if not self.model_paths:
            raise BatchTestsError(
                "No STL, OBJ, PLY, or 3MF models found in batch tests path"
            )

        self.mold_type = get_mold_type(
            getattr(context.scene, "mold_type_preview", "")
        )
        self.all_generators = all_generators
        if all_generators and (slip_casting_all_options or multipart_all_shapes):
            raise BatchTestsError("Choose one batch test mode at a time")
        if slip_casting_all_options and multipart_all_shapes:
            raise BatchTestsError("Choose one batch option matrix at a time")
        if slip_casting_all_options:
            from .mold_types import is_slip_casting_type

            if not is_slip_casting_type(self.mold_type.identifier):
                raise BatchTestsError("Select a Slip Casting mold type to test all options")
            variants = _slip_casting_batch_variants()
        elif multipart_all_shapes:
            from .mold_types import is_silicone_multipart_type

            if not is_silicone_multipart_type(self.mold_type.identifier):
                raise BatchTestsError("Select Silicone Multi-parts to test all shapes")
            variants = _multipart_batch_variants()
        else:
            variants = [(None, {})]
        mold_types = MOLD_TYPE_OPTIONS if all_generators else (self.mold_type,)
        self.test_cases = [
            (path, mold_type.identifier if all_generators else name, settings, mold_type)
            for path in self.model_paths
            for mold_type in mold_types
            for name, settings in variants
        ]
        self.active_variant = None
        self.active_settings = {}
        run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_dir = self.target_path / f"tests_{run_stamp}"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.report_path = self.run_dir / "batch_tests_report.txt"
        _write_batch_test_report_header(
            self.report_path,
            self.target_path,
            self.run_dir,
            len(self.model_paths),
            "All generators" if all_generators else self.mold_type.label,
        )
        if slip_casting_all_options or multipart_all_shapes or all_generators:
            with self.report_path.open("a", encoding="utf-8") as report_file:
                report_file.write(
                    f"Variants per model: {len(mold_types) * len(variants)}\n"
                    f"Test case count: {len(self.test_cases)}\n\n"
                )
        self.split_plane_specs = _capture_batch_test_split_plane_specs()
        self.fixture_height_plane_spec = (
            _capture_batch_test_fixture_height_plane_spec(self.mold_type)
        )
        self.completed_count = 0
        self.active_model_path = None
        self.model_stamp = None
        self.model_start = None
        self.mold_elapsed = None
        self.manifold_statuses = None
        self.blend_path = None
        self.export_dir = None
        self._active_model_failed = False

    def label(self, phase: str) -> str:
        model_name = (
            self.active_model_path.name
            if self.active_model_path is not None
            else "Batch tests"
        )
        if self.active_variant:
            model_name += f" [{self.active_variant}]"
        return f"{model_name}: {phase}"

    def start_model(self, model_path: Path, variant=None, settings=None, mold_type=None) -> None:
        if mold_type is not None:
            self.mold_type = mold_type
        self.active_variant = variant
        self.active_settings = dict(settings or {})
        self.active_model_path = model_path
        self.output_dir = _batch_test_output_dir(
            self.run_dir,
            self.mold_type,
            variant,
            all_generators=getattr(self, "all_generators", False),
        )
        self.model_stamp = (
            datetime.now().strftime("%Y%m%d_%H%M%S")
            + f"_{model_path.suffix[1:].lower()}"
        )
        if variant:
            self.model_stamp += f"_{variant}"
        self.model_start = time.perf_counter()
        self.mold_elapsed = None
        self.manifold_statuses = None
        self.blend_path = None
        self.export_dir = None
        self._active_model_failed = False
        logger.info("Batch test started for %s", model_path)

    def clear_scene(self) -> None:
        _clear_scene_for_batch_test(self.context)
        _restore_batch_test_mold_type(self.context, self.mold_type)

    def apply_variant(self) -> None:
        # Apply after the mold mode is restored and before import/preparation.
        for name, value in self.active_settings.items():
            setattr(self.context.scene, name, value)

    def import_model(self):
        imported_obj = self._import_model(str(self.active_model_path))
        return _finalize_batch_test_import(
            self.context,
            imported_obj,
            begin_import_finalization=self._begin_import_finalization,
        )

    def restore_guides(self) -> None:
        if self.all_generators:
            _restore_batch_test_split_plane_specs(self.context, [])
            return
        _restore_batch_test_fixture_height_plane_spec(
            self.context,
            self.fixture_height_plane_spec,
        )
        _restore_batch_test_split_plane_specs(
            self.context,
            self.split_plane_specs,
        )

    def clear_direct_undercuts(self) -> None:
        _run_direct_batch_test_clear_undercuts(self.context, self.mold_type)

    def clear_slip_casting_undercuts(self) -> None:
        _run_slip_casting_batch_test_clear_undercuts()

    def mark_generation_complete(self) -> None:
        self.mold_elapsed = time.perf_counter() - self.model_start

    def inspect_manifold_statuses(self) -> None:
        self.manifold_statuses = _batch_test_mesh_manifold_statuses(self.context)

    def save_blend(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.blend_path = self.output_dir / (
            f"{self.active_model_path.stem}_{self.model_stamp}.blend"
        )
        bpy.ops.wm.save_as_mainfile(filepath=str(self.blend_path))

    def begin_export(self):
        self.export_dir = self.output_dir / (
            f"{self.active_model_path.stem}_{self.model_stamp}_exports"
        )
        return self._begin_export(str(self.export_dir))

    def complete_model(self) -> None:
        execution_elapsed = time.perf_counter() - self.model_start
        _append_batch_test_report_entry(
            self.report_path,
            model_path=self.active_model_path,
            variant=self.active_variant,
            status="FINISHED",
            execution_elapsed=execution_elapsed,
            mold_elapsed=self.mold_elapsed,
            blend_path=self.blend_path,
            export_dir=self.export_dir,
            manifold_statuses=self.manifold_statuses,
        )
        self.completed_count += 1
        logger.info(
            "Batch test completed for %s: blend=%s exports=%s",
            self.active_model_path,
            self.blend_path,
            self.export_dir,
        )

    def fail_active_model(self, error: Exception) -> None:
        if self.active_model_path is None or self._active_model_failed:
            return
        self._active_model_failed = True
        logger.error(
            "Batch test failed for %s",
            self.active_model_path,
            exc_info=(type(error), error, error.__traceback__),
        )
        _append_batch_test_report_entry(
            self.report_path,
            model_path=self.active_model_path,
            variant=self.active_variant,
            status="FAILED",
            execution_elapsed=time.perf_counter() - self.model_start,
            mold_elapsed=self.mold_elapsed,
            manifold_statuses=self.manifold_statuses,
            error=error,
        )

    def guard(self, callback):
        def guarded_callback():
            try:
                value = callback()
            except Exception as exc:
                self.fail_active_model(exc)
                raise
            if (
                value is not None
                and callable(getattr(value, "done", None))
                and callable(getattr(value, "finish", None))
            ):
                return _GuardedBatchTestTask(self, value)
            return value

        return guarded_callback


def run_batch_tests(context, batch_tests_path: str) -> tuple[int, Path]:
    try:
        from moldboxer_silicone_native.source.bl_utils import import_model
        from moldboxer_silicone_native.source.components.export import export
        from moldboxer_silicone_native.source.mold_types import get_mold_type
    except ImportError:
        from .bl_utils import import_model
        from .components.export import export
        from .mold_types import get_mold_type

    target_path = _resolve_batch_tests_path(batch_tests_path)
    model_paths = _batch_test_model_paths(target_path)
    if not model_paths:
        raise BatchTestsError("No STL, OBJ, PLY, or 3MF models found in batch tests path")

    mold_type = get_mold_type(
        getattr(context.scene, "mold_type_preview", "")
    )
    operator_group, operator_name = mold_type.generate_operator.split(".", 1)
    generation_operator = getattr(
        getattr(bpy.ops, operator_group),
        operator_name,
    )

    run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = target_path / f"tests_{run_stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    output_dir = _batch_test_output_dir(run_dir, mold_type)
    report_path = run_dir / "batch_tests_report.txt"
    _write_batch_test_report_header(
        report_path,
        target_path,
        run_dir,
        len(model_paths),
        mold_type.label,
    )
    split_plane_specs = _capture_batch_test_split_plane_specs()
    fixture_height_plane_spec = _capture_batch_test_fixture_height_plane_spec(
        mold_type
    )

    completed_count = 0
    for model_path in model_paths:
        model_stamp = (
            datetime.now().strftime("%Y%m%d_%H%M%S")
            + f"_{model_path.suffix[1:].lower()}"
        )
        model_start = time.perf_counter()
        mold_elapsed = None
        manifold_statuses = None

        try:
            logger.info("Batch test started for %s", model_path)
            _clear_scene_for_batch_test(context)
            _restore_batch_test_mold_type(context, mold_type)
            imported_obj = import_model(str(model_path))
            _finalize_batch_test_import(context, imported_obj)
            _restore_batch_test_fixture_height_plane_spec(
                context,
                fixture_height_plane_spec,
            )
            _restore_batch_test_split_plane_specs(context, split_plane_specs)
            _run_direct_batch_test_clear_undercuts(context, mold_type)

            _run_batch_test_generation(mold_type, generation_operator)
            mold_elapsed = time.perf_counter() - model_start
            output_dir.mkdir(parents=True, exist_ok=True)
            blend_path = output_dir / f"{model_path.stem}_{model_stamp}.blend"
            bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))

            export_dir = output_dir / f"{model_path.stem}_{model_stamp}_exports"
            export(str(export_dir))
            # STL export cleans each exportable scene mesh in place before it
            # writes the file. Inspect only after export so this report records
            # the geometry produced by the cleaner, rather than its input.
            manifold_statuses = _batch_test_mesh_manifold_statuses(context)

            execution_elapsed = time.perf_counter() - model_start
            _append_batch_test_report_entry(
                report_path,
                model_path=model_path,
                status="FINISHED",
                execution_elapsed=execution_elapsed,
                mold_elapsed=mold_elapsed,
                blend_path=blend_path,
                export_dir=export_dir,
                manifold_statuses=manifold_statuses,
            )
            completed_count += 1
            logger.info(
                "Batch test completed for %s: blend=%s exports=%s",
                model_path,
                blend_path,
                export_dir,
            )
        except Exception as exc:
            logger.exception("Batch test failed for %s", model_path)
            _append_batch_test_report_entry(
                report_path,
                model_path=model_path,
                status="FAILED",
                execution_elapsed=time.perf_counter() - model_start,
                mold_elapsed=mold_elapsed,
                manifold_statuses=manifold_statuses,
                error=exc,
            )
            raise BatchTestsError(f"{model_path.name}: {exc}") from exc

    return completed_count, run_dir
