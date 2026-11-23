#!/usr/bin/env python3
"""Build the plain-Python Moldboxer Updater extension deterministically."""

import argparse
import hashlib
from pathlib import Path
import re
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "moldboxer_updater_extension"
PACKAGE_FILES = (
    (SOURCE_DIR / "blender_manifest.toml", "blender_manifest.toml"),
    (SOURCE_DIR / "__init__.py", "__init__.py"),
    (SOURCE_DIR / "updater.py", "updater.py"),
    (SOURCE_DIR / "README.md", "README.md"),
    (ROOT / "LICENSES" / "GPL-3.0-or-later.txt", "LICENSE"),
)
FIXED_TIMESTAMP = (2020, 1, 1, 0, 0, 0)


def _manifest_version() -> str:
    manifest = (SOURCE_DIR / "blender_manifest.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"\s*$', manifest, flags=re.MULTILINE)
    if match is None:
        raise RuntimeError("Updater manifest has no version")
    return match.group(1)


def build_archive(output_path: Path) -> tuple[int, str]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        output_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for source_path, archive_name in PACKAGE_FILES:
            info = zipfile.ZipInfo(archive_name, FIXED_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, source_path.read_bytes(), compresslevel=9)

    payload = output_path.read_bytes()
    return len(payload), hashlib.sha256(payload).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    version = _manifest_version()
    output_path = args.output or (
        ROOT / "dist" / "updater" / f"moldboxer_updater-{version}.zip"
    )
    size, digest = build_archive(output_path)
    print(output_path)
    print(f"archive_size={size}")
    print(f"archive_hash=sha256:{digest}")


if __name__ == "__main__":
    main()
