# Two action reference correction (isolated source only)

The original daily-sync producer compared raw close with the preceding raw close on two officially verified ex-right dates. This maintenance copy changes only the continuity comparison denominator on the two exact bound events; raw prices, native codec, the 1.5 ratio limits, field signatures, ordering, target-date checks and trusted-CAS prerequisites remain unchanged.

| Event | Exact reference |
|---|---|
| 301550 / market 0 / 2026-05-29 | (171.90 − 0.30) / (1 + 0.45) = 118.34482758620689 |
| 688489 / market 1 / 2026-05-27 | 42.31 / (1 + 0.47) = 28.78231292517007 |

The second reference uses the issuer's diluted 0.47 ratio, rather than its nominal 0.48 share transfer. Official issuer notices and SZSE 2026 trading rule §4.4.2 are SHA-bound in the local manifest; raw PDFs, responses and candidates are deliberately excluded from source delivery.

## Explicit admission and call paths

The optional manifest must be supplied with its exact SHA through `--action-reference-manifest` and `--action-reference-sha256`, or `V35_A_SYNC_ACTION_REFERENCE_MANIFEST` and `V35_A_SYNC_ACTION_REFERENCE_SHA256`. No configuration preserves original gate behavior. Manifest path components must be regular and free of symlinks, SHA and exact schema must match, and the only supported event tuples and official terms are explicitly enumerated. The complete preceding/event native 32-byte bar identities, dates and prices are bound to the saved response and checked again at comparison. Missing or changed identity fails closed. Other dates continue to use raw preceding close.

`run_sync` resets the module reference context and audit at the very start of every call, before parsing or manifest loading. A failed load cannot inherit earlier rules. The verified context is passed explicitly to provider/local checks. It remains available only for the existing authority's same-module post-run `_local_history_status` call; that path derives market/code only from an exact native filename (`sh|sz|bj` plus six ASCII digits). Every subsequent `run_sync` replaces or clears it. The shared `_continuity_reference` produces auditable observed/expected identities and the actual comparison reference; it does not waive the ratio test.

This file is an isolated maintenance carrier for the same producer. No loader, service, release, scheduler, native file, official panel or pointer was changed. Deployment wiring and formal-panel acceptance remain unverified and require the controller's next frozen integration scope.

## Writer auxiliary evidence

The first synthetic canary was blocked during pytest logging initialization before any test body ran (attempt to open `/dev/null`); its FAILED terminal remains. R2 disabled only that plugin. The suite then returned 21 passed and one wrong test expectation: a future response is rejected before target-presence checking in the original helper. Only that expectation was corrected; R3 reran that one case successfully. Because pytest's `/dev/null` root changed node ids, R2 deselection did not exclude the initial canary; this one extra execution is retained, not reported as 21 selected tests. Payload source did not change during these runner/test corrections. Independent acceptance still requires all 22 current test cases once.

The registered saved-response canary passed both repaired provider/native gates, source-date coverage, exact full-response date projection and native codec fidelity. 301550: 746 full = 745 eligible + one outside, all 278 original dates covered. 688489: 800 = 799 + one outside, all 272 original dates covered. All six decoded field quantization differences were zero; original files remained byte-identical. Candidate writes were confined to the isolated batch. Canary wall time 0.170 s, peak RSS 250560512 bytes, no network or formal writes.

Independent combined review ran exactly once and passed all 22 current synthetic cases plus read-only verification of both actual candidates (0.932 s, peak RSS 384008192 bytes). Only synthetic temporary fixtures were writable; network, formal and candidate writes were zero. Current status is IMPLEMENTED / TESTED / REVIEWED / BEHAVIOR_VERIFIED for these exact two events, strict input binding and context lifecycle. No deployment or formal-panel PASS is claimed. See REVIEW_RECEIPT.json. Current snapshots do not establish 9/6 or historical PIT identity, listing-complete history, Windows input parity or full stock-selection parity.

Local evidence: `research/a_v192_signal_pool_return_stability_v1/batches/v192_logic_input_diagnostic_20261020/NEXT_TDX_ACTION_*` in Factor Factory. Registry is append-only, stages have real start/terminal events. Source/test delivery is NOT_SYNCED pending controller integration; earlier accepted 17-field delivery remains unchanged and synced.

RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false.
