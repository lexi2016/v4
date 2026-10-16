# Runtime independent review
Reviewer: `mapping_recovery_review` (independent from `mapping_recovery_writer`)
Candidate manifest SHA256: `ae2ca8cee0380217b8c09a3dc3baed5cc88f27c82b02d4cd68668b15d79c5359`
REVIEWED=PASS — The fresh R2 candidate, frozen delta, preserved base entries, activation guards, and focused rollback behavior pass this bounded runtime-readiness review with no P0/P1/P2 findings.
BEHAVIOR_VERIFIED=PASS — Independent in-process API assertions passed against the prepared candidate. Live API/UI behavior and activation remain CANNOT_CONFIRM because the candidate is not active.

## Candidate and base

The candidate is `us-hk-recovery-v2r1-20261016-r2`, prepared against the current API-only base `futu-industry-api-20261016-r2` (manifest SHA256 `da83203770b86b1b092f003b287e4622505e5a95ba8a5abadf0aace25420a9c5`). The active plist SHA256 remained `46ac14b7cc3f2486ec86860d628301ea3fa58b771a6c06e18dc06b02845f6e0e` in the independent verifier and API-checker pre/post checks. The candidate manifest SHA256 and versioned config SHA256 are `ae2ca8cee0380217b8c09a3dc3baed5cc88f27c82b02d4cd68668b15d79c5359` and `589eaa058b9abd9cef59ab71ef2c3f4c3c998bae18dd26777134bf0fa22ef86e`. The candidate config changes only `relation_root` to the candidate app root.

An independent `verify_api_release_candidate` run with `active_pointer='base'`, `role='gateway'`, `base_role='gateway'`, and the shared release lock returned PASS. Its exact delta is the six prepared paths: the manager-selection JavaScript and HTML, `Workbench.vue`, `types.ts`, the new US-HK recovery overlay, and `us_mapping_catalog.py`. It confirmed all 1,211 non-delta entries match the Futu R2 base byte-for-byte (inventory SHA256 `64887c095d00f6be15c03385b3f6c6a0158eda9f6a7ee1a3f536e59da3f33723`). This retains the fresh Futu R2 changes and prior application contents outside the frozen delta.

The staged plist SHA256 matches the prepared receipt. Its changed selectors point to the R2 candidate release, candidate config, manifest, and working directory; label, port, KeepAlive, and RunAtLoad remain as in the active plist. The saved rollback plist is byte-identical to the current active plist (SHA256 `46ac14b7cc3f2486ec86860d628301ea3fa58b771a6c06e18dc06b02845f6e0e`).

## Helper and behavior review

The R2 activation wrapper preserves the accepted rollback repair. After normalizing the R1/R2 candidate, receipt, and import identity strings, the activation-helper diff is identical. The rollback path attempts detach, restores and reads back the saved plist even if detach confirmation fails, then bootstraps the prior service only after both detach identity and plist restoration are verified (`activate_runtime_candidate_r2.py:179-251`). Its preflight checks active plist/config, candidate config, staged plist, and rollback-preimage hashes under the shared API release lock, and the candidate verifier requires that lock lease (`:294-319`). The R2 API checker pins the exact candidate app/config paths, checks the active base under the lock, and verifies the candidate again after the in-process assertions (`check_candidate_api_r2.py:38-77, 178-199`).

The independent in-process API checker exited 0 and confirmed 667 stocks, 1,003 original/processed relations, 757 `CLOSED_RESEARCH_SCOPE`, 25 `CLOSED_EXCLUDED_SCOPE`, and 221 `OPEN`; exact records R006/R003/R001/R700; and prior-700 history SHA256 `d45d44fb074fc82923a0af5e37a8d645923a84acb48dc2bb1794b1f4ddc98c69`. The reported safety state remains `RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`, and `orders_sent=false`. Semantic mapping validity remains `CANNOT_CONFIRM`; independently accepted facts remain zero.

All three focused R2 rollback tests passed. They cover failed detach confirmation with plist restoration and no bootstrap, successful rollback after proven detach, and restore failure with bootstrap skipped. The R2 preparation receipt also records PASS for the isolated mapping UI test, Vite build, and focused Vue typecheck; the source-review receipt SHA256 is unchanged at `cf796bb7da55547c84cea24c9ab63096398fd56f01c39b5e8f3690988f31ce7a`, so its frozen source review is reused.

## Findings and limits

No actionable P0, P1, or P2 finding was found in the frozen runtime candidate scope. The R2 review-receipt parser accepted this receipt for the candidate manifest SHA without invoking activation.

`CANNOT_CONFIRM`: activation and live candidate API/UI readback were not run; launchd rollback behavior has only focused injected-branch tests, not a real activation failure; natural-slot behavior was not run; semantic mapping validity, PIT validity, prediction validation, and independent fact acceptance remain unestablished. This is an activation-readiness verdict for the prepared candidate, not deployed API/UI or overall workflow acceptance.
