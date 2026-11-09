# Company materials lifecycle repair

Current workbench source day means current research on the latest numeric candidates, with its evidence origin separate. Older selected source days are historical asof views: received/public evidence after that day is excluded; absent local receipt time is UNKNOWN and excluded. The latest view may show legacy evidence with UNKNOWN receipt time, always labelled historical/unreviewed and never PIT certified.

Reader validates the current candidate membership, generation and input SHA; each material independently validates its original immutable numeric origin, source candidate scope and shard SHA. A same-day numeric replacement does not rewrite the old evidence identity. Material revisions retain earlier references in `company_materials_versions`.

The existing importer V1/V2 contracts remain accepted. V3 consumes the received RESEARCH_MASTER/SOURCES/INDUSTRY_SECONDARY files and the exact original candidates/performance/manifest references. It preserves received PARTIAL, UNKNOWN, priority order, industry mapping, raw financial fields, original source times and source hashes. JSON/text aliases are projections only. Narrative financials are not parsed or promoted into verified facts; received normalized numeric fields are shown verbatim with their research scope.

V3 requires an explicit actual local `received_at`. A late return binds only its own source day in the company index, leaves latest numeric and completion event content unchanged, and uses the existing workbench module version/SSE invalidation path. The original pinned owner publisher/adapter performs writes under its shared A_LONG lock and index/event CAS. No provider, scheduler or second producer is added.

Verification: 20 targeted Python cases (including real 371-row mechanical raw-record and industry equality, original owner CAS/lock, cross-day, late return, same-day generation replacement, unknown/future receipt, future public dates and new candidate without evidence). Seven Node cases pass, with old 238/364 live-artifact-only tests not run; three actual representative new views and 002047 legacy reuse render in a DOM fixture. These are isolated projections, not installed API/UI verification or financial/PIT certification. Independent review and actual API/UI acceptance remain separate.

Safety: RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false.
