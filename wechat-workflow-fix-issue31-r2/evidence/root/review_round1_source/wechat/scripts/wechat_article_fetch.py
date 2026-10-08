"""Local, fail-closed entrypoint for read-only WeChat article intake.

The actual HTML/image collector is reused from the installed intake skill.
This adapter owns the URL, identity, and run-output security boundary.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import runpy
import sys
import tempfile
import uuid
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
    """Require a verified BODY identity; OCR completeness is a separate stage."""

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
        # Fetch may be complete while an OCR-only stage failed or was skipped.
        # That is resumable only when the collector explicitly labels the
        # missing phase and supplies an OCR status; transport/body failures
        # remain rejected below and by the artifact checks.
        ocr_status = _first(summary, "ocr_status").upper()
        ocr_incomplete = ocr_status.startswith("OCR_") and ocr_status not in {
            "OCR_OK", "OCR_NOT_APPLICABLE",
        }
        if not (label.endswith("NEED_OCR") and ocr_incomplete):
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


_FETCH_SOURCE_FILES = (
    "wechat_article_raw.html",
    "wechat_article_image_manifest.csv",
    "wechat_article_image_checkpoint.json",
    "wechat_article_intake_summary.json",
)
_DERIVED_OCR_FILES = (
    "ocr_slice_manifest.json",
    "windows_ocr_checkpoint.json",
    "windows_ocr_results.json",
    "windows_ocr_canary.json",
    "wechat_article_ocr_summary.json",
    "wechat_article_ocr_text.txt",
)
_CHECKPOINT_PATH_KEYS = frozenset({"local_path", "path", "image_path", "cached_image_path"})


def _attempts_root(run_dir: Path) -> Path:
    return run_dir / "evidence" / "wechat_article_fetch_attempts"


def _write_bytes_create_only(path: Path, payload: bytes, *, label: str) -> None:
    """Durably create a new artifact; an exact existing copy is idempotent."""
    _reject_symlink_components(path, label)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise ValueError(f"refusing to replace existing {label}: {path}")
        return
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _write_attempt_event(attempt_dir: Path, name: str, value: dict) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8-sig")
    _write_bytes_create_only(attempt_dir / name, payload, label=f"fetch attempt event {name}")


def _write_fetch_state(run_dir: Path, value: dict) -> None:
    path = run_dir / "wechat_article_fetch_state.json"
    _reject_symlink_components(path, "fetch state")
    descriptor, temporary = tempfile.mkstemp(prefix=".wechat_article_fetch_state.", dir=str(run_dir))
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8-sig"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _collector_args(raw_args: list[str], stage_dir: Path) -> list[str]:
    """Change only the collector output root; keep its existing CLI contract."""
    output = list(raw_args)
    replaced = False
    index = 0
    while index < len(output):
        token = output[index]
        if token == "--out":
            if index + 1 >= len(output):
                raise ValueError("--out requires a value")
            output[index + 1] = str(stage_dir)
            replaced = True
            index += 2
            continue
        if token.startswith("--out="):
            output[index] = f"--out={stage_dir}"
            replaced = True
        index += 1
    if not replaced:
        raise ValueError("collector output option --out is missing")
    return output


def _resolve_attempt_file(stage_dir: Path, value: object, *, label: str) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError(f"{label} path is missing")
    candidate = Path(raw)
    candidates: list[Path] = []
    if candidate.is_absolute():
        candidates.append(candidate)
    else:
        candidates.append(candidate)
        parts = candidate.parts
        if len(parts) >= 2 and parts[0] == "runs" and parts[1] == stage_dir.name:
            candidates.insert(0, Path(*parts[2:]))
        elif parts and parts[0] == stage_dir.name:
            candidates.insert(0, Path(*parts[1:]))
    last_error: Exception | None = None
    for item in candidates:
        try:
            return safe_run_path(stage_dir, item, must_exist=True, label=label)
        except (OSError, ValueError, FileNotFoundError) as exc:
            last_error = exc
    raise ValueError(f"{label} is missing or outside the isolated attempt") from last_error


def _resolve_attempt_image(stage_dir: Path, value: object, *, label: str) -> Path:
    image_root = stage_dir / "wechat_article_images"
    path = _resolve_attempt_file(stage_dir, value, label=label)
    if path.parent != image_root.resolve() or path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} is outside the isolated article image directory")
    return path


def _rewrite_checkpoint_paths(value: object, *, stage_dir: Path) -> object:
    if isinstance(value, dict):
        rewritten = {}
        for key, child in value.items():
            if key in _CHECKPOINT_PATH_KEYS and isinstance(child, str) and child.strip():
                path = _resolve_attempt_image(stage_dir, child, label=f"checkpoint {key}")
                rewritten[key] = path.relative_to(stage_dir.resolve()).as_posix()
            else:
                rewritten[key] = _rewrite_checkpoint_paths(child, stage_dir=stage_dir)
        return rewritten
    if isinstance(value, list):
        return [_rewrite_checkpoint_paths(child, stage_dir=stage_dir) for child in value]
    return value


def _prepare_promotion(stage_dir: Path, requested_url: str, *, attempt_id: str = "",
                       allow_saved_html: bool = False, expected_saved_html_sha256: str = "") -> dict:
    """Validate an isolated collector result and create normalized root artifacts."""
    summary_path = safe_run_path(
        stage_dir, "wechat_article_intake_summary.json", must_exist=True, label="attempt intake summary"
    )
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("attempt intake summary is invalid") from exc
    identity = validate_intake_identity(summary, requested_url, allow_saved_html=allow_saved_html)
    html_path, manifest_path = _validate_intake_artifacts(stage_dir, summary)
    html_bytes = html_path.read_bytes()
    saved_html_sha256 = hashlib.sha256(html_bytes).hexdigest() if allow_saved_html else ""
    if allow_saved_html and (not expected_saved_html_sha256 or saved_html_sha256 != expected_saved_html_sha256):
        raise ValueError("saved HTML bytes do not match the explicit CLI input bound to this attempt")
    with manifest_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    image_paths: dict[str, bytes] = {}
    seen_paths: set[Path] = set()
    for expected_index, row in enumerate(rows, 1):
        try:
            index = int(str(row.get("idx") or ""))
        except (TypeError, ValueError) as exc:
            raise ValueError("attempt image manifest index is invalid") from exc
        if index != expected_index:
            raise ValueError("attempt image manifest order is not stable")
        image_value = str(row.get("local_path") or "").strip()
        if not image_value:
            raise ValueError("attempt image manifest is missing local_path")
        image_path = _resolve_attempt_image(stage_dir, image_value, label=f"attempt image {index}")
        if image_path in seen_paths:
            raise ValueError("attempt image manifest contains duplicate image paths")
        seen_paths.add(image_path)
        expected_sha = str(row.get("image_sha256") or row.get("sha256") or "").strip().lower()
        actual_bytes = image_path.read_bytes()
        actual_sha = hashlib.sha256(actual_bytes).hexdigest()
        if not expected_sha or expected_sha != actual_sha:
            raise ValueError(f"attempt image {index} SHA-256 does not match its manifest")
        row["local_path"] = f"wechat_article_images/{image_path.name}"
        image_paths[row["local_path"]] = actual_bytes

    manifest_buffer = __import__("io").StringIO(newline="")
    writer = csv.DictWriter(manifest_buffer, fieldnames=fields, extrasaction="raise", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    manifest_bytes = manifest_buffer.getvalue().encode("utf-8-sig")

    checkpoint_path = stage_dir / "wechat_article_image_checkpoint.json"
    checkpoint_bytes = None
    if checkpoint_path.exists() or checkpoint_path.is_symlink():
        if checkpoint_path.is_symlink() or not checkpoint_path.is_file():
            raise ValueError("attempt image checkpoint is not a regular file")
        try:
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("attempt image checkpoint is invalid JSON") from exc
        checkpoint = _rewrite_checkpoint_paths(checkpoint, stage_dir=stage_dir)
        checkpoint_bytes = json.dumps(checkpoint, ensure_ascii=False, indent=2).encode("utf-8-sig")

    summary = dict(summary)
    summary.update({
        "html_path": "wechat_article_raw.html",
        "image_manifest_path": "wechat_article_image_manifest.csv",
        "identity_status": "PASS",
        "identity_validation_version": "wechat-intake-body-identity-v1",
        "identity_validation_mode": "SAVED_HTML" if allow_saved_html else "HTTP_FETCH",
        "fetch_attempt_id": attempt_id,
        "saved_html_sha256": saved_html_sha256 or None,
        "identity_validation": {
            "url": identity["url"], "title": identity["title"], "account": identity["account"],
            "biz": identity["biz"], "article_date": identity["article_date"],
            "content_hash": identity["content_hash"], "raw_html_sha256": hashlib.sha256(html_bytes).hexdigest(),
            "saved_html_sha256": saved_html_sha256 or None,
            "image_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        },
    })
    summary_bytes = json.dumps(summary, ensure_ascii=False, indent=2).encode("utf-8-sig")
    return {
        "identity": identity,
        "attempt_id": attempt_id,
        "allow_saved_html": allow_saved_html,
        "saved_html_sha256": saved_html_sha256,
        "summary": summary,
        "summary_bytes": summary_bytes,
        "html_bytes": html_bytes,
        "manifest_bytes": manifest_bytes,
        "checkpoint_bytes": checkpoint_bytes,
        "images": image_paths,
        "artifact_sha256": {
            "wechat_article_raw.html": hashlib.sha256(html_bytes).hexdigest(),
            "wechat_article_image_manifest.csv": hashlib.sha256(manifest_bytes).hexdigest(),
            **{name: hashlib.sha256(data).hexdigest() for name, data in image_paths.items()},
            **({"wechat_article_image_checkpoint.json": hashlib.sha256(checkpoint_bytes).hexdigest()}
               if checkpoint_bytes is not None else {}),
        },
    }


def _promote_verified_attempt(run_dir: Path, attempt_dir: Path, stage_dir: Path,
                              prepared: dict, requested_url: str, *, status_prefix: str = "SOURCE_CAPTURED") -> dict:
    """Publish validated BODY/image files create-only; never touch OCR outputs."""
    image_dir = run_dir / "wechat_article_images"
    if image_dir.exists() or image_dir.is_symlink():
        if image_dir.is_symlink() or not image_dir.is_dir():
            raise ValueError("existing article image path is not a directory")
        expected_names = {Path(name).name for name in prepared["images"]}
        existing_names = {path.name for path in image_dir.iterdir()}
        if existing_names - expected_names:
            raise ValueError("existing article image directory contains unbound files")
    else:
        _reject_symlink_components(image_dir, "article image directory")
        image_dir.mkdir(parents=True, exist_ok=True)
    for relative_name, data in prepared["images"].items():
        _write_bytes_create_only(image_dir / Path(relative_name).name, data, label="article image")
    for name, data in (
        ("wechat_article_raw.html", prepared["html_bytes"]),
        ("wechat_article_image_manifest.csv", prepared["manifest_bytes"]),
    ):
        _write_bytes_create_only(run_dir / name, data, label=name)
    if prepared["checkpoint_bytes"] is not None:
        _write_bytes_create_only(
            run_dir / "wechat_article_image_checkpoint.json", prepared["checkpoint_bytes"],
            label="article image checkpoint",
        )
    # Summary is the final source commit marker and is never replaced.
    _write_bytes_create_only(
        run_dir / "wechat_article_intake_summary.json", prepared["summary_bytes"],
        label="intake summary",
    )
    identity = validate_intake_identity(
        prepared["summary"], requested_url, allow_saved_html=prepared["allow_saved_html"]
    )
    _validate_intake_artifacts(run_dir, prepared["summary"])
    state = _source_state(run_dir, prepared["summary"], identity, status_prefix, attempt_dir.name)
    _write_attempt_event(attempt_dir, "PROMOTION_RECEIPT.json", {
        "status": "PROMOTED", "attempt_id": attempt_dir.name, "identity": identity,
        "artifact_sha256": prepared["artifact_sha256"],
        "allow_saved_html": prepared["allow_saved_html"],
        "saved_html_sha256": prepared["saved_html_sha256"] or None,
        "ocr_artifacts_modified": False,
    })
    _write_fetch_state(run_dir, state)
    return state


def _source_state(run_dir: Path, summary: dict, identity: dict, status_prefix: str,
                  attempt_id: str | None) -> dict:
    image_count = int(identity["image_count"])
    ocr_summary_status = "NOT_PRESENT"
    ocr_summary_path = run_dir / "wechat_article_ocr_summary.json"
    if ocr_summary_path.is_file() and not ocr_summary_path.is_symlink():
        try:
            ocr_summary = json.loads(ocr_summary_path.read_text(encoding="utf-8-sig"))
            if isinstance(ocr_summary, dict):
                ocr_summary_status = str(ocr_summary.get("status") or "INVALID")
        except (OSError, UnicodeError, json.JSONDecodeError):
            ocr_summary_status = "INVALID"
    if image_count == 0:
        next_missing_stage = "body_review_or_package"
    elif ocr_summary_status == "OCR_OK":
        next_missing_stage = "package"
    else:
        next_missing_stage = "prepare_ocr"
    if next_missing_stage == "prepare_ocr":
        status = status_prefix + "_NEED_OCR"
    elif next_missing_stage == "body_review_or_package":
        status = status_prefix + "_BODY_READY"
    else:
        status = status_prefix + "_OCR_SUMMARY_OK"
    return {
        "schema_version": "wechat-article-fetch-state-v1",
        "status": status,
        "source_status": "BODY_IDENTITY_VERIFIED",
        "identity": identity,
        "image_count": image_count,
        "ocr_status_from_intake": str(summary.get("ocr_status") or "UNKNOWN"),
        "ocr_summary_status": ocr_summary_status,
        "next_missing_stage": next_missing_stage,
        "attempt_id": attempt_id,
        "collector_execution_status": "NOT_RERUN_SOURCE_REUSED" if status_prefix == "SOURCE_REUSED" else "SOURCE_CAPTURED",
        "continuation_status": "RESUME_FROM_VERIFIED_SOURCE" if status_prefix == "SOURCE_REUSED" else "NEXT_STAGE_READY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _explicit_ocr_failure(summary: dict) -> bool:
    label = _first(summary, "final_label", "decision", "status").upper()
    ocr_status = _first(summary, "ocr_status").upper()
    return label.endswith("NEED_OCR") and ocr_status in {
        "OCR_IMPORT_ERROR", "OCR_ERROR", "OCR_TIMEOUT", "OCR_INTERRUPTED", "OCR_FAILED", "OCR_PARTIAL",
    }


def _existing_verified_source(run_dir: Path, requested_url: str) -> tuple[dict, dict] | None:
    summary_path = run_dir / "wechat_article_intake_summary.json"
    if not summary_path.exists() and not summary_path.is_symlink():
        return None
    if summary_path.is_symlink() or not summary_path.is_file():
        raise ValueError("existing intake summary is not a regular file")
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("existing intake summary is invalid") from exc
    if not isinstance(summary, dict) or summary.get("identity_status") != "PASS":
        raise ValueError("existing intake source lacks verified BODY identity; refusing a fresh fetch")
    allow_saved_html = summary.get("identity_validation_mode") == "SAVED_HTML"
    saved_html_sha256 = str(summary.get("saved_html_sha256") or "") if allow_saved_html else ""
    if allow_saved_html:
        attempt_id = str(summary.get("fetch_attempt_id") or "")
        if not attempt_id.startswith("attempt_") or Path(attempt_id).name != attempt_id:
            raise ValueError("saved HTML source lacks its bound fetch attempt identity")
        promotion_path = _attempts_root(run_dir) / attempt_id / "PROMOTION_RECEIPT.json"
        if promotion_path.is_symlink() or not promotion_path.is_file():
            raise ValueError("saved HTML source lacks an immutable promotion receipt")
        try:
            promotion = json.loads(promotion_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("saved HTML promotion receipt is invalid") from exc
        if (promotion.get("status") != "PROMOTED" or promotion.get("allow_saved_html") is not True
                or promotion.get("saved_html_sha256") != saved_html_sha256):
            raise ValueError("saved HTML permission is not bound by the immutable attempt receipt")
    identity = validate_intake_identity(
        summary, requested_url, allow_saved_html=allow_saved_html,
    )
    html_path, _ = _validate_intake_artifacts(run_dir, summary)
    if allow_saved_html:
        observed = hashlib.sha256(html_path.read_bytes()).hexdigest()
        validation = summary.get("identity_validation") if isinstance(summary.get("identity_validation"), dict) else {}
        if (not saved_html_sha256 or observed != saved_html_sha256
                or validation.get("raw_html_sha256") != observed
                or validation.get("saved_html_sha256") != observed):
            raise ValueError("saved HTML bytes differ from the CLI-bound source evidence")
    return summary, identity


def _reject_unbound_source_or_ocr_artifacts(run_dir: Path) -> None:
    names = (*_FETCH_SOURCE_FILES, "wechat_article_images", *_DERIVED_OCR_FILES)
    found = [name for name in names if (run_dir / name).exists() or (run_dir / name).is_symlink()]
    if found:
        raise ValueError(
            "run has unbound source/OCR artifacts without a verified intake summary; refusing to overwrite: "
            + ", ".join(found)
        )


def _recover_pending_attempt(run_dir: Path, requested_url: str) -> tuple[Path, Path, dict] | None:
    candidates = []
    root = _attempts_root(run_dir)
    if not root.exists():
        return None
    if root.is_symlink() or not root.is_dir():
        raise ValueError("fetch attempt evidence root is invalid")
    for attempt_dir in sorted(root.glob("attempt_*")):
        if attempt_dir.is_symlink() or not attempt_dir.is_dir():
            continue
        started_path = attempt_dir / "ATTEMPT_STARTED.json"
        try:
            started = json.loads(started_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if started.get("requested_url") != canonical_article_url(requested_url):
            continue
        allow_saved_html = started.get("allow_saved_html") is True
        saved_html_sha256 = str(started.get("saved_html_sha256") or "") if allow_saved_html else ""
        if allow_saved_html and not re.fullmatch(r"[0-9a-f]{64}", saved_html_sha256):
            continue
        result_path = attempt_dir / "ATTEMPT_RESULT.json"
        if result_path.is_file() and not result_path.is_symlink():
            try:
                attempt_result = json.loads(result_path.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if attempt_result.get("status") == "REJECTED":
                continue
        stage_dir = attempt_dir / run_dir.name
        if not stage_dir.is_dir() or stage_dir.is_symlink():
            continue
        try:
            prepared = _prepare_promotion(
                stage_dir, requested_url, attempt_id=attempt_dir.name,
                allow_saved_html=allow_saved_html,
                expected_saved_html_sha256=saved_html_sha256,
            )
        except (OSError, ValueError, RuntimeError):
            continue
        candidates.append((attempt_dir, stage_dir, prepared))
    if len(candidates) > 1:
        raise ValueError("multiple unpromoted verified fetch attempts exist; refusing to choose one")
    if not candidates:
        return None
    attempt_dir, stage_dir, prepared = candidates[0]
    result_path = attempt_dir / "ATTEMPT_RESULT.json"
    if not result_path.exists():
        _write_attempt_event(attempt_dir, "ATTEMPT_RESULT.json", {
            "status": "SOURCE_VERIFIED", "attempt_id": attempt_dir.name,
            "collector_returncode": None, "recovered_after_interruption": True,
            "reason": "The isolated attempt output passed BODY identity and artifact validation.",
            "artifact_sha256": prepared["artifact_sha256"],
        })
    return attempt_dir, stage_dir, prepared


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
    try:
        canonical_token_from_url(args.url)
        out_dir = _safe_output_dir(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        _existing_identity_conflict(out_dir, args.url)

        existing = _existing_verified_source(out_dir, args.url)
        if existing is not None:
            summary, identity = existing
            state = _source_state(out_dir, summary, identity, "SOURCE_REUSED", None)
            _write_fetch_state(out_dir, state)
            print(json.dumps(state, ensure_ascii=False))
            return 0

        pending = _recover_pending_attempt(out_dir, args.url)
        if pending is not None:
            attempt_dir, stage_dir, prepared = pending
            state = _promote_verified_attempt(
                out_dir, attempt_dir, stage_dir, prepared, args.url, status_prefix="SOURCE_RECOVERED"
            )
            print(json.dumps(state, ensure_ascii=False))
            return 0

        _reject_unbound_source_or_ocr_artifacts(out_dir)
        html_file = _safe_html_file(args.html_file) if args.html_file else None
        saved_html_sha256 = hashlib.sha256(html_file.read_bytes()).hexdigest() if html_file is not None else ""
        attempts_root = _attempts_root(out_dir)
        _reject_symlink_components(attempts_root, "fetch attempt evidence root")
        attempts_root.mkdir(parents=True, exist_ok=True)
        attempt_id = "attempt_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:12]
        attempt_dir = attempts_root / attempt_id
        attempt_dir.mkdir()
        stage_dir = attempt_dir / out_dir.name
        stage_dir.mkdir()
        _write_attempt_event(attempt_dir, "ATTEMPT_STARTED.json", {
            "status": "STARTED", "attempt_id": attempt_id,
            "requested_url": canonical_article_url(args.url),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "collector_output_isolated": True,
            "allow_saved_html": html_file is not None,
            "saved_html_sha256": saved_html_sha256 or None,
        })

        collector_returncode = None
        collector_error = None
        try:
            collector_returncode = _run_child(_intake_script(), _collector_args(raw_args, stage_dir))
        except Exception as exc:
            collector_error = f"{type(exc).__name__}: {exc}"

        try:
            prepared = _prepare_promotion(
                stage_dir, args.url, attempt_id=attempt_id,
                allow_saved_html=html_file is not None,
                expected_saved_html_sha256=saved_html_sha256,
            )
        except (OSError, ValueError, RuntimeError, csv.Error) as exc:
            reason = collector_error or f"{type(exc).__name__}: {exc}"
            attempt_result = {
                "status": "REJECTED", "attempt_id": attempt_id,
                "collector_returncode": collector_returncode,
                "reason": reason,
                "isolated_output": str(stage_dir),
            }
            _write_attempt_event(attempt_dir, "ATTEMPT_RESULT.json", attempt_result)
            state = {
                "schema_version": "wechat-article-fetch-state-v1",
                "status": "ATTEMPT_REJECTED",
                "source_status": "CANNOT_CONFIRM",
                "next_missing_stage": "fetch",
                "attempt_id": attempt_id,
                "attempt_receipt": str(attempt_dir / "ATTEMPT_RESULT.json"),
                "reason": reason,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
            _write_fetch_state(out_dir, state)
            print(json.dumps(state, ensure_ascii=False))
            return 2

        attempt_result = {
            "status": "SOURCE_VERIFIED", "attempt_id": attempt_id,
            "collector_returncode": collector_returncode,
            "collector_error": collector_error,
            "identity": prepared["identity"],
            "artifact_sha256": prepared["artifact_sha256"],
            "next_missing_stage": "prepare_ocr" if int(prepared["identity"]["image_count"]) else "body_review_or_package",
            "nonzero_collector_exit_tolerated": collector_returncode not in (None, 0),
        }
        _write_attempt_event(attempt_dir, "ATTEMPT_RESULT.json", attempt_result)
        _write_attempt_event(attempt_dir, "SOURCE_VERIFIED.json", {
            "status": "VERIFIED_BODY_AND_IMAGES", "attempt_id": attempt_id,
            "identity": prepared["identity"], "artifact_sha256": prepared["artifact_sha256"],
        })
        state = _promote_verified_attempt(out_dir, attempt_dir, stage_dir, prepared, args.url)
        known_ocr_failure = _explicit_ocr_failure(prepared["summary"])
        known_ocr_exception = bool(
            collector_error and collector_error.startswith("ModuleNotFoundError:") and known_ocr_failure
        )
        execution_verified = (
            collector_error is None and collector_returncode in (None, 0)
        ) or (
            collector_error is None and known_ocr_failure
        ) or known_ocr_exception
        if known_ocr_failure and (collector_error is None or known_ocr_exception):
            state["collector_execution_status"] = "OCR_IMPORT_ERROR" if "IMPORT_ERROR" in str(prepared["summary"].get("ocr_status", "")) else "OCR_INCOMPLETE"
            state["continuation_status"] = "RESUME_VIA_PREPARE_OCR"
            state["source_status"] = "BODY_IDENTITY_VERIFIED"
        elif execution_verified:
            state["collector_execution_status"] = "COMPLETE"
            state["continuation_status"] = "NEXT_STAGE_READY"
        else:
            state.update(
                status="SOURCE_RETAINED_CONTINUATION_UNVERIFIED",
                source_status="BODY_IDENTITY_VERIFIED",
                collector_execution_status="UNEXPECTED_EXCEPTION" if collector_error else "NONZERO_EXIT_UNCLASSIFIED",
                continuation_status="UNVERIFIED",
            )
        state["collector_returncode"] = collector_returncode
        if collector_error:
            state["collector_error"] = collector_error
        _write_fetch_state(out_dir, state)
        print(json.dumps(state, ensure_ascii=False))
        return 0 if execution_verified else 2
    except Exception as exc:
        payload = {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(payload, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
