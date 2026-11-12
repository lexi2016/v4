"""Optional same-origin research page export, limited to reviewed file hashes.

The allowlist is deployment configuration, never a request parameter. No scan,
directory listing, fallback document root, write, or market producer is used.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
from pathlib import Path, PurePosixPath
import re
import stat

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

_SCHEMA = "research_panel.assets.v1"
_PUBLIC_SUFFIXES = frozenset({
    ".html", ".js", ".mjs", ".css", ".json", ".png", ".jpg", ".jpeg", ".webp",
    ".gif", ".svg", ".ico", ".pdf", ".txt", ".woff", ".woff2",
})


def _valid_relative(value: object) -> bool:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        return False
    if any(ord(character) < 32 for character in value):
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and str(path) == value
        and all(part not in {".", ".."} and not part.startswith(".") for part in path.parts)
        and path.suffix.lower() in _PUBLIC_SUFFIXES
    )


def _read_allowlist(path: Path) -> dict[str, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("RESEARCH_PANEL_ALLOWLIST_UNREADABLE") from error
    if not isinstance(payload, dict) or payload.get("schema_version") != _SCHEMA:
        raise ValueError("RESEARCH_PANEL_ALLOWLIST_SCHEMA_INVALID")
    entries = payload.get("files")
    if not isinstance(entries, list):
        raise ValueError("RESEARCH_PANEL_ALLOWLIST_FILES_INVALID")
    allowed: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("RESEARCH_PANEL_ALLOWLIST_ENTRY_INVALID")
        name, digest = entry.get("path"), entry.get("sha256")
        if not _valid_relative(name) or name in allowed:
            raise ValueError("RESEARCH_PANEL_ALLOWLIST_PATH_INVALID")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError("RESEARCH_PANEL_ALLOWLIST_SHA_INVALID")
        allowed[name] = digest
    if "daily.html" not in allowed and "workbench.html" not in allowed:
        raise ValueError("RESEARCH_PANEL_DAILY_ENTRY_NOT_ALLOWED")
    return allowed


def _read_asset(root: Path, relative: str) -> bytes:
    """Read through directory descriptors; reject symlinks at every hop."""
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory = os.open(root, directory_flags)
    try:
        parts = PurePosixPath(relative).parts
        for component in parts[:-1]:
            child = os.open(component, directory_flags, dir_fd=directory)
            os.close(directory)
            directory = child
        file_descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                  dir_fd=directory)
        with os.fdopen(file_descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise OSError("not a regular file")
            return stream.read()
    finally:
        os.close(directory)


def create_research_panel_router(
    site_root: Path | str, asset_manifest: Path | str,
) -> APIRouter:
    """Serve only reviewed bytes at /research-panel; fail closed on bad config.

    Existing market JSON/images/PDFs are not supplied with the candidate. Local
    integration must explicitly review and add their frozen path/hash entries.
    """
    root = Path(site_root).expanduser()
    if root.is_symlink() or not root.is_dir():
        raise ValueError("RESEARCH_PANEL_ROOT_INVALID")
    root = root.resolve()
    allowed = _read_allowlist(Path(asset_manifest).expanduser())
    router = APIRouter(prefix="/research-panel", include_in_schema=False)

    @router.api_route("/", methods=["GET", "HEAD"])
    def entry(request: Request) -> RedirectResponse:
        query = request.url.query
        target = "/research-panel/" + ("workbench.html" if "workbench.html" in allowed else "daily.html") + ("?" + query if query else "")
        return RedirectResponse(target, status_code=307, headers={"Cache-Control": "no-store"})

    @router.api_route("/{asset_path:path}", methods=["GET", "HEAD"])
    def asset(asset_path: str, request: Request) -> Response:
        # Migrate only the old default entry when the reviewed new entry is
        # exported. The explicit backup alias still reads hash-bound daily bytes.
        if asset_path == "daily.html" and "workbench.html" in allowed:
            query = request.url.query
            return RedirectResponse("/research-panel/workbench.html" + ("?" + query if query else ""),
                                    status_code=307, headers={"Cache-Control": "no-store"})
        if asset_path == "legacy-daily.html":
            asset_path = "待删除/legacy-daily.html" if "待删除/legacy-daily.html" in allowed else "daily.html"
        if not _valid_relative(asset_path) or asset_path not in allowed:
            raise HTTPException(status_code=404, detail="RESEARCH_PANEL_ASSET_NOT_EXPORTED")
        try:
            data = _read_asset(root, asset_path)
        except OSError:
            raise HTTPException(status_code=404, detail="RESEARCH_PANEL_ASSET_MISSING_OR_UNSAFE") from None
        if hashlib.sha256(data).hexdigest() != allowed[asset_path]:
            raise HTTPException(status_code=409, detail="RESEARCH_PANEL_ASSET_SHA_MISMATCH")
        media_type = "text/javascript" if asset_path.endswith(".mjs") else mimetypes.guess_type(asset_path)[0] or "application/octet-stream"
        headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                   "Content-Length": str(len(data))}
        return Response(b"" if request.method == "HEAD" else data,
                        media_type=media_type, headers=headers)

    return router


def register_opening_research(
    app: FastAPI, *, module_role: str, selection_root: Path | str | None = None,
) -> None:
    """Add the read-only slice to the existing public app, without a new port."""
    if module_role not in {"combined", "gateway"}:
        return
    from apps.api.v4_api.opening_observation_router import create_opening_observation_router
    from apps.api.v4_api.opening_observation_service import OpeningObservationService

    panel_root = os.environ.get("V4_RESEARCH_PANEL_ROOT")
    panel_assets = os.environ.get("V4_RESEARCH_PANEL_ASSET_MANIFEST")
    if bool(panel_root) != bool(panel_assets):
        raise ValueError("RESEARCH_PANEL_CONFIGURATION_INCOMPLETE")
    panel_router = create_research_panel_router(panel_root, panel_assets) if panel_root else None
    service = OpeningObservationService(
        raw_root=os.environ.get("V4_OPENING_RAW_ROOT") or None,
        selection_root=os.environ.get("V4_OPENING_SELECTION_ROOT") or selection_root,
    )
    app.include_router(create_opening_observation_router(service))
    # User-approved new opening feature: one compatibility path, separate from the original 42.
    from infrastructure.api_namespace import install_legacy_aliases
    install_legacy_aliases(app, legacy_routes={"/api/v3/research/opening-observation": ["GET"]})
    if panel_router is not None:
        app.include_router(panel_router)
