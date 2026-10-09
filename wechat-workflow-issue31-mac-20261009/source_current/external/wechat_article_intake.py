from __future__ import annotations

import argparse
import csv
import hashlib
import html
import http.client
import io
import json
import os
import re
import sys
import tempfile
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import unquote, urlsplit


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


DEFAULT_IMAGE_WORKERS = 3
MAX_IMAGE_WORKERS = 3
DEFAULT_IMAGE_RETRIES = 2
MAX_IMAGE_RETRIES = 3
IMAGE_CHECKPOINT_NAME = "wechat_article_image_checkpoint.json"
IMAGE_FIELDS = [
    "idx",
    "url",
    "local_path",
    "download_status",
    "image_size",
    "ocr_text_length",
    "image_sha256",
    "sha256",
    "bytes",
    "attempts",
    "cache_status",
    "content_type",
    "error",
]


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Replace one output atomically, leaving no partially written artifact."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
    except Exception:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass
        raise


def _atomic_write_text(path: Path, text: str) -> None:
    _atomic_write_bytes(path, text.encode("utf-8-sig"))


def _atomic_write_json(path: Path, value: object) -> None:
    _atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def write_text(path: Path, text: str) -> None:
    _atomic_write_text(path, text)


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    output_text = io.StringIO(newline="")
    writer = csv.DictWriter(output_text, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    _atomic_write_text(path, output_text.getvalue())


def _is_verification_page(html_text: str) -> bool:
    sample = str(html_text or "").lower()
    return "secitptpage/verify" in sample or "verify.html" in sample


def _article_token(url: str) -> str:
    try:
        parsed = urlsplit(str(url or ""))
    except ValueError:
        return ""
    match = re.fullmatch(r"/s/([A-Za-z0-9_-]{1,256})/?", parsed.path or "")
    if parsed.scheme.lower() != "https" or parsed.hostname != "mp.weixin.qq.com" or not match:
        return ""
    return match.group(1)


def _same_article_url(requested: str, observed: str) -> bool:
    """Allow harmless query/fragment changes but reject article redirects."""

    if not observed:
        return True
    requested_token = _article_token(requested)
    observed_token = _article_token(observed)
    return bool(requested_token and observed_token and requested_token == observed_token)


def _fetch_html_http(url: str, timeout: int = 60) -> tuple[str, int, str]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125 Safari/537.36 MicroMessenger/8.0.43"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://mp.weixin.qq.com/",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = int(getattr(resp, "status", 200))
            final_url = ""
            geturl = getattr(resp, "geturl", None)
            if callable(geturl):
                final_url = str(geturl() or "")
            try:
                data = resp.read()
            except http.client.IncompleteRead as exc:
                data = exc.partial
        text = data.decode("utf-8", errors="ignore")
        if final_url and not _same_article_url(url, final_url):
            return text, status, f"redirected to a different article: {final_url}"
        return text, status, ""
    except Exception as exc:  # noqa: BLE001
        return "", 0, f"{type(exc).__name__}: {exc}"


def _fetch_html_crawl4ai(url: str, timeout: int = 60) -> tuple[str, int, str]:
    """Call the optional browser transport without importing it on HTTP runs."""

    try:
        from wechat_crawl4ai_fetch import fetch_html as crawl_fetch
    except Exception as exc:  # noqa: BLE001
        return "", 0, f"Crawl4AI unavailable: {type(exc).__name__}: {exc}"
    try:
        text, status, error = crawl_fetch(url, timeout=max(1, int(timeout)))
    except Exception as exc:  # noqa: BLE001
        return "", 0, f"Crawl4AI error: {type(exc).__name__}: {exc}"
    return text, status, error


def fetch_html_with_metadata(
    url: str,
    html_path: Path,
    timeout: int = 60,
    *,
    fetch_mode: str = "http",
) -> tuple[str, int, str, str]:
    """Fetch the requested article and return text/status/error/transport."""

    mode = str(fetch_mode or "http").strip().lower()
    if mode not in {"http", "auto", "crawl4ai"}:
        raise ValueError("fetch mode must be one of: http, auto, crawl4ai")

    if mode == "http":
        text, status, error = _fetch_html_http(url, timeout)
        transport = "http"
    elif mode == "crawl4ai":
        text, status, error = _fetch_html_crawl4ai(url, timeout)
        transport = "crawl4ai"
    else:
        http_text, http_status, http_error = _fetch_html_http(url, timeout)
        if http_text and http_status == 200 and not http_error and not _is_verification_page(http_text):
            text, status, error, transport = http_text, http_status, "", "http"
        else:
            crawl_text, crawl_status, crawl_error = _fetch_html_crawl4ai(url, timeout)
            if crawl_text and not crawl_error:
                text, status, error, transport = crawl_text, crawl_status, "", "crawl4ai"
            else:
                # Preserve the original response for evidence, while keeping
                # the combined transport error fail-closed for identity gates.
                text, status, transport = http_text, http_status, "http"
                errors = [item for item in (http_error, crawl_error) if item]
                error = " | ".join(errors)

    if text:
        write_text(html_path, text)
    return text, status, error, transport


def fetch_html(url: str, html_path: Path, timeout: int = 60, *, fetch_mode: str = "http") -> tuple[str, int, str]:
    """Backward-compatible HTTP/optional transport wrapper."""

    text, status, error, _transport = fetch_html_with_metadata(
        url, html_path, timeout, fetch_mode=fetch_mode
    )
    return text, status, error


def js_string(html_text: str, name: str) -> str:
    patterns = [
        rf'var\s+{re.escape(name)}\s*=\s*"((?:\\.|[^"])*)"',
        rf"var\s+{re.escape(name)}\s*=\s*'((?:\\.|[^'])*)'",
        rf'{re.escape(name)}\s*:\s*"((?:\\.|[^"])*)"',
    ]
    for pattern in patterns:
        match = re.search(pattern, html_text)
        if match:
            raw = match.group(1)
            try:
                if "\\u" in raw or "\\x" in raw or "\\/" in raw:
                    value = raw.encode("utf-8").decode("unicode_escape", errors="ignore")
                else:
                    value = raw
            except Exception:  # noqa: BLE001
                value = raw
            return html.unescape(value).strip()
    return ""


def meta_content(html_text: str, prop: str) -> str:
    pattern = rf'<meta\s+(?:property|name)=["\']{re.escape(prop)}["\']\s+content=["\']([^"\']*)["\']'
    match = re.search(pattern, html_text, re.I)
    return html.unescape(match.group(1)).strip() if match else ""


def js_number(html_text: str, name: str) -> str:
    patterns = [
        rf'var\s+{re.escape(name)}\s*=\s*"?(?P<v>\d+)"?',
        rf'{re.escape(name)}\s*:\s*"?(?P<v>\d+)"?',
    ]
    for pattern in patterns:
        match = re.search(pattern, html_text)
        if match:
            return match.group("v")
    return ""


def article_content_block(html_text: str) -> str:
    patterns = [
        r'<div[^>]+id=["\']js_content["\'][^>]*>(.*?)</div>\s*</div>\s*<script',
        r'<div[^>]+id=["\']js_content["\'][^>]*>(.*?)</div>',
    ]
    for pattern in patterns:
        match = re.search(pattern, html_text, re.S)
        if match:
            return match.group(1)
    return ""


def extract_text_preview(html_text: str) -> str:
    block = article_content_block(html_text)
    if not block:
        return ""
    block = re.sub(r"<script.*?</script>", "", block, flags=re.S)
    block = re.sub(r"<style.*?</style>", "", block, flags=re.S)
    text = re.sub(r"<[^>]+>", "\n", block)
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def extract_image_urls(html_text: str) -> list[str]:
    urls: list[str] = []
    search_area = article_content_block(html_text)
    for match in re.finditer(r'(?:data-src|src)=["\']([^"\']+)["\']', search_area):
        url = unquote(match.group(1)).replace("&amp;", "&")
        if "mmbiz.qpic.cn" not in url:
            continue
        if "wx_fmt=gif" in url:
            continue
        if url not in urls:
            urls.append(url)
    return urls


def _bounded_image_workers(value: int) -> int:
    try:
        workers = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("image workers must be an integer from 1 to 3") from exc
    if workers < 1 or workers > MAX_IMAGE_WORKERS:
        raise ValueError(f"image workers must be between 1 and {MAX_IMAGE_WORKERS}")
    return workers


def _bounded_image_retries(value: int) -> int:
    try:
        retries = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("image retries must be an integer from 0 to 3") from exc
    if retries < 0 or retries > MAX_IMAGE_RETRIES:
        raise ValueError(f"image retries must be between 0 and {MAX_IMAGE_RETRIES}")
    return retries


def _image_path(url: str, idx: int, img_dir: Path) -> Path:
    suffix = ".jpg"
    if "wx_fmt=png" in url or "fmt=png" in url:
        suffix = ".png"
    return img_dir / f"img_{idx:02d}{suffix}"


def _base_image_row(url: str, idx: int, path: Path) -> dict[str, str]:
    return {
        "idx": str(idx),
        "url": url,
        "local_path": str(path),
        "download_status": "",
        "image_size": "",
        "ocr_text_length": "",
        "image_sha256": "",
        "sha256": "",
        "bytes": "",
        "attempts": "0",
        "cache_status": "",
        "content_type": "",
        "error": "",
    }


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _response_header(response: object, name: str) -> str:
    headers = getattr(response, "headers", None)
    if headers is None:
        return ""
    try:
        value = headers.get(name, "")
    except AttributeError:
        return ""
    return str(value or "").strip()


def _image_magic(data: bytes) -> bool:
    """Recognize raster image payloads without trusting an HTTP header."""

    return data.startswith(
        (
            b"\xff\xd8\xff",  # JPEG
            b"\x89PNG\r\n\x1a\n",  # PNG
            b"GIF87a",
            b"GIF89a",
            b"BM",  # BMP
            b"II*\x00",  # TIFF little endian
            b"MM\x00*",  # TIFF big endian
        )
    ) or (len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP")


def _image_metadata(data: bytes, content_type: str = "") -> tuple[bool, str, str]:
    """Validate an image payload and return (valid, dimensions, error)."""

    if not data:
        return False, "", "empty response body"
    media_type = content_type.split(";", 1)[0].strip().lower()
    lower = data[:256].lstrip().lower()
    if media_type in {"text/html", "application/xhtml+xml", "text/plain", "application/json"}:
        return False, "", f"unexpected content type {media_type}"
    if lower.startswith((b"<!doctype html", b"<html", b"<head", b"<?xml")):
        return False, "", "response body is HTML/XML, not an image"
    if not _image_magic(data):
        return False, "", "response body has no recognized image signature"
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            return True, f"{image.width}x{image.height}", ""
    except ImportError:
        # The intake has a standard-library-only transport path.  Signature
        # validation still prevents HTML error pages when Pillow is absent.
        return True, "", ""
    except Exception as exc:  # noqa: BLE001
        return False, "", f"invalid image payload: {type(exc).__name__}: {exc}"


def _write_image_atomic(path: Path, data: bytes) -> None:
    _atomic_write_bytes(path, data)


def _cache_row_is_valid(
    cached: dict[str, str] | None,
    *,
    url: str,
    path: Path,
) -> tuple[bool, str, str, int]:
    """Validate URL, prior success, file hash, and image content before reuse."""

    if not isinstance(cached, dict):
        return False, "", "", 0
    if str(cached.get("url") or "") != url:
        return False, "", "", 0
    status = str(cached.get("download_status") or "").upper()
    if not status.startswith("OK"):
        return False, "", "", 0
    expected_hash = str(cached.get("image_sha256") or cached.get("sha256") or "").strip().lower()
    alternate_hash = str(cached.get("sha256") or "").strip().lower()
    if cached.get("image_sha256") and alternate_hash and alternate_hash != expected_hash:
        return False, "", "", 0
    if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        return False, "", "", 0
    if not path.is_file() or path.is_symlink():
        return False, "", "", 0
    try:
        data = path.read_bytes()
    except OSError:
        return False, "", "", 0
    actual_hash = _sha256_bytes(data)
    if actual_hash != expected_hash:
        return False, "", "", 0
    valid, image_size, _error = _image_metadata(data, str(cached.get("content_type") or ""))
    if not valid:
        return False, "", "", 0
    return True, actual_hash, image_size, len(data)


def _load_cached_rows(checkpoint_path: Path, manifest_path: Path | None = None) -> dict[int, dict[str, str]]:
    """Load prior rows; malformed checkpoints are ignored and re-fetched."""

    candidates = [checkpoint_path]
    if manifest_path is not None:
        candidates.append(manifest_path)
    rows_by_index: dict[int, dict[str, str]] = {}
    for candidate in candidates:
        if not candidate.is_file() or candidate.is_symlink():
            continue
        try:
            if candidate.suffix.lower() == ".csv":
                with candidate.open("r", encoding="utf-8-sig", newline="") as handle:
                    raw_rows = list(csv.DictReader(handle))
            else:
                value = json.loads(candidate.read_text(encoding="utf-8-sig"))
                raw_rows = value.get("images", []) if isinstance(value, dict) else value
            if not isinstance(raw_rows, list):
                continue
            for raw in raw_rows:
                if not isinstance(raw, dict):
                    continue
                try:
                    idx = int(str(raw.get("idx") or raw.get("index") or ""))
                except (TypeError, ValueError):
                    continue
                if idx > 0:
                    candidate_row = {str(k): str(v or "") for k, v in raw.items()}
                    previous = rows_by_index.get(idx)
                    previous_ok = str((previous or {}).get("download_status") or "").upper().startswith("OK")
                    candidate_ok = str(candidate_row.get("download_status") or "").upper().startswith("OK")
                    if previous is None or (candidate_ok and not previous_ok):
                        rows_by_index[idx] = candidate_row
        except (OSError, UnicodeError, csv.Error, TypeError, ValueError, json.JSONDecodeError):
            continue
    return rows_by_index


def _checkpoint_rows(rows: list[dict[str, str] | None]) -> list[dict[str, str]]:
    return [dict(row) for row in sorted((row for row in rows if row), key=lambda item: int(item["idx"]))]


def _write_image_checkpoint(path: Path, rows: list[dict[str, str] | None]) -> None:
    payload = {
        "schema_version": 1,
        "image_count_completed": len([row for row in rows if row]),
        "images": _checkpoint_rows(rows),
    }
    _atomic_write_json(path, payload)


def _download_image_once(url: str, idx: int, img_dir: Path, article_url: str, timeout: int, attempt: int) -> dict[str, str]:
    path = _image_path(url, idx, img_dir)
    row = _base_image_row(url, idx, path)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
            ),
            "Referer": article_url,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = int(getattr(resp, "status", 200) or 0)
            if status != 200:
                raise RuntimeError(f"HTTP status {status}")
            data = resp.read()
            content_type = _response_header(resp, "Content-Type")
        valid, image_size, validation_error = _image_metadata(data, content_type)
        if not valid:
            raise ValueError(validation_error)
        _write_image_atomic(path, data)
        # Validate the bytes after the atomic rename as well.  This catches a
        # broken filesystem write before the row is checkpointed as successful.
        written = path.read_bytes()
        image_hash = _sha256_bytes(written)
        valid, image_size_after, validation_error = _image_metadata(written, content_type)
        if not valid:
            raise ValueError(validation_error)
        row["download_status"] = f"OK bytes={len(written)}"
        row["image_size"] = image_size_after or image_size
        row["image_sha256"] = image_hash
        row["sha256"] = image_hash
        row["bytes"] = str(len(written))
        row["attempts"] = str(attempt)
        row["cache_status"] = "DOWNLOADED"
        row["content_type"] = content_type
        return row
    except Exception as exc:  # noqa: BLE001
        row["download_status"] = f"ERROR attempt={attempt} {type(exc).__name__}: {exc}"
        row["attempts"] = str(attempt)
        row["cache_status"] = "MISS"
        row["error"] = f"{type(exc).__name__}: {exc}"
        return row


def download_image(
    url: str,
    idx: int,
    img_dir: Path,
    article_url: str,
    timeout: int,
    *,
    retries: int = DEFAULT_IMAGE_RETRIES,
    cached: dict[str, str] | None = None,
) -> dict[str, str]:
    """Download one image with bounded retry and validated cache reuse."""

    retries = _bounded_image_retries(retries)
    path = _image_path(url, idx, img_dir)
    cached_ok, image_hash, image_size, byte_count = _cache_row_is_valid(cached, url=url, path=path)
    if cached_ok:
        row = _base_image_row(url, idx, path)
        row.update(
            {
                "download_status": f"OK_REUSED bytes={byte_count}",
                "image_size": image_size,
                "image_sha256": image_hash,
                "sha256": image_hash,
                "bytes": str(byte_count),
                "attempts": "0",
                "cache_status": "REUSED",
                "content_type": str(cached.get("content_type") or ""),
            }
        )
        return row

    last_row = _base_image_row(url, idx, path)
    attempts = retries + 1
    for attempt in range(1, attempts + 1):
        last_row = _download_image_once(url, idx, img_dir, article_url, max(1, int(timeout)), attempt)
        if last_row["download_status"].startswith("OK"):
            return last_row
        if attempt < attempts:
            # A short bounded backoff avoids hammering a transient CDN error,
            # while keeping a 3-image canary quick and deterministic.
            time.sleep(min(0.25 * (2 ** (attempt - 1)), 1.0))
    return last_row


def download_images(
    urls: list[str],
    img_dir: Path,
    article_url: str,
    timeout: int,
    *,
    workers: int = DEFAULT_IMAGE_WORKERS,
    retries: int = DEFAULT_IMAGE_RETRIES,
    checkpoint_path: Path | None = None,
    manifest_path: Path | None = None,
) -> list[dict[str, str]]:
    """Fetch images concurrently with ordered output and per-image checkpoints."""

    workers = _bounded_image_workers(workers)
    retries = _bounded_image_retries(retries)
    img_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = checkpoint_path or img_dir.parent / IMAGE_CHECKPOINT_NAME
    cached_rows = _load_cached_rows(checkpoint_path, manifest_path)
    completed: list[dict[str, str] | None] = [None] * len(urls)

    def fetch_one(index: int, image_url: str) -> dict[str, str]:
        return download_image(
            image_url,
            index,
            img_dir,
            article_url,
            timeout,
            retries=retries,
            cached=cached_rows.get(index),
        )

    if workers == 1:
        for index, image_url in enumerate(urls, 1):
            completed[index - 1] = fetch_one(index, image_url)
            _write_image_checkpoint(checkpoint_path, completed)
    else:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="wechat-image") as pool:
            futures = {
                pool.submit(fetch_one, index, image_url): index - 1
                for index, image_url in enumerate(urls, 1)
            }
            for future in as_completed(futures):
                position = futures[future]
                completed[position] = future.result()
                _write_image_checkpoint(checkpoint_path, completed)

    rows = [row for row in completed if row is not None]
    rows.sort(key=lambda row: int(row["idx"]))
    return rows


def run_ocr(rows: list[dict[str, str]], ocr_path: Path) -> tuple[str, list[dict[str, str]]]:
    try:
        import easyocr
        import numpy as np
        from PIL import Image
    except Exception as exc:  # noqa: BLE001
        write_text(ocr_path, "")
        return f"OCR_IMPORT_ERROR {type(exc).__name__}: {exc}", rows

    reader = easyocr.Reader(["ch_sim", "en"], gpu=False, verbose=False)
    chunks: list[str] = []
    for row in rows:
        path = Path(row["local_path"])
        if not path.exists() or not row["download_status"].startswith("OK"):
            row["ocr_text_length"] = "0"
            continue
        try:
            image = np.array(Image.open(path).convert("RGB"))
            result = reader.readtext(image, detail=0, paragraph=True)
            text = "\n".join(result).strip()
            text = re.sub(r"[ \t]+", " ", text)
            text = re.sub(r"\n{3,}", "\n\n", text)
            row["ocr_text_length"] = str(len(text))
            chunks.append(f"\n\n===== IMAGE {row['idx']} {path.name} =====\n{text}")
        except Exception as exc:  # noqa: BLE001
            row["ocr_text_length"] = f"ERROR {type(exc).__name__}: {exc}"
    ocr_text = "".join(chunks).strip()
    write_text(ocr_path, ocr_text + "\n")
    return "OCR_OK", rows


def decision_label(html_text: str, image_count: int, ocr_status: str, fetch_error: str) -> str:
    if _is_verification_page(html_text):
        return "WECHAT_RESEARCH_INTAKE_BLOCKED_BY_WECHAT_VERIFY"
    if fetch_error and not html_text:
        return "WECHAT_RESEARCH_INTAKE_PARTIAL_NEED_SAVED_HTML"
    if image_count > 0 and ocr_status in {"OCR_OK", "OCR_REUSED"}:
        return "WECHAT_RESEARCH_INTAKE_READY_FOR_STOCK_DRYRUN"
    if image_count > 0 and ocr_status != "OCR_OK":
        return "WECHAT_RESEARCH_INTAKE_PARTIAL_NEED_OCR"
    if article_content_block(html_text) and len(extract_text_preview(html_text)) >= 200:
        return "WECHAT_RESEARCH_INTAKE_READY_FOR_STOCK_DRYRUN"
    if html_text:
        return "WECHAT_RESEARCH_INTAKE_PARTIAL_NEED_SAVED_HTML"
    return "WECHAT_RESEARCH_INTAKE_REJECTED_NO_VERIFIABLE_CONTENT"


def main() -> int:
    parser = argparse.ArgumentParser(description="Dry-run intake for a WeChat Official Account research article.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--html-file", default="")
    parser.add_argument("--skip-ocr", action="store_true")
    parser.add_argument("--reuse-ocr", action="store_true", help="Reuse an existing non-empty OCR text file in the output directory.")
    parser.add_argument("--no-download-images", action="store_true")
    parser.add_argument("--image-timeout", type=int, default=15)
    parser.add_argument(
        "--image-workers", type=int, default=DEFAULT_IMAGE_WORKERS,
        help="Maximum concurrent image downloads (1-3; default: 3).",
    )
    parser.add_argument(
        "--image-retries", type=int, default=DEFAULT_IMAGE_RETRIES,
        help="Retries after the first failed/corrupt image response (0-3; default: 2).",
    )
    parser.add_argument(
        "--fetch-mode", "--transport", dest="fetch_mode", choices=("http", "auto", "crawl4ai"),
        default="http", help="Article HTML transport; auto uses Crawl4AI only after HTTP cannot pass.",
    )
    args = parser.parse_args()

    image_workers = _bounded_image_workers(args.image_workers)
    image_retries = _bounded_image_retries(args.image_retries)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    img_dir = out_dir / "wechat_article_images"
    img_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / "wechat_article_raw.html"
    manifest_path = out_dir / "wechat_article_image_manifest.csv"
    ocr_path = out_dir / "wechat_article_ocr_text.txt"
    summary_path = out_dir / "wechat_article_intake_summary.json"
    report_path = out_dir / "wechat_article_intake_report.md"
    plan_path = out_dir / "wechat_research_collection_usage_plan.md"

    fetch_error = ""
    http_status = 0
    fetch_transport = "saved_html" if args.html_file else args.fetch_mode
    if args.html_file:
        html_text = Path(args.html_file).read_text(encoding="utf-8-sig", errors="ignore")
        write_text(html_path, html_text)
    else:
        html_text, http_status, fetch_error, fetch_transport = fetch_html_with_metadata(
            args.url, html_path, fetch_mode=args.fetch_mode
        )

    title = js_string(html_text, "msg_title") or meta_content(html_text, "twitter:title") or meta_content(html_text, "og:title")
    nickname = (
        meta_content(html_text, "author")
        or meta_content(html_text, "og:article:author")
        or meta_content(html_text, "twitter:creator")
        or js_string(html_text, "nick_name")
        or js_string(html_text, "nickname")
    )
    publish_time = js_number(html_text, "publish_time") or js_number(html_text, "ct")
    biz = js_string(html_text, "__biz") or js_string(html_text, "biz")
    description = meta_content(html_text, "og:description") or meta_content(html_text, "twitter:description")
    article_body_found = bool(article_content_block(html_text))
    text_preview = extract_text_preview(html_text)
    image_urls = extract_image_urls(html_text)
    if args.no_download_images:
        image_rows = [
            {
                "idx": str(idx),
                "url": url,
                "local_path": str(img_dir / f"img_{idx:02d}.jpg"),
                "download_status": "SKIPPED",
                "image_size": "",
                "ocr_text_length": "0",
            }
            for idx, url in enumerate(image_urls, 1)
        ]
    else:
        image_rows = download_images(
            image_urls,
            img_dir,
            args.url,
            max(1, args.image_timeout),
            workers=image_workers,
            retries=image_retries,
            checkpoint_path=out_dir / IMAGE_CHECKPOINT_NAME,
            manifest_path=manifest_path,
        )
    if args.skip_ocr:
        ocr_status = "OCR_SKIPPED"
        write_text(ocr_path, "")
    elif args.reuse_ocr and ocr_path.exists() and ocr_path.stat().st_size > 0:
        ocr_status = "OCR_REUSED"
        cached_ocr = ocr_path.read_text(encoding="utf-8-sig", errors="ignore")
        for row in image_rows:
            if not row.get("ocr_text_length"):
                row["ocr_text_length"] = "REUSED"
    else:
        ocr_status, image_rows = run_ocr(image_rows, ocr_path)
    fields = IMAGE_FIELDS
    write_csv(manifest_path, image_rows, fields)
    ocr_text = ocr_path.read_text(encoding="utf-8-sig", errors="ignore") if ocr_path.exists() else ""
    evidence_hash = hashlib.sha1((html_text[:5000] + ocr_text[:5000]).encode("utf-8", errors="ignore")).hexdigest()
    label = decision_label(html_text, len(image_urls), ocr_status, fetch_error)
    summary = {
        "final_label": label,
        "article_url": args.url,
        "http_status": http_status,
        "fetch_error": fetch_error,
        "fetch_mode": args.fetch_mode,
        "fetch_transport": fetch_transport,
        "image_workers": image_workers,
        "image_retries": image_retries,
        "html_bytes": len(html_text.encode("utf-8", errors="ignore")),
        "title": title,
        "account_name": nickname,
        "raw_publish_time": publish_time,
        "biz": biz,
        "description": description,
        "article_body_found": article_body_found,
        "text_preview_length": len(text_preview),
        "image_count": len(image_urls),
        "downloaded_image_count": sum(1 for row in image_rows if row["download_status"].startswith("OK")),
        "reused_image_count": sum(1 for row in image_rows if row.get("cache_status") == "REUSED"),
        "failed_image_count": sum(1 for row in image_rows if not row["download_status"].startswith("OK")),
        "image_checkpoint_path": str(out_dir / IMAGE_CHECKPOINT_NAME),
        "ocr_status": ocr_status,
        "ocr_text_length": len(ocr_text),
        "evidence_hash": evidence_hash,
        "html_path": str(html_path),
        "image_manifest_path": str(manifest_path),
        "ocr_text_path": str(ocr_path),
    }
    write_text(summary_path, json.dumps(summary, ensure_ascii=False, indent=2))
    write_text(
        report_path,
        f"""# 微信文章只读 Intake

## State Review

- 本轮只判断文章如何进入研报收集 dry-run。
- 不接正式投资决策卡，不触发飞书，不改任务计划，不写正式库。
- 如果正文图片化，必须使用图片和 OCR 证据。

## 抓取结果

- URL: {args.url}
- final_label: {label}
- HTTP: {http_status}
- fetch_error: {fetch_error or '无'}
- 标题: {title or '未提取到'}
- 公众号: {nickname or '未提取到'}
- raw_publish_time: {publish_time or '未提取到'}
- __biz: {biz or '未提取到'}
- 简介: {description or '未提取到'}
- HTML 字节: {summary['html_bytes']}
- 是否找到正文块: {article_body_found}
- 正文文本长度: {len(text_preview)}
- 正文图片数: {len(image_urls)}
- 已下载图片数: {summary['downloaded_image_count']}
- OCR 状态: {ocr_status}
- OCR 字数: {len(ocr_text)}

## 结论

只有 `WECHAT_RESEARCH_INTAKE_READY_FOR_STOCK_DRYRUN` 才能进入股票候选抽取。其他状态必须先补 HTML、图片或 OCR 证据。
""",
    )
    write_text(
        plan_path,
        f"""# 研报收集使用计划

## 来源类型

`WECHAT_RESEARCH_SUBSCRIPTION`

## 当前结论

{label}

## 入库前字段

- article_url: {args.url}
- article_title: {title or '未提取到'}
- account_name: {nickname or '未提取到'}
- biz: {biz or '未提取到'}
- publish_time_raw: {publish_time or '未提取到'}
- evidence_hash: {evidence_hash}
- html_path: {html_path}
- image_manifest_path: {manifest_path}
- ocr_text_path: {ocr_path}

## 下一步

如果 final_label 为 `WECHAT_RESEARCH_INTAKE_READY_FOR_STOCK_DRYRUN`：

1. 从正文或 OCR 抽取股票候选。
2. 分层为 T1_CLEAN_VALUE / T1_VALUE_WITH_RISK / T2 / T3 / REJECT。
3. 生成小白验收面板和红队可读摘要。
4. 保持 `decision_card_allowed=NO`，直到单独授权正式接入。
""",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
