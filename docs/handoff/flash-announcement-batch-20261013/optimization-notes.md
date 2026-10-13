# Qwen3.8 Flash Next canary handoff

Status: the bounded runner and the later thinking-off native-chat artifact were independently reviewed PASS; the runner reviewer reran all 11 unit tests. A was stopped by the parent controller at 2026-10-13 13:39:42.474 UTC after 1,471.64 seconds total, including 895.9 seconds of thinking and 2,744 thinking tokens. It produced no final answer, so A is **CENSORED_RUN_NOT_COMPLETED_BENCHMARK** and has no completed-task quality result; see `evidence/compact-first4-concurrent-20261013/end-stopped.json`. B uses the same model, system prompt, and user input, with per-chat Thinking Off and Web Search On. The parent started B at 2026-10-13 21:50:51.245 Asia/Shanghai (`rid1b05b6f9-4297-426b-a6df-cc34bf4d0579`); its start receipt is `evidence/thinking-off-first4-concurrent-20261013/start.json`. The native API reports 9,068 prompt tokens; this is a different measurement from the 9,104-token local preparation count and must not be treated as the same counter. B remains **UI_RUN_IN_PROGRESS**; completion and quality are not available. The user retained concurrent Vibe workload to measure local peak performance, so these are concurrent-load observations rather than an exclusive or clean A/B baseline. Warm prefix-cache state and dynamic Vibe/cap conditions prevent a strict speedup claim. This writer made no inference or runtime change.

A separate concurrency preflight was a no-op: no settings update API was executed, and the actor/source of the observed cap change from 8 to 4 is **CANNOT_CONFIRM**. The independently reviewed observation receipt is `evidence/concurrency-8-to-4-20261013/observation-20261013T133443620480Z.json` (SHA-256 `a2be7f32dae0f7085ceae54fe88474daa31ce095419b067a9978e0d323ad32cd`).

## Input-size result

The exact local chat-template count includes the active system prompt, tool schema, request wrapper, article metadata, and complete source bodies. The active system prompt and tool schema stayed identical across each comparison. The model-facing article metadata now omits `source_origins` and `source_issuer_codes`; both remain in the local validated input, the full 23-article population manifest, and the preparation receipt. The complete article body and `article_id`, source/body SHA-256, publication date, title, issuer, symbol, observation/availability timestamps, and conservative PIT status remain in the model request. No body was shortened and no batching or completion budget was added.

| Prepared input | Before | Compact | Tokens removed | Reduction |
|---|---:|---:|---:|---:|
| All 23 articles | 51,727 | 32,038 | 19,689 | 38.06% |
| Fixed first-four canary | 12,547 | 9,104 | 3,443 | 27.44% |

These are exact initial-request counts from the installed model tokenizer, not generated-token counts or an inference benchmark. Both preparations fit the model-native 262,144-token context. The four canary IDs are the first four after lexicographic `article_id` ordering: `EASTMONEY:AN202610131830378826:HK.01511`, `EASTMONEY:AN202610131830378829:HK.02636`, `EASTMONEY:AN202610131830379994:HK.02171`, and `EASTMONEY:AN202610131830380019:HK.01999`. Their complete bodies are 1,874, 2,346, 2,123, and 2,557 Unicode characters (8,900 total). This is not a title or positive-signal selection and makes no claim of statistical representativeness. The remaining 19 IDs and all 23 identity/provenance rows stay in the local population manifest.

The malformed-IPv6 `fetch_url` path now converts URL parsing `ValueError` into `WEB_FETCH_ARGUMENT_INVALID`, returns a failed tool result, and continues the following model round. The regression test covers the failed tool result and continued round.

## Local runtime and external references

Read-only inspection of the installed `omlx/patches/moe_expert_offload.py` found a `ThreadPoolExecutor` around `os.pread` shard reads, fetch/compute overlap enabled by default (`OMLX_MOE_OFFLOAD_OVERLAP`, unless set to `0`), and power-of-two prefill-route padding that reuses buffer sizes. These mechanisms are already present in this runtime; this batch adds no duplicate optimization patch.

- [oMLX issue #3686](https://github.com/jundot/omlx/issues/3686) reports serial expert reads and then parallel `pread` plus fetch/compute overlap results. Its author’s quick comparison used an M4 MacBook Air with 32 GB; those timings do not predict this host’s performance.
- [oMLX issue #3353](https://github.com/jundot/omlx/issues/3353) reports MTP sensitivity to a concurrent sibling workload and a negative whole-graph `mx.compile` result on an M3 Ultra with 512 GB. It also reports context-specific prefix-cache results. These are useful controls and counterexamples, not transferable speed estimates for this machine.
- [oMLX issue #3738](https://github.com/jundot/omlx/issues/3738) traces expert-major-prefill memory growth on an M4 Max 64 GB to retained Metal buffers; the maintainer reports buffer-size reuse reduced a 4K test from 69.7 to 33.9 GiB and allowed a 16K test under a 56 GiB guard. This is a different hardware/runtime report, not evidence of this canary’s memory behavior.

After B completes, `prefill_priority=context→speed` remains a candidate for a later controlled comparison only; do not change settings during an in-flight request. Defer the 0.75 expert-residency comparison because the prior active-8 observation showed roughly 70 GB of footprint. Keep concurrent Vibe workload allowed and label it as part of the local peak-load condition; there is no exclusive-load or fully-idle-server prerequisite. Any later comparison must keep the safe memory guard, MTP, Thinking, and Web settings fixed and record their effective values, cache state, and resource snapshots. This writer did not invoke the model or alter runtime settings.

## Minimal source sync inventory

The runner’s minimal source set for this batch is `batch_runner.py` and `test_batch_runner.py`. The runner resolves the active Reader prompt/schema/validator from the local V4 `v4/manager_workbench/engines/announcement.py`, uses the installed oMLX runtime/tokenizer and Python dependencies, and reads the existing local runtime settings for the API key only if inference is explicitly executed. None of those local runtime files or credentials are in the sync set. `import_chat.py` was used to build local native Import Chats artifacts; it is not imported by the runner CLI.

The following preparation receipts contain hashes and article metadata only; they have no `article_body` field and contain no credential. They are the receipt candidates for source sync:

| File | SHA-256 |
|---|---|
| `batch_runner.py` | `3eb7d54c8e82d9067de618cf0646a183bc30eff497d342fa075038f0a44c462d` |
| `test_batch_runner.py` | `5e4187562805baa48612163f6eabd6337f7ddd678419383bbc0f56a7625d9e04` |
| `evidence/batches/prepare_fbab8aa42579b99a.json` | `99894dce6eb2afbe620589aace8c73e6f23214828f4cafa362095b2803c73398` |
| `evidence/batches/prepare_7a5f18699b16b0a1.json` | `cb935ac397400dcf5f71fc55b346fc080f6e327d775eb185f1fa20f9bb1369d5` |
| `evidence/batches/prepare_bf16a587553d8582.json` | `f71ba5bdc291a22658d40ca786db0519c219694712a67f22806051ef9c5c0d60` |
| `evidence/batches/prepare_54025459f5c44441.json` | `fe2f95455e28ecd7d452cf88ef5c6fc72d821e0e1bb57b93b98eb33af17325bb` |

Do not sync validated batch JSON, native Chat Import JSON, original announcement products/body artifacts, runtime settings, model files, or credentials. They remain local-only.
