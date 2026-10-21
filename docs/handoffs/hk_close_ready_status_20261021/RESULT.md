# HK close READY compatibility · 2026-10-21

The exact-date verified Top100 existed with status `READY`. The close reader accepted only `STRICT_0_2_READY`, discarded all 100 rows, and published `MODEL_0_2_SOURCE_MISSING`. The API and page reflected that stored artifact.

The candidate admits canonical `READY` only after the existing store verifies the pool/manifest/receipt trio. It also requires the canonical schema, HK market, known producer/source role, explicit target date and stage eligibility, and bound source hashes. Existing exact-date, unique-100, market and safety checks and legacy strict behavior remain in place. No partial status is newly admitted.

Writer validation: baseline reproduced `0 != 100`; 55 targeted tests passed. Replay of existing 20261021 inputs into an isolated store yielded 100 model rows, 11 close-Top20 hits, 55% coverage and 11% precision. The close universe remained 698, Top20 remained 20, and stage rows remained 70. 09:30 after-fact/PIT reasons and 13:00/14:45 partial evidence remain unresolved. Source files and the live close artifact stayed byte-identical.

Source baseline: `f592406e3fb32d425a2cbf5506b28b262938f610`. This branch does not contain the complete live dependency tree; the builder was already untracked in canonical, so its existing file is added with a minimal overlay shown in `source_overlay.diff`. Tests used pinned active scheduler dependencies with the candidate builder explicitly imported. This is not a standalone branch claim.

Exact local commands and raw readback are retained in the bounded evidence directory, not uploaded as runtime data. Independent review, integration, publication, deployment, API/UI after repair and natural verification are not performed by this Writer. Any authorized current-day regeneration must use the archived original and explicit manual-recovery context, reuse existing close and stage inputs, and call only `ops.build_close_review`; do not invoke its collector or scheduler wrapper.
