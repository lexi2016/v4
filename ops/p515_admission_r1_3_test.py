"""Exercise the R1.3 intake and export through synthetic, zero-fit fixtures."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, timedelta
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

import p515_common_dataset as common


GROUPS = common.expected_groups(True)
EXCLUSION_FIELDS = ("sample_id", "comparison_group_id", "exclusion_reason_code")
FROZEN_AT = "2026-11-13T00:00:00Z"
REVIEWED_AT = "2026-11-13T00:01:00Z"


def date_text(value):
    return value.strftime("%Y%m%d")


def clock(value, hour):
    return f"{value.isoformat()}T{hour}:00+08:00"


def write_csv(path, columns, rows):
    path.write_bytes(common.csv_bytes(columns, rows))


def write_json(path, obj):
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def write_tables(root, manifest, samples, folds, exclusions):
    for name, columns, rows in (
        ("samples", common.sample_columns(True), samples),
        ("fold_assignments", common.FOLD_FIELDS, folds),
        ("exclusions", EXCLUSION_FIELDS, exclusions),
    ):
        path = root / f"{name}.csv"
        write_csv(path, columns, rows)
        manifest["files"][name] = {"path": path.name, "sha256": common.digest_file(path), "row_count": len(rows)}
    manifest["exclusion_ledger_sha256"] = manifest["files"]["exclusions"]["sha256"]
    manifest["exclusion_summary"] = {
        "row_count": len(exclusions),
        "by_reason": dict(Counter(row["exclusion_reason_code"] for row in exclusions)),
    }
    path = root / "COMMON_TRAINING_MANIFEST.json"
    write_json(path, manifest)
    return path


def exclusions_for(samples, folds):
    assignments = {(r["sample_id"], r["comparison_group_id"]) for r in folds}
    return [
        {"sample_id": r["sample_id"], "comparison_group_id": group,
         "exclusion_reason_code": "UNKNOWN_LABEL" if r["label_confidence"] != "VERIFIED" else "NOT_ELIGIBLE_FOR_TASK"}
        for r in samples for group in GROUPS if (r["sample_id"], group) not in assignments
    ]


def observation(root, index, obs, group_name, role, evidence):
    row = dict.fromkeys(common.sample_columns(True), "")
    sid = f"SYNTHETIC_{index:02d}"
    security = f"{index:06d}.{'SZ' if role == 'train' else 'SH'}"
    days = [obs - timedelta(days=n) for n in range(35, -1, -1) if (obs - timedelta(days=n)).weekday() < 5]
    raw = []
    for i, trade_date in enumerate(days):
        opened = 20 + i / 10
        raw.append({"ts_code": security, "trade_date": date_text(trade_date), "open": opened,
                    "high": opened + 0.6, "low": opened - 0.5, "close": opened + 0.1,
                    "volume": 2000 + i * 19, "amount": 50000 + i * 43})
    path = root / f"{sid}.csv"
    write_csv(path, ("ts_code", *common.RAW_COLUMNS), raw)
    evidence.append(("raw_prefix", path))
    row.update(
        sample_id=sid, stable_security_id=security, observation_date=date_text(obs),
        exposure_status="UNEXPOSED", price_basis=common.RAW_PRICE_BASIS,
        volume_unit="SHARES", amount_unit="CNY", raw_prefix_sha256=common.digest_file(path),
        raw_prefix_row_count=str(len(raw)), raw_prefix_max_date=date_text(obs),
        label_maturity_date=date_text(obs + timedelta(days=2)), label_confidence="VERIFIED",
        label_source="SYNTHETIC_ONLY", feature_available_at=clock(obs, "15:01"), decision_at=clock(obs, "15:05"),
        **common.STATUS_CERTIFIED,
    )
    for other_group in GROUPS.values():
        for features in other_group["variants"].values():
            for field in features:
                row[field] = "1"

    if group_name == "H1_PHASE":
        row.update(event_identity_status="NO_REAL_EVENT", root_anchor_id="UNKNOWN", wave_id="UNKNOWN",
                   phase_label="TREND_CONSOLIDATION", sector_pit_status="UNKNOWN")
        values = [tuple(r[field] for field in common.RAW_COLUMNS[1:]) for r in raw]
        row.update({k: repr(v) for k, v in common.h1_features_from_raw(values).items()})
    else:
        row.update(
            event_identity_status="CERTIFIED_REAL_EVENT", event_id=f"E_{index}",
            event_start_date=date_text(days[-6]), raw_root_anchor_id=f"R_{index}",
            raw_root_anchor_date=date_text(days[-5]), wave_id=f"W_{index}",
            attack_start_date=date_text(days[-6]), attack_end_date=date_text(days[-4]),
            pullback_start_date=date_text(days[-3]), pullback_end_date=date_text(obs),
            support_role="ROOT_KEY_CANDLE", pullback_label="SUCCESS", support_label="SUPPORT_HELD",
            terminal_pullback_depth_pct="2.5", sessions_to_pullback_outcome="3",
        )
    return row


def build_fixture(root):
    root.mkdir()
    manifest = {
        "schema": common.TASK_SCHEMA, "market": "A_SHARE", "input_scope": "SYNTHETIC_ONLY",
        "dataset_id": "R1_3_SYNTHETIC_FIXTURE", "fit_authorized": False, "sealed_test_material_present": False,
        "trading_cost_contract": "NO_RETURN_EVALUATION", "frozen_at_utc": FROZEN_AT,
        "pit_cutoff_date": "20260220", "development_label_cutoff": "20260220",
        "windows": {"train_start": "20260101", "train_end": "20260131",
                    "development_start": "20260201", "development_end": "20260219"},
        "provenance": {"plan_author": "SYNTHETIC_PLAN", "independent_reviewer": "SYNTHETIC_REVIEW"},
        **common.contract_hashes(True), "groups": GROUPS, "files": {},
    }
    samples, folds, evidence, cert, judges, events, history, sectors, features = ([] for _ in range(9))
    for group_name in GROUPS:
        group = GROUPS[group_name]
        for role, day in (("train", date(2026, 1, 8)), ("dev", date(2026, 2, 5))):
            row = observation(root, len(samples) + 1, day, group_name, role, evidence)
            samples.append(row)
            keys = {"sample_id": row["sample_id"], "stable_security_id": row["stable_security_id"]}
            folds.append({"sample_id": row["sample_id"], "comparison_group_id": group_name,
                          "fold_id": "F1", "partition": role})
            cert.append({field: row[field] for field in common.OBSERVATION_EVIDENCE_FIELDS})
            target = group["target"]
            judges.append({
                **keys, "observation_date": row["observation_date"], "comparison_group_id": group_name,
                "label_maturity_date": row["label_maturity_date"],
                "target_name": target, "target_value": row[target], "judge_a": "SYNTHETIC_JUDGE_A",
                "judge_b": "SYNTHETIC_JUDGE_B", "judge_a_value": row[target], "judge_b_value": row[target],
                "arbitrator": "", "resolution_status": "AGREED",
            })
            if group_name == "H1_PHASE":
                continue
            events.append({**{field: row[field] for field in common.EVENT_EVIDENCE_FIELDS},
                           "identity_available_at": clock(day, "15:01")})
            hashes = {field: row[field] for field in {f for variant in group["variants"].values() for f in variant}}
            features.append({**keys, "observation_date": row["observation_date"], "comparison_group_id": group_name,
                             "feature_values_sha256": common.canonical_sha(hashes), "available_at": row["feature_available_at"]})
            if group_name == "H3_SUPPORT":
                history.append({**keys, "current_raw_root_anchor_id": row["raw_root_anchor_id"],
                                "history_event_id": f"HIST_E_{row['sample_id']}", "history_raw_root_anchor_id": f"HIST_R_{row['sample_id']}",
                                "history_role": row["support_role"], "history_maturity_date": "20251215",
                                "available_at": "2025-12-16T16:00+08:00"})
            if group_name in {"H3_SUPPORT", "H4_SUPPORT"}:
                sectors.append({**keys, "industry_id": "SYNTHETIC_INDUSTRY", "classification_version": "SYNTHETIC_V1",
                                "effective_from_date": "20251201", "effective_to_date": "20261201",
                                "published_at": "2025-11-15T15:00+08:00", "available_at": "2025-11-16T15:00+08:00"})
    for kind, fields, records, digest_field in (
        ("observation_certification", common.OBSERVATION_EVIDENCE_FIELDS, cert, "observation_evidence_sha256"),
        ("independent_label_adjudication", common.JUDGMENT_FIELDS, judges, "label_source_sha256"),
        ("event_lineage", (*common.EVENT_EVIDENCE_FIELDS, "identity_available_at"), events, "event_lineage_sha256"),
        ("same_role_history", common.HISTORY_FIELDS, history, "same_role_history_sha256"),
        ("sector_membership", common.SECTOR_FIELDS, sectors, "sector_membership_sha256"),
        ("historical_pit_and_features", common.FEATURE_EVIDENCE_FIELDS, features, "feature_evidence_sha256"),
    ):
        path = root / f"{kind}.csv"
        write_csv(path, fields, records)
        evidence.append((kind, path))
        ids = {record["sample_id"] for record in records}
        for row in samples:
            if row["sample_id"] in ids:
                row[digest_field] = common.digest_file(path)
    manifest["evidence"] = [
        {"kind": kind, "path": path.name, "sha256": common.digest_file(path),
         "owner": "SYNTHETIC_PRODUCER", "reviewed_by": "SYNTHETIC_REVIEW", "reviewed_at_utc": REVIEWED_AT}
        for kind, path in evidence
    ]
    return write_tables(root, manifest, samples, folds, exclusions_for(samples, folds))


def load_fixture(path):
    return (json.loads(path.read_text()), *(
        common.read_csv(path.parent / filename)[1] for filename in ("samples.csv", "fold_assignments.csv", "exclusions.csv")
    ))


def mutate_row(samples, group_name, values):
    index = 2 * list(GROUPS).index(group_name)
    samples[index].update(values)


def replace_evidence(root, manifest, samples, kind, old_sha, content):
    match = next(record for record in manifest["evidence"] if record["kind"] == kind and record["sha256"] == old_sha)
    path = root / match["path"]
    path.write_bytes(content)
    new_sha = common.digest_file(path)
    match["sha256"] = new_sha
    for row in samples:
        for field, value in row.items():
            if value == old_sha:
                row[field] = new_sha


def result(case, expected, observed):
    return {"case": case, "expected": expected, "observed": observed, "status": "PASS",
            "formal_fit": 0, "prediction_calls": 0}


def run_tests(root):
    manifest_path = build_fixture(root / "baseline")
    good_sha = common.digest_file(manifest_path)
    bundle = common.validate_manifest(manifest_path, good_sha, allow_synthetic=True)
    h1 = bundle["group_counts"]["H1_PHASE"]["F1"]
    if h1["train_eventless_rows"] != 1 or h1["development_eventless_rows"] != 1 or h1["train_events"] or h1["development_events"]:
        raise AssertionError("Eventless H1 controls were dropped or counted as invented events")
    if bundle["assigned_group_sample_count"] != 12:
        raise AssertionError("Expected twelve group-specific memberships")
    results = [result("H1_NO_REAL_EVENT_NO_ROOT_OR_WAVE", "PASS_H1", "Both H1 partitions accepted; two eventless observations")]
    portable, manifest = common.safe_export_payload(bundle, allow_synthetic=True)
    h1_header, _ = common.read_csv_bytes(portable["COMMON_SAMPLES_H1_PHASE.csv"])
    h2_header, _ = common.read_csv_bytes(portable["COMMON_SAMPLES_H2_SUPPORT.csv"])
    if {"event_id", "raw_root_anchor_id", "wave_id", "support_label"} & set(h1_header):
        raise AssertionError("H1 export exposed invented identities or unrelated targets")
    if "pullback_end_date" in h2_header:
        raise AssertionError("H2 export exposed an outcome-time lifecycle boundary")
    if manifest["schema"] != "p515-gemini-export/2" or manifest["input_scope"] != "SYNTHETIC_ONLY":
        raise AssertionError("R1.3 synthetic export preview lost its scope identity")
    results.append(result("R1_3_EXPORT_METADATA_ISOLATION", "PASS_EXPORT_IN_MEMORY", "H1 preserves allowed feature union without event IDs or other targets"))

    def reject(name, expected, mutation=None, incorrect_sha=False, synthetic=True):
        work = root / name
        shutil.copytree(manifest_path.parent, work)
        target = work / manifest_path.name
        data, samples, folds, exclusions = load_fixture(target)
        if mutation:
            mutation(work, data, samples, folds, exclusions)
        write_tables(work, data, samples, folds, exclusions)
        try:
            common.validate_manifest(target, "0" * 64 if incorrect_sha else common.digest_file(target),
                                     allow_synthetic=synthetic)
        except ValueError as error:
            if expected not in str(error):
                raise AssertionError(f"{name} rejected for wrong reason: {error}") from error
            results.append(result(name, f"REJECT: {expected}", str(error)))
        else:
            raise AssertionError(f"{name} unexpectedly passed")

    def field(name, expected, group_name, **changes):
        reject(name, expected, lambda _p, _m, samples, _f, _e: mutate_row(samples, group_name, changes))

    field("H1_INVENTED_EVENT_ID", "NO_REAL_EVENT requires blank event_id", "H1_PHASE", event_id="FABRICATED_1")
    field("H1_INVENTED_ROOT", "no invented event lineage", "H1_PHASE", root_anchor_id="FABRICATED_1")
    field("H2_MISSING_RAW_ROOT", "require a certified raw root", "H2_SUPPORT", event_identity_status="NO_REAL_EVENT",
          **{key: "" for key in ("event_id", *common.EVENT_EVIDENCE_FIELDS[4:], "event_lineage_sha256")})
    def empty_certified_root(_path, _manifest, samples, _folds, _exclusions):
        mutate_row(samples, "H2_SUPPORT", {"raw_root_anchor_id": ""})
    reject("H2_CERTIFIED_EVENT_MISSING_ROOT", "require a certified raw root", empty_certified_root)
    field("H2_MISSING_WAVE", "require a certified raw root", "H2_DEPTH", wave_id="")
    field("H3_MISSING_SAME_ROLE_HISTORY", "lacks hash-bound same_role_history", "H3_SUPPORT", same_role_history_sha256="")
    field("H4_MISSING_SECTOR_PIT", "sector_pit_status must be VERIFIED_DATED", "H4_SUPPORT", sector_pit_status="UNKNOWN")
    field("CORPORATE_ACTION_UNKNOWN", "corporate_action_pit_status must be VERIFIED_DATED", "H1_PHASE", corporate_action_pit_status="UNKNOWN")
    field("SUSPENSION_UNKNOWN", "suspension_status must be VERIFIED_DATED", "H1_PHASE", suspension_status="UNKNOWN")
    field("EXCHANGE_CALENDAR_UNKNOWN", "exchange_calendar_status must be VERIFIED_DATED", "H1_PHASE", exchange_calendar_status="UNKNOWN")
    field("EXPOSED_DEV_REJECTED_FROM_FROZEN_FOLD", "EXPOSED_DEV and unknown exposure", "H1_PHASE", exposure_status="EXPOSED_DEV")
    field("LABEL_MATURE_AT_DEV_START", "matures too late", "H1_PHASE", label_maturity_date="20260205")
    field("H1_FEATURE_DOES_NOT_MATCH_RAW", "does not match the D-only RAW derivation", "H1_PHASE", bar_body_fraction="0.99")
    reject("MANIFEST_SHA_MISMATCH", "exact manifest bytes", incorrect_sha=True)
    reject("SYNTHETIC_FORBIDDEN_ON_NORMAL_INTAKE", "SYNTHETIC_ONLY is confined", synthetic=False)
    reject("SYNTHETIC_FIXTURE_CANNOT_BECOME_SUPERVISED_BY_SCOPE_CHANGE",
           "cannot use known synthetic identities",
           lambda _p, manifest, _s, _f, _e: manifest.update(input_scope="FROZEN_SUPERVISED"), synthetic=False)

    def mutate_raw(conflict):
        def change(root, manifest, samples, _folds, _exclusions):
            row = samples[0]
            old_sha = row["raw_prefix_sha256"]
            entry = next(e for e in manifest["evidence"] if e["sha256"] == old_sha)
            path = root / entry["path"]
            header, bars = common.read_csv(path)
            if conflict == "security":
                bars[0]["ts_code"] = "000555.SZ"
            else:
                bars[-1]["trade_date"] = "20260109"
            observed = row["observation_evidence_sha256"]
            replace_evidence(root, manifest, samples, "raw_prefix", old_sha, common.csv_bytes(header, bars))
            cert_path = root / "observation_certification.csv"
            cert_fields, cert_rows = common.read_csv(cert_path)
            next(e for e in cert_rows if e["sample_id"] == row["sample_id"])["raw_prefix_sha256"] = row["raw_prefix_sha256"]
            replace_evidence(root, manifest, samples, "observation_certification", observed,
                             common.csv_bytes(cert_fields, cert_rows))
        return change

    reject("SECURITY_IDENTITY_CONFLICT", "RAW prefix security identity conflict", mutate_raw("security"))
    reject("RAW_D_PLUS_ONE_INJECTION", "includes a bar after D", mutate_raw("future"))

    def tamper_raw(root, manifest, _samples, _folds, _exclusions):
        entry = next(e for e in manifest["evidence"] if e["kind"] == "raw_prefix")
        path = root / entry["path"]
        path.write_bytes(path.read_bytes() + b"\n")
    reject("RAW_FILE_SHA_MISMATCH", "Evidence must be same-bundle hash-bound", tamper_raw)

    def recycle_event(_path, _manifest, samples, folds, exclusions):
        train = samples[6]
        dev = samples[7]
        dev.update(stable_security_id=train["stable_security_id"], event_id=train["event_id"])
        # A second, strictly later development fold reuses this event's identity.
        extra = {**dev, "sample_id": "SYNTHETIC_REUSED_EVENT", "observation_date": "20260206"}
        samples.append(extra)
        folds.extend([
            {**next(f for f in folds if f["sample_id"] == train["sample_id"]), "fold_id": "F2"},
            {**next(f for f in folds if f["sample_id"] == dev["sample_id"]), "sample_id": extra["sample_id"], "fold_id": "F2"},
        ])
        exclusions[:] = exclusions_for(samples, folds)
    reject("SAME_EVENT_REUSED_ACROSS_DEV_FOLDS", "Same-security event or raw root reused across development folds", recycle_event)

    def overlap_train_dev(_path, _manifest, samples, _folds, _exclusions):
        samples[7].update(stable_security_id=samples[6]["stable_security_id"], event_id=samples[6]["event_id"])
    reject("SAME_EVENT_OVERLAPS_TRAIN_DEV", "Same-security root/event overlap", overlap_train_dev)

    def mutate_side_evidence(kind, field, value_to_set, sample_index):
        def change(root, manifest, samples, _folds, _exclusions):
            match = next(e for e in manifest["evidence"] if e["kind"] == kind)
            header, records = common.read_csv(root / match["path"])
            next(r for r in records if r["sample_id"] == samples[sample_index]["sample_id"])[field] = value_to_set
            replace_evidence(root, manifest, samples, kind, match["sha256"], common.csv_bytes(header, records))
        return change

    reject("H3_HISTORY_AVAILABLE_AFTER_D", "H3 same-role history lineage", mutate_side_evidence(
        "same_role_history", "available_at", "2026-01-09T16:00+08:00", 8))
    reject("H4_SECTOR_PUBLISHED_AFTER_D", "Sector membership version or PIT", mutate_side_evidence(
        "sector_membership", "published_at", "2026-01-09T16:00+08:00", 10))
    reject("H1_JUDGES_NOT_INDEPENDENT", "two distinct independent judges", mutate_side_evidence(
        "independent_label_adjudication", "judge_b", "SYNTHETIC_JUDGE_A", 0))

    prep = root / "preparation"
    shutil.copytree(manifest_path.parent, prep)
    fixture, rows, _, _ = load_fixture(prep / manifest_path.name)
    prep_rows = rows[:2]
    for row in prep_rows:
        row.update(**common.PREPARATION_STATUS, exposure_status="EXPOSED_DEV", phase_label="", label_confidence="PENDING",
                   exchange_calendar_status="UNKNOWN", suspension_status="UNKNOWN", corporate_action_pit_status="UNKNOWN",
                   amount_unit="UNKNOWN")
    source_shas = {row["raw_prefix_sha256"] for row in prep_rows}
    fixture["evidence"] = [
        {**item, "status": "SOURCE_SHA_VERIFIED"} for item in fixture["evidence"]
        if item["kind"] == "raw_prefix" and item["sha256"] in source_shas
    ]
    fixture.update(input_scope="ADJUDICATION_PREPARATION", windows=None, pit_cutoff_date=None, development_label_cutoff=None,
                   provenance={"plan_author": "SYNTHETIC_PREP"})
    prepared_manifest = write_tables(prep, fixture, prep_rows, [], exclusions_for(prep_rows, []))
    prepared = common.validate_manifest(prepared_manifest, common.digest_file(prepared_manifest))
    if prepared["assigned_group_sample_count"] or prepared["excluded_group_sample_count"] != 12:
        raise AssertionError("Adjudication preparation generated supervised membership")
    try:
        common.safe_export_payload(prepared)
    except ValueError as error:
        if "requires a frozen supervised bundle" not in str(error):
            raise
    else:
        raise AssertionError("Pending adjudication preparation escaped into portable supervised export")
    results.append(result("H1_RAW_PREP_WITH_UNCERTIFIED_HISTORY", "PASS_PREP_ONLY",
                          "Two exposed D-only samples hash verified; none assigned; supervised export refused"))

    runner = Path(common.__file__).with_name("p515_local_training.py")
    formal = subprocess.run([sys.executable, str(runner), "--output", str(root / "not_written"),
                             "--research-root", str(root), "--audit", str(root),
                             "--certified-development-manifest", str(manifest_path)],
                            capture_output=True, text=True, check=False)
    if formal.returncode != 2 or "formal execution awaits" not in formal.stderr or (root / "not_written").exists():
        raise AssertionError("Production runner no-fit hold was not observed before I/O")
    results.append(result("FORMAL_ESTIMATOR_RUNNER_HOLD", "REJECT_BEFORE_IO", "runner exited 2 and wrote no result"))
    return results


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--report", type=Path, required=True)
    args = cli.parse_args()
    with TemporaryDirectory(prefix="p515-r13-admission-") as directory:
        results = run_tests(Path(directory))
    write_csv(args.report, tuple(results[0]), results)
    print(json.dumps({"checks": len(results), "status": "PASS_SYNTHETIC_ADMISSION_ONLY",
                      "formal_fit": 0, "prediction_calls": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
