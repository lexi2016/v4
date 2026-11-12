"""Exact historical paths delegate once to their canonical V4 route owner."""
from __future__ import annotations
import json
from pathlib import Path
from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.routing import Mount, Route

CONTRACT = Path(__file__).resolve().parents[1] / 'contracts/v4_legacy_api_aliases.json'


def _routers(router):
    """Source-router inventory retained for callers inspecting direct routes."""
    yield router
    for route in tuple(router.routes):
        included = getattr(route, 'original_router', None)
        if included is not None:
            yield from _routers(included)


def effective_api_routes(app: FastAPI):
    """Yield full paths and the actual cached include dependency context.

    Installed FastAPI keeps prefix composition and include dependencies in
    effective contexts. Calling the existing top-level include owner preserves
    that context without rebuilding or bypassing its request handler.
    """
    for owner in tuple(app.router.routes):
        if isinstance(owner, APIRoute):
            yield owner.path, owner.methods, owner, owner, owner.dependant
        elif callable(getattr(owner, 'effective_route_contexts', None)):
            for context in owner.effective_route_contexts():
                route = context.original_route
                if isinstance(route, APIRoute):
                    yield context.path, context.methods, route, owner, context.dependant


class LegacyAliasRoute(Route):
    def __init__(self, path, methods, *, canonical_route, canonical_owner, dependant):
        super().__init__(path, endpoint=canonical_route.endpoint,
                         methods=sorted(methods), name=canonical_route.name,
                         include_in_schema=False)
        # Starlette ordinarily adds HEAD to GET; retain the original contract exactly.
        self.methods = set(methods)
        self.app = canonical_route.app
        self.dependant = dependant
        self.canonical_route = canonical_route
        self.canonical_owner = canonical_owner

    async def handle(self, scope, receive, send):
        if scope['method'] not in self.methods:
            await super().handle(scope, receive, send)
            return
        canonical_scope = dict(scope)
        canonical_scope['path'] = scope['path'].replace('/api/v3/', '/api/v4/', 1)
        if 'raw_path' in scope:
            canonical_scope['raw_path'] = scope['raw_path'].replace(b'/api/v3/', b'/api/v4/', 1)
        # One in-process owner call; no redirect, retry, body read or second middleware pass.
        await self.canonical_owner.handle(canonical_scope, receive, send)


def install_legacy_aliases(app: FastAPI, *, legacy_routes=None) -> None:
    if legacy_routes is None:
        contract = json.loads(CONTRACT.read_text(encoding='utf-8'))
        if contract.get('schema_version') != 'v4.legacy_api_aliases.v1':
            raise ValueError('API_LEGACY_ALIAS_CONTRACT_INVALID')
        legacy_routes = contract.get('routes')
        if not isinstance(legacy_routes, dict) or len(legacy_routes) != 42:
            raise ValueError('API_LEGACY_ALIAS_CONTRACT_INVALID')
    rows = list(effective_api_routes(app))
    occupied = {(path, method) for path, methods, *_ in rows for method in methods}
    additions = []
    for legacy, requested in legacy_routes.items():
        if (not isinstance(legacy, str) or not legacy.startswith('/api/v3/')
                or not isinstance(requested, (list, tuple, set)) or not requested):
            raise ValueError('API_LEGACY_ALIAS_CONTRACT_INVALID')
        methods = set(requested)
        if not methods <= {'GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS'}:
            raise ValueError('API_LEGACY_ALIAS_CONTRACT_INVALID')
        if any((legacy, method) in occupied for method in methods):
            raise ValueError('API_LEGACY_ALIAS_COLLISION:' + legacy)
        canonical = legacy.replace('/api/v3/', '/api/v4/', 1)
        candidates = [row for row in rows if row[0] == canonical and methods <= row[1]]
        if len(candidates) != 1:
            raise ValueError('API_LEGACY_ALIAS_CANONICAL_MISSING_OR_AMBIGUOUS:' + legacy)
        _, _, route, owner, dependant = candidates[0]
        additions.append(LegacyAliasRoute(legacy, methods, canonical_route=route,
                                         canonical_owner=owner, dependant=dependant))
    insertion = next((i for i, route in enumerate(app.router.routes)
                      if isinstance(route, Mount)), len(app.router.routes))
    app.router.routes[insertion:insertion] = additions
    app.openapi_schema = None
