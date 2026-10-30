"""Propose a transitive equivalence binding; never activate acceptance metadata."""
import argparse
import ast
import copy
import hashlib
import json
from pathlib import Path
import subprocess


OLD_SHA = "33b2abe30026749c22bf83bff4370d9b2ec1d9280491610518871853421b6fe7"
NEW_SHA = "6757f2bada82fe222ef224fbf58361a7f499f4c8664575b9d1a0abe7a9ecf568"
BASELINE = "69d31e8971f38a00b4e76f84c48b45f08a3e4cb2"
CHANGED = {"_controller_quarantine_fact", "_verified_sop_skip"}
ADDED = {"_fixed_lifecycle_fact", "_two_brokers_quarantine_fact"}
CONSTANTS = {"_LIFECYCLE_ASSET_PATH", "_CONTROLLER_ARTIFACTS", "_TWO_BROKERS_SHA"}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def ref(path):
    return dict(path=str(path.resolve()), sha256=sha(path.read_bytes()))


def checked(reference):
    path = Path(reference["path"])
    assert path.is_absolute() and sha(path.read_bytes()) == reference["sha256"], str(path)
    return json.loads(path.read_text())


def ast_equivalence(old, new):
    trees = [ast.parse(raw) for raw in (old, new)]
    functions = [{n.name: ast.dump(n, include_attributes=False) for n in tree.body
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))} for tree in trees]
    a, b = functions
    assert a.keys() <= b.keys() and b.keys() - a.keys() == ADDED
    assert {name for name in a if a[name] != b[name]} == CHANGED

    def retained(tree):
        result = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in CHANGED | ADDED:
                continue
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in CONSTANTS for t in node.targets):
                continue
            result.append(ast.dump(node, include_attributes=False))
        return result
    assert retained(trees[0]) == retained(trees[1]), "UNRELATED_MODULE_AST_CHANGED"
    return dict(unchanged_functions=sorted(name for name in a if a[name] == b[name]),
                changed_quarantine_functions=sorted(CHANGED), added_quarantine_functions=sorted(ADDED),
                added_binding_constants=sorted(CONSTANTS), all_other_module_ast_identical=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--acceptance", type=Path, required=True)
    parser.add_argument("--candidate-receipt", type=Path, required=True)
    args = parser.parse_args()
    b = args.evidence_root
    before = b / "BEFORE_qfq_convention_acceptance.json"
    assert before.read_bytes() == args.acceptance.read_bytes(), "ACCEPTANCE_CAS_DRIFT"
    accepted = checked(ref(before))
    oracle_before = b / "BEFORE_qfq_futu_oracle.json"
    assert oracle_before.read_bytes() == args.acceptance.with_name("qfq_futu_oracle.json").read_bytes(), "ORACLE_CHANGED"
    initial = checked(accepted["initial_oracle_receipt"])
    assert initial["status"] == "PASS_FUTU_DISPLAY_ORACLE" and initial["asof_date"] == accepted["initial_asof_date"]
    assert initial["code_binding"] == accepted["code_binding"]
    assert len(accepted["approved_tuple_entries"]) == 1
    prior_entry = accepted["approved_tuple_entries"][0]
    prior = checked(prior_entry["equivalence_receipt"])
    checked(prior_entry["independent_review"])
    assert prior_entry["status"] == "PASS" and prior_entry["reviewer_id"]
    assert prior["status"] == "PASS_INPUT_EVENT_VOLUME_EQUIVALENCE"
    assert prior["baseline_code_binding"] == accepted["code_binding"]
    assert prior["code_binding"] == prior_entry["code_binding"]
    assert all(prior["assertions"][name] is True for name in
               ("events_parity", "volume_math_parity", "original_provider_dates_preserved", "source_and_code_pins_verified"))
    candidate = checked(ref(args.candidate_receipt))
    binding = {name: candidate[name] for name in accepted["code_binding"]}
    assert {name for name in binding if binding[name] != prior["code_binding"][name]} == {"factor_cache_sha256"}
    assert prior["code_binding"]["factor_cache_sha256"] == OLD_SHA and binding["factor_cache_sha256"] == NEW_SHA
    old = subprocess.check_output(["git", "-C", str(args.worktree), "show", BASELINE + ":ops/research_panel_factor_cache.py"])
    new = (args.worktree / "ops/research_panel_factor_cache.py").read_bytes()
    assert sha(old) == OLD_SHA and sha(new) == NEW_SHA
    ast_result = ast_equivalence(old, new)
    sop_review_ref = ref(b.parent / "INDEPENDENT_REVIEW_PASS.json")
    sop_review = checked(sop_review_ref)
    assert sop_review["verdict"] == "PASS" and sop_review["reviewer"] == "/root/sop_binding_reviewer"
    source_freeze = checked(dict(path=str(b.parent / "WRITER_SOURCE_FREEZE.json"), sha256=sop_review["source_freeze_sha256"]))
    assert next(item["sha256"] for item in source_freeze["files"] if item["path"] == "ops/research_panel_factor_cache.py") == NEW_SHA
    proof = dict(status="PASS_INPUT_EVENT_VOLUME_EQUIVALENCE", independent_review_status="PENDING",
        proof_kind="DERIVED_TRANSITIVE_SOP_ONLY_AST_EQUIVALENCE", author_id="/root/sop_binding_writer",
        baseline_code_binding=accepted["code_binding"], code_binding=binding, assertions=prior["assertions"],
        chain=dict(prior_equivalence=prior_entry["equivalence_receipt"], prior_independent_review=prior_entry["independent_review"],
                   prior_acceptance=ref(before), sop_independent_review=sop_review_ref,
                   initial_oracle_receipt=accepted["initial_oracle_receipt"], original_oracle=ref(oracle_before), baseline_commit=BASELINE),
        ast_equivalence=ast_result, old_factor_cache_sha256=OLD_SHA, new_factor_cache_sha256=NEW_SHA,
        source_claim="Only quarantine/nonadmission binding changed; all provider, event, carry and math AST retained",
        provider_calls=0, new_displayed_oracle=False, oracle_asof_date_unchanged=accepted["initial_asof_date"],
        RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
    proof_path = b / "DERIVED_EQUIVALENCE_PROPOSAL.json"
    raw = (json.dumps(proof, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    if proof_path.exists():
        assert proof_path.read_bytes() == raw, "IMMUTABLE_PROPOSAL_CONFLICT"
    else:
        proof_path.write_bytes(raw)
    proposal = copy.deepcopy(accepted)
    proposal["approved_tuple_entries"] = [dict(status="PENDING_INDEPENDENT_REVIEW", reviewer_id=None,
        code_binding=binding, equivalence_receipt=ref(proof_path), prior_approved_entry=prior_entry,
        prior_acceptance=ref(before))]
    (b / "ACCEPTANCE_PROPOSAL_NOT_ACTIVATED.json").write_text(json.dumps(proposal, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print(json.dumps(dict(status="PROPOSAL_PREPARED_NOT_ACTIVATED", proof=ref(proof_path), unchanged_functions=len(ast_result["unchanged_functions"]))))


if __name__ == "__main__":
    main()
