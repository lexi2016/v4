"""Mac-owned, research-only wrapper for the legacy WeChat profile probe.

The legacy V3 probe can provide a useful profile-page hint, but a profile
response is not an exact article identity.  This wrapper deliberately keeps
the old statuses while making the boundary machine-readable: every outcome
is ``URL_REQUIRED``, never creates a run, and never publishes anything.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any


BIZ = "Mzk2NDUyNjUwNQ=="
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
)
BLOCK_MARKERS = (
    "环境异常",
    "verify",
    "验证码",
    "访问过于频繁",
    "该内容已被发布者删除",
    "此内容因违规无法查看",
    "请先登录",
    "openid",
    "connect.qq.com",
)
RECEIPT_SCHEMA = "v3_5.wechat_profile_probe_receipt.v1"
_PROFILE_URL = "https://mp.weixin.qq.com/mp/profile_ext?action=home&__biz={biz}&scene=124"
MAX_PROFILE_BODY_BYTES = 2 * 1024 * 1024

_FORMAL_DATA_ROOT = (
    Path.home()
    / "Library"
    / "Application Support"
    / "com.lexi.v35.local"
    / "state"
    / "data"
)
_DOCUMENTS_CODEX_ROOT = Path.home() / "Documents" / "Codex"


def _path_is_under(path: Path, base: Path) -> bool:
    return path == base or base in path.parents


def _reject_symlink_components(path: Path) -> None:
    """Reject a symlink at the output leaf or anywhere in its ancestry."""

    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            if current.is_symlink():
                raise ValueError(f"symlink path is not allowed: {path}")
        except OSError as error:
            raise ValueError(f"path cannot be inspected for symlink safety: {path}") from error


def _validate_scoped_path(value: Path | str, *, label: str) -> Path:
    """Keep receipts and probe outputs in formal data or named test roots."""

    try:
        raw = os.fspath(value)
    except TypeError as error:
        raise ValueError(f"{label} path is invalid") from error
    if not isinstance(raw, str) or not raw or "\\" in raw:
        raise ValueError(f"{label} path is outside allowed roots")
    if re.match(r"^(?:[A-Za-z]:|//|\\\\)", raw):
        raise ValueError(f"{label} path is outside allowed roots")
    path = Path(os.path.normpath(os.path.expanduser(raw)))
    if not path.is_absolute():
        raise ValueError(f"{label} path must be absolute")
    if any(part.casefold() in {"desktop", "windows"} for part in path.parts):
        raise ValueError(f"{label} path is outside allowed roots")

    formal = Path(os.path.normpath(os.fspath(_FORMAL_DATA_ROOT)))
    documents = Path(os.path.normpath(os.fspath(_DOCUMENTS_CODEX_ROOT)))
    in_test_root = False
    if _path_is_under(path, documents):
        for ancestor in (path, *path.parents):
            if _path_is_under(ancestor, documents) and ancestor.name.startswith(
                "v35-stage-selection-"
            ):
                in_test_root = True
                break
    if not _path_is_under(path, formal) and not in_test_root:
        raise ValueError(f"{label} path is outside allowed roots")
    _reject_symlink_components(path)
    return path


def _limited_text(value: Any) -> tuple[str, str]:
    if isinstance(value, bytes):
        if len(value) > MAX_PROFILE_BODY_BYTES:
            return "", "PROFILE_BODY_TOO_LARGE"
        return value.decode("utf-8", errors="ignore"), ""
    if isinstance(value, bytearray):
        value = bytes(value)
        if len(value) > MAX_PROFILE_BODY_BYTES:
            return "", "PROFILE_BODY_TOO_LARGE"
        return value.decode("utf-8", errors="ignore"), ""
    text = value if isinstance(value, str) else str(value or "")
    if len(text.encode("utf-8")) > MAX_PROFILE_BODY_BYTES:
        return "", "PROFILE_BODY_TOO_LARGE"
    return text, ""


def _read_limited_response(response: Any) -> tuple[str, str]:
    chunks: list[bytes] = []
    total = 0
    while total <= MAX_PROFILE_BODY_BYTES:
        chunk = response.read(min(64 * 1024, MAX_PROFILE_BODY_BYTES - total + 1))
        if not chunk:
            break
        if isinstance(chunk, str):
            chunk = chunk.encode("utf-8")
        elif isinstance(chunk, bytearray):
            chunk = bytes(chunk)
        if not isinstance(chunk, bytes):
            chunk = bytes(chunk)
        total += len(chunk)
        if total > MAX_PROFILE_BODY_BYTES:
            return "", "PROFILE_BODY_TOO_LARGE"
        chunks.append(chunk)
    return b"".join(chunks).decode("utf-8", errors="ignore"), ""


def _fetch_profile(biz: str, timeout: int = 30) -> tuple[str, int, str]:
    """Fetch one profile page without persisting cookies, tokens, or runs."""

    url = _PROFILE_URL.format(biz=biz)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Referer": "https://mp.weixin.qq.com/",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200))
            text, body_error = _read_limited_response(response)
            return text, status, body_error
    except Exception as error:  # network/anti-bot failures are probe outcomes
        return "", 0, f"{type(error).__name__}: {error}"


def _parse_articles(text: str) -> list[dict[str, str]]:
    """Parse the same title/link hint shape as the old V3 probe."""

    rows: list[dict[str, str]] = []
    title_matches = list(re.finditer(r"msg_title\s*=\s*[\"']([^\"']+)[\"']", text))
    link_matches = list(
        re.finditer(r"https://mp\.weixin\.qq\.com/s/[A-Za-z0-9_-]+", text)
    )
    for index, title_match in enumerate(title_matches):
        link = link_matches[index].group(0) if index < len(link_matches) else ""
        if not link:
            continue
        rows.append(
            {
                "title": title_match.group(1).strip(),
                "link": link,
                "source": "profile_html",
            }
        )
        if len(rows) >= 20:
            break
    return rows


def _fetch_result(value: Any) -> tuple[str, int, str]:
    """Normalize a test seam or transport adapter to the legacy tuple."""

    if isinstance(value, Mapping):
        text, body_error = _limited_text(value.get("text") or value.get("body") or "")
        return (
            text,
            int(value.get("status") or value.get("http_status") or 0),
            str(value.get("error") or value.get("fetch_error") or body_error),
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) != 3:
            raise ValueError("profile fetcher must return (text, status, error)")
        text, body_error = _limited_text(value[0])
        return text, int(value[1] or 0), str(value[2] or body_error)
    raise ValueError("profile fetcher returned an unsupported result")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path = _validate_scoped_path(Path(path), label="receipt")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        content = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
            "utf-8"
        )
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _default_receipt_path(out_dir: Path) -> Path:
    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
    return Path(out_dir) / f"probe_{stamp}.json"


def probe_wechat_account(
    biz: str = BIZ,
    last_date: str = "",
    *,
    fetcher: Callable[..., Any] | None = None,
    timeout: int = 30,
    receipt_path: Path | str | None = None,
    out_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Probe a public-account profile and write an auditable fail-closed receipt.

    ``PROBE_FOUND`` means that a profile page contained article-shaped hints;
    it does not establish the exact article URL or authorize a V3 run.  The
    returned receipt intentionally records that all three outcomes require an
    exact URL supplied by the user.
    """

    if receipt_path is not None and out_dir is not None:
        raise ValueError("provide receipt_path or out_dir, not both")
    fetch = fetcher or _fetch_profile
    text, http_status, fetch_error = _fetch_result(fetch(biz, timeout=timeout))
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    articles: list[dict[str, str]] = []
    if fetch_error:
        status = "PROBE_UNAVAILABLE"
        note = f"profile fetch failed: {fetch_error.replace('_', ' ').lower()}"
    elif any(marker.casefold() in text.casefold() for marker in BLOCK_MARKERS):
        status = "PROBE_BLOCKED"
        note = "profile response hit a verification/rate-limit marker; exact URL is required"
    else:
        articles = _parse_articles(text)
        if articles:
            status = "PROBE_FOUND"
            note = "profile article hint found; confirm the exact article URL before any run"
        else:
            status = "PROBE_UNAVAILABLE"
            note = "profile page contained no usable article list; exact URL is required"

    result: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA,
        "probe_type": "V3_LEGACY_WECHAT_PROFILE_HINT",
        "probed_at": now,
        "biz": biz,
        "last_date": last_date,
        "profile_url": _PROFILE_URL.format(biz=biz),
        "http_status": http_status,
        "fetch_error": fetch_error,
        "status": status,
        "note": note,
        "articles": articles,
        # A profile hint never establishes an exact identity.
        "hint_only": True,
        "url_required": True,
        "next_action": "URL_REQUIRED",
        "exact_url": None,
        "run_id": None,
        "run_created": False,
        "no_run_created": True,
        "no_run": True,
        "publish": False,
        "publish_allowed": False,
        "published": False,
        "no_publish": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    if receipt_path is None and out_dir is not None:
        receipt_path = _default_receipt_path(
            _validate_scoped_path(Path(out_dir), label="probe output")
        )
    if receipt_path is not None:
        resolved_receipt = _validate_scoped_path(Path(receipt_path), label="receipt")
        result["receipt_path"] = str(resolved_receipt)
        # Preserve the legacy wrapper's machine-readable path vocabulary.
        result["output_path"] = str(resolved_receipt)
        _write_json(resolved_receipt, result)
    return result


# Names used by callers that describe the operation as a profile probe rather
# than an account probe.  They intentionally share the exact same fail-closed
# implementation and receipt schema.
probe_wechat_profile = probe_wechat_account
run_probe = probe_wechat_account


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe a WeChat profile for research-only hints")
    parser.add_argument("--biz", default=BIZ)
    parser.add_argument("--last-date", default="")
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    result = probe_wechat_account(
        args.biz,
        args.last_date,
        receipt_path=args.receipt,
        out_dir=args.out,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
