"""Measure the existing owner gates and two reservation ledgers without a claim."""
from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import plistlib
import shutil
import sys

from ops import research_storage_governance as gov
from ops import research_storage_retention as ret
from ops.research_qfq_task_continuity import _classified_for_other_dates, unclassified_qfq_rows

NONTERMINAL = {"RUNNING", "VALIDATING", "FAILED_RECOVERABLE", "SPACE_BLOCKED"}
D20, D23 = 20261120, 20261123


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def put(destination, data):
    with destination.open("x", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def allocation_forecast(policy, registry, state, legacy_key, target_key):
    settings = registry.config
    pointer_state = ret.pointer_state(policy)
    pair_bytes = sum(item["target_stat"]["size"] for item in pointer_state.values())
    requested = max(policy["minimum_build_bytes"], math.ceil(pair_bytes * 3.5))
    growth = {}
    try:
        growth = ret.growth_guard(policy, already_current=False)
    except ret.RetentionError as exc:
        growth = {"status": "BLOCKED", "reason": str(exc)}
    else:
        assert growth["predicted_bytes"] == requested

    existing = state["tasks"].get(target_key)
    assert existing is None, "no new-operation footprint can be inferred for an existing task"
    roots = set(settings["accounting_roots"]["ordinary"])
    resident = gov.ordinary_resident_paths(settings)
    roots.update(state.get("resident_baseline_paths") or resident)
    roots.update(resident)
    for row in state["tasks"].values():
        if row["category"] == "ordinary":
            roots.update(row.get("billing_paths", []))
    roots = gov.unique_roots(roots)
    seen = set()
    used = sum(gov.billing_bytes(path, seen=seen) for path in roots if path.exists())

    other_rows = {key:row for key,row in state["tasks"].items()
                  if key != target_key and row["state"] in NONTERMINAL}
    physical = sum(registry.remaining(row) for row in other_rows.values())
    category = sum(row["reserved_bytes"]-row.get("logical_written_bytes",row["written_bytes"])
                   for row in other_rows.values() if row["category"]=="ordinary")
    old = other_rows[legacy_key]
    old_physical = registry.remaining(old)
    old_category = old["reserved_bytes"]-old["logical_written_bytes"]
    assert (old_physical,old_category)==(51335737344,51350585740)
    disk_sampled_at = datetime.now().astimezone().isoformat()
    usage = shutil.disk_usage(registry.disk_root)
    margin = settings["reserve_bytes"]+settings["safety_bytes"]
    capacity = {
      "sample":"ACTUAL_POINT_IN_TIME_NO_CLAIM","disk_sampled_at":disk_sampled_at,
      "formula_status":"CONDITIONAL_ONLY",
      "target_date":D23,"target_key":target_key,"target_charge":"new ordinary, optional_full=false",
      "request_physical_peak_bytes":requested,"request_category_logical_bytes":requested,
      "request_basis":{"current_pair_anchor_bytes":pair_bytes,"multiplier":3.5,
                       "minimum_build_bytes":policy["minimum_build_bytes"],
                       "actual_current_anchor_sha256":{k:digest(Path(v["target"])) for k,v in pointer_state.items()},
                       "new_appended_billing_paths_before_owner_invocation":0},
      "retention_growth_separate_gate":growth,
      "disk":{"path":str(registry.disk_root),"total_bytes":usage.total,"free_bytes":usage.free,
              "free_ratio":usage.free/usage.total,"minimum_free_ratio":settings["minimum_free_ratio"],
              "optional_full":False,"optional_full_min_ratio":settings["optional_full_min_ratio"],
              "ratio_pass":usage.free/usage.total>=settings["minimum_free_ratio"]},
      "physical":{"old_reservation_remaining_bytes":old_physical,
                  "other_remaining_excluding_old_bytes":physical-old_physical,
                  "total_other_remaining_bytes":physical,"reserve_bytes":settings["reserve_bytes"],
                  "safety_bytes":settings["safety_bytes"],"free_less_requests_bytes":usage.free-physical-requested,
                  "headroom_after_reserve_safety_bytes":usage.free-physical-requested-margin},
      "category":{"old_remaining_bytes":old_category,"other_remaining_excluding_old_bytes":category-old_category,
                  "total_other_remaining_bytes":category,"measured_resident_used_bytes":used,
                  "ordinary_limit_bytes":settings["ordinary_peak_budget_bytes"],
                  "projected_bytes":used+category+requested,
                  "headroom_bytes":settings["ordinary_peak_budget_bytes"]-used-category-requested,
                  "billing_roots_count":len(roots),"measured_distinct_inodes":len(seen)},
      "registry_space_invoked_readonly":True,"claim_begin_called":False,
      "actual_admission_status":"NOT_REACHED_CLASSIFICATION_BLOCKED",
    }
    try:
        capacity["registry_space_result"] = registry.space(
            state,target_key,requested,category="ordinary",optional_full=False,
            category_used=used,category_remaining_bytes=requested)
        capacity["conditional_registry_space_decision"] = "PASS_POINT_IN_TIME"
    except gov.SpaceBlocked as exc:
        capacity["conditional_registry_space_decision"] = str(exc)
    return capacity


def main():
    stage, destination, final_child_identity = map(Path,sys.argv[1:4])
    history=Path(__file__).resolve().parents[2]/"v4_main_autorun_integration_20261121"
    historical=read(history/"ROLLBACK_PREIMAGE_MANIFEST.json")
    proof=read(Path(__file__).resolve().parent/"DEPLOYED_MAIN_API_SOURCE_READBACK.json")
    current=proof["current_preimages"]
    candidate=plistlib.loads((stage/"launchd.plist").read_bytes())["EnvironmentVariables"]
    assert Path(gov.__file__).resolve().is_relative_to(stage/"app")
    policy_path=Path(candidate["V4_RESEARCH_RETENTION_POLICY"])
    policy = ret.load_policy(policy_path,expected_sha256=candidate["V4_RESEARCH_RETENTION_POLICY_SHA256"])
    policy_sha=digest(policy_path)
    assert policy_sha==candidate["V4_RESEARCH_RETENTION_POLICY_SHA256"]
    settings=gov.configuration(policy)
    registry=gov.Registry(settings, policy["data_root"])
    registry_sha=digest(registry.path)
    state=registry.read()
    old_source=read(history/"private/OLD_TASK_FULL_ROW.json")
    legacy_key=old_source["old_key"]
    old=state["tasks"][legacy_key]
    assert old==old_source["old"] and registry_sha==historical["registry_sha256"]==old_source["registry_sha256"]
    old_sha=ret.canonical(old)
    active_ownership=gov.owner_state(old["owner"])
    other_active=[{"key":key,"owner_state":gov.owner_state(row["owner"]),"state":row["state"]}
                  for key,row in state["tasks"].items() if row["state"] in {"RUNNING","VALIDATING"}]
    assert active_ownership=="DEAD" and not other_active
    assert not settings.get("qfq_legacy_classification") and not settings.get("qfq_legacy_resume")

    from contracts.trading_calendar import load_market_calendar, resolve_market_states
    release_calendar_policy=stage/"app/contracts/a_share_daily_source_policy.json"
    calendar_ref=read(release_calendar_policy)["calendar"]
    calendar_path=Path(calendar_ref["path"])
    assert digest(calendar_path)==calendar_ref["sha256"]
    calendar=load_market_calendar(calendar_path)
    start=datetime.strptime("20261122","%Y%m%d")
    next_date=next(day for day in ((start+timedelta(days=d)).strftime("%Y%m%d") for d in range(1,8))
                  if resolve_market_states(calendar,day)["a_share"].value=="FULL_TRADING_DAY")
    assert int(next_date)==D23
    child_manifest_sha=digest(final_child_identity)
    master_identity=read(final_child_identity)
    assert master_identity["schema"] == "v4.r4_daemon_a_qfq_identity_probe.v1"
    assert master_identity["status"] == "PASS_READ_ONLY_DAEMON_A_QFQ_IDENTITY"
    child_identity=master_identity["qfq_child_identity"]
    assert child_identity["status"] == "PASS_READ_ONLY_QFQ_CHILD_IDENTITY"
    assert child_identity == master_identity["a_executor_fixture"]["captured_executor_run"]["qfq_identity_probe"]
    child_release_sha=child_identity["release_manifest"]["sha256"]
    assert child_release_sha==child_identity["release_manifest"]["expected_sha256"]==digest(stage/"release-manifest.json")
    assert Path(child_identity["stdlib_root"]).is_relative_to(stage/"runtime")
    assert child_identity["claim_begin_called"] is False and child_identity["admission_called"] is False
    assert child_identity["registry_sha256"] == registry_sha
    assert Path(child_identity["registry_path"]) == registry.path
    assert Path(child_identity["data_root"]) == Path(policy["data_root"])
    assert Path(child_identity["return_root"]) == Path(policy["run_root"])
    assert child_identity["no_user_site"] == 1
    target_key=child_identity["qfq_operation_keys"][str(D23)]
    assert len(target_key) == 64 and all(c in "0123456789abcdef" for c in target_key)
    assert child_identity["no_site"]==0 and child_identity["release_root"]==str(stage)
    assert target_key not in state["tasks"]
    unknown=unclassified_qfq_rows(state,policy["run_root"],target_key)
    assert unknown.get(legacy_key)==old_sha
    scope_path=Path(__file__).resolve().parents[1]/"admission/D20_D11_SCOPE_EVIDENCE.json"
    scope_raw=scope_path.read_bytes()
    scope_sha=hashlib.sha256(scope_raw).hexdigest()
    scope=json.loads(scope_raw)
    assert scope["source_and_schema_identity"]["registry"]["sha256"]==registry_sha
    date_rows=scope["date_semantics_and_row_validation"]
    assert set(date_rows)=={"D20","D11"}
    assert {row["row_key"]:row["row_sha256"] for row in date_rows.values()}==unknown
    prior=read(history/"BILLING_AND_FORMAL_API_READONLY.json")
    protected="candidate_receipt.json"
    owner_receipts=[]
    for root_info in prior["billing_roots"][:2]:
        path=Path(root_info["path"])/protected
        value=read(path)
        actual=digest(path)
        assert actual==root_info["status_receipts"][protected]["sha256"]
        assert value["target_date"]==D20 and Path(value["run_dir"])==path.parent
        assert path.parent.is_relative_to(Path(old["directory"]))
        owner_receipts.append({"path":str(path),"sha256":actual,"target_date":D20,
                               "generation":value["generation_id"],"input_sha256":value["input_sha256"]})
    assert len({row["input_sha256"] for row in owner_receipts})==2
    assert {row["sha256"] for row in owner_receipts}=={
        row["candidate_receipt_sha256"] for row in date_rows["D20"]["owner_receipts"]}
    prior_keys=history/"CANONICAL_IDENTITY_REAL_ROOTS_READONLY.json"
    prior_key=read(prior_keys)["real_d20_operation_keys"]["v4-forward-inputs-20261119-r1"]["legacy_key"]
    assert prior_key==legacy_key
    # Verify the scope evidence's structural branch using real immutable owner receipts.
    # Full admission still has no authorized evidence_closed/reviewer attestation.
    proposed={"classified_rows":{legacy_key:{"row_sha256":old_sha,"target":D20,
       "owner_receipts":[{"path":x["path"],"sha256":x["sha256"]} for x in owner_receipts]}}}
    pinned = {x["path"] for x in read(Path(policy["managed_pin_inventory"]["path"]))["pins"]}
    other_legacy = []
    for key, row_sha in unknown.items():
        if key==legacy_key:
            continue
        row=state["tasks"][key]
        source = [Path(p)/"stage_status.json" for p in row.get("billing_paths", [])
                  if Path(p).parent==Path(row["directory"]) and (Path(p)/"stage_status.json").is_file()]
        assert len(source)==1 and row["attempts"]==1
        p=source[0]
        status=read(p)
        actual=digest(p)
        assert str(p) in pinned and Path(status["run_dir"])==p.parent and status["error"]==row["error"]
        target=status["target_date"]
        assert type(target) is int and target!=D23 and gov.owner_state(row["owner"])=="DEAD"
        assert key==date_rows["D11"]["row_key"] and row_sha==date_rows["D11"]["row_sha256"]
        assert target==date_rows["D11"]["target_date"] and actual==date_rows["D11"]["owner_receipt"]["stage_status_sha256"]
        proposed["classified_rows"][key]={"row_sha256":row_sha,"target":target,
            "owner_receipts":[{"path":str(p),"sha256":actual}]}
        other_legacy.append({"key":key,"row_sha256":row_sha,"state":row["state"],"attempts":row["attempts"],
            "owner_state":"DEAD","target":target,"stage_status_sha256":actual,
            "category_remaining_bytes":row["reserved_bytes"]-row.get("logical_written_bytes",row["written_bytes"]),
            "physical_remaining_bytes":registry.remaining(row)})
    structural=_classified_for_other_dates(proposed,unknown,state,D23)==unknown
    try:
        _classified_for_other_dates(proposed,unknown,state,D20)
    except ret.RetentionError as exc:
        same_date=str(exc)
    else:
        raise AssertionError("same day role accepted a distinct-date classification")
    from ops.research_qfq_task_continuity import qfq_admission_context as check
    from ops import research_panel_qfq as owner
    try:
        check(owner,policy,Path(policy["data_root"]),Path(policy["run_root"]),D23,target_key)
    except ret.RetentionError as exc:
        actual_guard=str(exc)
    else:
        raise AssertionError("missing approved evidence let admission continue")
    assert actual_guard=="QFQ_UNCLASSIFIED_LEGACY_RESERVATION"
    capacity = allocation_forecast(policy,registry,state,legacy_key,target_key)

    assert digest(registry.path)==registry_sha and digest(policy_path)==policy_sha
    assert digest(final_child_identity)==child_manifest_sha
    assert digest(scope_path)==scope_sha
    assert digest(stage/"release-manifest.json")==child_release_sha
    assert all(digest(Path(ref["original_path"]))==ref["sha256"] for ref in current.values())
    assert all(digest(Path(policy["pointers"][role]))==ref["sha256"]
               for role,ref in historical["pointer_originals"].items())
    now=datetime.now().astimezone().isoformat()
    result={
        "captured_at":now, "registry_sha256":registry_sha,"old_row_sha256":old_sha,
        "target_calendar":{"asof":"20261122","next_a_trade_date":next_date,"calendar":calendar_ref,
                           "source_policy_sha256":digest(release_calendar_policy)},
        "actual_child_calculation_manifest_ref":{"path":str(final_child_identity),"sha256":child_manifest_sha,
            "candidate_release_manifest_sha256":child_release_sha,
            "calculation_dependencies_sha256":child_identity["computation_manifest_sha256"],
            "effective_environment_sha256":child_identity["environment_sha256"]},
        "current_live_control_preimage_bound":True,
        "desc":"Separately measured classification evidence and actual point-in-time capacity. No production action.",
        "unique_legacy_ownership":{"status":"CANNOT_CONFIRM","migration":"BLOCKED",
            "old_state":old["state"],"registered_attempts":old["attempts"],"old_owner":active_ownership,
            "other_running_or_validating":other_active,"receipts":owner_receipts,
            "reason":"No immutable mapping of both old attempts and their tokens to one generation. Different inputs."},
        "distinct_date_classification":{"status":"BLOCKED_NO_REVIEWED_CLASSIFICATION_IN_POLICY",
            "intended_schema":"v4.qfq_legacy_task_scope.v1","pool_id":settings["pool_id"],
            "old_key":legacy_key,"proposed_scope":proposed,
            "previous_real_d20_key_record_sha256":digest(prior_keys),"target":D23,"target_child_key":target_key,
            "observed_d20_row_artifact_dates":[D20],
            "observed_all_legacy_target_dates":sorted({D20}|{r["target"] for r in other_legacy}),
            "additional_unclassified_legacy_rows":other_legacy,
            "attempt_scope_evidence":"The D20 row’s two recorded generations share 20261120; its historical actual operation key was derived for that date.",
            "candidate_structure_check":structural,"same_date_branch":same_date,"actual_policy_gate":actual_guard,
            "date_source_evidence_status":"PASS_DATE_SCOPE_D20_D11_LOCAL_REVIEW",
            "related_source_scope_sha256":scope_sha,
            "independent_reviewer_attestation":None,"evidence_closed":None},
        "capacity":capacity,"claim_begin_called":False,"registry_writes":False,"migration":"BLOCKED",
    }
    put(destination,result)
    print(capacity["conditional_registry_space_decision"],capacity["physical"]["headroom_after_reserve_safety_bytes"],
          capacity["category"]["headroom_bytes"],actual_guard)


if __name__=="__main__":
    main()
