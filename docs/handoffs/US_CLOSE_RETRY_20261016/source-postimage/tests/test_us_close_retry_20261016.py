from __future__ import annotations

import contextlib
import hashlib
import importlib
import io
import json
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from contracts.runtime_tasks import DispatchMode, DispatchRequest
from infrastructure.scheduling.catalog import load_workload_catalog
from infrastructure.scheduling.dispatcher import _RUNTIME_IDENTITY_FILES
from infrastructure.scheduling.execution_ledger import ExecutionLedger
from infrastructure.scheduling.executor_registry import FixedExecutorRegistry, WorkloadExecutionError
import infrastructure.scheduling.executor_registry as registry_module
from infrastructure.http_transport import FetchResult, ProxyAwareHTTPTransport
from infrastructure.research_peripheral_store import ResearchPeripheralStore
from v4.manager_workbench.inputs.us_universe import load_us_universe_contract


digest = importlib.import_module("ops.us_market_digest")
runner = importlib.import_module("ops.run_us_market_slot")
ROOT = Path(__file__).resolve().parents[1]


def _bind_release(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    universe_contract = load_us_universe_contract()
    assert universe_contract["version"] == "US_MAPPING_UNIVERSE_CONTRACT_V3"
    assert len(universe_contract["symbols"]) == 48
    config_path = tmp_path / "manager-workbench-v7.json"
    config_path.write_text(
        json.dumps({"source_bindings": {"us_universe_contract": universe_contract}}),
        encoding="utf-8",
    )
    entries = []
    for relative in _RUNTIME_IDENTITY_FILES:
        body = (ROOT / relative).read_bytes()
        entries.append(
            {
                "path": relative,
                "kind": "file",
                "size": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            }
        )
    canonical = lambda value: json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    manifest = canonical(
        {
            "schema_version": "v4.release_candidate.v1",
            "candidate": {"app_root": str(ROOT), "release_id": "US_CLOSE_RETRY_TEST"},
            "application_inventory": {
                "entries": entries,
                "entry_count": len(entries),
                "aggregate_sha256": hashlib.sha256(canonical(entries)).hexdigest(),
            },
        }
    )
    manifest_path = tmp_path / "release-manifest.json"
    manifest_path.write_bytes(manifest)
    for key, value in {
        "V35_APP_ROOT": str(ROOT),
        "V35_RELEASE_ID": "US_CLOSE_RETRY_TEST",
        "V35_RELEASE_MANIFEST_PATH": str(manifest_path),
        "V35_RELEASE_MANIFEST_SHA256": hashlib.sha256(manifest).hexdigest(),
        "V4_MANAGER_WORKBENCH_CONFIG_PATH": str(config_path),
    }.items():
        monkeypatch.setenv(key, value)


def test_manual_cli_receipt_separates_target_session_and_late_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    now = datetime.fromisoformat("2026-10-15T16:45:12-04:00")
    monkeypatch.setattr(digest, "_capture_now", lambda: now)
    monkeypatch.setattr(
        digest,
        "_late_post_close_capture_id",
        lambda session_date, captured_at: f"manual:{session_date}:{captured_at:%H%M%S}",
    )
    calls = []

    def materialize(**kwargs):
        calls.append(kwargs)
        captured_at = "2026-10-15T20:45:12Z"
        row = {
            "us_session_date": "20261015",
            "capture_phase": "POST_CLOSE",
            "capture_id": kwargs["capture_id"],
            "run_id": "capture-run-15",
            "captured_at": captured_at,
            "capture_origin": "ORIGINAL_TIME_CAPTURE",
            "original_time_capture": True,
            "capture_mode": "CONTROLLED_LATE_POST_CLOSE",
            "late": True,
            "rss_status": "READY_EMPTY",
            "quote_capture_status": "ATTEMPTED",
        }
        payload = {
            "trade_date": "20261016",
            "source": "external_finance",
            "status": "READY",
            "fetched_at": captured_at,
            "market_snapshot_status": "READY",
            "market_snapshot": {"status": "READY", "capture_session_date": "20261015"},
            "us_session_captures": [row],
            "capture_origin": "ORIGINAL_TIME_CAPTURE",
            "original_time_capture": True,
            "capture_mode": "CONTROLLED_LATE_POST_CLOSE",
            "late": True,
            "cannot_confirm": [],
        }
        return {
            "payload": payload,
            "payload_path": "research/peripherals/20261016/external_finance.json",
            "receipt_path": "receipts/research/peripherals/20261016/external_finance.json",
            "payload_sha256": "a" * 64,
            "reused": False,
            "replaced": True,
            "market_snapshot_status": "READY",
            "capture_id": kwargs["capture_id"],
        }

    monkeypatch.setattr(digest, "materialize_us_market_phase", materialize)
    rc = digest.main(
        [
            "--data-root", str(tmp_path / "data"),
            "--trade-date", "20261016",
            "--us-session-date", "20261015",
            "--capture-phase", "POST_CLOSE",
            "--allow-late-post-close",
            "--manual-late-recovery",
        ]
    )
    result = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert calls[0]["trade_date"] == "20261016"
    assert calls[0]["us_session_date"] == "20261015"
    assert calls[0]["allow_late_post_close"] is True
    assert result["status"] == "READY"
    assert result["recovery_mode"] == "MANUAL_LATE_RECOVERY"
    assert result["recovery_executed_at"] == "2026-10-15T20:45:12Z"
    assert result["source_session_date"] == "20261015"
    assert result["target_trade_date"] == "20261016"
    # Keep the existing producer/API identity; the separate late marker and
    # actual capture timestamp describe that this recovery ran after the slot.
    assert result["capture_capture_origin"] == "ORIGINAL_TIME_CAPTURE"
    assert result["capture_original_time"] is True
    assert result["late"] is True


def test_manual_late_recovery_flag_requires_explicit_late_close_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def unexpected_materialize(**kwargs):
        pytest.fail(f"manual recovery ran without required late close flags: {kwargs}")

    monkeypatch.setattr(digest, "materialize_us_market_phase", unexpected_materialize)
    rc = digest.main(
        [
            "--data-root", str(tmp_path / "data"),
            "--trade-date", "20261016",
            "--us-session-date", "20261015",
            "--capture-phase", "POST_CLOSE",
            "--manual-late-recovery",
        ]
    )
    result = json.loads(capsys.readouterr().out)

    assert rc == 2
    assert "US_MANUAL_LATE_RECOVERY_REQUIRES_POST_CLOSE_LATE_CAPTURE" in result["reason"]
    assert result["recovery_mode"] == "MANUAL_LATE_RECOVERY"
    assert result["source_session_date"] == "20261015"
    assert result["target_trade_date"] == "20261016"
    assert result["recovery_executed_at"] is None


@pytest.mark.parametrize(
    ("business_date", "primary_slot", "retry_slot", "session_date"),
    (
        ("20261016", "0415", "0515", "20261015"),
        ("20261103", "0515", "2100", "20261102"),
    ),
)
def test_failed_close_retries_once_on_inactive_seasonal_slot_and_preserves_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    business_date: str,
    primary_slot: str,
    retry_slot: str,
    session_date: str,
) -> None:
    _bind_release(tmp_path, monkeypatch)
    ledger = ExecutionLedger(tmp_path / "ledger")

    class Executor:
        def __init__(self) -> None:
            self.calls: list[tuple[str, bool]] = []

        def __call__(self, workload, request, decision):
            capture = digest.resolve_capture_for_shanghai_slot(
                request.business_date, request.slot
            )
            retry_context = getattr(self, "_us_market_retry_context", None)
            self.calls.append((request.slot, retry_context is not None))
            if retry_context is None:
                raise WorkloadExecutionError(
                    {
                        "status": "FAILED",
                        "failure_class": "UPSTREAM_NOT_READY",
                        "reason": "US_MARKET_CAPTURE_NOT_READY",
                        "modules": ["ops.us_market_digest"],
                        "capture_phase": capture["capture_phase"],
                        "us_session_date": capture["us_session_date"],
                        "production_allowed": False,
                        "buy_gate_updated": False,
                        "orders_sent": False,
                    }
                )
            assert request.slot == primary_slot
            assert retry_context["retry_slot"] == retry_slot
            assert request.business_date == business_date
            assert capture == {"capture_phase": "POST_CLOSE", "us_session_date": session_date}
            return {
                "status": "SUCCEEDED",
                "modules": ["ops.us_market_digest"],
                "capture_phase": "POST_CLOSE",
                "capture_slot": request.slot,
                "us_session_date": session_date,
                "artifact_trade_date": business_date,
                "capture_origin": "ORIGINAL_TIME_CAPTURE",
                "original_time_capture": True,
                "late": True,
                "capture_captured_at": "2026-10-15T20:16:00Z",
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }

    executor = Executor()
    first = runner.run_us_market_slot(
        data_root=tmp_path / "data",
        ledger_root=tmp_path / "ledger",
        slot=primary_slot,
        business_date=business_date,
        executor=executor,
        ledger=ledger,
    )
    assert first["status"] == "FAILED"
    original = next(
        row
        for row in ledger.list_receipts(business_date, mode="LIVE")
        if row["slot"] == primary_slot
    )
    assert original["failure_class"] == "UPSTREAM_NOT_READY"

    if business_date == "20261016":
        # In daylight time, 2100 is the real PRE_OPEN slot and cannot replace
        # it with a close retry.
        assert digest.resolve_capture_for_shanghai_slot(business_date, "2100")["capture_phase"] == "PRE_OPEN"
        assert runner._failed_close_retry_context(
            ledger=ledger, business_date=business_date, retry_slot="2100"
        ) is None
    else:
        # In standard time, 2200 is the real PRE_OPEN slot; 2100 remains the
        # inactive recovery opportunity.
        assert digest.resolve_capture_for_shanghai_slot(business_date, "2200")["capture_phase"] == "PRE_OPEN"
        assert runner._failed_close_retry_context(
            ledger=ledger, business_date=business_date, retry_slot="2200"
        ) is None

    recovered = runner.run_us_market_slot(
        data_root=tmp_path / "data",
        ledger_root=tmp_path / "ledger",
        slot=retry_slot,
        business_date=business_date,
        executor=executor,
        ledger=ledger,
    )
    assert recovered["status"] == "SUCCEEDED"
    assert recovered["close_retry"]["status"] == "ARMED"
    assert recovered["slot"] == retry_slot
    workload_result = recovered["workload_results"][0]
    assert workload_result["late_post_close_retry"] is True
    assert workload_result["retry_of_slot"] == primary_slot
    assert workload_result["retry_slot"] == retry_slot
    assert workload_result["capture_slot"] == primary_slot
    assert workload_result["late"] is True
    assert workload_result["retry_mode"] == "AUTOMATIC_LATE_RETRY"
    assert workload_result["retry_executed_at"] == "2026-10-15T20:16:00Z"
    assert workload_result["retry_source_session_date"] == session_date
    assert workload_result["retry_target_trade_date"] == business_date
    assert workload_result["retry_capture_origin"] == "ORIGINAL_TIME_CAPTURE"
    assert workload_result["retry_capture_original_time"] is True
    assert workload_result["retry_capture_late"] is True

    after = ledger.list_receipts(business_date, mode="LIVE")
    original_after = next(row for row in after if row["slot"] == primary_slot)
    retry_receipt = next(row for row in after if row["slot"] == retry_slot)
    assert (original_after["run_id"], original_after["ledger_sha256"]) == (
        original["run_id"], original["ledger_sha256"]
    )
    assert retry_receipt["status"] == "SUCCEEDED"
    assert retry_receipt["run_id"] != original["run_id"]
    assert ledger.verify_receipt_chain(business_date, mode="LIVE")[0] is True

    repeated = runner.run_us_market_slot(
        data_root=tmp_path / "data",
        ledger_root=tmp_path / "ledger",
        slot=retry_slot,
        business_date=business_date,
        executor=executor,
        ledger=ledger,
    )
    assert repeated["status"] == "CONCURRENCY_SKIPPED"
    assert len(executor.calls) == 2


def _seed_failed_primary_close(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ExecutionLedger:
    _bind_release(tmp_path, monkeypatch)
    ledger = ExecutionLedger(tmp_path / "ledger")

    class FailedExecutor:
        def __call__(self, workload, request, decision):
            capture = digest.resolve_capture_for_shanghai_slot(
                request.business_date, request.slot
            )
            raise WorkloadExecutionError(
                {
                    "status": "FAILED",
                    "failure_class": "UPSTREAM_NOT_READY",
                    "reason": "US_MARKET_CAPTURE_NOT_READY",
                    "modules": ["ops.us_market_digest"],
                    "capture_phase": capture["capture_phase"],
                    "us_session_date": capture["us_session_date"],
                    "production_allowed": False,
                    "buy_gate_updated": False,
                    "orders_sent": False,
                }
            )

    result = runner.run_us_market_slot(
        data_root=tmp_path / "data",
        ledger_root=tmp_path / "ledger",
        slot="0415",
        business_date="20261016",
        executor=FailedExecutor(),
        ledger=ledger,
    )
    assert result["status"] == "FAILED"
    return ledger


def test_close_retry_refuses_tampered_primary_receipt_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = _seed_failed_primary_close(tmp_path, monkeypatch)
    failed = next(
        row
        for row in ledger.list_receipts("20261016", mode="LIVE")
        if row["slot"] == "0415"
    )
    receipt_path = ledger.root / failed["receipt_path"]
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["reason"] = "tampered after failure"
    receipt_path.write_text(json.dumps(payload), encoding="utf-8")

    valid, problems = ledger.verify_receipt_chain("20261016", mode="LIVE")
    assert valid is False
    assert any("self hash mismatch" in problem for problem in problems)
    assert runner._failed_close_retry_context(
        ledger=ledger, business_date="20261016", retry_slot="0515"
    ) is None


def test_close_retry_refuses_preexisting_not_due_fallback_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bind_release(tmp_path, monkeypatch)
    ledger = ExecutionLedger(tmp_path / "ledger")

    class Executor:
        def __call__(self, workload, request, decision):
            if request.slot == "0515":
                return {
                    "status": "SUCCEEDED",
                    "exit_code": 0,
                    "modules": ["ops.us_market_digest"],
                    "capture_status": "NOT_DUE",
                    "production_allowed": False,
                    "buy_gate_updated": False,
                    "orders_sent": False,
                }
            capture = digest.resolve_capture_for_shanghai_slot(
                request.business_date, request.slot
            )
            raise WorkloadExecutionError(
                {
                    "status": "FAILED",
                    "failure_class": "UPSTREAM_NOT_READY",
                    "reason": "US_MARKET_CAPTURE_NOT_READY",
                    "modules": ["ops.us_market_digest"],
                    "capture_phase": capture["capture_phase"],
                    "us_session_date": capture["us_session_date"],
                    "production_allowed": False,
                    "buy_gate_updated": False,
                    "orders_sent": False,
                }
            )

    executor = Executor()
    fallback = runner.run_us_market_slot(
        data_root=tmp_path / "data",
        ledger_root=tmp_path / "ledger",
        slot="0515",
        business_date="20261016",
        executor=executor,
        ledger=ledger,
    )
    assert fallback["status"] == "SUCCEEDED"
    fallback_receipt = next(
        row
        for row in ledger.list_receipts("20261016", mode="LIVE")
        if row["slot"] == "0515"
    )
    assert fallback_receipt["workload_results"][0]["capture_status"] == "NOT_DUE"

    failed = runner.run_us_market_slot(
        data_root=tmp_path / "data",
        ledger_root=tmp_path / "ledger",
        slot="0415",
        business_date="20261016",
        executor=executor,
        ledger=ledger,
    )
    assert failed["status"] == "FAILED"
    assert runner._failed_close_retry_context(
        ledger=ledger, business_date="20261016", retry_slot="0515"
    ) is None


def test_executor_rejects_ready_snapshot_with_wrong_provider_session_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from infrastructure.data_store import _sha256

    session_date = "20261015"
    trade_date = "20261016"
    capture_id = "post-close-20261015"
    run_id = "capture-run-20261015"
    captured_at = "2026-10-15T20:15:00Z"
    stored = {
        "trade_date": trade_date,
        "source": "external_finance",
        "status": "READY",
        "item_count": 0,
        "market_snapshot_status": "READY",
        "market_snapshot": {
            "status": "READY",
            "capture_phase": "POST_CLOSE",
            "capture_session_date": session_date,
            "provider_session_dates": ["20261014"],
        },
        "us_session_captures": [
            {
                "us_session_date": session_date,
                "capture_phase": "POST_CLOSE",
                "capture_id": capture_id,
                "run_id": run_id,
                "captured_at": captured_at,
                "capture_origin": "ORIGINAL_TIME_CAPTURE",
                "original_time_capture": True,
            }
        ],
        "cannot_confirm": [],
    }
    payload_sha256 = _sha256(stored)
    expected_payload_path = f"research/peripherals/{trade_date}/external_finance.json"
    expected_receipt_path = f"receipts/research/peripherals/{trade_date}/external_finance.json"

    class FakeStore:
        def __init__(self, _root):
            pass

        def read_exact(self, date, source):
            assert date == trade_date
            assert source == "external_finance"
            return stored

        @staticmethod
        def _receipt(_payload, digest_value):
            return {"payload_sha256": digest_value}

        @staticmethod
        def _relative(date, source):
            assert (date, source) == (trade_date, "external_finance")
            return expected_payload_path

        @staticmethod
        def _receipt_relative(date, source):
            assert (date, source) == (trade_date, "external_finance")
            return expected_receipt_path

    monkeypatch.setattr(registry_module, "ResearchPeripheralStore", FakeStore)

    cli_result = {
        "status": "READY",
        "trade_date": trade_date,
        "source": "external_finance",
        "payload_path": expected_payload_path,
        "receipt_path": expected_receipt_path,
        "payload_sha256": payload_sha256,
        "reused": True,
        "replaced": False,
        "capture_us_session_date": session_date,
        "capture_phase": "POST_CLOSE",
        "capture_id": capture_id,
        "capture_run_id": run_id,
        "capture_captured_at": captured_at,
        "capture_capture_origin": "ORIGINAL_TIME_CAPTURE",
        "capture_original_time": True,
        "market_snapshot_status": "READY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }

    def process(command, *, cwd, timeout_seconds, env):
        assert command[command.index("--trade-date") + 1] == trade_date
        assert command[command.index("--us-session-date") + 1] == session_date
        return subprocess.CompletedProcess(
            command, 0, json.dumps(cli_result), ""
        )

    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data", repo_root=ROOT, runner=process
    )
    request = DispatchRequest(
        scheduled_date=trade_date,
        business_date=trade_date,
        target_date=trade_date,
        slot="0415",
        mode=DispatchMode.LIVE,
    )

    with pytest.raises(WorkloadExecutionError) as error:
        registry._us_market_digest(request)
    assert error.value.result["failure_class"] == "CONTRACT"
    assert error.value.result["reason"] == "US_CAPTURE_EVIDENCE_INVALID"


def test_registry_publishes_to_business_date_with_prior_us_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bind_release(tmp_path, monkeypatch)
    stamp = "2026-10-15T16:15:00-04:00"

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            frozen = cls.fromisoformat(stamp)
            return frozen.astimezone(tz) if tz is not None else frozen.replace(tzinfo=None)

    monkeypatch.setattr(digest, "datetime", FrozenDateTime)
    contract = digest._configured_us_universe_contract()
    symbols = list(contract["symbols"])
    quote_response_sha256 = {}
    calls = []

    def fetch(self, url, *, timeout=None, **kwargs):
        calls.append(url)
        if "qt.gtimg.cn" in url:
            records = []
            for symbol in symbols:
                fields = [""] * 31
                fields[1:5] = [symbol, symbol, "110", "100"]
                fields[30] = "20261015160001"
                records.append(f'v_us{symbol}="' + "~".join(fields) + '";')
            body = "".join(records).encode()
            quote_response_sha256["value"] = hashlib.sha256(body).hexdigest()
        else:
            key = hashlib.sha256(url.encode()).hexdigest()[:12]
            body = (
                f"<rss><channel><item><title>US close test {key}</title>"
                f"<link>https://example.test/news/{key}</link>"
                "<pubDate>Thu, 15 Oct 2026 20:00:00 GMT</pubDate>"
                "<source>synthetic test</source></item></channel></rss>"
            ).encode()
        return FetchResult(
            body,
            {
                "status": "READY",
                "source": "SYNTHETIC_TRANSPORT",
                "source_url": url,
                "response_sha256": hashlib.sha256(body).hexdigest(),
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            },
        )

    monkeypatch.setattr(ProxyAwareHTTPTransport, "fetch", fetch)

    def process(command, *, cwd, timeout_seconds, env):
        assert command[1:3] == ["-m", "ops.us_market_digest"]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = digest.main(command[3:])
        return subprocess.CompletedProcess(command, rc, out.getvalue(), err.getvalue())

    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data", repo_root=ROOT, runner=process
    )
    request = DispatchRequest(
        scheduled_date="20261016",
        business_date="20261016",
        target_date="20261016",
        slot="0415",
        mode=DispatchMode.LIVE,
    )
    workload = next(
        item
        for item in load_workload_catalog().workloads
        if item.workload_id == "us_market_digest"
    )

    try:
        result = registry(workload, request)
    except WorkloadExecutionError as error:
        pytest.fail(f"registry failed: {error.result.get('reason')}; {error.result.get('stdout')}")
    store = ResearchPeripheralStore(tmp_path / "data")
    payload = store.read_exact("20261016", "external_finance")

    assert result["status"] == "SUCCEEDED", result
    assert result["us_session_date"] == "20261015"
    assert result["artifact_trade_date"] == "20261016"
    assert payload is not None
    assert payload["trade_date"] == "20261016"
    assert payload["market_snapshot_status"] == "READY"
    assert payload["market_snapshot"]["capture_session_date"] == "20261015"
    assert payload["market_snapshot"]["provider_session_dates"] == ["20261015"]
    assert payload["market_snapshot"]["universe_contract"] == contract
    assert payload["market_snapshot"]["universe_contract"]["version"] == "US_MAPPING_UNIVERSE_CONTRACT_V3"
    assert payload["market_snapshot"]["requested_symbol_count"] == 48
    assert payload["market_snapshot"]["available_symbol_count"] == 48
    assert len(payload["market_snapshot"]["quotes"]) == 48
    assert payload["market_snapshot"]["source_response_sha256"] == quote_response_sha256["value"]
    assert payload["market_snapshot"]["provider_receipt"]["response_sha256"] == quote_response_sha256["value"]
    assert store.read_exact("20261015", "external_finance") is None
    assert calls


@pytest.mark.parametrize(
    ("business_date", "primary_slot", "retry_slot", "session_date", "primary_time", "retry_time", "stale_date"),
    (
        (
            "20261016", "0415", "0515", "20261015",
            "2026-10-15T16:15:00-04:00", "2026-10-15T17:15:00-04:00", "20261014",
        ),
        (
            "20261103", "0515", "2100", "20261102",
            "2026-11-02T16:15:00-05:00", "2026-11-03T08:00:00-05:00", "20261101",
        ),
    ),
)
def test_dispatcher_retries_with_real_cli_and_keeps_target_and_capture_dates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    business_date: str,
    primary_slot: str,
    retry_slot: str,
    session_date: str,
    primary_time: str,
    retry_time: str,
    stale_date: str,
) -> None:
    _bind_release(tmp_path, monkeypatch)
    clock = {"value": primary_time}
    provider_date = {"value": stale_date}

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = cls.fromisoformat(clock["value"])
            return instant.astimezone(tz) if tz is not None else instant.replace(tzinfo=None)

    monkeypatch.setattr(digest, "datetime", FrozenDateTime)
    contract = digest._configured_us_universe_contract()
    symbols = list(contract["symbols"])
    quote_response_sha256 = {}
    calls = []
    pub_date = datetime.strptime(session_date, "%Y%m%d").strftime(
        "%a, %d %b %Y 20:00:00 GMT"
    )

    def fetch(self, url, *, timeout=None, **kwargs):
        calls.append(url)
        if "qt.gtimg.cn" in url:
            records = []
            for symbol in symbols:
                fields = [""] * 31
                fields[1:5] = [symbol, symbol, "110", "100"]
                fields[30] = provider_date["value"] + "160001"
                records.append(f'v_us{symbol}="' + "~".join(fields) + '";')
            body = "".join(records).encode()
            quote_response_sha256[provider_date["value"]] = hashlib.sha256(body).hexdigest()
        else:
            key = hashlib.sha256(url.encode()).hexdigest()[:12]
            body = (
                f"<rss><channel><item><title>US retry test {key}</title>"
                f"<link>https://example.test/news/{key}</link>"
                f"<pubDate>{pub_date}</pubDate>"
                "<source>synthetic test</source></item></channel></rss>"
            ).encode()
        return FetchResult(
            body,
            {
                "status": "READY",
                "source": "SYNTHETIC_TRANSPORT",
                "source_url": url,
                "response_sha256": hashlib.sha256(body).hexdigest(),
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            },
        )

    monkeypatch.setattr(ProxyAwareHTTPTransport, "fetch", fetch)

    def process(command, *, cwd, timeout_seconds, env):
        assert env["HTTP_PROXY"] == "http://127.0.0.1:7897"
        assert env["HTTPS_PROXY"] == "http://127.0.0.1:7897"
        assert env["NO_PROXY"] == "127.0.0.1,localhost,::1"
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = digest.main(command[3:])
        return subprocess.CompletedProcess(command, rc, out.getvalue(), err.getvalue())

    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data", repo_root=ROOT, runner=process
    )
    ledger = ExecutionLedger(tmp_path / "ledger")
    first = runner.run_us_market_slot(
        data_root=tmp_path / "data",
        ledger_root=tmp_path / "ledger",
        slot=primary_slot,
        business_date=business_date,
        executor=registry,
        ledger=ledger,
    )
    assert first["status"] == "FAILED", first
    failed = next(
        row
        for row in ledger.list_receipts(business_date, mode="LIVE")
        if row["slot"] == primary_slot
    )
    assert failed["failure_class"] == "EXTERNAL_SOURCE"
    assert not (tmp_path / "data/research/peripherals" / business_date / "external_finance.json").exists()

    clock["value"] = retry_time
    provider_date["value"] = session_date
    recovered = runner.run_us_market_slot(
        data_root=tmp_path / "data",
        ledger_root=tmp_path / "ledger",
        slot=retry_slot,
        business_date=business_date,
        executor=registry,
        ledger=ledger,
    )
    if recovered["status"] != "SUCCEEDED":
        pytest.fail(
            json.dumps(
                {
                    "status": recovered.get("status"),
                    "close_retry": recovered.get("close_retry"),
                    "workload_results": recovered.get("workload_results"),
                },
                ensure_ascii=False,
            )
        )
    workload_result = recovered["workload_results"][0]
    assert workload_result["late_post_close_retry"] is True
    assert workload_result["retry_mode"] == "AUTOMATIC_LATE_RETRY"
    assert workload_result["retry_of_slot"] == primary_slot
    assert workload_result["retry_slot"] == retry_slot
    assert workload_result["retry_source_session_date"] == session_date
    assert workload_result["retry_target_trade_date"] == business_date
    assert workload_result["retry_capture_origin"] == "ORIGINAL_TIME_CAPTURE"
    assert workload_result["retry_capture_original_time"] is True
    assert workload_result["retry_capture_late"] is True
    assert workload_result["retry_executed_at"]

    store = ResearchPeripheralStore(tmp_path / "data")
    payload = store.read_exact(business_date, "external_finance")
    assert payload is not None
    assert payload["trade_date"] == business_date
    assert payload["market_snapshot_status"] == "READY"
    assert payload["market_snapshot"]["capture_session_date"] == session_date
    assert payload["market_snapshot"]["provider_session_dates"] == [session_date]
    assert payload["market_snapshot"]["universe_contract"] == contract
    assert payload["market_snapshot"]["universe_contract"]["version"] == "US_MAPPING_UNIVERSE_CONTRACT_V3"
    assert payload["market_snapshot"]["requested_symbol_count"] == 48
    assert payload["market_snapshot"]["available_symbol_count"] == 48
    assert len(payload["market_snapshot"]["quotes"]) == 48
    assert payload["market_snapshot"]["source_response_sha256"] == quote_response_sha256[session_date]
    assert payload["market_snapshot"]["provider_receipt"]["response_sha256"] == quote_response_sha256[session_date]
    assert store.read_exact(session_date, "external_finance") is None

    all_receipts = ledger.list_receipts(business_date, mode="LIVE")
    assert next(row for row in all_receipts if row["slot"] == primary_slot)["ledger_sha256"] == failed["ledger_sha256"]
    assert next(row for row in all_receipts if row["slot"] == retry_slot)["status"] == "SUCCEEDED"
    assert ledger.verify_receipt_chain(business_date, mode="LIVE")[0] is True

    calls_after_recovery = len(calls)
    repeated = runner.run_us_market_slot(
        data_root=tmp_path / "data",
        ledger_root=tmp_path / "ledger",
        slot=retry_slot,
        business_date=business_date,
        executor=registry,
        ledger=ledger,
    )
    assert repeated["status"] == "CONCURRENCY_SKIPPED"
    assert len(calls) == calls_after_recovery


def test_phase_merge_binds_snapshot_to_selected_capture_for_api_consumer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.v35_api import research_lane_router
    from ops.us_market_digest import build_us_market_phase_payload

    _bind_release(tmp_path, monkeypatch)
    contract = load_us_universe_contract()
    captured = ["2026-10-16T00:20:00-04:00", "2026-10-16T00:30:00-04:00"]

    def make_phase(stamp: str) -> dict:
        quotes = {
            symbol: {
                "last": 101.0,
                "previous_close": 100.0,
                "session_date": "20261015",
                "session_time": "16:00:01",
            }
            for symbol in contract["symbols"]
        }
        return build_us_market_phase_payload(
            "20261016",
            us_session_date="20261015",
            capture_phase="POST_CLOSE",
            fetched_at=stamp,
            now=stamp,
            allow_late_post_close=True,
            fetch_rss=lambda *_args: b"<rss><channel></channel></rss>",
            fetch_quotes=lambda *_args: quotes,
        )

    merged = digest.merge_us_phase_payloads(make_phase(captured[0]), make_phase(captured[1]))
    snapshot = merged["market_snapshot"]
    matching = [
        row
        for row in merged["us_session_captures"]
        if row["capture_phase"] == snapshot["capture_phase"]
        and row["us_session_date"] == snapshot["capture_session_date"]
        and row["late"] is True
    ]
    assert len(matching) == 2
    selected = next(row for row in matching if row["captured_at"] == snapshot["captured_at"])

    class _MergedStore:
        root = tmp_path

        @staticmethod
        def read_exact(trade_date: str, source: str) -> dict:
            assert (trade_date, source) == ("20261016", "external_finance")
            return merged

    projected = research_lane_router._project_global_industries(
        store=_MergedStore(), research_date="20261016"
    )
    assert projected["status"] != "CANNOT_CONFIRM"
    assert snapshot["capture_id"] == selected["capture_id"]
    assert snapshot["run_id"] == selected["run_id"]
    assert projected["capture_id"] == selected["capture_id"]
    assert projected["run_id"] == selected["run_id"]
    assert projected["late"] is True

