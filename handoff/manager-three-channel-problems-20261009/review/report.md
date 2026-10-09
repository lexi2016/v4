# Independent problem-package review

**Verdict: FAIL (P2).** No P0 or P1 findings. The package accurately bounds the three known issues and their unknown causes, and the directory, ZIP, and file hashes verify. One local acceptance step describes a live-root read as a replay of a frozen historical input, so the package is not ready to mark `REVIEWED` until that step is corrected.

## Scope and evidence

Reviewed only this package directory and its ZIP. I did not read or write business state, repeat the live loader probe, call the API, or run the business regression suite. The package contains 62 manifest files and 48 complete source records (20 preimages, 22 candidate-after files, 6 references); the source index records role, side, path, byte count, and SHA-256. No test files or raw market-data file formats are in the manifest. The package itself states that Chat must return focused tests and their actual results.

The issue boundaries are stated correctly in `package/problem_matrix.md:5-7` and the corresponding evidence projections:

- Announcement: target `20261009`, publication `20261008`, and `PARTIAL` / `NOT_IMPORTED` are reported; the first break among trigger, capture, handoff, and import remains `CANNOT_CONFIRM` (`evidence/announcement_projection.json`).
- US mapping: `VALID_EMPTY` is preserved with 33/33 configured and available, 4 reviewed, zero matches, and `full_market=false`; the 17:23 daily run and plan are `NOT_RUN` / `NOT_MATERIALIZED`, while trigger-to-consumer causality remains `CANNOT_CONFIRM` (`evidence/us_mapping_projection.json`, `evidence/current_api_readback_1723.json`). This does not demand a nonzero match count or claim that a scheduler rejection occurred.
- HK screen: the recorded 10/8 lookup lacks the exact key and produces the stated `StoreError`; the 16:01 snapshot and 17:34 observation are distinguished (36 entries through 9/30 versus 37 through 10/9, both without the 10/8 key). The 10/9 POST_CLOSE inner cause and whether the 695-record receipt is a D-1 master remain `CANNOT_CONFIRM` (`evidence/hk_reader_projection.json:19-20,39-52`, `evidence/hk_reader_reproduction_1734.json`).

`tools/verify_package.py` passed for both the package directory and ZIP, each reporting 62 files and no errors. ZIP SHA-256 is `2357304626a82907a8e2ee01ef1f2bb15521a61e39a3f21727208b4903334e1d`, matching the frozen value. An offline temporary extraction had 64 ZIP members, no duplicate or unsafe member paths, no CRC error, and every extracted member matched its packaged directory counterpart byte-for-byte. No business tests were run; current repaired behavior remains `CANNOT_CONFIRM`.

## Finding

**P2 — Historical HK acceptance input is not reproducible as written.** `package/LOCAL_ACCEPTANCE.md:7` says to run `tools/reproduce_screen_reader.py` on the frozen 16:01 input. The script accepts only `--authority-root` and `--trade-date`, then reads `assets/hk_security_master/latest.json` from that root at invocation time (`tools/reproduce_screen_reader.py:8-16`). It has no argument for a frozen snapshot or its bytes. The included evidence confirms the input changed: the 16:01 snapshot SHA is `7547d5c...`, with 36 entries through `20260930`, while the 17:34 repro SHA is `cc10ca8...`, with 37 entries through `20261009` (`evidence/hk_reader_projection.json:39-52`). The package includes the hashes and projected counts, not the historical `latest.json` itself. Therefore, `CANNOT_CONFIRM` that the acceptance step can replay the 16:01 input; running the tool against the authority root later would read whatever file exists then.

Correct the step to use the saved 16:01 receipt as historical evidence and validate patched behavior with temporary exact-date fixtures, or provide an explicitly frozen safe fixture/input path. Keep the instruction against writing to the real authority root.

## Transferability limits

Content transfer is verified from the bundled full files and per-file hashes. The claimed relationship between those files and Git commit `ca01c4d0260fecf7aae3c89e96899f36901bf8f7` is `CANNOT_CONFIRM` under this package-only review. Also, `manifest.json:6` sets `source_manifest_sha256` to `2288039fdfdc763904b943d57fb02ad16879b9fa5d7a2c4bc7e1b8b414ba4213`, while the packaged `source_index.json` hashes to `36ad5654634fefd79561729649b3e35a91bbaa8c966261ebae0f1bd33e930626`; the field's referent is not explained by the package or checked by the verifier. The source index and all listed file hashes themselves pass verification.

`REVIEWED=FAIL`; `BEHAVIOR_VERIFIED=CANNOT_CONFIRM`; no deployment, API/UI, or natural-session claim is accepted by this package review.
