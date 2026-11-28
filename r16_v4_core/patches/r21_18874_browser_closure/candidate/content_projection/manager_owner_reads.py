"""Read isolated manager pages from old V4's existing, immutable saved plans."""

from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import sys
from threading import Lock
from types import SimpleNamespace

from fastapi import FastAPI
from starlette.routing import Match

OWNER = Path.home() / "Library/Application Support/com.lexi.v4.local"
RELEASE = OWNER / "candidates/v4-r2-rollup-20261124-api-r1/app"
CONFIG = OWNER / "config/us-industry-observed-api-20261018-r1.json"
SAVED_PLANS = OWNER / "state/manager_workbench/manager_workbench"
SOURCE_FILES = {
    "v4/manager_workbench/api.py": "b02d90adc33c39f569c459014bdeb6977f29a83af40564f574843afc626733aa",
    "v4/manager_workbench/store.py": "6a9dc55b0dbf00daad9fb1200293ea82e3ccb9408c5eec2a84ea1575cf40b48a",
    "v4/manager_workbench/contracts.py": "8c6993f6638e028f5e6d60b5c71604182ce368693ef376520631cd4477ced7a4",
    "v4/manager_workbench/display_read.py": "87c2edf936146fdf4fd2f1e3d4742577272ed47734d883b896bb97d125a50a20",
    "infrastructure/owned_io.py": "6f23204c84d21d11511b9468745f99508d9a2004b02a1485e97e0055d50a47c8",
}
PREFIX = "/api/v4/manager-workbench"
NATIVE_READS = frozenset({
    PREFIX + "/days/{date}/recommendations/{lane}",
    PREFIX + "/stocks/{symbol}",
    PREFIX + "/mapping-catalog",
    PREFIX + "/reviews/{date}",
})


def load_owner():
    for relative, expected in SOURCE_FILES.items():
        path = RELEASE / relative
        if path.resolve(strict=True) != path or sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"R21_MANAGER_NATIVE_READER_UNBOUND:{relative}")
    sys.path.insert(0, str(RELEASE))
    try:
        from infrastructure.owned_io import SafeRoot
        from v4.manager_workbench import api, contracts, display_read, store
    finally:
        sys.path.remove(str(RELEASE))
    for module in (api, contracts, display_read, store, sys.modules[SafeRoot.__module__]):
        path = Path(module.__file__).resolve(strict=True)
        if not path.is_relative_to(RELEASE) or path.relative_to(RELEASE).as_posix() not in SOURCE_FILES:
            raise ValueError("R21_MANAGER_NATIVE_IMPORT_PATH_MISMATCH")
    raw = json.loads(CONFIG.read_bytes())
    shared_root = Path(raw["shared_root"])
    if Path(raw["state_root"]) / "manager_workbench" != SAVED_PLANS or SAVED_PLANS.resolve(strict=True) != SAVED_PLANS:
        raise ValueError("R21_MANAGER_SOURCE_ROOT_MISMATCH")
    return SafeRoot, api, contracts, store, shared_root


def native_app():
    SafeRoot, api, contracts, store, shared_root = load_owner()

    class ExistingPlanStore(store.WorkbenchStore):
        def __init__(self):
            # The production constructor ensures directories. This adapter performs reads only.
            self.root = SAVED_PLANS
            self.io = SafeRoot(self.root)
            self.read_lock = Lock()

        @lru_cache(maxsize=2)
        def read_bound_plan(self, run_id, identity):
            plan = super().read_plan(run_id)
            if self.file_identity(run_id) != identity:
                raise store.StorageConflict("SAVED_PLAN_CHANGED_DURING_READ")
            return plan

        def file_identity(self, run_id):
            path = self._path("snapshots", run_id)
            stat = path.stat()
            return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns

        def read_plan(self, run_id):
            with self.read_lock:
                try:
                    return self.read_bound_plan(run_id, self.file_identity(run_id))
                except FileNotFoundError as exc:
                    raise KeyError("PLAN_NOT_FOUND") from exc

        def get_plan(self, date, phase=None, run_id=None):
            contracts.validate_date(date)
            if run_id:
                return super().get_plan(date, phase, run_id)
            phases = [item.value for item in contracts.Phase if not phase or item.value == phase]
            pointers = [
                (pointer["generated_at"], pointer["run_id"], name, pointer["product_sha256"])
                for name in phases
                if (pointer := self._read(self._path("pointers", date, name), max_bytes=16384))
            ]
            if not pointers:
                return None
            generated_at, selected, selected_phase, product_sha = max(pointers)
            plan = self.read_plan(selected)
            if (plan.context.target_date, plan.context.phase.value, plan.generated_at, plan.product_sha256) != (
                date, selected_phase, generated_at, product_sha
            ):
                raise store.StorageConflict("POINTER_READBACK_MISMATCH")
            return plan

    reader = ExistingPlanStore()
    service = SimpleNamespace(store=reader, config=SimpleNamespace(shared_root=shared_root))
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    owner_router = api.create_router(service)
    mounted = [route for route in owner_router.routes if route.path in NATIVE_READS and route.methods == {"GET"}]
    if {route.path for route in mounted} != NATIVE_READS:
        raise ValueError("R21_MANAGER_NATIVE_ROUTES_MISMATCH")
    app.router.routes.extend(mounted)

    @app.get(PREFIX + "/history")
    def history(date: str):
        def read():
            versions, gaps = reader.list_plan_metadata(date)
            return contracts.envelope(
                "READY" if versions else "NOT_RUN",
                {"date": date, "versions": versions, "version_metadata_gaps": gaps},
            )
        return api._safe_errors(read)

    return app


class ManagerOwnerReads:
    def __init__(self, app):
        self.app = app
        self.manager = native_app()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] == "GET" and scope["path"].startswith(PREFIX + "/"):
            if any(route.matches(scope)[0] is Match.FULL for route in self.manager.router.routes):
                return await self.manager(scope, receive, send)
        return await self.app(scope, receive, send)
