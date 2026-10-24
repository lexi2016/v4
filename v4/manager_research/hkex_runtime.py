"""Lifecycle binding for the original bounded HKEX source owner only."""
from contextlib import asynccontextmanager
from pathlib import Path

from .hkex_provider import HkexOfficialProvider
from .materials import MaterialStore
from .service import ManagerResearchJobService
from .store import ManagerResearchStore


def create_hkex_service(*, manager_root, security_master_root):
    root = Path(manager_root)
    materials = MaterialStore(root / 'materials')
    provider = HkexOfficialProvider(material_store=materials)
    return ManagerResearchJobService(
        ManagerResearchStore(root), observation_reader=None, source_provider=provider,
        material_store=materials, workspace_security_master_root=security_master_root,
    )


def assemble_hkex_announcements_api(app, *, manager_root, security_master_root, service=None):
    from apps.api.v35_api.hkex_announcements_router import create_hkex_announcements_router

    if getattr(app.state, 'hkex_announcements_service', None) is not None:
        raise RuntimeError('HKEX_ANNOUNCEMENTS_ALREADY_BOUND')
    service = service or create_hkex_service(
        manager_root=manager_root, security_master_root=security_master_root)
    if (service._material_store is None
            or service.source_provider._material_store is not service._material_store):
        service.close()
        raise RuntimeError('HKEX_ORIGINAL_SHARED_STORE_NOT_BOUND')
    app.state.hkex_announcements_service = service
    app.include_router(create_hkex_announcements_router(service))
    previous = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(instance):
        try:
            async with previous(instance):
                yield
        finally:
            service.close()

    app.router.lifespan_context = lifespan
    return service
