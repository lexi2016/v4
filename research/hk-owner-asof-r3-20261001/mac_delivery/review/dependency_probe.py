"""Record imported module origins for the frozen R3 acceptance carriers."""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = json.loads((ROOT / "assembly_receipt.json").read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("variant", choices=("canonical", "active"))
    args = parser.parse_args()
    variant = args.variant
    app = ROOT / "isolated/canonical" if variant == "canonical" else ROOT / "isolated/active_owner_composed"
    sys.path.insert(0, str(app))

    import contracts.trading_calendar as trading_calendar  # noqa: E402
    import domains.preselection_materializer as materializer  # noqa: E402
    import infrastructure.isolated_package_loader as package_loader  # noqa: E402
    import infrastructure.preselection_pool_store as pool_store  # noqa: E402
    import infrastructure.scheduling.executor_registry as registry  # noqa: E402
    import stage_center.hk_universe_preflight as publisher  # noqa: E402
    import stage_center.runner as stage_runner  # noqa: E402

    package_root = app / "upstreams/v3_shared_data"
    # This loads the real shared reader and its transitive source-only imports,
    # including the existing live universe module, without collecting data.
    reader = materializer._shared_hk_0_2_reader(package_root)
    reader_module = sys.modules[reader.__module__]
    security_master = sys.modules[
        reader_module.read_verified_hk_eligibility_asof.__module__
    ]
    universe_reader = security_master._hk_asof_universe_reader
    modules = [
        publisher,
        stage_runner,
        registry,
        materializer,
        pool_store,
        package_loader,
        trading_calendar,
        reader_module,
    ]
    package_resolved = package_root.resolve()
    for module in tuple(sys.modules.values()):
        filename = getattr(module, "__file__", None)
        if not filename:
            continue
        try:
            path = Path(filename).resolve()
            path.relative_to(package_resolved)
        except (OSError, ValueError):
            continue
        if path.is_file():
            modules.append(module)

    records = []
    seen = set()
    for module in modules:
        path_text = getattr(module, "__file__", None)
        if not path_text:
            continue
        path = Path(path_text).resolve()
        key = (module.__name__, str(path))
        if key in seen or not path.is_file():
            continue
        seen.add(key)
        record = {
            "module": module.__name__,
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        try:
            relative = path.relative_to(app)
            record["relative_path"] = relative.as_posix()
            if variant == "canonical":
                origin = Path("/Users/lexi/Desktop/学习/v4_app") / relative
            elif relative.parts[:2] == ("upstreams", "v3_shared_data"):
                origin = Path(RECEIPT["actual_roots"]["shared_package"]) / Path(*relative.parts[2:])
            elif relative.parts[:2] == ("stage_center", "_runner_parts"):
                origin = Path(RECEIPT["actual_roots"]["stage_app"]) / relative
            else:
                origin = Path(RECEIPT["actual_roots"]["preselection_app"]) / relative
            if origin.is_file():
                record["source_preimage_path"] = str(origin)
                record["source_preimage_sha256"] = hashlib.sha256(origin.read_bytes()).hexdigest()
        except ValueError:
            pass
        records.append(record)

    # The package loader resolves this trusted import through its managed
    # finder, so its function source is authoritative even when the module is
    # intentionally omitted from ordinary sys.modules enumeration.
    universe_path = Path(inspect.getsourcefile(universe_reader)).resolve()
    universe_record = {
        "module": universe_reader.__module__,
        "path": str(universe_path),
        "sha256": hashlib.sha256(universe_path.read_bytes()).hexdigest(),
    }
    relative = universe_path.relative_to(app)
    universe_record["relative_path"] = relative.as_posix()
    if variant == "canonical":
        origin = Path("/Users/lexi/Desktop/学习/v4_app") / relative
    else:
        origin = Path(RECEIPT["actual_roots"]["shared_package"]) / Path(*relative.parts[2:])
    if origin.is_file():
        universe_record["source_preimage_path"] = str(origin)
        universe_record["source_preimage_sha256"] = hashlib.sha256(origin.read_bytes()).hexdigest()
    records.append(universe_record)

    output = {
        "variant": variant,
        "interpreter": sys.executable,
        "python_version": sys.version,
        "app_root": str(app),
        "shared_package_root": str(package_root),
        "shared_reader_function": f"{reader.__module__}.{reader.__name__}",
        "loaded_modules": records,
    }
    output_path = ROOT / "review" / f"{variant}_dependency_receipt.json"
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
