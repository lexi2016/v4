# Commands run

All commands were read-only until the new handoff package was written. No experiment, test, preflight, model operation, score/truth row read, or registry operation was run.

Project intake:

- `cat START_HERE.md`
- `cat CURRENT_STATE.md`
- `wc -l START_HERE.md CURRENT_STATE.md`
- `sed -n '1,240p' CURRENT_STATE.md`
- `sed -n '241,480p' CURRENT_STATE.md`
- `sed -n '481,720p' CURRENT_STATE.md`
- `sed -n '721,935p' CURRENT_STATE.md`
- `sed -n '917,935p' CURRENT_STATE.md`
- `cat research/hk_burst_f5/README.md`
- `cat research/hk_burst_f5/STATUS.json`
- `cat research/hk_burst_f5/EVIDENCE_INDEX.json`

Static mechanism lookup:

- `rg -n "F5_RFF|RFF Logistic|RFF已保存|saved-eval|saved eval|saved evaluation" CURRENT_STATE.md`
- `rg --files research/hk_burst_f5 | rg -i 'rff|xendcg|saved.?eval|saved.?evaluation|evaluation'`
- `rg -n "def .*eval|def .*truth|join_truth|CANDIDATE_TRUTH_JOIN_DOMAIN_MISMATCH|score_path|scores_path|top3_path|SAVED_EVALUATION|evaluation-only|eval-only|input_binding|output" research/hk_burst_f5/batches/full64_rff_logistic_r1_20260927/src/rff_evaluation_completion.py research/hk_burst_f5/batches/full64_rff_logistic_r1_20260927/src/rff_worker.py research/hk_burst_f5/batches/full64_rff_logistic_r1_20260927/src/rff_candidate_entry.py research/hk_burst_f5/batches/full64_xendcg_r1_20260924/candidate_01/evaluation_recovery_02/src/saved_evaluation_entry.py research/hk_burst_f5/batches/full64_xendcg_r1_20260924/candidate_01/evaluation_recovery_02/src/run_saved_evaluation_r2.py research/hk_burst_f5/batches/full64_xendcg_r1_20260924/candidate_01/src/candidate_worker.py`
- `rg --files research/hk_burst_f5/batches/full64_rff_logistic_r1_20260927 | rg -i 'saved.?eval|evaluation.*(spec|binding|run)|run.*evaluation'`
- `nl -ba research/hk_burst_f5/batches/full64_rff_logistic_r1_20260927/src/rff_worker.py | sed -n '340,405p'`
- `nl -ba research/hk_burst_f5/batches/full64_rff_logistic_r1_20260927/src/rff_worker.py | sed -n '344,394p'`
- `nl -ba research/hk_burst_f5/batches/full64_xendcg_r1_20260924/candidate_01/evaluation_recovery_02/src/run_saved_evaluation_r2.py | sed -n '140,182p'`
- `nl -ba research/hk_burst_f5/batches/full64_xendcg_r1_20260924/candidate_01/evaluation_recovery_02/src/saved_evaluation_entry.py | sed -n '1,55p;285,335p'`
- `nl -ba research/hk_burst_f5/batches/full64_rff_logistic_r1_20260927/src/rff_evaluation_completion.py | sed -n '480,620p'`
- `nl -ba research/hk_burst_f5/batches/full64_xendcg_r1_20260924/candidate_01/evaluation_recovery_02/src/saved_evaluation_entry.py | sed -n '1,230p'`
- `nl -ba research/hk_burst_f5/batches/full64_xendcg_r1_20260924/candidate_01/evaluation_recovery_02/src/saved_evaluation_entry.py | sed -n '230,560p'`
- `nl -ba research/hk_burst_f5/batches/full64_xendcg_r1_20260924/candidate_01/evaluation_recovery_02/src/run_saved_evaluation_r2.py | sed -n '1,220p'`
- `nl -ba research/hk_burst_f5/batches/full64_xendcg_r1_20260924/candidate_01/evaluation_recovery_02/src/run_saved_evaluation_r2.py | sed -n '220,480p'`
- `ls -la handoffs/F5_RFF_SAVED_EVAL_RECOVERY_20261009`
- `rg --files research/hk_burst_f5/batches/full64_xendcg_r1_20260924/candidate_01/evaluation_recovery_02/src`
- `rg --files handoffs/F5_RFF_RESUME_EXECUTION_20260928 | rg 'CANDIDATE_INPUT_BINDING|FINAL_RESULT|PREDICTION_SEALED|CANDIDATE_RESULT|RFF_ROUTE_EVENTS|REVIEW_PACKET'`

Metadata-only reads:

- One `python3` JSON allowlist read checked the RFF experiment contract, the supplied RFF R3 binding path, the report's RFF binding copy, and XENDCG R2 RUN_SPEC/INPUT_BINDING; it printed only JSON keys and selected identity, resource, and evaluation-contract metadata. It did not open referenced data files.
- One `python3` JSON allowlist read inspected only the seal and binding metadata for candidate artifact/control paths and SHA values, plus evaluation row/session/slot counts. It did not open candidate scores, Top3, model, or truth files.
- One `python3` JSON allowlist read compared the named code/helper paths and SHA values recorded in RFF and XENDCG bindings. It did not execute those modules.
- `sha256sum` was run on the listed contracts, receipt, and source code files only; no score/truth/model artifact was hashed.
- Package creation used a Python ZIP writer over source `.py` files only and `ZipFile.testzip()` to verify the new code attachment archive.


## Corrective package update after independent review

Read-only evidence commands:

- unzip -l handoffs/F5_RFF_SAVED_EVAL_RECOVERY_20261009/CODE_ATTACHMENTS.zip
- unzip -p handoffs/F5_RFF_SAVED_EVAL_RECOVERY_20261009/CODE_ATTACHMENTS.zip BUNDLE_README.md
- unzip -p handoffs/F5_RFF_SAVED_EVAL_RECOVERY_20261009/CODE_ATTACHMENTS.zip SOURCE_MANIFEST.json
- sha256sum handoffs/F5_RFF_PR5_FIXTURE_MAC_ACCEPTANCE_20261009/pr_head/research/f5-rff-r3/research/hk_burst_f5/batches/full64_rff_logistic_r1_20260927/src/rff_worker.py handoffs/F5_RFF_PR5_FIXTURE_MAC_ACCEPTANCE_20261009/pr_head/research/f5-rff-r3/research/hk_burst_f5/batches/full64_rff_logistic_r1_20260927/tests/test_rff_truth_join.py handoffs/F5_RFF_PR5_FIXTURE_MAC_ACCEPTANCE_20261009/review/INDEPENDENT_MAC_REVIEW_RECEIPT.json
- sha256sum handoffs/F5_RFF_SAVED_EVAL_RECOVERY_20261009/review/INDEPENDENT_PACKAGE_REVIEW_RECEIPT.json

The corrective ZIP was rebuilt from the original attachment plus the exact PR5 accepted worker, its synthetic test file, and the independent Mac review receipt. A Python package-validation script parsed JSON, verified the member manifest SHA values, checked ZIP integrity with ZipFile.testzip(), and confirmed that old package-review receipt bytes were preserved. No test suite, research preflight, score/truth read, model operation, or registry action was run for this correction.
