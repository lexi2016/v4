"""Fixed Python executor registry for the V3.5 runtime dispatcher.

The registry selects a whitelisted Python module and a fixed argument list per
``workload_id``.  It never reads ``WorkloadDefinition.command``: the catalog
command remains an audit/oracle field only.  Business inputs come exclusively
from the V3.5/shared-owned roots passed at construction; when an input is
absent the module fails closed and the registry raises a structured failure.
"""
from __future__ import annotations

import hashlib
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
from infrastructure.owned_io import SafeRoot
from infrastructure.formula_generation import FormulaGenerationError, read_formula_generation
from infrastructure.isolated_package_loader import load_isolated_package_module

ALLOWED_WORKLOAD_IDS = frozenset(
    {
        "hourly_research",
        "us_market_digest",
        "v4_intraday_research",
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
    from infrastructure.scheduling._executor_registry_parts.degradation import __audited_peripheral_degradation_body as _v4_impl
    return _v4_impl(globals(), result, data_root=data_root, trade_date=trade_date)


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
    from infrastructure.scheduling._executor_registry_parts.degradation import __audited_peripheral_timeout_reuse_body as _v4_impl
    return _v4_impl(globals(), data_root=data_root, trade_date=trade_date)


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
    from infrastructure.scheduling._executor_registry_parts.degradation import __collector_not_materialized_result_body as _v4_impl
    return _v4_impl(globals(), collected, workload_id=workload_id, modules=modules, collector_payload=collector_payload)


def _default_runner(
    command: list[str],
    *,
    cwd: Path | None,
    timeout_seconds: int,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    from infrastructure.scheduling._executor_registry_parts.process_boundary import __default_runner_body as _v4_impl
    return _v4_impl(globals(), command, cwd=cwd, timeout_seconds=timeout_seconds, env=env)


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

    def _hk_0_2_runtime_error(self, executable: Path | str | None = None) -> str | None:
        """Validate an explicitly selected HK 0.2 interpreter in isolation.

        This probe is deliberately scoped to the HK lane.  A direct scheduler
        or slot invocation may bypass the shell launcher, so ``is_file`` alone
        is not enough: an existing Python 3.14 executable must be rejected
        before any HK producer is started.  The caller records the result as a
        lane-local ``CANNOT_CONFIRM`` degradation and continues sibling work.
        """
        from infrastructure.scheduling._executor_registry_parts.process_boundary import _FixedExecutorRegistry__hk_0_2_runtime_error_body as _v4_impl
        return _v4_impl(globals(), self, executable)

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
        from infrastructure.scheduling._executor_registry_parts.process_boundary import _FixedExecutorRegistry__run_body as _v4_impl
        return _v4_impl(globals(), self, module, arguments, cwd=cwd, env=env, python_executable=python_executable, timeout_seconds=timeout_seconds)

    def _classify_intraday_failure(self, result: dict[str, Any]) -> dict[str, Any]:
        """Keep the child's request boundary visible to scheduler retry logic."""
        from infrastructure.scheduling._executor_registry_parts.intraday_jobs import _FixedExecutorRegistry__classify_intraday_failure_body as _v4_impl
        return _v4_impl(globals(), self, result)

    def _intraday_research(self, request: DispatchRequest) -> dict[str, Any]:
        """The existing scheduler's single replacement for Vibe six-slot capture."""
        from infrastructure.scheduling._executor_registry_parts.intraday_jobs import _FixedExecutorRegistry__intraday_research_body as _v4_impl
        return _v4_impl(globals(), self, request)

    def _hourly_research(self, request: DispatchRequest) -> dict[str, Any]:
        from infrastructure.scheduling._executor_registry_parts.research_jobs import _FixedExecutorRegistry__hourly_research_body as _v4_impl
        return _v4_impl(globals(), self, request)

    def _hourly_research_materials(
        self, request: DispatchRequest
    ) -> dict[str, Any]:
        from infrastructure.scheduling._executor_registry_parts.research_materials import _FixedExecutorRegistry__hourly_research_materials_body as _v4_impl
        return _v4_impl(globals(), self, request)

    def _zsxq_0830(self, request: DispatchRequest) -> dict[str, Any]:
        from infrastructure.scheduling._executor_registry_parts.research_jobs import _FixedExecutorRegistry__zsxq_0830_body as _v4_impl
        return _v4_impl(globals(), self, request)

    def _morning_news_0830(self, request: DispatchRequest) -> dict[str, Any]:
        from infrastructure.scheduling._executor_registry_parts.research_jobs import _FixedExecutorRegistry__morning_news_0830_body as _v4_impl
        return _v4_impl(globals(), self, request)

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
        from infrastructure.scheduling._executor_registry_parts.stage_jobs import _FixedExecutorRegistry__stage_workbench_body as _v4_impl
        return _v4_impl(globals(), self, request)

    def _hk_auction_0920(self, request: DispatchRequest) -> dict[str, Any]:
        """Run the single-owner shared capture plus V3.5 materialization bridge."""
        from infrastructure.scheduling._executor_registry_parts.stage_jobs import _FixedExecutorRegistry__hk_auction_0920_body as _v4_impl
        return _v4_impl(globals(), self, request)


    def _verified_preselection_source(
        self,
        *,
        module_leaf: str,
        reader_name: str,
        target_date: str,
        signal_date: str,
    ) -> tuple[dict[str, Any] | None, str]:
        """Read an exact V4 shared source before deciding to run its producer."""
        from infrastructure.scheduling._executor_registry_parts.preselection import _FixedExecutorRegistry__verified_preselection_source_body as _v4_impl
        return _v4_impl(globals(), self, module_leaf=module_leaf, reader_name=reader_name, target_date=target_date, signal_date=signal_date)

    def _preselection_pools(
        self, request: DispatchRequest
    ) -> dict[str, Any]:
        from infrastructure.scheduling._executor_registry_parts.preselection import _FixedExecutorRegistry__preselection_pools_body as _v4_impl
        return _v4_impl(globals(), self, request)

    def _daily_materialize(self, request: DispatchRequest) -> dict[str, Any]:
        """Run the single 21:40 owner with explicit business/target dates."""
        from infrastructure.scheduling._executor_registry_parts.daily_reader import _FixedExecutorRegistry__daily_materialize_body as _v4_impl
        return _v4_impl(globals(), self, request)

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
        from infrastructure.scheduling._executor_registry_parts.research_jobs import _FixedExecutorRegistry__safe_lane_status_body as _v4_impl
        return _v4_impl(globals(), payload)

    def _research_panel_runtime_evidence(
        self, request: DispatchRequest
    ) -> dict[str, Any]:
        """Publish A/H panel receipts after their independent daily producers.

        This workload only publishes lineage metadata.  It never invokes the
        A/H producer and never turns a missing receipt into a successful lane.
        """
        from infrastructure.scheduling._executor_registry_parts.panel_evidence import _FixedExecutorRegistry__research_panel_runtime_evidence_body as _v4_impl
        return _v4_impl(globals(), self, request)

    def _research_panel_daily(
        self, request: DispatchRequest, *, lane: str
    ) -> dict[str, Any]:
        """Reuse the single public producer; require exact bound disk evidence.

        Config is lane-local. stdout is only a compact envelope, never the full
        upstream artifact, and cannot grant READY without its dated receipt.
        """
        from infrastructure.scheduling._executor_registry_parts.panel_execution import _FixedExecutorRegistry__research_panel_daily_body as _v4_impl
        return _v4_impl(globals(), self, request, lane=lane)

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
        from infrastructure.scheduling._executor_registry_parts.close_review import _FixedExecutorRegistry__review_core_pool_pipeline_body as _v4_impl
        return _v4_impl(globals(), self, request)

    def _run_stage_center_milestone(
        self, workload: WorkloadDefinition, request: DispatchRequest
    ) -> dict[str, Any]:
        from infrastructure.scheduling._executor_registry_parts.stage_jobs import _FixedExecutorRegistry__run_stage_center_milestone_body as _v4_impl
        return _v4_impl(globals(), self, workload, request)

    def _run_close_review_node(
        self, workload: WorkloadDefinition, request: DispatchRequest
    ) -> dict[str, Any]:
        from infrastructure.scheduling._executor_registry_parts.research_jobs import _FixedExecutorRegistry__run_close_review_node_body as _v4_impl
        return _v4_impl(globals(), self, workload, request)

    def _a_share_close_review(
        self, request: DispatchRequest
    ) -> dict[str, Any]:
        from infrastructure.scheduling._executor_registry_parts.close_review import _FixedExecutorRegistry__a_share_close_review_body as _v4_impl
        return _v4_impl(globals(), self, request)

    def _hk_connect_close_review(
        self, request: DispatchRequest
    ) -> dict[str, Any]:
        from infrastructure.scheduling._executor_registry_parts.close_review import _FixedExecutorRegistry__hk_connect_close_review_body as _v4_impl
        return _v4_impl(globals(), self, request)

    def _failure_result(
        self,
        workload_id: str,
        modules: list[str],
        message: str,
    ) -> dict[str, Any]:
        from infrastructure.scheduling._executor_registry_parts.research_jobs import _FixedExecutorRegistry__failure_result_body as _v4_impl
        return _v4_impl(globals(), self, workload_id, modules, message)

    def _us_market_digest(
        self, request: DispatchRequest
    ) -> dict[str, Any]:
        """Run only the seasonal US capture slot that is due now.

            Both DST variants are present in the catalog so launchd can remain a
            fixed-slot scheduler.  The explicit timezone resolver selects one
            active five-minute window; the other variant is a successful no-op and
            therefore cannot overwrite a same-session phase.
            """
        from infrastructure.scheduling._executor_registry_parts.us_digest import _FixedExecutorRegistry__us_market_digest_body as _v4_impl
        return _v4_impl(globals(), self, request)

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
                "us_market_digest": self._us_market_digest,
                "v4_intraday_research": self._intraday_research,
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
