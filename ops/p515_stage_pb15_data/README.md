# P515 Stage PB15 data materialization

This isolated research utility materializes historical screen/R2 candidates and PB15 labels. It does not fit or score a model. The final source edit removes the second candidate-ledger append; `candidate_docs` remains the single candidate buffer and `flush_shard_buffers()` remains its writer.

## Entrypoints and source graph

- `stage_pb15_materialize.py --self-test`: pure synthetic contract check; no Reader, R2 run, or model call.
- `stage_pb15_materialize.py --freeze`: writes the pre-read scope/config/code identity record.
- `stage_pb15_materialize.py --run`: bounded four-shard materialization using the same-generation V4 Reader, the frozen D17 5,572-security disposition, original `screen.py` daily screen rules, frozen R2 `run_symbol`/effective calendar, and the bound feature-wiring source. Source paths and SHA-256 identities are recorded in the run's `SOURCE_REFERENCES.json` and `SOURCE_AST_BINDING.json`.
- `recover_outputs_v1.py`: read-only recovery from the existing shard ledgers. It audits exact duplicate candidate rows, removes only byte-identical duplicates in a separate output directory, and calls the frozen pure fold/serialization function. It does not call the Reader, R2, feature builder, or model.

The data path is: D17 universe → bounded Reader shards → historical screen and R2 lifecycle → candidate/label/feature records → buffered shard flush → fold, maturity, and 80-byte input serialization. The recovery path starts from the saved candidate shards and creates `recovery_v1/CANONICAL_MATERIALIZATION/`; it does not replace the original run.

## This run and version identities

- Task run: `p515-stage-pb15-20261119T1407550800-87f5df8cf3b949da9d473b7dc2d63ea2` under `artifacts/p515_stage_pb15_data_materialization_r1_v1/`.
- Frozen executor used for the actual data read: SHA-256 `bd7a9b218c3204ea69b8657424b0bcf5ca19e585eab7a07fab0d8361deca26f1`. Its snapshot and pre-read SHA remain unchanged in the run archive. That version wrote each candidate twice; the original ledgers and insufficient admission result are preserved.
- Current isolated executor after removing the duplicate append: SHA-256 `53bdf9f827b68833d861ec2ec4d6eaf7b0e45c3c63b9e9bd76504d64e3b4394c`. This corrected version was syntax-checked and synthetic-self-tested only; it was not used to re-read or rebuild the historical data.
- Recovery executor: SHA-256 `09c218e81c864ae2ac9584a8963788f2601a5253119472e3b3883bff59231602`; it completed with recorded exit code 0. The original materializer host-process exit code is `UNKNOWN`; a completion marker exists, but no reliable process exit receipt was persisted.
- Frozen source identities: D17 disposition `5be9f005f4fdf50cc14dde4e4d7efdb66ae3753b1e323b0f3f8e43832810e89c`; `screen.py` `5bdbef2fe8dd33016bae095f3984dab06e9a0b3f9f04647e13ce37a5cc9a32ae`; R2 rules `0c5f20e93072701c2c06d9cddcf4b28832888028b67eece2d7fc14be1ccb1381`; feature wiring `873edeaa5c3d6d751a96cc17a94b48e792b43382b3266301915e10e7081cedbd`; V4 Reader `4f096d4995aa862296e0b918ca9dd136bd35dd0b1309efa1239f312be5f25565`; R2 effective calendar `2610bb6e8054351d7066fcfc5876f083d0e43c938f3bea43b17a592d08498a6d`.
- FIT, preprocessing FIT, model API, new probability, static new score, model deserialization, and tuning remained zero. This recovery's data gate is not model training or model acceptance.

## Handoff directory

`artifacts/p515_stage_pb15_data_materialization_r1_v1/` contains the original Prompt and the run directory. In the run directory, frozen inputs/identity receipts, source disposition, merged evidence, four `shards/` directories, and the original failed fold outputs remain intact. `recovery_v1/` contains `DUPLICATE_AUDIT.json`, `DUPLICATE_PAIR_INDEX.jsonl`, `RECOVERY_MANIFEST.json`, recovery counters/receipts, and `CANONICAL_MATERIALIZATION/` with the de-duplicated ledger, matrix, row index, fold membership/gates, stage counts, and data-admission result. `SUPPLEMENTAL_EXECUTION_RECEIPT.json` records the original run and recovery separately.

## Rollback

Rollback of the isolated source handoff means removing only these isolated source files and any link that points to them. Do not delete or overwrite the frozen run, original duplicated ledgers, recovery evidence, or their manifests. Do not rerun the real Reader, R2, historical materialization, training, or scoring as part of rollback.
