# Controller delivery result · 2026-11-10

Deployed and verified the bounded 9A Top200 scope/receipt/comparison repair. Implementation handoff HEAD: eedd3c037a12ccfec34e724ab32202e7ac372a20; behavior source commit: 28f12f21f0638487063fc56e9e2d0fae8f8d60d8. This final result document does not change those bytes.

- Independent review: REVIEWED/PASS, receipt symlink P2 independently reproduced and closed with three new regression passes.
- Release tool: f998046fc6ba71a19bffd3e4da87890f68402534. Final packet SHA256: 57d42d857f022d157ad3a1106d0ef01d20f42eb363bce3a81c34a22f6e9793b9.
- Actual API release: v4-top200-scope-20261110-r2-api, manifest 4d24d947cfbae389f38bfb7f0a65800abd3f34ac50bceff3dabafc0076a8a618. Actual frontend main-DCRf2b-t.js VERIFIED.
- Actual Main app/release/manifest unchanged (29ac5b4f...), only two retention policy env references updated; actual installed 24-source dependency check passed. Stage unchanged and not controlled.
- Actual API samples: D20261109 pool487/36, stage10/2 with1/7; D20261106 stage6/7; D20261110 NOT_MATERIALIZED with no date substitution. Original rankings/counts/membership retained.
- Actual D9 formula comparison: D1=20261106, four-group387/10, original47/1, smallk287/6, pullback111/3, breakout47/3, v19219/2.
- Actual user-page UI sample D9: explicit partial-scope cards, six comparison rows and six failed-stage Chinese reasons; three screenshots retained locally.
- Three representative existing company/score modules and all seven D9 natural receipt hashes preserved. No data publication or replay.

Local detailed receipts: /Users/lexi/Desktop/学习/agents调试/v4_top200_scope_repair_20261110/REPAIR_RESULT.md and adjacent INDEPENDENT_REVIEW.json, ACTUAL_API_VERIFICATION.json, ACTUAL_UI_VERIFICATION.json, ACTIVATION_RECEIPT.json.

Limits: actual D9 UI only, not a full V4 regression; new-reload natural slot NOT_RUN; original formula performance remains weak; historical_PIT=false and complete seven-stage effectiveness CANNOT_CONFIRM. Existing missing pools/research quality evidence remain explicit.

RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false.
