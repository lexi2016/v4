# R2 local research API activation authorization

The controller authorizes mapping_recovery_writer to activate the independently accepted us-hk-recovery-v2r1-20261016-r2 candidate under the existing user-authorized mapping integration and local research deployment scope.
Candidate manifest SHA256: ae2ca8cee0380217b8c09a3dc3baed5cc88f27c82b02d4cd68668b15d79c5359.
Required independent review: RUNTIME_INDEPENDENT_REVIEW_R2_20261016.md and RUNTIME_INDEPENDENT_REVIEW_R2.json.
Use only activate_runtime_candidate_r2.py with the shared API-only lock, fresh compare-and-swap checks, accepted rollback logic, actual process/config/static/API readback. If baseline moved, abort before mutation and report exact conflict. Only API-only service8873 and its plist selector may switch; scheduler,8910, trading, pools and business stores are forbidden. No historical run rewriting or new model/BUY eligibility.
Return actual deployment receipt with current runtime identity and outcomes.
RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false.
