"""stage_center.live_collectors: shared_module_loading (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __scoped_process_runner_body(_v4_scope, /, shared_root, process_runner):
    """Bind child imports to the explicit shared-data package root.

    The legacy probe is a ``python -m scripts...`` child.  launchd can invoke
    the parent from an arbitrary working directory, so relying on inherited
    cwd/PYTHONPATH produces the observed ``ModuleNotFoundError``.  This
    wrapper changes only the child invocation; it never mutates ``os.environ``
    in the parent process.
    """
    root = _v4_global(_v4_scope, 'str')(shared_root.resolve())

    def run(command: Any, **kwargs: Any) -> Any:
        child_env = _v4_global(_v4_scope, 'dict')(_v4_global(_v4_scope, 'os').environ)
        supplied_env = kwargs.get("env")
        if _v4_global(_v4_scope, 'isinstance')(supplied_env, _v4_global(_v4_scope, 'Mapping')):
            child_env.update({_v4_global(_v4_scope, 'str')(key): _v4_global(_v4_scope, 'str')(value) for key, value in supplied_env.items()})
        existing = child_env.get("PYTHONPATH", "")
        child_env["PYTHONPATH"] = _v4_global(_v4_scope, 'os').pathsep.join(item for item in (root, existing) if item)
        kwargs["cwd"] = root
        kwargs["env"] = child_env
        return process_runner(command, **kwargs)

    return run


def __load_shared_module_body(_v4_scope, /, shared_root, module_name):
    import importlib
    import sys

    package_root = shared_root
    module_path = package_root.joinpath(*module_name.split("." )).with_suffix(".py")
    if not module_path.is_file():
        raise _v4_global(_v4_scope, 'ValueError')(f"shared collector module missing: {module_path}")
    # The shared bridge uses package-relative imports (``scripts.*``).  Add
    # its explicit root only for the import operation and restore sys.path
    # immediately, so an unrelated local ``scripts`` package cannot leak into
    # later slots.
    original_path = _v4_global(_v4_scope, 'list')(sys.path)
    saved_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "scripts" or name.startswith("scripts.")
    }
    try:
        for name in _v4_global(_v4_scope, 'tuple')(saved_modules):
            sys.modules.pop(name, None)
        sys.path.insert(0, _v4_global(_v4_scope, 'str')(package_root))
        module = importlib.import_module(module_name)
        module_file = _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'getattr')(module, "__file__", ""))).resolve()
        try:
            module_file.relative_to(package_root)
        except _v4_global(_v4_scope, 'ValueError') as error:
            raise _v4_global(_v4_scope, 'ValueError')(f"shared collector resolved outside explicit root: {module_file}") from error
        return module
    finally:
        sys.path[:] = original_path
        for name in _v4_global(_v4_scope, 'tuple')(sys.modules):
            if name == "scripts" or name.startswith("scripts."):
                sys.modules.pop(name, None)
        sys.modules.update(saved_modules)
