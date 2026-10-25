"""Fixed Python executor registry for the V3.5 runtime dispatcher.

The registry selects a whitelisted Python module and a fixed argument list per
``workload_id``.  It never reads ``WorkloadDefinition.command``: the catalog
command remains an audit/oracle field only.  Business inputs come exclusively
from the V3.5/shared-owned roots passed at construction; when an input is
absent the module fails closed and the registry raises a structured failure.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from contracts.runtime_tasks import DispatchRequest, WorkloadDefinition
from ops.daily_materialize import resolve_selector_panel
from infrastructure.research_peripheral_store import ResearchPeripheralStore
from infrastructure.owned_path import resolve_owned_path

ALLOWED_WORKLOAD_IDS = frozenset(
    {
        "hourly_research",
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


def _audited_peripheral_degradation(
    result: dict[str, Any],
    *,
    data_root: Path,
    trade_date: str,
) -> dict[str, Any] | None:
    """Accept only a code-2 materializer summary backed by verified artifacts."""
    if result.get("status") != "FAILED" or result.get("exit_code") != 2:
        return None
    try:
        summary = json.loads(str(result.get("stdout") or ""))
        if set(summary) != {"trade_date", "source", "outputs"}:
            return None
        if summary["trade_date"] != trade_date or summary["source"] != "both":
            return None
        outputs = summary["outputs"]
        if not isinstance(outputs, list) or len(outputs) != len(_PERIPHERAL_SOURCES):
            return None
        store = ResearchPeripheralStore(data_root)
        sources: list[dict[str, Any]] = []
        seen: set[str] = set()
        for output in outputs:
            if set(output) != {"source", "status", "item_count", "payload_path", "receipt_path"}:
                return None
            source = output["source"]
            if source not in _PERIPHERAL_SOURCES or source in seen:
                return None
            status = output["status"]
            if status not in _PERIPHERAL_STATUSES or type(output["item_count"]) is not int:
                return None
            expected_payload = f"research/peripherals/{trade_date}/{source}.json"
            expected_receipt = f"receipts/research/peripherals/{trade_date}/{source}.json"
            if output["payload_path"] != expected_payload or output["receipt_path"] != expected_receipt:
                return None
            payload = store.read_exact(trade_date, source)
            if payload is None or payload["status"] != status or payload["item_count"] != output["item_count"]:
                return None
            if any(payload.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent")):
                return None
            gaps = payload.get("cannot_confirm")
            if not isinstance(gaps, list) or any(not isinstance(gap, str) for gap in gaps):
                return None
            seen.add(source)
            sources.append(
                {
                    "source": source,
                    "status": status,
                    "item_count": output["item_count"],
                    "cannot_confirm": gaps,
                }
            )
        if seen != _PERIPHERAL_SOURCES:
            return None
        gaps = sorted({gap for source in sources for gap in source["cannot_confirm"]})
        if not gaps:
            return None
        return {
            "module": "ops.materialize_research_peripherals",
            "exit_code": 2,
            "gaps": gaps,
            "sources": sorted(sources, key=lambda source: source["source"]),
        }
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _audited_peripheral_timeout_reuse(
    *,
    data_root: Path,
    trade_date: str,
) -> dict[str, Any] | None:
    """Accept a timed-out refresh only when both exact-date stores verify.

    A refresh timeout must not erase already-published same-day evidence.  The
    store reader verifies the manifest, payload schema, date/source identity,
    and safety flags before this helper returns a degradation record.  Missing
    or unsafe evidence still fails closed in ``_hourly_research``.
    """
    try:
        store = ResearchPeripheralStore(data_root)
        sources: list[dict[str, Any]] = []
        source_fetched_at: dict[str, str] = {}
        gaps = {"PERIPHERAL_REFRESH_TIMEOUT_REUSED_EXACT_DATE"}
        for source in sorted(_PERIPHERAL_SOURCES):
            payload = store.read_exact(trade_date, source)
            if payload is None or payload.get("status") not in _PERIPHERAL_STATUSES:
                return None
            if any(
                payload.get(flag) is not False
                for flag in ("production_allowed", "buy_gate_updated", "orders_sent")
            ):
                return None
            fetched_at = payload.get("fetched_at")
            cannot_confirm = payload.get("cannot_confirm")
            if (
                not isinstance(fetched_at, str)
                or not fetched_at
                or not isinstance(cannot_confirm, list)
                or any(not isinstance(gap, str) for gap in cannot_confirm)
            ):
                return None
            source_fetched_at[source] = fetched_at
            gaps.update(cannot_confirm)
            sources.append(
                {
                    "source": source,
                    "status": payload["status"],
                    "item_count": payload["item_count"],
                    "cannot_confirm": cannot_confirm,
                }
            )
        return {
            "module": "ops.materialize_research_peripherals",
            "exit_code": _TIMEOUT_EXIT_CODE,
            "reason": "PERIPHERAL_REFRESH_TIMEOUT_REUSED_EXACT_DATE",
            "gaps": sorted(gaps),
            "sources": sources,
            "source_fetched_at": source_fetched_at,
        }
    except (KeyError, OSError, TypeError, ValueError):
        return None


def _bounded(value: str | None, limit: int) -> str:
    text = value or ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n[truncated, total {len(text)} chars]"


def _collector_not_materialized_result(
    collected: dict[str, Any],
    *,
    workload_id: str,
    modules: list[str],
    collector_payload: dict[str, Any],
) -> dict[str, Any] | None:
    """Convert an empty collector response into a typed upstream failure.

    ``ops.collect_hourly_research_input`` may complete its own bounded fetch
    with ``READY_EMPTY``.  That is evidence that the fetch ran, not evidence
    that a formal hourly research artifact can be published.  Keep the
    collector receipt in the child result while preventing the executor from
    invoking the archive runner or reporting a successful workload.
    """

    row_count = collector_payload.get("row_count")
    if (
        collector_payload.get("status") == "READY_WITH_RESEARCH_POOL"
        and type(row_count) is int
        and row_count > 0
    ):
        return None
    result = dict(collected)
    result.update(
        {
            "status": "NOT_MATERIALIZED",
            "workload_id": workload_id,
            "modules": modules,
            "failure_class": "UPSTREAM_NOT_READY",
            "reason": "HOURLY_RESEARCH_INPUT_NOT_MATERIALIZED",
            "collector_status": str(collector_payload.get("status") or "CANNOT_CONFIRM"),
            "row_count": row_count if type(row_count) is int else 0,
            "hourly_artifact_status": "NOT_MATERIALIZED",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    )
    return result


def _default_runner(
    command: list[str],
    *,
    cwd: Path | None,
    timeout_seconds: int,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        shell=False,
        cwd=cwd,
        env=env,
        timeout=timeout_seconds,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


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
        self.repo_root = Path(repo_root) if repo_root is not None else None
        self._runner = runner or _default_runner
        self._sleeper = sleeper or time.sleep
        self._hk_0_2_python_explicit = (
            hk_0_2_python_executable is not None
            or bool(str(os.environ.get("V35_HK_0_2_PYTHON") or "").strip())
        )
        self.shared_futu_python_executable = Path(
            shared_futu_python_executable
            or os.environ.get("V3_SHARED_FUTU_PYTHON")
            or sys.executable
        )
        self.hk_0_2_python_executable = Path(
            hk_0_2_python_executable
            or os.environ.get("V35_HK_0_2_PYTHON")
            or sys.executable
        )
        self.hk_0_2_tdx_root = Path(
            hk_0_2_tdx_root
            or os.environ.get("V3_SHARED_HK_TDX_ROOT")
            or self.data_root / "hk_tdx"
        )

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
            return {
                "status": "TIMEOUT",
                "workload_id": "",
                "modules": [module],
                "exit_code": _TIMEOUT_EXIT_CODE,
                "stdout": _bounded(str(error.stdout or ""), _STDOUT_LIMIT),
                "stderr": _bounded(
                    str(error.stderr or "") or "subprocess timed out", _STDERR_LIMIT
                ),
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        return {
            "status": "SUCCEEDED" if completed.returncode == 0 else "FAILED",
            "workload_id": "",
            "modules": [module],
            "exit_code": int(completed.returncode),
            "stdout": _bounded(completed.stdout, _STDOUT_LIMIT),
            "stderr": _bounded(completed.stderr, _STDERR_LIMIT),
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    def _hourly_research(
        self, request: DispatchRequest
    ) -> dict[str, Any]:
        refresh_zsxq = int(request.slot) >= 900
        zsxq_refresh_failure: dict[str, Any] | None = None
        modules = [
            *(["ops.run_zsxq_hourly_delta"] if refresh_zsxq else []),
            "ops.materialize_research_peripherals",
            "ops.collect_hourly_research_input",
            "ops.run_hourly_research",
        ]
        if refresh_zsxq:
            zsxq = self._run(
                modules[0],
                [
                    "--data-root", str(self.data_root),
                    "--date", request.business_date,
                    "--slot", request.slot,
                ],
            )
            if zsxq["status"] == "SUCCEEDED":
                try:
                    decoded = json.loads(str(zsxq.get("stdout") or "{}"))
                except json.JSONDecodeError:
                    decoded = {}
                if decoded.get("status") not in {"READY", "READY_EMPTY"}:
                    zsxq["status"] = "FAILED"
                    zsxq["reason"] = "paginated ZSXQ delta did not verify"
            if zsxq["status"] != "SUCCEEDED":
                zsxq_refresh_failure = dict(zsxq)
        peripheral_module = "ops.materialize_research_peripherals"
        peripherals = self._run(
            peripheral_module,
            [
                "--data-root", str(self.data_root),
                "--trade-date", request.business_date,
                "--source", "both",
                "--reuse-existing",
                "--timeout", str(_PERIPHERAL_FETCH_TIMEOUT_SECONDS),
            ],
        )
        degraded_inputs = _audited_peripheral_degradation(
            peripherals,
            data_root=self.data_root,
            trade_date=request.business_date,
        )
        if peripherals["status"] == "TIMEOUT" and degraded_inputs is None:
            degraded_inputs = _audited_peripheral_timeout_reuse(
                data_root=self.data_root,
                trade_date=request.business_date,
            )
        if peripherals["status"] != "SUCCEEDED":
            if degraded_inputs is not None:
                peripherals["degraded_inputs"] = degraded_inputs
            else:
                peripherals["workload_id"] = "hourly_research"
                peripherals["modules"] = modules
                raise WorkloadExecutionError(peripherals)
        collected = self._run(
            "ops.collect_hourly_research_input",
            [
                "--data-root", str(self.data_root),
                "--date", request.business_date,
                "--slot", request.slot,
            ],
        )
        try:
            collected_payload = json.loads(str(collected.get("stdout") or "{}"))
        except json.JSONDecodeError:
            collected_payload = {}
        collector_failure = _collector_not_materialized_result(
            collected,
            workload_id="hourly_research",
            modules=modules,
            collector_payload=collected_payload,
        )
        if collector_failure is not None and zsxq_refresh_failure is None:
            if degraded_inputs is not None:
                collector_failure["degraded_inputs"] = degraded_inputs
            raise WorkloadExecutionError(collector_failure)
        if collected["status"] != "SUCCEEDED":
            if degraded_inputs is not None:
                collected["degraded_inputs"] = degraded_inputs
            collected["workload_id"] = "hourly_research"
            collected["modules"] = modules
            raise WorkloadExecutionError(collected)
        zsxq_degraded_input: dict[str, Any] | None = None
        if zsxq_refresh_failure is not None:
            fallback_row_count = collected_payload.get("row_count")
            verified_same_day_rows = (
                collected_payload.get("status") == "READY_WITH_RESEARCH_POOL"
                and type(fallback_row_count) is int
                and fallback_row_count > 0
            )
            if not verified_same_day_rows:
                failure = dict(zsxq_refresh_failure)
                failure.update(
                    {
                        "workload_id": "hourly_research",
                        "modules": modules,
                        "reason": "ZSXQ_REFRESH_FAILED_NO_VERIFIED_SAME_DAY_INPUT",
                    }
                )
                raise WorkloadExecutionError(failure)
            zsxq_degraded_input = {
                "reason": "ZSXQ_REFRESH_FAILED_REUSED_VERIFIED_SAME_DAY_INPUT",
                "refresh_exit_code": int(zsxq_refresh_failure.get("exit_code") or 0),
                "fallback_row_count": fallback_row_count,
                "fallback_source_path": str(
                    collected_payload.get("source_path") or ""
                ),
            }
        if collector_failure is not None:
            if degraded_inputs is not None:
                collector_failure["degraded_inputs"] = degraded_inputs
            raise WorkloadExecutionError(collector_failure)
        run_arguments = [
                "--data-root", str(self.data_root),
                "--date", request.business_date,
                "--target-date", request.business_date,
                "--slot", request.slot,
                "--mode", request.mode.value,
        ]
        if collected_payload.get("recovery") is True:
            recovery_relative = str(collected_payload.get("source_path") or "")
            recovery_path = resolve_owned_path(self.data_root, recovery_relative)
            run_arguments.extend(["--source", str(recovery_path)])
        result = self._run(
            "ops.run_hourly_research",
            run_arguments,
        )
        result["modules"] = modules
        if degraded_inputs is not None:
            result["degraded_inputs"] = degraded_inputs
        if zsxq_degraded_input is not None:
            result["zsxq_degraded_input"] = zsxq_degraded_input
        retryable_sources: list[str] = []
        if zsxq_degraded_input is not None:
            retryable_sources.append("zsxq")
        if degraded_inputs is not None:
            external_finance = next(
                (
                    source
                    for source in degraded_inputs.get("sources", [])
                    if source.get("source") == "external_finance"
                ),
                None,
            )
            if (
                external_finance is not None
                and external_finance.get("status") == "CANNOT_CONFIRM"
                and external_finance.get("item_count") == 0
                and any(
                    str(gap).startswith("EXTERNAL_FINANCE_FETCH_FAILED:")
                    for gap in external_finance.get("cannot_confirm", [])
                )
            ):
                retryable_sources.append("external_finance")
        if result.get("status") == "SUCCEEDED" and retryable_sources:
            result.update(
                {
                    "status": "FAILED",
                    "workload_id": "hourly_research",
                    "reason": "RESEARCH_SOURCE_REFRESH_RETRY_REQUIRED",
                    "retryable_sources": sorted(retryable_sources),
                    "hourly_artifact_status": "SUCCEEDED",
                }
            )
            raise WorkloadExecutionError(result)
        return result

    def _zsxq_0830(self, request: DispatchRequest) -> dict[str, Any]:
        modules = [
            "ops.run_zsxq_hourly_delta",
            "ops.collect_hourly_research_input",
            "ops.run_hourly_research",
        ]
        fetched = self._run(
            modules[0],
            [
                "--data-root", str(self.data_root),
                "--date", request.business_date,
                "--slot", request.slot,
            ],
        )
        if fetched["status"] == "SUCCEEDED":
            try:
                decoded = json.loads(str(fetched.get("stdout") or "{}"))
            except json.JSONDecodeError:
                decoded = {}
            if decoded.get("status") not in {"READY", "READY_EMPTY"}:
                fetched["status"] = "FAILED"
                fetched["reason"] = "ZSXQ 08:30 did not produce a verified status"
        if fetched["status"] != "SUCCEEDED":
            fetched["workload_id"] = "zsxq_0830"
            fetched["modules"] = modules
            raise WorkloadExecutionError(fetched)
        collected = self._run(
            modules[1],
            [
                "--data-root", str(self.data_root),
                "--date", request.business_date,
                "--slot", request.slot,
            ],
        )
        try:
            collected_payload = json.loads(str(collected.get("stdout") or "{}"))
        except json.JSONDecodeError:
            collected_payload = {}
        collector_failure = _collector_not_materialized_result(
            collected,
            workload_id="zsxq_0830",
            modules=modules,
            collector_payload=collected_payload,
        )
        if collector_failure is not None:
            raise WorkloadExecutionError(collector_failure)
        if collected["status"] != "SUCCEEDED":
            collected["workload_id"] = "zsxq_0830"
            collected["modules"] = modules
            raise WorkloadExecutionError(collected)
        result = self._run(
            modules[2],
            [
                "--data-root", str(self.data_root),
                "--date", request.business_date,
                "--target-date", request.business_date,
                "--slot", request.slot,
                "--mode", request.mode.value,
            ],
        )
        result["modules"] = modules
        return result

    def _morning_news_0830(self, request: DispatchRequest) -> dict[str, Any]:
        module = "scripts.run_scheduled_morning_news"
        modules = [module]
        if self.shared_data_root is None or self.shared_package_root is None:
            raise WorkloadExecutionError(
                self._failure_result(
                    "morning_news_0830",
                    modules,
                    "shared data root and shared package root are required",
                )
            )
        entry = self.shared_package_root / "scripts" / "run_scheduled_morning_news.py"
        if not entry.is_file():
            raise WorkloadExecutionError(
                self._failure_result(
                    "morning_news_0830",
                    modules,
                    "fixed shared morning-news entry is missing",
                )
            )
        environment = os.environ.copy()
        environment["V3_SHARED_DATA_STORE_ROOT"] = str(self.shared_data_root)
        result = self._run(
            module,
            ["--trade-date", request.business_date],
            cwd=self.shared_package_root,
            env=environment,
        )
        result["modules"] = modules
        return result

    def _research_preselection_refresh(
        self, request: DispatchRequest
    ) -> dict[str, Any]:
        return self._run(
            "ops.refresh_research_preselection",
            [
                "--data-root", str(self.data_root),
                "--date", request.business_date,
            ],
        )

    def _baimao_x_refresh(self, request: DispatchRequest) -> dict[str, Any]:
        return self._run(
            "ops.refresh_baimao_x_digest",
            [
                "--data-root", str(self.data_root),
                "--date", request.business_date,
                "--slot", request.slot,
            ],
        )

    def _stage_workbench(
        self, request: DispatchRequest
    ) -> dict[str, Any]:
        if self.shared_data_root is None:
            raise WorkloadExecutionError(
                self._failure_result(
                    "stage_workbench",
                    ["ops.materialize_stage_workbench"],
                    "shared data root not configured",
                )
            )
        try:
            stage_id = STAGE_BY_SLOT[request.slot]
        except KeyError as error:
            raise WorkloadExecutionError(
                self._failure_result(
                    "stage_workbench",
                    ["ops.materialize_stage_workbench"],
                    f"unknown stage slot: {request.slot}",
                )
            ) from error
        modules = ["ops.materialize_stage_workbench"]
        result = self._run(
            "ops.materialize_stage_workbench",
            [
                "--data-root", str(self.data_root),
                "--date", request.business_date,
                "--stage", stage_id,
                "--shared-data-root", str(self.shared_data_root),
                *(
                    ["--shared-package-root", str(self.shared_package_root)]
                    if self.shared_package_root is not None
                    else []
                ),
            ],
        )
        result["modules"] = modules
        return result

    def _hk_auction_0920(self, request: DispatchRequest) -> dict[str, Any]:
        """Run the single-owner shared capture plus V3.5 materialization bridge."""
        security_module = "ops.ensure_hk_security_master"
        capture_module = "ops.run_hkconnect_0915_0920_capture"
        modules = [security_module, capture_module]
        if (
            self.shared_data_root is None
            or self.hk_universe_root is None
            or self.shared_package_root is None
        ):
            raise WorkloadExecutionError(
                self._failure_result(
                    "hk_auction_0920",
                    modules,
                    "shared data root, HK universe root, and shared package root are required",
                )
            )
        security_entry = (self.repo_root or Path.cwd()) / "ops" / "ensure_hk_security_master.py"
        if not security_entry.is_file():
            raise WorkloadExecutionError(
                self._failure_result(
                    "hk_auction_0920",
                    modules,
                    "fixed HK security-master entry missing",
                )
            )
        environment = os.environ.copy()
        environment["V3_SHARED_DATA_STORE_ROOT"] = str(self.shared_data_root)
        environment["V3_SHARED_FUTU_PYTHON"] = str(self.shared_futu_python_executable)
        security_result = self._run(
            security_module,
            [
                "--store-root", str(self.shared_data_root),
                "--universe-root", str(self.hk_universe_root),
                "--shared-package-root", str(self.shared_package_root),
                "--trade-date", request.business_date,
                "--futu-python", str(self.shared_futu_python_executable),
            ],
            env=environment,
        )
        if security_result["status"] != "SUCCEEDED":
            security_result["modules"] = modules
            security_result["workload_id"] = "hk_auction_0920"
            raise WorkloadExecutionError(security_result)
        result = self._run(
            capture_module,
            [
                "--data-root", str(self.data_root),
                "--shared-data-root", str(self.shared_data_root),
                "--shared-package-root", str(self.shared_package_root),
                "--trade-date", request.business_date,
                "--futu-python", str(self.shared_futu_python_executable),
            ],
            env=environment,
            timeout_seconds=_HK_AUCTION_0920_TIMEOUT_SECONDS,
        )
        result["modules"] = modules
        result["workload_id"] = "hk_auction_0920"
        if result["status"] != "SUCCEEDED":
            raise WorkloadExecutionError(result)
        return result

    def _preselection_pools(
        self, request: DispatchRequest
    ) -> dict[str, Any]:
        modules = [
            "scripts.capture_public_fupan",
            "ops.materialize_shared_v192_preselection",
            "scripts.update_hk_0_2_panel",
            "ops.ensure_hk_security_master",
            "scripts.materialize_hk_0_2",
            "ops.materialize_d1_review_lanes",
            "ops.materialize_scheduled_preselection",
        ]
        if (
            self.shared_data_root is None
            or self.hk_universe_root is None
            or self.shared_package_root is None
        ):
            raise WorkloadExecutionError(
                self._failure_result(
                    "preselection_pools",
                    modules,
                    "shared data root, HK universe root, and shared package root are required",
                )
            )
        if self.preselection_input_root is None:
            raise WorkloadExecutionError(
                self._failure_result(
                    "preselection_pools",
                    modules,
                    "preselection input root not configured",
                )
            )
        for shared_entry in (
            self.shared_package_root / "scripts" / "capture_public_fupan.py",
            self.shared_package_root / "scripts" / "materialize_v192_selector.py",
            self.shared_package_root / "scripts" / "update_hk_0_2_panel.py",
            self.shared_package_root / "scripts" / "materialize_hk_0_2.py",
        ):
            if not shared_entry.is_file():
                raise WorkloadExecutionError(
                    self._failure_result(
                        "preselection_pools",
                        modules,
                        f"fixed shared entry missing: {shared_entry.name}",
                    )
                )
        security_entry = (self.repo_root or Path.cwd()) / "ops" / "ensure_hk_security_master.py"
        if not security_entry.is_file():
            raise WorkloadExecutionError(
                self._failure_result(
                    "preselection_pools",
                    modules,
                    "fixed HK security-master entry missing",
                )
            )
        selector: Path | None = None
        selector_error = ""
        if self.selector_data_root is None:
            selector_error = "selector data root not configured"
        else:
            try:
                selector = resolve_selector_panel(
                    self.selector_data_root, request.business_date
                )
            except FileNotFoundError as error:
                selector_error = f"selector panel unresolved: {error}"
        trusted_env = os.environ.copy()
        trusted_env.update({
            "V3_SHARED_DATA_STORE_ROOT": str(self.shared_data_root),
            "V35_SHARED_PACKAGE_ROOT": str(self.shared_package_root),
            "V3_SHARED_FUTU_PYTHON": str(self.shared_futu_python_executable),
            "V35_HK_0_2_PYTHON": str(self.hk_0_2_python_executable),
            "V3_SHARED_HK_TDX_ROOT": str(self.hk_0_2_tdx_root),
        })
        if selector is not None:
            trusted_env["V3_SHARED_SELECTOR_READY_PANEL"] = str(selector)
        else:
            trusted_env.pop("V3_SHARED_SELECTOR_READY_PANEL", None)
        a_lane_degradations: list[dict[str, Any]] = []
        if selector_error:
            a_lane_degradations.append(
                {
                    "status": "CANNOT_CONFIRM",
                    "lane": "A_SHARE",
                    "reason": selector_error,
                    "production_allowed": False,
                    "buy_gate_updated": False,
                    "orders_sent": False,
                }
            )
        public_result = self._run(
            "scripts.capture_public_fupan",
            ["--trade-date", request.business_date],
            cwd=self.shared_package_root,
            env=trusted_env,
        )
        if public_result["status"] != "SUCCEEDED":
            public_result = dict(public_result)
            public_result["lane"] = "A_SHARE"
            public_result["status"] = "CANNOT_CONFIRM"
            a_lane_degradations.append(public_result)
        shared_result = self._run(
            "ops.materialize_shared_v192_preselection",
            [
                "--signal-date", request.business_date,
                "--target-date", request.target_date,
            ],
            cwd=self.repo_root,
            env=trusted_env,
            timeout_seconds=_V192_PRESELECTION_TIMEOUT_SECONDS,
        )
        if shared_result["status"] != "SUCCEEDED":
            shared_result = dict(shared_result)
            shared_result["lane"] = "A_SHARE"
            shared_result["status"] = "CANNOT_CONFIRM"
            a_lane_degradations.append(shared_result)
        hk_lane_degradations: list[dict[str, Any]] = []
        hk_runtime_error = self._hk_0_2_runtime_error()
        hk_runtime_missing = (
            self._runner is _default_runner
            and not self.hk_0_2_python_executable.is_file()
        )
        hk_runtime_unavailable = hk_runtime_error is not None or hk_runtime_missing
        if hk_runtime_unavailable:
            update_result = self._failure_result(
                "preselection_pools",
                ["scripts.update_hk_0_2_panel"],
                hk_runtime_error
                or f"HK 0.2 Python runtime missing: {self.hk_0_2_python_executable}",
            )
            update_result["lane"] = "HK_CONNECT"
            update_result["status"] = "CANNOT_CONFIRM"
            hk_lane_degradations.append(update_result)
        else:
            update_result = self._run(
                "scripts.update_hk_0_2_panel",
                [
                    "--asset-root", str(self.shared_data_root / "assets" / "hk_0_2"),
                    "--tdx-root", str(self.hk_0_2_tdx_root),
                    "--through-date", request.business_date,
                ],
                cwd=self.shared_package_root,
                env=trusted_env,
                python_executable=self.hk_0_2_python_executable,
            )
            if update_result["status"] != "SUCCEEDED":
                update_result = dict(update_result)
                update_result["lane"] = "HK_CONNECT"
                update_result["status"] = "CANNOT_CONFIRM"
                hk_lane_degradations.append(update_result)
        security_result = self._run(
            "ops.ensure_hk_security_master",
            [
                "--store-root", str(self.shared_data_root),
                "--universe-root", str(self.hk_universe_root),
                "--shared-package-root", str(self.shared_package_root),
                "--trade-date", request.business_date,
                "--futu-python", str(self.shared_futu_python_executable),
            ],
            cwd=self.repo_root,
            env=trusted_env,
        )
        if security_result["status"] != "SUCCEEDED":
            security_result = dict(security_result)
            security_result["lane"] = "HK_CONNECT"
            security_result["status"] = "CANNOT_CONFIRM"
            hk_lane_degradations.append(security_result)
        if hk_runtime_unavailable:
            hk_result = dict(update_result)
            hk_result["modules"] = ["scripts.materialize_hk_0_2"]
        else:
            hk_result = self._run(
                "scripts.materialize_hk_0_2",
                [
                    "--store-root", str(self.shared_data_root),
                    "--asset-root", str(self.shared_data_root / "assets" / "hk_0_2"),
                    "--signal-date", request.business_date,
                    "--target-date", request.target_date,
                ],
                cwd=self.shared_package_root,
                env=trusted_env,
                python_executable=self.hk_0_2_python_executable,
            )
            if hk_result["status"] != "SUCCEEDED":
                hk_result = dict(hk_result)
                hk_result["lane"] = "HK_CONNECT"
                hk_result["status"] = "CANNOT_CONFIRM"
                hk_lane_degradations.append(hk_result)
        if selector is None:
            lane_result = {
                "status": "CANNOT_CONFIRM",
                "exit_code": 1,
                "stdout": "",
                "stderr": selector_error,
                "modules": ["ops.materialize_d1_review_lanes"],
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        else:
            lane_result = self._run(
                "ops.materialize_d1_review_lanes",
                [
                    "--trade-date", request.business_date,
                    "--target-date", request.target_date,
                    "--data-root", str(self.data_root),
                    "--preselection-input-root", str(self.preselection_input_root),
                    "--shared-data-root", str(self.shared_data_root),
                    "--shared-package-root", str(self.shared_package_root),
                    "--selector", str(selector),
                    *(
                        ["--stage-selection-root", str(self.stage_selection_root)]
                        if self.stage_selection_root is not None
                        else []
                    ),
                ],
            )
        optional_lane_degradation = None
        if lane_result["status"] != "SUCCEEDED":
            # The D-1 review lanes enrich the fupan/stage7 optional pools.  The
            # scheduled materializer already emits explicit CANNOT_CONFIRM
            # artifacts when those inputs are unavailable, so they must not
            # suppress the independently verified A v1.9.2 and HK 0.2 pools.
            optional_lane_degradation = {
                "status": "CANNOT_CONFIRM",
                "module": "ops.materialize_d1_review_lanes",
                "exit_code": lane_result["exit_code"],
                "stdout": lane_result["stdout"],
                "stderr": lane_result["stderr"],
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        arguments = [
            "--trade-date", request.target_date,
            "--signal-date", request.business_date,
            "--data-root", str(self.data_root),
            "--input-root", str(self.preselection_input_root),
            "--shared-data-root", str(self.shared_data_root),
            "--shared-package-root", str(self.shared_package_root),
        ]
        if selector is not None:
            arguments[6:6] = ["--selector", str(selector)]
        result = self._run("ops.materialize_scheduled_preselection", arguments)
        result["modules"] = modules
        result["a_selector_status"] = (
            "READY" if selector is not None and not a_lane_degradations else "CANNOT_CONFIRM"
        )
        result["hk_lane_status"] = (
            "SUCCEEDED"
            if hk_result["status"] == "SUCCEEDED" and not hk_lane_degradations
            else "CANNOT_CONFIRM"
        )
        if a_lane_degradations:
            result["a_lane_degradations"] = a_lane_degradations
        if hk_lane_degradations:
            result["hk_lane_degradations"] = hk_lane_degradations
        if optional_lane_degradation is not None:
            result["optional_d1_review_lane"] = optional_lane_degradation
        return result

    def _daily_materialize(self, request: DispatchRequest) -> dict[str, Any]:
        """Run the single 21:40 owner with explicit business/target dates."""
        module = "ops.daily_materialize"
        arguments = [
            "--data-root", str(self.data_root),
            "--business-date", request.business_date,
            "--target-date", request.target_date,
        ]
        if self.shared_data_root is not None:
            arguments.extend(["--shared-data-root", str(self.shared_data_root)])
        if self.selector_data_root is not None:
            arguments.extend(["--selector-data-root", str(self.selector_data_root)])
        if self.stage_selection_root is not None:
            arguments.extend(["--stage-selection-root", str(self.stage_selection_root)])
        result = self._run(module, arguments)
        result["modules"] = [module]
        return result

    @staticmethod
    def _decoded_stdout(result: dict[str, Any]) -> dict[str, Any]:
        try:
            value = json.loads(str(result.get("stdout") or ""))
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _safe_lane_status(payload: dict[str, Any]) -> str:
        """Reduce an evidence adapter result without converting gaps to READY."""
        statuses: list[str] = []
        lanes = payload.get("lanes")
        if isinstance(lanes, dict):
            statuses.extend(
                str(item.get("status") or "CANNOT_CONFIRM").upper()
                for item in lanes.values()
                if isinstance(item, dict)
            )
        direct = str(payload.get("status") or payload.get("overall_status") or "").upper()
        if direct:
            statuses.append(direct)
        if any(item in {"CANNOT_CONFIRM", "FAILED", "REJECTED", "FAIL"} for item in statuses):
            return "CANNOT_CONFIRM"
        if any(item in {"PARTIAL", "PARTIAL_WITH_ROWS", "EVIDENCE_GAP"} for item in statuses):
            return "PARTIAL"
        # An empty or malformed publisher envelope is not evidence of a ready
        # lane.  Keep it retryable/fail-closed rather than allowing a missing
        # producer receipt to become a successful scheduler ledger entry.
        return "CANNOT_CONFIRM"

    def _research_panel_runtime_evidence(
        self, request: DispatchRequest
    ) -> dict[str, Any]:
        """Publish A/H panel receipts after their independent daily producers.

        This workload only publishes lineage metadata.  It never invokes the
        A/H producer and never turns a missing receipt into a successful lane.
        """
        module = "ops.publish_research_panel_runtime_receipt"
        selector_root = self.selector_data_root or self.data_root / "selector"
        producer_root = Path(
            os.environ.get(
                "V35_RESEARCH_PANEL_RECEIPT_ROOT",
                str(self.data_root.parent / "research_panel_daily" / "receipts"),
            )
        )
        selector_pointer = Path(
            os.environ.get(
                "V35_SELECTOR_POINTER",
                str(selector_root / "data_layer_interface_current" / "CURRENT_SELECTOR_READY_PANEL.txt"),
            )
        )
        backtest_pointer = Path(
            os.environ.get(
                "V35_BACKTEST_POINTER",
                str(selector_root / "backtest_panel_interface_current" / "CURRENT_BACKTEST_BASE_PANEL.txt"),
            )
        )
        close_path = Path(
            os.environ.get(
                "V35_CLOSE_REVIEW_PATH",
                str(self.data_root / "close_reviews" / f"{request.business_date}.json"),
            )
        )
        close_receipt = Path(
            os.environ.get(
                "V35_CLOSE_REVIEW_RECEIPT",
                str(self.data_root / "receipts" / "close_reviews" / f"{request.business_date}.json"),
            )
        )
        result = self._run(
            module,
            [
                "--date", request.business_date,
                "--data-root", str(self.data_root),
                "--producer-receipt-root", str(producer_root),
                "--selector-pointer", str(selector_pointer),
                "--backtest-pointer", str(backtest_pointer),
                "--close-review-path", str(close_path),
                "--close-review-receipt", str(close_receipt),
            ],
        )
        payload = self._decoded_stdout(result)
        lane_status = self._safe_lane_status(payload)
        lanes = payload.get("lanes")
        a_status = (
            str(lanes.get("A", {}).get("status") or "CANNOT_CONFIRM").upper()
            if isinstance(lanes, dict) and isinstance(lanes.get("A"), dict)
            else "CANNOT_CONFIRM"
        )
        hk_status = (
            str(lanes.get("HK", {}).get("status") or "CANNOT_CONFIRM").upper()
            if isinstance(lanes, dict) and isinstance(lanes.get("HK"), dict)
            else "CANNOT_CONFIRM"
        )
        # The publisher's accepted semantic is exit 0 with a verified HK lane
        # and an A lane that may be READY or PARTIAL.  A non-zero publisher
        # exit, missing lanes, or CANNOT_CONFIRM must remain a retryable
        # failure so the five-minute catch-up can run after the source recovers.
        accepted = (
            result["status"] == "SUCCEEDED"
            and isinstance(lanes, dict)
            and a_status in {"READY", "PARTIAL"}
            and hk_status == "READY"
        )
        result.update(
            {
                "lane_status": lane_status,
                "evidence_status": lane_status,
                "modules": [module],
                "source_result": payload,
                "a_lane_status": a_status,
                "hk_lane_status": hk_status,
            }
        )
        if not accepted:
            result.update(
                {
                    "status": "FAILED",
                    "workload_id": "research_panel_runtime_evidence",
                    "failure_class": "UPSTREAM_NOT_READY",
                    "reason": "RESEARCH_PANEL_RUNTIME_EVIDENCE_NOT_READY",
                }
            )
            raise WorkloadExecutionError(result)
        result["status"] = "SUCCEEDED"
        return result

    def _research_panel_daily(
        self, request: DispatchRequest, *, lane: str
    ) -> dict[str, Any]:
        """Run the existing dated A/H producer with its exact plist arguments.

        The formal V3.5 research-panel LaunchAgent already proves this entry
        point and its authority-chain arguments.  The unified scheduler only
        reuses that command for one explicit lane at its canonical post-close
        slot; it does not create a second collector or infer missing inputs.
        Missing bindings are a typed configuration gap and remain retryable.
        """
        module = "ops.macos_research_panel_daily"
        names = (
            "V35_RESEARCH_PANEL_RECEIPT_ROOT",
            "V35_RESEARCH_PANEL_A_TDX_ROOT",
            "V35_RESEARCH_PANEL_HK_TDX_ROOT",
            "V35_RESEARCH_PANEL_A_SYNC_SCRIPT",
            "V35_RESEARCH_PANEL_A_FORMULA_SCRIPT",
            "V35_RESEARCH_PANEL_A_SEED_PANEL",
            "V35_RESEARCH_PANEL_A_DATA_ROOT",
            "V35_RESEARCH_PANEL_A_SELECTOR_POINTER",
            "V35_RESEARCH_PANEL_A_BACKTEST_POINTER",
            "V35_RESEARCH_PANEL_A_SELECTOR_SEED",
            "V35_RESEARCH_PANEL_A_BACKTEST_SEED",
            "V35_RESEARCH_PANEL_A_CONTRACT_CSV",
            "V35_RESEARCH_PANEL_A_CANONICAL_FORMULA",
            "V35_RESEARCH_PANEL_A_RETURN_ROOT",
            "V35_RESEARCH_PANEL_HK_UPDATER_SCRIPT",
            "V35_RESEARCH_PANEL_HK_PYTHON_EXECUTABLE",
            "V35_RESEARCH_PANEL_HK_ASSET_ROOT",
        )
        missing = [name for name in names if not str(os.environ.get(name) or "").strip()]
        if missing:
            failure = self._failure_result(
                "research_panel_daily_a" if lane == "A" else "research_panel_daily_hk",
                [module],
                "research panel producer bindings missing: " + ",".join(missing),
            )
            failure["failure_class"] = "CONFIGURATION_MISSING"
            raise WorkloadExecutionError(failure)
        env = {name: str(os.environ[name]) for name in names}
        arguments = [
            "--date", request.business_date,
            "--lane", lane,
            "--receipt-root", env["V35_RESEARCH_PANEL_RECEIPT_ROOT"],
            "--a-tdx-root", env["V35_RESEARCH_PANEL_A_TDX_ROOT"],
            "--hk-tdx-root", env["V35_RESEARCH_PANEL_HK_TDX_ROOT"],
            "--a-minimum-rows", "5000",
            "--a-sync-script", env["V35_RESEARCH_PANEL_A_SYNC_SCRIPT"],
            "--a-formula-script", env["V35_RESEARCH_PANEL_A_FORMULA_SCRIPT"],
            "--a-seed-panel", env["V35_RESEARCH_PANEL_A_SEED_PANEL"],
            "--a-data-root", env["V35_RESEARCH_PANEL_A_DATA_ROOT"],
            "--a-selector-pointer", env["V35_RESEARCH_PANEL_A_SELECTOR_POINTER"],
            "--a-backtest-pointer", env["V35_RESEARCH_PANEL_A_BACKTEST_POINTER"],
            "--a-selector-seed", env["V35_RESEARCH_PANEL_A_SELECTOR_SEED"],
            "--a-backtest-seed", env["V35_RESEARCH_PANEL_A_BACKTEST_SEED"],
            "--a-contract-csv", env["V35_RESEARCH_PANEL_A_CONTRACT_CSV"],
            "--a-canonical-formula", env["V35_RESEARCH_PANEL_A_CANONICAL_FORMULA"],
            "--a-return-root", env["V35_RESEARCH_PANEL_A_RETURN_ROOT"],
            "--hk-updater-script", env["V35_RESEARCH_PANEL_HK_UPDATER_SCRIPT"],
            "--hk-python-executable", env["V35_RESEARCH_PANEL_HK_PYTHON_EXECUTABLE"],
            "--hk-asset-root", env["V35_RESEARCH_PANEL_HK_ASSET_ROOT"],
        ]
        result = self._run(module, arguments)
        payload = self._decoded_stdout(result)
        lanes = payload.get("lanes")
        lane_payload = lanes.get(lane) if isinstance(lanes, dict) else None
        lane_status = (
            str(lane_payload.get("status") or "CANNOT_CONFIRM").upper()
            if isinstance(lane_payload, dict)
            else "CANNOT_CONFIRM"
        )
        result.update(
            {
                "lane": lane,
                "lane_status": lane_status,
                "target_date": request.business_date,
                "modules": [module],
                "source_result": payload,
            }
        )
        if result["status"] != "SUCCEEDED" or lane_status != "READY":
            result.update(
                {
                    "status": "FAILED",
                    "workload_id": "research_panel_daily_a" if lane == "A" else "research_panel_daily_hk",
                    "failure_class": "UPSTREAM_NOT_READY",
                    "reason": "RESEARCH_PANEL_DAILY_LANE_NOT_READY",
                }
            )
            raise WorkloadExecutionError(result)
        return result

    def _wechat_preselection_sync(self, request: DispatchRequest) -> dict[str, Any]:
        """Sync the exact pair; missing source is CANNOT_CONFIRM + retryable."""
        module = "ops.wechat_preselection_sync"
        # The canonical future producer boundary is the V3.5 input lane.  The
        # historical 20260821 pair under ``preselection_pools`` was a one-time
        # canary/evidence source and is never a natural-production fallback.
        configured_root = self.preselection_input_root
        if configured_root is None:
            configured_root = os.environ.get("V35_WECHAT_INPUT_ROOT")
        input_root = Path(
            configured_root
            if configured_root is not None
            else self.data_root / "preselection_inputs"
        )
        canonical_input_root = self.data_root / "preselection_inputs"
        try:
            input_root.resolve().relative_to(canonical_input_root.resolve())
        except (OSError, ValueError) as error:
            failure = self._failure_result(
                "wechat_preselection_sync",
                [module],
                "WeChat input root must remain under data_root/preselection_inputs; historical preselection_pools is evidence-only",
            )
            failure["failure_class"] = "CONTRACT"
            raise WorkloadExecutionError(
                failure
            ) from error
        receipt = self.data_root / "receipts" / "wechat_preselection" / f"{request.target_date}.json"
        result = self._run(
            module,
            [
                "--effective-date", request.target_date,
                "--input-root", str(input_root),
                "--data-root", str(self.data_root),
                "--receipt", str(receipt),
            ],
        )
        payload = self._decoded_stdout(result)
        status = str(payload.get("status") or "").upper()
        result.update(
            {
                "lane_status": status or "CANNOT_CONFIRM",
                "target_date": request.target_date,
                "modules": [module],
                "source_result": payload,
            }
        )
        # This is a consumer-side sync of an already verified exact pair.  It
        # is successful only when the child exits 0 and reports READY.  A
        # missing/partial pair is a retryable upstream gap, not a terminal
        # CANNOT_CONFIRM success that would block later catch-up.
        if result["status"] != "SUCCEEDED" or status != "READY":
            result.update(
                {
                    "status": "FAILED",
                    "workload_id": "wechat_preselection_sync",
                    "failure_class": "UPSTREAM_NOT_READY",
                    "reason": "WECHAT_EXACT_DATE_INPUT_NOT_READY",
                }
            )
            raise WorkloadExecutionError(result)
        result["status"] = "SUCCEEDED"
        return result

    def _review_core_pool_pipeline(self, request: DispatchRequest) -> dict[str, Any]:
        """Run the verified natural Review Core adapter at the 21:15 slot."""
        module = "ops.run_review_core_natural_pool_pipeline"
        package_root = Path(
            os.environ.get("V35_REVIEW_CORE_PACKAGE_ROOT", str(self.data_root / "review_core"))
        )
        shared_package_root = Path(
            os.environ.get(
                "V35_REVIEW_CORE_SHARED_PACKAGE_ROOT",
                str(self.shared_package_root or self.data_root / "shared_package"),
            )
        )
        shared_store_root = Path(
            os.environ.get(
                "V35_REVIEW_CORE_SHARED_STORE_ROOT",
                str(self.shared_data_root or self.data_root / "shared_store"),
            )
        )
        runtime_root = Path(os.environ.get("V35_REVIEW_CORE_RUNTIME_ROOT", str(self.data_root)))
        calendar_path = Path(
            os.environ.get(
                "V35_REVIEW_CORE_CALENDAR_PATH",
                str((self.repo_root or Path(__file__).resolve().parents[2]) / "contracts" / "market_calendar_2026.json"),
            )
        )
        hk_root = Path(
            os.environ.get("V35_REVIEW_CORE_HK_ROOT", str(self.hk_universe_root or self.data_root / "hk"))
        )
        close_root = Path(os.environ.get("V35_REVIEW_CORE_CLOSE_ROOT", str(self.data_root / "close_reviews")))
        fupan_root = Path(
            os.environ.get("V35_REVIEW_CORE_FUPAN_STORE_ROOT", str(self.data_root / "fupan_store"))
        )
        stage7_root = Path(
            os.environ.get("V35_REVIEW_CORE_STAGE7_STORE_ROOT", str(self.data_root / "stage7_store"))
        )
        bundle_root = Path(
            os.environ.get("V35_REVIEW_CORE_BUNDLE_ROOT", str(self.data_root / "review_bundle"))
        )
        # The released reader appends review_bundle/<date>/current.json.
        # Older scheduler bindings named that child instead of its runtime.
        # Correct only that exact known relationship; independent roots stay
        # explicit and must not be redirected by a matching directory name.
        if bundle_root == runtime_root / "review_bundle":
            bundle_root = runtime_root
        result = self._run(
            module,
            [
                "--trade-date", request.business_date,
                "--target-date", request.target_date,
                "--calendar-path", str(calendar_path),
                "--review-core-package-root", str(package_root),
                "--shared-package-root", str(shared_package_root),
                "--shared-store-root", str(shared_store_root),
                "--runtime-root", str(runtime_root),
                "--hk-root", str(hk_root),
                "--close-root", str(close_root),
                "--fupan-store-root", str(fupan_root),
                "--stage7-store-root", str(stage7_root),
                "--bundle-root", str(bundle_root),
            ],
        )
        payload = self._decoded_stdout(result)
        pipeline_status = str(payload.get("status") or payload.get("overall_status") or "CANNOT_CONFIRM").upper()
        result.update(
            {
                "pipeline_status": pipeline_status,
                "target_date": request.target_date,
                "modules": [module],
                "source_result": payload,
            }
        )
        # ReviewCore is the independent 21:15 owner.  PARTIAL, EVIDENCE_GAP,
        # and CANNOT_CONFIRM are preserved as evidence but remain retryable;
        # only an exit-0 READY envelope may close this scheduler slot.
        if result["status"] != "SUCCEEDED" or pipeline_status != "READY":
            result.update(
                {
                    "status": "FAILED",
                    "workload_id": "review_core_pool_pipeline",
                    "failure_class": "UPSTREAM_NOT_READY",
                    "reason": "REVIEW_CORE_POOL_PIPELINE_NOT_READY",
                }
            )
            raise WorkloadExecutionError(result)
        result["status"] = "SUCCEEDED"
        return result

    def _run_stage_center_milestone(
        self, workload: WorkloadDefinition, request: DispatchRequest
    ) -> dict[str, Any]:
        if self.stage_selection_root is None:
            raise WorkloadExecutionError(
                self._failure_result(
                    workload.workload_id,
                    ["ops.run_stage_center_milestone"],
                    "stage selection root not configured",
                )
            )
        node, stage_id, _market = MILESTONE_BY_WORKLOAD[workload.workload_id]
        result = self._run(
            "ops.run_stage_center_milestone",
            [
                "--node", node,
                "--data-root", str(self.data_root),
                "--date", request.business_date,
                "--stage-id", stage_id,
                "--selection-root", str(self.stage_selection_root),
            ],
        )
        result["modules"] = ["ops.run_stage_center_milestone"]
        return result

    def _run_close_review_node(
        self, workload: WorkloadDefinition, request: DispatchRequest
    ) -> dict[str, Any]:
        node = CLOSE_NODE_BY_WORKLOAD[workload.workload_id]
        arguments = [
            "--node", node,
            "--data-root", str(self.data_root),
            "--business-date", request.business_date,
        ]
        if self.selector_data_root is not None:
            arguments.extend(["--selector-data-root", str(self.selector_data_root)])
        result = self._run("ops.run_v35_close_review_slot", arguments)
        result["modules"] = ["ops.run_v35_close_review_slot"]
        return result

    def _a_share_close_review(
        self, request: DispatchRequest
    ) -> dict[str, Any]:
        if self.selector_data_root is None:
            raise WorkloadExecutionError(
                self._failure_result(
                    "a_share_close_review",
                    ["ops.build_a_share_close_review"],
                    "selector data root not configured",
                )
            )
        try:
            panel = resolve_selector_panel(
                self.selector_data_root, request.business_date
            )
        except FileNotFoundError as error:
            raise WorkloadExecutionError(
                self._failure_result(
                    "a_share_close_review",
                    ["ops.build_a_share_close_review"],
                    f"selector panel unresolved: {error}",
                )
            ) from error
        pointer_dir = self.data_root / ".dispatcher_tmp"
        pointer_dir.mkdir(parents=True, exist_ok=True)
        pointer = pointer_dir / "selector_panel_pointer.txt"
        pointer.write_text(str(panel), encoding="utf-8")
        return self._run(
            "ops.build_a_share_close_review",
            [
                "--data-root", str(self.data_root),
                "--date", request.business_date,
                "--panel-pointer", str(pointer),
            ],
        )

    def _hk_connect_close_review(
        self, request: DispatchRequest
    ) -> dict[str, Any]:
        collector_module = "ops.collect_hkconnect_close_snapshot"
        builder_module = "ops.build_close_review"
        modules = [collector_module, builder_module]
        if self.stage_selection_root is None:
            raise WorkloadExecutionError(
                self._failure_result(
                    "hk_connect_close_review",
                    modules,
                    "stage selection root not configured",
                )
            )
        elapsed_wait = 0
        attempts = 0
        while True:
            attempts += 1
            collector = self._run(
                collector_module,
                [
                    "--data-root", str(self.data_root),
                    "--date", request.business_date,
                ],
            )
            collector["attempts"] = attempts
            collector["slept_seconds"] = elapsed_wait
            if collector["status"] == "SUCCEEDED":
                break

            combined_output = "\n".join(
                str(collector.get(field) or "") for field in ("stdout", "stderr")
            )
            retryable = collector["status"] == "TIMEOUT" or (
                collector["status"] == "FAILED"
                and _HK_CLOSE_CUTOFF_ERROR_PREFIX in combined_output
            )
            if not retryable or elapsed_wait >= _HK_CLOSE_MAX_WAIT_SECONDS:
                collector["workload_id"] = "hk_connect_close_review"
                collector["modules"] = modules
                raise WorkloadExecutionError(collector)

            sleep_seconds = min(
                _HK_CLOSE_RETRY_INTERVAL_SECONDS,
                _HK_CLOSE_MAX_WAIT_SECONDS - elapsed_wait,
            )
            self._sleeper(sleep_seconds)
            elapsed_wait += sleep_seconds

        builder_arguments = [
            "--data-root", str(self.data_root),
            "--date", request.business_date,
            "--stage-selection-root", str(self.stage_selection_root),
        ]
        builder = self._run(builder_module, builder_arguments)
        builder["workload_id"] = "hk_connect_close_review"
        builder["modules"] = modules
        builder["attempts"] = attempts
        builder["slept_seconds"] = elapsed_wait
        if builder["status"] != "SUCCEEDED":
            raise WorkloadExecutionError(builder)
        return builder

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

    def __call__(
        self,
        workload: WorkloadDefinition,
        request: DispatchRequest,
        decision: Any = None,
    ) -> dict[str, Any]:
        if workload.workload_id not in ALLOWED_WORKLOAD_IDS:
            raise ValueError(f"unknown workload_id: {workload.workload_id}")
        if workload.workload_id in MILESTONE_BY_WORKLOAD:
            result = self._run_stage_center_milestone(workload, request)
        elif workload.workload_id in CLOSE_NODE_BY_WORKLOAD:
            result = self._run_close_review_node(workload, request)
        else:
            handler = {
                "hourly_research": self._hourly_research,
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
                "research_panel_daily_a": lambda request: self._research_panel_daily(request, lane="A"),
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


__all__ = [
    "ALLOWED_WORKLOAD_IDS",
    "FixedExecutorRegistry",
    "WorkloadExecutionError",
]
