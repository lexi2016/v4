"""Local, fail-closed entrypoint for read-only WeChat article intake.

The actual HTML/image collector is reused from the installed intake skill.
This adapter owns the URL, identity, and run-output security boundary.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import runpy
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from pathlib import PureWindowsPath
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wechat_common import normalize_date, normalize_title, safe_run_path, write_json, _reject_symlink_components  # noqa: E402


WECHAT_HOST = "mp.weixin.qq.com"
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{1,256}$")
_CN_TZ = timezone(timedelta(hours=8))


def _intake_script() -> Path:
    local = Path(__file__).with_name("wechat_article_intake.py")
    candidates = (
        local,
        Path.home() / ".codex" / "skills" / "wechat-research-intake" / "scripts" / "wechat_article_intake.py",
        Path.home() / ".agents" / "skills" / "wechat-research-intake" / "scripts" / "wechat_article_intake.py",
    )
    for candidate in candidates:
        if candidate.is_file() and not candidate.is_symlink():
            return candidate.resolve()
    searched = ", ".join(str(candidate) for candidate in candidates)
    raise FileNotFoundError(f"WeChat intake implementation not found; searched: {searched}")


def canonical_token_from_url(url: str) -> str:
    """Validate an HTTPS public article URL and return its /s/ token."""

    raw = str(url or "").strip()
    parsed = urlsplit(raw)
    if parsed.scheme.lower() != "https" or parsed.hostname != WECHAT_HOST:
        raise ValueError("only https://mp.weixin.qq.com/s/<token> is allowed")
    if parsed.username or parsed.password or parsed.port:
        raise ValueError("WeChat URL must not contain credentials or a port")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2 or parts[0].lower() != "s" or not _TOKEN_RE.fullmatch(parts[1]):
        raise ValueError("WeChat URL must contain one canonical /s/<token> path")
    return parts[1]


def canonical_article_url(url: str) -> str:
    return f"https://{WECHAT_HOST}/s/{canonical_token_from_url(url)}"


def _first(mapping: dict, *names: str) -> str:
    for name in names:
        value = mapping.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _consistent(mapping: dict, names: tuple[str, ...], label: str, normalizer=None) -> str:
    """Return one identity value and reject conflicting aliases."""

    values: list[str] = []
    for name in names:
        raw = str(mapping.get(name) or "").strip()
        if raw:
            values.append(normalizer(raw) if normalizer else raw)
    if values and any(value != values[0] for value in values[1:]):
        raise ValueError(f"conflicting {label} fields")
    return values[0] if values else ""


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"{label} is not an integer")
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value.strip()) is None:
        raise ValueError(f"{label} is not an integer")
    number = int(value)
    if number <= 0:
        raise ValueError(f"{label} must be non-zero")
    return number


def _nonnegative_int(value: object, label: str) -> int:
    """Parse a count where an empty image universe is a valid article shape."""

    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"{label} is not an integer")
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value.strip()) is None:
        raise ValueError(f"{label} is not an integer")
    number = int(value)
    if number < 0:
        raise ValueError(f"{label} must be non-negative")
    return number


def _date_from_raw(raw: str) -> str:
    raw = raw.strip()
    # Offset-bearing publication timestamps must first be converted to the
    # article's China calendar day, not truncated at the first YYYY-MM-DD.
    if re.match(r"^20[0-9]{2}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:", raw):
        try:
            published = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("publish timestamp is invalid") from exc
        if published.tzinfo is None:
            published = published.replace(tzinfo=_CN_TZ)
        return published.astimezone(_CN_TZ).strftime("%Y%m%d")
    date_match = re.search(r"20\d{2}[-/]?\d{2}[-/]?\d{2}", raw)
    if date_match:
        return normalize_date(date_match.group(0), label="article date")
    digits = re.sub(r"\D", "", raw)
    if re.fullmatch(r"20\d{6}", digits):
        return normalize_date(digits, label="article date")
    try:
        timestamp = int(raw)
        if timestamp <= 0:
            raise ValueError
        return datetime.fromtimestamp(timestamp, tz=_CN_TZ).strftime("%Y%m%d")
    except (TypeError, ValueError, OverflowError, OSError) as exc:
        raise ValueError("publish date is missing or invalid") from exc


def _article_date(summary: dict) -> str:
    explicit_values = [
        normalize_date(str(summary[name]), label="article date")
        for name in ("article_date", "publish_date", "date")
        if str(summary.get(name) or "").strip()
    ]
    if explicit_values and any(value != explicit_values[0] for value in explicit_values[1:]):
        raise ValueError("conflicting article date fields")
    raw_values = [
        _date_from_raw(str(summary[name]).strip())
        for name in ("raw_publish_time", "publish_time", "published_at", "published_at_iso")
        if str(summary.get(name) or "").strip()
    ]
    if raw_values and any(value != raw_values[0] for value in raw_values[1:]):
        raise ValueError("conflicting publish time fields")
    explicit = explicit_values[0] if explicit_values else ""
    raw = raw_values[0] if raw_values else ""
    if explicit and raw and explicit != raw:
        raise ValueError("article date conflicts with publish time")
    if explicit:
        return explicit
    if raw:
        return raw
    raise ValueError("publish date is missing or invalid")


def validate_intake_identity(
    summary: dict,
    requested_url: str,
    *,
    allow_saved_html: bool = False,
) -> dict[str, str]:
    """Require non-blocked, non-partial content and exact article identity."""

    if not isinstance(summary, dict):
        raise ValueError("intake summary must be an object")
    expected_url = canonical_article_url(requested_url)
    expected_token = canonical_token_from_url(requested_url)
    observed_url = _consistent(summary, ("article_url", "url"), "article URL", canonical_article_url)
    if not observed_url or canonical_article_url(observed_url) != expected_url:
        raise ValueError("intake response URL/token does not match the request")
    observed_canonical_url = _consistent(summary, ("canonical_url",), "canonical URL", canonical_article_url)
    if observed_canonical_url and canonical_article_url(observed_canonical_url) != expected_url:
        raise ValueError("intake canonical URL conflicts with requested URL")
    observed_token = _consistent(summary, ("canonical_token", "token"), "canonical token")
    if observed_token and observed_token != expected_token:
        raise ValueError("intake canonical token conflicts with requested URL")

    label = _first(summary, "final_label", "decision", "status").upper()
    if "VERIFY" in label or "BLOCKED" in label:
        raise ValueError("WeChat verification/blocked page is not an article")
    if "ERROR" in label or "REJECTED" in label:
        raise ValueError("intake result is errored or rejected")
    if "PARTIAL" in label:
        # The fetch stage deliberately skips OCR.  Only the collector's
        # explicit NEED_OCR label is resumable in that state; saved-HTML or
        # any other partial result must not be promoted to an identity PASS.
        if not (label.endswith("NEED_OCR") and _first(summary, "ocr_status").upper() == "OCR_SKIPPED"):
            raise ValueError("intake result is partial")
    if _first(summary, "fetch_error"):
        raise ValueError("intake transport is partial or errored")
    try:
        http_status = int(summary.get("http_status") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid HTTP status") from exc
    html_bytes = _positive_int(summary.get("html_bytes"), "html_bytes")
    if http_status != 200 and not allow_saved_html:
        raise ValueError("intake requires HTTP 200")
    if summary.get("article_body_found") is not True:
        raise ValueError("article body block is missing")
    _positive_int(summary.get("text_preview_length"), "text_preview_length")
    image_count = _nonnegative_int(summary.get("image_count"), "image_count")
    downloaded = _nonnegative_int(summary.get("downloaded_image_count"), "downloaded_image_count")
    if downloaded != image_count:
        raise ValueError("image download is partial")

    title = _consistent(summary, ("title", "article_title"), "title", normalize_title)
    account = _consistent(summary, ("account_name", "account", "nickname"), "account")
    biz = _consistent(summary, ("biz", "__biz"), "biz")
    content_hash = _consistent(
        summary, ("content_hash", "evidence_hash", "html_sha256"), "content hash",
        lambda value: value.lower(),
    )
    if not all((title, account, biz, content_hash)):
        raise ValueError("canonical title/account/biz/content hash is incomplete")
    if not re.fullmatch(r"[0-9a-fA-F]{8,128}", content_hash) or set(content_hash) == {"0"}:
        raise ValueError("content hash is empty or malformed")
    return {
        "url": expected_url,
        "token": expected_token,
        "title": title,
        "account": account,
        "biz": biz,
        "article_date": _article_date(summary),
        "content_hash": content_hash.lower(),
        "http_status": str(http_status),
        "html_bytes": str(html_bytes),
        "image_count": str(image_count),
    }


def validate_intake_summary(summary: dict, requested_url: str, *, allow_saved_html: bool = False) -> dict[str, str]:
    return validate_intake_identity(summary, requested_url, allow_saved_html=allow_saved_html)


def _validate_intake_artifacts(out_dir: Path, summary: dict) -> tuple[Path, Path]:
    """Require declared HTML/manifest artifacts to be real and non-empty."""

    def resolve_declared(raw: object, label: str) -> Path:
        value = str(raw or "").strip()
        if not value:
            raise ValueError(f"{label} path is missing")
        candidates: list[Path] = []
        candidate = Path(value)
        if candidate.is_absolute():
            candidates.append(candidate)
        else:
            candidates.append(candidate)
            # The reusable collector reports module-relative paths such as
            # runs/<run>/wechat_article_raw.html.  Normalize that spelling to
            # the already validated run without widening the allowed root.
            parts = candidate.parts
            if len(parts) >= 2 and parts[0] == "runs" and parts[1] == out_dir.name:
                candidates.insert(0, Path(*parts[2:]))
            elif parts and parts[0] == out_dir.name:
                candidates.insert(0, Path(*parts[1:]))
        last_error: Exception | None = None
        for item in candidates:
            try:
                return safe_run_path(out_dir, item, must_exist=True, label=label)
            except (OSError, ValueError, FileNotFoundError) as exc:
                last_error = exc
        raise ValueError(f"{label} path is missing or outside run") from last_error

    html_path = resolve_declared(summary.get("html_path"), "article HTML")
    image_manifest = resolve_declared(summary.get("image_manifest_path"), "image manifest")
    if html_path.stat().st_size <= 0 or image_manifest.stat().st_size <= 0:
        raise ValueError("intake artifacts must be non-empty")
    sample = html_path.read_text(encoding="utf-8-sig", errors="ignore")[:20000].lower()
    if "secitptpage/verify" in sample or "verify.html" in sample:
        raise ValueError("intake HTML is a WeChat verification page")
    try:
        with image_manifest.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            if len(rows) != _nonnegative_int(summary.get("image_count"), "image_count"):
                raise ValueError("image manifest count conflicts with intake summary")
            fields = set(reader.fieldnames or [])
            if "download_status" in fields and any(
                not str(row.get("download_status") or "").startswith("OK") for row in rows
            ):
                raise ValueError("image manifest contains undownloaded images")
            if {"image_sha256", "sha256"} & fields:
                expected_indices = list(range(1, len(rows) + 1))
                observed_indices: list[int] = []
                image_root = (out_dir / "wechat_article_images").resolve()
                for row in rows:
                    try:
                        observed_indices.append(int(str(row.get("idx") or "")))
                    except (TypeError, ValueError) as exc:
                        raise ValueError("image manifest index is invalid") from exc
                    image_url = str(row.get("url") or "").strip()
                    if not image_url:
                        raise ValueError("image manifest URL is missing")
                    expected_hash = str(row.get("image_sha256") or row.get("sha256") or "").strip().lower()
                    alternate_hash = str(row.get("sha256") or "").strip().lower()
                    if row.get("image_sha256") and alternate_hash and alternate_hash != expected_hash:
                        raise ValueError("image manifest hash aliases conflict")
                    if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
                        raise ValueError("image manifest hash is missing or malformed")
                    image_path = resolve_declared(row.get("local_path"), "image artifact")
                    if image_path.parent != image_root or not image_path.is_file() or image_path.is_symlink():
                        raise ValueError("image artifact is outside the article image directory")
                    digest = hashlib.sha256()
                    with image_path.open("rb") as image_handle:
                        for chunk in iter(lambda: image_handle.read(1024 * 1024), b""):
                            digest.update(chunk)
                    if digest.hexdigest() != expected_hash:
                        raise ValueError(f"image {row.get('idx')} hash does not match manifest")
                if observed_indices != expected_indices:
                    raise ValueError("image manifest indices are not stable and ordered")
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ValueError("image manifest is unreadable") from exc
    return html_path, image_manifest


def _safe_output_dir(raw: str) -> Path:
    value = str(raw or "").strip()
    if not value or "\x00" in value or ".." in Path(value).parts or ".." in PureWindowsPath(value).parts:
        raise ValueError("unsafe intake output directory")
    path = Path(value)
    if path.is_symlink():
        raise ValueError("intake output directory must not be a symlink")
    _reject_symlink_components(path, "intake output directory")
    parent = path.parent.resolve(strict=False)
    if not parent.is_dir():
        raise ValueError(f"intake output parent is not a directory: {parent}")
    resolved = path.resolve(strict=False)
    if resolved.exists() and not resolved.is_dir():
        raise ValueError("intake output is not a directory")
    return resolved


def _safe_html_file(raw: str) -> Path:
    value = str(raw or "").strip()
    if not value or "\x00" in value or ".." in Path(value).parts or ".." in PureWindowsPath(value).parts:
        raise ValueError("unsafe saved HTML path")
    path = Path(value)
    if path.is_symlink() or not path.is_file():
        raise ValueError("saved HTML must be a regular local file")
    _reject_symlink_components(path, "saved HTML")
    return path.resolve()


def _existing_identity_fields(mapping: object, *, label: str) -> dict[str, str]:
    """Read optional identity fields while rejecting conflicting aliases."""

    if not isinstance(mapping, dict):
        return {}
    fields: dict[str, str] = {}
    fields["url"] = _consistent(mapping, ("article_url", "url", "canonical_url"), f"{label} URL", canonical_article_url)
    fields["title"] = _consistent(mapping, ("title", "article_title"), f"{label} title", normalize_title)
    fields["biz"] = _consistent(mapping, ("biz", "__biz"), f"{label} biz")
    fields["content_hash"] = _consistent(
        mapping,
        ("content_hash", "evidence_hash", "html_sha256"),
        f"{label} content hash",
        lambda value: str(value).strip().lower(),
    )
    explicit_dates = [
        normalize_date(str(mapping[name]), label=f"{label} date")
        for name in ("target_date", "article_date", "article_publish_date", "publish_date", "date")
        if str(mapping.get(name) or "").strip()
    ]
    if explicit_dates and any(value != explicit_dates[0] for value in explicit_dates[1:]):
        raise ValueError(f"conflicting {label} date fields")
    raw_dates = [
        _date_from_raw(str(mapping[name]).strip())
        for name in ("raw_publish_time", "publish_time", "published_at", "published_at_iso")
        if str(mapping.get(name) or "").strip()
    ]
    if raw_dates and any(value != raw_dates[0] for value in raw_dates[1:]):
        raise ValueError(f"conflicting {label} publish time fields")
    if explicit_dates and raw_dates and explicit_dates[0] != raw_dates[0]:
        raise ValueError(f"{label} date conflicts with publish time")
    if explicit_dates or raw_dates:
        fields["article_date"] = explicit_dates[0] if explicit_dates else raw_dates[0]
    return {key: value for key, value in fields.items() if value}


def _existing_identity_conflict(out_dir: Path, requested_url: str) -> None:
    snapshots: list[dict[str, str]] = []
    for name in ("wechat_article_intake_summary.json", "article_research.json"):
        path = out_dir / name
        if not path.is_file():
            continue
        if path.is_symlink():
            raise ValueError(f"existing {name} must not be a symlink")
        _reject_symlink_components(path, f"existing {name}")
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"existing {name} is invalid") from exc
        article = value.get("article", {}) if name == "article_research.json" and isinstance(value, dict) else value
        snapshots.append(_existing_identity_fields(article, label=name))
    expected_url = canonical_article_url(requested_url)
    combined: dict[str, str] = {}
    for snapshot in snapshots:
        for field, value in snapshot.items():
            if field in combined and combined[field] != value:
                raise ValueError(f"existing run identity conflicts for {field}")
            combined[field] = value
    if combined.get("url") and combined["url"] != expected_url:
        raise ValueError("CLI URL conflicts with existing run identity")


def _run_child(script: Path, argv: list[str]) -> int:
    previous = list(sys.argv)
    sys.argv = [str(script), *argv]
    try:
        runpy.run_path(str(script), run_name="__main__")
    except SystemExit as exc:
        if exc.code in (None, 0):
            return 0
        try:
            return int(exc.code)
        except (TypeError, ValueError):
            return 1
    finally:
        sys.argv = previous
    return 0


def _reject_duplicate_options(argv: list[str], names: set[str]) -> None:
    """Reject duplicate identity/output options before argparse keeps one."""

    seen: dict[str, int] = {name: 0 for name in names}
    for index, token in enumerate(argv):
        for name in names:
            if token == name or token.startswith(name + "="):
                seen[name] += 1
                if token == name and index + 1 >= len(argv):
                    raise ValueError(f"{name} requires a value")
    duplicates = [name for name, count in seen.items() if count > 1]
    if duplicates:
        raise ValueError(f"duplicate CLI identity/output option: {', '.join(sorted(duplicates))}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail-closed local WeChat article intake adapter")
    parser.add_argument("--url", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--html-file", default="")
    raw_args = list(sys.argv[1:] if argv is None else argv)
    _reject_duplicate_options(raw_args, {"--url", "--out", "--html-file"})
    args, _ = parser.parse_known_args(raw_args)
    canonical_token_from_url(args.url)
    out_dir = _safe_output_dir(args.out)
    _existing_identity_conflict(out_dir, args.url)
    html_file = _safe_html_file(args.html_file) if args.html_file else None
    child_args = raw_args
    code = _run_child(_intake_script(), child_args)
    if code:
        return code
    summary_path = safe_run_path(out_dir, "wechat_article_intake_summary.json", must_exist=True)
    summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
    identity = validate_intake_identity(summary, args.url, allow_saved_html=html_file is not None)
    _validate_intake_artifacts(out_dir, summary)
    summary.update(
        {
            "canonical_url": identity["url"],
            "canonical_token": identity["token"],
            "article_date": identity["article_date"],
            "content_hash": identity["content_hash"],
            "identity_status": "PASS",
        }
    )
    write_json(summary_path, summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
