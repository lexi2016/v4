# -*- coding: utf-8 -*-
"""公众号管线编排器：--stage 分步执行，--resume 按工件存在跳过。

stage 顺序：fetch → prepare_ocr → ocr_canary → ocr_full → coverage → extract →
resolve → build_v3 → sync → summary → yesterday → validate。

fetch 调权威 fengyan_wechat_pipeline.py --skip-ocr；build_v3 调权威
build_wechat_v3_preselect.py；extract 调 fengyan_wechat_pipeline.extract_stock_pool。
人工研判（coverage.events / pool_resolve）在对应 stage 前由主控填入 article_research.json。

边界：RESEARCH_ONLY / WATCH_ONLY / NO_BUY_GATE。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from pathlib import PureWindowsPath

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wechat_common import (  # noqa: E402
    WORK_ROOT, FENGYAN_PIPELINE, BUILD_V3, FETCH_INTAKE, LEGACY_ARCHIVE_ROOT,
    UnsafePathError, load_article_research, normalize_date, normalize_title,
    safe_run_path, validate_run_dir, read_json, write_json, runtime_context_matches,
    runtime_evidence_context, _reject_symlink_components, selector_exact_date_required,
    article_body_text,
)

SCRIPT_DIR = Path(__file__).resolve().parent
PY = sys.executable


def _canonical_url(value: object) -> str:
    from wechat_article_fetch import canonical_article_url

    return canonical_article_url(str(value or ""))


def _consistent_article_value(
    article: dict,
    names: tuple[str, ...],
    *,
    field: str,
    normalizer=None,
) -> str:
    """Read aliases without silently selecting one conflicting identity."""

    values: list[str] = []
    for name in names:
        raw = str(article.get(name) or "").strip()
        if raw:
            values.append(normalizer(raw) if normalizer else raw)
    if values and any(value != values[0] for value in values[1:]):
        raise ValueError(f"article identity aliases conflict for {field}")
    return values[0] if values else ""


def resolve_stage_identity(
    article: dict | None,
    *,
    cli_url: str = "",
    cli_title: str = "",
    cli_target_date: str = "",
    cli_effective_trade_date: str = "",
) -> dict[str, str]:
    """Resolve CLI/run identity without allowing a conflicting override."""

    article = article if isinstance(article, dict) else {}
    values = {
        "url": _consistent_article_value(article, ("url", "article_url"), field="url", normalizer=_canonical_url),
        "title": _consistent_article_value(article, ("title", "article_title"), field="title", normalizer=normalize_title),
        "target_date": _consistent_article_value(
            article, ("target_date", "article_date"), field="target_date",
            normalizer=lambda value: normalize_date(value, label="target_date"),
        ),
        "effective_trade_date": _consistent_article_value(
            article, ("effective_trade_date",), field="effective_trade_date",
            normalizer=lambda value: normalize_date(value, label="effective_trade_date"),
        ),
    }
    overrides = {
        "url": str(cli_url or "").strip(),
        "title": str(cli_title or "").strip(),
        "target_date": str(cli_target_date or "").strip(),
        "effective_trade_date": str(cli_effective_trade_date or "").strip(),
    }
    if overrides["url"]:
        overrides["url"] = _canonical_url(overrides["url"])
    if overrides["title"]:
        overrides["title"] = normalize_title(overrides["title"])
    for key in ("target_date", "effective_trade_date"):
        if overrides[key]:
            overrides[key] = normalize_date(overrides[key], label=key)
    for key, override in overrides.items():
        if override and values[key] and override != values[key]:
            raise ValueError(f"CLI {key} conflicts with run article identity")
        if override:
            values[key] = override
    return values


def canary_indices(image_count: int) -> list[int]:
    """Return the fixed [2, floor(N/2), N] image canary without duplicates."""

    count = int(image_count)
    if count < 1:
        return []
    middle = max(1, min(count, count // 2))
    return sorted({max(1, min(count, 2)), middle, count})


def resolve_ocr_backend(platform: str | None = None, powershell_available: bool | None = None) -> str:
    """Select a native OCR route without silently falling back to EasyOCR."""

    current_platform = platform or sys.platform
    if powershell_available is None:
        powershell_available = shutil.which("powershell") is not None or shutil.which("pwsh") is not None
    if current_platform.startswith("win") and powershell_available:
        return "windows_media_ocr"
    if current_platform == "darwin":
        return "macos_vision"
    return "unsupported"


def _sub(*args: str) -> None:
    env_utf8 = child_process_env()
    subprocess.run(list(args), check=True, env=env_utf8)


def _ps1(run_dir: Path, mode: str) -> None:
    backend = resolve_ocr_backend()
    if backend == "windows_media_ocr":
        powershell = shutil.which("powershell") or shutil.which("pwsh") or "powershell"
        ps = str(SCRIPT_DIR / "wechat_windows_ocr.ps1")
        subprocess.run(
            [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps, "-Mode", mode, "-RunDir", str(run_dir)],
            check=True,
            env=child_process_env(),
        )
        return
    if backend == "macos_vision":
        _sub(
            PY,
            "-X",
            "utf8",
            str(SCRIPT_DIR / "wechat_macos_ocr.py"),
            "--mode",
            mode,
            "--run-dir",
            str(run_dir),
        )
        return
    raise RuntimeError(f"no supported native OCR backend for platform {sys.platform}")


def child_process_env() -> dict[str, str]:
    """Return inherited UTF-8/Python-path settings for pipeline children."""

    env = dict(__import__("os").environ)
    env["PYTHONIOENCODING"] = "utf-8"
    pathsep = __import__("os").pathsep
    existing = [item for item in env.get("PYTHONPATH", "").split(pathsep) if item]
    scripts = str(SCRIPT_DIR)
    if not existing or existing[0] != scripts:
        existing = [scripts] + [item for item in existing if item != scripts]
    env["PYTHONPATH"] = pathsep.join(existing)
    env["WECHAT_PANDAS3_COMPAT"] = "1"
    return env


def build_fetch_command(
    run_dir: Path,
    target_date: str,
    url: str,
    platform: str | None = None,
    *,
    image_workers: int | None = None,
    image_retries: int | None = None,
    fetch_mode: str | None = None,
) -> list[str]:
    """Build the platform-safe read-only fetch command for one run."""

    run_dir = validate_run_dir(run_dir)
    target_date = normalize_date(target_date, label="target_date")
    url = _canonical_url(url)
    current_platform = platform or sys.platform
    if current_platform == "darwin":
        command = [
            PY,
            "-X",
            "utf8",
            str(FETCH_INTAKE),
            "--url",
            url,
            "--out",
            str(run_dir),
            "--skip-ocr",
        ]
        if image_workers is not None:
            command.extend(["--image-workers", str(image_workers)])
        if image_retries is not None:
            command.extend(["--image-retries", str(image_retries)])
        if fetch_mode:
            command.extend(["--fetch-mode", str(fetch_mode)])
        return command
    fetch_staging = run_dir / "_fetch_staging"
    return [
        PY,
        "-X",
        "utf8",
        str(FENGYAN_PIPELINE),
        "--target-date",
        target_date,
        "--url",
        url,
        "--run-dir",
        str(run_dir),
        "--v3-system-root",
        str(fetch_staging / "v3_system"),
        "--archive-root",
        str(fetch_staging / "legacy_archive"),
        "--skip-ocr",
    ]


def _run_validator_with_receipt(run_dir: Path) -> dict:
    """Run the read-only validator and persist its machine-readable receipt."""
    run_dir = validate_run_dir(run_dir)
    env_utf8 = child_process_env()
    cmd = [
        PY,
        "-X",
        "utf8",
        str(WORK_ROOT / "validate_wechat_run.py"),
        "--run-dir",
        str(run_dir),
        "--require-latest",
    ]
    completed = subprocess.run(cmd, check=False, capture_output=True, text=True, encoding="utf-8", env=env_utf8)
    raw_stdout = completed.stdout or ""
    try:
        receipt = json.loads(raw_stdout)
    except (TypeError, ValueError, json.JSONDecodeError):
        receipt = {"status": "FAIL", "error": "validator did not emit JSON", "raw_stdout": raw_stdout[-4000:]}
    if not isinstance(receipt, dict):
        receipt = {"status": "FAIL", "error": "validator emitted non-object JSON", "raw_stdout": raw_stdout[-4000:]}
    receipt["validator_returncode"] = int(completed.returncode)
    if completed.stderr:
        receipt["validator_stderr_tail"] = completed.stderr[-2000:]
    # Preserve explicitly supplied runtime-lane evidence alongside the
    # validator checks.  The validator itself is read-only and cannot inspect
    # the live API or a user-visible page, so these fields remain opt-in notes
    # from the run's research contract rather than inferred PASS values.
    research = load_article_research(run_dir)
    notes = research.get("run_summary_notes", {})
    expected_context = runtime_evidence_context(run_dir)
    api_context = notes.get("api_evidence_context") if isinstance(notes, dict) else None
    ui_context = notes.get("ui_evidence_context") if isinstance(notes, dict) else None
    receipt["runtime_evidence_context"] = {
        "expected": expected_context,
        "api": api_context,
        "api_match": runtime_context_matches(api_context, expected_context),
        "ui": ui_context,
        "ui_match": runtime_context_matches(ui_context, expected_context),
    }
    if isinstance(notes, dict):
        if (
            notes.get("api_validated") is True
            and str(notes.get("api_validation_note") or "").strip()
            and runtime_context_matches(api_context, expected_context)
        ):
            receipt["api_status"] = "API_VALIDATED"
            receipt["api_evidence"] = str(notes["api_validation_note"]).strip()
        elif str(notes.get("api_validation_note") or "").strip():
            receipt["api_status"] = "API_PENDING"
            receipt["api_evidence"] = str(notes["api_validation_note"]).strip()
        ui_note = notes.get("ui_verified")
        if ui_note is True and runtime_context_matches(ui_context, expected_context):
            receipt["ui_status"] = "UI_VERIFIED"
        elif isinstance(ui_note, str) and ui_note.strip():
            receipt["ui_status"] = ui_note.strip().upper() if runtime_context_matches(ui_context, expected_context) else "UI_PENDING"
        if str(notes.get("ui_validation_note") or "").strip():
            receipt["ui_evidence"] = str(notes["ui_validation_note"]).strip()
    receipt_path = safe_run_path(run_dir, "validation_receipt.json", label="validation receipt")
    write_json(receipt_path, receipt)
    if completed.returncode != 0:
        raise subprocess.CalledProcessError(completed.returncode, cmd, output=completed.stdout, stderr=completed.stderr)
    return receipt


def _artifact_path(run_dir: Path, value: object) -> Path | None:
    text = str(value or "")
    if not text:
        return None
    try:
        return safe_run_path(run_dir, text, must_exist=True, label="artifact")
    except (OSError, ValueError):
        return None


def _run_local_artifact(run_dir: Path, value: object, *, label: str) -> Path:
    """Resolve an artifact inside the run, mapping Windows paths by basename."""

    run_dir = validate_run_dir(run_dir)
    raw = str(value or "").strip()
    if not raw:
        raise ValueError(f"{label} is empty")
    try:
        resolved = safe_run_path(run_dir, raw, must_exist=True, label=label)
    except (OSError, ValueError, FileNotFoundError) as original:
        # Same-basename recovery is exclusively for absolute Windows paths
        # copied into Mac manifests.  Never turn a native traversal or system
        # path into an apparently safe run-local artifact.
        if "\x00" in raw or ".." in Path(raw).parts or ".." in PureWindowsPath(raw).parts:
            raise original
        if not PureWindowsPath(raw).drive:
            raise original
        basename = PureWindowsPath(raw).name
        if not basename or basename == raw:
            raise original
        resolved = safe_run_path(run_dir, basename, must_exist=True, label=label)
    if resolved.suffix.lower() in {".txt", ".pointer", ".ptr", ".path"}:
        target_raw = resolved.read_text(encoding="utf-8-sig").strip()
        if not target_raw or ".." in Path(target_raw).parts or ".." in PureWindowsPath(target_raw).parts:
            raise ValueError(f"unsafe {label} pointer target")
        target = Path(target_raw)
        if PureWindowsPath(target_raw).drive:
            basename = PureWindowsPath(target_raw).name
            if not basename:
                raise ValueError(f"unsafe {label} pointer target")
            target = basename
        return safe_run_path(run_dir, target, must_exist=True, label=label)
    return resolved


def _resolve_selector_artifact(run_dir: Path, value: object) -> Path:
    """Resolve a selector path while permitting an explicit external panel.

    Run outputs and copied Windows paths must remain run-local.  A selector
    snapshot is different: the operator may explicitly supply the reviewed
    immutable panel that lives in the shared data workspace.  Delegate the
    path and symlink checks to the extractor's selector resolver so this
    exception cannot widen the generic artifact boundary.
    """

    raw = str(value or "").strip()
    if not raw:
        raise ValueError("selector panel is empty")
    declared = Path(raw)
    if declared.is_absolute():
        # An explicit absolute path can still point at the current run (the
        # tests and generated manifests commonly do this).  Resolve that
        # case through the run boundary before considering the shared data
        # roots below.  This keeps the external-panel exception narrow.
        try:
            return _run_local_artifact(run_dir, declared, label="selector panel")
        except (OSError, ValueError, FileNotFoundError):
            pass
        from wechat_extract_stock_pool import _selector_external_path_allowed, _selector_target_path

        if not _selector_external_path_allowed(declared):
            raise ValueError("selector panel UNSAFE_PANEL_PATH")
        resolved, status = _selector_target_path(declared)
        if status != "OK" or resolved is None:
            raise ValueError(f"selector panel {status}")
        return resolved
    return _run_local_artifact(run_dir, declared, label="selector panel")


def _intake_semantically_ready(
    run_dir: Path,
    article: dict | None = None,
    *,
    expected_url: str = "",
    expected_title: str = "",
    expected_date: str = "",
) -> bool:
    try:
        intake_path = safe_run_path(
            validate_run_dir(run_dir),
            "wechat_article_intake_summary.json",
            must_exist=True,
            label="intake summary",
        )
    except (OSError, ValueError):
        return False
    intake = _load_json(intake_path)
    if not isinstance(intake, dict):
        return False
    try:
        article = article if isinstance(article, dict) else {}
        _require_exact_intake(
            run_dir,
            article,
            expected_url=expected_url or str(intake.get("article_url") or intake.get("url") or ""),
            expected_title=expected_title,
            expected_date=expected_date,
        )
    except (OSError, ValueError, TypeError, RuntimeError):
        return False
    return True


def _intake_artifacts_ready(run_dir: Path, summary: dict) -> bool:
    """Ensure declared intake files are real, non-empty, and not a verify page."""

    try:
        from wechat_article_fetch import _validate_intake_artifacts

        _validate_intake_artifacts(run_dir, summary)
    except (OSError, ValueError, TypeError):
        return False
    return True


def _require_exact_intake(
    run_dir: Path,
    article: dict | None,
    *,
    expected_url: str = "",
    expected_title: str = "",
    expected_date: str = "",
) -> dict[str, object]:
    """Validate intake identity against the run's reviewed article metadata."""

    run_dir = validate_run_dir(run_dir)
    try:
        summary_path = safe_run_path(
            run_dir,
            "wechat_article_intake_summary.json",
            must_exist=True,
            label="intake summary",
        )
    except (OSError, ValueError) as exc:
        raise RuntimeError("exact intake identity summary is missing or invalid") from exc
    summary = _load_json(summary_path)
    if not isinstance(summary, dict):
        raise RuntimeError("exact intake identity summary is missing or invalid")
    article = article if isinstance(article, dict) else {}
    try:
        article_identity = resolve_stage_identity(article)
        article_biz = _consistent_article_value(
            article, ("biz", "__biz"), field="biz"
        )
        article_hash = _consistent_article_value(
            article,
            ("content_hash", "evidence_hash", "html_sha256"),
            field="content_hash",
            normalizer=lambda value: str(value).strip().lower(),
        )
        article_account = _consistent_article_value(
            article,
            ("account", "account_name", "nickname"),
            field="account",
        )
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError("article_research identity is missing or conflicting") from exc
    expected_url = str(expected_url or article_identity["url"] or "").strip()
    if not expected_url:
        expected_url = str(summary.get("article_url") or summary.get("url") or "").strip()
    try:
        from wechat_article_fetch import validate_intake_identity

        identity = validate_intake_identity(summary, expected_url)
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError(f"exact intake identity is not verified: {exc}") from exc

    if article_identity["url"] and article_identity["url"] != identity["url"]:
        raise RuntimeError("intake URL conflicts with article_research identity")
    expected_title = str(expected_title or article_identity["title"] or "").strip()
    if expected_title and normalize_title(expected_title) != identity["title"]:
        raise RuntimeError("intake title conflicts with article_research identity")
    expected_date = str(expected_date or article_identity["target_date"] or "").strip()
    if expected_date and normalize_date(expected_date, label="article date") != identity["article_date"]:
        raise RuntimeError("intake article date conflicts with article_research identity")
    if article_account and article_account != identity["account"]:
        raise RuntimeError("intake account conflicts with article_research identity")
    if article_biz and article_biz != identity["biz"]:
        raise RuntimeError("intake biz conflicts with article_research identity")
    if article_hash and article_hash != identity["content_hash"]:
        raise RuntimeError("intake content hash conflicts with article_research identity")
    for article_key, intake_key in (
        ("account", "account"),
        ("account_name", "account"),
        ("biz", "biz"),
        ("content_hash", "content_hash"),
        ("evidence_hash", "content_hash"),
        ("html_sha256", "content_hash"),
    ):
        expected = str(article.get(article_key) or "").strip()
        if article_key in {"content_hash", "evidence_hash", "html_sha256"}:
            expected = expected.lower()
        if expected and expected != identity[intake_key]:
            raise RuntimeError(f"intake {intake_key} conflicts with article_research identity")
    if not _intake_artifacts_ready(run_dir, summary):
        raise RuntimeError("intake artifacts are not contained by the run")
    return {"summary": summary, "identity": identity}


def _require_selector_sidecar(run_dir: Path, panel_path: Path) -> None:
    """Verify the hash sidecar required by a frozen CSV selector snapshot."""

    panel_path = Path(panel_path)
    try:
        panel_path.relative_to(validate_run_dir(run_dir) / "_frozen_inputs")
    except ValueError:
        # Temporary/non-frozen fixtures retain the legacy no-sidecar
        # compatibility; frozen selector snapshots are a stricter contract.
        return
    if panel_path.suffix.lower() != ".csv":
        return
    try:
        sidecar = safe_run_path(
            validate_run_dir(run_dir),
            panel_path.with_suffix(".manifest.json"),
            label="selector sidecar",
        )
    except (OSError, ValueError) as exc:
        raise RuntimeError("selector sidecar path is unsafe") from exc
    if not sidecar.is_file() or sidecar.is_symlink():
        raise RuntimeError("selector sidecar is missing")
    try:
        value = json.loads(sidecar.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("selector sidecar is not valid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError("selector sidecar must be a JSON object")
    expected = {}
    for field in ("source_sha256", "copied_sha256"):
        digest = str(value.get(field) or "").strip()
        if len(digest) != 64 or any(char not in "0123456789abcdefABCDEF" for char in digest):
            raise RuntimeError(f"selector sidecar {field} is not a 64-hex digest")
        expected[field] = digest.lower()
    try:
        actual = hashlib.sha256(panel_path.read_bytes()).hexdigest()
    except (OSError, ValueError) as exc:
        raise RuntimeError("selector panel cannot be hashed") from exc
    if any(digest != actual for digest in expected.values()):
        raise RuntimeError("selector sidecar SHA does not match selector CSV")


def _require_selector_snapshot(run_dir: Path, article_date: str, panel: str = "") -> Path:
    """Require a local, PIT-valid selector snapshot before extraction/build."""

    try:
        from wechat_extract_stock_pool import _read_selector_rows, _selector_panel_path, _selector_target_path

        declared = Path(panel) if str(panel or "").strip() else _selector_panel_path(run_dir)
        if declared is None:
            raise RuntimeError("selector panel is missing")
        panel_path = _resolve_selector_artifact(run_dir, declared)
        resolved, status = _selector_target_path(panel_path)
        if status != "OK" or resolved is None:
            raise RuntimeError(status)
        _require_selector_sidecar(run_dir, resolved)
        rows, status = _read_selector_rows(
            resolved,
            article_date,
            exact_date=selector_exact_date_required(run_dir),
        )
    except (OSError, ValueError, TypeError, ImportError) as exc:
        raise RuntimeError(f"selector snapshot cannot be loaded: {exc}") from exc
    if status != "OK" or not rows:
        raise RuntimeError(f"selector snapshot is not PIT-valid: {status}")
    return Path(resolved)


def _optional_selector_snapshot(run_dir: Path, article_date: str, panel: str = "") -> Path | None:
    """Resolve an explicitly supplied selector, or select source-only mode."""

    if not str(panel or "").strip():
        return None
    return _require_selector_snapshot(run_dir, article_date, panel)


def _resume_identity_ready(
    run_dir: Path, *, require_selector: bool, panel: str = ""
) -> bool:
    """Apply the same identity/PIT gates before a checkpoint is skipped."""

    research = load_article_research(run_dir)
    article = research.get("article", {}) if isinstance(research, dict) else {}
    identity = resolve_stage_identity(article)
    if not identity["target_date"]:
        return False
    _require_exact_intake(run_dir, article)
    if require_selector:
        _require_selector_snapshot(run_dir, identity["target_date"], panel)
    return True


_BUILD_MANIFEST_IDENTITY_ALIASES = {
    "url": ("url", "article_url", "canonical_url"),
    "token": ("token", "canonical_token"),
    "title": ("title", "article_title"),
    "biz": ("biz", "__biz"),
    "content_hash": ("content_hash", "evidence_hash", "html_sha256"),
}


def _build_manifest_identity_matches(
    manifest: object, intake_identity: object
) -> bool:
    """Require a V3 manifest to describe the exact verified article intake."""

    if not isinstance(manifest, dict) or not isinstance(intake_identity, dict):
        return False
    expected = {
        "url": _canonical_url(intake_identity.get("url")),
        "token": str(intake_identity.get("token") or "").strip(),
        "title": normalize_title(intake_identity.get("title")),
        "biz": str(intake_identity.get("biz") or "").strip(),
        "content_hash": str(intake_identity.get("content_hash") or "").strip().lower(),
    }
    if not all(expected.values()):
        return False

    sources = [manifest]
    for nested_name in ("article", "identity", "article_identity", "runtime_identity"):
        nested = manifest.get(nested_name)
        if isinstance(nested, dict):
            sources.append(nested)

    normalizers = {
        "url": _canonical_url,
        "token": lambda value: str(value or "").strip(),
        "title": normalize_title,
        "biz": lambda value: str(value or "").strip(),
        "content_hash": lambda value: str(value or "").strip().lower(),
    }
    for field, names in _BUILD_MANIFEST_IDENTITY_ALIASES.items():
        values: list[str] = []
        for source in sources:
            for name in names:
                raw = source.get(name)
                if raw is None or not str(raw).strip():
                    continue
                try:
                    normalized = normalizers[field](raw)
                except (TypeError, ValueError):
                    return False
                if not normalized:
                    return False
                values.append(normalized)
        if not values or any(value != values[0] for value in values[1:]):
            return False
        if values[0] != expected[field]:
            return False
    return True


def _fetch_identity_ready(run_dir: Path) -> bool:
    """Require fetch checkpoints to bind every current article identity field."""

    try:
        research = load_article_research(run_dir)
        article = research.get("article", {}) if isinstance(research, dict) else {}
        if not isinstance(article, dict):
            return False
        identity = resolve_stage_identity(article)
        biz = _consistent_article_value(article, ("biz", "__biz"), field="biz")
        content_hash = _consistent_article_value(
            article,
            ("content_hash", "evidence_hash", "html_sha256"),
            field="content_hash",
            normalizer=lambda value: str(value).strip().lower(),
        )
        if not all((identity["url"], identity["title"], identity["target_date"], biz, content_hash)):
            return False
        _require_exact_intake(
            run_dir,
            article,
            expected_url=identity["url"],
            expected_title=identity["title"],
            expected_date=identity["target_date"],
        )
    except (OSError, ValueError, TypeError, RuntimeError):
        return False
    return True


def _run_fetch(
    run_dir: Path,
    target_date: str,
    url: str,
    *,
    article: dict | None = None,
    title: str = "",
    image_workers: int | None = None,
    image_retries: int | None = None,
    fetch_mode: str | None = None,
) -> None:
    """Fetch source artifacts; tolerate legacy skip-OCR empty-pool exit.

    The legacy command performs extraction after the skip-OCR fetch and exits
    with ``FAIL_EMPTY_STOCK_POOL`` because OCR text is intentionally empty.
    A semantically complete intake is still a valid fetch checkpoint, so only
    that post-fetch exit is tolerated; transport/identity failures remain
    fatal.
    """
    run_dir = validate_run_dir(run_dir)
    # The collector writes these paths directly.  Reject pre-existing links
    # before invoking it so a stale run cannot redirect an output outside the
    # validated run root.
    for name in (
        "wechat_article_intake_summary.json",
        "wechat_article_raw.html",
        "wechat_article_image_manifest.csv",
        "wechat_article_ocr_text.txt",
        "wechat_article_intake_report.md",
        "wechat_research_collection_usage_plan.md",
        "wechat_article_images",
        "_fetch_staging",
    ):
        _reject_symlink_components(run_dir / name, f"fetch output {name}")
    image_dir = run_dir / "wechat_article_images"
    if image_dir.is_dir():
        for path in image_dir.iterdir():
            _reject_symlink_components(path, f"fetch image output {path.name}")
    # The legacy fetch command also performs archive/sync work before OCR.  Keep
    # those side effects inside the run until the explicit ``sync`` stage.
    fetch_staging = run_dir / "_fetch_staging"
    v3_staging = fetch_staging / "v3_system"
    archive_staging = fetch_staging / "legacy_archive"
    if (sys.platform or "").startswith("win"):
        v3_staging.mkdir(parents=True, exist_ok=True)
        archive_staging.mkdir(parents=True, exist_ok=True)

    env_utf8 = child_process_env()
    cmd = build_fetch_command(
        run_dir,
        target_date,
        url,
        image_workers=image_workers,
        image_retries=image_retries,
        fetch_mode=fetch_mode,
    )
    completed = subprocess.run(cmd, check=False, capture_output=True, text=True, encoding="utf-8", env=env_utf8)
    research = load_article_research(run_dir)
    reviewed_article = article if isinstance(article, dict) else (
        research.get("article", {}) if isinstance(research, dict) else {}
    )
    if not isinstance(reviewed_article, dict):
        reviewed_article = {}
    try:
        _require_exact_intake(
            run_dir,
            reviewed_article,
            expected_url=url,
            expected_title=title,
            expected_date=target_date,
        )
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        if completed.returncode == 0:
            raise RuntimeError("fetch completed without an exact intake identity checkpoint") from exc
        exact_intake_error = exc
    else:
        exact_intake_error = None
    if completed.returncode == 0:
        return
    failure_output = f"{completed.stdout or ''}\n{completed.stderr or ''}"
    if "FAIL_EMPTY_STOCK_POOL" in failure_output and exact_intake_error is None:
        print(json.dumps({"status": "FETCH_INTAKE_READY", "pipeline_returncode": completed.returncode}, ensure_ascii=False))
        return
    raise subprocess.CalledProcessError(completed.returncode, cmd, output=completed.stdout, stderr=completed.stderr)


def build_v3_command(
    run_dir: Path,
    target_date: str,
    effective_trade_date: str,
    title: str,
    panel: str = "",
) -> list[str]:
    """Build the V3 observation command with an optional frozen panel."""

    run_dir = validate_run_dir(run_dir)
    target_date = normalize_date(target_date, label="target_date")
    effective_trade_date = normalize_date(effective_trade_date, label="effective_trade_date")
    title = normalize_title(title)
    command = [
        PY,
        "-X",
        "utf8",
        str(BUILD_V3),
        "--wechat-pool",
        str(Path(run_dir) / "wechat_stock_pool_raw.csv"),
        "--signal-date",
        target_date,
        "--target-date",
        target_date,
        "--effective-trade-date",
        effective_trade_date,
        "--target-title-token",
        title.replace("风言风语信息更新 ", "").strip(),
        "--output-dir",
        str(run_dir),
    ]
    if str(panel or "").strip():
        panel_path = _resolve_selector_artifact(run_dir, panel)
        command.extend(["--panel", str(panel_path)])
    return command


def _has(path: Path) -> bool:
    return path.exists()


STAGES = [
    "fetch", "prepare_ocr", "ocr_canary", "ocr_full", "coverage",
    "extract", "resolve", "build_v3", "sync", "summary", "yesterday",
    "baimao_observations", "validate",
]

CHECKPOINT_FILES = {
    "fetch": "wechat_article_intake_summary.json",
    "prepare_ocr": "ocr_slice_manifest.json",
    "ocr_canary": "windows_ocr_canary.json",
    "ocr_full": "windows_ocr_results.json",
    "coverage": "source_coverage_summary.json",
    "extract": "wechat_stock_pool_raw_initial.csv",
    "resolve": "wechat_stock_pool_raw.csv",
    "build_v3": "wechat_v3_preselect_manifest.json",
    "sync": None,
    "summary": "run_summary.json",
    "yesterday": None,
    "baimao_observations": "baimao_reader_out/baimao_research_observations.json",
    "validate": None,
}


def _load_json(path: Path) -> dict | list | None:
    try:
        _reject_symlink_components(Path(path), "JSON artifact")
    except (OSError, ValueError):
        return None
    if path.is_symlink() or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _csv_row_count(path: Path) -> int:
    try:
        _reject_symlink_components(Path(path), "CSV artifact")
    except (OSError, ValueError):
        return -1
    if path.is_symlink() or not path.is_file():
        return -1
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return sum(1 for _ in csv.DictReader(handle))
    except (OSError, csv.Error):
        return -1


def _checkpoint_int(value: object, default: int = -1) -> int:
    """Parse checkpoint counters without allowing malformed JSON to raise."""

    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _entity_scan_checkpoint_valid(run_dir: Path, *, source_only_allowed: bool = False) -> bool:
    """Require a complete, closed OCR/entity scan before extract/resolve resume."""

    summary = _load_json(run_dir / "security_entity_candidates_summary.json")
    if not isinstance(summary, dict):
        return False
    scan_status = str(summary.get("scan_status") or "").upper()
    if scan_status not in {"PASS", "PASS_SOURCE_ONLY"}:
        return False
    if scan_status == "PASS_SOURCE_ONLY":
        if (
            not source_only_allowed
            or str(summary.get("scan_mode") or "").upper() != "SOURCE_ONLY"
            or str(summary.get("selector_status") or "").upper() not in {"MISSING_PANEL", "NO_SELECTOR"}
        ):
            return False
    elif source_only_allowed:
        return False
    ocr_status = str(summary.get("ocr_status") or "").strip().upper()
    if ocr_status not in {"OK", "OCR_OK", "COMPLETE", "FULL_OCR_OK"} and not ocr_status.startswith("OCR_OK"):
        return False
    image_count = _checkpoint_int(summary.get("ocr_image_count"), 0)
    candidate_count = _checkpoint_int(
        summary.get("candidate_count", summary.get("entity_candidate_count")), -1
    )
    if ("ocr_image_count" in summary and image_count < 0) or candidate_count < 0:
        return False

    count_pairs = (
        ("mapped_count", "unmapped_count"),
        ("entity_mapped_count", "entity_unmapped_count"),
        ("ocr_mapped_count", "ocr_unmapped_count"),
    )
    mapped = unmapped = None
    for mapped_key, unmapped_key in count_pairs:
        if mapped_key in summary and unmapped_key in summary:
            mapped = _checkpoint_int(summary.get(mapped_key), -1)
            unmapped = _checkpoint_int(summary.get(unmapped_key), -1)
            break
    if mapped is None or unmapped is None or mapped < 0 or unmapped < 0:
        return False
    return mapped + unmapped == candidate_count


def source_summary_prerequisites(run_dir: Path) -> tuple[bool, str]:
    """Validate the source-only summary inputs without requiring a V3 manifest.

    Source-only mode is an explicit recovery lane for a missing exact-date
    selector.  It reuses the existing intake, coverage, OCR and entity gates,
    then checks the resolved pool and both entity ledgers before allowing the
    summary writer to run.  No runtime/API/UI lane is inferred here.
    """

    try:
        run_dir = validate_run_dir(run_dir)
        research = load_article_research(run_dir)
        article = research.get("article", {}) if isinstance(research, dict) else {}
        identity = resolve_stage_identity(article)
        if not identity["target_date"]:
            return False, "source-only summary requires article target_date"
        _require_exact_intake(run_dir, article)
        if not _coverage_checkpoint_valid(run_dir):
            return False, "source-only summary requires a valid current coverage checkpoint"
        if not _full_ocr_provenance_valid(run_dir):
            return False, "source-only summary requires valid full OCR provenance"
        entity_summary = _load_json(run_dir / "security_entity_candidates_summary.json")
        if not _entity_scan_checkpoint_valid(run_dir, source_only_allowed=True):
            return False, "source-only summary requires a closed SOURCE_ONLY entity scan"
        if not isinstance(entity_summary, dict):
            return False, "source-only summary requires an entity scan summary"
        mapping = _load_json(run_dir / "pool_mapping_summary.json")
        if not isinstance(mapping, dict) or mapping.get("status") != "PASS":
            return False, "source-only summary requires a PASS resolved pool mapping"
        rows = _csv_row_count(run_dir / "wechat_stock_pool_raw.csv")
        if rows < 0 or _checkpoint_int(mapping.get("final_rows"), -1) != rows:
            return False, "source-only summary resolved pool count does not match current rows"
        if _checkpoint_int(mapping.get("entity_unresolved_count"), -1) != 0:
            return False, "source-only summary requires entity_unresolved_count=0"

        candidates_path = safe_run_path(run_dir, "security_entity_candidates.csv", must_exist=True, label="entity candidates")
        ledger_path = safe_run_path(run_dir, "security_entity_coverage_ledger.csv", must_exist=True, label="entity ledger")
        with candidates_path.open("r", encoding="utf-8-sig", newline="") as handle:
            candidates = list(csv.DictReader(handle))
        with ledger_path.open("r", encoding="utf-8-sig", newline="") as handle:
            ledger = list(csv.DictReader(handle))
        if len(candidates) != len(ledger):
            return False, "source-only summary entity candidate/ledger counts differ"
        candidate_count = _checkpoint_int(
            entity_summary.get("candidate_count", entity_summary.get("entity_candidate_count")), -1
        )
        if candidate_count < 0 or len(candidates) != candidate_count:
            return False, "source-only summary entity candidate count does not match the scan summary"
        candidate_ids = [str(row.get("candidate_id") or "").strip() for row in candidates]
        ledger_ids = [str(row.get("candidate_id") or "").strip() for row in ledger]
        if any(not value for value in candidate_ids) or len(set(candidate_ids)) != len(candidate_ids):
            return False, "source-only summary entity candidates are not uniquely identified"
        if candidate_ids != ledger_ids:
            return False, "source-only summary entity ledger order/identity differs"
        allowed_statuses = {"MAPPED", "EXCLUDED", "UNMAPPED"}
        if any(str(row.get("status") or "").strip().upper() not in allowed_statuses for row in ledger):
            return False, "source-only summary entity ledger has an invalid status"
        pool_path = safe_run_path(run_dir, "wechat_stock_pool_raw.csv", must_exist=True, label="source pool")
        with pool_path.open("r", encoding="utf-8-sig", newline="") as handle:
            pool_rows = list(csv.DictReader(handle))
        unique_codes = {
            str(row.get("ts_code") or row.get("code") or "").strip().upper()
            for row in pool_rows
            if str(row.get("ts_code") or row.get("code") or "").strip()
        }
        for row in ledger:
            if str(row.get("status") or "").strip().upper() == "MAPPED":
                code = str(row.get("ts_code") or row.get("code") or "").strip().upper()
                if not code or code not in unique_codes or str(row.get("final_pool_present") or "").strip().lower() != "true":
                    return False, "source-only summary mapped entity is missing from the current pool"
        return True, ""
    except (OSError, UnicodeError, ValueError, TypeError, RuntimeError, csv.Error) as exc:
        return False, f"source-only summary prerequisites invalid: {exc}"


def _full_ocr_provenance_valid(run_dir: Path) -> bool:
    """Re-run the extractor's one-to-one image/OCR provenance gate.

    A summary count is not evidence that the current manifests, files and
    hashes still match.  Resume gates must consult the same loader used by
    extraction so stale or incomplete OCR cannot reach pool stages.
    """

    try:
        sys.path.insert(0, str(SCRIPT_DIR))
        from wechat_extract_stock_pool import load_ocr_image_records

        _records, status = load_ocr_image_records(run_dir)
    except (OSError, ValueError, TypeError, RuntimeError, ImportError):
        return False
    return status == "OK"


def _coverage_ledger_matches_current_sources(
    run_dir: Path,
    *,
    image_count: int,
    ocr_records: list[dict[str, str]],
    coverage: object,
    body_text: str,
    expected_event_count: int | None = None,
    expected_no_event_count: int | None = None,
) -> bool:
    """Require the saved coverage ledger to name the current source universe.

    ``source_coverage_summary.json`` and a CSV row count are insufficient for
    resume: an older BODY-only ledger can still report PASS after a run has
    acquired images.  Match source ids in order and bind each image row to the
    currently verified OCR image hash before allowing the checkpoint to skip.
    """

    from wechat_build_coverage_ledger import expected_review_fields

    expected_ids = ["BODY", *[f"IMAGE{index:03d}" for index in range(1, image_count + 1)]]
    expected_review = {
        "BODY": expected_review_fields(coverage, "BODY"),
        **{
            f"IMAGE{index:03d}": expected_review_fields(coverage, str(index))
            for index in range(1, image_count + 1)
        },
    }
    if any(value is None for value in expected_review.values()):
        return False
    expected_text = {"BODY": body_text}
    expected_text.update(
        {
            f"IMAGE{int(record.get('index') or 0):03d}": str(record.get("text") or "")
            for record in ocr_records
        }
    )
    expected_hashes = {
        f"IMAGE{int(record.get('index') or 0):03d}": str(record.get("image_sha256") or "").strip().lower()
        for record in ocr_records
    }
    for path in sorted(run_dir.glob("source_coverage_ledger_*.csv")):
        try:
            _reject_symlink_components(path, "coverage ledger")
        except (OSError, ValueError):
            continue
        if path.is_symlink() or not path.is_file():
            continue
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)
        except (OSError, UnicodeError, csv.Error):
            continue
        if not reader.fieldnames or "source_index" not in reader.fieldnames:
            continue
        observed_ids = [str(row.get("source_index") or "").strip().upper() for row in rows]
        if observed_ids != expected_ids:
            continue
        required_fields = {
            "source_index", "image_sha256", "ocr_status", "transcription_chars",
            "transcription", "event", "subject", "source_grade",
            "contradiction_or_falsifier",
        }
        if not required_fields.issubset(set(reader.fieldnames)):
            continue
        if any(any(value is None for value in row.values()) for row in rows):
            continue
        body = rows[0]
        if str(body.get("image_sha256") or "").strip():
            continue
        if any(
            str(row.get("image_sha256") or "").strip().lower() != expected_hashes.get(source_id, "")
            for row, source_id in zip(rows[1:], expected_ids[1:])
        ):
            continue
        for row, source_id in zip(rows, expected_ids):
            source_key = "BODY" if source_id == "BODY" else str(int(source_id[-3:]))
            review = expected_review[source_id]
            text = expected_text.get(source_id, "")
            expected_ocr_status = "BODY_CAPTURED" if source_id == "BODY" else "OCR_OK"
            if (
                tuple(str(row.get(field) or "").strip() for field in (
                    "event", "subject", "source_grade", "contradiction_or_falsifier",
                )) != review
                or str(row.get("ocr_status") or "").strip() != expected_ocr_status
                or str(row.get("transcription") or "") != text
                or str(row.get("transcription_chars") or "").strip() != str(len(text))
                or expected_review_fields(coverage, source_key) != review
            ):
                break
        else:
            ledger_event_count = sum(
                str(row.get("event") or "").strip().upper() != "NO_EVENT"
                for row in rows
            )
            ledger_no_event_count = len(rows) - ledger_event_count
            if (
                expected_event_count is not None
                and ledger_event_count != expected_event_count
            ):
                continue
            if (
                expected_no_event_count is not None
                and ledger_no_event_count != expected_no_event_count
            ):
                continue
            return True
    return False


def _coverage_checkpoint_valid(run_dir: Path) -> bool:
    """Validate coverage against current intake, OCR provenance and source ids."""

    summary = _load_json(run_dir / "source_coverage_summary.json")
    if not isinstance(summary, dict):
        return False
    try:
        research = load_article_research(run_dir)
        coverage = research.get("coverage") if isinstance(research, dict) else None
    except (OSError, ValueError, TypeError, RuntimeError):
        return False
    try:
        from wechat_build_coverage_ledger import _declared_image_count

        image_count, declaration_status = _declared_image_count(run_dir)
    except (OSError, UnicodeError, ValueError, TypeError, RuntimeError, ImportError):
        return False
    if declaration_status != "OK" or image_count is None or image_count < 0:
        return False
    try:
        from wechat_extract_stock_pool import load_ocr_image_records

        records, ocr_status = load_ocr_image_records(run_dir)
    except (OSError, UnicodeError, ValueError, TypeError, RuntimeError, ImportError):
        return False
    if ocr_status != "OK" or len(records) != image_count:
        return False

    # Keep both checkpoint summaries bound to the same complete OCR result.
    # ``source_coverage_summary`` uses the historical ``ocr_*`` names while
    # the OCR summary uses ``*_count``.  Older valid body/image fixtures may
    # omit the optional coverage ``ocr_empty`` field, so derive that one from
    # the authoritative OCR summary when present and otherwise retain the
    # existing zero default.
    ocr_summary = _load_json(run_dir / "wechat_article_ocr_summary.json")
    if not isinstance(ocr_summary, dict):
        ocr_summary = {}
    for key in ("timeout_count", "error_count", "empty_count"):
        if key in ocr_summary and _checkpoint_int(ocr_summary.get(key), -1) != 0:
            return False
    for key in ("ocr_timeout", "ocr_error"):
        if key in summary and _checkpoint_int(summary.get(key), -1) != 0:
            return False
    if "ocr_empty" in summary and _checkpoint_int(summary.get("ocr_empty"), -1) != 0:
        return False

    expected_sources = image_count + 1  # BODY is always a captured source.
    expected_status = f"PASS_{expected_sources}_OF_{expected_sources}"
    summary_event_count = _checkpoint_int(summary.get("event_count"), -1)
    summary_no_event_count = _checkpoint_int(summary.get("no_event_count"), -1)
    if (
        summary.get("status") != expected_status
        or _checkpoint_int(summary.get("captured_sources"), -1) != expected_sources
        or _checkpoint_int(summary.get("reviewed_sources"), -1) != expected_sources
        or summary_event_count < 0
        or summary_no_event_count < 0
        or summary_event_count + summary_no_event_count != expected_sources
        or _checkpoint_int(summary.get("image_sources"), -1) != image_count
        or _checkpoint_int(summary.get("body_source_count"), -1) != 1
        or _checkpoint_int(summary.get("ocr_ok"), -1) != image_count
        or summary.get("missing_ids")
        or summary.get("duplicate_ids")
    ):
        return False
    raw_html = safe_run_path(run_dir, "wechat_article_raw.html", must_exist=True, label="article HTML")
    try:
        if raw_html.is_symlink() or raw_html.stat().st_size <= 0:
            return False
        body_text = article_body_text(raw_html.read_text(encoding="utf-8-sig", errors="ignore"))
        if not body_text:
            return False
    except (OSError, UnicodeError, ValueError):
        return False
    return _coverage_ledger_matches_current_sources(
        run_dir,
        image_count=image_count,
        ocr_records=records,
        coverage=coverage,
        body_text=body_text,
        expected_event_count=summary_event_count,
        expected_no_event_count=summary_no_event_count,
    )


def _source_summary_checkpoint_valid(run_dir: Path) -> bool:
    """Validate a successful source-only summary against current inputs."""

    value = _load_json(run_dir / "run_summary.json")
    if not isinstance(value, dict) or value.get("status") != "PASS_RESEARCH_ARCHIVE_SOURCE_ONLY":
        return False
    if value.get("summary_mode") != "SOURCE_ONLY":
        return False
    provenance = value.get("summary_provenance")
    if not isinstance(provenance, dict) or provenance.get("mode") != "SOURCE_ONLY":
        return False
    try:
        from wechat_write_run_summary import source_summary_fingerprint, source_summary_identity

        research = load_article_research(run_dir)
        article = research.get("article", {}) if isinstance(research, dict) else {}
        expected_identity = source_summary_identity(run_dir, article)
        if provenance.get("identity") != expected_identity:
            return False
        if provenance.get("input_hashes") != source_summary_fingerprint(run_dir):
            return False
        output_hashes = provenance.get("output_hashes")
        if not isinstance(output_hashes, dict) or not output_hashes:
            return False
        for raw_path, expected_sha in output_hashes.items():
            path = safe_run_path(run_dir, raw_path, must_exist=True, label="summary provenance output")
            if path.name == "run_summary.json" or hashlib.sha256(path.read_bytes()).hexdigest() != str(expected_sha):
                return False
        selector = value.get("selector")
        v3 = value.get("v3_preselection")
        article_summary = value.get("article")
        if not isinstance(selector, dict) or not isinstance(v3, dict):
            return False
        if (
            not isinstance(article_summary, dict)
            or article_summary.get("selector_score_date") is not None
            or article_summary.get("required_selector_date") != str(
                provenance.get("required_selector_date") or ""
            )
        ):
            return False
        required = str(provenance.get("required_selector_date") or "")
        if (
            selector.get("status") != "CANNOT_CONFIRM"
            or selector.get("selector_score_date") is not None
            or selector.get("score_date") is not None
            or selector.get("date") is not None
            or selector.get("required_selector_date") != required
            or v3.get("status") != "CANNOT_CONFIRM_EXACT_SELECTOR_PANEL"
            or v3.get("selector_score_date") is not None
            or v3.get("score_date") is not None
            or v3.get("date") is not None
            or v3.get("required_selector_date") != required
            or any(v3.get(key) is not None for key in ("matched", "unmatched", "guard_pass", "high_repeat"))
        ):
            return False
        runtime = value.get("runtime_acceptance")
        if not isinstance(runtime, dict):
            return False
        if any(runtime.get(key) is True for key in ("artifact_validated", "latest_pointer_validated", "api_validated")):
            return False
        if runtime.get("ui_verified") == "UI_VERIFIED":
            return False
        return source_summary_prerequisites(run_dir)[0]
    except (OSError, UnicodeError, ValueError, TypeError, RuntimeError, ImportError):
        return False


def _publish_v35_preselection_input(run_dir: Path, effective_trade_date: str) -> dict[str, object]:
    """Publish only the verified WeChat input pair consumed by V3.5.

    The runner owns the source run and archive sync, while the dedicated
    publisher owns atomic/idempotent destination writes.  Keep this bridge
    fail-closed: a successful sync is not reported unless the exact-date pair
    exists and has the manifest-declared matched-row count.
    """
    run_dir = validate_run_dir(run_dir)
    if not effective_trade_date:
        raise RuntimeError("effective_trade_date required for V3.5 WeChat input publish")
    effective_trade_date = normalize_date(effective_trade_date, label="effective_trade_date")
    source_manifest = safe_run_path(run_dir, "wechat_v3_preselect_manifest.json", must_exist=True, label="V3 manifest")
    manifest = _load_json(source_manifest)
    if not isinstance(manifest, dict):
        raise RuntimeError("WeChat V3 manifest missing before V3.5 input publish")
    outputs = manifest.get("outputs")
    rows_value = outputs.get("all") if isinstance(outputs, dict) else None
    try:
        source_rows = _run_local_artifact(run_dir, rows_value, label="V3 rows")
    except (OSError, ValueError, FileNotFoundError) as exc:
        raise RuntimeError("WeChat V3 manifest outputs.all is missing before V3.5 input publish") from exc
    counts = manifest.get("counts") if isinstance(manifest.get("counts"), dict) else {}
    try:
        expected_rows = int(counts.get("v3_matched_codes") or 0)
    except (TypeError, ValueError):
        expected_rows = 0
    if expected_rows <= 0:
        raise RuntimeError("WeChat V3 manifest has no positive matched-row count")

    destination_root = WORK_ROOT.parents[2] / "v3.5" / ".runtime" / "preselection_inputs"
    _reject_symlink_components(destination_root, "V3.5 destination root")
    if destination_root.exists() and not destination_root.is_dir():
        raise RuntimeError("V3.5 destination root is not a directory")
    destination_day = destination_root / effective_trade_date
    _reject_symlink_components(destination_day, "V3.5 destination day")
    if destination_day.exists() and not destination_day.is_dir():
        raise RuntimeError("V3.5 destination day is not a directory")
    _sub(
        PY,
        "-X",
        "utf8",
        str(SCRIPT_DIR / "wechat_publish_v35_preselection.py"),
        "--source-manifest",
        str(source_manifest),
        "--source-rows",
        str(source_rows),
        "--destination-root",
        str(destination_root),
        "--effective-trade-date",
        effective_trade_date,
    )

    destination = destination_day
    destination_manifest = destination / "wechat_manifest.json"
    destination_rows = destination / "wechat_rows.csv"
    if not destination_manifest.is_file() or not destination_rows.is_file():
        raise RuntimeError("V3.5 WeChat input pair missing after publisher")
    actual_rows = _csv_row_count(destination_rows)
    if actual_rows != expected_rows:
        raise RuntimeError(
            f"V3.5 WeChat input row-count mismatch: expected {expected_rows}, got {actual_rows}"
        )
    published = _load_json(destination_manifest)
    if not isinstance(published, dict) or published.get("effective_trade_date") != effective_trade_date:
        raise RuntimeError("V3.5 WeChat input manifest effective date mismatch")
    receipt_path = safe_run_path(run_dir, "v35_publish_receipt.json", label="V3.5 publish receipt")
    write_json(receipt_path, {
        "status": "V35_PUBLISH_PASS",
        "effective_trade_date": effective_trade_date,
        "source_manifest_sha256": hashlib.sha256(source_manifest.read_bytes()).hexdigest(),
        "source_rows_sha256": hashlib.sha256(source_rows.read_bytes()).hexdigest(),
        "row_count": actual_rows,
        "destination_manifest": str(destination_manifest),
        "destination_rows": str(destination_rows),
        "destination_manifest_sha256": hashlib.sha256(destination_manifest.read_bytes()).hexdigest(),
        "destination_rows_sha256": hashlib.sha256(destination_rows.read_bytes()).hexdigest(),
    })
    return {
        "destination": str(destination),
        "manifest": str(destination_manifest),
        "rows": str(destination_rows),
        "row_count": actual_rows,
        "effective_trade_date": effective_trade_date,
    }


def checkpoint_is_valid(
    stage: str,
    run_dir: Path,
    *,
    panel: str = "",
    source_only: bool = False,
) -> bool:
    """Check semantic readiness before ``--resume`` skips a stage."""
    try:
        run_dir = validate_run_dir(run_dir)
    except (OSError, ValueError):
        return False
    checkpoint = CHECKPOINT_FILES.get(stage)
    if not checkpoint:
        return False
    try:
        path = safe_run_path(run_dir, checkpoint, must_exist=True, label=f"{stage} checkpoint")
    except (OSError, ValueError):
        return False

    if stage == "fetch":
        return _fetch_identity_ready(run_dir)
    if stage == "prepare_ocr":
        value = _load_json(path)
        count = _checkpoint_int(value.get("image_count"), -1) if isinstance(value, dict) else -1
        images = value.get("images") if isinstance(value, dict) else None
        return (
            isinstance(value, dict)
            and value.get("status") == "PREPARED"
            and count >= 0
            and isinstance(images, list)
            and len(images) == count
        )
    if stage == "ocr_canary":
        value = _load_json(path)
        summary = _load_json(run_dir / "windows_ocr_canary_summary.json")
        rows = value if isinstance(value, list) else (value.get("records", []) if isinstance(value, dict) else [])
        if not isinstance(summary, dict) or not isinstance(rows, list):
            return False
        planned_raw = summary.get("planned_indices")
        try:
            planned = [int(item) for item in planned_raw]
            actual = [int(row.get("index")) for row in rows if isinstance(row, dict)]
        except (TypeError, ValueError):
            return False
        slice_manifest = _load_json(run_dir / "ocr_slice_manifest.json")
        image_count = _checkpoint_int(slice_manifest.get("image_count"), 0) if isinstance(slice_manifest, dict) else 0
        expected = canary_indices(image_count)
        if (
            (image_count > 0 and not expected)
            or len(planned) != len(expected)
            or len(set(planned)) != len(planned)
            or sorted(planned) != expected
            or len(rows) != len(expected)
            or not all(isinstance(row, dict) for row in rows)
            or len(actual) != len(expected)
            or len(set(actual)) != len(actual)
            or sorted(actual) != expected
        ):
            return False
        return (
            summary.get("status") == ("OCR_OK" if image_count > 0 else "OCR_NOT_APPLICABLE")
            and summary.get("processed_count") == len(expected)
            and summary.get("ok_count") == len(expected)
            and summary.get("error_count") == 0
            and summary.get("empty_count") == 0
            and all(
                isinstance(row, dict)
                and str(row.get("status", "")).startswith("OCR_OK")
                and bool(str(row.get("text") or "").strip())
                for row in rows
            )
        )
    if stage == "ocr_full":
        if not _full_ocr_provenance_valid(run_dir):
            return False
        value = _load_json(path)
        summary = _load_json(run_dir / "wechat_article_ocr_summary.json")
        if not isinstance(value, list) or not isinstance(summary, dict):
            return False
        count = _checkpoint_int(summary.get("image_count"), 0)
        return (
            summary.get("status") == ("OCR_OK" if count > 0 else "OCR_NOT_APPLICABLE")
            and count >= 0
            and len(value) == count
            and _checkpoint_int(summary.get("processed_count"), -1) == count
            and _checkpoint_int(summary.get("ok_count"), -1) == count
            and _checkpoint_int(summary.get("timeout_count"), -1) == 0
            and _checkpoint_int(summary.get("error_count"), -1) == 0
            and _checkpoint_int(summary.get("empty_count"), -1) == 0
            and all(
                isinstance(row, dict)
                and str(row.get("status", "")).startswith("OCR_OK")
                and bool(str(row.get("text") or "").strip())
                for row in value
            )
        )
    if stage == "coverage":
        return _coverage_checkpoint_valid(run_dir)
    if stage in {"extract", "resolve"}:
        try:
            if not _coverage_checkpoint_valid(run_dir):
                return False
            if not _resume_identity_ready(
                run_dir,
                require_selector=bool(str(panel or "").strip()),
                panel=panel,
            ):
                return False
            if not _full_ocr_provenance_valid(run_dir):
                return False
            if not _entity_scan_checkpoint_valid(
                run_dir,
                source_only_allowed=not bool(str(panel or "").strip()),
            ):
                return False
        except (OSError, ValueError, TypeError, RuntimeError):
            return False
        rows = _csv_row_count(path)
        if rows < 0:
            return False
        if rows == 0:
            summary = _load_json(run_dir / "security_entity_candidates_summary.json")
            source_only = (
                isinstance(summary, dict)
                and str(summary.get("scan_status") or "").upper() == "PASS_SOURCE_ONLY"
            )
            if not source_only:
                return False
        if stage == "resolve":
            mapping = _load_json(run_dir / "pool_mapping_summary.json")
            return isinstance(mapping, dict) and mapping.get("status") == "PASS" and _checkpoint_int(mapping.get("final_rows"), -1) == rows
        return True
    if stage == "build_v3":
        try:
            research = load_article_research(run_dir)
            article = research.get("article", {}) if isinstance(research, dict) else {}
            identity = resolve_stage_identity(article)
            if not identity["effective_trade_date"] or not _resume_identity_ready(
                run_dir, require_selector=True, panel=panel
            ):
                return False
            intake_identity = _require_exact_intake(run_dir, article)["identity"]
        except (OSError, ValueError, TypeError, RuntimeError):
            return False
        value = _load_json(path)
        if not isinstance(value, dict):
            return False
        if not _build_manifest_identity_matches(value, intake_identity):
            return False
        counts = value.get("counts") if isinstance(value.get("counts"), dict) else {}
        target_validation = value.get("target_validation") if isinstance(value.get("target_validation"), dict) else {}
        unique = _checkpoint_int(counts.get("wechat_unique_codes"), 0)
        matched = _checkpoint_int(counts.get("v3_matched_codes"), 0)
        unmatched = _checkpoint_int(counts.get("v3_unmatched_codes"), 0)
        resolved_panel = str(panel or value.get("selector_ready_panel") or "").strip()
        return (
            value.get("status") == "WECHAT_V3_PRESELECT_READY"
            and unique > 0
            and matched + unmatched == unique
            and target_validation.get("status") == "TARGET_DATE_CHECK_PASS"
            and checkpoint_is_valid("resolve", run_dir, panel=resolved_panel)
        )
    if stage == "summary":
        if source_only:
            return _source_summary_checkpoint_valid(run_dir)
        value = _load_json(path)
        runtime = value.get("runtime_acceptance") if isinstance(value, dict) and isinstance(value.get("runtime_acceptance"), dict) else {}
        return (
            isinstance(value, dict)
            and value.get("status") == "PASS_RESEARCH_ARCHIVE_AND_V3_PRESELECT_PUBLISHED"
            and runtime.get("artifact_validated") is True
            and runtime.get("latest_pointer_validated") is True
            and runtime.get("api_validated") is True
            and runtime.get("ui_verified") == "UI_VERIFIED"
        )
    if stage == "baimao_observations":
        value = _load_json(path)
        counts = value.get("counts") if isinstance(value, dict) and isinstance(value.get("counts"), dict) else {}
        return isinstance(value, dict) and value.get("schema_version") and _checkpoint_int(counts.get("total"), 0) > 0
    return False


def run_stage(stage: str, args) -> None:
    run_dir = validate_run_dir(args.run_dir)
    research = load_article_research(run_dir)
    article = research.get("article", {})
    identity = resolve_stage_identity(
        article,
        cli_url=args.url,
        cli_title=args.title,
        cli_target_date=args.target_date,
        cli_effective_trade_date=args.effective_trade_date,
    )
    url = identity["url"]
    title = identity["title"]
    target = identity["target_date"]
    effective = identity["effective_trade_date"]
    if not (run_dir / "wechat_article_intake_summary.json").exists() and not url:
        raise RuntimeError("url required (missing intake); pass --url")

    if stage == "fetch":
        _run_fetch(
            run_dir,
            target,
            url,
            article=article,
            title=title,
            image_workers=getattr(args, "image_workers", None),
            image_retries=getattr(args, "image_retries", None),
            fetch_mode=getattr(args, "fetch_mode", None),
        )
    elif stage == "prepare_ocr":
        _sub(PY, "-X", "utf8", str(SCRIPT_DIR / "wechat_prepare_ocr.py"), "--run-dir", str(run_dir))
    elif stage == "ocr_canary":
        _ps1(run_dir, "Canary")
    elif stage == "ocr_full":
        _ps1(run_dir, "Full")
    elif stage == "coverage":
        _sub(PY, "-X", "utf8", str(SCRIPT_DIR / "wechat_build_coverage_ledger.py"), "--run-dir", str(run_dir))
    elif stage == "extract":
        _require_exact_intake(run_dir, article, expected_url=url, expected_title=title, expected_date=target)
        if not _coverage_checkpoint_valid(run_dir):
            raise RuntimeError("extract requires a valid current coverage checkpoint")
        selector_path = _optional_selector_snapshot(run_dir, target, args.panel)
        extract_command = [
            PY, "-X", "utf8", str(SCRIPT_DIR / "wechat_extract_stock_pool.py"),
            "--run-dir", str(run_dir), "--target-date", target,
            "--article-title", title, "--article-url", url,
        ]
        if selector_path is not None:
            extract_command.extend(["--selector-panel", str(selector_path)])
        _sub(*extract_command)
    elif stage == "resolve":
        _require_exact_intake(run_dir, article, expected_url=url, expected_title=title, expected_date=target)
        if not checkpoint_is_valid("extract", run_dir, panel=args.panel):
            raise RuntimeError("resolve requires a valid extract checkpoint")
        _sub(PY, "-X", "utf8", str(SCRIPT_DIR / "wechat_resolve_stock_pool.py"), "--run-dir", str(run_dir))
    elif stage == "build_v3":
        if not effective:
            raise RuntimeError("effective_trade_date required for build_v3; fill article_research.json")
        _require_exact_intake(run_dir, article, expected_url=url, expected_title=title, expected_date=target)
        selector_path = _require_selector_snapshot(run_dir, target, args.panel)
        if not checkpoint_is_valid("resolve", run_dir, panel=args.panel):
            raise RuntimeError("build_v3 requires a valid resolved pool checkpoint")
        _sub(*build_v3_command(run_dir, target, effective, title, str(selector_path)))
    elif stage == "sync":
        _require_exact_intake(run_dir, article, expected_url=url, expected_title=title, expected_date=target)
        if not checkpoint_is_valid("build_v3", run_dir, panel=args.panel):
            raise RuntimeError("sync requires a valid V3 preselection checkpoint")
        # A V3.5 publisher failure must leave both latest pointers untouched;
        # publish the external input pair before entering the archive writer.
        _publish_v35_preselection_input(run_dir, effective)
        _sub(PY, "-X", "utf8", str(SCRIPT_DIR / "wechat_sync_archive.py"),
             "--run-dir", str(run_dir), "--v3-system-root", str(WORK_ROOT))
    elif stage == "summary":
        command = [
            PY,
            "-X",
            "utf8",
            str(SCRIPT_DIR / "wechat_write_run_summary.py"),
            "--run-dir",
            str(run_dir),
        ]
        if getattr(args, "source_only", False):
            command.append("--source-only")
        _sub(*command)
    elif stage == "yesterday":
        yesterday_dir = args.yesterday_run_dir
        if not yesterday_dir:
            # 自动找最近一个含 manifest 的 run
            from wechat_yesterday_performance import find_previous_run_dir
            prev = find_previous_run_dir(run_dir)
            if prev is None:
                raise RuntimeError("--yesterday-run-dir not provided and no previous run found")
            yesterday_dir = str(prev)
        cmd = [PY, "-X", "utf8", str(SCRIPT_DIR / "wechat_yesterday_performance.py"),
               "--yesterday-run-dir", yesterday_dir, "--out-dir", str(run_dir / "baimao_reader_out")]
        if args.panel:
            cmd += ["--panel", args.panel]
        _sub(*cmd)
    elif stage == "baimao_observations":
        _sub(PY, "-X", "utf8", str(SCRIPT_DIR / "wechat_export_baimao_observations.py"),
             "--run-dir", str(run_dir))
    elif stage == "validate":
        _run_validator_with_receipt(run_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="公众号管线编排器")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--url", default="")
    parser.add_argument("--title", default="")
    parser.add_argument("--target-date", default="")
    parser.add_argument("--effective-trade-date", default="")
    parser.add_argument("--yesterday-run-dir", default="")
    parser.add_argument("--panel", default="")
    parser.add_argument("--image-workers", type=int, default=None, help="Fetch image concurrency (1-3 on the Mac intake).")
    parser.add_argument("--image-retries", type=int, default=None, help="Fetch image retries after the first attempt (0-3).")
    parser.add_argument("--fetch-mode", choices=("http", "auto", "crawl4ai"), default=None, help="Article HTML transport for the Mac intake.")
    parser.add_argument("--stage", required=True, help=", 分隔的 stage 或 all")
    parser.add_argument("--resume", action="store_true", help="按工件存在跳过已完成 stage")
    parser.add_argument(
        "--source-only",
        action="store_true",
        help="仅 summary 阶段生成 source-only 归档；不允许与 build_v3/sync/validate 等阶段混用",
    )
    args = parser.parse_args(argv)

    stages = STAGES if args.stage == "all" else [s.strip() for s in args.stage.split(",") if s.strip()]
    for s in stages:
        if s not in STAGES:
            print(json.dumps({"status": "ERROR", "error": f"unknown stage {s}"}, ensure_ascii=False))
            return 2
    if args.source_only and stages != ["summary"]:
        print(json.dumps({
            "status": "ERROR",
            "error": "--source-only is restricted to --stage summary",
        }, ensure_ascii=False))
        return 2

    run_dir = validate_run_dir(args.run_dir)
    try:
        research = load_article_research(run_dir)
        article = research.get("article", {}) if isinstance(research, dict) else {}
        resolve_stage_identity(
            article,
            cli_url=args.url,
            cli_title=args.title,
            cli_target_date=args.target_date,
            cli_effective_trade_date=args.effective_trade_date,
        )
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=False))
        return 2
    done: list[str] = []
    for s in stages:
        if args.resume and checkpoint_is_valid(
            s, run_dir, panel=args.panel, source_only=args.source_only
        ):
            print(json.dumps({"stage": s, "action": "SKIP_RESUME"}, ensure_ascii=False))
            continue
        print(json.dumps({"stage": s, "action": "RUN"}, ensure_ascii=False))
        run_stage(s, args)
        done.append(s)
    print(json.dumps({"status": "STAGES_DONE", "run_dir": str(run_dir), "stages": done}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
