# HK history Phase 2 review and archive receipt

Recorded 2026-10-15. Independent Luna Max review returned `REVIEWED` / `BEHAVIOR_VERIFIED` for the frozen Phase 2 candidate: dynamic C-owned data resolution, the exact ten-file relocation, and the bounded candidate API behavior. This is an archive of the review outcome, not a claim of canonical-data semantic validation, scoring activation, or deployment.

## Review sequence

- Phase 1 received a P2 finding because a generic reconciliation writer accepted an arbitrary output path. That writer was removed; the bounded adapter, five focused tests, and frozen B/C reconciliation then passed independent review.
- Phase 2's first review found that the aggregate “16 LaunchAgent plist hashes unchanged” observation lacked a retained per-file before/after map. The receipts were narrowed: aggregate equality remains a writer observation and all-16 identity is `CANNOT_CONFIRM`. The active API and HK scheduler plist each independently match their supplied baseline SHA. The final review passed the bounded Phase 2 scope while retaining the all-16 gap.
- The independent Phase 2 evidence reused here is eight focused tests and three frozen real-key canaries, each checked through the adapter and isolated `TestClient`. Existing JSON receipts were not changed after review; their pending-review status records the writer handoff time. This receipt records the subsequent final verdict.

## Reviewed identities

| Item | SHA-256 | Review/archive note |
|---|---|---|
| `v4/hk_research_history.py` | `ca4407478ac6d8f8e1392aeaff8da3fe8a4034ec30ac11fb71abcb92c34eca2b` | Final adapter |
| `tests/test_hk_research_history.py` | `0924b5dde78611023429b807f482c086058a3e20e838a96c92c6cf003ae0e35b` | Final tests; independent result 8 passed |
| `v4/manager_workbench/api.py` | `b71d52e88dbf8898995611ec8649914672f6fce6c66eb0e5e5b1167c969d227b` | Candidate file; the HK-only diff SHA `721cba5882ca03994f6e874a3e001e63d4255bb12d64c073c26799253a3a1e3d` is recorded in `PHASE2_RECEIPT.json` |
| `SCOPE.md` at review | `1f189df9821754bbbdd16422065596402b74c902a58d5b152f145e546c1a6356` | Reviewed scope before the status-only archive annotation |
| `MOVE_RECEIPT.json` | `fdad2a1e5e784db061459fa07e3746ff2dbfb855fcff9c11fc5b5d71cbc84398` | Not changed after review |
| `PHASE2_RECEIPT.json` | `f61e0e1b8f9ce9670b25102d0e060db358d7420c33b7c1f9efb979640bb77898` | Not changed after review |
| `reconciliation.json` | `8ef66157427b968ba9302ecc337e93c663896565355f2798c9710f0494912a81` | Frozen Phase 1 reconciliation |
| `SCOPE.md` after archive annotation | `b4eb5555af069a2fefdebadb26b3ca57d33fb69dcd11abf196f00f98901d353f` | Status wording only; reviewed SHA above is preserved |

The API candidate SHA identifies the full workspace file, which also contains pre-existing unrelated mapping content. For archival/Git synchronization, retain the HK-only unified diff and its SHA from `PHASE2_RECEIPT.json`; do not package the unrelated full API file as a new artifact.

The installed C owner descriptor at `.../assets/hk_0_2/research_history.json` is 5,604 bytes with SHA-256 `54fbb5dd3db15353c06045bdf2be1937536b2873c58652dc6040a3073ec927cc`. The new docs copy has byte-for-byte identical content. Its resolution remains dynamic through `panel_latest.json` to the manifest and panel it names. The reviewed snapshot identities are recorded in the unchanged receipts: B daily bars `17f5b62b6ec0264d48b6ee66ce0cd31aa8c1deb661e3e765b90b780add2eb230`; C pointer `47e680a7e58cf0985fffead2149ed1e8c3b1a9ec93a5c1f7f9e5f5ba93e6282c`, manifest `4c9a6c325a17e5341d6f1a9d82bdb89a688df6b36759222cac8c8c920657a76d`, and panel `3958528f34416925df7d5e5ba4bfdde4e92ad35494b1712eacc20013df59cb37`. A/B feature and label files remain metadata-only references; their payloads were not read.

The two exact five-file packages were moved by same-device rename, with source file hashes and directory inodes retained in `MOVE_RECEIPT.json`; original paths remain absolute symlink aliases. The directory inodes are `853403` and `26263824`. No source payload was deleted or copied during relocation.

## Runtime and evidence boundary

The candidate is research-only (`production_allowed=false`, `scoring_allowed=false`, `buy_gate_updated=false`, `orders_sent=false`). No release copy, reload, or deployment occurred. The parent's live request to port 8873 returned 404 for the history route, as expected while the candidate is not deployed; this does not change the isolated candidate pass. Raw units, currency and adjustment basis, and point-in-time safety remain `UNKNOWN`. The all-16 LaunchAgent identity claim remains `CANNOT_CONFIRM` because the per-file map was not retained; the other 14 plists are not individually verified. Review does not establish semantic validation of canonical data or scoring activation.
