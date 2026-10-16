# US industry compact panel writer receipt

Date: 2026-10-16
Scope: compact presentation and disclosure interaction for the V4 US industry panel only.

The panel uses a concise Chinese heading, source date and confirmed-board count, rise/fall/pending overview, collapsed per-board details, a collapsed pending-theme group, and one collapsed “数据与说明” section. Confirmed percentages retain their original values and signs. Unmatched rows show “待匹配” without a fabricated board percentage. Detail content retains board identity, timestamps, breadth, independent ETF/basket references, relationship evidence and links, quality/freshness metadata, clock details, and read-only/safety statements. READY-only ranking behavior remains. The panel has scoped readable styles, keyboard-focus indicators, and 48px disclosure rows.

## Source files changed from the saved preimage

- apps/web/src/components/research/GlobalIndustryMap.vue
  - Preimage SHA-256: 7fe1c84ff08e65e7d947a87f2528372bed874197a76829887cb0983a9a5a7206
  - Final SHA-256 after the date-identity correction: 8aeef4bc8eb6e8cfe61630b325fa89ca758bf1e3901a2078f3d0bd953288f251
- apps/web/src/components/research/GlobalIndustryMap.spec.ts
  - Preimage SHA-256: 1944e592c8046e5d852bae340825bba738feb1c4b0cb7ee7b48b32a99bd1062a
  - Final SHA-256 after the date-identity correction: 881997ce1e443f07e4999c8d59a749be85e2a848b2529fba6451d258993062dc

The initial spec SHA differs from the runtime spec SHA supplied in the task brief (9e2e5ac0cc810ecb85144f49e06d670ca72a3add8d6b8339d7f8cff319c0b0f5). The current canonical spec was copied and preserved as the preimage; all implementation delta is measured from that copy. The Vue preimage SHA matches the supplied runtime Vue SHA.

## Incremental date-identity correction

The independent reviewer found one P2: target stage date 2026-09-01 versus read snapshot date 2026-09-09 was only visible inside the default-collapsed disclosure. A concise notice now appears outside the disclosure for an unexpected target/read-snapshot mismatch. Same-day snapshots and a snapshot one calendar day before the target are treated as the normal US-close relation; the existing previous-source-day fixture and a separate target-versus-prior-snapshot fixture both assert no notice.

- Incremental diff from the reviewed pre-P2 candidate: /Users/lexi/Desktop/学习/agents调试/US_INDUSTRY_COMPACT_20261016/incremental-date-identity-notice.diff
- Incremental diff SHA-256: 29848dbd203ca0eefbb281825a262f531ec3c6bc6a0364974e43a1efec100d27
- Final full diff from the saved preimages: /Users/lexi/Desktop/学习/agents调试/US_INDUSTRY_COMPACT_20261016/final-changed-from-preimage.diff
- Final full diff SHA-256: 1b14d6f95dd95406b89de1102675d50f3b05c12537f10e5703b3f509bf134293
- The original reviewed candidate diff remains unchanged at changed-from-preimage.diff (SHA-256 bb10d110a0c8a54b6c6c7015bfcb80f2de62bd30c4e2ad96e7e323fe185715c9); independent-review.json records that candidate’s P2 and must not be treated as a review of the corrected final diff.

## Verification

From /Users/lexi/Desktop/学习/v4_app/apps/web:

- Before implementation, npm test -- src/components/research/GlobalIndustryMap.spec.ts -t 'shows PARTIAL quality|uses the newest materialized market snapshot' reproduced the missing notice: 1 matching test failed and 1 passed.
- After implementation, npm test -- src/components/research/GlobalIndustryMap.spec.ts -t 'shows PARTIAL quality|does not warn when the latest US snapshot|uses the newest materialized market snapshot' passed 3 tests (15 skipped).
- npm test -- src/components/research/GlobalIndustryMap.spec.ts — PASS, 1 file / 18 tests.
- npm run build — PASS, Vite transformed 99 modules and completed the build.

No API/data logic, market-date selection, scoring, ranking, BUY or trading behavior changed. No service was started or reloaded.

## CANNOT_CONFIRM / handoff

- The prior independent review remains candidate verdict FAIL for its pre-correction diff. A new independent Luna Max review must inspect final-changed-from-preimage.diff and rerun the frozen scope before review acceptance.
- Actual same-width 8873 page behavior, reload, asynchronous date settlement, browser keyboard activation, and narrow-screen rendering remain for the parent’s authorized UI check.
- No commit, push, deploy, service operation, API/data logic change, or trade/BUY gate change was performed.

At the initial handoff, the checkout was already extensively modified; branch was codex/system-consolidation-20260912 and HEAD was 55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054. The saved preimages and diff artifacts distinguish this batch from prior edits. No Git operation changed branch or commit during the correction.
