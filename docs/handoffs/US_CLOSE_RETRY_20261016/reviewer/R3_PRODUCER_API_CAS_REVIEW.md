# R3 Producer/API and CAS Independent Review

Date: 2026-10-16  
Reviewer: independent read-only reviewer  
Scope: frozen R3 producer/API binding and US-only compare-and-swap activation candidate. No live capture, activation, rollback, or service mutation was run.

## Verdict

**PASS for the reviewed target case**, with one non-blocking P2 edge boundary recorded below. This PASS covers the R3 target’s distinct-timestamp binding path and the plan-only US CAS preflight. It does not claim post-activation, live API/UI, or natural-slot acceptance.

## Producer/API evidence

R3 application manifest SHA256: `592bb39ce93fd9d564d34088403d96fd14213c2380991b239a458e80c72a9139`. Its 1,188-entry inventory differs from active R1 only at `ops/_us_market_digest_parts/phase_merge.py`, SHA256 `daf48ff122eb46368fa909562cad86c25106c0cc2072fcfa462d9275544e181b`.

The revised isolated canary driver SHA256 is `14a9b81866345278dc2f39f97fa12a4744b18de8f8d2475a94c35fca6a81968e`. Its evidence files pin API R4 manifest SHA `a2dd8358300d0b61e8a365ed1ac8fe57e5872857208d5bd888e505b47a6cb135` and consumer module SHA `e7f85cda8d26203b7e0d6c8824525d57ac65ab286106a14adfc55aecfd4ee39d`.

I reran both updated temp-only controls using the configured v3.5-mac Python; each exited 0:

- R2 control receipt `candidate/evidence/us_close_r3_api_consumer_canary_r2.json`, SHA256 `2db2853453e50f27620e14a85fb50483099b49baaa12593be6c41de6c475f70b`: the actual API R4 consumer returns `CANNOT_CONFIRM / MARKET_SNAPSHOT_CAPTURE_IDENTITY_AMBIGUOUS_OR_UNBOUND`.
- R3 receipt `candidate/evidence/us_close_r3_api_consumer_canary_r3.json`, SHA256 `f1261c79d8156742339fe49aa35a6d43ec38c42a02a3a0932318d0ba17aed794`: the full R3 producer runs against a temporary copy of the exact R2 V3/48 preimage; the actual API R4 projection returns READY with 48 requested/available symbols and binds the snapshot to `capture_id=9fc8810ac4974980a2c81db6`, `run_id=us-rss:20261015:POST_CLOSE:9fc8810ac4974980a2c81db6`, and the same captured/bound timestamp `2026-10-16T04:35:00Z`. The canary confirms both prior capture IDs remain in the merged payload and confirms the hash-addressed history bytes exactly equal the V3/48 preimage (`3c395a48f7d5d52f49e52cbbe77859bde661719b9bc01dfc1664e53a1f01c8c3`); its paired receipt hash is `22611d26644a4259f4c22331ea46f911d51bcfe4891679acdc3c46dff3fbd6fc`. Producer HTTP responses are synthetic and the API reads only the temporary store.

Focused source regression command previously rerun against this unchanged helper SHA: `/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python -m pytest -q -p no:cacheprovider --basetemp=/tmp/us-close-r3-source tests/test_us_close_retry_20261016.py` → **11 passed**.

### P2 edge boundary (non-blocking for this target)

At `ops/_us_market_digest_parts/phase_merge.py:119-124`, `snapshot_match` is assigned with `next(...)`, so tied timestamp matches are not required to be unique. I reproduced a silent provenance mismatch with two valid producer payloads having the same `captured_at=2026-10-16T00:30:00-04:00` but distinct explicit IDs/runs (A=`a…a` / `run-a`, B=`b…b` / `run-b`). Equal-time snapshot merge selects incoming B (its quote value is 202), but R3 stamps A’s identity from the first matching capture; the actual API projection then returns READY bound to A. The focused regression at `tests/test_us_close_retry_20261016.py:833-888` covers distinct timestamps, not ties.

The current pinned preimage’s two capture timestamps differ, and the parent will verify the upcoming target capture timestamp is distinct before the real refresh. Whether this tie occurs in natural data is **CANNOT_CONFIRM**. Per the parent’s scope decision, this is recorded as a P2 backlog boundary and does not block this target-scoped PASS.

The canary proves preservation of the immediate R2 V3/48 preimage. It does not independently prove retention of the earlier V2/33 artifact (`e65a6e82e21f7cba1667be19e01957184da6e415c329bbeb9ee5f4f934a3c368`); that historical link is **CANNOT_CONFIRM** in this receipt.

## CAS evidence

Final R3 activation helper SHA256: `64f8e55ab30717906dae14057af26e0b7f3b1a5fb8d76b50a9d85303287060c5`. Candidate plist SHA256: `d9cc2ea72a17177a5054d1034a9a361af4cf10b5a08036b476ade505ffc74f7d`. The R3 helper’s candidate pins resolve to manifest `592bb39c…a9139`, while the active-pair CAS is pinned to the R1 manifest `3793d0acb6937828fccc0c6f1a5331be699e7ad62ac448654050a62ab70225a9` and the R1 plist backup SHA `9aa5c54d2b75f59f039da3618453a1abc99d1e8662875a87409f201d0023b5bb`.

Focused R3 CAS tests: `test_cas_activation_r3.py` → **3 passed**. They exercise both US plist/manifest checks after bootout and the final manifest-then-plist CAS check immediately before replacement. The default no-flag helper invocation exited 0 with `PLAN_READY`, `mutations_performed=false`; it verified the active US plist/R1 manifest pins and no active US process. No `--apply` or `--rollback` was run.

Plan output reports three non-US plists whose hashes differ from the 2026-10-16 baseline as `EXTERNAL_CONCURRENT_CHANGE`; their manifests still match. The helper treats these as observational, does not block the US-only plan, and its activation code only targets the US LaunchAgent. The observed differences are not attributed to this review or to this candidate.

## Remaining acceptance

Live R3 recapture, API/UI projection, and any activation are outside this review run and remain **CANNOT_CONFIRM** until separately verified.
