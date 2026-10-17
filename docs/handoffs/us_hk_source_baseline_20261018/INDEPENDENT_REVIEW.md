# Independent review — Issue 45 source baseline

**REVIEWED: PASS. SOURCE_BASELINE_READY: PASS. BEHAVIOR_VERIFIED: PASS, limited to isolated imports, the exported API request/method dependency, and the focused baseline test selection.** This review is by a separate agent identity and covers only the frozen source-baseline scope. It does not verify any of the four Issue 45 business repairs.

The final `SOURCE_EXPORT_MANIFEST.json` SHA-256 is `964bb055b6975fdd256c81afa6a2948d955f94aa1f1afabd1cd6aa8d8ebbd8ae`. I independently matched all 436 staged file paths, byte sizes, and SHA-256 values to the manifest (8,361,532 bytes total); its sole symlink resolves inside `staging/`. The required modules imported from a fresh `/tmp/v4-issue45-baseline-review-final2-c67z5o` copy with `PYTHONPATH` and `PYTHONHOME` unset. Each checked `__file__` stayed inside that copy and the canonical checkout was absent from `sys.path`. The refreshed API dependency also passed a focused structural check: `api.py`'s cached-recovery request model imports, and `AnnouncementUpdate.start_cached_product_recovery` exists in the same export.

The documented focused test selection returned **225 passed, 3 failed, 1 deselected** from that fresh copy. The deselected 11:30 intraday dispatcher case is explicitly outside this Issue 45 closure. The three preserved baseline failures are:

- `test_source_binding_carries_configured_quote_scope_and_proposal_sources`: `market_snapshot READY universe quote coverage incomplete`.
- `test_v3_48_symbol_scope_and_proposed_relations_remain_observation_only`: actual `US_SESSION_RELATION_OR_CONNECT_UNVERIFIED` differs from expected `US_RELATION_PROPOSED_PIT_UNCONFIRMED`.
- `test_unknown_universe_version_is_rejected_as_unassessed`: expected `US_UNIVERSE_CONTRACT_VERSION_UNSUPPORTED` is absent.

These known failures are documented in the README and are allowed by the frozen baseline contract; they were not fixed or relabeled as passing. The dependency dry-run resolved all nine pinned requirements without changes. An independent high-confidence scan found no AWS, GitHub, Slack, OpenAI-style, or private-key patterns. The 1,003-relation fixture is labeled derived and quote-free, and the full recovery overlay, raw captures, credentials, runtime releases, logs, and backups are excluded. The small canonical relation registry remains clearly `PROPOSED`, `PIT_UNCONFIRMED`, `OBSERVATION_ONLY`, and `strict_selection_eligible=false`.

**P0/P1 findings: none.** The three known test failures are P2 baseline discrepancies explicitly permitted by this scope. `CANNOT_CONFIRM`: whether the frozen `announcement_update.py` source bytes can still be compared to the original canonical file at freeze time; its manifest and staged SHA match, but canonical drift after the recorded freeze is out of scope. GitHub branch readback/sync is also `CANNOT_CONFIRM` here. The README/prompt correctly keep Issue 45 dispatch acceptance, date/session handoff, full owner-overlay consumer readback, API/page reload, notification, and natural-slot behavior `CANNOT_CONFIRM`.

No production source, tests, services, configuration, or runtime files were changed by this review. The only files written are this receipt and its JSON companion.
