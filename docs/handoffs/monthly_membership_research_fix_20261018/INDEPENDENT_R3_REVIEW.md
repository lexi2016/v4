# Independent R3 count-contract review

**PASS_CANDIDATE_REVIEW.** I reviewed only the frozen R3 count/display scope. No P0/P1/P2 findings remain in this candidate.

The saved run 2e2a1dbb1312422c8b1e21a58d2d44d0 and snapshot SHA 388b4db4f4d46d7f926258ea872226243b9f121cd071e7ad6fb56aafb51cccbf were replayed through the R2 API candidate with only the R3 display_read overlay, using an in-memory store. The resulting lane has 701 deduplicated HK candidates: selected 0, conditional watch 153, unassessed 437, not selected 111 and observation-only 0. The default recommendation list is 153 with a 50-row page. The separate saved-source breakdown remains 60 rows: 0/0/27/33/0. The 1,003-row relation catalog is excluded from candidate counts. The snapshot hash remained unchanged. Strict selection stays explicitly unavailable; engine decisions, target qualification/PIT and BUY behavior were not changed.

Reran the focused Python regression suite: **12 passed** (including preserved non-US_MAPPING/OVERSOLD count behavior). Reran the local R3 overlay Vitest file: **4 passed**. Replayed the read-only saved-snapshot API canary: **PASS**.

The candidate release manifest and every inventoried file hash match. The R3 candidate differs from active R2 in exactly six runtime paths, with all 1,243 non-delta entries preserved. The Workbench overlay is based on the frozen R2 runtime source, carrying the scoped R3 hunks; the other R2 runtime differences were preserved. Candidate is still inactive. R3 deployed API/UI behavior and a natural run remain CANNOT_CONFIRM.

The historical R2 live P2 receipt was corrected: vm.day comes from the lane recommendations endpoint; the bug was legacy-row-only counting that excluded industry-candidate rows. R3 fixes the count contract in candidate replay while retaining the R2 FAIL record.
