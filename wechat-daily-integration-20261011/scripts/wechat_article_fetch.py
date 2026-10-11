"""Local, fail-closed entrypoint for read-only WeChat article intake.

The actual HTML/image collector is reused from the installed intake skill.
This adapter owns the URL, identity, and run-output security boundary.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
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
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wechat_common import (
    _ArticleBodyTextParser, _reject_symlink_components, normalize_date, normalize_title,
    safe_run_path, write_json,
)  # noqa: E402


WECHAT_HOST = "mp.weixin.qq.com"
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{1,256}$")
_CN_TZ = timezone(timedelta(hours=8))
_PREPARE_MUTABLE_MANIFEST_FIELDS = frozenset({
    "local_path", "download_status", "image_size", "ocr_text_length",
})
_LEGACY_PREPARE_EXTENSION_FIELDS = frozenset({
    "download_status", "image_size", "ocr_text_length",
})
_LEGACY_SUMMARY_PATHS = {
    "html_path": "wechat_article_raw.html",
    "image_manifest_path": "wechat_article_image_manifest.csv",
    "ocr_text_path": "wechat_article_ocr_text.txt",
    "image_checkpoint_path": "wechat_article_image_checkpoint.json",
}
_ADOPTION_EVIDENCE_ROOT = Path("evidence/wechat_article_fetch_adoptions")


def _collector_image_contract() -> dict:
    """Load the bound collector's parser so adapter validation cannot drift."""
    bundled = Path(__file__).resolve().parent.parent / "external" / "wechat_article_intake.py"
    candidates = [bundled]
    if not bundled.is_file():
        candidates.append(_intake_script())
    for candidate in candidates:
        if candidate.is_file() and not candidate.is_symlink():
            namespace = runpy.run_path(str(candidate.resolve()), run_name="_issue31_collector_contract")
            if callable(namespace.get("extract_image_urls")):
                return namespace
            raise ValueError("bound WeChat collector lacks extract_image_urls")
    raise FileNotFoundError("bound WeChat collector source is unavailable")


def _validate_article_body(html_bytes: bytes, manifest_rows: list[dict[str, str]]) -> None:
    """Bind every BODY to the collector's ordered, unique image projection."""
    try:
        html_text = html_bytes.decode("utf-8-sig", errors="replace")
        parser = _ArticleBodyTextParser()
        parser.feed(html_text)
        parser.close()
    except (TypeError, ValueError) as exc:
        raise ValueError("raw article HTML cannot be parsed") from exc
    if not parser._found_root:
        raise ValueError("raw article HTML has no js_content BODY block")
    try:
        observed = _collector_image_contract()["extract_image_urls"](html_text)
    except (OSError, RuntimeError, TypeError, ValueError, KeyError) as exc:
        raise ValueError("real collector image URL projection could not be verified") from exc
    expected = [str(row.get("url") or "") for row in manifest_rows]
    if observed != expected:
        raise ValueError("js_content BODY collector image projection does not exactly match the ordered manifest")
    if not parser.text().strip() and not observed:
        raise ValueError("empty-text BODY has no collector images")


def _image_source_projection_sha256(fields: list[str], rows: list[dict[str, str]]) -> str:
    """Bind stable collector source columns while allowing prepare's known edits."""
    stable_fields = [field for field in fields if field not in _PREPARE_MUTABLE_MANIFEST_FIELDS]
    if not {"idx", "url"}.issubset(stable_fields) or not ("sha256" in stable_fields or "image_sha256" in stable_fields):
        raise ValueError("image manifest lacks stable source-projection fields")
    projection = {
        "fields": stable_fields,
        "rows": [{field: str(row.get(field) or "") for field in stable_fields} for row in rows],
    }
    payload = json.dumps(projection, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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
    _nonnegative_int(summary.get("text_preview_length"), "text_preview_length")
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
_PUBLICATION_TEMP_PREFIX = ".wechat_article_fetch_publish."


def _attempts_root(run_dir: Path) -> Path:
    return run_dir / "evidence" / "wechat_article_fetch_attempts"


def _write_temporary_payload(path: Path, descriptor: int, payload: bytes) -> None:
    """Write and fsync a complete private temp file before it becomes visible."""
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _write_bytes_create_only(path: Path, payload: bytes, *, label: str,
                             temp_dir: Path | None = None) -> None:
    """Atomically publish a complete file without replacing an existing artifact."""
    _reject_symlink_components(path, label)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(temp_dir) if temp_dir is not None else path.parent
    _reject_symlink_components(temporary_root, f"temporary directory for {label}")
    temporary_root.mkdir(parents=True, exist_ok=True)
    if temporary_root.stat().st_dev != path.parent.stat().st_dev:
        raise ValueError(f"temporary directory is on a different filesystem for {label}")
    descriptor, temporary = tempfile.mkstemp(prefix=_PUBLICATION_TEMP_PREFIX, dir=str(temporary_root))
    temporary_path = Path(temporary)
    try:
        _write_temporary_payload(temporary_path, descriptor, payload)
        _reject_symlink_components(path, label)
        try:
            # Hard-link creation is atomic and fails if the destination exists.
            # The destination can never expose a partially written payload.
            os.link(temporary_path, path)
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
                raise ValueError(f"refusing to replace existing {label}: {path}")
        else:
            if os.name != "nt":
                directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
    finally:
        temporary_path.unlink(missing_ok=True)


def _cleanup_publication_temps(attempt_dir: Path) -> None:
    """Remove only adapter-owned leftover temp files after an interrupted promotion."""
    if attempt_dir.is_symlink() or not attempt_dir.is_dir():
        raise ValueError("fetch attempt directory is invalid during publication recovery")
    for path in attempt_dir.iterdir():
        if not path.name.startswith(_PUBLICATION_TEMP_PREFIX):
            continue
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"refusing to remove non-file publication temp: {path}")
        path.unlink()


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
    _validate_article_body(html_bytes, rows)
    source_projection_sha256 = _image_source_projection_sha256(fields, rows)
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
            "image_source_projection_sha256": source_projection_sha256,
        },
    })
    summary_bytes = json.dumps(summary, ensure_ascii=False, indent=2).encode("utf-8-sig")
    return {
        "identity": identity,
        "attempt_id": attempt_id,
        "allow_saved_html": allow_saved_html,
        "saved_html_sha256": saved_html_sha256,
        "image_source_projection_sha256": source_projection_sha256,
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
    _cleanup_publication_temps(attempt_dir)
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
        _write_bytes_create_only(
            image_dir / Path(relative_name).name, data, label="article image", temp_dir=attempt_dir,
        )
    for name, data in (
        ("wechat_article_raw.html", prepared["html_bytes"]),
        ("wechat_article_image_manifest.csv", prepared["manifest_bytes"]),
    ):
        _write_bytes_create_only(run_dir / name, data, label=name, temp_dir=attempt_dir)
    if prepared["checkpoint_bytes"] is not None:
        _write_bytes_create_only(
            run_dir / "wechat_article_image_checkpoint.json", prepared["checkpoint_bytes"],
            label="article image checkpoint", temp_dir=attempt_dir,
        )
    # Summary is the final source commit marker and is never replaced.
    _write_bytes_create_only(
        run_dir / "wechat_article_intake_summary.json", prepared["summary_bytes"],
        label="intake summary", temp_dir=attempt_dir,
    )
    identity = validate_intake_identity(
        prepared["summary"], requested_url, allow_saved_html=prepared["allow_saved_html"]
    )
    _validate_intake_artifacts(run_dir, prepared["summary"])
    state = _source_state(run_dir, prepared["summary"], identity, status_prefix, attempt_dir.name)
    _write_attempt_event(attempt_dir, "PROMOTION_RECEIPT.json", {
        "status": "PROMOTED", "attempt_id": attempt_dir.name, "identity": identity,
        "artifact_sha256": prepared["artifact_sha256"],
        "image_source_projection_sha256": prepared["image_source_projection_sha256"],
        "allow_saved_html": prepared["allow_saved_html"],
        "saved_html_sha256": prepared["saved_html_sha256"] or None,
        "ocr_artifacts_modified": False,
    })
    _write_fetch_state(run_dir, state)
    return state


def _source_state(run_dir: Path, summary: dict, identity: dict, status_prefix: str,
                  attempt_id: str | None) -> dict:
    image_count = int(identity["image_count"])
    ocr_summary_status = _validated_ocr_status(run_dir, summary, image_count)
    ocr_ready = ocr_summary_status in {"OCR_OK", "OCR_NOT_APPLICABLE"}
    if ocr_ready:
        next_missing_stage = "package"
        status = status_prefix + "_OCR_READY"
    elif (run_dir / "ocr_slice_manifest.json").is_file():
        next_missing_stage = "ocr_full"
        status = status_prefix + "_NEED_OCR"
    else:
        next_missing_stage = "prepare_ocr"
        status = status_prefix + "_NEED_OCR"
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


def _read_external_anchor(raw: str, label: str) -> tuple[Path, bytes]:
    value = str(raw or "").strip()
    if not value or "\x00" in value or ".." in Path(value).parts or ".." in PureWindowsPath(value).parts:
        raise ValueError(f"unsafe {label} path")
    path = Path(value).expanduser()
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    _reject_symlink_components(path, label)
    resolved = path.resolve(strict=True)
    if resolved.is_symlink() or not resolved.is_file():
        raise ValueError(f"{label} must be a regular file")
    return resolved, resolved.read_bytes()


def _read_strict_csv(data: bytes, label: str) -> tuple[list[str], list[dict[str, str]]]:
    try:
        stream = io.StringIO(data.decode("utf-8-sig"), newline="")
        reader = csv.DictReader(stream)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    except (UnicodeError, csv.Error) as exc:
        raise ValueError(f"{label} is not valid UTF-8 CSV") from exc
    if not fields or len(fields) != len(set(fields)) or any(not field for field in fields):
        raise ValueError(f"{label} has an empty or duplicate column")
    if any(None in row for row in rows):
        raise ValueError(f"{label} has rows with extra columns")
    return fields, rows


def _relative_artifact_value(value: object, *, root: Path, expected: str,
                             label: str, must_exist: bool) -> Path:
    raw = str(value or "").strip()
    if not raw or "\x00" in raw or ".." in Path(raw).parts or ".." in PureWindowsPath(raw).parts:
        raise ValueError(f"{label} path is empty or unsafe")
    candidate = Path(raw)
    root_resolved = root.resolve(strict=False)
    if candidate.is_absolute():
        if candidate.resolve(strict=False) != (root_resolved / expected).resolve(strict=False):
            raise ValueError(f"{label} path is not the exact run-root mapping")
        relative = Path(expected)
    else:
        parts = list(candidate.parts)
        if len(parts) >= 2 and parts[0] == "runs" and parts[1] == root.name:
            parts = parts[2:]
        elif parts and parts[0] == root.name:
            parts = parts[1:]
        relative = Path(*parts)
        if relative.as_posix() != expected:
            raise ValueError(f"{label} path is not the exact run-root mapping")
    if must_exist:
        resolved = safe_run_path(root, relative, must_exist=True, label=label)
        if resolved.is_symlink() or not resolved.is_file():
            raise ValueError(f"{label} is not a regular in-run file")
    return relative


def _legacy_summary_path_projection(source: dict, current: dict, *, source_root: Path,
                                    run_dir: Path) -> dict[str, dict[str, str]]:
    if set(source) != set(current):
        raise ValueError("legacy/current source summary fields differ")
    mappings: dict[str, dict[str, str]] = {}
    projected = dict(source)
    for key, relative in _LEGACY_SUMMARY_PATHS.items():
        if key not in source:
            continue
        _relative_artifact_value(
            source[key], root=source_root, expected=relative,
            label=f"original summary {key}", must_exist=False,
        )
        _relative_artifact_value(
            current[key], root=run_dir, expected=relative,
            label=f"current summary {key}", must_exist=True,
        )
        projected[key] = current[key]
        mappings[key] = {"source": str(source[key]), "current": str(current[key])}
    if projected != current:
        raise ValueError("legacy source summary differs beyond the four exact path fields")
    for required in ("html_path", "image_manifest_path"):
        if required not in mappings:
            raise ValueError(f"legacy source summary is missing required path field {required}")
    return mappings


def _summary_published_at(summary: dict) -> str:
    for key in ("published_at", "published_at_iso"):
        value = str(summary.get(key) or "").strip()
        if value:
            return value
    for key in ("raw_publish_time", "publish_time", "ct"):
        value = str(summary.get(key) or "").strip()
        if not value:
            continue
        try:
            timestamp = int(value)
            if timestamp > 0:
                return datetime.fromtimestamp(timestamp, tz=_CN_TZ).isoformat()
        except (TypeError, ValueError, OverflowError, OSError):
            continue
    return ""


def _validate_legacy_source(run_dir: Path, requested_url: str, *, package_path: str,
                            expected_package_sha256: str, package_id: str, input_digest: str,
                            source_summary_path: str | Path, source_manifest_path: str | Path,
                            source_run_root: str | Path | None = None,
                            allow_prepare_extensions: bool = False) -> dict:
    """Revalidate an explicitly frozen historical package without collector/network work."""
    try:
        import wechat_chat_handoff as handoff
    except ImportError as exc:
        raise ValueError("frozen package validator is unavailable") from exc

    package_file, package_bytes = _read_external_anchor(package_path, "frozen package ZIP")
    observed_package_sha = hashlib.sha256(package_bytes).hexdigest()
    expected_package_sha = str(expected_package_sha256 or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_package_sha) or observed_package_sha != expected_package_sha:
        raise ValueError("frozen package ZIP does not match the externally expected SHA-256")
    package_identifier = str(package_id or "").strip()
    expected_input_digest = str(input_digest or "").strip().lower()
    if not package_identifier or not re.fullmatch(r"[0-9a-f]{64}", expected_input_digest):
        raise ValueError("frozen package id/input digest is invalid")
    package_validation = handoff._validate_package_zip(
        package_file, source_run=None, package_id=package_identifier,
        declared_sha=expected_package_sha, observed_sha=observed_package_sha,
    )
    if (package_validation.get("package_identity_status") != "VERIFIED"
            or package_validation.get("input_digest") != expected_input_digest):
        raise ValueError("frozen ZIP is not the expected trusted v2 package")

    try:
        with zipfile.ZipFile(package_file) as archive:
            names = handoff._zip_member_names(archive)
            frozen_manifest = handoff._zip_json(archive, "manifest.json", label="manifest")
            descriptor = frozen_manifest.get("input_descriptor")
            package_csv_bytes, package_rows = handoff._zip_manifest_rows(
                archive, names, int(frozen_manifest["total_images"]),
            )
    except (OSError, KeyError, TypeError, ValueError, zipfile.BadZipFile) as exc:
        raise ValueError("frozen package ZIP cannot be read") from exc
    if not isinstance(descriptor, dict):
        raise ValueError("frozen package input descriptor is missing")
    source_intake_sha = str(frozen_manifest.get("source_intake_sha256") or "").lower()
    source_manifest_sha = str(frozen_manifest.get("source_manifest_sha256") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", source_intake_sha) or not re.fullmatch(r"[0-9a-f]{64}", source_manifest_sha):
        raise ValueError("frozen package does not bind both original intake source files")

    source_summary_file, source_summary_bytes = _read_external_anchor(
        str(source_summary_path), "original source summary",
    )
    source_manifest_file, source_manifest_bytes = _read_external_anchor(
        str(source_manifest_path), "original source manifest",
    )
    if hashlib.sha256(source_summary_bytes).hexdigest() != source_intake_sha:
        raise ValueError("original source summary SHA-256 differs from trusted package")
    if hashlib.sha256(source_manifest_bytes).hexdigest() != source_manifest_sha:
        raise ValueError("original source manifest SHA-256 differs from trusted package")
    inferred_source_root = source_summary_file.parent.resolve()
    anchor_source_root = Path(source_run_root).resolve(strict=False) if source_run_root else inferred_source_root
    if source_run_root is None and source_manifest_file.parent.resolve() != inferred_source_root:
        raise ValueError("original summary and manifest anchors must come from the same frozen run")

    try:
        source_summary = handoff._json_no_duplicate_keys(
            source_summary_bytes, label="original source summary",
        )
        current_summary_path = safe_run_path(
            run_dir, "wechat_article_intake_summary.json", must_exist=True,
            label="current intake summary",
        )
        current_summary_bytes = current_summary_path.read_bytes()
        current_summary = handoff._json_no_duplicate_keys(
            current_summary_bytes, label="current intake summary",
        )
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError("legacy source summary is missing or invalid") from exc
    if not isinstance(source_summary, dict) or not isinstance(current_summary, dict):
        raise ValueError("legacy source summary must be a JSON object")
    if str(source_summary.get("identity_status") or "").upper() != "PASS" or str(current_summary.get("identity_status") or "").upper() != "PASS":
        raise ValueError("legacy source requires identity_status=PASS in both anchored summaries")
    summary_path_map = _legacy_summary_path_projection(
        source_summary, current_summary, source_root=anchor_source_root, run_dir=run_dir,
    )
    try:
        source_identity = validate_intake_identity(source_summary, requested_url, allow_saved_html=True)
        current_identity = validate_intake_identity(current_summary, requested_url, allow_saved_html=True)
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(f"legacy BODY identity is not verified against the request: {exc}") from exc
    if source_identity != current_identity:
        raise ValueError("legacy/current summary identities differ")
    if current_identity["http_status"] not in {"0", "200"}:
        raise ValueError("historical adoption permits only HTTP 200 or saved-HTML status 0")

    manifest_path = safe_run_path(
        run_dir, "wechat_article_image_manifest.csv", must_exist=True,
        label="current image manifest",
    )
    current_manifest_bytes = manifest_path.read_bytes()
    if hashlib.sha256(current_manifest_bytes).hexdigest() == source_manifest_sha:
        # An original-byte copy is valid only if its image paths already resolve inside this run.
        pass
    source_fields, source_rows = _read_strict_csv(source_manifest_bytes, "original source manifest")
    current_fields, current_rows = _read_strict_csv(current_manifest_bytes, "current image manifest")
    package_fields, parsed_package_rows = _read_strict_csv(package_csv_bytes, "frozen package manifest.csv")
    if not (source_fields == current_fields == package_fields):
        raise ValueError("legacy/current/frozen image manifest column order differs")
    if not (len(source_rows) == len(current_rows) == len(parsed_package_rows) == int(source_identity["image_count"])):
        raise ValueError("legacy/current/frozen image manifest row counts differ")
    if frozen_manifest.get("source_run_id") != run_dir.name:
        raise ValueError("frozen package source_run_id does not match the isolated run name")
    if int(frozen_manifest.get("total_images", -1)) != int(source_identity["image_count"]):
        raise ValueError("frozen package image count differs from the source summary")

    mutable_fields = {"local_path"}
    if allow_prepare_extensions:
        mutable_fields.update(_LEGACY_PREPARE_EXTENSION_FIELDS)
    path_map: list[dict[str, str]] = []
    stable_fields = [field for field in source_fields if field not in mutable_fields]
    if not {"idx", "url", "bytes"}.issubset(stable_fields) or not ({"sha256", "image_sha256"} & set(stable_fields)):
        raise ValueError("legacy manifest lacks stable index/URL/hash/byte columns")
    for index, (source_row, current_row, package_row) in enumerate(
            zip(source_rows, current_rows, parsed_package_rows), 1):
        if any(source_row.get(field) != current_row.get(field) for field in stable_fields):
            raise ValueError(f"legacy/current manifest differs outside prepare path/status fields at row {index}")
        if any(current_row.get(field) != package_row.get(field) for field in stable_fields):
            raise ValueError(f"current manifest differs from trusted frozen package at row {index}")
        expected_index = f"{index:03d}"
        if str(current_row.get("idx") or "").strip() != str(index):
            raise ValueError(f"current manifest order is invalid at IMAGE{expected_index}")
        source_local = str(source_row.get("local_path") or "").strip()
        current_local = str(current_row.get("local_path") or "").strip()
        package_local = str(package_row.get("local_path") or package_row.get("path") or "").strip()
        if not source_local or not current_local or not package_local:
            raise ValueError(f"image path is missing at IMAGE{expected_index}")
        source_parts = Path(source_local)
        _relative_artifact_value(
            source_local, root=anchor_source_root,
            expected=f"wechat_article_images/{source_parts.name}",
            label=f"original manifest IMAGE{expected_index}", must_exist=False,
        )
        _relative_artifact_value(
            current_local, root=run_dir,
            expected=f"wechat_article_images/{source_parts.name}",
            label=f"current manifest IMAGE{expected_index}", must_exist=True,
        )
        if Path(current_local).name != source_parts.name:
            raise ValueError(f"image filename changed during path rebinding at IMAGE{expected_index}")
        if package_local != f"images/IMAGE{index:03d}{source_parts.suffix.lower()}":
            raise ValueError(f"frozen package image order/path differs at IMAGE{expected_index}")
        path_map.append({"index": str(index), "source": source_local, "current": current_local,
                         "package": package_local})

    package_manifest = frozen_manifest
    for field, expected in (
        ("original_url", current_identity["url"]),
        ("title", current_identity["title"]),
        ("account", current_identity["account"]),
        ("biz", current_identity["biz"]),
        ("article_date", current_identity["article_date"]),
        ("content_hash", current_identity["content_hash"]),
        ("total_images", int(current_identity["image_count"])),
    ):
        value = package_manifest.get(field)
        if field == "original_url":
            value = canonical_article_url(str(value or ""))
        if value != expected:
            raise ValueError(f"trusted package identity differs from the source summary: {field}")
    if package_manifest.get("source_run_id") != run_dir.name:
        raise ValueError("trusted package identity differs from the current isolated run")
    published_at = _summary_published_at(current_summary)
    if not published_at or package_manifest.get("published_at") != published_at:
        raise ValueError("trusted package published_at differs from the exact source summary")
    descriptor_identity = descriptor.get("identity")
    if not isinstance(descriptor_identity, dict) or any(
            descriptor_identity.get(key) != package_manifest.get(key)
            for key in ("original_url", "article_id", "title", "account", "biz", "published_at",
                        "article_date", "content_hash", "source_run_id")):
        raise ValueError("trusted package descriptor identity is incomplete")

    html_path, validated_manifest_path = _validate_intake_artifacts(run_dir, current_summary)
    if validated_manifest_path != manifest_path:
        raise ValueError("current summary manifest path differs from the bound manifest")
    raw_html_bytes = html_path.read_bytes()
    raw_html_sha = hashlib.sha256(raw_html_bytes).hexdigest()
    if raw_html_sha != str(descriptor.get("raw_html_sha256") or "").lower():
        raise ValueError("current raw HTML SHA-256 differs from the trusted package descriptor")
    _validate_article_body(raw_html_bytes, current_rows)
    try:
        _, _, validated_rows = handoff._manifest_rows(run_dir, {"image_count": len(current_rows)})
    except (OSError, ValueError, TypeError, RuntimeError, csv.Error) as exc:
        raise ValueError(f"current image bytes do not match the frozen manifest contract: {exc}") from exc
    for index, (row, package_row) in enumerate(zip(validated_rows, parsed_package_rows), 1):
        if (row.get("url") != package_row.get("url")
                or row.get("sha256") != package_row.get("sha256")
                or row.get("bytes") != package_row.get("bytes")):
            raise ValueError(f"current image source/hash/bytes differ from frozen package at IMAGE{index:03d}")
    if allow_prepare_extensions and "ocr_text_length" in current_fields:
        try:
            ocr_records, _ = handoff._ocr_records(run_dir, validated_rows)
        except (OSError, ValueError, TypeError, RuntimeError, csv.Error):
            ocr_records = {}
        for index, (source_row, current_row) in enumerate(zip(source_rows, current_rows), 1):
            old_length = str(source_row.get("ocr_text_length") or "")
            new_length = str(current_row.get("ocr_text_length") or "")
            if old_length == new_length or not new_length:
                continue
            record = ocr_records.get(index)
            if (not re.fullmatch(r"[0-9]+", new_length) or not isinstance(record, dict)
                    or len(str(record.get("text") or "")) != int(new_length)):
                raise ValueError(f"post-prepare OCR length is not bound to verified OCR at IMAGE{index:03d}")

    identity = {
        "url": current_identity["url"], "title": current_identity["title"],
        "account": current_identity["account"], "biz": current_identity["biz"],
        "article_date": current_identity["article_date"],
        "content_hash": current_identity["content_hash"],
        "image_count": int(current_identity["image_count"]),
        "source_run_id": run_dir.name,
    }
    image_projection = _image_source_projection_sha256(current_fields, current_rows)
    current_artifacts = {
        "wechat_article_intake_summary.json": hashlib.sha256(current_summary_bytes).hexdigest(),
        "wechat_article_raw.html": raw_html_sha,
        "wechat_article_image_manifest.csv": hashlib.sha256(current_manifest_bytes).hexdigest(),
        "images": [
            {"idx": str(row.get("idx") or ""), "url": str(row.get("url") or ""),
             "sha256": str(row.get("sha256") or row.get("image_sha256") or "").lower(),
             "bytes": str(row.get("bytes") or "")}
            for row in current_rows
        ],
    }
    return {
        "package_file": package_file,
        "package_sha256": observed_package_sha,
        "package_id": package_identifier,
        "input_digest": expected_input_digest,
        "source_intake_sha256": source_intake_sha,
        "source_manifest_sha256": source_manifest_sha,
        "source_summary_path": source_summary_file,
        "source_manifest_path": source_manifest_file,
        "source_summary_bytes": source_summary_bytes,
        "source_manifest_bytes": source_manifest_bytes,
        "source_run_root": str(anchor_source_root),
        "source_summary_sha256": hashlib.sha256(source_summary_bytes).hexdigest(),
        "source_manifest_sha256_observed": hashlib.sha256(source_manifest_bytes).hexdigest(),
        "current_manifest_sha256": hashlib.sha256(current_manifest_bytes).hexdigest(),
        "current_summary_sha256": hashlib.sha256(current_summary_bytes).hexdigest(),
        "summary_path_mapping": summary_path_map,
        "manifest_path_mapping": path_map,
        "identity": identity,
        "image_source_projection_sha256": image_projection,
        "raw_html_sha256": raw_html_sha,
        "current_artifacts": current_artifacts,
        "summary": current_summary,
        "validated_identity": current_identity,
    }


def _adoption_receipt_payload(run_dir: Path, result: dict) -> dict:
    state = _source_state(
        run_dir, result["summary"], result["validated_identity"],
        "LEGACY_SOURCE_REVALIDATED", None,
    )
    ocr_cache_status = state["ocr_summary_status"]
    state.update(
        status="LEGACY_SOURCE_REVALIDATED_" + ("OCR_READY" if state["next_missing_stage"] == "package" else "NEED_OCR"),
        source_status="HISTORICAL_SOURCE_REVALIDATED",
        collector_execution_status="NOT_INVOKED_HISTORICAL_REVALIDATION",
        continuation_status="NEXT_STAGE_READY",
        historical_promotion_claimed=False,
        collector_invoked=False,
        network_attempts=0,
        ocr_cache_status=ocr_cache_status,
    )
    receipt = {
        "receipt_version": "wechat-legacy-source-revalidation-v1",
        "status": "HISTORICAL_SOURCE_REVALIDATED",
        "run_dir": str(run_dir.resolve()),
        "historical_promotion_claimed": False,
        "collector_invoked": False,
        "network_attempts": 0,
        "source_run_root": result["source_run_root"],
        "source_anchors": {
            "original_summary_sha256": result["source_summary_sha256"],
            "expected_summary_sha256": result["source_intake_sha256"],
            "original_manifest_sha256": result["source_manifest_sha256_observed"],
            "expected_manifest_sha256": result["source_manifest_sha256"],
        },
        "current_artifacts": result["current_artifacts"],
        "path_rebinding": {
            "summary": result["summary_path_mapping"],
            "manifest": result["manifest_path_mapping"],
        },
        "identity": result["identity"],
        "image_source_projection_sha256": result["image_source_projection_sha256"],
        "package": {
            "path": str(result["package_file"]),
            "package_id": result["package_id"],
            "input_digest": result["input_digest"],
            "external_expected_sha256": result["package_sha256"],
            "observed_sha256": result["package_sha256"],
            "source_run_id": result["identity"]["source_run_id"],
            "raw_html_sha256": result["raw_html_sha256"],
        },
        "ocr_cache_status": ocr_cache_status,
        "next_missing_stage": state["next_missing_stage"],
    }
    return {"receipt": receipt, "state": state}


def _persist_legacy_adoption(run_dir: Path, requested_url: str, *, package_path: str,
                             expected_package_sha256: str, package_id: str, input_digest: str,
                             source_summary_path: str, source_manifest_path: str) -> dict:
    result = _validate_legacy_source(
        run_dir, requested_url, package_path=package_path,
        expected_package_sha256=expected_package_sha256, package_id=package_id,
        input_digest=input_digest, source_summary_path=source_summary_path,
        source_manifest_path=source_manifest_path,
    )
    anchor = json.dumps({
        "package_sha256": result["package_sha256"],
        "package_path": str(result["package_file"]),
        "source_summary_sha256": result["source_summary_sha256"],
        "source_manifest_sha256": result["source_manifest_sha256_observed"],
        "current_summary_sha256": result["current_summary_sha256"],
        "current_manifest_sha256": result["current_manifest_sha256"],
        "source_run_root": result["source_run_root"],
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")
    adoption_id = "adopt_" + hashlib.sha256(anchor).hexdigest()[:24]
    adoption_dir = run_dir / _ADOPTION_EVIDENCE_ROOT / adoption_id
    _reject_symlink_components(adoption_dir, "legacy adoption evidence")
    adoption_dir.mkdir(parents=True, exist_ok=True)
    _write_bytes_create_only(
        adoption_dir / "ORIGINAL_SOURCE_SUMMARY.json", result["source_summary_bytes"],
        label="original source summary anchor",
    )
    _write_bytes_create_only(
        adoption_dir / "ORIGINAL_SOURCE_MANIFEST.csv", result["source_manifest_bytes"],
        label="original source manifest anchor",
    )
    record = _adoption_receipt_payload(run_dir, result)
    record["receipt"].update({
        "adoption_id": adoption_id,
        "package_path": str(result["package_file"]),
        "original_source_summary_sidecar": str((adoption_dir / "ORIGINAL_SOURCE_SUMMARY.json").relative_to(run_dir)),
        "original_source_manifest_sidecar": str((adoption_dir / "ORIGINAL_SOURCE_MANIFEST.csv").relative_to(run_dir)),
    })
    receipt_bytes = json.dumps(record["receipt"], ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8-sig")
    _write_bytes_create_only(
        adoption_dir / "REVALIDATION_RECEIPT.json", receipt_bytes,
        label="historical source revalidation receipt",
    )
    record["state"]["revalidation_receipt"] = str(adoption_dir / "REVALIDATION_RECEIPT.json")
    return record


def _verify_adoption_receipt(run_dir: Path, receipt_path: Path, requested_url: str) -> dict:
    if receipt_path.is_symlink() or not receipt_path.is_file():
        raise ValueError("historical revalidation receipt is not a regular file")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("historical revalidation receipt is invalid") from exc
    if not isinstance(receipt, dict) or receipt.get("receipt_version") != "wechat-legacy-source-revalidation-v1":
        raise ValueError("historical revalidation receipt version is invalid")
    if (receipt.get("run_dir") != str(run_dir.resolve())
            or receipt.get("historical_promotion_claimed") is not False
            or receipt.get("collector_invoked") is not False
            or receipt.get("network_attempts") != 0):
        raise ValueError("historical revalidation receipt scope is invalid")
    adoption_dir = receipt_path.parent
    summary_sidecar = safe_run_path(
        run_dir, receipt.get("original_source_summary_sidecar"), must_exist=True,
        label="original source summary sidecar",
    )
    manifest_sidecar = safe_run_path(
        run_dir, receipt.get("original_source_manifest_sidecar"), must_exist=True,
        label="original source manifest sidecar",
    )
    expected_sidecar_parent = adoption_dir.resolve()
    if summary_sidecar.parent.resolve() != expected_sidecar_parent or manifest_sidecar.parent.resolve() != expected_sidecar_parent:
        raise ValueError("historical source anchors are outside their adoption evidence directory")
    package = receipt.get("package") if isinstance(receipt.get("package"), dict) else {}
    if package.get("path") != receipt.get("package_path"):
        raise ValueError("historical revalidation ZIP path binding is invalid")
    result = _validate_legacy_source(
        run_dir, requested_url,
        package_path=str(package.get("path") or ""),
        expected_package_sha256=str(package.get("external_expected_sha256") or ""),
        package_id=str(package.get("package_id") or ""),
        input_digest=str(package.get("input_digest") or ""),
        source_summary_path=str(summary_sidecar),
        source_manifest_path=str(manifest_sidecar),
        source_run_root=str(receipt.get("source_run_root") or ""),
        allow_prepare_extensions=(
            hashlib.sha256(safe_run_path(
                run_dir, "wechat_article_image_manifest.csv", must_exist=True,
                label="current image manifest",
            ).read_bytes()).hexdigest()
            != str((receipt.get("current_artifacts") or {}).get("wechat_article_image_manifest.csv") or "").lower()
        ),
    )
    expected_payload = _adoption_receipt_payload(run_dir, result)["receipt"]
    expected_payload.update({
        "adoption_id": receipt.get("adoption_id"),
        "package_path": str(result["package_file"]),
        "original_source_summary_sidecar": str(summary_sidecar.relative_to(run_dir)),
        "original_source_manifest_sidecar": str(manifest_sidecar.relative_to(run_dir)),
    })
    recorded_manifest_sha = str(
        (receipt.get("current_artifacts") or {}).get("wechat_article_image_manifest.csv") or ""
    ).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", recorded_manifest_sha):
        raise ValueError("historical receipt lacks its original current-manifest SHA-256")
    # prepare_ocr may update only its established mutable manifest columns.
    # The source anchors, stable-column comparison, current path checks, image
    # bytes, and OCR records are revalidated above on every reuse.
    expected_payload["current_artifacts"]["wechat_article_image_manifest.csv"] = recorded_manifest_sha
    if receipt != expected_payload:
        raise ValueError("historical revalidation receipt no longer matches its source/package artifacts")
    record = _adoption_receipt_payload(run_dir, result)
    record["state"].update(revalidation_receipt=str(receipt_path))
    return record


def _find_legacy_adoption(run_dir: Path, requested_url: str, *, required: bool) -> dict | None:
    root = run_dir / _ADOPTION_EVIDENCE_ROOT
    if not root.exists() and not root.is_symlink():
        if required:
            raise ValueError("explicit frozen-package adoption evidence is required for this historical run")
        return None
    _reject_symlink_components(root, "historical adoption evidence root")
    if root.is_symlink() or not root.is_dir():
        raise ValueError("historical adoption evidence root is unsafe")
    receipts = sorted(root.glob("adopt_*/REVALIDATION_RECEIPT.json"))
    valid: list[dict] = []
    errors: list[str] = []
    for receipt_path in receipts:
        try:
            valid.append(_verify_adoption_receipt(run_dir, receipt_path, requested_url))
        except (OSError, ValueError, RuntimeError, TypeError, csv.Error) as exc:
            errors.append(str(exc))
    if len(valid) > 1:
        raise ValueError("multiple historical revalidation receipts match this run")
    if valid:
        return valid[0]
    if required:
        detail = errors[0] if errors else "no complete receipt exists"
        raise ValueError("explicit frozen-package revalidation failed: " + detail)
    if receipts:
        raise ValueError("historical revalidation receipt is invalid: " + (errors[0] if errors else "unknown error"))
    return None


def _validated_ocr_status(run_dir: Path, summary: dict, image_count: int) -> str:
    """Return a package-consumable OCR status, never trust the summary alone."""
    summary_path = run_dir / "wechat_article_ocr_summary.json"
    if summary_path.is_symlink() or not summary_path.is_file():
        return "NOT_PRESENT"
    try:
        raw_summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
        if not isinstance(raw_summary, dict):
            return "INVALID"
        declared_status = str(raw_summary.get("status") or "INVALID").upper()
        if declared_status not in {"OCR_OK", "OCR_NOT_APPLICABLE"}:
            return declared_status
        from wechat_chat_handoff import _identity_from_intake, _manifest_rows, _ocr_records

        handoff_identity = _identity_from_intake(run_dir)
        _, _, manifest_rows = _manifest_rows(run_dir, handoff_identity)
        if len(manifest_rows) != image_count:
            return "INVALID"
        _, validated_summary = _ocr_records(run_dir, manifest_rows)
        validated_status = str(validated_summary.get("status") or "INVALID").upper()
        if (image_count == 0 and validated_status != "OCR_NOT_APPLICABLE") or (
            image_count > 0 and validated_status != "OCR_OK"
        ):
            return "INVALID"
        return validated_status
    except (OSError, UnicodeError, json.JSONDecodeError, ImportError, ValueError, RuntimeError,
            KeyError, TypeError, csv.Error):
        return "INVALID"


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
    attempt_id = str(summary.get("fetch_attempt_id") or "")
    if not attempt_id.startswith("attempt_") or Path(attempt_id).name != attempt_id:
        raise ValueError("existing intake source lacks its bound fetch attempt identity")
    attempt_dir = _attempts_root(run_dir) / attempt_id
    promotion_path = attempt_dir / "PROMOTION_RECEIPT.json"
    _reject_symlink_components(promotion_path, "fetch promotion receipt")
    if promotion_path.is_symlink():
        raise ValueError("fetch promotion receipt must not be a symlink")
    if not promotion_path.exists():
        # A summary may have been committed just before an interrupted
        # promotion receipt write. Let the same validated attempt roll forward.
        return None
    if not promotion_path.is_file():
        raise ValueError("fetch promotion receipt is not a regular file")
    try:
        promotion = json.loads(promotion_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("fetch promotion receipt is invalid") from exc
    if (promotion.get("status") != "PROMOTED" or promotion.get("attempt_id") != attempt_id
            or promotion.get("allow_saved_html") is not allow_saved_html
            or (allow_saved_html and promotion.get("saved_html_sha256") != saved_html_sha256)):
        raise ValueError("source permission/identity is not bound by the immutable promotion receipt")
    identity = validate_intake_identity(
        summary, requested_url, allow_saved_html=allow_saved_html,
    )
    html_path, manifest_path = _validate_intake_artifacts(run_dir, summary)
    with manifest_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        manifest_fields = list(reader.fieldnames or [])
        manifest_rows = list(reader)
    _validate_article_body(html_path.read_bytes(), manifest_rows)
    source_projection_sha256 = _image_source_projection_sha256(manifest_fields, manifest_rows)
    validation = summary.get("identity_validation") if isinstance(summary.get("identity_validation"), dict) else {}
    raw_html_sha256 = hashlib.sha256(html_path.read_bytes()).hexdigest()
    expected_raw_html_sha256 = str(validation.get("raw_html_sha256") or "").lower()
    if (not re.fullmatch(r"[0-9a-f]{64}", expected_raw_html_sha256)
            or raw_html_sha256 != expected_raw_html_sha256):
        raise ValueError("existing raw HTML differs from its validated source SHA-256")
    if promotion.get("artifact_sha256", {}).get("wechat_article_raw.html") != raw_html_sha256:
        raise ValueError("existing raw HTML differs from the immutable promotion receipt")
    expected_projection = str(validation.get("image_source_projection_sha256") or "").lower()
    if (not re.fullmatch(r"[0-9a-f]{64}", expected_projection)
            or source_projection_sha256 != expected_projection
            or promotion.get("image_source_projection_sha256") != source_projection_sha256):
        raise ValueError("existing image manifest source projection differs from verified intake")
    if allow_saved_html:
        if (not saved_html_sha256 or raw_html_sha256 != saved_html_sha256
                or validation.get("saved_html_sha256") != raw_html_sha256):
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
        promotion_path = attempt_dir / "PROMOTION_RECEIPT.json"
        if promotion_path.exists() or promotion_path.is_symlink():
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
            "image_source_projection_sha256": prepared["image_source_projection_sha256"],
        })
    return attempt_dir, stage_dir, prepared


def _reject_duplicate_options(argv: list[str], names: set[str]) -> None:
    """Reject aliases/abbreviations before unknown arguments reach the collector."""
    aliases = {
        "-u": "--url", "-o": "--out", "--output": "--out", "--output-dir": "--out",
        "--html_file": "--html-file",
    }
    long_names = {name for name in names if name.startswith("--")}
    seen: dict[str, int] = {name: 0 for name in names}
    index = 0
    while index < len(argv):
        token = argv[index]
        option = token.split("=", 1)[0]
        if option in aliases:
            raise ValueError(f"use canonical option {aliases[option]}; aliases are not forwarded")
        if option.startswith("-") and not option.startswith("--") and option not in names:
            if option.startswith("-o") or option.startswith("-u"):
                raise ValueError("short/abbreviated URL and output options are not allowed")
        if option.startswith("--") and option not in names and any(name.startswith(option) for name in long_names):
            raise ValueError("abbreviated URL/output options are not allowed")
        if option in names:
            seen[option] += 1
            if "=" not in token:
                if index + 1 >= len(argv):
                    raise ValueError(f"{option} requires a value")
                index += 2
                continue
        index += 1
    duplicates = [name for name, count in seen.items() if count > 1]
    if duplicates:
        raise ValueError(f"duplicate CLI identity/output option: {', '.join(sorted(duplicates))}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail-closed local WeChat article intake adapter", allow_abbrev=False)
    parser.add_argument("--url", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--html-file", default="")
    parser.add_argument("--adopt-frozen-package", default="")
    parser.add_argument("--adopt-package-sha256", default="")
    parser.add_argument("--adopt-package-id", default="")
    parser.add_argument("--adopt-input-digest", default="")
    parser.add_argument("--legacy-source-summary", default="")
    parser.add_argument("--legacy-source-manifest", default="")
    raw_args = list(sys.argv[1:] if argv is None else argv)
    try:
        _reject_duplicate_options(raw_args, {
            "--url", "--out", "--html-file", "--adopt-frozen-package",
            "--adopt-package-sha256", "--adopt-package-id", "--adopt-input-digest",
            "--legacy-source-summary", "--legacy-source-manifest",
        })
    except ValueError as exc:
        print(json.dumps({"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 2
    args, _ = parser.parse_known_args(raw_args)
    try:
        canonical_token_from_url(args.url)
        out_dir = _safe_output_dir(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        _existing_identity_conflict(out_dir, args.url)

        adoption_values = (
            args.adopt_frozen_package, args.adopt_package_sha256,
            args.adopt_package_id, args.adopt_input_digest,
            args.legacy_source_summary, args.legacy_source_manifest,
        )
        if any(adoption_values) and not all(adoption_values):
            raise ValueError("frozen adoption requires package path/SHA/id/digest and both original source anchors")
        if all(adoption_values):
            adopted = _persist_legacy_adoption(
                out_dir, args.url,
                package_path=args.adopt_frozen_package,
                expected_package_sha256=args.adopt_package_sha256,
                package_id=args.adopt_package_id,
                input_digest=args.adopt_input_digest,
                source_summary_path=args.legacy_source_summary,
                source_manifest_path=args.legacy_source_manifest,
            )
            state = adopted["state"]
            _write_fetch_state(out_dir, state)
            print(json.dumps(state, ensure_ascii=False))
            return 0

        prior_adoption = _find_legacy_adoption(out_dir, args.url, required=False)
        if prior_adoption is not None:
            state = prior_adoption["state"]
            state["status"] = "LEGACY_SOURCE_REUSED_" + (
                "OCR_READY" if state["next_missing_stage"] == "package" else "NEED_OCR"
            )
            _write_fetch_state(out_dir, state)
            print(json.dumps(state, ensure_ascii=False))
            return 0

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
            "image_source_projection_sha256": prepared["image_source_projection_sha256"],
            "next_missing_stage": "prepare_ocr" if int(prepared["identity"]["image_count"]) else "body_review_or_package",
            "nonzero_collector_exit_tolerated": collector_returncode not in (None, 0),
        }
        _write_attempt_event(attempt_dir, "ATTEMPT_RESULT.json", attempt_result)
        _write_attempt_event(attempt_dir, "SOURCE_VERIFIED.json", {
            "status": "VERIFIED_BODY_AND_IMAGES", "attempt_id": attempt_id,
            "identity": prepared["identity"], "artifact_sha256": prepared["artifact_sha256"],
            "image_source_projection_sha256": prepared["image_source_projection_sha256"],
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
