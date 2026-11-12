# Main / Stage control preparation

Source repair was independently accepted `REVIEWED/PASS`; source, test, inline delta and `SOURCE_BINDING.json` are frozen. This supplement covers the later controller-authorized inactive release preparation only.

Prepared root: `/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-prepool-publication-20261112-r1`.

- `PREPARE_RECEIPT.json` SHA: `2233b7461dbe914fb490de5cdac7d1af7529f28a027700c090f7681976272734`.
- Main manifest: `1ecc6373c11eb36ff09881d925be20607e612ce2eab8a2c19961f16513b99643`; proposed plist: `1bcb97f70f9eccdb686ed33b5f764444111b15b24d33404974d9b6c1757a2973`.
- Stage manifest: `6fd32ec201f928cd96ef73227381b948d9d3a3d27bad45863295d3fe7bf5b94a`; proposed plist: `e6199d7e846bb24938db915d035f3892346e0fc2d7296206c9e88a5a3f5e82b0`.

`prepare_main_stage_candidate.py` reuses the existing inventory/APFS clone/pin/reader preparation pattern from the previous Main-only release and Stage owner-repin scripts. It verified all 1,037 Main and 1,005 Stage inventory entries before and after copying. Main changes exactly the two accepted inline files. Stage changes only `stage_center_tick_config.json`: new Main current owner, prior current owner appended as historical owner 11, release identity; transition binding unchanged. No Stage source code or membership, formula, model, BUY, schedule, pool or numerical rule changes.

The Main policy retains its previous behavior and refreshes source pins, reader attestation and future live Stage plist SHA together. There are 38 pin-reference changes: remapped Main source references, the three declared Stage references, and the Stage plist identity. Other sources remain pinned to their existing content. The Main plist is excluded from circular pinning by the existing policy.

The first preparation stopped before any candidate directory was created because Main's Stage plist pin was stale. Keep `PREPOOL_PREPARE_LOG.txt`. The controller accepted only the already deployed membership transition:

- Membership `before-stage.plist` exactly `24355058e5aacf2df8cfe0d3c1269f1ea012aff2b2d4be0544ac584223a15af6`, equal to existing Main pin/reader value.
- Membership `proposed-stage.plist` exactly `10212fdf1526e88b7a654a9161a0028fd6e66a3479fd2e106b32726e1ecc4dfd`, byte-identical to actual live Stage plist.
- Stage manifest exactly `61bbf480d8833c7e43c5cdfe780a8f23f0d341e799c47dc52e38ec4266ba6aa4`; real inventory matches. The two registered Stage code refs have unchanged content; the third config ref is rebound from the previous control clone to actual membership plus the new owner-only change.

The successful receipt records these exact before/proposed/live identities. Every other pin/source mismatch still blocks. Original live plists and Main policy were checked unchanged at the end of preparation.

Command run (existing `PANEL_PYTHON`, cwd worktree):

```sh
"$PANEL_PYTHON" docs/operations/prepool_repair_20261112/prepare_main_stage_candidate.py \
  --candidate-root '/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-prepool-publication-20261112-r1' \
  --evidence-root /Users/lexi/Desktop/学习/agents调试/v4_prepool_storage_repair_20261112 \
  --expected-main-manifest-sha256 558d313eb3181ae6bf030b95bc552df40c0a052f4e34e413e05f5e94b1817d55 \
  --expected-stage-manifest-sha256 61bbf480d8833c7e43c5cdfe780a8f23f0d341e799c47dc52e38ec4266ba6aa4
```

Result: `PREPARED_NOT_ACTIVATED`. Evidence: `PREPOOL_PREPARE_ACCEPTED_TRANSITION_LOG.txt`, `PREPOOL_MAIN_STAGE_PREPARE.json` in the same evidence root. New candidate is a required deliverable and is retained. No activation, service action, live plist/config write or producer/backfill was performed. Incremental independent identity review, coordinated controller activation and existing-owner backfill remain required. The backfill recipe is in `WRITER_HANDOFF.md`; preserve original failed receipts and label actual replay `BACKFILL`, never natural.
