# Source-only patch coverage and reconstruction limits

`SOURCE_ONLY.patch` contains the exact, hash-verified `ops/run_us_market_slot.py` diff. Its frozen preimage SHA matches `writer/preimage.sha256` and the untouched active-release file.

A complete canonical source-only patch cannot be confirmed from the available frozen preimage: the remaining source preimages are recorded only by SHA-256, and their bytes are absent from Git `HEAD`/the allowed evidence tree. In particular, the changed preimages for `ops/_us_market_digest_parts/cli_primitives.py`, `ops/_us_market_digest_parts/phase_publication.py`, and `infrastructure/scheduling/_executor_registry_parts/us_digest.py` are not recoverable from the frozen preimage record. New tests are also untracked in this worktree. `candidate-runtime.delta.patch` is the complete byte diff from the frozen actual US release tree to the isolated candidate, not a substitute claim for the unavailable source-only base.
