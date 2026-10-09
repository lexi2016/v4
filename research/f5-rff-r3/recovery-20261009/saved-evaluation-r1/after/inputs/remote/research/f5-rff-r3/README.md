# F5 RFF R3 source slice

This directory is a review-ready source subset for `research/f5-rff-r3/` in the existing private `lexi2016/v4` repository. It is staged locally only; this task did not upload or create a remote branch.

## Maintenance target

After the parent accepts and uploads this snapshot, the private repository path `research/f5-rff-r3/` on branch `f5-rff-r3-collaboration` is the sole maintenance target for this shared slice. Treat the original Factor Factory workspace as provenance and historical source, not as a second active copy to edit in parallel. This local export remains a candidate snapshot until the first reviewed commit exists.

Any future Chat-generated change must start from a named repository commit and arrive as a commit-based diff or pull request. Review that diff against its stated base; do not replace the exported tree wholesale or sync unreviewed files from the local workspace.

## What this snapshot covers

The current binding identifies 11 source files under `binding.code_files` (`code_sha256` `bf9ae8ec0352a56106a976e8dc8347f4270837d605e20f117cb534a8d683060e`). The export carries those files, the binding's explicitly named runtime helpers/contracts, their selected supporting source files, five focused RFF test sources, and the frozen `EXPERIMENT_CONTRACT.json`. `SOURCE_MAP.json` records each original project-relative path, exported path, byte count, and SHA-256. One frozen evaluator helper came from the validated handoff's `source_current` snapshot; the source map marks that provenance.

## Current execution status

The upstream RFF execution ran one fit. The original-session readback reports about 0.90 seconds for the fit step and about 6.5 seconds for the process; the subsequent evaluation failed, and the L04 completion receipt was not generated. A final root cause and terminal receipt are not available in this snapshot. The single fit budget is consumed; do not retrain. These are inherited upstream status facts, not measurements recreated by this export.

The engineering scope here is source identity and the RFF dependency/preflight, runtime-adaptation, completion, and L04 boundary checks represented by these files. This export does not prove model performance or acceptance, and it provides no reviewer authorization, parent authorization, or release. No tests were rerun while preparing this source slice. The four-row metadata file is sanitized configuration-change context only, explicitly not an approval or execution instruction.

This is not a complete, independently runnable Factor Factory project. It omits real inputs and truth, models/checkpoints, run specs, local registries, virtual environments, output artifacts, handoff ZIPs, and GitHub automation. Do not run training from this slice.

## Original local mapping

Paths in the snapshot preserve their original repository-relative layout where the sources live in the Factor Factory workspace. The local root used to assemble it was the Factor Factory workspace (`因子工厂`); source mappings use project-relative paths, with no absolute local root embedded in `SOURCE_MAP.json`. The frozen evaluator helper is mapped to its validated handoff source snapshot. See `SOURCE_MAP.json` for the exact per-file mapping and hashes.
