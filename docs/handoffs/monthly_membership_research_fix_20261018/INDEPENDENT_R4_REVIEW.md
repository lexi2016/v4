# Independent R4 copy-correction review

**PASS_CANDIDATE_REVIEW.** No P0/P1/P2 findings remain within the frozen R4 scope. The focused candidate behavior is independently verified; the candidate has not been activated, so live R4 API/UI remains CANNOT_CONFIRM.

R4 changes one source paragraph on the immutable R3 Workbench base and adds focused assertions. The paragraph now uses the existing `us_mapping_summary.mapped_hk_count` for the 36 relation rows (19 HK stocks) and labels 701 separately as the full deduplicated candidate pool. The test fixture covers source rows 60, relation rows 36, mapped HK stocks 19, full candidate pool 701, and selected 0 / conditional watch 153 with the strict-rule-unavailable message.

I reran the focused Vitest file on the R3-based R4 overlay: **4 passed**. The exact R3-to-R4 overlay diff is limited to the paragraph and focused test fixture/assertions. The candidate release manifest hash matches the R4 build receipt; all 1,250 inventoried files match it, exactly the four declared Workbench/test/generated-web files differ from immutable R3, and the other 1,246 entries are preserved. Generated bundle hashes match `ROOT_WEB_BUILD_R4.json`; no other entrypoint was rebuilt.

The frozen R3 live evidence retains the 153 upside / 109 downside values, and this R4 delta does not touch the directional list or data. No API/data/count/engine change was made.

Evidence: [R4 scope](/Users/lexi/Desktop/学习/v4_app/docs/handoffs/monthly_membership_research_fix_20261018/R4_COPY_SCOPE.json), [writer receipt](/Users/lexi/Desktop/学习/v4_app/docs/handoffs/monthly_membership_research_fix_20261018/WRITER_R4_RECEIPT.json), [API candidate build](/Users/lexi/Desktop/学习/v4_app/docs/handoffs/monthly_membership_research_fix_20261018/ROOT_API_RELEASE_BUILD_R4.json), [web build](/Users/lexi/Desktop/学习/v4_app/docs/handoffs/monthly_membership_research_fix_20261018/ROOT_WEB_BUILD_R4.json), [detailed reviewer evidence](/Users/lexi/Desktop/学习/v4_app/docs/handoffs/monthly_membership_research_fix_20261018/local_only/reviewer_r4/review_evidence.json).
