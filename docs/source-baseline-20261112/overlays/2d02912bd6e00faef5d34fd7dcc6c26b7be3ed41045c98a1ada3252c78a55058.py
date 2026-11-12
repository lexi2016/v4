"""Load one trusted sibling package without changing interpreter search paths."""
from __future__ import annotations

import hashlib
import importlib.util
import re
import sys
import threading
from functools import lru_cache
from pathlib import Path
from types import ModuleType


_SAFE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_IMPORT_LOCK = threading.RLock()


def _restore_module_prefix(
    prefix: str, saved: dict[str, ModuleType | None]
) -> None:
    for name in tuple(sys.modules):
        if name == prefix or name.startswith(prefix + "."):
            sys.modules.pop(name, None)
    for name, module in saved.items():
        if module is not None:
            sys.modules[name] = module


def _load_sibling_package(root: Path, name: str) -> ModuleType | None:
    package_dir = root / name
    package_init = package_dir / "__init__.py"
    if not package_dir.is_dir():
        return None
    if not package_init.is_file():
        # ``scripts`` is a trusted namespace package in the shared upstream;
        # give importlib an explicit path without adding that path to
        # sys.path.
        package = ModuleType(name)
        package.__path__ = [str(package_dir)]  # type: ignore[attr-defined]
        package.__package__ = name
        package.__spec__ = importlib.util.spec_from_loader(
            name, loader=None, is_package=True
        )
        sys.modules[name] = package
        return package
    spec = importlib.util.spec_from_file_location(
        name,
        package_init,
        submodule_search_locations=[str(package_dir)],
    )
    if spec is None or spec.loader is None:
        raise ValueError(f"trusted sibling package cannot be loaded: {package_init}")
    package = importlib.util.module_from_spec(spec)
    sys.modules[name] = package
    spec.loader.exec_module(package)
    return package


@lru_cache(maxsize=16)
def load_isolated_package_module(
    package_root: Path,
    *,
    package_directory: str,
    module_leaf: str,
    namespace_prefix: str,
) -> ModuleType:
    """Import a fixed module from a verified directory under an isolated name."""
    for label, value in (
        ("package_directory", package_directory),
        ("module_leaf", module_leaf),
        ("namespace_prefix", namespace_prefix),
    ):
        if not _SAFE_NAME.fullmatch(value):
            raise ValueError(f"unsafe {label}: {value!r}")

    root = Path(package_root).resolve()
    package_dir = root / package_directory
    package_init = package_dir / "__init__.py"
    module_path = package_dir / f"{module_leaf}.py"
    if not package_init.is_file() or not module_path.is_file():
        raise ValueError(f"shared module missing: {module_path}")

    token = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:12]
    package_name = f"_{namespace_prefix}_{token}"
    with _IMPORT_LOCK:
        if package_name not in sys.modules:
            package_spec = importlib.util.spec_from_file_location(
                package_name,
                package_init,
                submodule_search_locations=[str(package_dir)],
            )
            if package_spec is None or package_spec.loader is None:
                raise ValueError(f"shared package cannot be loaded: {package_init}")
            package = importlib.util.module_from_spec(package_spec)
            sys.modules[package_name] = package
            package_spec.loader.exec_module(package)
        else:
            package = sys.modules[package_name]

        module_name = f"{package_name}.{module_leaf}"
        if module_name not in sys.modules:
            module_spec = importlib.util.spec_from_file_location(module_name, module_path)
            if module_spec is None or module_spec.loader is None:
                raise ValueError(f"shared module cannot be loaded: {module_path}")
            module = importlib.util.module_from_spec(module_spec)
            # A few trusted upstream packages retain absolute imports of their
            # sibling package (for example ``scripts.*``).  Alias only those
            # fixed package roots for this execution, never the interpreter
            # search path, and restore every pre-existing module afterwards.
            alias_names = {package_directory}
            if (root / "scripts").is_dir():
                alias_names.add("scripts")
            saved = {
                name: sys.modules.get(name)
                for name in tuple(sys.modules)
                if any(name == alias or name.startswith(alias + ".") for alias in alias_names)
            }
            try:
                sys.modules[package_directory] = package
                if "scripts" in alias_names:
                    _load_sibling_package(root, "scripts")
                sys.modules[module_name] = module
                try:
                    module_spec.loader.exec_module(module)
                except BaseException:
                    sys.modules.pop(module_name, None)
                    raise
            finally:
                for alias in alias_names:
                    _restore_module_prefix(alias, saved)
        return sys.modules[module_name]


__all__ = ["load_isolated_package_module"]
