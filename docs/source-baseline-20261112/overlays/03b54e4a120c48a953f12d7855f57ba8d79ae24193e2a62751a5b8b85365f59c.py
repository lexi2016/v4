"""V4 routes and in-process legacy aliases share one endpoint invocation."""
from copy import copy
from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.routing import Mount, compile_path


def _routers(router):
    """Support installed FastAPI's lazy includes and older flattened routers."""
    yield router
    for route in tuple(router.routes):
        included = getattr(route, 'original_router', None)
        if included is not None:
            yield from _routers(included)


def install_legacy_aliases(app: FastAPI) -> None:
    """Add old paths to the same APIRoute application, never redirect/retry.

    Alias clones retain the already-built ASGI handler and dependency graph.
    Included routers retain their original include context. Historical records
    and their hashes are untouched. V4 is canonical in OpenAPI.
    """
    routers = list(_routers(app.router))
    occupied = {(route.path, method) for router in routers for route in router.routes
                if isinstance(route, APIRoute) for method in route.methods}
    additions = []
    for router in routers:
        aliases = []
        for route in tuple(router.routes):
            if not isinstance(route, APIRoute) or not route.path.startswith('/api/v4/'):
                continue
            legacy = '/api/v3/' + route.path[len('/api/v4/'):]
            if any((legacy, method) in occupied for method in route.methods):
                raise ValueError('API_LEGACY_ALIAS_COLLISION:' + legacy)
            alias = copy(route)
            alias.path = legacy
            alias.path_regex, alias.path_format, alias.param_convertors = compile_path(legacy)
            alias.include_in_schema = False
            aliases.append(alias)
            occupied.update((legacy, method) for method in route.methods)
        additions.append((router, aliases))
    for router, aliases in additions:
        insertion = next((i for i, route in enumerate(router.routes)
                          if isinstance(route, Mount)), len(router.routes))
        router.routes[insertion:insertion] = aliases
    app.openapi_schema = None
