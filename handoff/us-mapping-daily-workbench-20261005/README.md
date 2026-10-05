# US → HK research on the manager workbench

The existing 2026-09-30 manager workbench now shows five reviewed relationships: three priority rows and two watch rows, with official sources, product maturity, US session and review dates. The original failed pre-open plan remains visible. Other target dates do not inherit these rows.

This page-only milestone is implemented, independently tested/reviewed, integrated, deployed, and verified through the live API and actual browser. The daily workflow is still an isolated candidate; natural execution is not verified.

The active local release is `manager-us-mapping-r17-20261006-page-r1`. `PAGE_DELIVERY.json` binds its manifest, source hashes, canonical differences, tests and failure/rollback history. The seven deployed files are reconstructed by applying `release_delta/page_overlay.patch` to R15; `canonical/` holds the scoped canonical source including pre-existing edits retained during integration. These are distinct identities. The repository baseline commit is `759a1797df28574f73ab90d5005cc14c98ca1c14`; earlier handoff folders contain its release/source context. No full repository snapshot or raw live response is uploaded.

A real-browser failure in R16 was retained: an omitted unknown-count field caused strict frontend rejection. R17 explicitly returns null while preserving the strict validator. Independent checks passed 13 frontend tests, one Python page-boundary test and actual owner GET → validator → rendered component. Live browser acceptance confirmed all five rows and retained announcement counts 23/10/103/4. Missing research on 2026-09-28 does not carry over 9/30 rows.

Research only. Target-date eligibility and historical PIT remain CANNOT_CONFIRM. No Stage/BUY gates or orders were changed.
