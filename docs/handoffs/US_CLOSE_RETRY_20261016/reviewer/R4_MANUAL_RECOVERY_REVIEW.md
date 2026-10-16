# US close retry R4 manual recovery review

**Verdict:** `REVIEWED: PASS` · `BEHAVIOR_VERIFIED: true` for the corrected manual plan preflight and the existing producer's replacement-history path.

**Scope:** Only the R4 manual recovery script/configuration increment and preservation of the existing `20261016` V2/33 payload. The candidate package is pinned by manifest SHA `3793d0acb6937828fccc0c6f1a5331be699e7ad62ac448654050a62ab70225a9`. No `--execute`, provider capture, or API/UI/natural-slot verification was run by this review.

## Reviewed files and evidence

- `candidate/recover_20261016_post_close.sh`, SHA-256 `1e1b8d33a627a27658bfdf3912d54b7225cf6feadef61c755043db5c1c2b6bb6`.
- `candidate/evidence/test_recovery_script_contract.py`, SHA-256 `57d064c3a703c3f07c045422205280036ab752411717aa020e8a91ad8322ab3a`.
- Both hashes match the current entries in `docs/handoffs/US_CLOSE_RETRY_20261016/CANDIDATE_SHA256SUMS.txt` (lines 43 and 49).

The script exports the candidate owner root, release ID, manifest path/SHA, and explicit manager-workbench config path before importing the producer (`recover_20261016_post_close.sh:29-33`). Its read-only preflight checks the exact config and manifest hashes and the resolved V3/48 contract (`:50-75`), then requires the current V2/33 `20261016` / `20261015` payload to match its pinned raw SHA, READY status, and 33/33 counts (`:77-93`). Execute mode remains explicit; the test invokes plan-only and asserts the target bytes and recovery-receipt directory remain unchanged (`test_recovery_script_contract.py:21-48`).

Independent targeted test command, using the candidate runtime Python:

```text
'/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' -m pytest -q -p no:cacheprovider --basetemp='/Users/lexi/Desktop/学习/agents调试/V4_US_CLOSE_RETRY_20261016/candidate/pytest-review-owner-preflight' '/Users/lexi/Desktop/学习/agents调试/V4_US_CLOSE_RETRY_20261016/candidate/evidence/test_recovery_script_contract.py'
```

Result: `1 passed in 0.13s`.

The pinned producer path at candidate `phase_publication.py:352-360` calls `ResearchPeripheralStore.replace` with the existing payload digest. The store checks manifest, prior payload, receipt, and date/source identity before writing (`research_peripheral_store.py:1234-1255`); it writes the prior payload to a digest-addressed history path and writes a supersession receipt naming the prior digest before replacing the current payload/receipt/manifest (`:1270-1310`). An independent temp-only probe cloned the exact current V2/33 payload, its receipt, and manifest into an isolated directory under the candidate evidence tree, called this same `replace` implementation with a synthetic timestamp-only payload change, and passed: archived JSON equaled the original payload, all 33 quotes and its capture/provider receipt were retained, the supersession's previous digest matched, safety flags remained false, and the real target bytes were unchanged. The temporary directory was removed.

## Risks and limits

- **P0:** None found.
- **P1:** None found.
- **P2:** `candidate/CANDIDATE_RECEIPT.md` still lists the earlier recovery-script SHA `cd0e59f9c365648ff9fbaf94391e80a3a72ad53280ff8de6a1828ca2e0545171`; the checksum ledger and evidence index identify the reviewed current script SHA above. This stale narrative hash does not block this review because the reviewed file is unambiguously pinned by the current checksum entry.

`CANNOT_CONFIRM`: whether a real provider run will return all 48 quotes and publish an accepted V3/48 close; actual corrected `--execute` outcome; subsequent API/UI readback; and natural-slot retry behavior. This receipt covers the manual script contract and isolated preservation behavior only.
