from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess


_MANIFOLD_LINE = re.compile(
    r"^\s*manifold\s*=\s*(yes|no)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(frozen=True)
class BambuManifoldResult:
    manifold: bool
    output: str


def find_bambu_studio_executable() -> str | None:
    """Return the installed Bambu Studio CLI executable, when available."""

    candidates: list[Path] = []
    if os.name == "nt":
        for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            root = os.environ.get(variable)
            if root:
                candidates.extend(
                    (
                        Path(root) / "Bambu Studio" / "bambu-studio.exe",
                        Path(root) / "BambuStudio" / "bambu-studio.exe",
                    )
                )
    else:
        candidates.extend(
            (
                Path("/Applications/BambuStudio.app/Contents/MacOS/BambuStudio"),
                Path.home()
                / "Applications/BambuStudio.app/Contents/MacOS/BambuStudio",
            )
        )

    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)

    for command in ("bambu-studio", "BambuStudio"):
        executable = shutil.which(command)
        if executable:
            return executable
    return None


def parse_bambu_info_output(output: str) -> bool:
    """Parse the manifold result emitted by ``BambuStudio --info``."""

    match = _MANIFOLD_LINE.search(output)
    if match is None:
        raise ValueError("Bambu Studio did not return a manifold result")
    return match.group(1).casefold() == "yes"


def check_stl_with_bambu(
    executable: str,
    stl_path: str | Path,
    *,
    timeout: float = 60.0,
) -> BambuManifoldResult:
    """Import an STL through Bambu Studio and return its repaired mesh status."""

    path = Path(stl_path)
    completed = subprocess.run(
        (executable, "--info", str(path)),
        cwd=str(path.parent),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    if completed.returncode != 0:
        detail = output.strip() or f"exit code {completed.returncode}"
        raise RuntimeError(f"Bambu Studio manifold check failed: {detail}")
    return BambuManifoldResult(
        manifold=parse_bambu_info_output(output),
        output=output,
    )
