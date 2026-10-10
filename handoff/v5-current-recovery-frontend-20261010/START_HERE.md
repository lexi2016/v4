# V5 CURRENT_RECOVERY frontend handoff

Scope: unchanged minimum frontend patch and full source images, for cloud integration. No deployment or product test was performed for this handoff.

Read MANIFEST.json first. Original patch SHA256: 757fff2254cdb714946f6efdeb4675c86bbc97ea41f5df0556bd290348bd9804.

## Files and exact baseline

- before/web/src/: three complete Mac preimages.
- after/web/src/: three complete TypeScript source files and one added test.
- The added test did not exist before; see BEFORE_ABSENT.json. No fake empty source preimage is supplied.
- Recorded Mac frontend release: e9c94a13a1407449a16b3fa731bd0ef46867cf34. managerWorkspace.ts and catalystObservationPanel.ts preimages exactly match Git blobs at V5/ui/manager-workbench/source/apps/web/src/ in that commit.
- dailyChannels.ts is present in the Mac preimage but absent from that fixed Git tree. Its exact preimage SHA is in MANIFEST.json. This is not a clean all-files Git baseline; cloud must reconcile this dependency and current source without overwriting its tree.
- Original patch paths use e9/ and candidate/ relative to web/src. Compare each current file with its before-image SHA before any application. after/ contains only the scoped file images, not a repository replacement.

## Critical test limitation

The original added test is NOT self-contained synthetic data: it reads ../evidence/manager-read-publication.json and asserts the existing saved run/SHA. The real fixture is deliberately excluded. The test and patch remain byte-identical to the approved Mac copies. Cloud owns any later portable/synthetic-fixture change and its validation; absence of that fixture must not be reported as a test pass. No real announcement text, decisions, semantic catalog, manager response, credentials or local configuration is included.

## Relation to earlier backend fix

2bfb4c8c5f770122077e3baf914cf5b05b8a2450 handoff/v5-blockers-fix-20261010-r1/manager/changes.patch is a separate Python backend patch, not this frontend delta. Do not replace newer backend or current US/native identity code with an old tree.

## Publication and verification scope

Only this handoff directory is added on a separate branch rooted at the recorded frontend release. v5/cloud-preview-20261010 and local V4/61796 are not modified. Payload SHA256 values are exact local bytes; Git blob IDs permit remote readback checking. Reconstructed unified diff equals the original patch byte-for-byte. Existing product tests were not rerun. IAB remains unavailable in the current Mac tool list; no UI verification is claimed.
