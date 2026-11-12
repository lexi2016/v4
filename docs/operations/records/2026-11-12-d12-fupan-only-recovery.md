# D12 independent fupan recovery

Baseline: `6971e4eb3253be0deb69753fb873df2a92473623`. Branch: `codex/optional-d12-recovery-20261112`.

The 20261112 fupan pool was blocked because the original D1 source producer required nonempty Stage7 selection rows even though fupan scoring does not depend on Stage7. Added an explicit fupan-only recovery option to the existing producer; default strict behavior, scores, ranks, and trading boundaries remain unchanged. Fupan-only recovery never synthesizes Stage7 rows.

Actual recovery used source date 20261111 and published 62 fupan rows with `FUPAN_WATCHLIST_POOL_READY_DATA_PARTIAL`. The original missing placeholder was replaced through the existing locked CAS/revision owner. Stage7 remains `CANNOT_CONFIRM`: its natural research completion witness was missing, raw temporal cutoff was unsafe, and the afterfact snapshot is ineligible.

Validation: 4 actual sparse-runtime checks passed; a cache-reentry defect was independently found and fixed, with the affected test and real 62-row cache reuse passing. One independent review, including that incremental fix, passed. API verified all 62 symbols/ranks and dates; three distinct roles matched source names/scores. Headless homepage showed 62 rows and retained the Stage7 missing state; owned browser/context closed. Five protected valid/original pools retained their hashes.

This was a manual historical backfill. Candidate source was not integrated into canonical or activated as Main/Stage/API; natural dispatch remains NOT_RUN. No model, formula, BUY gate, orders, third-party groups, or service configuration changed.

Frozen scope SHA: `a595493312794d00cc2c7e6630889f87de078e09ec5d51b9b693c7df4315817d`.
Independent receipt SHA: `2617836dc1ef603f34d9a1384c58b957c11b79818757d0746cd9e11af28833f3`.
Published artifact SHA: `9fde912fb7f3009d17f36a230e7fb8be4f825eb726f0af17e6a4000ac71aa5dd`.
Replaced placeholder SHA: `6025ec959f714f54555d528c61cfcd3aed915c519fcd301264d7e9224653ab87`.
Actual recovery UTC: `2026-11-12T14:27:32.404360+00:00`.

Source identities:

| File | Before SHA256 | After SHA256 |
| --- | --- | --- |
| ops/materialize_d1_review_lanes.py | dc2a4e3afc99afe179896831f564da0db10a0d55661b2aa31fb20f1865bf6039 | c9b11a965b45b8d2f7da1faaccd7499c36698cd569dc5cace710f5f1a4002cca |
| domains/d1_review_source_producer.py | 195ab9af387eae5c4dfe38bf9685cf566e27bbc74baab9e37cd736ec21903c8a | 77a49963a9ba9036e54cd7ceaa65e835e4eddebe90e147e7c4370e9e333b9b5e |
| domains/d1_review_lane_producer.py | ec80a2bf74a19da940da419b2f44c3dd6ebd2c4fff22e9d296e1b08d4c17195d | 5f30238962779b02b2372025ea957e295e0f68cefbe35bc2309b83d54f21dda8 |
| domains/_d1_review_lane_producer_parts/preopen_lanes.py | f8cfd1b6ee3ca2f57cded10d3a2ee1324ca6c0ac3fb2132ce7d7fbd5c327dc70 | be02638bd165d074296c6184aeffc3b36e987702b5f8620917947b46fc4866a2 |
| tests/test_d1_fupan_missing_stage7.py | NEW | 659bb9b75fadd387bdb7060c34c921c4d060a4f4eb75aa6a8d91ea2982c35e5f |

Runtime: existing verified v3.5-mac interpreter and a three-module sparse candidate over the active Main release. The original shared public-fupan reader and logical-selector reader were reused; no network data acquisition or v192 recomputation.

`RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`, `orders_sent=false`.
