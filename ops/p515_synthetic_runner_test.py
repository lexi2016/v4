"""Exercise the P5.15 CLI with temporary, generated fixtures and call tracing."""
from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timedelta
from pathlib import Path
import json
import os
import runpy
import subprocess
import sys
from tempfile import TemporaryDirectory

import p515_local_training as runner


RUNNER = Path(runner.__file__).resolve()
DAYS = [(date(2030, 1, 2) + timedelta(days=index)).strftime("%Y%m%d") for index in range(10)]
CUTOFF = "20300125"
REVIEWER = "SYNTHETIC independent reviewer"
AUTHOR = "SYNTHETIC fixture author"
MARKER = 10_000


def read_json(path):
    return json.loads(path.read_text())


def json_file(path, content):
    path.write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n")
    return path


def read_csv(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, items, columns):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(items)
    return path


def fixture_rows():
    columns = runner.PRICE + runner.MARKET + runner.STRUCTURE + runner.PERSONALITY + runner.SECTOR
    rows = []
    for day_index, day in enumerate(DAYS):
        for within_day in range(14):
            number = day_index * 14 + within_day
            timestamp = f"{day[:4]}-{day[4:6]}-{day[6:]}T15:00:00+08:00"
            row = dict(stable_security_id=f"SYNTHETIC_{number:06d}", observation_date=day,
                       event_id=f"fixture-event-{number}", root_anchor_id=f"fixture-root-{number}",
                       wave_id=f"fixture-wave-{number}", phase_label=runner.PHASES[within_day % 7],
                       pullback_label="SUCCESS" if within_day % 2 == 0 else "FAILURE",
                       label_source="SYNTHETIC_ADJUDICATION", label_maturity_date=day,
                       label_confidence="VERIFIED", PIT_status="VERIFIED_DATED", UNKNOWN_reason="",
                       feature_available_at=timestamp, decision_at=timestamp, event_start_date=day,
                       terminal_pullback_depth_pct=within_day + 0.5, sessions_to_pullback_outcome=1 + within_day,
                       support_label="SUPPORT_HELD" if within_day % 2 == 0 else "STRUCTURE_FAILURE")
            row.update({column: number + 0.01 * (col_index + 1) for col_index, column in enumerate(columns)})
            # Realistic count guard for personality data, with actual 0/low/mid/high strata.
            row["same_role_history_event_n"] = (0, 1, 2, 3, 5, 8, 12)[within_day % 7]
            rows.append(row)
    exclusions = {}

    def decoy(name, **overrides):
        position = MARKER + len(exclusions)
        row = dict(rows[0], stable_security_id=f"SYNTHETIC_{position:06d}",
                   event_id=f"decoy-event-{position}", root_anchor_id=f"decoy-root-{position}",
                   wave_id=f"decoy-wave-{position}")
        row.update({column: position + .01 for column in columns if column != "same_role_history_event_n"})
        row.update(overrides)
        rows.append(row)
        exclusions[name] = row

    decoy("PARTIAL", label_confidence="PARTIAL")
    decoy("UNKNOWN", label_confidence="UNKNOWN", phase_label="UNKNOWN", pullback_label="UNKNOWN")
    decoy("UNMATURED", label_maturity_date="20300201")
    decoy("FUTURE_FEATURE", feature_available_at="2030-01-02T15:00:00.001+08:00")
    decoy("ROW_LABEL_EVIDENCE_MISSING", label_source_sha256="")
    decoy("ROW_PIT_EVIDENCE_MISSING", feature_evidence_sha256="")
    decoy("PIT_STATUS_UNKNOWN", PIT_status="UNKNOWN")
    decoy("BAD_WAVE", wave_id="UNKNOWN")
    base_dev = rows[84]
    decoy("SAME_STOCK_ROOT", stable_security_id=base_dev["stable_security_id"],
          root_anchor_id=base_dev["root_anchor_id"])
    decoy("SAME_STOCK_EVENT", stable_security_id=base_dev["stable_security_id"],
          event_id=base_dev["event_id"])
    decoy("SAME_STOCK_INTERVAL", stable_security_id=rows[85]["stable_security_id"],
          label_maturity_date=DAYS[3])
    rows[85]["event_start_date"] = DAYS[2]
    decoy("MATURE_AT_DEV_START", label_maturity_date=DAYS[6])
    decoy("MATURE_AFTER_DEV_START", label_maturity_date=DAYS[7])
    decoy("PHASE_UNKNOWN_TARGET", phase_label="UNKNOWN")
    decoy("UNSTARTED_PULLBACK", pullback_label="NOT_STARTED")
    decoy("CENSORED_PULLBACK", pullback_label="CENSORED")
    decoy("NONNUMERIC_STRUCTURE", current_true_pullback_depth_pct="INVALID_SCORE")
    decoy("BLANK_STRUCTURE", current_true_pullback_depth_pct="")
    decoy("FRACTIONAL_SESSION_TARGET", sessions_to_pullback_outcome=1.5)
    decoy("FRACTIONAL_HISTORY_COUNT", same_role_history_event_n=0.5)
    return rows, exclusions


def make_bundle(bundle, rows, schema="p515-synthetic-fixture/1"):
    bundle.mkdir()
    label = bundle / "fabricated_adjudication.txt"
    label.write_text("Synthetic labels created only for P5.15 runner tests.\n")
    pit = bundle / "fabricated_pit.txt"
    pit.write_text("Synthetic point-in-time clocks created only for P5.15 runner tests.\n")
    evidence = [
        dict(path=path.name, kind=kind, sha256=runner.sha(path), owner="SYNTHETIC evidence constructor")
        for path, kind in ((label, "independent_label_adjudication"), (pit, "historical_pit_and_features"))
    ]
    rows = [dict({"label_source_sha256": evidence[0]["sha256"], "feature_evidence_sha256": evidence[1]["sha256"]},
                 **row) for row in rows]
    dataset = write_csv(bundle / "dataset.csv", rows, runner.CERTIFIED_COLUMNS)
    return json_file(bundle / "dataset_manifest.json",
                     dict(schema=schema, independent_reviewer=REVIEWER, runner_sha256=runner.sha(RUNNER),
                          development_label_cutoff=CUTOFF, dataset=dataset.name,
                          dataset_sha256=runner.sha(dataset), evidence=evidence))


def traced_cli():
    """Trace external estimator and Joblib calls inside a separate CLI process."""
    import joblib
    import numpy as np
    from sklearn import pipeline
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

    trace_path = Path(os.environ["P515_TRACE_FILE"])
    fault = os.environ.get("P515_TEST_FAULT", "")
    fit_calls = 0
    load_calls = 0

    def log(kind, **extra):
        with trace_path.open("a") as stream:
            stream.write(json.dumps(dict(kind=kind, **extra)) + "\n")

    def wrap_fit(original, estimator_name):
        def wrapped(self, data, target, *args, **kwargs):
            nonlocal fit_calls
            fit_calls += 1
            log("estimator_fit", estimator=estimator_name, features=list(data.columns),
                tokens=np.floor(data.iloc[:, 0]).astype(int).tolist(), targets=[str(value) for value in target])
            if fault == "RETRY" and fit_calls == 1:
                raise ValueError("INJECTED_ESTIMATOR_FIT_FAILURE")
            outcome = original(self, data, target, *args, **kwargs)
            log("estimator_fit_complete")
            return outcome

        return wrapped

    def wrap_predict(original, predict_name):
        def wrapped(self, data, *args, **kwargs):
            log("prediction", method=predict_name, features=list(data.columns),
                tokens=np.floor(data.iloc[:, 0]).astype(int).tolist())
            return original(self, data, *args, **kwargs)

        return wrapped

    def wrap_stage(original, stage):
        def wrapped(self, *args, **kwargs):
            log(stage)
            return original(self, *args, **kwargs)

        return wrapped

    for estimator_type, method in ((HistGradientBoostingClassifier, "predict_proba"),
                                   (HistGradientBoostingRegressor, "predict")):
        estimator_type.fit = wrap_fit(estimator_type.fit, estimator_type.__name__)
        setattr(estimator_type, method, wrap_predict(getattr(estimator_type, method), method))
    pipeline.Pipeline.fit = wrap_stage(pipeline.Pipeline.fit, "preprocessing")
    CalibratedClassifierCV.fit = wrap_stage(CalibratedClassifierCV.fit, "calibration")

    original_load = joblib.load

    def load(path, *args, **kwargs):
        nonlocal load_calls
        load_calls += 1
        log("load", path=Path(path).name, sha256=runner.sha(Path(path)))
        if (fault == "UNRECOVERED" and load_calls == 1) or (fault == "RETRY" and load_calls == 2):
            raise EOFError("INJECTED_WEIGHT_RELOAD_FAILURE")
        return original_load(path, *args, **kwargs)

    joblib.load = load
    sys.argv = [str(RUNNER), *sys.argv[2:]]
    runpy.run_path(str(RUNNER), run_name="__main__")


def cli(root, name, manifest, arguments, *, approve_sha=None, fault=None, extra=()):
    output = root / f"p5_15_local_training_{name}"
    trace_path = root / f"{name}-calls.jsonl"
    binary = [sys.executable, str(RUNNER)]
    if fault is not None:
        binary = [sys.executable, str(Path(__file__).resolve()), "--trace-child"]
    command = binary + ["--synthetic-fixture-root", str(root), "--output", str(output),
                        "--certified-development-manifest", str(manifest), "--approved-manifest-sha256",
                        approve_sha or runner.sha(manifest), *arguments, *extra]
    env = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
               P515_TRACE_FILE=str(trace_path), P515_TEST_FAULT=fault or "", PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run(command, env=env, capture_output=True, text=True, check=False, timeout=120)
    frames = [json.loads(line) for line in trace_path.read_text().splitlines()] if trace_path.exists() else []
    return result, output, frames


def receipt_for(root, name, frozen, **changes):
    plan = read_json(frozen)
    approval = {field: plan[field] for field in ("scope", "certified_manifest_sha256", "certified_input_sha256",
                                                  "runner_sha256", "feature_contract_sha256", "verified_data_sha256")}
    date = datetime.fromisoformat(plan["frozen_at_utc"]) + timedelta(seconds=1)
    approval.update(schema="p515-fit-approval/1", verdict="APPROVED_SYNTHETIC_FIXTURE_FIT", reviewer=REVIEWER,
                    prefit_freeze_sha256=runner.sha(frozen), reviewed_at_utc=date.isoformat())
    approval.update(changes)
    return json_file(root / name, approval)


def freeze(root, name, manifest, extra=()):
    result, output, _ = cli(root, name, manifest, ["--freeze-only", "--plan-author", AUTHOR], extra=extra)
    if result.returncode:
        raise AssertionError(result.stderr)
    return output / "PREFIT_FREEZE.json"


def execute(root, name, manifest, frozen, approval, *, extra=(), fault=None):
    return cli(root, name, manifest, ["--prefit-freeze", str(frozen), "--fit-approval-receipt",
                                     str(approval), "--fit-approval-sha256", runner.sha(approval)],
               extra=extra, fault=fault)


def verify_successes(output, trace=None):
    ledger = read_csv(output / "EXPERIMENT_LEDGER.csv")
    inventory = read_csv(output / "WEIGHT_INVENTORY.csv")
    receipt = read_json(output / "RUN_RECEIPT.json")
    metrics = read_json(output / "EXPERIMENT_METRICS.json")
    for label in ("estimator_fit_count", "estimator_fit_completed_count", "prediction_calls",
                  "preprocessing_fit_count", "calibration_fit_count"):
        assert sum(int(row[label]) for row in ledger) == receipt[label], label
    for weight in inventory:
        assert runner.sha(output / weight["weight_path"]) == weight["sha256"], weight
        if weight["status"] == "RELOAD_PASSED":
            assert float(weight["reload_max_abs_error"]) == 0.0, weight
    for name in ("prediction_calls", "estimator_fit_count", "estimator_fit_completed_count"):
        assert receipt[name] >= 0
    if trace is not None:
        kinds = [item["kind"] for item in trace]
        for receipt_key, trace_key in (("estimator_fit_count", "estimator_fit"),
                                       ("estimator_fit_completed_count", "estimator_fit_complete"),
                                       ("prediction_calls", "prediction"), ("preprocessing_fit_count", "preprocessing"),
                                       ("calibration_fit_count", "calibration")):
            assert receipt[receipt_key] == kinds.count(trace_key), (receipt_key, receipt[receipt_key], kinds.count(trace_key))
        assert sorted(item["sha256"] for item in trace if item["kind"] == "load") == sorted(w["sha256"] for w in inventory)
    return ledger, inventory, receipt, metrics


def test_suite(root):
    results = []
    evidence = {}

    def record(name, proof, **counts):
        results.append(dict(case=name, verdict="PASS", evidence=proof, **counts))

    def checked_rejection(name, expected, invocation):
        result, output, trace = invocation
        assert result.returncode != 0 and expected in result.stderr, (name, result.stderr)
        assert not (output / "weights").exists() and not (output / "EXPERIMENT_LEDGER.csv").exists() and not trace, name
        record(name, expected, estimator_fit_count=0, preprocessing_fit_count=0, prediction_calls=0)

    rows, decoys = fixture_rows()
    manifest = make_bundle(root / "baseline", rows)
    frozen = freeze(root, "freeze", manifest)
    approval = receipt_for(root, "allow.json", frozen)
    result, output, trace = execute(root, "baseline", manifest, frozen, approval, fault="")
    assert result.returncode == 0, (result.stderr, result.stdout)
    ledger, inventory, receipt, metrics = verify_successes(output, trace)
    assert len(ledger) == len(inventory) == 28
    assert receipt["estimator_fit_count"] == 28 and receipt["estimator_fit_completed_count"] == 28
    assert receipt["prediction_calls"] == 56 and receipt["successful_fold_count"] == 28
    assert receipt["preprocessing_fit_count"] == receipt["calibration_fit_count"] == 0
    assert len(metrics["per_variant"]) == 28 and len(metrics["matched_development_contrasts"]) == 16
    attempts = [item for item in trace if item["kind"] == "estimator_fit"]
    predictions = [item for item in trace if item["kind"] == "prediction"]
    assert len(attempts) == len(ledger)
    by_variant = {}
    by_variant_dev = {}
    for index, (entry, actual_fit) in enumerate(zip(ledger, attempts)):
        variant = entry["variant"].split("/")[0]
        model, target, names, classes = runner.EXPERIMENTS[variant]
        assert actual_fit["features"] == list(names), entry
        assert actual_fit["estimator"] == f"HistGradientBoosting{'Classifier' if classes else 'Regressor'}", entry
        assert int(entry["train_rows"]) == len(actual_fit["tokens"])
        original, reloaded = predictions[index * 2:index * 2 + 2]
        assert original == reloaded and int(entry["dev_rows"]) == len(original["tokens"])
        if classes:
            assert set(actual_fit["targets"]) == set(classes)
        else:
            assert all(float(value) > 0 for value in actual_fit["targets"])
        by_variant[entry["variant"]] = actual_fit["tokens"]
        by_variant_dev[entry["variant"]] = original["tokens"]
        assert set(original["tokens"]) == set(range(84, 112) if entry["variant"].endswith("/F1") else range(112, 140))
        report = metrics["per_variant"][index]
        if classes:
            assert report["classes"] == classes and set(report["per_class_recall"]) == set(classes)
            assert sum(map(sum, report["confusion_matrix"])) == len(original["tokens"])
            if "STRUCTURE_FAILURE" in classes:
                assert report["risk_false_negative_rate"] == 1 - report["per_class_recall"]["STRUCTURE_FAILURE"]
        else:
            assert report["MAE"] >= 0 and report["unit"] == ("sessions" if "TIME" in variant else "percentage_points")
        if model == "C":
            assert set(report["history_count_strata"]) == {"0–2", "3–7", "8+"}
        record(f"EXECUTE_{entry['variant']}", f"{len(actual_fit['tokens'])} train / {len(original['tokens'])} dev; SHA and exact reload verified",
               estimator_fit_count=1, preprocessing_fit_count=0, prediction_calls=2)
    not_verified = list(decoys)[:8]
    data = read_csv(output / "VERIFIED_TRAINING_DATASET.csv")
    admitted = {(row["stable_security_id"], row["observation_date"], row["event_id"]) for row in data}
    all_tokens = set().union(*[set(item["tokens"]) for item in attempts + predictions])
    for index, name in enumerate(not_verified):
        row = decoys[name]
        assert tuple(row[key] for key in runner.KEY) not in admitted and MARKER + index not in all_tokens, name
        record(name, "Key absent from verified projection and all traced train/dev calls")
    for name in list(decoys)[8:13]:
        position = MARKER + list(decoys).index(name)
        assert tuple(decoys[name][key] for key in runner.KEY) in admitted
        assert all(position not in tokens for fold, tokens in by_variant.items() if fold.endswith("/F1")), name
        record(name, "Admitted provenance, then removed from first dev fold’s estimator inputs")
    for name, variants in {
        "PHASE_UNKNOWN_TARGET": ("A",), "UNSTARTED_PULLBACK": ("B", "C", "D"), "CENSORED_PULLBACK": ("B", "C", "D"),
        "NONNUMERIC_STRUCTURE": ("A", "B"), "BLANK_STRUCTURE": ("A", "B"),
        "FRACTIONAL_SESSION_TARGET": ("B_TIME",), "FRACTIONAL_HISTORY_COUNT": ("C",),
    }.items():
        position = MARKER + list(decoys).index(name)
        assert all(position not in tokens for fold, tokens in by_variant.items() if fold.startswith(variants)), name
        record(name, "Excluded from applicable model targets or matched support groups")
    record("VERIFIED_POSITIVE_CONTROL", "14 variants and both folds run; per-call matrices match ledger",
           estimator_fit_count=28, preprocessing_fit_count=0, prediction_calls=56)
    record("NAN_POLICY_AND_CLASS_MAP", "Missing/nonnumeric features excluded on matched support; seven A classes, two support classes in traced targets")
    record("COMMON_SUPPORT", "All variants in each target group use identical ordered columns-independent row tokens and prediction date folds")
    for comparator in metrics["matched_development_contrasts"]:
        left = comparator["candidate"]
        right = comparator["comparator"]
        assert by_variant[left] == by_variant[right], comparator
        assert by_variant_dev[left] == by_variant_dev[right], comparator

    rejection_dir = root / "p5_15_local_training_real_replay"
    absent_input = root / "real_data_must_not_be_read"
    result = subprocess.run([sys.executable, str(RUNNER), "--research-root", str(absent_input),
                             "--audit", str(absent_input), "--output", str(rejection_dir),
                             "--certified-development-manifest", str(manifest), "--approved-manifest-sha256",
                             runner.sha(manifest), "--prefit-freeze", str(frozen), "--fit-approval-receipt",
                             str(approval), "--fit-approval-sha256", runner.sha(approval)],
                            capture_output=True, text=True, check=False, timeout=120)
    checked_rejection("FORMAL_ANTI_REPLAY", "awaits the authoritative COMMON_TRAINING_MANIFEST", (result, rejection_dir, []))
    assert not rejection_dir.exists()

    for key, phrase, mutate in (
        ("RUNNER_SHA_MISMATCH", "different runner", lambda item: item.update(runner_sha256="0" * 64)),
        ("DATASET_SHA_MISMATCH", "dataset SHA mismatch", lambda item: item.update(dataset_sha256="0" * 64)),
        ("EVIDENCE_LABEL_MISSING", "require distinct evidence", lambda item: item["evidence"].pop(0)),
        ("EVIDENCE_PIT_MISSING", "require distinct evidence", lambda item: item["evidence"].pop(1)),
        ("REAL_SCHEMA_IN_SYNTHETIC_MODE", "selected data mode", lambda item: item.update(schema="p515-certified-development/1")),
    ):
        content = read_json(manifest)
        mutate(content)
        altered = json_file(manifest.parent / f"{key}.json", content)
        checked_rejection(key, phrase, cli(root, key, altered, ["--freeze-only", "--plan-author", AUTHOR]))
    checked_rejection("MANIFEST_SHA_MISMATCH", "does not match this manifest",
                      cli(root, "manifest_sha", manifest, ["--freeze-only", "--plan-author", AUTHOR], approve_sha="0" * 64))

    for name, phrase, change in (
        ("FEATURE_CONTRACT_SHA_MISMATCH", "different dataset, runner, features", dict(feature_contract_sha256="0" * 64)),
        ("REVIEWER_ID_MISMATCH", "differs from the independently reviewed manifest", dict(reviewer="SYNTHETIC other reviewer")),
        ("REVIEW_AUTHOR_COLLISION", "differ from the plan author", dict(reviewer=AUTHOR)),
        ("APPROVAL_BEFORE_FREEZE", "dated after", dict(reviewed_at_utc="2020-01-01T00:00:00+00:00")),
        ("FORMAL_VERDICT_IN_SYNTHETIC_MODE", "did not approve", dict(verdict="APPROVED_RESEARCH_DEVELOPMENT_FIT")),
    ):
        bad_approval = receipt_for(root, f"{name}.json", frozen, **change)
        checked_rejection(name, phrase, execute(root, name, manifest, frozen, bad_approval))

    plan = read_json(frozen)
    plan["feature_contract_sha256"] = "0" * 64
    tampered_dir = root / "tampered_plan"
    tampered_dir.mkdir()
    tampered = json_file(tampered_dir / frozen.name, plan)
    tampered_approval = receipt_for(root, "tampered_receipt.json", tampered)
    checked_rejection("FROZEN_FEATURE_SHA_MISMATCH", "Frozen feature contract SHA", execute(
        root, "tampered_contract", manifest, tampered, tampered_approval))

    def run_pass_record(name, output, trace):
        detail = verify_successes(output, trace)
        summary = detail[2]
        evidence[name] = dict(receipt=summary, ledger=detail[0], weight_inventory=detail[1],
                              metrics_sha256=runner.sha(output / "EXPERIMENT_METRICS.json"))
        return summary, detail[0]

    run_pass_record("baseline", output, trace)
    missing = [dict(row, own_depth_median_shrunk_pct="") for row in rows]
    support_manifest = make_bundle(root / "blocked_personality", missing)
    support_freeze = freeze(root, "blocked_freeze", support_manifest)
    support_approval = receipt_for(root, "blocked_allow.json", support_freeze)
    result, output, trace = execute(root, "blocked", support_manifest, support_freeze, support_approval, fault="")
    assert result.returncode == 0, result.stderr
    summary, attempts = run_pass_record("blocked_personality", output, trace)
    assert summary["successful_fold_count"] == 20 and summary["estimator_fit_count"] == 20
    assert summary["prediction_calls"] == 40
    assert len([entry for entry in attempts if entry["status"] == "BLOCKED" and entry["model"] == "C"]) == 4
    assert all(int(entry["estimator_fit_count"]) == 0 for entry in attempts if entry["model"] == "C")
    record("INDEPENDENT_VARIANT_BLOCK", "All four C contrasts block on absent common support; A/B/D 20 folds complete",
           estimator_fit_count=20, preprocessing_fit_count=0, prediction_calls=40)

    result, output, trace = execute(root, "unrecovered", manifest, frozen, approval, fault="UNRECOVERED")
    assert result.returncode == 1, result.stderr
    summary, attempts = run_pass_record("unrecovered_reload", output, trace)
    assert summary["terminal_failed_folds"] == ["A_PRICE/F1"] and summary["successful_fold_count"] == 27
    assert summary["prediction_calls"] == 55 and summary["estimator_fit_count"] == 28
    assert attempts[0]["last_stage"] == "WEIGHT_RELOAD" and attempts[0]["status"] == "ATTEMPT_FAILED"
    assert attempts[0]["block_reason"].endswith("INJECTED_WEIGHT_RELOAD_FAILURE")
    assert attempts[-1]["variant"] == "D_SECTOR/F2" and attempts[-1]["status"] == "RELOAD_PASSED"
    record("UNRECOVERED_RELOAD_CONTINUE", "A_PRICE/F1 load fails; later 27 folds pass; CLI exits nonzero after recording both",
           estimator_fit_count=28, preprocessing_fit_count=0, prediction_calls=55)

    retry = ("--retry-failed-once",)
    retry_plan = freeze(root, "retry_freeze", manifest, retry)
    retry_approval = receipt_for(root, "retry_allow.json", retry_plan)
    checked_rejection("UNAPPROVED_RETRY", "Execution context differs", execute(
        root, "unapproved_retry", manifest, frozen, approval, extra=retry))
    result, output, trace = execute(root, "retry", manifest, retry_plan, retry_approval, extra=retry, fault="RETRY")
    assert result.returncode == 0, result.stderr
    summary, attempts = run_pass_record("recovered_fit_and_reload", output, trace)
    assert summary["successful_fold_count"] == 28 and summary["estimator_fit_count"] == 30
    assert summary["estimator_fit_completed_count"] == 29 and summary["retry_attempt_count"] == 2
    assert summary["failed_attempt_count"] == 2 and summary["prediction_calls"] == 57
    assert [(r["variant"], r["attempt"], r["last_stage"], r["status"]) for r in attempts[:4]] == [
        ("A_PRICE/F1", "1", "ESTIMATOR_FIT", "ATTEMPT_FAILED"), ("A_PRICE/F1", "2", "COMPLETE", "RELOAD_PASSED"),
        ("A_PRICE/F2", "1", "WEIGHT_RELOAD", "ATTEMPT_FAILED"), ("A_PRICE/F2", "2", "COMPLETE", "RELOAD_PASSED"),
    ], attempts[:4]
    assert not attempts[0]["weight_sha256"]
    assert (output / "weights/A_PRICE_F2.joblib").is_file() and (output / "weights/A_PRICE_F2_attempt2.joblib").is_file()
    record("FIT_FAILURE_AND_BOUNDED_RETRY", "Failed estimator entry counted once, no weight; distinct second attempt passes")
    record("RELOAD_FAILURE_AND_BOUNDED_RETRY", "Original failed weight inventoried; attempt 2 uses separate bytes and passes")
    record("RETRY_TOTALS", "Two failed call entries retained, 28 successful folds, 29 completed estimator fits",
           estimator_fit_count=30, preprocessing_fit_count=0, prediction_calls=57)
    return results, evidence


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--trace-child":
        traced_cli()
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", required=True, type=Path)
    args = parser.parse_args()
    out = args.report_dir.resolve()
    if not out.is_dir():
        parser.error("report directory must already exist")
    with TemporaryDirectory(prefix="p515-synthetic-") as directory:
        results, evidence = test_suite(Path(directory))
    columns = ["case", "verdict", "evidence", "estimator_fit_count", "preprocessing_fit_count", "prediction_calls"]
    write_csv(out / "SYNTHETIC_ADMISSION_TESTS.csv", results, columns)
    for batch in evidence.values():
        batch["receipt"]["environment"].pop("interpreter")
        for row in batch["ledger"]:
            env = json.loads(row["environment"])
            env.pop("interpreter")
            row["environment"] = env
    json_file(out / "SYNTHETIC_EXECUTION_RECEIPTS.json",
              dict(schema="p515-synthetic-execution-evidence/1", runner_sha256=runner.sha(RUNNER),
                   harness_sha256=runner.sha(Path(__file__)), synthetic_only=True,
                   temporary_fixtures_removed=True, batches=evidence))
    print(f"PASS {len(results)} synthetic acceptance assertions")


if __name__ == "__main__":
    main()
