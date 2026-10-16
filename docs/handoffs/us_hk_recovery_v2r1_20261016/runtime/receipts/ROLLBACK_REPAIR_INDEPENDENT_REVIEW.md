# Rollback repair independent review
Reviewer: `mapping_recovery_review` (independent from `mapping_recovery_writer`)
REVIEWED=PASS — The bounded rollback repair addresses ACT-ROLLBACK-01: detach errors are retained while original-plist restoration is attempted and byte-verified, process identity is preserved, and prior-service bootstrap is gated on confirmed detach and identity.
BEHAVIOR_VERIFIED=PASS — All three isolated rollback tests passed; the default helper run stayed PREPARED_ONLY, and the no-authorization read gate rejected activation before side effects.

Scope is the rollback repair only. No overall runtime candidate or activation PASS is issued.

- Independent rerun: `PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 .venv/bin/python -B -m pytest -q --basetemp=<reviewer-owned temporary directory> docs/handoffs/us_hk_recovery_v2r1_20261016/runtime/tests/test_activation_rollback.py` → 3 passed.
- The tests verify restoration after detach failure with unknown service identity (including preserving the detach error and skipping bootstrap), normal detach/restore/probe/single-bootstrap ordering, and that a failed plist restore prevents bootstrap and returns `ROLLBACK_INCOMPLETE`.
- Independent default run returned `PREPARED_ONLY` with `launchctl_called=false`. `--activate` without a root-authorization reference returned `EXPLICIT_ROOT_AUTHORIZATION_REFERENCE_REQUIRED`; the active plist hash remained unchanged and no activation receipt was created.
- No P0/P1/P2 finding remains in the bounded rollback repair. Real launchd detach, restoration, and service restart behavior remain CANNOT_CONFIRM because the tests use isolated mocks and no activation or rollback was run.
- The prepared candidate is stale: current active plist SHA256 is `46ac14b7cc3f2486ec86860d628301ea3fa58b771a6c06e18dc06b02845f6e0e` and selects `futu-industry-api-20261016-r2`; the prepared plan expects plist SHA256 `d601d017cbf1f893949c44a5e321458c7e5a3c81216601cfb4133c4781f44e1a`. Candidate activation eligibility and live candidate API/UI behavior are CANNOT_CONFIRM and are not covered by this repair verdict.

Reviewed helper SHA256: `fd1a9dbbbe5a2f831c44fa990aa38bb2fab48da46e505a9290d36faef649c8f7`.
