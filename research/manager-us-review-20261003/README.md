# Manager US relation status: single bounded fix, 2026-10-03

Refs Issue #8. Chat writes the fix; Luna Max applies and tests locally; an independent Luna Max reviewer accepts final bytes. Controller orchestrates.

## One actionable defect
For ASSESSED_WITH_RELATIONS, accepted count 1, complete input, the backend emits VERIFIED_RELATIONS_PASSED_TWO_SOURCE_PIT. businessStatus.ts lacks that label and renders its generic missing-evidence fallback beside the positive state. See evidence/positive_relation_detail_repro.log and REVIEW_RECEIPT.json.

Map this known success reason to a correct explanation or omit its gap explanation. Add an assertion using the exact producer reason that positive detail does not claim missing evidence. Preserve real unknown reasons and insufficient/not-evaluated states. Allowed modifications: source/apps/web/src/manager-selection/businessStatus.ts and its businessChainR2.spec.ts; businessCompletionR3.spec.ts only if necessary. Python producer is read-only context. Return minimal unified diff, before/after SHA, focused test evidence. Do not redesign or implement other repairs.

## Reuse completed work
Announcement dates, deterministic parser cache, and R6.1 UI already passed review and deployment; R7 preserves them. Do not reparse PDFs, refetch, change Python versions, redo old repairs, or broaden tests. Frozen Python exact scope: 76 passed. Saved-input replay: 10/10 passed, 80 pre-Connect cards retained for research, 0 formal cards, snapshot not ready means NOT_EVALUATED and accepted=null, two-source PIT retained. Targeted TS passed. Three old frontend failures classified in receipt: literal text mismatch reproduces in preimage, two old incomplete announcement fixtures no longer fail in canonical. Old full-typecheck TS2578 is out of scope. Do not compare expanded 81/3 tests with exact 76-test scope. Daily unqueried UNKNOWN is correct without an authoritative count; no 696-675 inference.

## Deployment and scope
This is a source/evidence slice, not a complete runnable or deployable app. Existing local project provides type imports and dependencies; do not fabricate stubs as whole-app acceptance. Only focused positive-detail/four-state tests need rerun for this fix. Local deployment and 20261002 manual plan/save/readback/API/UI follow independent PASS. Natural-run evidence is separate. Active baseline must be freshly confirmed before overlay; never deploy this source slice wholesale or replace current code with old main/R5/PR18.

RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false. No changes to BUY, Stage, Vibe8910, collection, qualification/PIT gates, or unrelated schedulers. Evidence includes local paths for provenance but no complete plist, credentials or raw market dataset. Replay JSON is a summary only.
