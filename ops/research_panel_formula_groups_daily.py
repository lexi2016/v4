"""Build the approved formula groups from the current A-share daily product."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import stat
import sys
import tempfile
from types import SimpleNamespace
from urllib.parse import quote
from urllib.request import urlopen


FLAGS = {
    "RESEARCH_ONLY": True,
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}
FORMULA_SHA256 = {
    "b23_entry": "7834657819023edfbe5c77628e478c0fca996e728689b7dcc609f3a8c3254581",
    "pb2_confirm": "f7b5f5a543325c2e681671ca23c4039cb9cf6749931eb7c262b36e77d38a2307",
}
ASSET_SHA256 = {
    "project.py": "7e7ea6942601e8882f78806ff7e75ea9a26213936340cd6787f697020aae526c",
    "resolve_names.py": "ba3612dcb7b5f0479cac903cbea36024c72027a14ad0df14779d0dea54dc79c4",
    "prepare-formula-group-artifact.py": "8ed647524c70ae2b7f57bde27bbed91e7c84c3864b33d1cbfe1ae589a48f003e",
    "publish-formula-group-artifact.py": "79d0e232d82ecab6b1003e95a537047d7df8bd3e65ca92c4a408d3a65775e0b1",
}
PARTS = Path(__file__).with_name("_formula_groups_daily_parts")
PROJECT_PATH = PARTS / "project.py"
NAMES_PATH = PARTS / "resolve_names.py"
PUBLISH_PATH = PARTS / "publish-formula-group-artifact.py"
FORMULA_ASSET_ROOT = PARTS / "formula_assets"
SCHEDULER_PLIST = Path.home() / "Library/LaunchAgents/com.lexi.v4.scheduler.plist"
API_PLIST = Path.home() / "Library/LaunchAgents/com.lexi.v4.api.plist"
ORIGIN = "http://127.0.0.1:8873"


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _absolute(path: Path) -> Path:
    _require(path.is_absolute() and path.resolve() == path, "FORMULA_PATH_NOT_CANONICAL")
    return path


def _load_plist(path: Path) -> dict:
    _require(path.is_file() and not path.is_symlink(), "FORMULA_LAUNCH_BINDING_MISSING")
    value = plistlib.loads(path.read_bytes())
    _require(isinstance(value, dict), "FORMULA_LAUNCH_BINDING_INVALID")
    return value


def _checked_assets(asset_root: Path) -> dict[str, Path]:
    _require(asset_root.is_absolute() and asset_root.resolve() == asset_root,
             "FORMULA_ASSET_ROOT_NOT_CANONICAL")
    formulas = {
        "b23_entry": asset_root / "b23_entry.txt",
        "pb2_confirm": asset_root / "pb2_confirm.txt",
    }
    for slug, path in formulas.items():
        _absolute(path)
        _require(path.is_file() and not path.is_symlink(), "FORMULA_ASSET_MISSING:" + slug)
        _require(_sha(path) == FORMULA_SHA256[slug], "FORMULA_ASSET_SHA_DRIFT:" + slug)
    return formulas


def _api_binding() -> tuple[Path, str, dict]:
    env = _load_plist(API_PLIST).get("EnvironmentVariables", {})
    path = _absolute(Path(env["V4_WORKBENCH_HOST_BINDING"]))
    expected = env["V4_WORKBENCH_HOST_BINDING_SHA256"]
    raw = path.read_bytes()
    _require(hashlib.sha256(raw).hexdigest() == expected, "FORMULA_HOST_BINDING_SHA_DRIFT")
    binding = json.loads(raw)
    _require(binding.get("schema") == "V4_MAC_WORKBENCH_BINDING_V1"
             and binding.get("candidate_group_formula_sha256") == FORMULA_SHA256
             and isinstance(binding.get("candidate_group_overrides"), dict)
             and all(binding.get(key) is value for key, value in FLAGS.items()),
             "FORMULA_HOST_BINDING_INVALID")
    _absolute(Path(binding["formula_groups_root"]))
    _require(path.read_bytes() == raw, "FORMULA_HOST_BINDING_MOVED")
    return path, expected, binding


def _api_json(url: str) -> dict:
    with urlopen(url, timeout=25) as response:
        value = json.load(response)
    _require(isinstance(value, dict), "FORMULA_API_RESPONSE_INVALID")
    return value


def _source_identity(day: str) -> dict:
    import datetime

    trade_date = datetime.datetime.strptime(day, "%Y%m%d").date()
    source_date = trade_date.isoformat()
    encoded_date = quote(source_date, safe="-")
    product = _api_json(f"{ORIGIN}/api/v4/research/a-share/daily-product?date={day}")
    workflow = _api_json(f"{ORIGIN}/api/v4/research/workbench/workflow-contract?source_date={encoded_date}")
    _require(product.get("data_date") == day
             and product.get("status") in {"READY", "PARTIAL_WITH_ROWS"},
             "FORMULA_DAILY_PRODUCT_NOT_READY")
    observation = workflow.get("observation_date")
    _require(workflow.get("source_date") in {None, source_date}
             and isinstance(observation, str) and observation > source_date,
             "FORMULA_WORKFLOW_DATE_INVALID")
    product_identity = product.get("source_identity") or {}
    manifest = product.get("manifest")
    _require(isinstance(manifest, dict) and isinstance(manifest.get("path"), str)
             and isinstance(manifest.get("sha256"), str), "FORMULA_CANONICAL_MANIFEST_MISSING")
    manifest_path = _absolute(Path(manifest["path"]))
    _require(_sha(manifest_path) == manifest["sha256"], "FORMULA_CANONICAL_MANIFEST_SHA_DRIFT")
    _require(product.get("source_generation") and product_identity.get("input_sha256")
             and product_identity.get("selector_artifact_sha256"), "FORMULA_PRODUCT_IDENTITY_MISSING")
    return {
        "product": product,
        "workflow": workflow,
        "source_date": source_date,
        "observation_date": observation,
        "generation": product["source_generation"],
        "input_sha256": product_identity["input_sha256"],
        "selector_sha256": product_identity["selector_artifact_sha256"],
        "numeric_manifest": manifest,
    }


def _current_pointer(root: Path, source: dict) -> tuple[str, dict | None]:
    day_root = _absolute(root / source["source_date"])
    latest = day_root / "latest.json"
    _require(not latest.is_symlink(), "FORMULA_CURRENT_POINTER_INVALID")
    latest = _absolute(latest)
    if not latest.exists():
        return "ABSENT", None
    _require(latest.is_file() and not latest.is_symlink(), "FORMULA_CURRENT_POINTER_INVALID")
    raw = latest.read_bytes()
    before = hashlib.sha256(raw).hexdigest()
    pointer = json.loads(raw)
    _require(pointer.get("schema") == "V4_WORKBENCH_MODULE_COMMIT_V1"
             and pointer.get("module") == "formula_groups"
             and pointer.get("date") == source["source_date"]
             and all(pointer.get(key) is value for key, value in FLAGS.items()),
             "FORMULA_CURRENT_POINTER_INVALID")
    artifact_ref, receipt_ref = pointer.get("artifact"), pointer.get("receipt")
    _require(isinstance(artifact_ref, dict) and isinstance(receipt_ref, dict),
             "FORMULA_CURRENT_POINTER_REFS_INVALID")
    artifact_path = _absolute(Path(artifact_ref["path"]))
    receipt_path = _absolute(Path(receipt_ref["path"]))
    _require(artifact_path.is_relative_to(day_root / "artifacts")
             and receipt_path.is_relative_to(day_root / "receipts"),
             "FORMULA_CURRENT_POINTER_PATH_INVALID")
    _require(_sha(artifact_path) == artifact_ref["sha256"]
             and _sha(receipt_path) == receipt_ref["sha256"], "FORMULA_CURRENT_ARTIFACT_DRIFT")
    artifact = json.loads(artifact_path.read_bytes())
    receipt = json.loads(receipt_path.read_bytes())
    _require(receipt.get("status") == "COMMITTED" and receipt.get("artifact") == artifact_ref
             and receipt.get("source_date") == source["source_date"]
             and receipt.get("generation") == artifact.get("generation")
             and receipt.get("numeric_manifest") == artifact.get("numeric_manifest")
             and all(receipt.get(key) is value for key, value in FLAGS.items()),
             "FORMULA_CURRENT_RECEIPT_INVALID")
    _require(artifact.get("schema") == "V4_WORKBENCH_FORMULA_GROUP_OVERRIDE_V1"
             and all(artifact.get(key) is value for key, value in FLAGS.items())
             and artifact.get("formula_sha256") == FORMULA_SHA256,
             "FORMULA_CURRENT_ARTIFACT_INVALID")
    if (artifact.get("source_date") == source["source_date"]
            and artifact.get("observation_date") == source["observation_date"]
            and artifact.get("generation") == source["generation"]
            and artifact.get("input_sha256") == source["input_sha256"]
            and artifact.get("numeric_manifest") == source["numeric_manifest"]
            and artifact.get("selector_sha256") == source["selector_sha256"]):
        return before, {"pointer": str(latest), "artifact": artifact_ref, "receipt": receipt_ref}
    return before, None


def _available_memory_bytes() -> int | None:
    try:
        return int(os.sysconf("SC_AVPHYS_PAGES")) * int(os.sysconf("SC_PAGE_SIZE"))
    except (AttributeError, OSError, ValueError):
        return None


def choose_workers(cpu_count: int | None = None, available_bytes: int | None = None) -> int:
    """Bound workers by live CPU and memory while retaining foreground headroom."""
    cpus = cpu_count or os.cpu_count() or 1
    by_cpu = max(1, cpus - 2)
    available = _available_memory_bytes() if available_bytes is None else available_bytes
    by_memory = (min(4, by_cpu) if available is None else
                 max(1, int((max(0, available) * 0.65) // (1.5 * 1024 ** 3))))
    return min(14, by_cpu, by_memory)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    _require(spec is not None and spec.loader is not None, "FORMULA_CODE_ASSET_LOAD_FAILED:" + path.name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        if sys.modules.get(name) is module:
            sys.modules.pop(name, None)
        raise
    return module


def _setup_formula_worker(programs: dict, day: int) -> None:
    """Spawn-safe initializer for the exact pinned project module."""
    import importlib

    project = importlib.import_module("project")
    module_path = Path(project.__file__).resolve()
    _require(module_path == PROJECT_PATH.resolve()
             and _sha(module_path) == ASSET_SHA256["project.py"],
             "FORMULA_SPAWN_PROJECT_MODULE_DRIFT")
    project.DATE = int(day)
    project.PROGRAMS = programs


def _run_projection(day: str, source: dict, scheduler_env: dict, formula_assets: dict,
                    stage: Path, workers: int) -> Path:
    for name, expected in ASSET_SHA256.items():
        path = PARTS / name
        _require(_sha(path) == expected, "FORMULA_CODE_ASSET_SHA_DRIFT:" + name)
    previous_project = sys.modules.get("project")
    previous_path = list(sys.path)
    project = None
    previous_argv = sys.argv
    thread_env = ("VECLIB_MAXIMUM_THREADS", "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS")
    previous_thread_env = {key: os.environ.get(key) for key in thread_env}
    try:
        os.environ.update({key: "1" for key in thread_env})
        sys.path[:] = [str(PARTS), *(path for path in sys.path if path != str(PARTS))]
        project = _load_module("project", PROJECT_PATH)
        # resolve_names imports the project module by its historical import name.
        project.OUT = stage
        project.DATE = int(day)
        project.MAIN = _absolute(Path(scheduler_env["V4_APP_ROOT"]))
        manifest = _absolute(Path(scheduler_env["V4_RELEASE_MANIFEST_PATH"]))
        _require(_sha(manifest) == scheduler_env["V4_RELEASE_MANIFEST_SHA256"],
                 "FORMULA_MAIN_RELEASE_MANIFEST_SHA_DRIFT")
        project.MAIN_MANIFEST = manifest
        project.FORMULAS = {
            slug: (formula_assets[slug], expected)
            for slug, expected in FORMULA_SHA256.items()
        }

        def workbench_identity(context):
            identity = source
            _require(context.generation == identity["generation"]
                     and context.identity.get("input_sha256") == identity["input_sha256"]
                     and context.identity.get("selector_artifact_sha256") == identity["selector_sha256"],
                     "FORMULA_SOURCE_CONTEXT_MISMATCH")
            return identity["numeric_manifest"]

        project.workbench_identity = workbench_identity
        original_configure = project.configure

        def configure_with_pinned_spawn_path():
            data = original_configure()
            sys.path[:] = [str(PARTS), *(path for path in sys.path if path != str(PARTS))]
            return data

        project.configure = configure_with_pinned_spawn_path
        from functools import partial
        project.setup_worker = partial(_setup_formula_worker, day=int(day))
        old_save_json, old_save_csv = project.save_json, project.save_csv

        def save_json(path, value):
            if Path(path).name == "RESULT.json":
                value["observation_date"] = source["observation_date"]
                value["date_adapter_sha256"] = _sha(Path(__file__))
            old_save_json(path, value)

        def save_csv(path, rows):
            for row in rows:
                if "source_observation_date" in row:
                    row["source_observation_date"] = source["observation_date"]
            old_save_csv(path, rows)

        project.save_json = save_json
        project.save_csv = save_csv
        sys.argv = [str(PROJECT_PATH), "--canary"]
        project.main()
        sys.argv = [str(PROJECT_PATH), "--workers", str(workers)]
        project.main()
        name_module = _load_module("v4_formula_groups_daily_resolve_names", NAMES_PATH)
        name_module.main()
        _require((stage / "RESULT.json").is_file() and (stage / "NAME_BINDING.json").is_file()
                 and (stage / "CANDIDATES_NAMED.csv").is_file(), "FORMULA_PROJECTION_OUTPUT_MISSING")
        return stage
    finally:
        sys.argv = previous_argv
        for key, value in previous_thread_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        if previous_project is None:
            if project is not None and sys.modules.get("project") is project:
                sys.modules.pop("project", None)
        else:
            sys.modules["project"] = previous_project
        sys.path[:] = previous_path


def _inherited_owner_fd(day: str) -> tuple[Path, int]:
    from ops.sync_stock_history_completion import DEFAULT_OWNER_LOCK, _inherited_owner_duplicate

    path = _absolute(Path(DEFAULT_OWNER_LOCK))
    lock = os.stat(path, follow_symlinks=False)
    _require(stat.S_ISREG(lock.st_mode), "FORMULA_OWNER_LOCK_NOT_REGULAR")
    shared = {"path": str(path), "device": lock.st_dev, "inode": lock.st_ino}
    fd = _inherited_owner_duplicate(shared, day)
    _require(fd is not None, "FORMULA_INHERITED_A_LONG_REQUIRED")
    return path, fd


def _run_publisher(stage: Path, binding_path: Path, binding_sha: str, owner_lock: Path,
                   owner_fd: int, expected_current: str) -> dict:
    publisher = _load_module("v4_formula_groups_daily_publisher", PUBLISH_PATH)
    args = SimpleNamespace(batch=stage, binding=binding_path, binding_sha256=binding_sha,
                           owner_lock=owner_lock, owner_fd=owner_fd,
                           expected_current=expected_current, origin=ORIGIN)
    return publisher.publish(args)


def _complete_workbench_supplements(day: str, scheduler_env: dict, binding: dict,
                                   committed: dict, source: dict) -> dict:
    """Run exact-roster supplements only after the dated group is committed."""
    try:
        data_root = _absolute(Path(scheduler_env['V4_RESEARCH_PANEL_A_DATA_ROOT']))
        product_base = _absolute(Path(scheduler_env['V4_A_SHARE_DAILY_PRODUCT_ROOT']))
        product_root = _absolute(product_base / 'daily_products' / 'a_share')
        _require((product_root / 'index.json').is_file()
                 and not (product_root / 'index.json').is_symlink(),
                 'FORMULA_SUPPLEMENT_EXPLICIT_PRODUCT_ROOT_NOT_READY')
        from ops.research_panel_daily_product import SourceContext
        from ops._formula_groups_daily_parts.workbench_supplements import complete

        context = SourceContext(data_root, int(day))
        # The A producer uses an explicitly bound product root; SourceContext's
        # legacy default is only the data-root sibling and is not authoritative.
        context.root = product_root
        if (context.generation != source['generation']
                or context.identity.get('input_sha256') != source['input_sha256']
                or context.identity.get('selector_artifact_sha256') != source['selector_sha256']):
            raise ValueError('FORMULA_SUPPLEMENT_SOURCE_CONTEXT_MISMATCH')
        return complete(context, Path(binding['formula_groups_root']), committed['artifact'],
                        committed['receipt'])
    except Exception as error:
        return dict(status='CANNOT_CONFIRM', reason=type(error).__name__ + ':' + str(error)[:240],
                    data_date=day, **FLAGS)


def complete_daily_formula_groups(data_date: str | int) -> dict:
    """Publish date-scoped groups, retaining daily/derivative outcome on failures."""
    day = str(data_date)
    result = {"schema": "V4_FORMULA_GROUP_DAILY_RUN_V1", "data_date": day, **FLAGS}
    owner_fd = None
    try:
        _require(len(day) == 8 and day.isdigit(), "FORMULA_DATE_INVALID")
        scheduler_env = _load_plist(SCHEDULER_PLIST).get("EnvironmentVariables", {})
        binding_path, binding_sha, binding = _api_binding()
        source = _source_identity(day)
        result.update(source_date=day, observation_date=source["observation_date"],
                      source_generation=source["generation"],
                      numeric_manifest=source["numeric_manifest"])
        root = _absolute(Path(binding["formula_groups_root"]))
        expected_current, committed = _current_pointer(root, source)
        owner_lock, owner_fd = _inherited_owner_fd(day)
        if committed is not None:
            supplements = _complete_workbench_supplements(day, scheduler_env, binding, committed, source)
            return {**result, "status": "ALREADY_COMMITTED", **committed,
                    "workbench_supplements": supplements}

        formula_assets = _checked_assets(FORMULA_ASSET_ROOT)
        with tempfile.TemporaryDirectory(prefix="v4-formula-groups-") as temporary:
            stage = Path(temporary)
            workers = choose_workers()
            _run_projection(day, source, scheduler_env, formula_assets, stage, workers)
            published = _run_publisher(stage, binding_path, binding_sha, owner_lock,
                                        owner_fd, expected_current)
        status = published.get("status")
        _require(status in {"COMMITTED", "ALREADY_COMMITTED"}, "FORMULA_PUBLICATION_STATUS_INVALID")
        committed_result = published if isinstance(published.get('artifact'), dict) else committed
        supplements = _complete_workbench_supplements(day, scheduler_env, binding,
            committed_result, source) if committed_result else dict(status='CANNOT_CONFIRM',
                reason='FORMULA_COMMIT_REFERENCES_MISSING', data_date=day, **FLAGS)
        return {**result, **published, "workers": workers,
                "workbench_supplements": supplements}
    except Exception as error:
        return {**result, "status": "CANNOT_CONFIRM",
                "reason": f"{type(error).__name__}:{str(error)[:240]}"}
    finally:
        if owner_fd is not None:
            os.close(owner_fd)


__all__ = ["complete_daily_formula_groups", "choose_workers"]
