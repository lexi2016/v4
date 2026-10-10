# R5 local Stage deployment acceptance — 2026-10-10

Result: DEPLOYED, API_VERIFIED, REVIEWED_PARTIAL_ACCEPTANCE. Full Stage recovery is CANNOT_CONFIRM.

Source sync commit: 6710510d7785dd0bc8f31217d9ef25f5aa8b5b63; source root /Users/lexi/Desktop/学习/v4_app. The active runtime is the isolated reviewed release, not canonical source.

At publication and independent readback: 127.0.0.1:8873, PID 8501, release stage-research-r4-20261009, runtime root /Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R4_MAC_20261009/candidate/mac_apply_20261010_r5_02/integration/candidate/stage-research-r4-20261009/app. Release manifest SHA256 a162a878c01b89f6769710f83bc0907467a05bf18d6e5838b760c7c83efe72d6. API plist changed from c88e4069f6deb467a204b4510824e62b15cb8fc11dfa7892a43e5ec8eaed8ec4 to 6cb00de89be004b8bba2981be437d241c3d2abf431965593ac37589f991a99a3. Existing schedulers unchanged. Protected publisher exit 0; rollback preimage retained locally. Concurrent Manager integration may later change runtime identity; this receipt is time-scoped.

20261009 / STAGE_0930_0935: independent live API confirmed A 10 and HK 10, backfill run 85e29661ecd848fe9b8344ea59279e86, PARTIAL_WITH_ROWS. HK rows are WATCH_ONLY research with unverified formal D1 membership, not restored formal eligibility. Root reloaded the user-requested in-app browser and saw the new release badge, exact date/stage, both 10-row counts, and the explicit HK research limitations. Local screenshot: coordination/LIVE_8873_HK_STAGE_20261010.jpg. Independent reviewer could not access that browser surface, so independent UI_VERIFIED remains CANNOT_CONFIRM; do not replace it with root observation.

20261012 preselection: A 410 contributing rows minus 39 duplicates = 371 unique codes; HK 100 rows, STRICT_0_2_READY, physical TRIO_VERIFIED. Input canary passed, but live API stage_reuse_status is CANNOT_CONFIRM because the HK producer pool envelope lacks target_date and stage_selection_eligible. Owner: v3_shared_hk_0_2_consumer_v1 pool artifact contract. API requires both explicitly; existing strict Stage v1 consumer permits omitted envelope fields and resolves exact dates from envelope/rows. These different validation contracts explain the differing outcomes. No producer artifact was rewritten and no alternate producer created. Selected 20261012 STAGE_0925 has no run yet; 12 October is a future trading day, so this is not evidence of a failed natural run.

Validation: reused independent R5 code/plan acceptance; isolated canary checked 113 historical date-stage pairs without semantic changes, 10 UI assertions and 19 GETs. Publication verified all 11 static files. Independent post-publication checks were read-only; no test rerun after unchanged source. Tests, API, root UI, independent UI, and natural execution remain separately scoped. NATURAL_VERIFIED=CANNOT_CONFIRM.

Evidence SHA256:
- operation_receipt.json: 475b5a2a3dbeb0e8b87fa413f5725a29cd57e6da4ff1603cc6af9cfb1ed548a8
- post_execute_identity_lock_readback.json: fed6fe90e5410848870a887de671a270a078f0a56010038a44373322f82e6c87
- R5_POSTPUBLICATION_API_UI_REVIEW_20261010.json: 109ef670347236b1cdbbd97364297e3841e04a13b984e8ed45078236d2c56253
- CANARY_RECEIPT.json: 3421fa7c2b51e745ec9306266afd5f38293a0972d2a5f409a7fba32f3c60b25f

RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false. No raw market data, full runtime responses, credentials, plans, or built dist uploaded in this result sync.
