"""Mount only the isolated manager read projections."""
from pathlib import Path

from starlette.routing import Match

from v4_core.decoupled.manager_history import ManagerHistory, PREFIX, create_manager_app

SNAPSHOT = Path(__file__).resolve().parents[1] / "home/data/r21_pre_d30/manager"
SNAPSHOT_SHA256 = "7d8377756faf893239977a822143160065252d4302a4f25ff8e439f6d292d621"


class ManagerOwnerReads:
    def __init__(self, app, *, snapshot=SNAPSHOT, snapshot_sha256=SNAPSHOT_SHA256):
        self.app = app
        self.manager = create_manager_app(ManagerHistory(Path(snapshot), snapshot_sha256))

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] == "GET" and scope["path"].startswith(PREFIX + "/"):
            if any(route.matches(scope)[0] is Match.FULL for route in self.manager.router.routes):
                return await self.manager(scope, receive, send)
        return await self.app(scope, receive, send)
