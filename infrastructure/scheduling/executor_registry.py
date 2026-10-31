"""Fixed Python executor registry for the V4 runtime dispatcher.

The registry selects a whitelisted Python module and a fixed argument list per
``workload_id``.  It never reads ``WorkloadDefinition.command``: the catalog
command remains an audit/oracle field only.  Business inputs come exclusively
from the V4/shared-owned roots passed at construction; when an input is
absent the module fails closed and the registry raises a structured failure.
"""
from __future__ import annotations
from infrastructure.runtime_graph.notifications import notify as _graph_notify
from infrastructure.market_time import shanghai_now

import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from contracts.runtime_tasks import DispatchRequest, WorkloadDefinition
from ops.daily_materialize import resolve_selector_panel
from infrastructure.research_peripheral_store import ResearchPeripheralStore
from infrastructure.owned_path import resolve_owned_path
from infrastructure.preselection_pool_store import PreselectionPoolStore
from ops.us_market_digest import (
    resolve_capture_for_shanghai_slot,
    us_market_day_certification,
)

ALLOWED_WORKLOAD_IDS = frozenset(
    {
        "hourly_research",
        "us_market_digest",
        "research_preselection_refresh",
        "zsxq_0830",
        "morning_news_0830",
        "baimao_x_refresh",
        "hk_auction_0920",
        "stage_workbench",
        "preselection_pools",
        "daily_materialize",
        "a_share_close_review",
        "hk_connect_close_review",
        "fupan_close_materials",
        "fupan_review_start",
        "fupan_video_check",
        "fupan_video_download_asr",
        "fupan_stockdict",
        "fupan_video_table_ocr_align",
        "fupan_video_gap",
        "fupan_v3_publish",
        "fupan_8771_verify",
        "research_panel_daily_a",
        "research_panel_daily_hk",
        "research_panel_runtime_evidence",
        "wechat_preselection_sync",
        "review_core_pool_pipeline",
    }
)

STAGE_BY_SLOT = {
    "0925": "STAGE_0925",
    "0935": "STAGE_0930_0935",
    "0940": "STAGE_0935_0940",
    "0945": "STAGE_0940_0945",
    "1030": "STAGE_0945_1030",
    "1315": "STAGE_1300_1315",
    "1500": "STAGE_1445_1500",
    "1555": "STAGE_1545_1555",
}

MILESTONE_BY_WORKLOAD = {
    "fupan_close_materials": ("FUPAN_CLOSE_MATERIALS", "STAGE_1445_1500", "A_SHARE"),
    "fupan_review_start": ("FUPAN_REVIEW_START", "STAGE_1545_1555", "HK_CONNECT"),
}
CLOSE_NODE_BY_WORKLOAD = {
    "fupan_video_check": "FUPAN_VIDEO_CHECK",
    "fupan_video_download_asr": "FUPAN_VIDEO_DOWNLOAD_ASR",
    "fupan_stockdict": "FUPAN_STOCKDICT",
    "fupan_video_table_ocr_align": "FUPAN_VIDEO_TABLE_OCR_ALIGN",
    "fupan_video_gap": "FUPAN_VIDEO_GAP",
    "fupan_v3_publish": "FUPAN_V3_PUBLISH",
    "fupan_8771_verify": "FUPAN_8771_VERIFY",
}

_STDOUT_LIMIT = 2048
_STDERR_LIMIT = 2048
_DEFAULT_TIMEOUT_SECONDS = 300
_V192_PRESELECTION_TIMEOUT_SECONDS = 1800
_HK_AUCTION_0920_TIMEOUT_SECONDS = 420
_TIMEOUT_EXIT_CODE = 124
_PERIPHERAL_FETCH_TIMEOUT_SECONDS = 10
_HK_CLOSE_RETRY_INTERVAL_SECONDS = 120
_HK_CLOSE_MAX_WAIT_SECONDS = 1200
_HK_CLOSE_CUTOFF_ERROR_PREFIX = "final close cutoff not reached:"
_HK_0_2_REQUIRED_PYTHON_VERSION = "3.13.12"
_PERIPHERAL_SOURCES = frozenset({"external_finance", "ai_news"})
_PERIPHERAL_STATUSES = frozenset({"READY", "READY_EMPTY", "CANNOT_CONFIRM"})


def _validate_optional_timeout(value: float | None) -> float | None:
    """Validate an optional lane-specific outer timeout without changing global defaults."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("A_DAILY_TIMEOUT_SECONDS_INVALID")
    try:
        timeout = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError("A_DAILY_TIMEOUT_SECONDS_INVALID") from error
    if not math.isfinite(timeout) or timeout <= 0.0:
        raise ValueError("A_DAILY_TIMEOUT_SECONDS_INVALID")
    return timeout

_PAYLOAD_BEGIN = "@@V4_AUTHORITY_PAYLOAD_BEGIN@@"
_PAYLOAD_END = "@@V4_AUTHORITY_PAYLOAD_END@@"
_PAYLOAD_KEYS = frozenset(
    {
        "status",
        "overall_status",
        "lanes",
        "lane",
        "payload_path",
        "payload_sha256",
        "through_date",
        "target_date",
        "trade_date",
        "row_count",
        "coverage_rate",
        "sha256",
        "source_sha256",
        "panel_sha256",
        "capture_status",
    }
)


def _strict_json_object(text: str) -> dict[str, Any]:
    """Decode exactly one JSON object and reject duplicate/non-standard values."""

    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-standard JSON constant: {value}")

    value = json.loads(
        text,
        object_pairs_hook=object_pairs,
        parse_constant=reject_constant,
    )
    if not isinstance(value, dict):
        raise ValueError("authoritative payload must be a JSON object")
    return value


def _decode_authoritative_payload(source: Any) -> tuple[dict[str, Any] | None, str | None]:
    """Decode a complete child payload without slicing arbitrary log text.

    A runner may provide an explicit ``authoritative_payload`` side channel.
    Otherwise the complete stdout is accepted only when it is one JSON object,
    one explicitly framed JSON object, or exactly one complete JSON payload line
    surrounded by ordinary producer logs.  A bounded log field is never used
    for acceptance.
    """

    side_channel: Any = None
    payload_path: Any = None
    raw_stdout: Any = None
    if isinstance(source, Mapping):
        side_channel = source.get("authoritative_payload")
        if side_channel is None:
            side_channel = source.get("_authoritative_payload")
        payload_path = source.get("authoritative_payload_path")
        if payload_path is None:
            payload_path = source.get("_authoritative_payload_path")
        raw_stdout = source.get("stdout_full", source.get("_stdout_full", source.get("stdout")))
    else:
        side_channel = getattr(source, "authoritative_payload", None)
        if side_channel is None:
            side_channel = getattr(source, "_authoritative_payload", None)
        payload_path = getattr(source, "authoritative_payload_path", None)
        if payload_path is None:
            payload_path = getattr(source, "_authoritative_payload_path", None)
        raw_stdout = getattr(source, "stdout", None)

    if side_channel is not None:
        if isinstance(side_channel, Mapping):
            return dict(side_channel), None
        return None, "AUTHORITATIVE_PAYLOAD_INVALID_SIDE_CHANNEL"

    if payload_path not in (None, ""):
        try:
            path = Path(os.fspath(payload_path))
            if path.is_symlink() or not path.is_file():
                return None, "AUTHORITATIVE_PAYLOAD_PATH_UNAVAILABLE"
            return _strict_json_object(path.read_text(encoding="utf-8-sig")), None
        except (OSError, UnicodeError, TypeError, ValueError, json.JSONDecodeError):
            return None, "AUTHORITATIVE_PAYLOAD_PATH_INVALID"

    if isinstance(raw_stdout, bytes):
        try:
            text = raw_stdout.decode("utf-8")
        except UnicodeDecodeError:
            return None, "AUTHORITATIVE_PAYLOAD_NOT_UTF8"
    else:
        text = str(raw_stdout or "")
    stripped = text.strip()
    if not stripped:
        return None, "AUTHORITATIVE_PAYLOAD_MISSING"

    try:
        return _strict_json_object(stripped), None
    except (TypeError, ValueError, json.JSONDecodeError):
        pass

    lines = text.splitlines()
    begin_positions = [index for index, line in enumerate(lines) if line.strip() == _PAYLOAD_BEGIN]
    end_positions = [index for index, line in enumerate(lines) if line.strip() == _PAYLOAD_END]
    if begin_positions or end_positions:
        if len(begin_positions) != 1 or len(end_positions) != 1 or end_positions[0] <= begin_positions[0]:
            return None, "AUTHORITATIVE_PAYLOAD_AMBIGUOUS"
        for index, line in enumerate(lines):
            if begin_positions[0] <= index <= end_positions[0] or not line.strip():
                continue
            try:
                _strict_json_object(line.strip())
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            return None, "AUTHORITATIVE_PAYLOAD_AMBIGUOUS"
        body = "\n".join(lines[begin_positions[0] + 1 : end_positions[0]]).strip()
        try:
            framed = _strict_json_object(body)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None, "AUTHORITATIVE_PAYLOAD_MALFORMED"
        if not set(framed).intersection(_PAYLOAD_KEYS - {"status"}):
            return None, "AUTHORITATIVE_PAYLOAD_CONTRACT_INVALID"
        return framed, None

    candidates: list[dict[str, Any]] = []
    for line in lines:
        candidate_text = line.strip()
        if not candidate_text:
            continue
        try:
            candidate = _strict_json_object(candidate_text)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        candidates.append(candidate)
    if len(candidates) == 1:
        if not set(candidates[0]).intersection(_PAYLOAD_KEYS - {"status"}):
            return None, "AUTHORITATIVE_PAYLOAD_CONTRACT_INVALID"
        return candidates[0], None
    if len(candidates) > 1:
        return None, "AUTHORITATIVE_PAYLOAD_AMBIGUOUS"
    return None, "AUTHORITATIVE_PAYLOAD_MALFORMED"


def _read_exact_dated_receipt(
    module: str, arguments: list[str], *, allow_a_failure: bool = False
) -> tuple[dict[str, Any] | None, str | None]:
    """Read the fixed daily-panel receipt only as a bounded fallback seam."""

    if module != "ops.macos_research_panel_daily":
        return None, None

    def one_argument(flag: str) -> str | None:
        values = [arguments[index + 1] for index, value in enumerate(arguments[:-1]) if value == flag]
        return values[0] if len(values) == 1 else None

    date = one_argument("--date")
    lane = one_argument("--lane")
    root = one_argument("--receipt-root")
    if date is None or lane not in {"A", "HK"} or root is None or len(date) != 8 or not date.isdigit():
        return None, None
    path = Path(root).expanduser() / f"{lane.lower()}-{date}.json"
    try:
        if path.is_symlink() or not path.is_file():
            return None, "EXACT_DATED_RECEIPT_UNAVAILABLE"
        payload = _strict_json_object(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, TypeError, ValueError, json.JSONDecodeError):
        return None, "EXACT_DATED_RECEIPT_INVALID"
    if payload.get("schema_version") != "v3.macos.research_panel_receipt.v1":
        return None, "EXACT_DATED_RECEIPT_SCHEMA_MISMATCH"
    if payload.get("target_date") != date or payload.get("lane") != lane:
        return None, "EXACT_DATED_RECEIPT_IDENTITY_MISMATCH"
    if any(
        payload.get(field) is not False
        for field in ("production_allowed", "buy_gate_updated", "orders_sent")
    ):
        return None, "EXACT_DATED_RECEIPT_SAFETY_MISMATCH"
    status = payload.get("status")
    if not isinstance(status, str) or status not in {
        "READY",
        "PARTIAL",
        "REBUILD_REQUIRED",
        "FAILED",
        "CANNOT_CONFIRM",
        "NON_TRADING_DAY",
    }:
        return None, "EXACT_DATED_RECEIPT_STATUS_INVALID"
    if allow_a_failure and lane == "A" and status in {"FAILED", "CANNOT_CONFIRM"}:
        return payload, None  # failure observation only; successful evidence stays strict
    digest = payload.get("sha256")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in digest)
    ):
        return None, "EXACT_DATED_RECEIPT_PROVENANCE_INVALID"
    row_count = payload.get("row_count")
    if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count < 0:
        return None, "EXACT_DATED_RECEIPT_ROW_COUNT_INVALID"
    coverage_rate = payload.get("coverage_rate")
    if (
        isinstance(coverage_rate, bool)
        or not isinstance(coverage_rate, int | float)
        or not math.isfinite(float(coverage_rate))
        or not 0.0 <= float(coverage_rate) <= 1.0
    ):
        return None, "EXACT_DATED_RECEIPT_COVERAGE_INVALID"
    if lane == "HK":
        if row_count <= 0 or float(coverage_rate) <= 0.0:
            return None, "EXACT_HK_RECEIPT_METRICS_INVALID"
        try:
            binding_error = _validate_hk_receipt_artifact_binding(payload, arguments, date)
        except (OSError, OverflowError, RuntimeError, TypeError, UnicodeError, ValueError):
            binding_error = "EXACT_HK_RECEIPT_ARTIFACT_BINDING_INVALID"
        if binding_error is not None:
            return None, binding_error
    return payload, None


def _validate_hk_receipt_artifact_binding(
    payload: Mapping[str, Any], arguments: list[str], date: str
) -> str | None:
    """Bind a READY HK receipt digest to its exact packed day-file bytes."""

    def one_argument(flag: str) -> str | None:
        values = [arguments[index + 1] for index, value in enumerate(arguments[:-1]) if value == flag]
        return values[0] if len(values) == 1 else None

    def valid_digest(value: Any) -> bool:
        return isinstance(value, str) and len(value) == 64 and all(
            character in "0123456789abcdefABCDEF" for character in value
        )

    hk_root = one_argument("--hk-tdx-root")
    files = payload.get("files")
    if not hk_root or not isinstance(files, list) or not files:
        return "EXACT_HK_RECEIPT_ARTIFACT_LEDGER_INVALID"
    file_count = payload.get("file_count")
    if isinstance(file_count, bool) or not isinstance(file_count, int) or file_count != len(files):
        return "EXACT_HK_RECEIPT_ARTIFACT_LEDGER_INVALID"
    day_root = Path(hk_root).expanduser().resolve() / "vipdoc" / "ds" / "lday"
    total_rows = 0
    file_digests: list[str] = []
    seen_paths: set[Path] = set()
    for item in files:
        if not isinstance(item, Mapping) or item.get("status") != "READY" or item.get("target_date") != date:
            return "EXACT_HK_RECEIPT_ARTIFACT_LEDGER_INVALID"
        if any(item.get(field) is not False for field in ("production_allowed", "buy_gate_updated", "orders_sent")):
            return "EXACT_HK_RECEIPT_ARTIFACT_LEDGER_INVALID"
        raw_path = Path(str(item.get("path") or "")).expanduser()
        if not raw_path.is_absolute() or raw_path.is_symlink():
            return "EXACT_HK_RECEIPT_ARTIFACT_LEDGER_INVALID"
        path = raw_path.resolve()
        if path in seen_paths:
            return "EXACT_HK_RECEIPT_ARTIFACT_LEDGER_INVALID"
        seen_paths.add(path)
        try:
            path.relative_to(day_root)
        except ValueError:
            return "EXACT_HK_RECEIPT_ARTIFACT_LEDGER_INVALID"
        if path.suffix != ".day" or not path.name.startswith("71#") or not path.is_file():
            return "EXACT_HK_RECEIPT_ARTIFACT_LEDGER_INVALID"
        digest = item.get("sha256")
        if not valid_digest(digest):
            return "EXACT_HK_RECEIPT_ARTIFACT_DIGEST_INVALID"
        actual_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_digest != digest.lower():
            return "EXACT_HK_RECEIPT_ARTIFACT_DIGEST_INVALID"
        item_rows = item.get("row_count")
        item_coverage = item.get("coverage_rate")
        if isinstance(item_rows, bool) or not isinstance(item_rows, int) or item_rows <= 0:
            return "EXACT_HK_RECEIPT_ARTIFACT_METRICS_INVALID"
        if (
            isinstance(item_coverage, bool)
            or not isinstance(item_coverage, int | float)
            or not math.isfinite(float(item_coverage))
            or float(item_coverage) <= 0.0
        ):
            return "EXACT_HK_RECEIPT_ARTIFACT_METRICS_INVALID"
        total_rows += item_rows
        file_digests.append(actual_digest)
    if payload.get("row_count") != total_rows or payload.get("row_count", 0) <= 0:
        return "EXACT_HK_RECEIPT_METRICS_INVALID"
    if float(payload.get("coverage_rate", 0.0)) <= 0.0:
        return "EXACT_HK_RECEIPT_METRICS_INVALID"
    expected_digest = hashlib.sha256("".join(sorted(file_digests)).encode()).hexdigest()
    if payload.get("sha256", "").lower() != expected_digest:
        return "EXACT_HK_RECEIPT_DIGEST_INVALID"
    return None


@dataclass
class WorkloadExecutionError(RuntimeError):
    result: dict[str, Any]

    def __str__(self) -> str:
        return (
            f"workload execution failed: "
            f"workload_id={self.result.get('workload_id')} "
            f"status={self.result.get('status')} "
            f"exit_code={self.result.get('exit_code')}"
        )

from types import FunctionType

from . import executor_registry_common as _common
from . import executor_registry_research as _research
from . import executor_registry_preselection as _preselection
from . import executor_registry_review as _review

class FixedExecutorRegistry:
    """Executes only fixed whitelisted Python modules with fixed arguments."""

    def __init__(
        self,
        data_root: Path | str,
        shared_data_root: Path | str | None = None,
        hk_universe_root: Path | str | None = None,
        shared_package_root: Path | str | None = None,
        shared_futu_python_executable: Path | str | None = None,
        selector_data_root: Path | str | None = None,
        preselection_input_root: Path | str | None = None,
        stage_selection_root: Path | str | None = None,
        timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
        repo_root: Path | str | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        hk_0_2_python_executable: Path | str | None = None,
        hk_0_2_tdx_root: Path | str | None = None,
        sleeper: Callable[[float], None] | None = None,
        a_daily_timeout_seconds: float | None = None,
        repair_date: str | None = None,
        repair_slot: str | None = None,
        repair_expected_old_input_sha256: str | None = None,
    ) -> None:
        self.data_root = Path(data_root)
        self.shared_data_root = (
            Path(shared_data_root) if shared_data_root is not None else None
        )
        self.hk_universe_root = (
            Path(hk_universe_root) if hk_universe_root is not None else None
        )
        self.shared_package_root = (
            Path(shared_package_root) if shared_package_root is not None else None
        )
        self.selector_data_root = (
            Path(selector_data_root) if selector_data_root is not None else None
        )
        self.preselection_input_root = (
            Path(preselection_input_root)
            if preselection_input_root is not None
            else None
        )
        self.stage_selection_root = (
            Path(stage_selection_root) if stage_selection_root is not None else None
        )
        self.timeout_seconds = int(timeout_seconds)
        self.a_daily_timeout_seconds = _validate_optional_timeout(a_daily_timeout_seconds)
        self._active_workload_id: str | None = None
        self.repo_root = Path(repo_root) if repo_root is not None else None
        self._runner = runner or _default_runner
        self._sleeper = sleeper or time.sleep
        self._hk_0_2_python_explicit = (
            hk_0_2_python_executable is not None
            or bool(str(os.environ.get("V4_HK_0_2_PYTHON") or "").strip())
        )
        self.shared_futu_python_executable = Path(
            shared_futu_python_executable
            or os.environ.get("V3_SHARED_FUTU_PYTHON")
            or sys.executable
        )
        self.hk_0_2_python_executable = Path(
            hk_0_2_python_executable
            or os.environ.get("V4_HK_0_2_PYTHON")
            or sys.executable
        )
        self.hk_0_2_tdx_root = Path(
            hk_0_2_tdx_root
            or os.environ.get("V3_SHARED_HK_TDX_ROOT")
            or self.data_root / "hk_tdx"
        )
        repair_values = (
            repair_date,
            repair_slot,
            repair_expected_old_input_sha256,
        )
        if any(value is not None for value in repair_values):
            if not all(
                isinstance(value, str) and value.strip()
                for value in repair_values
            ):
                raise ValueError("REPAIR_AUTH_INCOMPLETE")
            if not re.fullmatch(r"\d{8}", repair_date or ""):
                raise ValueError("REPAIR_DATE_INVALID")
            if not re.fullmatch(r"\d{4}", repair_slot or ""):
                raise ValueError("REPAIR_SLOT_INVALID")
            if not re.fullmatch(
                r"[0-9a-fA-F]{64}", repair_expected_old_input_sha256 or ""
            ):
                raise ValueError("REPAIR_EXPECTED_SOURCE_SHA_INVALID")
            self.repair_date = repair_date
            self.repair_slot = repair_slot
            self.repair_expected_old_input_sha256 = (
                repair_expected_old_input_sha256.lower()
            )
        else:
            self.repair_date = None
            self.repair_slot = None
            self.repair_expected_old_input_sha256 = None

    def _hk_0_2_runtime_error(self) -> str | None:
        """Validate an explicitly selected HK 0.2 interpreter in isolation.

        This probe is deliberately scoped to the HK lane.  A direct scheduler
        or slot invocation may bypass the shell launcher, so ``is_file`` alone
        is not enough: an existing Python 3.14 executable must be rejected
        before any HK producer is started.  The caller records the result as a
        lane-local ``CANNOT_CONFIRM`` degradation and continues sibling work.
        """
        # Production callers must validate the effective default as well:
        # without an explicit argument it would otherwise fall back to the
        # scheduler's Python 3.14 interpreter.  Test doubles that do not
        # provide an explicit runtime retain their command-level seam.
        if self._runner is not _default_runner and not self._hk_0_2_python_explicit:
            return None
        executable = self.hk_0_2_python_executable
        if not executable.is_file() or not os.access(executable, os.X_OK):
            return f"HK 0.2 Python runtime missing or not executable: {executable}"
        try:
            completed = subprocess.run(
                [
                    str(executable),
                    "-c",
                    "import sys; print('.'.join(map(str, sys.version_info[:3])))",
                ],
                shell=False,
                cwd=self.repo_root if self.repo_root and self.repo_root.is_dir() else None,
                timeout=max(1, min(self.timeout_seconds, 15)),
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
        except subprocess.TimeoutExpired:
            return f"HK 0.2 Python version probe timed out: {executable}"
        except OSError as error:
            return f"HK 0.2 Python version probe failed: {type(error).__name__}: {executable}"
        version = str(completed.stdout or "").strip()
        if completed.returncode != 0:
            return f"HK 0.2 Python version probe exited {completed.returncode}: {executable}"
        if version != _HK_0_2_REQUIRED_PYTHON_VERSION:
            return (
                f"HK 0.2 requires Python {_HK_0_2_REQUIRED_PYTHON_VERSION}, "
                f"got {version or 'unknown'}: {executable}"
            )
        return None

    def _run(
        self,
        module: str,
        arguments: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        python_executable: Path | str | None = None,
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        executable = str(python_executable or sys.executable)
        if (
            timeout_seconds is None
            and self._active_workload_id == "research_panel_daily_a"
            and self.a_daily_timeout_seconds is not None
            and module == "ops.macos_research_panel_daily"
        ):
            effective_timeout = self.a_daily_timeout_seconds
        else:
            effective_timeout = self.timeout_seconds if timeout_seconds is None else int(timeout_seconds)
        command = [executable, "-m", module, *arguments]
        try:
            completed = self._runner(
                command,
                cwd=self.repo_root if cwd is None else cwd,
                timeout_seconds=effective_timeout,
                env=env,
            )
        except subprocess.TimeoutExpired as error:
            exception_type = type(error).__name__
            return {
                "status": "TIMEOUT",
                "workload_id": "",
                "modules": [module],
                "exit_code": _TIMEOUT_EXIT_CODE,
                "stdout": _bounded(
                    getattr(error, "stdout", None) or getattr(error, "output", None),
                    _STDOUT_LIMIT,
                ),
                "stderr": _bounded(
                    error.stderr or "subprocess timed out", _STDERR_LIMIT
                ),
                "exception_type": exception_type,
                "original_exception_type": exception_type,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        except Exception as error:
            structured = getattr(error, "result", None)
            failure = dict(structured) if isinstance(structured, Mapping) else {}
            stdout_value = failure.get("stdout")
            if stdout_value in (None, ""):
                stdout_value = getattr(error, "stdout", None)
            stderr_value = failure.get("stderr")
            if stderr_value in (None, ""):
                stderr_value = getattr(error, "stderr", None) or str(error)
            failure.update(
                {
                    "status": "FAILED",
                    "workload_id": failure.get("workload_id", ""),
                    "modules": failure.get("modules", [module]),
                    "exit_code": failure.get(
                        "exit_code",
                        int(error.returncode)
                        if isinstance(getattr(error, "returncode", None), int)
                        else 1,
                    ),
                    "stdout": _bounded(stdout_value, _STDOUT_LIMIT),
                    "stderr": _bounded(stderr_value, _STDERR_LIMIT),
                    "error": failure.get("error") or f"{type(error).__name__}: {error}",
                    "exception_type": failure.get("exception_type") or type(error).__name__,
                    "original_exception_type": failure.get("original_exception_type") or type(error).__name__,
                }
            )
            failure.update(
                {
                    "production_allowed": False,
                    "buy_gate_updated": False,
                    "orders_sent": False,
                }
            )
            return failure
        if isinstance(completed, Mapping):
            returncode = completed.get("returncode", 1)
            completed_stdout = completed.get("stdout")
            completed_stderr = completed.get("stderr")
        else:
            returncode = getattr(completed, "returncode", 1)
            completed_stdout = getattr(completed, "stdout", None)
            completed_stderr = getattr(completed, "stderr", None)
        if not isinstance(returncode, int):
            returncode = 1
        payload, payload_error = _decode_authoritative_payload(completed)
        if payload is None and payload_error != "AUTHORITATIVE_PAYLOAD_AMBIGUOUS":
            receipt_payload, receipt_error = _read_exact_dated_receipt(module, arguments)
            if receipt_payload is not None:
                payload, payload_error = receipt_payload, None
            elif receipt_error is not None:
                payload_error = receipt_error
        result = {
            "status": "SUCCEEDED" if returncode == 0 else "FAILED",
            "workload_id": "",
            "modules": [module],
            "exit_code": int(returncode),
            # Keep producer diagnostics bounded and expose only a complete,
            # separately decoded payload through the historical stdout seam.
            # Child handlers still parse ``stdout`` directly; it is never a
            # truncated log when an authoritative payload was found.
            "stdout": (
                json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                if payload is not None
                else _bounded(completed_stdout, _STDOUT_LIMIT)
            ),
            "stdout_log": _bounded(completed_stdout, _STDOUT_LIMIT),
            "stderr": _bounded(completed_stderr, _STDERR_LIMIT),
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        if payload is not None:
            result["_authoritative_payload"] = payload
        if payload_error is not None:
            result["_authoritative_payload_error"] = payload_error
        return result
    def _failure_result(
        self,
        workload_id: str,
        modules: list[str],
        message: str,
    ) -> dict[str, Any]:
        return {
            "status": "FAILED",
            "workload_id": workload_id,
            "modules": modules,
            "exit_code": 1,
            "stdout": "",
            "stderr": message,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    def _run_a_daily(self, request):
        failed = None
        try:
            result = self._run_a_daily_source(request)
        except WorkloadExecutionError as error:
            failed = error
            result = dict(error.result)
        if request.mode.value != "LIVE":
            if failed is not None:
                raise failed
            return result
        if (result.get("reason") == "A_DAILY_OUTSIDE_WINDOW_ALERT_ONLY" or
                result.get("original_chart_leaf", {}).get("reason") == "A_DAILY_OUTSIDE_WINDOW_ALERT_ONLY"):
            if failed is not None:
                raise failed
            return {**result, "daily_derivatives": {"status": "SKIPPED_OUTSIDE_WINDOW", "data_date": request.business_date}}
        root = os.environ.get("V4_A_SHARE_DAILY_PRODUCT_ROOT")
        data = os.environ.get("V4_RESEARCH_PANEL_A_DATA_ROOT")
        receipts = os.environ.get("V4_RESEARCH_PANEL_RECEIPT_ROOT")
        classification = os.environ.get("V4_WORKBENCH_CLASSIFICATION_ROOT")
        if not all((root, data, receipts, classification)):
            missing = {**result, "daily_derivatives": {"status": "CANNOT_CONFIRM", "reason": "A_DAILY_DERIVATIVE_BINDINGS_MISSING"}}
            if failed is not None:
                raise WorkloadExecutionError(missing)
            return missing
        from ops.research_panel_top200 import complete_daily_derivatives
        derivatives = complete_daily_derivatives(Path(data), int(request.business_date), Path(root)/"daily_products/a_share", Path(receipts), Path(classification), result if failed is not None or result.get("status") in {"FAILED", "CANNOT_CONFIRM", "TIMEOUT", "INTERRUPTED"} else None)
        completed = {**result, "daily_derivatives": derivatives}
        if failed is not None:
            raise WorkloadExecutionError(completed)
        return completed

    def _run_a_daily_source(self, request: DispatchRequest) -> dict[str, Any]:
        previous_workload_id = self._active_workload_id
        self._active_workload_id = "research_panel_daily_a"
        try:
            # A slot migration must not re-acquire an already completed date.
            # Preserve the strict receipt status; this is dated artifact reuse,
            # never evidence that the new 15:40 provider run occurred.
            if request.mode.value == "LIVE" and request.slot in {"1540", "1610", "1640"}:
                moment = shanghai_now()
                in_window = moment.strftime("%Y%m%d") == request.business_date and "1540" <= moment.strftime("%H%M") < "1700"
                root = os.environ.get("V4_RESEARCH_PANEL_RECEIPT_ROOT")
                selector = os.environ.get("V4_RESEARCH_PANEL_A_SELECTOR_POINTER")
                backtest = os.environ.get("V4_RESEARCH_PANEL_A_BACKTEST_POINTER")
                if root and selector and backtest:
                    receipt, _ = _read_exact_dated_receipt(
                        "ops.macos_research_panel_daily",
                        ["--date", request.business_date, "--lane", "A", "--receipt-root", root],
                        allow_a_failure=request.slot in {"1610", "1640"},
                    )
                    from ops.macos_research_panel_daily_receipts import validate_a_receipt
                    status = validate_a_receipt(receipt, request.business_date,
                                               selector_pointer=selector, backtest_pointer=backtest)
                    if status in {"READY", "PARTIAL_WITH_ROWS"}:
                        from ops.macos_research_panel_daily_gate import selector_pointer_is_ready
                        if not selector_pointer_is_ready(selector, request.business_date):
                            raise WorkloadExecutionError(self._failure_result("research_panel_daily_a", [],
                                "SOP_MIGRATION_REBIND_REQUIRED:paired receipt exists but generation is not ready"))
                        leaf = {"status": "CANNOT_CONFIRM", "reason": "A_DAILY_OUTSIDE_WINDOW_ALERT_ONLY"}
                        if in_window:
                            try:
                                data_root = os.environ.get("V4_RESEARCH_PANEL_A_DATA_ROOT")
                                if not data_root:
                                    raise ValueError("A_DAILY_CHART_OWNER_ROOT_MISSING")
                                product_root = Path(os.environ["V4_A_SHARE_DAILY_PRODUCT_ROOT"])/"daily_products/a_share"
                                from ops.research_panel_daily_product import checked, materialize_daily_product
                                from ops.research_panel_qfq import panel_contract
                                # validate_a_receipt already verified the paired files.
                                # Reuse the original footer contract, without another
                                # full-calendar or multi-gigabyte panel scan here.
                                selector_bytes = Path(selector).read_bytes()
                                backtest_bytes = Path(backtest).read_bytes()
                                if (selector_bytes.decode("utf-8-sig").strip() != receipt["selector"] or
                                        backtest_bytes.decode("utf-8-sig").strip() != receipt["backtest"]):
                                    raise ValueError("PAIRED_SOURCE_POINTER_IDENTITY_CONFLICT")
                                footer = panel_contract(Path(receipt["selector"]))
                                back_footer = panel_contract(Path(receipt["backtest"]))
                                authority = receipt["formula"]["authority"]
                                if (any(item["asof_date"] != int(request.business_date) or
                                        item["generation_id"] != authority["generation_id"] or
                                        item["input_sha256"] != authority["source_sha256"]
                                        for item in (footer, back_footer)) or
                                        footer["adjustment_snapshot"]["sha256"] != footer["snapshot_file_sha256"] or
                                        back_footer["adjustment_snapshot"] != footer["adjustment_snapshot"]):
                                    raise ValueError("PAIRED_SOURCE_FOOTER_IDENTITY_CONFLICT")
                                expected_identity = dict(generation=authority["generation_id"],
                                    input_sha256=authority["source_sha256"], snapshot=footer["adjustment_snapshot"],
                                    selector_artifact_sha256=receipt["selector_sha256"], asof=int(request.business_date),
                                    basis=footer["market_basis"]["A"], historical_PIT=False)
                                def saved_leaf():
                                    index = json.loads((product_root/"index.json").read_bytes())
                                    manifest_ref = index["dates"][request.business_date]
                                    manifest = json.loads(checked(manifest_ref).read_bytes())
                                    product = json.loads(checked(manifest["artifact"]).read_bytes())
                                    if product["data_date"] != request.business_date or product["sample_only"] is not False:
                                        raise ValueError("EXISTING_DAILY_PRODUCT_DATE_OR_SCOPE_CONFLICT")
                                    if (product["source_identity"] != expected_identity or
                                            product["source_generation"] != expected_identity["generation"] or
                                            manifest["source_generation"] != expected_identity["generation"] or
                                            manifest["input_sha256"] != expected_identity["input_sha256"] or
                                            manifest["snapshot"] != expected_identity["snapshot"]):
                                        raise ValueError("EXISTING_DAILY_PRODUCT_CURRENT_PAIRED_IDENTITY_CONFLICT")
                                    chart = index["original_charts"][request.business_date]
                                    if chart["numeric_manifest"] != manifest_ref:
                                        raise ValueError("EXISTING_DAILY_CHART_NUMERIC_BINDING_CONFLICT")
                                    samples = json.loads(checked(chart["manifest"]).read_bytes())["samples"]
                                    chart_receipt = json.loads(checked(chart["receipt"]).read_bytes())
                                    if (set(samples) != {row["symbol"] for row in product["rows"]} or
                                            chart_receipt.get("status") != "OWNER_CHARTS_COMPLETED"):
                                        raise ValueError("EXISTING_DAILY_CHART_LEAF_INCOMPLETE")
                                    for sample in samples.values():
                                        if any(not Path(sample[kind]["path"]).is_file() for kind in ("html", "PNG", "projection")):
                                            raise ValueError("EXISTING_DAILY_CHART_ASSET_MISSING")
                                    if (Path(selector).read_bytes() != selector_bytes or
                                            Path(backtest).read_bytes() != backtest_bytes):
                                        raise ValueError("PAIRED_SOURCE_CHANGED_DURING_LEAF_RECOVERY")
                                    return {"status": product["status"], "manifest": manifest_ref, "reused": True, "numeric_recomputed": False}
                                try:
                                    leaf = saved_leaf()
                                except (OSError, ValueError, KeyError, TypeError):
                                    # The paired source is already valid. Resume its exact
                                    # original materializer/checkpoints, without invoking
                                    # collection or formula-source generation a second time.
                                    recovered = materialize_daily_product(data_root=data_root,
                                        target=int(request.business_date), output_root=product_root)
                                    leaf = {**saved_leaf(), "recovered_by_original_materializer": True,
                                            "numeric_recomputed": None, "materialization": recovered}
                            except Exception as error:
                                leaf = {"status": "CANNOT_CONFIRM", "reason": "ORIGINAL_CHART_LEAF_RECOVERY_FAILED:" + str(error)}
                        path = Path(root) / f"a-{request.business_date}.json"
                        reused = {"status": "SUCCEEDED", "lane": "A", "lane_status": status,
                                "target_date": request.business_date, "modules": [], "exit_code": 0,
                                "migration_reuse": True, "provider_invoked": False,
                                "numeric_recomputed": leaf.get("numeric_recomputed"), "source_recomputed": False, "original_chart_leaf": leaf,
                                "natural_1540_verified": False, "source_receipt": str(path),
                                "source_receipt_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                "row_count": receipt.get("row_count"),
                                "coverage_rate": receipt.get("coverage_rate"),
                                "accepted_count": receipt.get("accepted_count"),
                                "quarantine_count": receipt.get("quarantine_count"),
                                "target_count": receipt.get("target_count"),
                                "reason": "EXACT_DATED_A_RECEIPT_REUSED_WITH_PAIRED_ARTIFACT_BINDING" if in_window else "A_DAILY_OUTSIDE_WINDOW_ALERT_ONLY",
                                "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
                        if in_window and leaf["status"] == "CANNOT_CONFIRM":
                            raise WorkloadExecutionError({**reused, "status": "FAILED", "exit_code": 1,
                                "reason": "A_DAILY_PRODUCT_LEAF_RECOVERY_FAILED"})
                        return reused
                    if request.slot in {"1610", "1640"} and (not isinstance(receipt, dict) or receipt.get("status") not in {"FAILED", "CANNOT_CONFIRM"}):
                        raise WorkloadExecutionError(self._failure_result("research_panel_daily_a", [],
                            "A_DAILY_RETRY_REQUIRES_EXACT_DATED_FAILED_RECEIPT"))
                elif request.slot in {"1610", "1640"}:
                    raise WorkloadExecutionError(self._failure_result("research_panel_daily_a", [],
                        "A_DAILY_RETRY_BINDING_MISSING"))
                if not in_window:
                    failure = self._failure_result("research_panel_daily_a", [], "A_DAILY_OUTSIDE_WINDOW_ALERT_ONLY")
                    failure.update(failure_class="UPSTREAM_NOT_READY", reason="A_DAILY_OUTSIDE_WINDOW_ALERT_ONLY")
                    raise WorkloadExecutionError(failure)
            return self._research_panel_daily(request, lane="A")
        finally:
            self._active_workload_id = previous_workload_id

    def __call__(
        self,
        workload: WorkloadDefinition,
        request: DispatchRequest,
        decision: Any = None,
    ) -> dict[str, Any]:
        if workload.workload_id not in ALLOWED_WORKLOAD_IDS:
            raise ValueError(f"unknown workload_id: {workload.workload_id}")
        _graph_notify("MAIN", workload.workload_id, request.business_date, "EXECUTOR_ENTERED")
        if workload.workload_id in MILESTONE_BY_WORKLOAD:
            result = self._run_stage_center_milestone(workload, request)
        elif workload.workload_id in CLOSE_NODE_BY_WORKLOAD:
            result = self._run_close_review_node(workload, request)
        else:
            handler = {
                "hourly_research": self._hourly_research,
                "us_market_digest": self._us_market_digest,
                "research_preselection_refresh": self._research_preselection_refresh,
                "zsxq_0830": self._zsxq_0830,
                "morning_news_0830": self._morning_news_0830,
                "baimao_x_refresh": self._baimao_x_refresh,
                "hk_auction_0920": self._hk_auction_0920,
                "stage_workbench": self._stage_workbench,
                "preselection_pools": self._preselection_pools,
                "daily_materialize": self._daily_materialize,
                "a_share_close_review": self._a_share_close_review,
                "hk_connect_close_review": self._hk_connect_close_review,
                "research_panel_daily_a": self._run_a_daily,
                "research_panel_daily_hk": lambda request: self._research_panel_daily(request, lane="HK"),
                "research_panel_runtime_evidence": self._research_panel_runtime_evidence,
                "wechat_preselection_sync": self._wechat_preselection_sync,
                "review_core_pool_pipeline": self._review_core_pool_pipeline,
            }[workload.workload_id]
            result = handler(request)
        result["workload_id"] = workload.workload_id
        result["production_allowed"] = False
        result["buy_gate_updated"] = False
        result["orders_sent"] = False
        if result["status"] != "SUCCEEDED":
            raise WorkloadExecutionError(result)
        return result


_FUNCTION_SOURCES = {
    **{
        name: getattr(_common, name)
        for name in (
            "_audited_peripheral_degradation",
            "_audited_peripheral_timeout_reuse",
            "_bounded",
            "_collector_not_materialized_result",
            "_default_runner",
        )
    },
    **{
        name: getattr(_research, name)
        for name in (
            "_repair_requested",
            "_repair_collector_arguments",
            "_hourly_research",
            "_us_market_digest",
            "_zsxq_0830",
            "_morning_news_0830",
            "_research_preselection_refresh",
            "_baimao_x_refresh",
            "_stage_workbench",
            "_hk_auction_0920",
        )
    },
    **{
        name: getattr(_preselection, name)
        for name in (
            "_verified_formal_pool_reuse",
            "_preselection_pools",
        )
    },
    **{
        name: getattr(_review, name)
        for name in (
            "_daily_materialize",
            "_decoded_stdout",
            "_safe_lane_status",
            "_research_panel_runtime_evidence",
            "_research_panel_daily",
            "_wechat_preselection_sync",
            "_review_core_pool_pipeline",
            "_run_stage_center_milestone",
            "_run_close_review_node",
            "_a_share_close_review",
            "_hk_connect_close_review",
        )
    },
}

_METHOD_NAMES = frozenset(
    name
    for name in _FUNCTION_SOURCES
    if name not in {
        "_audited_peripheral_degradation",
        "_audited_peripheral_timeout_reuse",
        "_bounded",
        "_collector_not_materialized_result",
        "_default_runner",
        "_repair_requested",
        "_repair_collector_arguments",
    }
)
_STATIC_METHOD_NAMES = frozenset({"_decoded_stdout", "_safe_lane_status"})


def _rebind_function(source: FunctionType) -> FunctionType:
    rebound = FunctionType(
        source.__code__,
        globals(),
        name=source.__name__,
        argdefs=source.__defaults__,
        closure=source.__closure__,
    )
    rebound.__kwdefaults__ = source.__kwdefaults__
    rebound.__annotations__ = source.__annotations__
    rebound.__doc__ = source.__doc__
    rebound.__dict__ = source.__dict__.copy()
    rebound.__qualname__ = (
        f"FixedExecutorRegistry.{source.__name__}"
        if source.__name__ in _METHOD_NAMES
        else source.__qualname__
    )
    rebound.__module__ = __name__
    if hasattr(source, "__type_params__"):
        rebound.__type_params__ = source.__type_params__
    return rebound


for _function_name, _function_source in _FUNCTION_SOURCES.items():
    _rebound = _rebind_function(_function_source)
    globals()[_function_name] = _rebound
    if _function_name in _METHOD_NAMES:
        setattr(
            FixedExecutorRegistry,
            _function_name,
            staticmethod(_rebound)
            if _function_name in _STATIC_METHOD_NAMES
            else _rebound,
        )

del _common, _research, _preselection, _review
del _FUNCTION_SOURCES, _METHOD_NAMES, _STATIC_METHOD_NAMES
del _function_name, _function_source, _rebound, FunctionType

__all__ = [
    "ALLOWED_WORKLOAD_IDS",
    "FixedExecutorRegistry",
    "WorkloadExecutionError",
]
