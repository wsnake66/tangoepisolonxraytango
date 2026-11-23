#!/usr/bin/env python3
"""Remove diagnostics from an isolated production package tree."""

from __future__ import annotations

import argparse
import ast
import base64
import binascii
from pathlib import Path

try:
    from .verify_client_boundary import validate_client_boundary
except ImportError:
    from verify_client_boundary import validate_client_boundary


LOGGER_METHODS = {
    "debug",
    "info",
    "warning",
    "error",
    "exception",
    "critical",
    "log",
}
PRINT_METHODS = {"print_exc", "print_exception"}
BUILD_PROFILE_PATH = Path("source/build_profile.py")
OPERATOR_LOGS_PATH = Path("source/operator_logs.py")
SERVICE_TRANSPORT_PATH = Path("source/service_transport.py")
PRODUCTION_OPERATOR_LOGS = '''"""Operator logging is unavailable in production builds."""

from pathlib import Path

def log_background_event(event_logger, message: str, *args) -> None:
    return None


def get_last_operator_log_path() -> Path:
    return Path()


def begin_operator_log(operator_id: str, operator_label: str) -> bool:
    return False


def end_operator_log(operator_id: str, operator_label: str, result=None) -> None:
    return None


def read_last_operator_log() -> str:
    return ""


def last_operator_log_mtime() -> float:
    return 0.0


def last_operator_log_age_seconds() -> float:
    return 0.0
'''


def _is_name(node: ast.AST, name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == name


def _is_logging_get_logger(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "getLogger"
        and _is_name(node.func.value, "logging")
    )


def _is_logger_reference(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "logger" or node.id.endswith("_logger")
    return _is_logging_get_logger(node)


def _is_diagnostic_call(node: ast.Call) -> bool:
    func = node.func
    if _is_name(func, "print"):
        return True
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr in PRINT_METHODS and _is_name(func.value, "traceback"):
        return True
    if func.attr == "basicConfig" and _is_name(func.value, "logging"):
        return True
    return func.attr in LOGGER_METHODS and _is_logger_reference(func.value)


class ProductionTransformer(ast.NodeTransformer):
    def __init__(self, *, worker_grant_public_key: str | None = None) -> None:
        super().__init__()
        self.worker_grant_public_key = worker_grant_public_key

    def visit_Call(self, node: ast.Call) -> ast.AST:
        node = self.generic_visit(node)
        if _is_diagnostic_call(node):
            return ast.copy_location(ast.Constant(value=None), node)
        return node

    def visit_Assign(self, node: ast.Assign) -> ast.AST:
        node = self.generic_visit(node)
        target_names = {
            target.id for target in node.targets if isinstance(target, ast.Name)
        }
        if "IS_PRODUCTION_BUILD" in target_names:
            node.value = ast.copy_location(ast.Constant(value=True), node.value)
        elif any(name.startswith("SLIP_CASTING_") and "DEBUG" in name for name in target_names):
            node.value = ast.copy_location(ast.Constant(value=False), node.value)
        elif "WORKER_RELEASE_ORIGIN_LOCK" in target_names:
            node.value = ast.copy_location(ast.Constant(value=True), node.value)
        elif (
            "WORKER_GRANT_PUBLIC_KEY" in target_names
            and self.worker_grant_public_key is not None
        ):
            node.value = ast.copy_location(
                ast.Constant(value=self.worker_grant_public_key),
                node.value,
            )
        return node


class DiagnosticCallFinder(ast.NodeVisitor):
    def __init__(self) -> None:
        self.calls: list[ast.Call] = []

    def visit_Call(self, node: ast.Call) -> None:
        if _is_diagnostic_call(node):
            self.calls.append(node)
        self.generic_visit(node)


def _rewrite_python_file(
    path: Path,
    *,
    worker_grant_public_key: str | None = None,
) -> None:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    transformed = ProductionTransformer(
        worker_grant_public_key=worker_grant_public_key
    ).visit(tree)
    ast.fix_missing_locations(transformed)
    output = ast.unparse(transformed) + "\n"
    compile(output, str(path), "exec")
    path.write_text(output, encoding="utf-8")


def _validate_no_diagnostic_calls(package_root: Path) -> None:
    remaining: list[str] = []
    for path in sorted(package_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        finder = DiagnosticCallFinder()
        finder.visit(tree)
        remaining.extend(
            f"{path.relative_to(package_root)}:{call.lineno}" for call in finder.calls
        )
    if remaining:
        raise RuntimeError(
            "Production package still contains diagnostic calls:\n  "
            + "\n  ".join(remaining)
        )


def prepare_production_tree(
    package_root: Path,
    *,
    require_build_profile: bool = True,
    worker_grant_public_key: str | None = None,
) -> int:
    package_root = package_root.resolve()
    repository_root = Path(__file__).resolve().parents[1]
    if package_root in {repository_root, repository_root / "source"}:
        raise ValueError("Refusing to rewrite the working source tree")
    if not package_root.is_dir():
        raise FileNotFoundError(f"Package tree does not exist: {package_root}")

    validate_client_boundary(package_root)

    build_profile_path = package_root / BUILD_PROFILE_PATH
    if require_build_profile and not build_profile_path.is_file():
        raise FileNotFoundError(
            f"Production build profile is missing: {build_profile_path}"
        )

    operator_logs_path = package_root / OPERATOR_LOGS_PATH
    if operator_logs_path.is_file():
        operator_logs_path.write_text(PRODUCTION_OPERATOR_LOGS, encoding="utf-8")

    service_transport_path = package_root / SERVICE_TRANSPORT_PATH
    if service_transport_path.is_file() and not worker_grant_public_key:
        raise RuntimeError("Production worker grant public key is required")
    if worker_grant_public_key:
        try:
            decoded_key = base64.b64decode(
                worker_grant_public_key
                + "=" * (-len(worker_grant_public_key) % 4),
                altchars=b"-_",
                validate=True,
            )
        except (UnicodeEncodeError, ValueError, binascii.Error) as exc:
            raise ValueError("Worker grant public key is invalid") from exc
        if len(decoded_key) != 32:
            raise ValueError("Worker grant public key must contain 32 raw bytes")

    python_files = sorted(package_root.rglob("*.py"))
    for path in python_files:
        _rewrite_python_file(
            path,
            worker_grant_public_key=worker_grant_public_key,
        )

    if build_profile_path.is_file():
        profile_tree = ast.parse(build_profile_path.read_text(encoding="utf-8"))
        production_values = [
            node.value.value
            for node in profile_tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name)
                and target.id == "IS_PRODUCTION_BUILD"
                for target in node.targets
            )
            and isinstance(node.value, ast.Constant)
        ]
        if production_values != [True]:
            raise RuntimeError("Production build profile was not enabled")

    _validate_no_diagnostic_calls(package_root)
    return len(python_files)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("package_root", type=Path)
    parser.add_argument(
        "--allow-missing-build-profile",
        action="store_true",
        help="Used for a root-only package whose native wheel was prepared separately.",
    )
    parser.add_argument(
        "--worker-grant-public-key",
        help="Base64url-encoded raw Ed25519 public key embedded in the worker.",
    )
    args = parser.parse_args()
    count = prepare_production_tree(
        args.package_root,
        require_build_profile=not args.allow_missing_build_profile,
        worker_grant_public_key=args.worker_grant_public_key,
    )
    print(f"Prepared {count} production Python files")


if __name__ == "__main__":
    main()
