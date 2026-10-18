# Independent R3 live leaf acceptance

**FAIL_P2_COUNT_UNIT_WORDING_MISMATCH** for the frozen count/display contract. R3 is deployed and the existing-run API response and AX tree verify the target counts, but one live UI sentence still confuses the source-relation count with the full candidate-pool count. This is a P2 acceptance blocker for the count wording only.

The deployed API identity is `monthly-membership-api-20261018-r3` (PID `10304`), health and ready checks both returned 200. The read-only live response is HTTP 200 for run `2e2a1dbb1312422c8b1e21a58d2d44d0`; its raw bytes hash to `e223e23c838b4c0f0c13303fcee916f02098efdcafbbaeecb8cead26057dfe66` and match the readback receipt. The saved run ID, input SHA `1de9655dde06cbd4f15deca41df57eb73d00c00e657e880e0ffe3607d22a6c33`, product SHA `78bfe4db1f37e5e356b7d71878faeb9a7d4edf551a7083570ab9fbca532bd922`, and on-disk snapshot SHA `388b4db4f4d46d7f926258ea872226243b9f121cd071e7ad6fb56aafb51cccbf` match the prior R2-bound run/saved-snapshot evidence. No new run was submitted.

API counts are 701 deduplicated candidate stocks: strict selected 0, conditional watch 153, unassessed 437, not selected 111, observation-only 0. The 60 original source rows retain separate counts 0/0/27/0/33. The source relation summary says 36 relation rows map to 19 HK stocks. Pagination is `153` total, offset `0`, limit `50`.

The AX tree verifies “严格入选 0 / 条件观察 153” and the explicit “严格精选规则尚未启用” message. However, AX line 887 says “36 条含港股，涉及 701 只,” while line 892 and the API summary say the 36 relations involve 19 HK stocks. The 701 figure is the full deduplicated candidate pool. This directly conflicts with the frozen requirement to keep stock-candidate and source-record counts distinct.

**Single minimal correction:** revise only that sentence to “本路径保存 60 条来源研究记录（计数单位：研究记录）；36 条含港股关系记录，涉及 19 只港股；全路径去重港股候选池共 701 只。” No new field, filter, or selection rule is needed.

Pixel screenshot remains CANNOT_CONFIRM because the captured view had zero width; AX was used for UI text verification. Natural-run evidence remains CANNOT_CONFIRM. Tests and source review were not repeated in this live leaf pass.

Evidence: [API activation](/Users/lexi/Desktop/学习/v4_app/docs/handoffs/monthly_membership_research_fix_20261018/ROOT_API_ACTIVATION_RECEIPT_R3.json), [API readback](/Users/lexi/Desktop/学习/v4_app/docs/handoffs/monthly_membership_research_fix_20261018/ROOT_API_READBACK_R3.json), [UI readback](/Users/lexi/Desktop/学习/v4_app/docs/handoffs/monthly_membership_research_fix_20261018/ROOT_UI_READBACK_R3.json), [live lane response](/Users/lexi/Desktop/学习/v4_app/docs/handoffs/monthly_membership_research_fix_20261018/local_only/actual_r3/lane-response.json), [AX tree](/Users/lexi/Desktop/学习/v4_app/docs/handoffs/monthly_membership_research_fix_20261018/local_only/actual_r3/ui-ax.txt).
