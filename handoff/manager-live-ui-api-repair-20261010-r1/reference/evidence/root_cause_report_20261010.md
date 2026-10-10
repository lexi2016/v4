# Manager plan identity: global manifest coupling review

Review scope: read-only backend identity diagnosis for the saved 20261009 plan and the frozen `stage_r4_manager_r2_owner_input_r1_fused_r1` candidate. No business source, service, API, or state was changed. The offline reproduction writes only the JSON receipt in this review directory.

## Finding

**P2 — confirmed identity-coupling contributor; unique live root cause remains `CANNOT_CONFIRM`.** The semantic plan identity includes the complete `manifest_sha256` copied into every per-artifact binding. Consequently, a global registry fingerprint change can change identity while the specific archive payloads and receipts consumed by the plan remain byte-identical. This can make a saved plan fail readback as stale and require a fresh plan; the fail-closed behavior is safe, but the invalidation is broader than the consumed input set.

The candidate code path is exact and continuous:

- `app/infrastructure/research_lane_source.py:93-112` reads the whole `manifest.json`; line 112 places its whole-file SHA in `artifact_binding`, alongside the exact payload and receipt SHAs.
- `app/v4/manager_research/existing_materials.py:23-65` projects the already verified archive. It preserves the binding under each material's `source_refs` (line 63), maps semantic `available_at` (line 59), and retains the original `source_row` (line 64).
- `app/v4/manager_research/workspace_projection.py:492-495` computes `input_identity` over the full `materials` argument. That includes each `source_refs[*].manifest_sha256`.
- `app/v4/manager_research/workspace.py:881-896` carries the projection identity into the outer plan identity; `_readback_plan` requires saved and current identities to match at line 1036.

Candidate source SHA256 values:

| File | SHA256 |
|---|---|
| `app/infrastructure/research_lane_source.py` | `2a58fe0db5c5d7915e7dbc884b8720e7d32a8c0084fe5e78b0e9e37f9e738cd4` |
| `app/v4/manager_research/existing_materials.py` | `88144b666e4a78ef46513f6eaf9846367ad0189478d9b3b85b9ac8124a5ca6e1` |
| `app/v4/manager_research/workspace_projection.py` | `027d855613e675e1f569b401b9a8344e40766b88c31e987e791d05a0b3a2f200` |
| `app/v4/manager_research/workspace.py` | `7a4875f1ab5ba46ac6c18bdaffe2c103a136734fda276fbee918163332844bb0` |

## Evidence

The persisted plan is `.../workspace_plans/20261009/3bc75d1beea24036850b1af0f4d5f395.json`, SHA256 `42ffe059781333dddaf5dead93416ae168b7a90fa265b178a8912441d79f3d12`. Its workspace contains 1,970 materials and 1,970 source refs; all saved refs carry global manifest SHA `c8a8fc7f1fe654d7f700c960ead60fce1dd075c9999a3ad1b98932dcc180dcc4`.

The exact current V35 research root is `/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data`. Its current manifest SHA is `864e1f6d789e9a8a9b2614ac2534f6e4cdce55ccc46242fefba7203f1fed6e31`. I compared all 40 unique payload/receipt pairs represented by the saved materials against current file bytes and current manifest entries: all 40 payload SHAs, all 40 receipt SHAs, and all 40 current manifest payload entries match the saved bindings. Example leaf: archive date `20261007`, payload SHA `5e956e10c86391730afbdd11f3bf08ffdce44ffc1f737666b7354adb510c59ab`, receipt SHA `56ae0ce08a533c6e752716108b075f40fbcebd6bfb7075d626ffcb7fd4db9fb`, material `available_at=null`; current payload, receipt, and entry still match those values.

The offline counterfactual deep-copied all 1,970 materials and changed only `source_refs[*].manifest_sha256` from the saved global SHA to the actual current manifest SHA. It held dates, payload/receipt hashes, `available_at`, every `source_row`, and all other material fields fixed, then called the candidate's actual `build_workspace("20261009", catalyst={}, materials=..., stage=None, close=None)` twice. The projection identity changed from `ca3292e1f150a7a79a5b66a81bc5e890b0c58fe9079d87019e192694f9bc445e` to `9decd5e0e88c6237517a83545db7a632fa65de5efcef1065a2e2bda293b4f919`.

A separate captured live readback in `live_ui_api_problem_projection.json` (SHA256 `dda047f7a8ee6b9a442ee7ae7ebf175d1edf6d0856430e5a03c4e1802e4b4805`) has saved identity `4b7da917cb344f71fcf336e397a9f31122a45b78bd30f5a3a2b1a4494dd0727e`, current identity `e0f5ed6853fd464903104bf226af96ea595aacca35f1f3f7b45c8bd843165c5f`, equal date bindings, and `STALE_INPUTS_CHANGED` / `consumed=false`. The same evidence package also records a corrected owner readback that was `CURRENT` and consumed, but `PARTIAL` with zero stocks. Therefore this finding explains a real invalidation mechanism, not complete manager selection failure, and does not establish the sole cause of the earlier identity mismatch.

The prior whole-manifest bytes are not retained. It is therefore `CANNOT_CONFIRM` whether only unrelated manifest entries changed, or which exact registry rows changed. The saved GET body was not persisted, and other identity extensions exist; do not call this the unique historical root cause.

## Reproduction artifacts and acceptance

- Script: `reproduce_global_manifest_identity_coupling.py` (SHA256 `b57c4635a678bcfdf3fbed123673ffd7ae913bb6d95de4c6fc427a5c7cc5ad60`).
- Machine receipt: `global_manifest_identity_counterfactual_receipt.json` (SHA256 `093ded63f330ca25b52b549c8392035b21c9393f566e907a62b32eeae7d1c9fb`), status `PASS_COUNTERFACTUAL_GLOBAL_MANIFEST_COUPLING`.
- Replay with existing repo Python: `PYTHONDONTWRITEBYTECODE=1 /Users/lexi/Desktop/学习/v4_app/.venv/bin/python reproduce_global_manifest_identity_coupling.py`.

`REVIEWED=PASS_ROOT_CAUSE_CONTRIBUTOR`; `TESTED=PASS` for this deterministic offline mechanism reproduction; `BEHAVIOR_VERIFIED=PASS_COUNTERFACTUAL_GLOBAL_MANIFEST_COUPLING` for the projection identity only. No production fix is implemented here. Full selection, unique live cause, and any post-fix runtime behavior remain `CANNOT_CONFIRM`.

Recommended repair contract for the package: keep the global manifest SHA as provenance, but define semantic plan identity from the exact consumed artifact binding (source/date/path, manifest entry/payload SHA and receipt SHA) plus the material's semantic `available_at` and content. Preserve the existing owner read and exact artifact verification. Add focused regression coverage showing that an unrelated manifest-entry update preserves plan identity, while a changed consumed payload/receipt or semantic `available_at` changes identity or fails verification.
