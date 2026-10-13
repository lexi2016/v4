# US29 closure and independent recommendations — 2026-10-13

Remote baseline: 94b4cc2642301ee181681dd9cf0f6b2bb9a0fd18
Branch: codex/manager-workbench-data-closure-20261013
Writer/Reviewer: separate manager_writer_sol / manager_reviewer_sol identities, gpt-6.1-sol high.
Source root: /Users/lexi/.codex/worktrees/manager-workbench-rewrite-mac/v4_app
Canonical root: /Users/lexi/Desktop/学习/v4_app

## Delivered result
Fixed33 US universe and existing relation scope unchanged. Ten original tuples received NEW reviewed classifications (3 PRIORITY/7 WATCH), independently available at 2026-10-13T12:36:18.755109Z. This does not restore an old missing field or prove orders/revenue/causality. US source assessment4→9, unknown29→24. Only EQIX→HK09988 is CONDITIONAL_WATCH (+0.63739% on source session20261012, documented 2017 Alibaba Cloud partnership).
Remaining24: 21 ETF theme proxies without reviewed HK issuer edges; MU original pageHTTP403; WDC unresolved current issuer abbreviation; DLR targetConnect=false. Not claimed fully resolved.

New readonly recommendations/{lane} API and Vue entry points use each saved lane's decisions/counts/reasons/detail. Same stock may appear in both; no cross-lane aggregate classification drives either list. Source-only gaps are not HK stock recommendations. US33sources/37records/14HKrelations/10HKstocks, strict0/watch1; oversold692/662assessed/30unknown, strict20/watch277/not365. Oversold records/results and40% AND1.5 rule unchanged.

## Formal evidence
Run528ef6fd4f0b49e7a3ec2b6719fc9afe, RETROSPECTIVE.
Product94567ead8a0bd21e4076ad08a8152abe460b72cfad61d623a3602f71385cccf7.
Raw snapshot673c159af0b2a40af61741e655245f80f01d61da459c998aa7c7660a72762c62.
Page http://127.0.0.1:8873/manager-selection/?date=20261013&phase=RETROSPECTIVE&run_id=528ef6fd4f0b49e7a3ec2b6719fc9afe
FinalAPI PID54701; cwd independent-recommendations-r3 reviewed candidate.
API-only plan7c9f964d2635d63519a8645c54b37f8e3667ea856356fa86d863e1e100581896.
Manifest a31abf3a90a760311862e5b3ceb30ad38683e8c269c1be5d035740b7a5110615.
V14 first delivered US evidence consumption; final API-only batch changed no Scheduler/config/engines/snapshots. Parallel pool-label/morning-pool changes preserved. Later parallel Scheduler is separately identified in receipts, not falsely called V14.

Independent validation: US50Python tests; independent lists7Python/61Vitest/typecheck/build; final package6tests; live297recommendations pagination200+97, lane+row-bound details and unchanged old snapshots. Exact commands/environment/before-after sourceSHA are in paired implementation/independent receipts.
CUA reload/switch/filter/detail verified HK09988 US WATCH versus oversold NOT_SELECTED, independent explanations and counts. UI receipt181f4c9e227186f4eacf3dce7db5ee09b259a179df1dfa2d7e1bd7268e298ed0.
Final formal Reviewer receipt0d9b73f8adad6c8fb9d7c65e09862cde31ade920115ce24b3091b9ac14c5e2f9. Main UI is attributed to main, not Reviewer.
Preserved failures: candidate r1 manifest omission, r2 old WorkingDirectory, both before formal writes; finalr3 correct startup root tested. A final receipt copy encountered a SHA update race and stopped before writing; retried only after Reviewer supplied finalSHA.

Status: IMPLEMENTED/REVIEWED/TESTED/INTEGRATED/DEPLOYED/API_VERIFIED/UI_VERIFIED/BEHAVIOR_VERIFIED (engineering/saved-results only). NATURAL_SLOT_UNVERIFIED; research effectiveness NOT_VERIFIED.

## Research request and publication
US_FACTOR_RESEARCH_20261013.md compares primary research and a public QuantConnect implementation. Market lead-lag, industry ETF factors and company economic links are distinct. Proposed factor definitions are DIRECTION_ONLY; no new factor/threshold/source/composite score activated. Monthly results are not proof of next-day HK alpha.
Publish only necessary sources/tests/generators, versioned relation-reference JSON dependencies and concise receipts/reports. Four inherited readonly source JSON files were absent from remote base and are included byte-for-byte for provenance closure. No old manager business imports.
Exclude rawHTTP bodies, market histories, full input/HTTPfixtures/plans, credentials, accounts, dist, environments and node_modules.
RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false.
