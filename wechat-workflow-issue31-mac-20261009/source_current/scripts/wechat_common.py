# -*- coding: utf-8 -*-
"""Shared helpers for the WeChat public-account pipeline.

Holds path constants, JSON/CSV io, the per-article research data file loader
and the run image count. All shared scripts under scripts/ import from here.
"""
from __future__ import annotations

import csv
import html
import json
import os
import re
import sys
from html.parser import HTMLParser
from datetime import datetime
from pathlib import Path
from pathlib import PureWindowsPath
from urllib.parse import urlsplit


MODULE_ROOT = Path(__file__).resolve().parents[1]


def _windows_layout() -> bool:
    return os.name == "nt" or sys.platform.startswith("win")


if _windows_layout():
    WORK_ROOT = Path(r"C:\Users\huang\Desktop\学习\v3_system\选股池\微信公众号")
    LEARNING_ROOT = Path(r"C:\Users\huang\Desktop\学习")
    LEGACY_ARCHIVE_ROOT = Path(r"C:\Users\huang\Desktop\学习\个股\股票池\风言风语\articles")
    FENGYAN_PIPELINE = Path(r"C:\Users\huang\Desktop\学习\个股\股票池\风言风语\scripts\fengyan_wechat_pipeline.py")
    BUILD_V3 = Path(r"C:\Users\huang\Desktop\学习\个股\scripts\main_scripts\build_wechat_v3_preselect.py")
    DATA_LAYER_INTERFACE = Path(r"C:\Users\huang\Desktop\学习\数据\data_layer_interface_current\DATA_LAYER_INTERFACE.py")
    FETCH_INTAKE = Path(r"C:\Users\huang\Desktop\学习\v3_system\选股池\微信公众号\scripts\wechat_article_fetch.py")
else:
    # On macOS the migrated module is authoritative.  Resolve paths from this
    # checkout so no Windows drive path can leak into a local run.
    WORK_ROOT = MODULE_ROOT
    LEARNING_ROOT = WORK_ROOT.parents[2]
    # The migrated run/artifact tree and the historical Fengyan archive are
    # deliberately separate roots.  This is a definition only: archive sync
    # remains an explicit later stage and never writes during import.
    LEGACY_ARCHIVE_ROOT = LEARNING_ROOT / "个股" / "股票池" / "风言风语" / "articles"
    FENGYAN_PIPELINE = LEARNING_ROOT / "个股" / "股票池" / "风言风语" / "scripts" / "fengyan_wechat_pipeline.py"
    BUILD_V3 = LEARNING_ROOT / "个股" / "scripts" / "main_scripts" / "build_wechat_v3_preselect.py"
    DATA_LAYER_INTERFACE = LEARNING_ROOT / "数据" / "data_layer_interface_current" / "DATA_LAYER_INTERFACE.py"
    FETCH_INTAKE = MODULE_ROOT / "scripts" / "wechat_article_fetch.py"
RUNS_DIR = WORK_ROOT / "runs"
ARTICLES_DIR = WORK_ROOT / "articles"

BOUNDARY = ["RESEARCH_ONLY", "WATCH_ONLY", "NO_BUY_GATE"]


class UnsafePathError(ValueError):
    """Raised when a pipeline path escapes its declared local root."""


def _has_parent_component(raw: str) -> bool:
    """Reject both native and Windows spellings of ``..`` components."""

    return ".." in Path(raw).parts or ".." in PureWindowsPath(raw).parts


def _reject_symlink_components(path: Path, label: str) -> None:
    """Reject symlinks in the lexical path before resolving them.

    Checking only the resolved path loses the evidence that an input entered
    the run through a symlink (including a symlinked parent).  Walk the
    platform-native spelling first, while allowing not-yet-created output
    leaves.
    """

    lexical = Path(os.path.abspath(str(path)))
    current = Path(lexical.anchor or os.curdir)
    components = lexical.parts[1:] if lexical.anchor else lexical.parts
    # macOS exposes temporary directories through these stable system aliases
    # (for example /var -> /private/var).  They are not run-owned links and
    # must not make every TemporaryDirectory-based invocation unusable.
    system_aliases = {Path("/var"), Path("/tmp")}
    for component in components:
        current = current / component
        if current.is_symlink() and current not in system_aliases:
            raise UnsafePathError(f"unsafe {label}: symlink component {current}")


def safe_run_path(
    root: Path,
    value: str | Path,
    *,
    must_exist: bool = False,
    label: str = "path",
) -> Path:
    """Return a real path contained by ``root`` and reject symlinks/traversal.

    Pipeline manifests may contain paths copied from Windows.  A Mac process
    must never interpret those paths as a new local root, nor follow a link out
    of the current run.  ``must_exist`` is intentionally opt-in so callers can
    validate output destinations before creating them.
    """

    root_path = Path(root)
    raw = str(value if value is not None else "").strip()
    if not raw:
        raise UnsafePathError(f"{label} is empty")
    if "\x00" in raw or _has_parent_component(raw):
        raise UnsafePathError(f"unsafe {label}: traversal is not allowed")
    if root_path.is_symlink():
        raise UnsafePathError(f"unsafe root for {label}: symlink")
    _reject_symlink_components(root_path, f"root for {label}")
    root_real = root_path.resolve(strict=False)
    if not root_real.exists() or not root_real.is_dir():
        raise UnsafePathError(f"root for {label} is not a directory: {root_real}")

    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = root_path / candidate
    _reject_symlink_components(candidate, label)
    candidate_real = candidate.resolve(strict=False)
    try:
        relative = candidate_real.relative_to(root_real)
    except ValueError as exc:
        raise UnsafePathError(f"unsafe {label}: outside {root_real}: {raw}") from exc

    # Check every existing component, not only the leaf.  A symlinked parent
    # can otherwise resolve back inside the root after leaving it temporarily.
    current = root_real
    for component in relative.parts:
        current = current / component
        if current.is_symlink():
            raise UnsafePathError(f"unsafe {label}: symlink component {current}")
    if must_exist and not candidate_real.exists():
        raise FileNotFoundError(f"{label} does not exist: {candidate_real}")
    return candidate_real


def validate_run_dir(run_dir: str | Path) -> Path:
    """Validate an existing run directory before any child process runs."""

    path = Path(run_dir)
    raw = str(run_dir)
    if _has_parent_component(raw) or path.is_symlink():
        raise UnsafePathError(f"unsafe run directory: {run_dir}")
    _reject_symlink_components(path, "run directory")
    resolved = path.resolve(strict=False)
    if not resolved.is_dir():
        raise UnsafePathError(f"run directory is not a directory: {resolved}")
    # Walk existing parents to reject a symlinked component even when the leaf
    # itself is a real directory.
    current = Path(resolved.anchor or "/")
    for component in resolved.parts[1:] if resolved.anchor else resolved.parts:
        current = current / component
        if current.is_symlink():
            raise UnsafePathError(f"unsafe run directory: symlink component {current}")
    return resolved


def normalize_date(value: object, *, label: str = "date", allow_empty: bool = False) -> str:
    """Normalize a date to YYYYMMDD and reject invalid/future-ambiguous input."""

    raw = str(value or "").strip()
    if "\x00" in raw or ".." in raw:
        raise ValueError(f"unsafe {label}: {value!r}")
    text = re.sub(r"\D", "", raw)
    if not text and allow_empty:
        return ""
    if not re.fullmatch(r"20\d{6}", text):
        raise ValueError(f"invalid {label}: {value!r}")
    try:
        datetime.strptime(text, "%Y%m%d")
    except ValueError as exc:
        raise ValueError(f"invalid {label}: {value!r}") from exc
    return text


def normalize_title(value: object, *, label: str = "title") -> str:
    """Normalize a title for child-process arguments without path/control chars."""

    text = " ".join(str(value or "").split())
    if not text or len(text) > 300 or any(ord(ch) < 32 for ch in text):
        raise ValueError(f"invalid {label}")
    if "/" in text or "\\" in text:
        raise ValueError(f"unsafe {label}: path separators are not allowed")
    return text


def normalize_security_code(value: object) -> str:
    """Normalize a security code without letting a bare code evade guards.

    Market-qualified codes keep their market suffix.  A bare code remains
    visibly bare because its market is not confirmed; callers use
    :func:`security_code_matches` when comparing exclusions/presence so
    ``03625`` and ``03625.HK`` (and any other bare/suffixed pair) cannot be
    treated as different identities.
    """

    text = re.sub(r"\s+", "", str(value or "").strip()).upper()
    if "." in text:
        code, market = text.split(".", 1)
        return f"{code}.{market}"
    return text


def security_code_matches(left: object, right: object) -> bool:
    """Compare codes conservatively, equating a bare code with its suffix."""

    left_code = normalize_security_code(left)
    right_code = normalize_security_code(right)
    if not left_code or not right_code:
        return False
    if left_code == right_code:
        return True
    left_bare = "." not in left_code
    right_bare = "." not in right_code
    if left_bare or right_bare:
        return left_code.split(".", 1)[0] == right_code.split(".", 1)[0]
    return False


def security_code_in(code: object, candidates: object) -> bool:
    """Return whether ``code`` matches one code in an exclusion/presence set."""

    try:
        values = candidates or ()
    except Exception:
        values = ()
    return any(security_code_matches(code, candidate) for candidate in values)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_run_contract(run_dir: Path) -> dict:
    """Load the optional per-run contract without weakening legacy runs."""

    try:
        path = safe_run_path(run_dir, "run_contract.json", must_exist=True, label="run contract")
    except (OSError, ValueError, FileNotFoundError):
        return {}
    try:
        value = read_json(path)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def selector_exact_date_required(run_dir: Path) -> bool:
    """Return whether this run requires a selector panel on the article date."""

    contract = load_run_contract(run_dir)
    selector = contract.get("selector") if isinstance(contract.get("selector"), dict) else {}
    return str(selector.get("mode") or "").strip().upper() == "EXACT_ARTICLE_DATE"


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8-sig")


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def image_count(run_dir: Path) -> int:
    manifest = read_json(run_dir / "ocr_slice_manifest.json")
    return int(manifest["image_count"])


def load_article_research(run_dir: Path) -> dict:
    """Load the per-article research data file. Returns an empty shell if absent."""
    try:
        path = safe_run_path(run_dir, "article_research.json", must_exist=True, label="article research")
    except FileNotFoundError:
        path = None
    if path is not None:
        return read_json(path)
    return {
        "schema_version": 1,
        "article": {},
        "coverage": {"events": {}, "no_event_notes": {}, "visual_review": {}},
        "pool_resolve": {"exclusions": {}, "additions": {}, "unmapped": []},
        "run_summary_notes": {},
    }


class _ArticleBodyTextParser(HTMLParser):
    """Parse visible text inside js_content; void tags never open a scope.

    The fallback is used only when no js_content root was found. Once found,
    all pre-root text is discarded and all post-root text is ignored.
    Subclasses may override on_image without duplicating HTML scope logic.
    """

    VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input",
                      "link", "meta", "param", "source", "track", "wbr"})
    BLOCK = frozenset({"p", "div", "section", "article", "blockquote", "li", "ul", "ol",
                       "h1", "h2", "h3", "h4", "h5", "h6", "table", "tr", "pre"})
    HIDDEN = frozenset({"script", "style", "noscript"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._stack: list[str] = []
        self._hidden: list[str] = []
        self._found_root = False
        self._parts: list[str] = []

    def on_image(self, attrs: list[tuple[str, str | None]]) -> None:
        pass

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self._hidden:
            if tag not in self.VOID:
                self._hidden.append(tag)
            return
        if tag in self.HIDDEN:
            self._hidden.append(tag)
            return
        attrs_map = dict(attrs)
        if not self._found_root and attrs_map.get("id") == "js_content":
            self._found_root = True
            self._parts.clear()
            self._stack = [tag]
            return
        if self._found_root and not self._stack:
            return
        if tag in self.BLOCK or tag in {"br", "hr"}:
            self._parts.append("\n")
        elif tag in {"td", "th"}:
            self._parts.append("\t")
        if self._stack:
            if tag == "img":
                self.on_image(attrs)
            if tag not in self.VOID:
                self._stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.VOID:
            return
        if self._hidden:
            if tag in self._hidden:
                del self._hidden[len(self._hidden) - 1 - self._hidden[::-1].index(tag):]
            return
        if self._stack and tag in self._stack:
            del self._stack[len(self._stack) - 1 - self._stack[::-1].index(tag):]
            if tag in self.BLOCK:
                self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._hidden and (self._stack or not self._found_root):
            self._parts.append(re.sub(r"\s+", " ", data))

    def text(self) -> str:
        lines = [re.sub(r" +", " ", line).strip() for line in "".join(self._parts).splitlines()]
        return "\n".join(line for line in lines if line)


def article_body_text(raw_html: object) -> str:
    """Return deterministic visible article text, never regex-rebuild failed HTML."""
    parser = _ArticleBodyTextParser()
    parser.feed(str(raw_html or ""))
    parser.close()
    return parser.text()


def validate_slice_geometry(item: dict) -> None:
    """Require ordered, gap-free, non-overlapping vertical coverage.

    This checks coordinates, not image-to-crop semantic equality. The original
    image and each crop must separately be hash-bound by the caller.
    """
    parts = item.get("parts") or []
    if not isinstance(parts, list) or bool(item.get("sliced")) != bool(parts):
        raise ValueError("slice flag/parts mismatch")
    width, height = item.get("width"), item.get("height")
    if not all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in (width, height)):
        raise ValueError("image dimensions are missing or invalid")
    if not parts:
        if max(width, height) > 10000:
            raise ValueError("oversize image has no complete slice coverage")
        return
    top = 0
    for number, part in enumerate(parts, 1):
        if not isinstance(part, dict):
            raise ValueError("slice must be an object")
        values = [part.get(k) for k in ("part", "top", "bottom", "width", "height")]
        if any(isinstance(v, bool) or not isinstance(v, int) for v in values):
            raise ValueError("slice coordinates must be integers")
        if (part["part"] != number or part["top"] != top or
                part["bottom"] <= top or part["width"] != width or
                part["height"] != part["bottom"] - top or part["bottom"] > height):
            raise ValueError("slice order/range does not cover the original image")
        top = part["bottom"]
    if top != height:
        raise ValueError("slice coverage is missing the image tail")


def ocr_record_complete(record: dict) -> bool:
    """Success is exact status + nonempty text at every declared part."""
    if record.get("status") not in {"OCR_OK", "OCR_OK_SLICED"} or not str(record.get("text") or "").strip():
        return False
    parts = record.get("parts") or []
    if not isinstance(parts, list) or (record.get("status") == "OCR_OK_SLICED") != bool(parts):
        return False
    for n, part in enumerate(parts, 1):
        if (not isinstance(part, dict) or part.get("part") != n or part.get("status") != "OCR_OK"
                or not str(part.get("text") or "").strip() or part.get("error")):
            return False
    if parts:
        joined = "\n".join(str(part["text"]) for part in parts).strip()
        if joined != str(record["text"]).strip():
            return False
    return not bool(record.get("error"))


def title_tokens(yyyymmdd: str) -> list[str]:
    date = re.sub(r"\D", "", yyyymmdd or "")
    if not re.fullmatch(r"20\d{6}", date):
        return []
    month = int(date[4:6])
    day = int(date[6:8])
    return [f"{month}.{day}", f"{month}-{day}", f"{month}/{day}",
            f"{month}月{day}日", f"{month}月{day}", f"{month:02d}.{day:02d}"]


def runtime_evidence_context(run_dir: Path) -> dict[str, object]:
    """Expected API/UI evidence identity derived from current run artifacts."""

    try:
        mapping = read_json(
            safe_run_path(run_dir, "pool_mapping_summary.json", must_exist=True, label="mapping summary")
        )
    except (OSError, ValueError, json.JSONDecodeError):
        mapping = {}
    try:
        manifest = read_json(
            safe_run_path(run_dir, "wechat_v3_preselect_manifest.json", must_exist=True, label="V3 manifest")
        )
    except (OSError, ValueError, json.JSONDecodeError):
        manifest = {}
    counts = manifest.get("counts") if isinstance(manifest.get("counts"), dict) else {}
    try:
        a_bj_rows = int(mapping.get("a_bj_rows") or 0)
    except (TypeError, ValueError, OverflowError):
        a_bj_rows = 0
    try:
        v3_unique = int(counts.get("wechat_unique_codes") or 0)
    except (TypeError, ValueError, OverflowError):
        v3_unique = 0
    if not v3_unique:
        try:
            v3_unique = int(counts.get("v3_matched_codes") or 0) + int(counts.get("v3_unmatched_codes") or 0)
        except (TypeError, ValueError, OverflowError):
            v3_unique = 0
    pool_size_consistent = a_bj_rows > 0 and v3_unique > 0 and a_bj_rows == v3_unique
    try:
        final_rows = int(mapping.get("final_rows") or 0)
    except (TypeError, ValueError, OverflowError):
        final_rows = 0
    identity = _article_identity_context(run_dir)
    return {
        "pool_size": v3_unique if pool_size_consistent else 0,
        "a_bj_rows": a_bj_rows,
        "final_rows": final_rows,
        "pool_size_consistent": pool_size_consistent,
        "target_date": str(manifest.get("article_publish_date") or manifest.get("signal_date") or ""),
        "effective_trade_date": str(manifest.get("effective_trade_date") or ""),
        **identity,
    }


_IDENTITY_CONTEXT_ALIASES = {
    "url": ("url", "article_url", "canonical_url"),
    "token": ("token", "canonical_token"),
    "title": ("title", "article_title"),
    "biz": ("biz", "__biz"),
    "content_hash": ("content_hash", "evidence_hash", "html_sha256"),
}


def _canonical_context_url(value: object) -> str:
    raw = str(value or "").strip()
    parsed = urlsplit(raw)
    try:
        has_forbidden_authority = bool(parsed.username or parsed.password or parsed.port)
    except ValueError:
        return ""
    if (
        parsed.scheme.lower() != "https"
        or parsed.hostname != "mp.weixin.qq.com"
        or has_forbidden_authority
    ):
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2 or parts[0].lower() != "s" or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", parts[1]):
        return ""
    return f"https://mp.weixin.qq.com/s/{parts[1]}"


def _identity_context_value(mapping: object, field: str) -> str | None:
    if not isinstance(mapping, dict):
        return None
    normalizer = {
        "url": _canonical_context_url,
        "token": lambda value: str(value or "").strip()
        if re.fullmatch(r"[A-Za-z0-9_-]{1,256}", str(value or "").strip())
        else "",
        "title": lambda value: normalize_title(value, label="identity title"),
        "biz": lambda value: str(value or "").strip(),
        "content_hash": lambda value: str(value or "").strip().lower(),
    }[field]
    values: list[str] = []
    sources = [mapping]
    for nested_name in ("article", "identity", "article_identity", "runtime_identity"):
        nested = mapping.get(nested_name)
        if isinstance(nested, dict):
            sources.append(nested)
    for source in sources:
        for name in _IDENTITY_CONTEXT_ALIASES[field]:
            raw = source.get(name)
            if raw is None or not str(raw).strip():
                continue
            try:
                normalized = normalizer(raw)
            except (TypeError, ValueError):
                return None
            if not normalized:
                return None
            values.append(normalized)
    if not values or any(value != values[0] for value in values[1:]):
        return None
    if field == "content_hash" and (
        not re.fullmatch(r"[0-9a-fA-F]{8,128}", values[0])
        or set(values[0]) == {"0"}
    ):
        return None
    return values[0]


def _article_identity_context(run_dir: Path) -> dict[str, str]:
    """Read canonical identity only from the current article_research file."""

    try:
        research = load_article_research(run_dir)
        article = research.get("article", {}) if isinstance(research, dict) else {}
        if not isinstance(article, dict):
            return {}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}
    fields = {
        field: _identity_context_value(article, field)
        for field in _IDENTITY_CONTEXT_ALIASES
    }
    url = fields.get("url") or ""
    token = fields.get("token") or ""
    derived_token = url.rsplit("/", 1)[-1] if url else ""
    if token and derived_token and token != derived_token:
        return {}
    if url and not token:
        token = derived_token
    if not url or not token or any(not fields.get(field) for field in ("title", "biz", "content_hash")):
        # Keep no partial identity in a runtime context.  A missing hash (or
        # any other identity field) must make API/UI evidence unmatchable.
        return {}
    return {
        "url": url,
        "article_url": url,
        "token": token,
        "canonical_token": token,
        "title": fields["title"] or "",
        "article_title": fields["title"] or "",
        "biz": fields["biz"] or "",
        "content_hash": fields["content_hash"] or "",
    }


def runtime_context_matches(context: object, expected: dict[str, object]) -> bool:
    if not isinstance(context, dict) or not isinstance(expected, dict):
        return False
    try:
        pool_size = int(context.get("pool_size"))
        expected_pool_size = int(expected.get("pool_size") or 0)
    except (TypeError, ValueError):
        return False
    if not all(
        _identity_context_value(context, field)
        and _identity_context_value(expected, field)
        and _identity_context_value(context, field) == _identity_context_value(expected, field)
        for field in _IDENTITY_CONTEXT_ALIASES
    ):
        return False
    for mapping in (context, expected):
        url = _identity_context_value(mapping, "url")
        token = _identity_context_value(mapping, "token")
        if not url or not token or url.rsplit("/", 1)[-1] != token:
            return False
    return (
        pool_size > 0
        and expected_pool_size > 0
        and expected.get("pool_size_consistent") is True
        and pool_size == expected_pool_size
        and str(context.get("target_date") or "") == str(expected.get("target_date") or "")
        and str(context.get("effective_trade_date") or "") == str(expected.get("effective_trade_date") or "")
        and bool(str(context.get("target_date") or ""))
        and bool(str(context.get("effective_trade_date") or ""))
    )
