R2 identity repair, 2026-10-29

R1 baseline a569b60841fd1e1f3728f6f3694c3f0cfff6012c is preserved.
Both pinned original parquet captures contain 19 market=99 rows, for raw codes
161506 and 519666; neither numeric code intersects the requested identities.
R1 rejected its first such row before producing any plan or provider request.

The adapter retains market 99 rows in GBBQ_MARKET_99 without inferring an exchange.
Every original field/category/duplicate remains in the row fingerprint. A numeric
collision with any requested code blocks planning; unknown markets other than the
observed 99 and invalid identity types still fail closed. The planner supplies its
complete requested-code set to both original detectors before routing exclusions.
No mathematical, provider date, input, default, pointer, or service change.

Targeted synthetic and affected original tests: 59 passed (prior 51 plus 8).
Python: v4-mac, isolated -I -B, explicit source-root sys.path for pytest.
Initial isolated pytest collection lacked ops on sys.path; that failure is retained.
Real offline canary and independent review are pending Root registration/dispatch.
Frozen evidence: Factor Factory research/a_daily_update_path_20261029_r1/factor_cache_r2.
Highest status: engineering candidate. RESEARCH_ONLY=true; production_allowed=false;
buy_gate_updated=false; orders_sent=false. No provider-current or historical PIT claim.

Next-stage integration design (read-only proposal, outside this repair)

The current Main release pointer_ready checks QFQ adapter, input adapter, factor
cache and TDX adapter SHA independently against current files. generation_identity
also binds driver, formula, field contract and user formula. Its readiness code_refs
are checked again, so replacing only factor/cache bytes invalidates the old D29
generation even when accepted panel bytes are unchanged.

Freeze an explicit accepted-generation compatibility record containing the exact
old generation ID, target, selector/backtest panel contracts, snapshot SHA,
readiness proof SHA, full original generation module tuple and exact deployed
successor tuple. Resolve old code_refs to their immutable old release files and
verify every SHA. Permit only that complete old tuple for read/ready compatibility;
all altered fields, unlisted generations and mismatched successor tuples fail
closed. New generation creation continues to use only current module identities.
Do not delete SHA checks or relabel the old generation with new code identity.

Before enablement, implement QFQ consumption of the distinct research schema and
original-provider provenance, plus Main's explicit opt-in config binding. Keep the
old default path until schema acceptance and compatibility tests pass. API has no
ops/research_panel_qfq.py in its current release; locate its actual panel consumer
and prove old accepted generation stays readable before choosing API patch scope.
Freeze this larger release scope separately, then validate old D29 read/ready,
new typed carry consumption and restart/invalidation with bounded samples, followed
by a reversible Main/API switch and Root-controlled natural-run evidence. Do not
force a full-market recomputation to accommodate module changes. The unaccepted
15:30 schedule remains disabled; official package timing remains separate.
