# HK Stage preparation for 2026-10-08

Scope: prepare an independently checked candidate using the existing selector and date contract. No selector or architecture rewrite, historical acquisition, shared-output replay, service activation, or natural-run claim was performed.

## Fixed source and candidate identity
- Base commit: 9ebb2faa954aa6c910d5fc4f4d4e0c418df9ca89. Existing Stage business source is preserved at d6ab71f02f8deb03f45514ce28dc35a983654c47 under handoff/hk-daily-runtime-r2-20261007/candidate/.
- New Stage candidate: hk-stage-oct8-ready-r1-20261007. Manifest SHA-256: e861cf6ec72c9bdfe35dc1bfff68b32d69cbfbb7f0d4bf817c56c8b59a3b83e3.
- Candidate config SHA-256: d259a5c88eba5ed3b6d7dc426ae84eede526577a42be126cdc8aeef7701e0890. Packaged plist SHA-256: 80fca32e36a05608a63bee9e65e3cb1acacead0b8021e30928b52e4f3afbd552.
- Relative to frozen R2: zero business-source byte changes; only config release identity/shared-data-root and release/plist metadata changed. 915 other regular files and two declared symlinks are preserved. Inventory: 918 entries; aggregate c0c7c7382df8a22a4cb0bf6d622c85162c19cdbca759ca467c69ac70e22c108f. All 18 source dependency closure pins match.
- New preparation receipt SHA: 33d2faf1a7d1ae055469f5a333315b86ccbfc7e5df9d08c81714668744c538ad. Pin receipt SHA: 51ae005d978e08554a980702db0bfa0bcaef131a3274b1acdf16f8985c32411f.
- New independent admission receipt SHA: 504cc7f6ea2f7b19798f9449e12bee7692bc1a431347842832626bf2a47b7b29. ENGINEERING_PREPARED=PASS; REVIEWED=PASS_WITH_P2; TARGET_INPUT=BLOCKED; NOT_DEPLOYED/NOT_ACTIVATED.

## Date contract and single runtime blocker
For 20261008: target date 20261008, price signal date 20261007, eligibility source date 20260930. Both HK securities and Connect are open on 10/8. Keep 9/30 eligibility provenance; do not relabel it. On HK-open/Connect-closed dates, a valid target-day research pool has priority; only genuinely missing target inputs permit the existing controlled observation fallback. An invalid present target must fail closed. The closed-Connect fallback is not a 10/8 admission route.

The existing 10/8 pool has 100 unique HK codes but all row signal_date values are 20260930 and split-date provenance/stage eligibility is absent. Pool SHA: 62d7716c51978a8e2b55c8aa423ae72691da1385fb80b97df35da714addee09b; manifest SHA: cc476019362896f89b37ca12b0f5d7c606fe188ef3b0a33b7c8224df21aa8de6; receipt SHA: 1871468dda045659d1786b46576ec6290b92df667bcda7c5b325a62a0af01b28. Source run: 20261008-hk-connect-d1-top100-0-2-8a0386afb66b (file_replay with 9/30 signal). The independently copied unchanged trio was rejected with HK D1 split-date eligibility provenance missing; no fallback binding returned. No 10/8 Stage output is claimed.

No 10/7 price original was found in this source run's exact references; this is not a claim that the workstation contains no such data. The inspected producer interface couples signal and security-master dates and does not emit the required independent eligibility provenance. Do not repair this by changing date labels. The remaining blocker is a valid, traceable 10/8 pool satisfying the existing split-date contract.

## Actual configured and running identities preserved
- Stage is still registered to 20261003-hk-binding-wrapper-r3, manifest f642954ebcb2c7af86e9c7ea84674e485ab82530503474536167766624895434; plist SHA 9c7199ca1fcfedc09397255c932d25c6edc15779952bbd5b5bec2671e883d3f5. Observed not running, runs=0. It is not the prepared candidate.
- API PID 36518: hk-research-calendar-all-r1-20261007-api; manifest a82609515bb91c206e2437b64d09ce5e8a8ae38be144482c425d75a0e7d13f65. Process cwd matched this app.
- Close scheduler PID 36534: hk-research-calendar-all-r1-20261007-scheduler; manifest f64f62f50a5dcc8e251ffbad10188946ca6308850d8486eed8e156435b546605. Process cwd and plist workload identity matched. Its Python executable is the separately bound v15 runtime.
These active identities were read back, not installed or changed by this preparation batch. No API/close rollback or Stage activation occurred.

## Existing 10/7 execution, not a new natural result
The original 09:40:01.026007–09:40:09.649820 execution is RECOVERY/LATE_CATCHUP_REPLAY:
- Pool input run hk-d1-20260930-f45233cd1d30d04a; pool SHA f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901.
- Raw run 20261007-hk_connect_1min_stage_0930_0935-7cede698e1215da2; CSV SHA 48e24ef6788b1d6b604171c5ccaa44e88139739c36b08e5a0cb19c7b862208a0.
- Output run run-483b9e0e13a4c3777331ba0e; CSV SHA b712747ed325ff707a91e8b211e02add757cd85c5404b3e73c10a2a65650e61b.
- Canonical manifest SHA 10b453d27a131ff183cf1125327a3c79a8ff07795e3ddf9f461de67faf562fbe; canonical receipt SHA 8a44c5b28977e54813662c0d4e73ef234f9e51aa4018b0b2b345b5a44e1a290a.
Stored latest and current read-only API both return that run and 10 observation rows. Status stays PARTIAL_WITH_ROWS / OBSERVATION_UNVERIFIED with temporal-cutoff-unsafe evidence. Parent readback receipt SHA d83bd5d23f144e7859a2f5af751a5b43af0b549dd927bbe80f2e654bf5d8e77d. No new historical replay was run.

## Independent verification and limits
Four new pin tests, PIN_CHECK_OK and actual candidate --check CHECK_OK/16 nodes passed independently. The 19 race/source and 33 snapshot checks are reused only for identical frozen source/test identities. One existing historical test fails during setup due to a missing constant on unchanged R2 source; it is recorded as P2, not passed. Runtime Python 3.14.6 and five imported Stage distributions are recorded separately as observed dependencies; a service-bound reproducible lock/wheelhouse remains CANNOT_CONFIRM (nonblocking P2).

Old historical crossdate BLOCKED receipt SHA 2c9697aca108a8581befac1db381109f27533b09d3935aa3c9e6cb44d7e8a751 is preserved, not rewritten as PASS. Future real-time acquisition, natural triggers and same-run API/UI acceptance for 10/8 are NOT_RUN. Acceptance must bind actual date, pool/price/eligibility inputs, raw snapshot SHA, loaded release, execution mode and output run/SHA; existing stored results or a GET are not recomputation.

## Preserved close-source work
The separate close candidate hk-close-other-dates-r1-20261007-scheduler remains unactivated. Manifest b09f59e074707dfa0d7ece5e7a9921cada10d87e413e524f7c5ccbb6c359401b; independent receipt 6ad5f2f26619a998f6ec78cbb384b0cd8935c87c7302229b8e4c4d82b77987e8. Three isolated dates restored 100 model rows with unchanged close Top20/source SHA and PARTIAL states; 51 focused tests passed, and three broader failures reproduced on baseline. P2 gaps (future provenance dates, nested unknown fields, missing explicit legacy 8/25 PIT marker) remain recorded. No shared catchup or scheduler switch was performed.

The close canonical store snapshot contains a known pre-existing dirty change, preserved in place. Recorded before SHA a6260549e63fd2a904d77bd7b2856d8c3883557efb691a2715b9595128e27aaa and previous-diff SHA b068e0306ea95525d206f0b4b73d5e120af6571e0dc6b9614788a168eb750070 distinguish it from this batch; uploaded full files are receipt-bound snapshots, not a claim that all canonical changes originated here.

This handoff is a minimal delta/evidence snapshot, not a standalone installed application. Raw market data, full runtime manifests, local absolute-path maps, live configuration/plists, credentials, dist and virtual environments are excluded. The config is an example; the checker requires the protected local pin and installed candidate. Research safety remains production_allowed=false, buy_gate_updated=false, orders_sent=false.
