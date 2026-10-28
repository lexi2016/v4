"""infrastructure.scheduling.executor_registry: panel_evidence (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _FixedExecutorRegistry__research_panel_runtime_evidence_body(_v4_scope, /, self, request):
    """Publish A/H panel receipts after their independent daily producers.

        This workload only publishes lineage metadata.  It never invokes the
        A/H producer and never turns a missing receipt into a successful lane.
        """
    module = "ops.publish_research_panel_runtime_receipt"
    selector_root = self.selector_data_root or self.data_root / "selector"
    producer_root = _v4_global(_v4_scope, 'Path')(
        _v4_global(_v4_scope, 'os').environ.get(
            "V35_RESEARCH_PANEL_RECEIPT_ROOT",
            _v4_global(_v4_scope, 'str')(self.data_root.parent / "research_panel_daily" / "receipts"),
        )
    )
    a_producer_root = _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'os').environ.get("V35_RESEARCH_PANEL_A_RECEIPT_ROOT") or "").strip()
    selector_pointer = _v4_global(_v4_scope, 'Path')(
        _v4_global(_v4_scope, 'os').environ.get(
            "V35_SELECTOR_POINTER",
            _v4_global(_v4_scope, 'str')(selector_root / "data_layer_interface_current" / "CURRENT_SELECTOR_READY_PANEL.txt"),
        )
    )
    backtest_pointer = _v4_global(_v4_scope, 'Path')(
        _v4_global(_v4_scope, 'os').environ.get(
            "V35_BACKTEST_POINTER",
            _v4_global(_v4_scope, 'str')(selector_root / "backtest_panel_interface_current" / "CURRENT_BACKTEST_BASE_PANEL.txt"),
        )
    )
    close_path = _v4_global(_v4_scope, 'Path')(
        _v4_global(_v4_scope, 'os').environ.get(
            "V35_CLOSE_REVIEW_PATH",
            _v4_global(_v4_scope, 'str')(self.data_root / "close_reviews" / f"{request.business_date}.json"),
        )
    )
    close_receipt = _v4_global(_v4_scope, 'Path')(
        _v4_global(_v4_scope, 'os').environ.get(
            "V35_CLOSE_REVIEW_RECEIPT",
            _v4_global(_v4_scope, 'str')(self.data_root / "receipts" / "close_reviews" / f"{request.business_date}.json"),
        )
    )
    generation_pointer = _v4_global(_v4_scope, 'str')(
        _v4_global(_v4_scope, 'os').environ.get("V35_RESEARCH_PANEL_A_FORMULA_GENERATION_POINTER") or ""
    ).strip()
    result = self._run(
        module,
        [
            "--date", request.business_date,
            "--data-root", _v4_global(_v4_scope, 'str')(self.data_root),
            "--producer-receipt-root", _v4_global(_v4_scope, 'str')(producer_root),
            *( ["--a-producer-receipt-root", a_producer_root] if a_producer_root else [] ),
            "--selector-pointer", _v4_global(_v4_scope, 'str')(selector_pointer),
            "--backtest-pointer", _v4_global(_v4_scope, 'str')(backtest_pointer),
            "--close-review-path", _v4_global(_v4_scope, 'str')(close_path),
            "--close-review-receipt", _v4_global(_v4_scope, 'str')(close_receipt),
            *(["--formula-generation-pointer", generation_pointer] if generation_pointer else []),
        ],
    )
    payload = self._decoded_stdout(result)
    lane_status = self._safe_lane_status(payload)
    lanes = payload.get("lanes")
    a_status = (
        _v4_global(_v4_scope, 'str')(lanes.get("A", {}).get("status") or "CANNOT_CONFIRM").upper()
        if _v4_global(_v4_scope, 'isinstance')(lanes, _v4_global(_v4_scope, 'dict')) and _v4_global(_v4_scope, 'isinstance')(lanes.get("A"), _v4_global(_v4_scope, 'dict'))
        else "CANNOT_CONFIRM"
    )
    hk_status = (
        _v4_global(_v4_scope, 'str')(lanes.get("HK", {}).get("status") or "CANNOT_CONFIRM").upper()
        if _v4_global(_v4_scope, 'isinstance')(lanes, _v4_global(_v4_scope, 'dict')) and _v4_global(_v4_scope, 'isinstance')(lanes.get("HK"), _v4_global(_v4_scope, 'dict'))
        else "CANNOT_CONFIRM"
    )
    # The publisher's accepted semantic is exit 0 with a verified HK lane
    # and an A lane that may be READY or PARTIAL.  A non-zero publisher
    # exit, missing lanes, or CANNOT_CONFIRM must remain a retryable
    # failure so the five-minute catch-up can run after the source recovers.
    accepted = (
        result["status"] == "SUCCEEDED"
        and _v4_global(_v4_scope, 'isinstance')(lanes, _v4_global(_v4_scope, 'dict'))
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
        raise _v4_global(_v4_scope, 'WorkloadExecutionError')(result)
    result["status"] = "SUCCEEDED"
    return result
