"""Standalone, public-only video acquisition producer for :mod:`review_core`.

This module deliberately does not import or execute the V3 orchestrator.  The
network and ASR boundaries are injectable, making the producer deterministic in
tests while leaving the default path cookie-free and fail-closed.
"""

from __future__ import annotations

import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .config import ProducerConfig


Tool = Callable[..., Any]


@dataclass(frozen=True)
class AcquisitionTools:
    """Injectable discovery, capture and local FunASR adapters.

    Callables receive ``(trade_date, config)``, ``(selection, work_dir,
    config)`` and ``(media_path, work_dir, config)`` respectively.  The
    producer also accepts shorter callables for simple test doubles.
    """

    discover: Tool | None = None
    capture: Tool | None = None
    asr: Tool | None = None


class DiscoveryCandidates(list[dict[str, Any]]):
    """List-compatible discovery result carrying public-route evidence.

    Existing adapters historically returned a plain list.  Keeping this type
    list-compatible preserves that seam while making a blocked lookup
    distinguishable from a valid empty result in receipts and manifests.
    """

    def __init__(
        self,
        items: list[dict[str, Any]] | None = None,
        *,
        discovery_status: str = "DISCOVERY_CANDIDATES_READY",
        discovery_routes: list[dict[str, Any]] | None = None,
        discovery_errors: list[str] | None = None,
    ) -> None:
        super().__init__(items or [])
        self.discovery_status = str(discovery_status)
        self.discovery_routes = [dict(item) for item in (discovery_routes or []) if isinstance(item, Mapping)]
        self.discovery_errors = [str(item) for item in (discovery_errors or []) if str(item)]

    @property
    def discovery_attempt(self) -> dict[str, Any]:
        return {
            "status": self.discovery_status,
            "routes": [dict(item) for item in self.discovery_routes],
            "errors": list(self.discovery_errors),
            "network_attempted": True,
        }


class AccessBlockedError(RuntimeError):
    """Public media route was denied or requires an unsupported access mode."""


def build_ffmpeg_wav_command(ffmpeg_path: Path | str, source_path: Path | str, wav_path: Path | str) -> list[str]:
    """Build the conservative 16 kHz mono WAV extraction command."""

    return [
        str(ffmpeg_path),
        "-y",
        "-i",
        str(source_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        str(wav_path),
    ]


def build_funasr_command(
    python_path: Path | str,
    script_path: Path | str,
    output_dir: Path | str,
    wav_path: Path | str,
) -> list[str]:
    """Build the verified local FunASR invocation contract."""

    return [str(python_path), str(script_path), "--out-dir", str(output_dir), str(wav_path)]


def _command_result(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {
            "returncode": int(value.get("returncode", 0) or 0),
            "stdout": str(value.get("stdout", "") or ""),
            "stderr": str(value.get("stderr", "") or ""),
        }
    return {
        "returncode": int(getattr(value, "returncode", 0) or 0),
        "stdout": str(getattr(value, "stdout", "") or ""),
        "stderr": str(getattr(value, "stderr", "") or ""),
    }


def _run_command(
    command: list[str],
    *,
    cwd: Path,
    timeout: int,
    config: ProducerConfig,
    env_path: Path | None = None,
) -> dict[str, Any]:
    runner = config.extra.get("runner") if isinstance(config.extra, Mapping) else None
    environment: dict[str, str] | None = None
    if env_path is not None:
        environment = os.environ.copy()
        environment["PATH"] = os.pathsep.join((str(Path(env_path).absolute()), environment.get("PATH", "")))
    if callable(runner):
        try:
            kwargs: dict[str, Any] = {"cwd": cwd, "timeout": timeout, "check": False}
            if environment is not None:
                kwargs["env"] = environment
            return _command_result(runner(command, **kwargs))
        except TypeError:
            return _command_result(runner(command))
    try:
        kwargs = {
            "cwd": str(cwd),
            "capture_output": True,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "timeout": timeout,
            "check": False,
        }
        if environment is not None:
            kwargs["env"] = environment
        return _command_result(subprocess.run(command, **kwargs))
    except (OSError, subprocess.SubprocessError) as exc:
        return {"returncode": 127, "stdout": "", "stderr": str(exc)}


def _access_blocked_reason(text: str) -> str:
    lowered = str(text or "").lower()
    markers = (
        "private",
        "members only",
        "member-only",
        "login required",
        "sign in",
        "permission",
        "forbidden",
        "http error 403",
        "403 forbidden",
        "http error 412",
        "412 precondition",
        "precondition failed",
        "drm",
        "geo",
        "region",
        "paywall",
        "cookie",
        "access denied",
    )
    return next((marker for marker in markers if marker in lowered), "")


_WBI_MIXIN_KEY_ENC_TAB = (
    46,
    47,
    18,
    2,
    53,
    8,
    23,
    32,
    15,
    50,
    10,
    31,
    58,
    3,
    45,
    35,
    27,
    43,
    5,
    49,
    33,
    9,
    42,
    19,
    29,
    28,
    14,
    39,
    12,
    38,
    41,
    13,
    37,
    48,
    7,
    16,
    24,
    55,
    40,
    61,
    26,
    17,
    0,
    1,
    60,
    51,
    30,
    4,
    22,
    25,
    54,
    21,
    56,
    59,
    6,
    63,
    57,
    62,
    11,
    36,
    20,
    34,
    44,
    52,
)


def _public_api_base(config: ProducerConfig) -> str:
    configured = config.extra.get("api_base_url") if isinstance(config.extra, Mapping) else None
    return str(configured or "https://api.bilibili.com").rstrip("/")


def _public_request(url: str) -> urllib.request.Request:
    return urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36 review_core/standalone",
            "Referer": "https://www.bilibili.com/",
            "Accept": "application/json, text/plain, */*",
        },
    )


def _public_json(url: str, *, timeout: int = 20) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Read one public JSON route, retaining HTTP/API failure evidence."""

    try:
        with urllib.request.urlopen(_public_request(url), timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            payload = json.loads(raw) if raw.strip() else {}
            if not isinstance(payload, Mapping):
                return {}, {"error": "public route returned non-object JSON", "http_status": getattr(response, "status", 0)}
            return dict(payload), None
    except Exception as exc:
        code = getattr(exc, "code", None)
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
        except Exception:
            body = ""
        message = str(exc) or type(exc).__name__
        if body:
            message = f"{message}: {body[:300]}"
        return {}, {"error": message, "http_status": int(code) if isinstance(code, int) else 0}


def _wbi_mixin_key(nav_payload: Mapping[str, Any]) -> str:
    data = nav_payload.get("data") if isinstance(nav_payload, Mapping) else None
    wbi_img = data.get("wbi_img") if isinstance(data, Mapping) else None
    if not isinstance(wbi_img, Mapping):
        return ""
    raw = "".join(Path(str(wbi_img.get(name) or "")).stem for name in ("img_url", "sub_url"))
    if not raw:
        return ""
    return "".join(raw[index] for index in _WBI_MIXIN_KEY_ENC_TAB if index < len(raw))[:32]


def _wbi_url(
    base_url: str,
    *,
    mid: str,
    page: int = 1,
    page_size: int = 50,
    nav_payload: Mapping[str, Any] | None = None,
) -> str:
    if nav_payload is None:
        nav_payload, nav_error = _public_json(f"{base_url}/x/web-interface/nav")
        if nav_error:
            raise RuntimeError(f"WBI nav failed: {nav_error.get('error', '')}")
    mixin_key = _wbi_mixin_key(nav_payload)
    if not mixin_key:
        raise RuntimeError("WBI nav did not expose wbi_img keys")
    params: dict[str, str | int] = {
        "mid": str(mid),
        "order": "pubdate",
        "pn": int(page),
        "ps": int(page_size),
        "wts": int(time.time()),
    }
    filtered = {key: re.sub(r"[!'()*]", "", str(value)) for key, value in params.items()}
    query = urllib.parse.urlencode(sorted(filtered.items()))
    filtered["w_rid"] = hashlib.md5((query + mixin_key).encode("utf-8")).hexdigest()
    return f"{base_url}/x/space/wbi/arc/search?{urllib.parse.urlencode(filtered)}"


def _parse_discovery_rows(
    payload: Mapping[str, Any],
    *,
    config: ProducerConfig,
    route: str,
) -> list[dict[str, Any]]:
    data = payload.get("data", {}) if isinstance(payload, Mapping) else {}
    listing = data.get("list", {}) if isinstance(data, Mapping) else {}
    rows = listing.get("vlist", []) if isinstance(listing, Mapping) else []
    if not rows and isinstance(data, Mapping):
        rows = data.get("result", [])
    if not rows and isinstance(data, Mapping):
        # ``/x/space/arc/list`` is the public non-WBI fallback.  Its response
        # uses ``data.archives`` and nests the owner under ``author``.
        rows = data.get("archives", [])
    candidates: list[dict[str, Any]] = []
    for rank, row in enumerate(rows if isinstance(rows, list) else [], 1):
        if not isinstance(row, Mapping):
            continue
        title = re.sub(r"<.*?>", "", str(row.get("title") or ""))
        bv_id = str(row.get("bvid") or row.get("bv_id") or "").strip()
        if not bv_id:
            continue
        nested_author = row.get("author") if isinstance(row.get("author"), Mapping) else {}
        author = str(
            (nested_author.get("name") if isinstance(nested_author, Mapping) else "")
            or row.get("uploader")
            or (row.get("author") if isinstance(row.get("author"), str) else "")
            or ""
        ).strip()
        mid = str(
            (nested_author.get("mid") if isinstance(nested_author, Mapping) else "")
            or row.get("mid")
            or row.get("author_mid")
            or row.get("owner_mid")
            or ""
        ).strip()
        if mid and mid != config.target_mid:
            continue
        if author and author != config.target_uploader:
            continue
        pubdate = row.get("pubdate") or row.get("created")
        upload_date = ""
        try:
            upload_date = time.strftime("%Y%m%d", time.localtime(int(pubdate))) if pubdate else ""
        except (TypeError, ValueError, OverflowError, OSError):
            upload_date = ""
        candidates.append(
            {
                "candidate_rank": str(rank),
                "bv_id": bv_id,
                "title": title,
                "upload_date": upload_date,
                "uploader": author or config.target_uploader,
                "uploader_mid": mid or config.target_mid,
                "target_mid": config.target_mid,
                "metadata_status": "METADATA_READY",
                "source_route": f"https://www.bilibili.com/video/{bv_id}/",
                "discovery_route": route,
            }
        )
    return candidates


def _resolve_ytdlp_prefix(config: ProducerConfig) -> list[str] | None:
    if config.ytdlp_path is not None and config.ytdlp_path.is_file():
        return [str(config.ytdlp_path)]
    executable = shutil.which("yt-dlp") or shutil.which("yt-dlp.exe")
    if executable:
        return [executable]
    try:
        import yt_dlp  # noqa: F401

        return [str(config.python_path or sys.executable), "-m", "yt_dlp"]
    except ImportError:
        return None


def _canonical(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_bytes(path: Path, payload: bytes) -> str:
    import hashlib

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = __import__("tempfile").mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        actual = _sha256(path)
        expected = hashlib.sha256(payload).hexdigest()
        if actual != expected:
            raise RuntimeError(f"atomic write SHA mismatch: {path}")
        return actual
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_json(path: Path, payload: Any) -> str:
    return _atomic_bytes(path, (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _copy_atomic(source: Path, destination: Path) -> str:
    if not source.is_file():
        raise FileNotFoundError(str(source))
    source_sha = _sha256(source)
    if destination.is_file():
        if _sha256(destination) != source_sha:
            raise RuntimeError(f"content-addressed destination mismatch: {destination}")
        return source_sha
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = __import__("tempfile").mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=str(destination.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as output, source.open("rb") as input_handle:
            shutil.copyfileobj(input_handle, output, length=1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
        if _sha256(destination) != source_sha:
            raise RuntimeError(f"copied artifact SHA mismatch: {destination}")
        return source_sha
    finally:
        if temporary.exists():
            temporary.unlink()


def _safe_name(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value or "artifact")
    return value[:120] or "artifact"


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return default


def _invoke(tool: Tool, *args: Any) -> Any:
    """Call a test double without requiring it to accept unused config args."""

    try:
        signature = inspect.signature(tool)
    except (TypeError, ValueError):
        return tool(*args)
    positional = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.kind in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD)
    ]
    if any(parameter.kind == parameter.VAR_POSITIONAL for parameter in signature.parameters.values()):
        return tool(*args)
    count = len(positional)
    if count == 2 and len(args) == 3:
        second_name = positional[1].name.lower()
        if "config" in second_name or "setting" in second_name:
            return tool(args[0], args[2])
        return tool(args[0], args[1])
    return tool(*args[:count])


def _tool_fingerprint(tool: Tool | None) -> dict[str, str]:
    if tool is None:
        return {"module": "", "qualname": "", "source_sha256": ""}
    module = str(getattr(tool, "__module__", ""))
    qualname = str(getattr(tool, "__qualname__", getattr(tool, "__name__", "")))
    source_sha = ""
    try:
        source = inspect.getsource(tool).encode("utf-8")
        import hashlib

        source_sha = hashlib.sha256(source).hexdigest()
    except (OSError, TypeError, UnicodeError):
        source_sha = ""
    return {"module": module, "qualname": qualname, "source_sha256": source_sha}


def _default_discover(trade_date: str, config: ProducerConfig) -> DiscoveryCandidates:
    """Discover exact-date public videos with legacy then WBI routes.

    A valid empty search is ``NO_NEW_VIDEO``.  A response such as ``-799`` or
    an HTTP 412 is ``UP_LOOKUP_BLOCKED`` and is retained in route evidence;
    neither state is collapsed to a bare ``[]``.
    """

    label = f"{trade_date[4:6].lstrip('0')}.{trade_date[6:]}"
    api_base = _public_api_base(config)
    routes: list[dict[str, Any]] = []
    errors: list[str] = []
    successful_search = False

    legacy_query = urllib.parse.urlencode(
        {
            "mid": config.target_mid,
            "pn": "1",
            "ps": "50",
            "keyword": f"{config.target_uploader} {label}",
            "order": "pubdate",
        }
    )
    legacy_url = f"{api_base}/x/space/arc/search?{legacy_query}"
    legacy_payload, legacy_error = _public_json(legacy_url)
    legacy_code = legacy_payload.get("code") if legacy_payload else None
    if legacy_error:
        route = {"route": "legacy_space_arc_search", "url": legacy_url, **legacy_error}
        routes.append(route)
        errors.append(f"legacy_space_arc_search: {legacy_error.get('error', '')}")
    else:
        legacy_rows = _parse_discovery_rows(legacy_payload, config=config, route="legacy_space_arc_search")
        route = {
            "route": "legacy_space_arc_search",
            "url": legacy_url,
            "code": legacy_code,
            "candidate_count": len(legacy_rows),
        }
        routes.append(route)
        if legacy_code == 0:
            successful_search = True
            if legacy_rows:
                return DiscoveryCandidates(
                    legacy_rows,
                    discovery_status="DISCOVERY_CANDIDATES_READY",
                    discovery_routes=routes,
                )
        elif legacy_code is not None:
            errors.append(f"legacy_space_arc_search: code={legacy_code} {legacy_payload.get('message', '')}".strip())

    nav_url = f"{api_base}/x/web-interface/nav"
    nav_payload, nav_error = _public_json(nav_url)
    if nav_error:
        routes.append({"route": "wbi_nav", "url": nav_url, **nav_error})
        errors.append(f"wbi_nav: {nav_error.get('error', '')}")
    else:
        nav_code = nav_payload.get("code")
        routes.append({"route": "wbi_nav", "url": nav_url, "code": nav_code, "candidate_count": 0})
        try:
            wbi_url = _wbi_url(api_base, mid=config.target_mid, nav_payload=nav_payload)
        except Exception as exc:
            routes[-1]["error"] = str(exc)
            errors.append(f"wbi_nav: {exc}")
        else:
            wbi_payload, wbi_error = _public_json(wbi_url)
            if wbi_error:
                routes.append({"route": "wbi_space_arc_search", "url": wbi_url, **wbi_error})
                errors.append(f"wbi_space_arc_search: {wbi_error.get('error', '')}")
            else:
                wbi_code = wbi_payload.get("code")
                wbi_rows = _parse_discovery_rows(wbi_payload, config=config, route="wbi_space_arc_search")
                routes.append(
                    {
                        "route": "wbi_space_arc_search",
                        "url": wbi_url,
                        "code": wbi_code,
                        "candidate_count": len(wbi_rows),
                    }
                )
                if wbi_code == 0:
                    successful_search = True
                    if wbi_rows:
                        return DiscoveryCandidates(
                            wbi_rows,
                            discovery_status="DISCOVERY_CANDIDATES_READY",
                            discovery_routes=routes,
                            discovery_errors=errors,
                        )
                elif wbi_code is not None:
                    errors.append(f"wbi_space_arc_search: code={wbi_code} {wbi_payload.get('message', '')}".strip())

    # The public, non-WBI archive list is the last discovery route.  It is
    # intentionally called with order=pubdate: omitting that parameter can
    # return an empty archive set for this UP even while the route is healthy.
    arc_list_query = urllib.parse.urlencode(
        {
            "mid": config.target_mid,
            "pn": "1",
            "ps": "30",
            "order": "pubdate",
        }
    )
    arc_list_url = f"{api_base}/x/space/arc/list?{arc_list_query}"
    arc_list_payload, arc_list_error = _public_json(arc_list_url)
    if arc_list_error:
        routes.append({"route": "public_space_arc_list", "url": arc_list_url, **arc_list_error})
        errors.append(f"public_space_arc_list: {arc_list_error.get('error', '')}")
    else:
        arc_list_code = arc_list_payload.get("code")
        arc_list_rows = _parse_discovery_rows(
            arc_list_payload,
            config=config,
            route="public_space_arc_list",
        )
        routes.append(
            {
                "route": "public_space_arc_list",
                "url": arc_list_url,
                "code": arc_list_code,
                "candidate_count": len(arc_list_rows),
            }
        )
        if arc_list_code == 0:
            successful_search = True
            if arc_list_rows:
                return DiscoveryCandidates(
                    arc_list_rows,
                    discovery_status="DISCOVERY_CANDIDATES_READY",
                    discovery_routes=routes,
                    discovery_errors=errors,
                )
        elif arc_list_code is not None:
            errors.append(
                f"public_space_arc_list: code={arc_list_code} {arc_list_payload.get('message', '')}".strip()
            )

    status = "NO_NEW_VIDEO" if successful_search else "UP_LOOKUP_BLOCKED"
    return DiscoveryCandidates(
        [],
        discovery_status=status,
        discovery_routes=routes,
        discovery_errors=errors,
    )


def _download_public_stream(url: str, destination: Path, *, referer: str = "https://www.bilibili.com/") -> dict[str, Any]:
    """Download one public DASH stream without cookies or browser state."""

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        request = _public_request(url)
        request.headers["Referer"] = referer
        with urllib.request.urlopen(request, timeout=1800) as response, destination.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
        if not destination.is_file() or destination.stat().st_size <= 0:
            return {"status": "ACCESS_BLOCKED", "reason": "public stream returned no bytes", "access_status": "EMPTY_STREAM"}
        return {"status": "DOWNLOADED", "path": str(destination), "downloaded": True}
    except Exception as exc:
        blocked = _access_blocked_reason(str(exc))
        return {
            "status": "ACCESS_BLOCKED" if blocked or getattr(exc, "code", None) in {401, 403, 412} else "CAPTURE_NOT_AVAILABLE",
            "reason": str(exc),
            "access_status": (blocked or f"HTTP_{getattr(exc, 'code', '')}").upper(),
        }


def _direct_public_capture(
    selection: Mapping[str, Any],
    work_dir: Path,
    config: ProducerConfig,
    *,
    metadata_path: Path | None = None,
    prior_error: str = "",
) -> dict[str, Any]:
    """Use public ``view`` + ``playurl`` DASH routes as a no-cookie fallback."""

    bv_id = str(selection.get("bv_id") or "")
    if not bv_id:
        return {"status": "CAPTURE_NOT_AVAILABLE", "reason": "missing BV id", "access_status": "DISCOVERY_EMPTY", "downloaded": False}
    api_base = _public_api_base(config)
    view_url = f"{api_base}/x/web-interface/view?{urllib.parse.urlencode({'bvid': bv_id})}"
    view_payload, view_error = _public_json(view_url)
    routes: list[dict[str, Any]] = []
    if view_error:
        routes.append({"route": "public_view", "url": view_url, **view_error})
        return {
            "status": "ACCESS_BLOCKED" if view_error.get("http_status") in {401, 403, 412} else "CAPTURE_NOT_AVAILABLE",
            "reason": view_error.get("error") or prior_error or "public view route failed",
            "access_status": f"HTTP_{view_error.get('http_status')}" if view_error.get("http_status") else "VIEW_FAILED",
            "capture_route": "PUBLIC_VIEW_PLAYURL_NO_COOKIES",
            "capture_routes": routes,
            "downloaded": False,
        }
    view_code = view_payload.get("code")
    view_data = view_payload.get("data") if isinstance(view_payload, Mapping) else None
    routes.append({"route": "public_view", "url": view_url, "code": view_code})
    if view_code != 0 or not isinstance(view_data, Mapping):
        return {
            "status": "ACCESS_BLOCKED",
            "reason": str(view_payload.get("message") or prior_error or f"public view code={view_code}"),
            "access_status": f"VIEW_CODE_{view_code}",
            "capture_route": "PUBLIC_VIEW_PLAYURL_NO_COOKIES",
            "capture_routes": routes,
            "downloaded": False,
        }
    owner = view_data.get("owner") if isinstance(view_data.get("owner"), Mapping) else {}
    owner_mid = str(owner.get("mid") or view_data.get("owner_mid") or "")
    owner_name = str(owner.get("name") or view_data.get("author") or "")
    if (owner_mid and owner_mid != config.target_mid) or (owner_name and owner_name != config.target_uploader):
        return {
            "status": "WRONG_UPLOADER",
            "reason": "public view owner does not match fixed target uploader",
            "access_status": "OWNER_MISMATCH",
            "capture_route": "PUBLIC_VIEW_PLAYURL_NO_COOKIES",
            "capture_routes": routes,
            "downloaded": False,
        }
    if str(view_data.get("bvid") or bv_id) != bv_id:
        return {
            "status": "CAPTURE_NOT_AVAILABLE",
            "reason": "public view BV mismatch",
            "access_status": "BV_MISMATCH",
            "capture_route": "PUBLIC_VIEW_PLAYURL_NO_COOKIES",
            "capture_routes": routes,
            "downloaded": False,
        }
    if metadata_path is None:
        metadata_path = work_dir / f"{bv_id}_metadata.json"
    _write_json(metadata_path, view_payload)
    pages = view_data.get("pages")
    page = pages[0] if isinstance(pages, list) and pages and isinstance(pages[0], Mapping) else {}
    cid = str(view_data.get("cid") or page.get("cid") or "")
    if not cid:
        return {
            "status": "CAPTURE_NOT_AVAILABLE",
            "reason": "public view did not expose cid",
            "access_status": "CID_MISSING",
            "capture_route": "PUBLIC_VIEW_PLAYURL_NO_COOKIES",
            "capture_routes": routes,
            "metadata_path": str(metadata_path),
            "downloaded": False,
        }
    play_query = urllib.parse.urlencode({"bvid": bv_id, "cid": cid, "qn": 64, "fnval": 16, "fourk": 1})
    play_url = f"{api_base}/x/player/playurl?{play_query}"
    play_payload, play_error = _public_json(play_url)
    if play_error:
        routes.append({"route": "public_playurl", "url": play_url, **play_error})
        return {
            "status": "ACCESS_BLOCKED" if play_error.get("http_status") in {401, 403, 412} else "CAPTURE_NOT_AVAILABLE",
            "reason": play_error.get("error") or "public playurl route failed",
            "access_status": f"HTTP_{play_error.get('http_status')}" if play_error.get("http_status") else "PLAYURL_FAILED",
            "capture_route": "PUBLIC_VIEW_PLAYURL_NO_COOKIES",
            "capture_routes": routes,
            "metadata_path": str(metadata_path),
            "downloaded": False,
        }
    play_code = play_payload.get("code")
    routes.append({"route": "public_playurl", "url": play_url, "code": play_code})
    play_data = play_payload.get("data") if isinstance(play_payload, Mapping) else None
    dash = play_data.get("dash") if isinstance(play_data, Mapping) else None
    videos = dash.get("video") if isinstance(dash, Mapping) else None
    audios = dash.get("audio") if isinstance(dash, Mapping) else None
    video_url = ""
    audio_url = ""
    if isinstance(videos, list) and videos and isinstance(videos[0], Mapping):
        video_url = str(videos[0].get("baseUrl") or videos[0].get("base_url") or videos[0].get("url") or "")
        if not video_url:
            backups = videos[0].get("backupUrl") or videos[0].get("backup_url") or []
            video_url = str(next((item for item in backups if item), "")) if isinstance(backups, list) else ""
    if isinstance(audios, list) and audios and isinstance(audios[0], Mapping):
        audio_url = str(audios[0].get("baseUrl") or audios[0].get("base_url") or audios[0].get("url") or "")
        if not audio_url:
            backups = audios[0].get("backupUrl") or audios[0].get("backup_url") or []
            audio_url = str(next((item for item in backups if item), "")) if isinstance(backups, list) else ""
    if play_code != 0 or not video_url or not audio_url:
        return {
            "status": "ACCESS_BLOCKED" if play_code not in {0, None} else "CAPTURE_NOT_AVAILABLE",
            "reason": str(play_payload.get("message") or "public playurl did not expose DASH video/audio"),
            "access_status": f"PLAYURL_CODE_{play_code}" if play_code not in {0, None} else "DASH_MISSING",
            "capture_route": "PUBLIC_VIEW_PLAYURL_NO_COOKIES",
            "capture_routes": routes,
            "metadata_path": str(metadata_path),
            "downloaded": False,
        }
    video_source = work_dir / f"{bv_id}.video.m4s"
    audio_source = work_dir / f"{bv_id}.audio.m4s"
    video_download = _download_public_stream(video_url, video_source, referer=f"{config.public_base_url.rstrip('/')}/video/{bv_id}/")
    if video_download.get("status") != "DOWNLOADED":
        return {**video_download, "capture_route": "PUBLIC_VIEW_PLAYURL_NO_COOKIES", "capture_routes": routes, "metadata_path": str(metadata_path), "downloaded": False}
    audio_download = _download_public_stream(audio_url, audio_source, referer=f"{config.public_base_url.rstrip('/')}/video/{bv_id}/")
    if audio_download.get("status") != "DOWNLOADED":
        return {**audio_download, "capture_route": "PUBLIC_VIEW_PLAYURL_NO_COOKIES", "capture_routes": routes, "metadata_path": str(metadata_path), "downloaded": False}
    ffmpeg = config.ffmpeg_path or (Path(shutil.which("ffmpeg")) if shutil.which("ffmpeg") else None)
    if ffmpeg is None or not ffmpeg.is_file():
        return {
            "status": "FFMPEG_NOT_AVAILABLE",
            "reason": "ffmpeg is required to merge public DASH video/audio",
            "access_status": "PUBLIC_DASH_DOWNLOADED",
            "capture_route": "PUBLIC_VIEW_PLAYURL_NO_COOKIES",
            "capture_routes": routes,
            "metadata_path": str(metadata_path),
            "downloaded": True,
        }
    media_path = work_dir / f"{bv_id}.mp4"
    merge_command = [str(ffmpeg), "-y", "-i", str(video_source), "-i", str(audio_source), "-c", "copy", "-movflags", "+faststart", str(media_path)]
    merge_run = _run_command(merge_command, cwd=work_dir, timeout=1800, config=config)
    if merge_run["returncode"] != 0 or not media_path.is_file() or media_path.stat().st_size <= 0:
        return {
            "status": "CAPTURE_NOT_AVAILABLE",
            "reason": merge_run.get("stderr", "")[-1200:] or "ffmpeg public DASH merge failed",
            "access_status": "MERGE_FAILED",
            "capture_route": "PUBLIC_VIEW_PLAYURL_NO_COOKIES",
            "capture_routes": routes,
            "metadata_path": str(metadata_path),
            "downloaded": True,
        }
    wav_path = work_dir / "audio" / f"{bv_id}.wav"
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    wav_run = _run_command(build_ffmpeg_wav_command(ffmpeg, media_path, wav_path), cwd=work_dir, timeout=600, config=config)
    result: dict[str, Any] = {
        "status": "CAPTURED" if wav_run["returncode"] == 0 and wav_path.is_file() and wav_path.stat().st_size > 0 else "FFMPEG_NOT_AVAILABLE",
        "media_path": str(media_path),
        "metadata_path": str(metadata_path),
        "downloaded": True,
        "access_status": "PUBLIC_NO_COOKIES_WBI_PLAYURL",
        "capture_route": "PUBLIC_VIEW_PLAYURL_NO_COOKIES",
        "capture_routes": routes,
    }
    if wav_run["returncode"] == 0 and wav_path.is_file() and wav_path.stat().st_size > 0:
        result["audio_path"] = str(wav_path)
    else:
        result.update({"ffmpeg_missing": True, "reason": wav_run.get("stderr", "")[-1200:] or "ffmpeg WAV extraction failed"})
    return result


def _default_capture(selection: Mapping[str, Any], work_dir: Path, config: ProducerConfig) -> dict[str, Any]:
    """Capture public media with yt-dlp, metadata first, without cookies."""

    work_dir.mkdir(parents=True, exist_ok=True)
    supplied = selection.get("media_path") or selection.get("media_file")
    if supplied and Path(str(supplied)).is_file():
        return {"status": "CAPTURED", "media_path": str(Path(str(supplied)).resolve()), "downloaded": False}
    bv_id = str(selection.get("bv_id") or "")
    if not bv_id:
        return {"status": "CAPTURE_NOT_AVAILABLE", "reason": "missing BV id", "access_status": "DISCOVERY_EMPTY", "downloaded": False}
    prefix = _resolve_ytdlp_prefix(config)
    metadata_path = work_dir / f"{bv_id}_metadata.json"
    if prefix is None:
        return _direct_public_capture(selection, work_dir, config, metadata_path=metadata_path, prior_error="yt-dlp executable/module is not configured")
    url = f"{config.public_base_url.rstrip('/')}/video/{bv_id}/"
    metadata_cmd = prefix + ["--skip-download", "--dump-single-json", "--no-playlist", url]
    metadata_run = _run_command(metadata_cmd, cwd=work_dir, timeout=120, config=config)
    metadata_text = metadata_run.get("stdout", "")
    try:
        metadata = json.loads(metadata_text) if metadata_text.strip() else {}
    except json.JSONDecodeError:
        metadata = {}
    _write_json(metadata_path, metadata if isinstance(metadata, Mapping) else {"raw_stdout": metadata_text})
    if metadata_run["returncode"] != 0:
        blocked = _access_blocked_reason(metadata_run.get("stderr", ""))
        if blocked and blocked not in {"http error 412", "412 precondition", "precondition failed"}:
            return {
                "status": "ACCESS_BLOCKED",
                "reason": metadata_run.get("stderr", "")[-1200:] or "metadata lookup blocked",
                "access_status": blocked.upper(),
                "metadata_path": str(metadata_path),
                "downloaded": False,
                "capture_route": "YTDLP_NO_COOKIES",
            }
        fallback = _direct_public_capture(
            selection,
            work_dir,
            config,
            metadata_path=metadata_path,
            prior_error=metadata_run.get("stderr", "")[-1200:] or "metadata lookup failed",
        )
        if fallback.get("status") in {"CAPTURED", "FFMPEG_NOT_AVAILABLE"}:
            return fallback
        if blocked and fallback.get("status") == "CAPTURE_NOT_AVAILABLE":
            fallback["status"] = "ACCESS_BLOCKED"
        return fallback
    owner_mid = str(metadata.get("uploader_id") or metadata.get("channel_id") or metadata.get("uploader_mid") or "")
    owner_name = str(metadata.get("uploader") or metadata.get("channel") or "")
    if owner_mid and owner_mid != config.target_mid or owner_name and owner_name != config.target_uploader:
        return {
            "status": "WRONG_UPLOADER",
            "reason": "metadata owner does not match fixed target uploader",
            "access_status": "OWNER_MISMATCH",
            "metadata_path": str(metadata_path),
            "downloaded": False,
        }
    output_template = work_dir / f"{bv_id}.%(ext)s"
    media_cmd = prefix + [
        "--no-playlist",
        "--format",
        "bv*+ba/b",
        "--merge-output-format",
        "mp4",
        "--output",
        str(output_template),
        url,
    ]
    media_run = _run_command(media_cmd, cwd=work_dir, timeout=1800, config=config)
    blocked = _access_blocked_reason(media_run.get("stderr", ""))
    media_candidates = [
        path
        for path in sorted(work_dir.glob(f"{bv_id}.*"))
        if path.suffix.lower() not in {".json", ".part", ".ytdl"} and path.is_file()
    ]
    media_path = next((path for path in media_candidates if path.suffix.lower() in {".mp4", ".mkv", ".webm"}), None)
    audio_path = next((path for path in media_candidates if path.suffix.lower() in {".wav", ".m4a", ".mp3", ".aac", ".opus"}), None)
    if media_run["returncode"] != 0 or media_path is None:
        if blocked and blocked not in {"http error 412", "412 precondition", "precondition failed"}:
            return {
                "status": "ACCESS_BLOCKED",
                "reason": media_run.get("stderr", "")[-1200:] or "public media route blocked",
                "access_status": blocked.upper(),
                "metadata_path": str(metadata_path),
                "downloaded": False,
                "capture_route": "YTDLP_NO_COOKIES",
            }
        fallback = _direct_public_capture(
            selection,
            work_dir,
            config,
            metadata_path=metadata_path,
            prior_error=media_run.get("stderr", "")[-1200:] or "public media route did not produce media",
        )
        if fallback.get("status") in {"CAPTURED", "FFMPEG_NOT_AVAILABLE"}:
            return fallback
        if blocked and fallback.get("status") == "CAPTURE_NOT_AVAILABLE":
            fallback["status"] = "ACCESS_BLOCKED"
        return fallback
    result: dict[str, Any] = {
        "status": "CAPTURED",
        "media_path": str(media_path),
        "metadata_path": str(metadata_path),
        "downloaded": True,
        "access_status": "PUBLIC_NO_COOKIES",
        "capture_route": "YTDLP_NO_COOKIES",
    }
    ffmpeg = config.ffmpeg_path or (Path(shutil.which("ffmpeg")) if shutil.which("ffmpeg") else None)
    if audio_path is not None and audio_path.suffix.lower() == ".wav":
        result["audio_path"] = str(audio_path)
    elif ffmpeg is None or not ffmpeg.is_file():
        result.update({"status": "FFMPEG_NOT_AVAILABLE", "ffmpeg_missing": True, "reason": "ffmpeg is required to produce 16 kHz mono WAV"})
    else:
        wav_path = work_dir / "audio" / f"{bv_id}.wav"
        ffmpeg_input = audio_path or media_path
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg_run = _run_command(build_ffmpeg_wav_command(ffmpeg, ffmpeg_input, wav_path), cwd=work_dir, timeout=600, config=config)
        if ffmpeg_run["returncode"] == 0 and wav_path.is_file() and wav_path.stat().st_size > 0:
            result["audio_path"] = str(wav_path)
        else:
            result.update({"status": "FFMPEG_NOT_AVAILABLE", "ffmpeg_missing": True, "reason": ffmpeg_run.get("stderr", "")[-1200:] or "ffmpeg WAV extraction failed"})
    return result


def _default_asr(media_path: Path, work_dir: Path, config: ProducerConfig) -> dict[str, Any]:
    """Run verified local FunASR on an extracted WAV and validate outputs."""

    if config.funasr_path is None or not config.funasr_path.is_file():
        return {"status": "ASR_REVIEW_REQUIRED", "reason": "verified local FunASR script is not configured"}
    if config.python_path is not None and not config.python_path.is_file():
        return {"status": "ASR_REVIEW_REQUIRED", "reason": "configured Python interpreter is not available"}
    if media_path.suffix.lower() != ".wav":
        return {"status": "ASR_REVIEW_REQUIRED", "reason": "FunASR requires extracted 16 kHz mono WAV"}
    output_dir = work_dir / "asr"
    output_dir.mkdir(parents=True, exist_ok=True)
    python_path = config.python_path or Path(sys.executable)
    if config.funasr_path.suffix.lower() == ".py":
        command = build_funasr_command(python_path, config.funasr_path, output_dir, media_path)
    else:
        command = [str(config.funasr_path), "--out-dir", str(output_dir), str(media_path)]
    asr_bin: Path | None = None
    if config.ffmpeg_path is not None and config.ffmpeg_path.is_file():
        asr_bin = work_dir / ".asr_bin"
        asr_bin.mkdir(parents=True, exist_ok=True)
        ffmpeg_alias = asr_bin / "ffmpeg"
        expected_ffmpeg = config.ffmpeg_path.resolve()
        if ffmpeg_alias.exists() or ffmpeg_alias.is_symlink():
            if not ffmpeg_alias.is_symlink() or ffmpeg_alias.resolve() != expected_ffmpeg:
                return {"status": "FAILED", "reason": "ASR_LOCAL_FFMPEG_ALIAS_CONFLICT"}
        else:
            try:
                os.symlink(expected_ffmpeg, ffmpeg_alias)
            except OSError as error:
                return {"status": "FAILED", "reason": f"ASR_LOCAL_FFMPEG_ALIAS_FAILED:{error}"}
    completed = _run_command(command, cwd=work_dir, timeout=3600, config=config, env_path=asr_bin)
    trace = output_dir / "funasr_run_manifest.json"
    _write_json(
        trace,
        {
            "status": "OK" if completed["returncode"] == 0 else "FAILED",
            "returncode": completed["returncode"],
            "command": command,
            "stderr_tail": completed.get("stderr", "")[-500:],
            "stdout_tail": completed.get("stdout", "")[-500:],
        },
    )
    if completed["returncode"] != 0:
        return {"status": "FAILED", "reason": completed.get("stderr", "")[-500:] or "FunASR execution failed", "trace_path": str(trace)}
    raw = next(iter(sorted(output_dir.rglob("*.funasr_raw.txt"))), None)
    segments = next(iter(sorted(output_dir.rglob("*.funasr_segments.csv"))), None)
    tokens = next(iter(sorted(output_dir.rglob("*.funasr_tokens.csv"))), None)
    if raw is None or segments is None:
        return {"status": "FAILED", "reason": "FunASR completed without validated raw/segments outputs", "trace_path": str(trace)}
    return {
        "status": "ASR_REVIEW_REQUIRED",
        "reason": "FunASR completed; exact transcript spot-check remains required",
        "raw_path": str(raw),
        "segments_path": str(segments),
        "tokens_path": str(tokens) if tokens else "",
        "trace_path": str(trace),
        "engine": "FunASR",
    }


class _DateLock:
    """Small process-safe mkdir lock with bounded waiting."""

    def __init__(self, path: Path, timeout: float = 60.0) -> None:
        self.path = path
        self.timeout = timeout
        self.acquired = False

    def __enter__(self) -> "_DateLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self.path.mkdir()
                (self.path / "owner.json").write_text(
                    json.dumps({"pid": os.getpid(), "time": time.time()}), encoding="utf-8"
                )
                self.acquired = True
                return self
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"acquisition lock timeout: {self.path}")
                time.sleep(0.02)

    def __exit__(self, *_exc: object) -> None:
        if self.acquired:
            owner = self.path / "owner.json"
            try:
                if owner.exists():
                    owner.unlink()
                self.path.rmdir()
            except OSError:
                # Lock cleanup is best effort; no artifact is ever replaced.
                pass


def _cache_index(path: Path) -> list[dict[str, Any]]:
    payload = _read_json(path, [])
    return [dict(item) for item in payload if isinstance(item, Mapping)] if isinstance(payload, list) else []


def _find_cached_media(data_root: Path, bv_id: str) -> dict[str, Any] | None:
    index_path = data_root / "media" / bv_id / "index.json"
    for entry in _cache_index(index_path):
        relative = str(entry.get("path") or "")
        candidate = data_root / relative
        expected = str(entry.get("sha256") or "")
        if relative and candidate.is_file() and expected and _sha256(candidate) == expected:
            result = {"path": relative, "sha256": expected, "name": candidate.name}
            audio_relative = str(entry.get("audio_path") or "")
            if audio_relative and (data_root / audio_relative).is_file():
                result["audio_path"] = audio_relative
            return result
    return None


def _find_cached_asr(data_root: Path, bv_id: str, media_sha256: str) -> dict[str, Any] | None:
    index_path = data_root / "asr" / "cache" / bv_id / media_sha256 / "index.json"
    entries = _cache_index(index_path)
    if not entries:
        return None
    cached_status = str(entries[0].get("status") or "").upper()
    if cached_status in {"FAILED", "ASR_FAILED", "NOT_RUN"}:
        # A failed sentinel records an attempt, not reusable evidence.  A
        # later run with the same content-addressed media must be allowed to
        # repair the ASR tool path and produce a new immutable Review Core run.
        return None
    files: list[dict[str, Any]] = []
    for entry in entries:
        relative = str(entry.get("path") or "")
        if not relative:
            # A status-only sentinel records a completed/failed attempt with
            # no materialized transcript files.
            continue
        candidate = data_root / relative
        expected = str(entry.get("sha256") or "")
        if not relative or not candidate.is_file() or not expected or _sha256(candidate) != expected:
            return None
        files.append({"path": relative, "sha256": expected, "name": candidate.name, "key": entry.get("key", "")})
    return {"files": files, "status": str(entries[0].get("status") or "ASR_REVIEW_REQUIRED"), "aliases": entries[0].get("aliases") or []}


def _asr_cache_relative_path(data_root: Path, bv_id: str, media_sha256: str, source: Path) -> Path:
    """Choose a content-addressed ASR filename without overwriting a failed attempt."""

    relative = Path("asr") / "cache" / bv_id / media_sha256 / _safe_name(source.name)
    destination = data_root / relative
    if destination.is_file() and _sha256(destination) != _sha256(source):
        relative = relative.with_name(f"{_safe_name(source.stem)}-{_sha256(source)[:16]}{source.suffix}")
    return relative


def _register(refs: list[dict[str, Any]], path: str, kind: str, sha256: str, size: int, *, import_mode: str = "MATERIALIZED", source_path: str = "") -> dict[str, Any]:
    ref: dict[str, Any] = {"kind": kind, "path": path, "sha256": sha256, "size": size, "import_mode": import_mode}
    if source_path:
        ref["source_path"] = source_path
    refs.append(ref)
    return ref


def _artifact(stage: Path, run_rel: str, name: str, kind: str, payload: Any, refs: list[dict[str, Any]]) -> Path:
    path = stage / name
    digest = _write_json(path, payload)
    _register(refs, f"{run_rel}/{Path(name).as_posix()}", kind, digest, path.stat().st_size)
    return path


def _artifact_copy(stage: Path, run_rel: str, source: Path, local_name: str, kind: str, refs: list[dict[str, Any]]) -> Path:
    destination = stage / local_name
    digest = _copy_atomic(source, destination)
    _register(refs, f"{run_rel}/{Path(local_name).as_posix()}", kind, digest, destination.stat().st_size, source_path=str(source))
    return destination


def _safe_tool_result(value: Any, default_status: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, (str, Path)):
        return {"status": default_status, "media_path": str(value)}
    return {"status": default_status}


def _segment_count_from_files(asr_files: list[dict[str, Any]]) -> int:
    for item in asr_files:
        if str(item.get("key") or "") != "segments_path":
            continue
        path = Path(str(item.get("source_path") or ""))
        if not path.is_file():
            return 0
        try:
            import csv

            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                return sum(1 for _ in csv.DictReader(handle))
        except (OSError, UnicodeError, csv.Error):
            return 0
    return 0


def normalize_stockdict_aliases(aliases: Any) -> list[dict[str, Any]]:
    """Preserve a deterministic raw-to-normalized alias trace.

    Uncertain aliases are never promoted to a clean stock mention; they stay
    visible with ``status=UNCERTAIN`` for human review.
    """

    if not isinstance(aliases, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in aliases:
        if not isinstance(item, Mapping):
            continue
        raw = str(item.get("raw") or item.get("surface") or item.get("text") or "")
        value = str(item.get("normalized") or item.get("canonical") or "")
        status = str(item.get("status") or ("UNCERTAIN" if raw and not value else "NORMALIZED"))
        normalized.append({"raw": raw, "normalized": value, "status": status, "reason": str(item.get("reason") or "")})
    return normalized


def audit_gap_alignment(
    rows: Any,
    *,
    independent_review_input: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run a deterministic OCR/table-gap audit without changing facts.

    The returned payload only references independent fact IDs; it never copies
    video narration into the independent fact values.
    """

    gap_rows = json.loads(json.dumps(rows if isinstance(rows, list) else [], ensure_ascii=False))
    facts = independent_review_input.get("facts", []) if independent_review_input else []
    fact_ids = [str(item.get("fact_id")) for item in facts if isinstance(item, Mapping) and item.get("fact_id")]
    return {
        "status": "VIDEO_GAP_AUDIT_READY" if gap_rows else "VIDEO_GAP_AUDIT_EMPTY",
        "gap_rows": gap_rows,
        "gap_row_count": len(gap_rows),
        "independent_fact_ids": fact_ids,
        "evidence_boundary": "VIDEO_ENHANCEMENT_ONLY; INDEPENDENT_FACTS_UNCHANGED",
    }


def _stable_discovery_attempt(value: Any) -> dict[str, Any]:
    """Keep deterministic route outcomes while dropping volatile URLs/timestamps."""

    if not isinstance(value, Mapping):
        return {}
    routes: list[dict[str, Any]] = []
    for item in value.get("routes") or []:
        if not isinstance(item, Mapping):
            continue
        route: dict[str, Any] = {}
        for key in ("route", "code", "http_status", "candidate_count"):
            if key in item:
                route[key] = item.get(key)
        if item.get("error"):
            route["error"] = str(item.get("error"))
        routes.append(route)
    return {
        "status": str(value.get("status") or ""),
        "routes": routes,
        "errors": [str(item) for item in (value.get("errors") or []) if str(item)],
        "network_attempted": bool(value.get("network_attempted")),
    }


def _candidate_digest(trade_date: str, selection: Mapping[str, Any], candidates: list[dict[str, Any]], config: ProducerConfig, tools: AcquisitionTools) -> tuple[str, dict[str, Any]]:
    import hashlib

    from . import core

    source_hashes = {
        "review_core_implementation": core._implementation_source_hashes(),
        "acquisition_config": config.fingerprint(),
        "acquisition_tools": {
            "discover": _tool_fingerprint(tools.discover),
            "capture": _tool_fingerprint(tools.capture),
            "asr": _tool_fingerprint(tools.asr),
        },
        "candidate_sha256": hashlib.sha256(_canonical(candidates)).hexdigest(),
        "discovery_attempt": _stable_discovery_attempt(selection.get("discovery_attempt") or {}),
    }
    payload = {
        "contract": core.SCHEMA_VERSION,
        "trade_date": trade_date,
        "selection": {
            "bv_id": selection.get("bv_id", ""),
            "title": selection.get("title", ""),
            "upload_date": selection.get("upload_date", ""),
            "date_scope": selection.get("date_scope", "DAILY_VIDEO_NOT_LOCKED"),
        },
        "source_sha256": source_hashes,
    }
    return hashlib.sha256(_canonical(payload)).hexdigest(), source_hashes


def _write_acquired_run(
    *,
    trade_date: str,
    data_root: Path,
    run_id: str,
    input_digest: str,
    selection: Mapping[str, Any],
    candidates: list[dict[str, Any]],
    source_hashes: dict[str, Any],
    capture_result: dict[str, Any],
    media_ref: dict[str, Any] | None,
    asr_result: dict[str, Any],
    asr_files: list[dict[str, Any]],
    aliases: list[dict[str, Any]],
    independent_review_input: Mapping[str, Any] | None,
    acquisition_count: int,
    asr_execution_count: int,
    network_used: bool,
    discovery_attempt: Mapping[str, Any] | None = None,
    advance_current: bool = True,
) -> dict[str, Any]:
    from . import core

    bv_id = str(selection.get("bv_id") or "")
    run_rel = f"review/{trade_date}/runs/{run_id}"
    run_dir = data_root / run_rel
    if run_dir.exists():
        raise core.ImmutableRunError(f"immutable run already exists without idempotent current: {run_dir}")
    stage = run_dir.parent / f".{run_id}.staging"
    if stage.exists():
        raise core.ImmutableRunError(f"staging run already exists: {stage}")
    stage.mkdir(parents=True, exist_ok=False)
    refs: list[dict[str, Any]] = []
    try:
        if media_ref:
            # Media is content-addressed outside the immutable run and is
            # referenced by the run manifest without being copied again.
            refs.append(dict(media_ref))
        audio_ref = capture_result.get("_audio_ref")
        if isinstance(audio_ref, Mapping):
            refs.append(dict(audio_ref))
        _artifact(
            stage,
            run_rel,
            "source_index.json",
            "source_index",
            {
                "schema_version": "ReviewCoreSourceIndexV1",
                "trade_date": trade_date,
                "run_id": run_id,
                "selected_video": dict(selection),
                "candidates": candidates,
                "network_used": network_used,
                "discovery_attempt": dict(discovery_attempt or {}),
            },
            refs,
        )
        _artifact(
            stage,
            run_rel,
            "video_session.json",
            "video_session",
            {
                "schema_version": "ReviewCoreVideoSessionV1",
                "trade_date": trade_date,
                "target_trade_date": trade_date,
                "run_id": run_id,
                "bv_id": bv_id,
                "title": str(selection.get("title") or ""),
                "upload_date": str(selection.get("upload_date") or ""),
                "date_scope": str(selection.get("date_scope") or "DAILY_VIDEO_NOT_LOCKED"),
                "discovery_status": str(selection.get("discovery_status") or "DAILY_VIDEO_NOT_LOCKED"),
                "producer_identity": "review_core.standalone_producer",
                "network_used": network_used,
                "import_mode": "ACQUIRE_PUBLIC_NO_COOKIES" if bv_id else "NO_MATCH",
                "source_sha256": source_hashes,
            },
            refs,
        )

        capture_paths: dict[str, list[str]] = {key: [] for key in ("media_files", "audio_files", "subtitle_files", "transcript_files", "segment_files", "token_files", "asr_run_manifests", "metadata_files")}
        if media_ref:
            capture_paths["media_files"].append(media_ref["path"])
        if isinstance(audio_ref, Mapping):
            capture_paths["audio_files"].append(str(audio_ref.get("path") or ""))
        capture_payload = {
            "schema_version": core.CAPTURE_SCHEMA_VERSION,
            "trade_date": trade_date,
            "bv_id": bv_id,
            "status": str(capture_result.get("status") or ("CAPTURED" if media_ref else "NOT_RUN")),
            "capture_route": str(capture_result.get("capture_route") or "PUBLIC_NO_COOKIES"),
            "network_used": network_used,
            "download_count": acquisition_count,
            "ffmpeg_status": "MISSING" if capture_result.get("ffmpeg_missing") else "NOT_REQUIRED",
            "access_status": str(capture_result.get("access_status") or "PUBLIC"),
            "cannot_confirm": [str(capture_result.get("reason"))] if capture_result.get("reason") else [],
            **capture_paths,
        }
        _artifact(stage, run_rel, "capture_manifest.json", "capture_manifest", capture_payload, refs)
        _artifact(
            stage,
            run_rel,
            "receipts/discovery.json",
            "phase_receipt",
            {
                "phase": "discovery",
                "status": str(selection.get("discovery_status") or "DAILY_VIDEO_NOT_LOCKED"),
                "error": str(selection.get("discovery_error") or ""),
                "network_used": network_used,
                "discovery_attempt": dict(discovery_attempt or selection.get("discovery_attempt") or {}),
                "routes": list((discovery_attempt or selection.get("discovery_attempt") or {}).get("routes") or []),
            },
            refs,
        )
        _artifact(
            stage,
            run_rel,
            "receipts/capture.json",
            "phase_receipt",
            {"phase": "capture", "status": capture_payload["status"], "access_status": capture_payload["access_status"], "ffmpeg_status": capture_payload["ffmpeg_status"], "download_count": acquisition_count},
            refs,
        )

        pointer_paths: dict[str, str] = {}
        for item in asr_files:
            key = str(item.get("key") or "")
            local_name = f"asr/{key or _safe_name(str(item.get('name') or 'artifact'))}"
            source = Path(str(item["source_path"]))
            copied = _artifact_copy(stage, run_rel, source, local_name, {"raw_path": "transcript", "segments_path": "segment", "tokens_path": "asr_token", "trace_path": "asr_trace"}.get(key, "asr_support"), refs)
            pointer_paths[key] = f"{run_rel}/{local_name}"
        pointer_status = "CURRENT_ASR_STOCKDICT_READY" if asr_files and str(asr_result.get("status")) in {"OK", "ASR_REVIEW_REQUIRED"} else "NOT_AVAILABLE"
        pointer_payload: dict[str, Any] = {
            "schema_version": core.ASR_POINTER_SCHEMA_VERSION,
            "trade_date": trade_date,
            "bv": bv_id,
            "status": pointer_status,
            "engine": str(asr_result.get("engine") or "FunASR"),
            "raw_asr_path": pointer_paths.get("raw_path", ""),
            "segment_path": pointer_paths.get("segments_path", ""),
            "tokens_path": pointer_paths.get("tokens_path", ""),
            "trace_path": pointer_paths.get("trace_path", ""),
            "referenced_artifacts": [value for value in pointer_paths.values() if value],
            "stockdict_status": "STOCKDICT_REVIEW_REQUIRED" if aliases else "NOT_AVAILABLE",
        }
        _artifact(stage, run_rel, "asr/current_asr_pointer.json", "asr_pointer", pointer_payload, refs)
        _artifact(
            stage,
            run_rel,
            "receipts/asr.json",
            "phase_receipt",
            {"phase": "asr", "status": str(asr_result.get("status") or "NOT_RUN"), "execution_count": asr_execution_count, "stockdict_status": pointer_payload["stockdict_status"]},
            refs,
        )

        gap_rows = []
        if independent_review_input:
            supplied_rows = independent_review_input.get("gap_rows") or independent_review_input.get("video_gap_rows") or []
            if isinstance(supplied_rows, list):
                gap_rows = json.loads(json.dumps(supplied_rows, ensure_ascii=False))
        gap_payload = {
            "schema_version": core.GAP_SCHEMA_VERSION,
            "trade_date": trade_date,
            "bv_id": bv_id,
            "status": "VIDEO_GAP_AUDIT_READY" if gap_rows else ("DAILY_VIDEO_NOT_LOCKED" if not bv_id else "VIDEO_GAP_AUDIT_EMPTY"),
            "gap_rows": gap_rows,
            "gap_row_count": len(gap_rows),
            "targeted_spotcheck_count": sum(1 for row in gap_rows if isinstance(row, Mapping) and str(row.get("gap_type") or "") in {"ASR_TARGETED_SPOTCHECK", "ASR_SEGMENT_SPOTCHECK_REQUIRED"}),
            "evidence_boundary": "VIDEO_ENHANCEMENT_ONLY; INDEPENDENT_FACTS_UNCHANGED",
            "independent_fact_ids": [str(item.get("fact_id")) for item in (independent_review_input or {}).get("facts", []) if isinstance(item, Mapping) and item.get("fact_id")],
        }
        _artifact(stage, run_rel, "video_gap_audit.json", "video_gap_audit", gap_payload, refs)
        _artifact(
            stage,
            run_rel,
            "receipts/gap_audit.json",
            "phase_receipt",
            {"phase": "gap_audit", "status": gap_payload["status"], "row_count": gap_payload["gap_row_count"], "evidence_boundary": gap_payload["evidence_boundary"]},
            refs,
        )

        independent_payload = dict(independent_review_input or {})
        if independent_payload:
            _artifact(stage, run_rel, "independent_review.json", "independent_review", independent_payload, refs)
        if aliases:
            _artifact(stage, run_rel, "asr/stockdict_alias_trace.json", "stockdict_alias_trace", {"aliases": aliases, "status": "STOCKDICT_REVIEW_REQUIRED"}, refs)

        transcript_ref = next((ref for ref in refs if ref["kind"] == "transcript"), None)
        cannot_confirm: list[str] = []
        if not bv_id:
            cannot_confirm.append("DAILY_VIDEO_NOT_LOCKED: no exact-date or permitted late target video")
        if selection.get("discovery_error"):
            cannot_confirm.append(f"discovery failed: {selection['discovery_error']}")
        if capture_result.get("reason"):
            cannot_confirm.append(str(capture_result["reason"]))
        if str(asr_result.get("status") or "").upper() in {"FAILED", "ASR_FAILED"}:
            cannot_confirm.append(str(asr_result.get("reason") or "ASR execution failed"))
        if aliases:
            cannot_confirm.append("stock dictionary aliases require raw-to-normalized review")
        if capture_result.get("ffmpeg_missing"):
            cannot_confirm.append("ffmpeg is unavailable; media/audio alignment is incomplete")
        if selection.get("discovery_error") or capture_result.get("status") in {"ACCESS_BLOCKED", "FFMPEG_NOT_AVAILABLE", "CAPTURE_NOT_AVAILABLE", "WRONG_UPLOADER"} or str(asr_result.get("status") or "").upper() in {"FAILED", "ASR_FAILED"}:
            _artifact(
                stage,
                run_rel,
                "error.json",
                "error",
                {
                    "capture_status": capture_result.get("status"),
                    "asr_status": asr_result.get("status"),
                    "reason": capture_result.get("reason") or asr_result.get("reason") or "phase failed",
                    "safety_flags": {name: False for name in core.SAFETY_FLAG_NAMES},
                },
                refs,
            )
        capture_status = str(capture_result.get("status") or ("CAPTURED" if media_ref else "NOT_RUN")) if bv_id else "NOT_RUN"
        asr_status = "ASR_FAILED" if str(asr_result.get("status") or "").upper() in {"FAILED", "ASR_FAILED"} else (str(asr_result.get("status") or "ASR_REVIEW_REQUIRED") if bv_id else "NOT_RUN")
        if asr_status == "OK":
            asr_status = "ASR_REVIEW_REQUIRED"
        stockdict_status = "STOCKDICT_REVIEW_REQUIRED" if aliases else ("STOCKDICT_READY" if asr_files else "NOT_AVAILABLE")
        output_sha = {ref["path"]: ref["sha256"] for ref in refs}
        manifest = {
            "schema_version": core.SCHEMA_VERSION,
            "trade_date": trade_date,
            "run_id": run_id,
            "bv_id": bv_id,
            "title": str(selection.get("title") or ""),
            "upload_date": str(selection.get("upload_date") or ""),
            "target_trade_date": trade_date,
            "date_scope": str(selection.get("date_scope") or "DAILY_VIDEO_NOT_LOCKED"),
            "discovery_status": str(selection.get("discovery_status") or "DAILY_VIDEO_NOT_LOCKED"),
            "discovery_error": str(selection.get("discovery_error") or ""),
            "discovery_attempt": dict(discovery_attempt or selection.get("discovery_attempt") or {}),
            "discovery_routes": list((discovery_attempt or selection.get("discovery_attempt") or {}).get("routes") or []),
            "capture_status": capture_status,
            "access_status": str(capture_result.get("access_status") or "PUBLIC"),
            "ffmpeg_status": "MISSING" if capture_result.get("ffmpeg_missing") else "NOT_REQUIRED",
            "asr_status": asr_status,
            "asr_segment_count": _segment_count_from_files(asr_files),
            "gap_status": gap_payload["status"],
            "gap_row_count": gap_payload["gap_row_count"],
            "targeted_spotcheck_count": gap_payload["targeted_spotcheck_count"],
            "media_sha256": media_ref["sha256"] if media_ref else "",
            "transcript_sha256": transcript_ref["sha256"] if transcript_ref else "",
            "stockdict_status": stockdict_status,
            "stockdict_aliases": aliases,
            "stockdict_trace_path": f"{run_rel}/asr/stockdict_alias_trace.json" if aliases else "",
            "cannot_confirm": list(dict.fromkeys(cannot_confirm)),
            "producer_identity": {"name": "review_core.standalone_producer", "module": "review_core.producer", "contract": "single_video_producer"},
            "producer": {"name": "review_core.standalone_producer", "module": "review_core.producer"},
            "implementation_sha256": source_hashes.get("review_core_implementation", {}),
            "input_sha256": source_hashes,
            "output_sha256": output_sha,
            "artifact_refs": refs,
            "media_refs": [ref for ref in refs if ref["kind"] == "media"],
            "audio_refs": [ref for ref in refs if ref["kind"] == "audio"],
            "network_used": network_used,
            "network_allowed": network_used,
            "acquisition_mode": "acquire" if bv_id else "acquire_no_match",
            "acquisition_count": acquisition_count,
            "download_count": acquisition_count,
            "asr_execution_count": asr_execution_count,
            "asr_count": asr_execution_count,
            "independent_review": independent_payload,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
            "video_evidence_boundary": "ENHANCEMENT_ONLY_INDEPENDENT_REVIEW_NOT_VIDEO_AUGMENTED",
        }
        manifest_path = _artifact(stage, run_rel, "manifest.json", "manifest", manifest, refs)
        # Keep output_sha256 immutable and intentionally exclude manifest itself.
        manifest["artifact_refs"] = refs
        receipt = {
            "schema_version": core.RECEIPT_SCHEMA_VERSION,
            "trade_date": trade_date,
            "run_id": run_id,
            "status": (
                str(selection.get("discovery_status") or "DAILY_VIDEO_NOT_LOCKED")
                if str(selection.get("discovery_status") or "").upper() in {"NO_NEW_VIDEO", "UP_LOOKUP_BLOCKED"}
                else ("DAILY_VIDEO_NOT_LOCKED" if not bv_id else ("ACQUIRE_FAILED" if asr_status == "ASR_FAILED" or capture_status in {"ACCESS_BLOCKED", "FFMPEG_NOT_AVAILABLE", "CAPTURE_NOT_AVAILABLE", "WRONG_UPLOADER"} else "ACQUIRED"))
            ),
            "input_digest": input_digest,
            "acquisition_count": acquisition_count,
            "asr_execution_count": asr_execution_count,
            "network_used": network_used,
            "discovery_attempt": dict(discovery_attempt or selection.get("discovery_attempt") or {}),
            "current_advanced": bool(advance_current),
            "manifest_sha256": _sha256(manifest_path),
            "safety_flags": {name: False for name in core.SAFETY_FLAG_NAMES},
        }
        receipt_path = stage / "receipt.json"
        _write_json(receipt_path, receipt)
        receipt_sha = _sha256(receipt_path)
        run_dir.parent.mkdir(parents=True, exist_ok=True)
        os.replace(stage, run_dir)
        current = {
            "schema_version": core.CURRENT_SCHEMA_VERSION,
            "trade_date": trade_date,
            "run_id": run_id,
            "input_digest": input_digest,
            "run_path": run_rel,
            "manifest_path": f"{run_rel}/manifest.json",
            "manifest_sha256": _sha256(run_dir / "manifest.json"),
            "receipt_sha256": receipt_sha,
            "safety_flags": {name: False for name in core.SAFETY_FLAG_NAMES},
        }
        current_path = data_root / "review" / trade_date / "current.json"
        if advance_current:
            _write_json(current_path, current)
            inspected = core.inspect_bundle(trade_date, data_root)
        else:
            # Failed refreshes remain immutable evidence, but an accepted
            # prior current pointer is never replaced by the failure.
            inspected = core._read_json(run_dir / "manifest.json")
        return {
            "status": inspected["discovery_status"],
            "idempotent": False,
            "run_id": run_id,
            "run_dir": str(run_dir),
            "current_path": str(current_path),
            "current_advanced": bool(advance_current),
            "manifest": inspected,
            "acquisition_count": acquisition_count,
            "asr_execution_count": asr_execution_count,
        }
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def acquire_video(
    trade_date: str,
    *,
    data_root: Path | str | None = None,
    allow_network: bool,
    tools: AcquisitionTools | None = None,
    acquisition_tools: AcquisitionTools | Mapping[str, Any] | None = None,
    config: ProducerConfig | None = None,
    source_root: Path | str | None = None,
    funasr_path: Path | str | None = None,
    ffmpeg_path: Path | str | None = None,
    ytdlp_path: Path | str | None = None,
    python_path: Path | str | None = None,
    target_mid: str | None = None,
    target_uploader: str | None = None,
    independent_review_input: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Acquire one exact-date video with process-safe idempotency."""

    from . import core

    target = core.normalize_trade_date(trade_date)
    if not allow_network:
        raise core.EvidenceValidationError("acquire mode requires explicit --allow-network")
    if config is None:
        config = ProducerConfig(
            data_root=Path(data_root) if data_root is not None else Path(__file__).resolve().parent / ".runtime",
            source_root=Path(source_root) if source_root is not None else None,
            funasr_path=Path(funasr_path) if funasr_path is not None else None,
            ffmpeg_path=Path(ffmpeg_path) if ffmpeg_path is not None else None,
            ytdlp_path=Path(ytdlp_path) if ytdlp_path is not None else None,
            python_path=Path(python_path) if python_path is not None else None,
            target_mid=target_mid or "3546557003598528",
            target_uploader=target_uploader or "比巴卜作手",
            network_allowed=True,
        )
    elif not isinstance(config, ProducerConfig):
        raise TypeError("config must be a ProducerConfig")
    if not allow_network and config.network_allowed:
        allow_network = True
    selected_input = tools if tools is not None else acquisition_tools
    if isinstance(selected_input, Mapping):
        selected_tools = AcquisitionTools(
            discover=selected_input.get("discover"),
            capture=selected_input.get("capture"),
            asr=selected_input.get("asr"),
        )
    else:
        selected_tools = selected_input or AcquisitionTools()
    if selected_tools.discover is None:
        selected_tools = AcquisitionTools(_default_discover, selected_tools.capture, selected_tools.asr)
    if selected_tools.capture is None:
        selected_tools = AcquisitionTools(selected_tools.discover, _default_capture, selected_tools.asr)
    if selected_tools.asr is None:
        selected_tools = AcquisitionTools(selected_tools.discover, selected_tools.capture, _default_asr)
    runtime = config.data_root
    lock_path = runtime / "review" / target / ".acquire.lock"
    with _DateLock(lock_path):
        try:
            candidates_raw = _invoke(selected_tools.discover, target, config)
            discovery_status = str(getattr(candidates_raw, "discovery_status", "DISCOVERY_CANDIDATES_READY") or "DISCOVERY_CANDIDATES_READY")
            discovery_routes = [dict(item) for item in (getattr(candidates_raw, "discovery_routes", []) or []) if isinstance(item, Mapping)]
            discovery_errors = [str(item) for item in (getattr(candidates_raw, "discovery_errors", []) or []) if str(item)]
            discovery_attempt = getattr(candidates_raw, "discovery_attempt", None)
            if isinstance(candidates_raw, Mapping):
                candidates_raw = candidates_raw.get("candidates") or candidates_raw.get("items") or []
            candidates = [dict(item) for item in (candidates_raw or []) if isinstance(item, Mapping)]
            discovery_error = ""
        except Exception as exc:
            # Discovery is a public boundary: preserve a fail-closed no-lock
            # bundle with the error receipt rather than substituting an old BV.
            candidates = []
            discovery_error = str(exc)
            # Keep legacy injected-adapter exception semantics for compatibility
            # while the explicit attempt/receipt carries the precise blocked
            # lookup state.  The default public adapter returns a
            # DiscoveryCandidates(UP_LOOKUP_BLOCKED) directly.
            discovery_status = "DAILY_VIDEO_NOT_LOCKED"
            discovery_attempt_status = "UP_LOOKUP_BLOCKED"
            discovery_routes = []
            discovery_errors = [discovery_error]
            discovery_attempt = {
                "status": discovery_attempt_status,
                "routes": [],
                "errors": list(discovery_errors),
                "network_attempted": True,
            }
        selection = core.select_target_video(
            candidates,
            target,
            target_mid=config.target_mid,
            target_uploader=config.target_uploader,
        )
        if discovery_status == "UP_LOOKUP_BLOCKED" and discovery_errors:
            discovery_error = "; ".join(discovery_errors)
        elif discovery_status == "DAILY_VIDEO_NOT_LOCKED" and discovery_errors:
            discovery_error = "; ".join(discovery_errors)
        elif discovery_status == "DISCOVERY_CANDIDATES_READY":
            discovery_error = ""
        if discovery_error:
            selection["discovery_error"] = discovery_error
        selection["discovery_status"] = (
            "TARGET_BV_LOCKED" if selection.get("bv_id") and discovery_status == "DISCOVERY_CANDIDATES_READY" else discovery_status
        )
        selection["discovery_routes"] = discovery_routes
        selection["discovery_errors"] = discovery_errors
        selection["discovery_attempt"] = discovery_attempt or {
            "status": discovery_status,
            "routes": discovery_routes,
            "errors": discovery_errors,
            "network_attempted": True,
        }
        input_digest, source_hashes = _candidate_digest(target, selection, candidates, config, selected_tools)
        current = core._existing_current(runtime, target)
        run_id = core._run_id(target, {"selection": selection, "source_hashes": source_hashes}, input_digest)
        if current is not None and current.get("input_digest") == input_digest:
            inspected = core.inspect_bundle(target, runtime)
            return {
                "status": inspected["discovery_status"],
                "idempotent": True,
                "run_id": run_id,
                "run_dir": str(runtime / "review" / target / "runs" / run_id),
                "current_path": str(runtime / "review" / target / "current.json"),
                "manifest": inspected,
                "acquisition_count": 0,
                "asr_execution_count": 0,
            }
        if current is not None:
            current_manifest = core.inspect_bundle(target, runtime)
        else:
            current_manifest = None

        capture_result: dict[str, Any] = {"status": "NOT_RUN"}
        media_ref: dict[str, Any] | None = None
        acquisition_count = 0
        asr_execution_count = 0
        asr_result: dict[str, Any] = {"status": "NOT_RUN"}
        asr_files: list[dict[str, Any]] = []
        aliases: list[dict[str, Any]] = []
        work_dir = runtime / ".acquire_work" / target / (str(selection.get("bv_id") or "no-match"))
        work_dir.mkdir(parents=True, exist_ok=True)
        if selection.get("bv_id"):
            bv_id = str(selection["bv_id"])
            # The date lock protects one target run; this nested BV lock also
            # protects cache creation when the same BV is discovered for
            # multiple dates concurrently.
            with _DateLock(runtime / "locks" / "bv" / f"{bv_id}.lock"):
                cached_media = _find_cached_media(runtime, bv_id)
                if cached_media:
                    media_ref = {"kind": "media", "path": cached_media["path"], "sha256": cached_media["sha256"], "size": (runtime / cached_media["path"]).stat().st_size, "import_mode": "REUSE_CONTENT_ADDRESSED"}
                    capture_result = {"status": "REUSED_CONTENT", "access_status": "CACHE"}
                    if cached_media.get("audio_path"):
                        cached_audio = runtime / cached_media["audio_path"]
                        capture_result["audio_path"] = str(cached_audio)
                        capture_result["_audio_ref"] = {
                            "kind": "audio",
                            "path": cached_media["audio_path"],
                            "sha256": _sha256(cached_audio),
                            "size": cached_audio.stat().st_size,
                            "import_mode": "REUSE_CONTENT_ADDRESSED",
                        }
                else:
                    try:
                        capture_result = _safe_tool_result(_invoke(selected_tools.capture, selection, work_dir, config), "CAPTURED")
                    except AccessBlockedError as exc:
                        capture_result = {"status": "ACCESS_BLOCKED", "reason": str(exc), "access_status": "PUBLIC_NO_COOKIES"}
                    if config.ffmpeg_path is not None and not config.ffmpeg_path.is_file() and capture_result.get("status") not in {"ACCESS_BLOCKED", "CAPTURE_NOT_AVAILABLE"}:
                        capture_result["ffmpeg_missing"] = True
                        capture_result["status"] = "FFMPEG_NOT_AVAILABLE"
                    media_value = capture_result.get("media_path") or selection.get("media_path")
                    media_path = Path(str(media_value)) if media_value else None
                    if capture_result.get("status") == "ACCESS_BLOCKED":
                        # A blocked public route must never be satisfied by a
                        # stale/old media path returned alongside the error.
                        media_path = None
                    if media_path is not None and media_path.is_file():
                        digest = _sha256(media_path)
                        destination_relative = Path("media") / bv_id / digest / _safe_name(media_path.name)
                        destination = runtime / destination_relative
                        _copy_atomic(media_path, destination)
                        media_ref = {"kind": "media", "path": destination_relative.as_posix(), "sha256": digest, "size": destination.stat().st_size, "import_mode": "MATERIALIZED"}
                        acquisition_count = 1 if capture_result.get("downloaded", capture_result.get("download", True)) else 0
                        audio_value = capture_result.get("audio_path") or capture_result.get("audio_file")
                        audio_path = Path(str(audio_value)) if audio_value else None
                        audio_relative_for_index = ""
                        if audio_path is not None and audio_path.is_file():
                            audio_digest = _sha256(audio_path)
                            audio_relative = Path("audio") / bv_id / audio_digest / _safe_name(audio_path.name)
                            audio_destination = runtime / audio_relative
                            _copy_atomic(audio_path, audio_destination)
                            capture_result["_audio_ref"] = {
                                "kind": "audio",
                                "path": audio_relative.as_posix(),
                                "sha256": audio_digest,
                                "size": audio_destination.stat().st_size,
                                "import_mode": "MATERIALIZED",
                            }
                            audio_relative_for_index = audio_relative.as_posix()
                        index_path = runtime / "media" / bv_id / "index.json"
                        _write_json(
                            index_path,
                            [{"path": destination_relative.as_posix(), "sha256": digest, "name": destination.name, "audio_path": audio_relative_for_index}],
                        )
                if media_ref:
                    cached_asr = _find_cached_asr(runtime, bv_id, media_ref["sha256"])
                    if cached_asr:
                        asr_result = {"status": cached_asr["status"], "aliases": cached_asr.get("aliases") or []}
                        aliases = normalize_stockdict_aliases(cached_asr.get("aliases") or [])
                        asr_files = [{"key": item.get("key", ""), "name": item.get("name", ""), "source_path": str(runtime / item["path"])} for item in cached_asr["files"]]
                    else:
                        try:
                            asr_input = Path(str(capture_result.get("audio_path") or ""))
                            if not asr_input.is_file():
                                asr_input = runtime / media_ref["path"]
                            asr_result = _safe_tool_result(_invoke(selected_tools.asr, asr_input, work_dir, config), "ASR_REVIEW_REQUIRED")
                        except Exception as exc:
                            asr_result = {"status": "FAILED", "reason": str(exc)}
                        if asr_result.get("trade_date") and str(asr_result.get("trade_date")) != target:
                            asr_result = {"status": "FAILED", "reason": "ASR pointer exact-date mismatch"}
                        elif asr_result.get("bv") and str(asr_result.get("bv")) != bv_id:
                            asr_result = {"status": "FAILED", "reason": "ASR pointer BV mismatch"}
                        aliases = normalize_stockdict_aliases(asr_result.get("aliases") or [])
                        asr_execution_count = 1
                        cache_dir = runtime / "asr" / "cache" / bv_id / media_ref["sha256"]
                        cache_entries: list[dict[str, Any]] = []
                        for key in ("raw_path", "segments_path", "tokens_path", "trace_path"):
                            value = asr_result.get(key)
                            source = Path(str(value)) if value else None
                            if source is None or not source.is_file():
                                continue
                            destination_relative = _asr_cache_relative_path(
                                runtime,
                                bv_id,
                                media_ref["sha256"],
                                source,
                            )
                            destination = runtime / destination_relative
                            digest = _copy_atomic(source, destination)
                            cache_entries.append({"key": key, "path": destination_relative.as_posix(), "sha256": digest, "name": destination.name, "status": str(asr_result.get("status") or "ASR_REVIEW_REQUIRED"), "aliases": aliases})
                            asr_files.append({"key": key, "name": destination.name, "source_path": str(destination)})
                        # Store a status sentinel even when FunASR failed or
                        # returned no artifacts, so a duplicate request cannot
                        # execute the same ASR job again without a new media SHA.
                        if not cache_entries:
                            cache_entries.append({"status": str(asr_result.get("status") or "ASR_REVIEW_REQUIRED"), "aliases": aliases})
                        _write_json(cache_dir / "index.json", cache_entries)
        refresh_failed = bool(
            selection.get("discovery_error")
            or discovery_status == "UP_LOOKUP_BLOCKED"
            or not selection.get("bv_id")
            or capture_result.get("status") in {"ACCESS_BLOCKED", "FFMPEG_NOT_AVAILABLE", "CAPTURE_NOT_AVAILABLE", "WRONG_UPLOADER"}
            or str(asr_result.get("status") or "").upper() in {"FAILED", "ASR_FAILED"}
        )
        return _write_acquired_run(
            trade_date=target,
            data_root=runtime,
            run_id=run_id,
            input_digest=input_digest,
            selection=selection,
            candidates=candidates,
            source_hashes=source_hashes,
            capture_result=capture_result,
            media_ref=media_ref,
            asr_result=asr_result,
            asr_files=asr_files,
            aliases=aliases,
            independent_review_input=independent_review_input,
            acquisition_count=acquisition_count,
            asr_execution_count=asr_execution_count,
            network_used=True,
            discovery_attempt=selection.get("discovery_attempt") or {},
            advance_current=(
                current is None
                or not refresh_failed
                or str((current_manifest or {}).get("discovery_status") or "") != "TARGET_BV_LOCKED"
            ),
        )


__all__ = [
    "AccessBlockedError",
    "AcquisitionTools",
    "ProducerConfig",
    "acquire_video",
    "audit_gap_alignment",
    "normalize_stockdict_aliases",
]
