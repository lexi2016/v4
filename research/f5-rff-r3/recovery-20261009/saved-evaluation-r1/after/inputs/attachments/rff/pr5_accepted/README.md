# PR5 accepted RFF truth-join evidence

Accepted repository: lexi2016/v4
PR: 5
Reviewed head: 66a57bead52a20845e1d2af6035c7f19f0b04ed7

The accepted route-local RFF worker SHA256 is 3ea10757a81207147e5cfb9e68e69750a0579786153e7ce58ccf342a3184058c.
The scoped test test_rff_truth_join.py SHA256 is c19f32aee9aae82919e49583ec041da97852ce5520918810ab1e14e3446980ad.
The independent Mac review receipt SHA256 is 28f5cac31469a488987bffba4a799ba73910392bff36e74403dcfd42edd20630 and records 29/29 scoped synthetic cases passed.

This is synthetic scoped behavior evidence only. It does not establish full-worker or L04 acceptance, and it does not identify which historical real row or key triggered CANDIDATE_TRUTH_JOIN_DOMAIN_MISMATCH. Keep the prior candidate execution and its original worker binding immutable. A future zero-fit saved-evaluation binding must bind/reuse this accepted helper SHA; do not create a second join rule or treat the older worker copy in rff/pre_pr5_historical as accepted.
