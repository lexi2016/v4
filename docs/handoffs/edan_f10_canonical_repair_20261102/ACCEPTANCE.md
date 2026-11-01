# Edan F10 canonical reference repair

The three-stock F10 publication reached the index with a receipt outside the API's bound A-share product root. The installed API rejected each stock with `A_DAILY_PRODUCT_REFERENCE_OUTSIDE_BOUND_ROOT`. This repair uses the running Main owner and the three saved, SHA-bound captures to materialize new immutable references under the existing product root. It does not fetch new data or weaken the installed API path gate.

Actual Main completion and publication were exercised under an isolated product root using the original captured files and an isolated lock. The installed API host and source path guard were exercised using an adapter that routes the existing 172-row product to the real source and F10 to the isolated root: three stocks returned OBSERVED and the outside-root negative case failed closed. The actual installed path guard also accepted the canonical receipt, checkpoint, and three stock references. Two path/code identity tests passed.

The prepared receipt is not published by this worktree. The actual index/event still refer to the failed publication at the time of preparation. The owner must perform the fresh check and the reviewed CAS publication; real HTTP F10 readback and UI acceptance are separate pending steps. Existing failure evidence is retained. No service reload, market-panel CURRENT, seed, trading gate, or order is involved. Captured F10 is current knowledge, not historical PIT.

Evidence and exact pinned check/publish commands are in `F10_CANONICAL_HANDOFF_R1.json` under the task evidence root. This commit contains source and tests only; it excludes raw F10, product data, plists, and runtime copies.
