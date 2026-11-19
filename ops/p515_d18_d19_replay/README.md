# D18 final-model replay and D19 review

The fixed task is P515_MAC_D18_LATEST_TRAINED_MODEL_SELECTION_D19_REVIEW_V1. This isolated utility uses the existing D18 screen and native R2 source, the accepted GEMINI C010 FINAL_9 weight bytes, and the original CODEX frozen scaler.

- `replay.py prepare` verifies the D18 universe and Reader identity, rebuilds K3 qualification, and persists 20-column input bytes plus native row keys. Existing valid preparation results are returned without recalculation.
- `replay.py infer` requires the controller's real Drive prelaunch readback, checks each frozen file and the final inference source hash, reserves an exclusive execution token before deserialization, transforms the frozen scaler, clips the 16 numeric columns, and makes one complete predict_proba call. A return is written as raw little-endian float64 before output checks and ranking. There is no retry path.
- `replay.py evaluate` requires a persisted ranking freeze before reading D19 values. It consumes the bound V4 Reader or the V4 accepted official-day snapshot through its existing codec. It reports raw unadjusted D18–D19 price changes for official-day files and records unknown ex-right treatment, source gaps, and the upstream authority's global state.
- `replay.py selftest` checks serialization and exact-tie ordering with synthetic values, with zero Reader, model, and deserialization calls.

The controller owns `PRELAUNCH_READBACK.json` and `EVALUATION_SOURCE_BINDING.json` in this batch's `run/` directory. Full bounds are in the original Prompt. Generated matrices and raw probabilities are research artifacts. Parent training budgets and production objects are outside this utility's writes.

The preparation phase was run while the inference/evaluation implementation was still being completed. PREPARED.json retains its then-current source SHA. No whole-file copy was saved at that instant. SOURCE_FINALIZATION.json records that evidence limit and the final source identity used in this batch's real prelaunch package. Preparation was not rerun.

Rollback consists of removing the isolated source entry or references to it. Preserve the batch's frozen input, raw probability, ranking, and failure evidence.
