# R4 writer receipt

**Status:** `TESTED_CANDIDATE_READY_FOR_INDEPENDENT_REVIEW`

R3 independent live review found one P2 wording mismatch. The page paired 36 HK relation rows with 701, even though the saved source summary says those relations map to 19 HK stocks. The single sentence now states the 36/19 relationship and labels 701 as the full deduplicated candidate pool. No count or decision logic changed.

The patch was applied to canonical `apps/web/src/manager-workbench/Workbench.vue` and to a local overlay rebased from immutable `monthly-membership-api-20261018-r3` (release-manifest SHA `7ad0c2fe45fc4edb620b15de72c5012ba8f6b7dcd2f22f4c3e462827ec54f608`). Only the overlay Workbench and `__tests__/us_factor.spec.ts` differ from that release; the other 9 manager-workbench source/test files and `vite.config.ts` are byte-identical. The focused fixture uses saved values 60 source rows, 36 relations, 19 mapped HK stocks, 701 candidate stocks, and strict 0/watch 153. The directional-count fields and rendering were untouched; the prior independent R3 readback recorded 153 upside and 109 downside.

Focused validation passed: `us_factor.spec.ts` **4/4** with direct Vitest, no package-manager invocation. The first invocation used a relative config path and failed at startup; the next exposed a whitespace-sensitive assertion, which was normalized. The final run passed after rebasing the Workbench overlay directly from R3. Exact command and each file SHA are in the JSON receipt.

**CANNOT_CONFIRM:** independent R4 review and fresh live UI readback remain pending root integration. Prior pixel screenshot and natural-run gaps remain as recorded in the R3 review.

No API, service, scheduler, saved input, count logic, build, deployment, or run submission was changed.
