# Independent review evidence

**Candidate scope only: `PROPOSAL_ONLY / LIVE_API_UI_NOT_RUN`.** The conclusion and its limits are in `docs/INDEPENDENT_REVIEW.md`, relative to the delivery root.

| Evidence | What it records |
|---|---|
| `package_verification.json`, `verify_package.log`, `check_evidence_contract.log` | Supplied verifier and contract results, independent actual ZIP CRC/member match, and byte-identical reports. |
| `receipt_crosschecks.json`, `receipt_crosschecks.log` | The independent 44-assertion receipt/source audit, exact recovered source hashes, and evidence limitations. |
| `ORIGIN_REFERENCES.json` | Origin package filenames and SHA-256 values. Supplied screenshots and raw market/owner data were not copied here. |
| `backend_review_initial.log`, `backend_review_after_legacy_fix.log` | Independent failing scheduled legacy-reuse regression and its passing rerun after correction. |
| `backend_final_baseline.log`, `backend_final_candidate.log` | Same final 21-method backend suite: 19 baseline assertion failures including subcases, no errors; 21 candidate passes. |
| `backend_scale_probe.json`, `backend_scale_probe.log` | Synthetic 1,970-material/40-binding diagnostic size and source-locatability check. |
| `frontend_independent_suite.log`, `frontend_harness_provenance.json`, `frontend_rendered_source_hashes.json` | Final frozen 23-case real-panel suite plus one independently added text-rendering test; exact harness, fixture, runtime, and source identities. All requests stay offline. |
| `frontend_red_narrow_implementer.log` | Attributed implementer failure of the intermediate 670×900 layout; all three status labels were below the initial viewport. |
| `frontend_viewport_probe.log`, `viewport_geometry.json` | Independently authored final four-size geometry probe with explicit local CJK font. |
| `viewport_1600x1200_synthetic.png`, `viewport_670x900_synthetic.png` | Synthetic final candidate screenshots from that geometry probe; these are not live Mac UI screenshots. |
| `backend_review_source_sha256.json`, `frontend_review_source_sha256.json`, `final_source_crosscheck.json` | Reviewed before/after hashes, unchanged response validator and source readers, final render-source consistency, and preserved supplied paths. |
| `review_sources/` | Exact independent review script/fixture copies. Their original workspace paths and execution limits are described there; the separately packaged `tools/` runners provide the portable regression entry points. |

The new synthetic screenshots use the real panel modules in a small fixture host with test fonts. They do not establish the production Vue shell, final bundled asset, or Mac font/layout identity. The three daily status labels are in the first viewport at the tested sizes; full provenance and longer details may require scrolling or expansion.
