from __future__ import annotations

import importlib
import importlib.metadata
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DISTRIBUTIONS = {
    "numpy": "numpy",
    "pandas": "pandas",
    "pyarrow": "pyarrow",
    "requests": "requests",
}


def test_runtime_dependencies_are_declared_locked_and_loaded_from_candidate() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    declared = {item.split(">", 1)[0].split("<", 1)[0].split("=", 1)[0].lower() for item in project["dependencies"]}
    assert set(RUNTIME_DISTRIBUTIONS).issubset(declared)

    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    application = next(package for package in lock["package"] if package["name"] == project["name"])
    locked_direct = {dependency["name"] for dependency in application["dependencies"]}
    assert set(RUNTIME_DISTRIBUTIONS).issubset(locked_direct)
    locked_packages = {package["name"]: package for package in lock["package"]}
    package_names = set(locked_packages)
    assert set(RUNTIME_DISTRIBUTIONS).issubset(package_names)

    prefix = Path(sys.prefix).resolve()
    modules = {name: importlib.import_module(module) for name, module in RUNTIME_DISTRIBUTIONS.items()}
    versions = {name: importlib.metadata.version(name) for name in RUNTIME_DISTRIBUTIONS}
    locations = {name: Path(module.__file__).resolve() for name, module in modules.items()}
    assert all(path.is_relative_to(prefix) for path in locations.values())
    assert versions == {name: locked_packages[name]["version"] for name in RUNTIME_DISTRIBUTIONS}

    # Exercise the actual eagerly-imported V1.9.2 oracle bundle and the V4
    # request adapter. They must resolve the declared packages from this env.
    bundle = importlib.import_module("upstreams.v3_shared_data.shared_data.v192_oracle_bundle")
    assert bundle.np is modules["numpy"]
    assert bundle.pd is modules["pandas"]
    assert bundle.pa is modules["pyarrow"]
    fuyao = importlib.import_module("domains.research_review_generation.data_core.fuyao_sources")
    assert fuyao.requests is modules["requests"]
