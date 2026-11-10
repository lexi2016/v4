# Controller result · A925 native price/readiness · 2026-11-10

The scoped input repair is deployed as v4-a925-readiness-20261110-r3 API/Main/Stage. Reviewed business HEAD: 083e07706007de75de596d5dff06949065497648; release tool HEAD: 9533664efef9a1e1c8f16b4e43eca020a160ef47. This follow-up commit adds documentation only; sealed source handoffs and release packets remain unchanged. Canonical workspace and unrelated changes were not overwritten.

Baseline source commit: fc423383b906f964896a4ceb423d4da020d9c32e. Active-source overlay and per-file before/after SHA are in HANDOFF.json/SOURCE_BASELINE.json; separate API/Main patches retain distinct active source variants.

Independent r3 verdict: REVIEWED/PASS; packet SHA 0770cb7a873fcde10a27eb1269a5bfa22b296bbc87b6b6c2085c12215f392aa4. Production interpreter: /Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python.

Installed release validation passed with 24 source bindings. Actual installed Stage/API/Main readers each returned all 10 new-algorithm fixture rows; actual Main consumer.get returned 10; actual loaded Stage owner configuration verified the real old-Main November 10 09:00 witness. This is not a new natural A925 result. Health/frontend GETs and representative original Top200, v1.9.2 score and company-material guards passed. The existing November 9 Top200 UI was reloaded and showed the new API identity with the unchanged frontend bundle; original ranking/membership/cards remained.

Commands executed after independent review:

```text
python -B -m ops.prepare_a925_mainclosure_release activate --packet <r3>/PACKET.json --review <evidence>/INDEPENDENT_REVIEW_R3.json
python -B -m ops.prepare_a925_mainclosure_release validate --packet <r3>/PACKET.json --installed
```

Business targeted 21 PASS; active Stage overlay 42 PASS with two unchanged baseline fixture failures explicitly retained; reviewer optional-field regression 15 PASS; Main new/old reader and seven-owner boundary regressions passed. Existing isolated November 9 calculation hit 3 of 200 with 10 names versus 2 of 200 in the original natural Top10. No strategy-lift, historical PIT or true matched-auction-price claim. Coefficients, Top10, models and BUY gates remain unchanged.

Actual manifests:

- API dec319be02f69095d5e53b6a4fc96c69b2731ecd32ba8ee31d5b7259acaa57b6
- Main ef1fe8701ca953eab207428a0913813340588989f1fb34552efb22473a8f0d29
- Stage 813d595dd27c2af31007e5ee9d3ddf56cadde21170f17221320db4f944c563bc

Nine original dated snapshots/receipts remained hash-identical. Historical jobs were not replayed. On the actual 15:55 natural tick, HK tail selection was READY but redundant PREP_0915 failed strict current evidence identity mismatch against today's already sealed, strictly readable READY330 old-Stage input. The overall tick is CANNOT_CONFIRM/exit3 and is preserved. Read-only diagnosis found 17:00 is hourly-only, next-day preselection does not publish Stage acquisition, and tomorrow uses an absent separate date partition; no same-condition blocker established for those paths. No old-input overwrite, permissive identity migration or schedule change was added to clear this one-day redundant warning. First repaired A925 natural run on November 11 remains NOT_YET_OCCURRED.

A baseline pytest invocation changed two sealed test-cache files; changed bytes were preserved and exact original sealed bytes CAS-restored. No validator/manifest exception. Subsequent tests were isolated. r2 was never activated after Main compatibility failure; its evidence remains immutable.

Git destination: existing lexi2016/v4, codex/a925-price-readiness-20261110 and codex/a925-main-consumer-release-20261110. Remote commits and 19 key files were verified against frozen hashes; final documentation commit is verified separately. No merge or visibility change.

Full local evidence: /Users/lexi/Desktop/学习/agents调试/v4_a925_price_readiness_repair_20261110/REPAIR_RESULT.md and adjacent machine-readable receipts. No raw quotes, runtime apps, credentials, account data or logs included in this source delivery. Necessary isolated fixtures, failure evidence and frozen source references are retained; no shared/user data deleted.

RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false.
