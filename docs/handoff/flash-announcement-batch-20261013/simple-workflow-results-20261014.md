# Flash announcement simple-workflow experiment, 2026-10-14

Status: IMPLEMENTED and independently REVIEWED offline; real semantic acceptance FAIL. Not integrated or deployed to the canonical manager workbench. The 29-item pressure phase was NOT_RUN.

Baseline commit: f55fc9bde71bb65877fafb6e2631284ab9cf8e64.
Canonical source remains /Users/lexi/Desktop/学习/v4_app and was not modified by this isolated experiment.
Candidate source: /Users/lexi/Desktop/学习/agents调试/助手/qwen_flash_next_20261013/pipeline_canary.
Runtime: Apple Silicon Mac, Python 3.12.13, oMLX 0.7.0, xgrammar 0.2.3, apache-tvm-ffi 0.1.11, official oMLX torch import stub. No full torch install. Model ID qwen3_8_flash_next; retained 27B baseline, no new 27B comparison this round.

Changes:
- Complete immutable article body represented as ordered paragraph/table units; one article per model request and single queue concurrency.
- A single typed complete-or-missing-fact-lookup envelope, native oMLX structured_outputs JSON grammar, Thinking Off.
- Program injects frozen article source/body identities and projects chosen unit IDs to verbatim text and locators. Model claims and judgments remain unchanged; there is no answer corrector.
- Coherent Chinese evidence-first prompt and schema property ordering. Existing 13-field Reader constraints, selection criteria and semantic gate unchanged.
- First nonempty content timing measured separately from first SSE event, bounded retry, resume and missing-fact web controls.
- Current implementation still sends every article to the model. It does not implement deterministic administrative-form extraction or a semantic rule-based triage before model use.

Validation:
The independent reviewer reran the six v5 focused tests with the specified local runtime:
PYTHONDONTWRITEBYTECODE=1 <runtime>/venv/bin/python -m unittest
test_batch_runner.BatchRunnerTests.test_simple_workflow_prompt_has_one_envelope_schema_and_lookup_shapes_fail_closed
test_batch_runner.BatchRunnerTests.test_simple_workflow_prompt_requires_unit_local_grounded_claims_and_preserves_reader_contract
test_batch_runner.BatchRunnerTests.test_simple_workflow_schema_reorders_only_properties_and_keeps_frozen_constraints
test_batch_runner.BatchRunnerTests.test_simple_workflow_frozen_prompt_hash_pin_matches_current_prompt
test_batch_runner.BatchRunnerTests.test_simple_workflow_lookup_round_is_typed_and_returned_as_untrusted_user_data
test_batch_runner.BatchRunnerTests.test_simple_workflow_projects_source_units_and_passes_business_fields_through -v
All six PASS. Previously approved unchanged checks were reused; no redundant full-suite rerun.
Offline exact-tokenizer XGrammar compilation and property-order probe PASS. Reported grammar memory is a compiler metric, not confirmed resident service allocation.

Real visible test:
- Six frozen real articles captured 2026-10-13, same source/body/unit identities as earlier candidates.
- Started 2026-10-14T10:25:11.358Z; finished 2026-10-14T10:28:16.124Z.
- Resident model, no extra warmup or manual loading included in this measurement. Legacy run-receipt cold-load wording must not be interpreted as an observed cold model load.
- 184.731 s end to end; 184.676 s summed model streams; one request round and attempt per job, zero retries and web lookups.
- UI job wall seconds: 20.917, 18.319, 22.036, 35.900, 39.063, 48.496.
- First nonempty content seconds: 8.384, 2.144, 3.843, 4.029, 8.119, 10.113.
- 4,993 completion tokens. Completion tokens / total stream wall is an estimate, not isolated decoder throughput.
- Mechanical checks: 6/6 success. Independent semantic review: 0/6 fully accepted under frozen criteria.
- Corrected earlier invented name, referenced-title-as-completed-payment and reporting-period problems. Remaining failures: mixed-unit claims with incomplete citations, incorrect ratio denominator, incorrect price range, missing issuer facts and unsupported transaction-level inference.
- v4 real run: 163.746 s and 0/6 semantic passes. V5 is slower; no qualified speed/accuracy improvement claimed.
- Pressure cohort 29 has one overlap with canary and would need 28 new jobs. It never ran; UI overlap count does not prove pressure execution.
- One sparse system-wide GPU reading at 2026-10-14T10:27:12Z was 64%; model process CPU 72.9% and RSS 6,710,752 KiB nearby. These are snapshots, not run averages or exclusive GPU attribution. RSS excludes significant GPU allocation.

Local immutable evidence root:
evidence/simple-workflow-20261014/compact-v5-evidence-first/
Manifest SHA-256: 6e87bcf8ffb723e326f4765b8f3ee211872d22a21a4651334edb0ee191e10c64
Prompt SHA-256: 89ef6779d46181f570a7c30a5f785524f9111cdc2e28bfc0e7faedc7aff46180
Normalized structured schema SHA-256: 30816be27a055151df27a26a683b093e502c937573feee7ae2a7e6150511bc07
Ordered schema SHA-256: bfea12651d488e91499e76de12c4f8997d591bf87514d1df9eb8b9f2eae125da
No raw source, model responses, UI screenshots, input manifests, credentials or runtime configuration are uploaded here.

Current source hashes:
batch_runner.py: 057781017060db0088a1a4f14216295ba9a0dd3c36af0c9dd89ae2845d48beb1
automatic_canary_server.py: ce1451b0b84de3d4dfcff46a75485a16fe3066cd5aedfee88a48387d4d1c2551
test_batch_runner.py: a2f0d7e6fc8738a2387167fed414c8de97af2a982f7bbcc0c9e683979f63095e
test_automatic_canary_server.py: 27311aba96e18dae9787b19aac859c78ee7a13bde2bdca5bd33844f5b37f6866

Research-only: production_allowed=false, buy_gate_updated=false, orders_sent=false.
