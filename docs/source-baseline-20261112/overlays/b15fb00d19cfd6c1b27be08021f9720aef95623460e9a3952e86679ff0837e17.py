from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
import csv
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "ops" / "a_share_daily_sync.py"
spec = importlib.util.spec_from_file_location("a_share_daily_sync_resume_repair", MODULE_PATH)
assert spec is not None and spec.loader is not None
sync = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = sync
spec.loader.exec_module(sync)


REVIEWED_INPUTS = Path(
    "/Users/lexi/Desktop/学习/agents调试/助手/v35_repair_20260907/"
    "a-sync-recovery/post-cas-authority-recovery/reviewed-repair-inputs.json"
)

AUTHORITY_PATH = Path(__file__).resolve().parents[1] / "ops" / "macos_research_panel_daily_authority.py"
BASELINE_APP = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/20260908-full-repair-a-ohlc/app"
)


def load_owner_authority() -> object:
    """Load the candidate adapter with its immutable shared helper modules."""
    baseline_text = str(BASELINE_APP)
    if baseline_text not in sys.path:
        sys.path.insert(0, baseline_text)
    # The candidate directory intentionally contains only the two allowlisted
    # business modules.  Reuse the released, read-only helper modules while
    # loading the candidate authority under a distinct module name.
    import ops.macos_research_panel_daily_common  # type: ignore[import-not-found]
    import ops.macos_research_panel_daily_pack  # type: ignore[import-not-found]

    module_name = "ops.macos_research_panel_daily_authority_candidate"
    spec = importlib.util.spec_from_file_location(module_name, AUTHORITY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def bar(date_value: int, close: float = 10.0) -> dict[str, object]:
    text = str(date_value)
    return {
        "year": int(text[:4]),
        "month": int(text[4:6]),
        "day": int(text[6:]),
        "open": close,
        "high": close + 0.2,
        "low": close - 0.2,
        "close": close,
        "amount": 1000.0,
        "vol": 100.0,
    }


def write_bars(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(sync.pack_hq_bar(row) for row in rows))


class FakeAPI:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.rows_by_code: dict[str, list[dict[str, object]]] = {}
        self.connect_calls: list[tuple[object, ...]] = []
        self.fetch_calls: list[tuple[object, ...]] = []
        self.disconnect_calls = 0

    def connect(self, *args: object, **kwargs: object) -> bool:
        self.connect_calls.append((*args, kwargs))
        return True

    def get_security_bars(self, *args: object) -> list[dict[str, object]]:
        self.fetch_calls.append(args)
        code = str(args[2]) if len(args) > 2 else ""
        return list(self.rows_by_code.get(code, self.rows))

    def disconnect(self) -> None:
        self.disconnect_calls += 1


class ResumeRepairTests(unittest.TestCase):
    def target(self, root: Path, code: str = "000089") -> sync.DailyTarget:
        return sync.DailyTarget(code=code, market=0, path=root / f"sz{code}.day")

    def progress_for(
        self,
        progress_path: Path,
        targets: list[sync.DailyTarget],
        *,
        completed: list[str] | None = None,
        pending: list[str] | None = None,
        symbol_progress: dict[str, object] | None = None,
    ) -> None:
        payload = sync._new_progress(20260907, targets, dry_run=False)
        payload["completed_symbols"] = completed or []
        payload["pending_symbols"] = pending or []
        payload["symbol_progress"] = symbol_progress or {}
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        progress_path.write_text(json.dumps(payload), encoding="utf-8")

    def assert_conservation(self, result: dict[str, object]) -> None:
        self.assertEqual(
            result["target_count"],
            result["accepted_count"] + result["quarantine_count"] + result["pending_count"],
        )

    def test_resume_order_exact_target_precedes_pending_and_preserves_remainder(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            current = self.target(root, "000001")
            pending = self.target(root, "000002")
            retry = self.target(root, "000003")
            write_bars(current.path, [bar(20260907, 10.1)])
            write_bars(pending.path, [bar(20260904, 20.1)])
            write_bars(retry.path, [bar(20260904, 30.1)])
            progress = {
                "target_date": "20260907",
                "completed_symbols": [current.code],
                "pending_symbols": [pending.code],
                "symbol_progress": {
                    current.code: {"classification": "ACCEPTED"},
                    pending.code: {"classification": "UNPROCESSED"},
                    retry.code: {"classification": "QUARANTINED"},
                },
            }
            ordered = sync._resume_target_order(
                [pending, retry, current],
                progress,
                20260907,
            )
            self.assertEqual(
                [item.code for item in ordered],
                [current.code, pending.code, retry.code],
            )

    def test_final_reconciliation_removes_overlap_when_run_stops_before_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            target = self.target(root, "000001")
            write_bars(target.path, [bar(20260907)])
            progress_path = root / "progress.json"
            self.progress_for(
                progress_path,
                [target],
                completed=[target.code],
                pending=[target.code],
                symbol_progress={target.code: {"classification": "ACCEPTED"}},
            )
            with mock.patch.object(sync, "_trusted_cas_load_inputs", return_value=None):
                result = sync.run_sync(
                    [target],
                    target_date="20260907",
                    api_factory=lambda *_args: self.fail("provider must not run"),
                    host_candidates=[("unused", 7709)],
                    progress_path=progress_path,
                    run_budget_seconds=0.000001,
                )
            self.assertEqual(result["pending_count"], 1)
            self.assert_conservation(result)
            self.assertEqual(result["progress"]["pending_symbols"], [target.code])
            self.assertEqual(result["progress"]["completed_symbols"], [])
            self.assertEqual(
                set(result["progress"]["pending_symbols"]) & set(result["progress"]["completed_symbols"]),
                set(),
            )

    def test_unprocessed_pending_symbol_is_attempted_before_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            pending_target = self.target(root, "000001")
            retry_target = self.target(root, "000002")
            write_bars(pending_target.path, [bar(20260904, 10.0)])
            write_bars(retry_target.path, [bar(20260904, 20.0)])
            progress_path = root / "progress.json"
            self.progress_for(
                progress_path,
                [pending_target, retry_target],
                pending=[pending_target.code],
                symbol_progress={
                    pending_target.code: {"classification": "UNPROCESSED"},
                    retry_target.code: {"classification": "QUARANTINED"},
                },
            )
            api = FakeAPI([bar(20260907, 10.1)])
            api.rows_by_code[retry_target.code] = [bar(20260907, 20.1)]
            with mock.patch.object(sync, "_trusted_cas_load_inputs", return_value=None):
                result = sync.run_sync(
                    [pending_target, retry_target],
                    target_date="20260907",
                    api_factory=lambda *_args: api,
                    host_candidates=[("provider", 7709)],
                    progress_path=progress_path,
                )
            self.assertEqual(
                [call[2] for call in api.fetch_calls],
                [pending_target.code, retry_target.code],
            )
            self.assertEqual(result["accepted_count"], 2)
            self.assertEqual(result["pending_count"], 0)
            self.assert_conservation(result)
            self.assertEqual(result["progress"]["completed_symbols"], [pending_target.code, retry_target.code])

    def test_reviewed_exact_date_cas_is_local_and_does_not_call_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            target = self.target(root)
            write_bars(target.path, [bar(20260904, 10.0), bar(20260907, 10.1)])
            current_sha = hashlib.sha256(target.path.read_bytes()).hexdigest()
            index = {
                "target_date": "20260907",
                "entries": {
                    target.code: {
                        "candidate_after_sha256": current_sha,
                        "native_path": str(target.path),
                        "record_count": 2,
                        "cohort": "new483",
                        "receipt_path": "/reviewed/native-apply-result.json",
                        "receipt_sha256": "a" * 64,
                        "cohort_review_path": "/reviewed/receipt.json",
                        "cohort_review_sha256": "b" * 64,
                        "candidate_manifest_path": "/reviewed/candidate-manifest.json",
                        "candidate_manifest_sha256": "c" * 64,
                    }
                },
            }
            progress_path = root / "progress.json"
            self.progress_for(
                progress_path,
                [target],
                completed=[target.code],
                pending=[target.code],
                symbol_progress={
                    target.code: {
                        "classification": "ACCEPTED",
                        "target_date": "20260907",
                        "source_sha256_after": "d" * 64,
                    }
                },
            )
            api = FakeAPI([bar(20260908, 10.2)])
            with mock.patch.object(sync, "_trusted_cas_load_inputs", return_value=index):
                result = sync.run_sync(
                    [target],
                    target_date="20260907",
                    api_factory=lambda *_args: self.fail("trusted CAS must not call provider"),
                    host_candidates=[("unused", 7709)],
                    progress_path=progress_path,
                    trusted_cas_inputs="ignored-by-patched-loader",
                )
            row = result["by_symbol"][target.code]
            self.assertEqual(row["status"], "TRUSTED_CAS_CURRENT")
            self.assertEqual(row["trusted_cas_cohort"], "new483")
            self.assertEqual(result["accepted_count"], 1)
            self.assertEqual(result["pending_count"], 0)
            self.assert_conservation(result)
            self.assertEqual(result["progress"]["completed_symbols"], [target.code])
            self.assertEqual(result["progress"]["pending_symbols"], [])
            self.assertEqual(api.fetch_calls, [])

    def test_reviewed_inputs_index_both_cohorts_and_future_date_is_inert(self) -> None:
        index = sync._trusted_cas_load_inputs(REVIEWED_INPUTS, 20260907)
        self.assertIsNotNone(index)
        assert index is not None
        self.assertEqual(index["cohort_counts"], {"old4662": 4662, "new483": 483, "total": 5145})
        self.assertIn("600004", index["entries"])
        self.assertEqual(index["entries"]["600004"]["cohort"], "new483")
        self.assertIsNone(sync._trusted_cas_load_inputs(REVIEWED_INPUTS, 20260908))

    def test_missing_stale_or_wrong_path_proof_cannot_reuse_local_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            target = self.target(root, "000089")
            write_bars(target.path, [bar(20260904, 10.0), bar(20260907, 10.1)])
            current_sha = hashlib.sha256(target.path.read_bytes()).hexdigest()
            history, failure = sync._local_history_status(target.path, 20260907)
            self.assertIsNone(failure)
            common = {
                "candidate_after_sha256": current_sha,
                "native_path": str(target.path),
                "record_count": 2,
                "cohort": "new483",
            }
            self.assertIsNone(
                sync._trusted_cas_local_reuse(
                    {"target_date": "20260907", "entries": {}},
                    target,
                    20260907,
                    current_sha,
                    history,
                    failure,
                    [],
                )
            )
            stale = dict(common)
            stale["record_count"] = 1
            self.assertIsNone(
                sync._trusted_cas_local_reuse(
                    {"target_date": "20260907", "entries": {target.code: stale}},
                    target,
                    20260907,
                    current_sha,
                    history,
                    failure,
                    [],
                )
            )
            wrong_path = dict(common)
            wrong_path["native_path"] = str(root / "other.day")
            self.assertIsNone(
                sync._trusted_cas_local_reuse(
                    {"target_date": "20260907", "entries": {target.code: wrong_path}},
                    target,
                    20260907,
                    current_sha,
                    history,
                    failure,
                    [],
                )
            )

    def test_reviewed_receipt_sha_drift_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            payload = json.loads(REVIEWED_INPUTS.read_text(encoding="utf-8"))
            payload["old4662"]["integration_receipt"]["sha256"] = "0" * 64
            malformed = root / "malformed-reviewed-inputs.json"
            malformed.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "SHA_DRIFT"):
                sync._trusted_cas_load_inputs(malformed, 20260907)

    def test_old_date_uses_original_provider_gate_and_future_bar_is_quarantined(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            target = self.target(root, "600004")
            write_bars(target.path, [bar(20260904, 10.0)])
            before = target.path.read_bytes()
            api = FakeAPI([bar(20260908, 10.1)])
            run_dir = root / "run"
            with mock.patch.object(sync, "_trusted_cas_load_inputs", return_value=None), mock.patch.object(
                sync, "RUN_DIR", run_dir
            ):
                result = sync.run_sync(
                    [target],
                    target_date="20260907",
                    api_factory=lambda *_args: api,
                    host_candidates=[("future-provider", 7709)],
                    progress_path=root / "progress.json",
                )
            row = result["by_symbol"][target.code]
            self.assertEqual(row["classification"], "QUARANTINED")
            self.assertEqual(row["reason_code"], "OUT_OF_SCOPE_AFTER_TARGET_DATE")
            self.assert_conservation(result)
            self.assertEqual(len(api.fetch_calls), 1)
            self.assertEqual(target.path.read_bytes(), before)

    def test_changed_native_bytes_do_not_reuse_cas_and_source_identity_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            target = self.target(root, "600004")
            write_bars(target.path, [bar(20260904, 10.0), bar(20260907, 10.1)])
            current_sha = hashlib.sha256(target.path.read_bytes()).hexdigest()
            index = {
                "target_date": "20260907",
                "entries": {
                    target.code: {
                        "candidate_after_sha256": "e" * 64,
                        "native_path": str(target.path),
                        "record_count": 2,
                        "cohort": "new483",
                    }
                },
            }
            self.assertNotEqual(current_sha, index["entries"][target.code]["candidate_after_sha256"])
            progress_path = root / "progress.json"
            self.progress_for(
                progress_path,
                [target],
                completed=[target.code],
                symbol_progress={
                    target.code: {
                        "classification": "ACCEPTED",
                        "target_date": "20260907",
                        "source_sha256_after": "d" * 64,
                    }
                },
            )
            api = FakeAPI([bar(20260907, 10.5)])
            with mock.patch.object(sync, "_trusted_cas_load_inputs", return_value=index):
                result = sync.run_sync(
                    [target],
                    target_date="20260907",
                    api_factory=lambda *_args: api,
                    host_candidates=[("provider", 7709)],
                    progress_path=progress_path,
                )
            row = result["by_symbol"][target.code]
            self.assertEqual(row["classification"], "QUARANTINED")
            self.assertEqual(row["reason_code"], "SOURCE_IDENTITY_CHANGED")
            self.assert_conservation(result)
            self.assertEqual(len(api.fetch_calls), 1)

    def test_malformed_local_field_signature_is_quarantined_without_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            target = self.target(root, "000089")
            good = sync.pack_hq_bar(bar(20260904, 10.0))
            malformed = sync.DAY_STRUCT.pack(
                20260907,
                1000,
                1020,
                980,
                1010,
                sync.struct.unpack("<f", sync.struct.pack("<I", sync.KNOWN_MALFORMED_AMOUNT_BITS))[0],
                0,
                0,
            )
            target.path.parent.mkdir(parents=True, exist_ok=True)
            target.path.write_bytes(good + malformed)
            before = target.path.read_bytes()
            with mock.patch.object(sync, "_trusted_cas_load_inputs", return_value=None):
                result = sync.run_sync(
                    [target],
                    target_date="20260907",
                    api_factory=lambda *_args: self.fail("malformed local bytes must not call provider"),
                    host_candidates=[("unused", 7709)],
                    progress_path=root / "progress.json",
                )
            row = result["by_symbol"][target.code]
            self.assertEqual(row["classification"], "QUARANTINED")
            self.assertEqual(row["reason_code"], sync.KNOWN_MALFORMED_AMOUNT_VOLUME_SIGNATURE)
            self.assert_conservation(result)
            self.assertEqual(target.path.read_bytes(), before)

    def test_actual_owner_cli_accepts_trusted_cas_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            tdx_root = root / "tdx"
            cas_path = root / "reviewed.json"
            cas_path.write_text("{}", encoding="utf-8")
            target_path = tdx_root / "vipdoc" / "sz" / "lday" / "sz000001.day"
            target = ("sz", 0, "000001", target_path, None)
            args = sync.parse_args(
                [
                    "--tdx-root",
                    str(tdx_root),
                    "--target-date",
                    "20260907",
                    "--trusted-cas-inputs",
                    str(cas_path),
                ]
            )
            self.assertEqual(args.trusted_cas_inputs, cas_path)
            stub_result = {"by_symbol": {}, "exit_code": 0, "run_id": "test"}
            with mock.patch.object(sync, "RUN_DIR", root / "run"), mock.patch.object(
                sync, "discover_targets", return_value=[target]
            ), mock.patch.object(sync, "run_sync", return_value=stub_result) as run_sync, mock.patch.object(
                sync, "write_csv"), mock.patch.object(sync, "write_json"), mock.patch(
                    "sys.stdout", new_callable=io.StringIO
                ):
                sync.run(args)
            self.assertEqual(run_sync.call_args.kwargs["trusted_cas_inputs"], cas_path)

    def test_original_owner_authority_accepts_trusted_cas_row(self) -> None:
        authority = load_owner_authority()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve() / "tdx"
            target_path = root / "vipdoc" / "sz" / "lday" / "sz000001.day"
            write_bars(target_path, [bar(20260907, 10.1)])
            target_key = authority._a_target_key(root, target_path)
            report = {
                "status": "PASS",
                "exit_code": 0,
                "target_date": 20260907,
                "target_fingerprint": authority._canonical_scope_fingerprint([target_key]),
                "target_count": 1,
                "accepted_count": 1,
                "quarantine_count": 0,
                "pending_count": 0,
                "symbol_reconciliation": [
                    {
                        "symbol": "000001",
                        "market": 0,
                        "status": "TRUSTED_CAS_CURRENT",
                        "fetch_status": "TRUSTED_CAS_REUSE",
                        "classification": "ACCEPTED",
                        "path": str(target_path),
                        "source_sha256_after": hashlib.sha256(target_path.read_bytes()).hexdigest(),
                    }
                ],
            }
            script = Path(temp) / "fake_original_owner.py"
            script.write_text(
                "def run(args):\n"
                "    assert args.target_date == 20260907\n"
                "    assert str(args.trusted_cas_inputs).endswith('reviewed.json')\n"
                f"    return {report!r}\n",
                encoding="utf-8",
            )
            trusted_inputs = Path(temp) / "reviewed.json"
            trusted_inputs.write_text("{}", encoding="utf-8")
            result = authority.run_windows_a_sync_authority(
                script,
                root,
                "20260907",
                Path(temp) / "receipt",
                authority_args={"trusted_cas_inputs": trusted_inputs},
            )
            self.assertEqual(result["authority_status"], "PASS")
            self.assertEqual(result["accepted_count"], 1)
            self.assertEqual(result["pending_count"], 0)
            self.assertEqual(result["status"], "READY")

    def test_partial_formula_handoff_accepts_trusted_cas_reuse(self) -> None:
        authority = load_owner_authority()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve() / "tdx"
            target_path = root / "vipdoc" / "sz" / "lday" / "sz000089.day"
            write_bars(target_path, [bar(20260904, 10.0), bar(20260907, 10.1)])
            receipt_root = Path(temp).resolve() / "receipt"
            run_dir = receipt_root / "a_sync_authority" / "20260907"
            run_dir.mkdir(parents=True)
            source_sha = hashlib.sha256(target_path.read_bytes()).hexdigest()
            with (run_dir / "file_results.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["path", "status", "fetch_status", "classification", "source_sha256_after"],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "path": str(target_path),
                        "status": "TRUSTED_CAS_CURRENT",
                        "fetch_status": "TRUSTED_CAS_REUSE",
                        "classification": "ACCEPTED",
                        "source_sha256_after": source_sha,
                    }
                )
            result = authority._accepted_formula_input_root(
                root,
                20260907,
                receipt_root,
                run_dir,
                target_files=[target_path],
                authority_status="REBUILD_REQUIRED",
                _history_status=lambda _path, _target: ([], None),
            )
            self.assertEqual(result["accepted_target_date_file_count"], 1)
            manifest = Path(result["formula_input_manifest"])
            self.assertTrue(manifest.is_file())
            copied = manifest.parent / "vipdoc" / "sz" / "lday" / "sz000089.day"
            self.assertEqual(copied.read_bytes(), target_path.read_bytes())


if __name__ == "__main__":
    unittest.main()
