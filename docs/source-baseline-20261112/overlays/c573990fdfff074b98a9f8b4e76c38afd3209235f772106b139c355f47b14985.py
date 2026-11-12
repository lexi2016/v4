"""Load trusted sibling packages without changing interpreter search paths."""
from __future__ import annotations
import hashlib
import builtins
import importlib.abc
import importlib.machinery
import importlib.util
import os
import re
import stat
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import NamedTuple

from infrastructure.isolated_import_policy import validate_isolated_import_policy

_SAFE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_IMPORT_LOCK = threading.RLock()
_FINDER_LOCK = threading.RLock()
# Immutable consumers may retain returned modules for lazy relative imports;
# only an explicit cache_clear may reclaim their managed namespace.
_CACHE_MAXSIZE: int | None = None
_CACHE: dict[tuple[Path, str, str, str], ModuleType] = {}
_CACHE_HITS = 0
_CACHE_MISSES = 0
_MANAGED_NAMESPACES: dict[str, "_ManagedNamespace"] = {}
_FINDER_PREFIXES: dict[str, list["_ManagedNamespace"]] = {}
_NAMESPACE_REGISTRY: dict[tuple[Path, str, str], "_ManagedNamespace"] = {}
_FINDER_OWNED = False
_ORIGINAL_IMPORT = builtins.__import__

class _CacheInfo(NamedTuple):
    hits: int
    misses: int
    maxsize: int | None
    currsize: int

@dataclass
class _ManagedNamespace:
    package: ModuleType
    root: Path
    package_directory: str
    prefix: str
    namespace_prefix: str
    owner_keys: set[tuple[Path, str, str, str]] = field(default_factory=set)
    canonical: bool = False
    owner_thread: int | None = None

class _SourceOnlyLoader(importlib.abc.SourceLoader):
    """A source loader whose code path never consults timestamped bytecode."""
    def __init__(self, fullname: str, root: Path, source_path: Path) -> None:
        self.fullname = fullname
        self.root = root
        self.source_path = source_path
    def _check_name(self, fullname: str) -> None:
        if fullname != self.fullname:
            raise ImportError(f"managed source loader name mismatch: {fullname!r}")
    def _trusted_source_path(self) -> Path:
        try:
            source_path = _inside(self.root, self.source_path, "managed source loader")
        except (OSError, TypeError, ValueError) as error:
            raise ValueError(f"managed source loader path escaped trusted root: {self.source_path}") from error
        if not source_path.is_file():
            raise ValueError(f"managed source loader source missing: {source_path}")
        return source_path
    def get_filename(self, fullname: str) -> str:
        self._check_name(fullname)
        return str(self._trusted_source_path())
    def get_data(self, path: str) -> bytes:
        source_path = self._trusted_source_path()
        if Path(path).resolve() != source_path:
            raise ValueError(f"managed source loader path mismatch: {path}")
        return self._read_source()
    def _read_source(self) -> bytes:
        source_path = _inside(self.root, self.source_path, "managed source loader")
        try:
            relative = source_path.relative_to(self.root)
            nofollow = getattr(os, "O_NOFOLLOW", 0)
            if not nofollow:
                raise ValueError("managed source loader needs O_NOFOLLOW")
            directory_flags = os.O_RDONLY | nofollow | getattr(os, "O_DIRECTORY", 0)
            file_flags = os.O_RDONLY | nofollow | getattr(os, "O_CLOEXEC", 0)
            root_fd = os.open(str(self.root), directory_flags)
            directory_fd = root_fd
            try:
                for part in relative.parts[:-1]:
                    next_fd = os.open(part, directory_flags, dir_fd=directory_fd)
                    if directory_fd != root_fd:
                        os.close(directory_fd)
                    directory_fd = next_fd
                source_fd = os.open(relative.parts[-1], file_flags, dir_fd=directory_fd)
                with os.fdopen(source_fd, "rb") as source:
                    if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                        raise ValueError(f"managed source is not a regular file: {source_path}")
                    return source.read()
            finally:
                if directory_fd != root_fd:
                    os.close(directory_fd)
                os.close(root_fd)
        except (OSError, ValueError) as error:
            if isinstance(error, ValueError):
                raise
            raise ValueError(f"managed source loader source cannot be read: {source_path}") from error
    def get_code(self, fullname: str):
        self._check_name(fullname)
        source_path = self._trusted_source_path()
        return self.source_to_code(self._read_source(), str(source_path))
    def exec_module(self, module: ModuleType) -> None:
        _install_managed_import(module)
        code = self.get_code(self.fullname)
        exec(code, module.__dict__)
    def is_package(self, fullname: str) -> bool:
        self._check_name(fullname)
        return self.source_path.name == "__init__.py"

class _FailClosedLoader(importlib.abc.Loader):
    """Loader returned for managed missing, pyc-only, or escaped paths."""
    def __init__(self, fullname: str, reason: str) -> None:
        self.fullname = fullname
        self.reason = reason
    def create_module(self, spec: object) -> None:
        return None
    def exec_module(self, module: ModuleType) -> None:
        raise ValueError(
            f"managed isolated import rejected for {self.fullname}: {self.reason}"
        )
    def is_package(self, fullname: str) -> bool:
        return False

class _ManagedNamespaceFinder(importlib.abc.MetaPathFinder):
    """Find source-only specs for prefixes currently owned by the loader."""
    def find_spec(self, fullname: str, path: object = None, target: object = None):
        state = _finder_state_for(fullname)
        if state is None: return None
        if state.canonical and state.owner_thread != threading.get_ident():
            with _IMPORT_LOCK:
                return _external_spec(fullname, target)
        if fullname == state.prefix: return None
        relative = fullname[len(state.prefix) + 1 :]
        parts = tuple(relative.split("."))
        if not parts or any(not _SAFE_NAME.fullmatch(part) for part in parts): return _fail_closed_spec(fullname, "unsafe managed module name")
        candidate = state.root / state.package_directory / Path(*parts)
        source_path = candidate.with_suffix(".py")
        try:
            trusted_source = _inside(state.root, source_path, "managed source module")
        except (OSError, TypeError, ValueError) as error:
            return _fail_closed_spec(fullname, str(error))
        if trusted_source.is_file(): return _source_spec(fullname, state.root, trusted_source)
        try:
            trusted_package = _inside(state.root, candidate, "managed package directory")
        except (OSError, TypeError, ValueError) as error:
            return _fail_closed_spec(fullname, str(error))
        if trusted_package.is_dir():
            package_init = trusted_package / "__init__.py"
            try:
                trusted_init = _inside(state.root, package_init, "managed package initializer")
            except (OSError, TypeError, ValueError) as error:
                return _fail_closed_spec(fullname, str(error))
            if trusted_init.is_file(): return _source_spec(fullname, state.root, trusted_init)
            if _has_pyc_evidence(package_init): return _fail_closed_spec(fullname, "pyc-only package evidence")
            return _namespace_spec(fullname, trusted_package)
        if _has_pyc_evidence(source_path):
            return _fail_closed_spec(fullname, "pyc-only module evidence")
        return _fail_closed_spec(fullname, "managed module source missing")

_SOURCE_ONLY_FINDER = _ManagedNamespaceFinder()

def _inside(root: Path, path: Path, label: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{label} escapes trusted package root: {path}") from error
    return resolved
def _state_candidate(
    state: _ManagedNamespace, fullname: str
) -> tuple[Path, Path] | None:
    if fullname == state.prefix or not fullname.startswith(state.prefix + "."): return None
    parts = tuple(fullname[len(state.prefix) + 1 :].split("."))
    if not parts or any(not _SAFE_NAME.fullmatch(part) for part in parts): return None
    package_dir = state.root / state.package_directory / Path(*parts)
    return package_dir.with_suffix(".py"), package_dir
def _module_owned_by_state(
    module: object, state: _ManagedNamespace, fullname: str
) -> bool:
    if fullname == state.prefix: return module is state.package and sys.modules.get(fullname) is module
    if not isinstance(module, ModuleType) or module.__name__ != fullname: return False
    spec = getattr(module, "__spec__", None)
    loader = getattr(spec, "loader", None)
    candidate = _state_candidate(state, fullname)
    if candidate is None: return False
    source_path, package_dir = candidate
    try:
        if isinstance(loader, _SourceOnlyLoader):
            expected = _inside(state.root, source_path, "managed child source")
            return (_inside(state.root, loader.source_path, "managed child loader") == expected
                    and _inside(state.root, Path(str(getattr(module, "__file__", ""))), "managed child") == expected)
        paths = _module_paths(module)
        expected = _inside(state.root, package_dir, "managed child package")
        return loader is None and bool(paths) and all(
            _inside(state.root, Path(path), "managed child package") == expected for path in paths)
    except (OSError, TypeError, ValueError):
        return False

def _candidate_exists(state: _ManagedNamespace, fullname: str) -> bool:
    candidate = _state_candidate(state, fullname)
    if candidate is None: return False
    source_path, package_dir = candidate
    try:
        return source_path.is_file() or package_dir.is_dir()
    except OSError:
        return True
def _ensure_managed_module(fullname: str, state: _ManagedNamespace) -> None:
    with _IMPORT_LOCK:
        current = sys.modules.get(fullname)
        if current is not None and not _module_owned_by_state(current, state, fullname):
            sys.modules.pop(fullname, None)
def _managed_import(
    name: str,
    globals: dict[str, object] | None = None,
    locals: dict[str, object] | None = None,
    fromlist: object = (),
    level: int = 0,
):
    package = globals.get("__package__") if isinstance(globals, dict) else None
    if level and isinstance(package, str) and package:
        try:
            absolute = importlib.util.resolve_name("." * level + name, package)
        except (ImportError, TypeError, ValueError):
            absolute = ""
        state = _finder_state_for(absolute) if absolute else None
        if state is not None:
            items = fromlist if isinstance(fromlist, (tuple, list)) else ()
            targets = [absolute] + [f"{absolute}.{item}" for item in items
                if isinstance(item, str) and item != "*"
                and (f"{absolute}.{item}" in sys.modules or _candidate_exists(state, f"{absolute}.{item}"))]
            for target in targets:
                if target == state.prefix or _candidate_exists(state, target): _ensure_managed_module(target, state)
            result = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)
            for target in targets:
                if target in sys.modules and not _module_owned_by_state(sys.modules[target], state, target):
                    raise ValueError(f"managed lazy import ownership changed: {target}")
            return result
    return _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)

def _install_managed_import(module: ModuleType) -> None:
    current = module.__dict__.get("__builtins__")
    builtins_dict = dict(current) if isinstance(current, dict) else dict(vars(builtins))
    builtins_dict["__import__"] = _managed_import
    module.__dict__["__builtins__"] = builtins_dict
def _source_spec(fullname: str, root: Path, source_path: Path):
    loader = _SourceOnlyLoader(fullname, root, source_path)
    is_package = source_path.name == "__init__.py"
    spec = importlib.util.spec_from_file_location(fullname, source_path, loader=loader,
        submodule_search_locations=[str(source_path.parent)] if is_package else None)
    if spec is None: raise ValueError(f"managed source spec unavailable: {source_path}")
    return spec
def _namespace_spec(fullname: str, package_dir: Path):
    spec = importlib.util.spec_from_loader(fullname, loader=None, is_package=True)
    if spec is None: raise ValueError(f"managed namespace spec unavailable: {fullname}")
    spec.submodule_search_locations = [str(package_dir)]
    return spec
def _fail_closed_spec(fullname: str, reason: str):
    return importlib.util.spec_from_loader(fullname, _FailClosedLoader(fullname, reason), is_package=False)
def _has_pyc_evidence(source_path: Path) -> bool:
    candidates = [source_path.with_suffix(".pyc")]
    cache_dir = source_path.parent / "__pycache__"
    try:
        if cache_dir.is_dir(): candidates.extend(cache_dir.glob(f"{source_path.stem}.*.pyc"))
        return any(candidate.is_file() for candidate in candidates)
    except OSError:
        return True

def _finder_state_for(fullname: str) -> _ManagedNamespace | None:
    with _FINDER_LOCK:
        matches = [
            prefix
            for prefix, states in _FINDER_PREFIXES.items()
            if states and (fullname == prefix or fullname.startswith(prefix + "."))
        ]
        if not matches: return None
        return _FINDER_PREFIXES[max(matches, key=len)][-1]
def _meta_items(meta_path: object) -> tuple[object, ...]:
    if meta_path is None: return ()
    try:
        return tuple(meta_path)  # type: ignore[arg-type]
    except (TypeError, RuntimeError):
        return ()
def _external_spec(fullname: str, target: object = None):
    parent, _, _child = fullname.rpartition(".")
    if parent and parent not in sys.modules:
        try: _ORIGINAL_IMPORT(parent, {}, {}, (), 0)
        except (ImportError, ValueError): pass
    if parent:
        parent_paths = _module_paths(sys.modules[parent]) if parent in sys.modules else ()
        if not parent_paths:
            parent_spec = importlib.machinery.PathFinder.find_spec(parent, sys.path, target)
            parent_paths = getattr(parent_spec, "submodule_search_locations", None)
        if parent_paths: return importlib.machinery.PathFinder.find_spec(fullname, parent_paths, target)
    return importlib.machinery.PathFinder.find_spec(fullname, sys.path, target)
def _install_source_only_finder() -> None:
    global _FINDER_OWNED
    with _FINDER_LOCK:
        if any(item is _SOURCE_ONLY_FINDER for item in _meta_items(sys.meta_path)): return
        if sys.meta_path is None or not hasattr(sys.meta_path, "insert"):
            raise ValueError("mutable sys.meta_path required for isolated source loader")
        try: sys.meta_path.insert(0, _SOURCE_ONLY_FINDER)  # type: ignore[union-attr]
        except (AttributeError, TypeError) as error:
            raise ValueError("mutable sys.meta_path required for isolated source loader") from error
        _FINDER_OWNED = True
def _remove_owned_finder() -> None:
    global _FINDER_OWNED
    with _FINDER_LOCK:
        if not _FINDER_OWNED: return
        try:
            items = list(_meta_items(sys.meta_path))
            positions = [index for index, item in enumerate(items) if item is _SOURCE_ONLY_FINDER]
            if positions:
                index = positions[1] if len(positions) > 1 and positions[0] == 0 and positions[1] == 1 else positions[0]
                items.pop(index)
                sys.meta_path[:] = items
        except (AttributeError, TypeError):
            pass
        _FINDER_OWNED = False
def _release_finder_state(state: _ManagedNamespace) -> None:
    with _FINDER_LOCK:
        stack = _FINDER_PREFIXES.get(state.prefix)
        if stack is not None:
            stack[:] = [candidate for candidate in stack if candidate is not state]
            if not stack: _FINDER_PREFIXES.pop(state.prefix, None)
        if not _FINDER_PREFIXES: _remove_owned_finder()
def _register_finder_state(state: _ManagedNamespace) -> None:
    with _FINDER_LOCK:
        _install_source_only_finder()
        stack = _FINDER_PREFIXES.setdefault(state.prefix, [])
        if not any(candidate is state for candidate in stack): stack.append(state)
def _restore_meta_path(original: object, values: tuple[object, ...]) -> None:
    with _FINDER_LOCK:
        desired = list(values)
        if _FINDER_PREFIXES and not any(item is _SOURCE_ONLY_FINDER for item in desired): desired.insert(0, _SOURCE_ONLY_FINDER)
        elif not _FINDER_PREFIXES and _FINDER_OWNED: desired = [item for item in desired if item is not _SOURCE_ONLY_FINDER]
        try: original[:] = desired  # type: ignore[index]
        except (AttributeError, TypeError): pass
        sys.meta_path = original
def _module_parts(module_leaf: str) -> tuple[str, ...]:
    parts = tuple(module_leaf.split("."))
    if not parts or any(not _SAFE_NAME.fullmatch(part) for part in parts):
        raise ValueError(f"unsafe module_leaf: {module_leaf!r}")
    return parts
def _module_names(prefix: str) -> tuple[str, ...]:
    return tuple(
        name for name in tuple(sys.modules)
        if name == prefix or name.startswith(prefix + ".")
    )
def _purge_module_prefix(prefix: str) -> None:
    for name in _module_names(prefix):
        sys.modules.pop(name, None)
def _restore_module_prefixes(prefixes: set[str], saved: dict[str, ModuleType | None]) -> None:
    for prefix in prefixes:
        _purge_module_prefix(prefix)
    for name, module in saved.items(): sys.modules[name] = module
def _module_paths(module: ModuleType) -> tuple[str, ...]:
    paths = getattr(module, "__path__", ())
    if paths is None: return ()
    if isinstance(paths, (str, bytes)): return (str(paths),)
    return tuple(str(path) for path in paths)
def _validate_prefix(
    prefix: str, root: Path, label: str, *, check_names: bool = False
) -> None:
    for name in _module_names(prefix):
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            raise ValueError(f"{label} module is not a module: {name}")
        if getattr(module, "_isolated_import_blocker", False):
            continue
        if check_names and getattr(module, "__name__", None) != name:
            raise ValueError(f"{label} module name mismatch: {name}")
        module_file = getattr(module, "__file__", None)
        paths = _module_paths(module)
        if module_file: _inside(root, Path(str(module_file)), f"{label} {name}")
        for module_path in paths:
            if module_path: _inside(root, Path(module_path), f"{label} {name}")
        if not module_file and not paths:
            raise ValueError(f"{label} module provenance missing: {name}")
def _validate_aliases(alias_names: set[str], root: Path) -> None:
    for alias in alias_names:
        for name in _module_names(alias):
            module = sys.modules.get(name)
            if not isinstance(module, ModuleType):
                raise ValueError(f"trusted alias is not a module: {name}")
            if getattr(module, "_isolated_import_blocker", False):
                continue
            module_file = getattr(module, "__file__", None)
            paths = _module_paths(module)
            if not module_file and not paths:
                kind = "package" if name == alias else "module"
                raise ValueError(f"trusted alias {kind} provenance missing: {name}")
    for alias in alias_names:
        _validate_prefix(alias, root, "trusted alias")
def _namespace_package(name: str, package_dir: Path, *, blocker: bool = False) -> ModuleType:
    package = ModuleType(name)
    package.__path__ = [] if blocker else [str(package_dir)]  # type: ignore[attr-defined]
    package.__package__ = name
    if blocker: package._isolated_import_blocker = True  # type: ignore[attr-defined]
    package_spec = importlib.util.spec_from_loader(name, loader=None, is_package=True)
    if package_spec is None: raise ValueError(f"trusted namespace package cannot be loaded: {name}")
    package_spec.submodule_search_locations = [] if blocker else [str(package_dir)]
    package.__spec__ = package_spec
    sys.modules[name] = package
    return package
def _load_sibling_package(
    root: Path, name: str, *, execute: bool = True
) -> ModuleType | None:
    package_dir = _inside(root, root / name, "trusted sibling package")
    if not package_dir.is_dir(): return None
    package_init = package_dir / "__init__.py"
    if not package_init.is_file():
        if _has_pyc_evidence(package_init): raise ValueError(f"trusted sibling package is pyc-only: {package_dir}")
        return _namespace_package(name, package_dir)
    package_init = _inside(root, package_init, "trusted sibling package initializer")
    spec = _source_spec(name, root, package_init)
    if spec is None or spec.loader is None: raise ValueError(f"trusted sibling package cannot be loaded: {package_init}")
    package = importlib.util.module_from_spec(spec)
    sys.modules[name] = package
    if execute: spec.loader.exec_module(package)
    return package
def _prepare_package(
    root: Path, package_directory: str, package_name: str
) -> tuple[ModuleType, object | None]:
    package_dir = _inside(root, root / package_directory, "shared package")
    if not package_dir.is_dir(): raise ValueError(f"shared package missing: {package_dir}")
    package_init = package_dir / "__init__.py"
    if not package_init.is_file():
        if _has_pyc_evidence(package_init): raise ValueError(f"shared package is pyc-only: {package_dir}")
        return _namespace_package(package_name, package_dir), None
    package_init = _inside(root, package_init, "shared package initializer")
    package_spec = _source_spec(package_name, root, package_init)
    if package_spec is None or package_spec.loader is None: raise ValueError(f"shared package cannot be loaded: {package_init}")
    package = importlib.util.module_from_spec(package_spec)
    sys.modules[package_name] = package
    return package, package_spec
def _execute_package(package: ModuleType, package_spec: object | None) -> None:
    if package_spec is None: return
    loader = getattr(package_spec, "loader", None)
    if loader is None: raise ValueError(f"shared package loader unavailable: {package.__name__}")
    loader.exec_module(package)
def _valid_custom_prefix(
    package_name: str, root: Path, package_directory: str
) -> bool:
    package = sys.modules.get(package_name)
    if not isinstance(package, ModuleType): return False
    owner = _MANAGED_NAMESPACES.get(package_name)
    if (owner is None or owner.package is not package or owner.root != root
            or owner.package_directory != package_directory): return False
    try:
        _validate_prefix(package_name, root, "isolated package", check_names=True)
        expected_dir = _inside(root, root / package_directory, "isolated package")
        return tuple(Path(path).resolve() for path in _module_paths(package)) == (expected_dir,)
    except (OSError, TypeError, ValueError):
        return False
def _valid_module(
    module: object,
    *,
    root: Path,
    package_name: str,
    package_directory: str,
    module_name: str,
    module_path: Path,
) -> bool:
    if not isinstance(module, ModuleType) or sys.modules.get(module_name) is not module: return False
    if module.__name__ != module_name: return False
    module_file = getattr(module, "__file__", None)
    if not module_file: return False
    try:
        if _inside(root, Path(str(module_file)), "isolated module") != module_path: return False
        if not _valid_custom_prefix(package_name, root, package_directory): return False
        package = str(getattr(module, "__package__", "") or "")
        while package:
            parent = sys.modules.get(package)
            if not isinstance(parent, ModuleType): return False
            _validate_prefix(package, root, "isolated package chain", check_names=True)
            package = package.rpartition(".")[0]
    except (OSError, TypeError, ValueError):
        return False
    return True
def _prepare_nested_parents(
    root: Path, package_dir: Path, package_name: str, parents: tuple[str, ...]
) -> None:
    current_name = package_name
    current_dir = package_dir
    for part in parents:
        current_name = f"{current_name}.{part}"
        current_dir = _inside(root, current_dir / part, "nested shared package")
        if not current_dir.is_dir(): raise ValueError(f"nested shared package missing: {current_dir}")
        if _valid_custom_prefix(current_name, root, str(current_dir.relative_to(root))): continue
        _purge_module_prefix(current_name)
        package_init = current_dir / "__init__.py"
        if package_init.is_file():
            package_init = _inside(root, package_init, "nested shared package initializer")
            spec = _source_spec(current_name, root, package_init)
            if spec is None or spec.loader is None: raise ValueError(f"nested shared package cannot be loaded: {package_init}")
            package = importlib.util.module_from_spec(spec)
            sys.modules[current_name] = package
            spec.loader.exec_module(package)
        else:
            if _has_pyc_evidence(package_init): raise ValueError(f"nested shared package is pyc-only: {current_dir}")
            _namespace_package(current_name, current_dir)
def _snapshot_valid_custom(
    package_name: str, root: Path, package_directory: str
) -> dict[str, ModuleType | None]:
    if not _valid_custom_prefix(package_name, root, package_directory): return {}
    return {name: sys.modules[name] for name in _module_names(package_name)
            if isinstance(sys.modules.get(name), ModuleType)}
def _restore_custom_snapshot(
    package_name: str, snapshot: dict[str, ModuleType | None]
) -> None:
    _purge_module_prefix(package_name)
    for name, module in snapshot.items():
        if module is not None: sys.modules[name] = module
def _alias_names(root: Path, package_directory: str) -> set[str]:
    return {package_directory, "scripts", "shared_data"}
def _unique_package_name(
    root: Path, package_directory: str, namespace_prefix: str
) -> str:
    identity = b"\0".join((str(root.resolve()).encode(), package_directory.encode(), namespace_prefix.encode()))
    token = hashlib.sha256(identity).hexdigest()
    return f"_isolated_{token}"
def _register_unique_namespace(
    package_name: str,
    root: Path,
    package_directory: str,
    namespace_prefix: str,
    package: ModuleType,
) -> tuple[_ManagedNamespace, bool]:
    with _FINDER_LOCK:
        existing = _MANAGED_NAMESPACES.get(package_name)
        if (existing is not None and existing.package is package and existing.root == root
                and existing.package_directory == package_directory and existing.namespace_prefix == namespace_prefix):
            _register_finder_state(existing)
            return existing, False
        if existing is not None: _unregister_unique_namespace(package_name, existing)
        state = _ManagedNamespace(package, root, package_directory, package_name, namespace_prefix)
        _register_finder_state(state)
        _MANAGED_NAMESPACES[package_name] = state
        _NAMESPACE_REGISTRY[(root, package_directory, namespace_prefix)] = state
        return state, True
def _unregister_unique_namespace(
    package_name: str, state: _ManagedNamespace | None = None
) -> None:
    with _FINDER_LOCK:
        current = _MANAGED_NAMESPACES.get(package_name)
        if current is None or (state is not None and current is not state): return
        _MANAGED_NAMESPACES.pop(package_name, None)
        identity = (current.root, current.package_directory, current.namespace_prefix)
        if _NAMESPACE_REGISTRY.get(identity) is current: _NAMESPACE_REGISTRY.pop(identity, None)
        _release_finder_state(current)

_MISSING = object()
def _under_prefix(name: str, prefixes: set[str]) -> bool:
    return any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes)
def _mapping_items(mapping: object) -> tuple[tuple[object, object], ...]:
    try:
        return tuple(mapping.items())  # type: ignore[attr-defined]
    except (AttributeError, TypeError, ValueError):
        return ()

def _safe_new_module_entries(
    items: tuple[tuple[object, object], ...],
    original_snapshot: dict[str, object],
    excluded_prefixes: set[str],
) -> dict[str, ModuleType]:
    entries: dict[str, ModuleType] = {}
    for name, module in items:
        if (not isinstance(name, str) or name in original_snapshot or _under_prefix(name, excluded_prefixes)
                or not isinstance(module, ModuleType) or getattr(module, "__name__", None) != name): continue
        entries[name] = module
    return entries
def _managed_namespace_entries(
    package_name: str,
    root: Path,
    items: tuple[tuple[object, object], ...],
) -> dict[str, ModuleType]:
    owner = _MANAGED_NAMESPACES.get(package_name)
    if owner is None or owner.root != root:
        return {}
    entries: dict[str, ModuleType] = {}
    for name, module in items:
        if not isinstance(name, str) or not isinstance(module, ModuleType): continue
        if name == package_name:
            if module is owner.package: entries[name] = module
            continue
        if not name.startswith(package_name + "."): continue
        if getattr(module, "__name__", None) != name: continue
        try:
            module_file = getattr(module, "__file__", None)
            paths = _module_paths(module)
            if module_file: _inside(root, Path(str(module_file)), "managed isolated module")
            for path in paths: _inside(root, Path(path), "managed isolated package")
            if not module_file and not paths: continue
        except (OSError, TypeError, ValueError):
            continue
        entries[name] = module
    return entries
def _restore_host_state(
    original_modules: object,
    original_snapshot: dict[str, object],
    *,
    alias_names: set[str],
    package_name: str,
    saved_aliases: dict[str, ModuleType | None],
    root: Path,
) -> bool:
    current_modules = sys.modules
    current_items = _mapping_items(current_modules)
    excluded_prefixes = set(alias_names) | {package_name}
    host_corrupted = current_modules is not original_modules
    if not host_corrupted:
        for name, expected in original_snapshot.items():
            if _under_prefix(name, excluded_prefixes):
                continue
            try:
                actual = original_modules.get(name, _MISSING)  # type: ignore[attr-defined]
            except (AttributeError, TypeError):
                actual = _MISSING
            if actual is not expected:
                host_corrupted = True
                break
    if host_corrupted:
        original_items = _mapping_items(original_modules)
        new_entries = _safe_new_module_entries(
            current_items + original_items,
            original_snapshot,
            excluded_prefixes,
        )
        managed_entries = _managed_namespace_entries(
            package_name, root, current_items + original_items
        )
        sys.modules = original_modules  # type: ignore[assignment]
        original_modules.clear()  # type: ignore[attr-defined]
        original_modules.update(original_snapshot)  # type: ignore[attr-defined]
        original_modules.update(new_entries)  # type: ignore[attr-defined]
        original_modules.update(managed_entries)  # type: ignore[attr-defined]
    else:
        sys.modules = original_modules  # type: ignore[assignment]
    _restore_module_prefixes(alias_names, saved_aliases)
    return host_corrupted
def _bind_aliases(
    root: Path, package_directory: str, package: ModuleType
) -> list[_ManagedNamespace]:
    managed_aliases: list[_ManagedNamespace] = []
    try:
        sys.modules[package_directory] = package
        target_alias = _ManagedNamespace(
            package=package,
            root=root,
            package_directory=package_directory,
            prefix=package_directory,
            namespace_prefix=f"canonical:{package_directory}",
            canonical=True,
            owner_thread=threading.get_ident(),
        )
        managed_aliases.append(target_alias)
        _register_finder_state(target_alias)
        deferred: list[ModuleType] = []
        for sibling in ("scripts", "shared_data"):
            if sibling == package_directory:
                continue
            sibling_package = _load_sibling_package(root, sibling, execute=False)
            if sibling_package is None:
                sibling_package = _namespace_package(sibling, root, blocker=True)
            sibling_alias = _ManagedNamespace(
                package=sibling_package,
                root=root,
                package_directory=sibling,
                prefix=sibling,
                namespace_prefix=f"canonical:{sibling}",
                canonical=True,
                owner_thread=threading.get_ident(),
            )
            managed_aliases.append(sibling_alias)
            _register_finder_state(sibling_alias)
            if getattr(getattr(sibling_package, "__spec__", None), "loader", None):
                deferred.append(sibling_package)
        for sibling_package in deferred:
            _execute_package(sibling_package, sibling_package.__spec__)
        return managed_aliases
    except BaseException:
        _release_aliases(managed_aliases)
        raise
def _release_aliases(managed_aliases: list[_ManagedNamespace]) -> None:
    for state in reversed(managed_aliases):
        _release_finder_state(state)

def _load_uncached(
    root: Path,
    *,
    package_directory: str,
    module_leaf: str,
    namespace_prefix: str,
    owner_key: tuple[Path, str, str, str] | None = None,
) -> ModuleType:
    parts = _module_parts(module_leaf)
    package_dir = _inside(root, root / package_directory, "shared package")
    module_path = _inside(
        root,
        package_dir.joinpath(*parts).with_suffix(".py"),
        "shared module",
    )
    if not module_path.is_file():
        raise ValueError(f"shared module missing: {module_path}")
    validate_isolated_import_policy(root, package_directory, module_path)
    package_name = _unique_package_name(root, package_directory, namespace_prefix)
    module_name = f"{package_name}.{module_leaf}"
    with _IMPORT_LOCK:
        original_modules = sys.modules
        try:
            original_modules_snapshot = dict(original_modules)
        except (TypeError, ValueError, RuntimeError) as error:
            raise ValueError("sys.modules host mapping unavailable") from error
        original_path = sys.path
        original_path_values = list(original_path)
        original_meta_path = sys.meta_path
        original_meta_path_values = _meta_items(original_meta_path)
        alias_names = _alias_names(root, package_directory)
        saved_aliases = {
            name: original_modules_snapshot.get(name)
            for name in tuple(original_modules_snapshot)
            if any(name == alias or name.startswith(alias + ".") for alias in alias_names)
        }
        package_valid = _valid_custom_prefix(package_name, root, package_directory)
        preserved_custom = _snapshot_valid_custom(
            package_name, root, package_directory
        ) if package_valid else {}
        if not package_valid:
            _purge_module_prefix(package_name)
            _unregister_unique_namespace(package_name)
        _purge_module_prefix(module_name)
        for alias in alias_names:
            _purge_module_prefix(alias)
        loaded_module: ModuleType | None = None
        operation_error: BaseException | None = None
        namespace_state: _ManagedNamespace | None = None
        namespace_created = not package_valid
        managed_aliases: list[_ManagedNamespace] = []
        host_corrupted = False
        cleanup_error: BaseException | None = None
        try:
            try:
                if package_valid:
                    package = sys.modules[package_name]
                    package_spec = None
                else:
                    package, package_spec = _prepare_package(
                        root, package_directory, package_name
                    )
                namespace_state, namespace_created = _register_unique_namespace(
                    package_name,
                    root,
                    package_directory,
                    namespace_prefix,
                    package,
                )
                if owner_key is not None:
                    namespace_state.owner_keys.add(owner_key)
                # Bind canonical aliases before *any* trusted package initializer
                # runs, so absolute imports cannot resolve an external same-name
                # package from the caller's interpreter environment.
                managed_aliases = _bind_aliases(root, package_directory, package)
                _execute_package(package, package_spec)
                _validate_aliases(alias_names, root)
                _prepare_nested_parents(root, package_dir, package_name, parts[:-1])
                module_spec = _source_spec(module_name, root, module_path)
                if module_spec is None or module_spec.loader is None:
                    raise ValueError(f"shared module cannot be loaded: {module_path}")
                module = importlib.util.module_from_spec(module_spec)
                sys.modules[module_name] = module
                module_spec.loader.exec_module(module)
                _validate_prefix(package_name, root, "isolated package", check_names=True)
                _validate_aliases(alias_names, root)
                if sys.modules.get(package_name) is not package:
                    raise ValueError("isolated package ownership changed during import")
                if not _valid_module(
                    module,
                    root=root,
                    package_name=package_name,
                    package_directory=package_directory,
                    module_name=module_name,
                    module_path=module_path,
                ):
                    raise ValueError(f"loaded module escaped trusted path: {module_path}")
                loaded_module = module
            except BaseException as error:
                operation_error = error
        except BaseException:
            raise
        try:
            host_corrupted = _restore_host_state(
                original_modules,
                original_modules_snapshot,
                alias_names=alias_names,
                package_name=package_name,
                saved_aliases=saved_aliases,
                root=root,
            )
        except BaseException as error:
            cleanup_error = error
            host_corrupted = True
            try:
                sys.modules = original_modules
                original_modules.clear()  # type: ignore[attr-defined]
                original_modules.update(original_modules_snapshot)  # type: ignore[attr-defined]
            except BaseException:
                pass
        try:
            _release_aliases(managed_aliases)
        except BaseException as error:
            cleanup_error = cleanup_error or error
        try:
            sys.__dict__["path"] = original_path
            original_path[:] = original_path_values
        except BaseException as error:
            cleanup_error = cleanup_error or error
        if host_corrupted:
            for key in tuple(_CACHE):
                if _cache_package_name(key) == package_name:
                    _CACHE.pop(key, None)
            current_state = _MANAGED_NAMESPACES.get(package_name)
            if current_state is namespace_state:
                current_state.owner_keys.clear()
                _purge_module_prefix(package_name)
                _unregister_unique_namespace(package_name, current_state)
        try:
            _restore_meta_path(original_meta_path, original_meta_path_values)
        except BaseException as error:
            cleanup_error = cleanup_error or error
        if operation_error is not None and not host_corrupted:
            if namespace_state is not None and owner_key is not None:
                namespace_state.owner_keys.discard(owner_key)
            if package_valid:
                _restore_custom_snapshot(package_name, preserved_custom)
            elif namespace_created:
                _purge_module_prefix(package_name)
                _unregister_unique_namespace(package_name, namespace_state)
        if host_corrupted:
            raise ValueError("sys.modules host mapping corrupted") from operation_error
        if operation_error is not None:
            raise operation_error
        if cleanup_error is not None:
            raise ValueError("isolated loader cleanup failed") from cleanup_error
        if loaded_module is None:
            raise ValueError("isolated module load did not complete")
        return loaded_module
def _request_details(
    package_root: Path,
    *,
    package_directory: str,
    module_leaf: str,
    namespace_prefix: str,
) -> tuple[Path, Path, str, str]:
    if not _SAFE_NAME.fullmatch(package_directory):
        raise ValueError(f"unsafe package_directory: {package_directory!r}")
    parts = _module_parts(module_leaf)
    if not _SAFE_NAME.fullmatch(namespace_prefix):
        raise ValueError(f"unsafe namespace_prefix: {namespace_prefix!r}")
    root = Path(package_root).resolve()
    if not root.is_dir():
        raise ValueError(f"shared package root missing: {root}")
    package_dir = _inside(root, root / package_directory, "shared package")
    module_path = _inside(
        root,
        package_dir.joinpath(*parts).with_suffix(".py"),
        "shared module",
    )
    if not module_path.is_file():
        raise ValueError(f"shared module missing: {module_path}")
    return (
        root,
        module_path,
        _unique_package_name(root, package_directory, namespace_prefix),
        package_directory,
    )
def _cache_key(
    root: Path, package_directory: str, module_leaf: str, namespace_prefix: str
) -> tuple[Path, str, str, str]:
    return root, package_directory, module_leaf, namespace_prefix
def _cache_package_name(key: tuple[Path, str, str, str]) -> str:
    root, package_directory, _module_leaf, namespace_prefix = key
    return _unique_package_name(root, package_directory, namespace_prefix)
def _drop_cache_key(key: tuple[Path, str, str, str]) -> None:
    _CACHE.pop(key, None)
    package_name = _cache_package_name(key)
    state = _MANAGED_NAMESPACES.get(package_name)
    if state is None:
        return
    state.owner_keys.discard(key)
    module_name = f"{package_name}.{key[2]}"
    _purge_module_prefix(module_name)
    if not state.owner_keys:
        _purge_module_prefix(package_name)
        _unregister_unique_namespace(package_name, state)
def _drop_cache_namespace(package_name: str) -> None:
    for key in tuple(_CACHE):
        if _cache_package_name(key) == package_name:
            _drop_cache_key(key)
def _cached_load(
    root: Path,
    package_directory: str,
    module_leaf: str,
    namespace_prefix: str,
) -> ModuleType:
    global _CACHE_HITS, _CACHE_MISSES
    key = _cache_key(root, package_directory, module_leaf, namespace_prefix)
    module = _CACHE.get(key)
    if module is not None:
        _CACHE_HITS += 1
        return module
    _CACHE_MISSES += 1
    module = _load_uncached(
        root,
        package_directory=package_directory,
        module_leaf=module_leaf,
        namespace_prefix=namespace_prefix,
        owner_key=key,
    )
    _CACHE[key] = module
    state = _MANAGED_NAMESPACES.get(_cache_package_name(key))
    if state is not None:
        state.owner_keys.add(key)
    return module
def _cache_info() -> _CacheInfo:
    return _CacheInfo(_CACHE_HITS, _CACHE_MISSES, _CACHE_MAXSIZE, len(_CACHE))
def _clear_loader_cache() -> None:
    global _CACHE_HITS, _CACHE_MISSES
    with _IMPORT_LOCK:
        _CACHE.clear()
        states = tuple(_MANAGED_NAMESPACES.items())
        for package_name, state in states:
            _purge_module_prefix(package_name)
            state.owner_keys.clear()
            _unregister_unique_namespace(package_name, state)
        for stack in tuple(_FINDER_PREFIXES.values()):
            for state in tuple(stack):
                _release_finder_state(state)
        _CACHE_HITS = 0
        _CACHE_MISSES = 0
def load_isolated_package_module(
    package_root: Path,
    *,
    package_directory: str,
    module_leaf: str,
    namespace_prefix: str,
) -> ModuleType:
    """Import one fixed module while isolating aliases and validating provenance."""
    root, module_path, package_name, package_directory = _request_details(
        package_root,
        package_directory=package_directory,
        module_leaf=module_leaf,
        namespace_prefix=namespace_prefix,
    )
    module_name = f"{package_name}.{module_leaf}"
    key = _cache_key(root, package_directory, module_leaf, namespace_prefix)
    with _IMPORT_LOCK:
        module = _cached_load(root, package_directory, module_leaf, namespace_prefix)
        isolated_ok = _valid_module(
            module,
            root=root,
            package_name=package_name,
            package_directory=package_directory,
            module_name=module_name,
            module_path=module_path,
        )
        # Canonical aliases are restored to the caller after every uncached
        # import and may legitimately belong to a different trusted root (or
        # to an external caller).  A valid cached module retains its own
        # unique package namespace for relative imports, so never consume or
        # overwrite those ambient aliases on a cache hit.
        if isolated_ok:
            return module
        _drop_cache_key(key)
        module = _cached_load(root, package_directory, module_leaf, namespace_prefix)
        if not _valid_module(
            module,
            root=root,
            package_name=package_name,
            package_directory=package_directory,
            module_name=module_name,
            module_path=module_path,
        ):
            _drop_cache_namespace(package_name)
            raise ValueError("isolated module provenance invalid after reload")
        return module
# Preserve the cache inspection/clear hooks that the original decorated public
# function exposed, while keeping the validation wrapper above in control.
load_isolated_package_module.cache_clear = _clear_loader_cache  # type: ignore[attr-defined]
load_isolated_package_module.cache_info = _cache_info  # type: ignore[attr-defined]
__all__ = ["load_isolated_package_module"]
