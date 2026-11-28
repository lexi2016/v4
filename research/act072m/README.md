# ACT-072M local VLM run

ACT-072M consumes the frozen ACT-071B V1.1 cases and frozen ACT-072S prompt. The runner uses the pinned MLX-VLM 0.8.1 runtime and versioned local Qwen2.5-VL 3B 4-bit assets. The publisher-verified download receipt fixes every asset name, size and SHA-256. It also fixes the frozen weight digest independently of the receipt. Sampling is greedy with seed 720 and a 6144-token generation cap.

Run from this worktree using the ACT-072M stage interpreter:

```sh
"$STAGE/.venv/bin/python" -B -m research.act072m.run_case smoke-load --stage-dir "$STAGE"
"$STAGE/.venv/bin/python" -B -m research.act072m.run_case preflight \
  --stage-dir "$STAGE" --case-dir "$STAGE/frozen_A_case_inputs/T01"
"$STAGE/.venv/bin/python" -B -m research.act072m.run_case infer \
  --stage-dir "$STAGE" --case-dir "$STAGE/frozen_A_case_inputs/T01"
```

`smoke-load` initializes the runtime with local weights in its own offline subprocess. It receives no case or prompt and performs zero decodes. `preflight` checks the case and model pins without importing the model runtime. An official `infer` reserves one `attempts/T01` directory exclusively. A new sandboxed Python process instantiates the model once and calls the streaming generation API once. An existing reservation blocks another attempt for the same case.

Each user turn contains the exact UTF-8 frozen prompt, one image and the three exact text attachments, carried in named attachment boundaries. The checkpoint's native chat template supplies its role and image tokens. The runner checks that the rendered template contains the exact original text blocks and one image token. Prompt, vision and automatic prefix cache reuse are disabled. The kernel sandbox blocks networking and restricts project artifact access to this case's four files, the frozen prompt, the runtime and model assets, and the worker's own attempt files.

The original streamed text is appended byte-for-byte to `T01_raw.txt`. `T01.json` copies those bytes, with a possible removal of one exact outer Markdown fence. A malformed or empty response is preserved for A's validator. `attempt.json` is the exclusive reservation, `decode_started.json` is the single decode marker, and `launch_receipt.json` records derivative and raw hashes even on child failure. The worker logs outcomes, generation/load duration, tokens, finish reason, peak MLX allocations and peak process RSS in `metrics.json`.

The trusted ACT-071B A receipt and SVG remain with A and are consumed by the unchanged V1.1 validator. ACT-072M performs local inference only with `RESEARCH_ONLY=true`, `S_FIT=0`, `B_FIT=0`, and `PRODUCTION_ALLOWED=false`.

Run standard-library synthetic boundary checks with `python -B -m research.act072m.selftest`. Add `--model-metadata-dir "$STAGE/.local_model/46d4cf06a06ffc1a766c214174f9cbed2f45bcab"` to exercise the native checkpoint template on synthetic content with the pinned Transformers runtime. The latter opens tokenizer metadata and performs no model initialization or generation.
