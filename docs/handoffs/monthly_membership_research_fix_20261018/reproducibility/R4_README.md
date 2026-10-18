# R4 source paragraph correction

Canonical source and runtime overlay differ in pre-existing formatting. The runtime source delta is exactly the two files under runtime_overlay_r4/app, based on immutable API R3. Restore that overlay into the handoff local_only directory and use the recorded R4 baseline/build scripts. Build inputs and node dependencies remain local; no bundle, credentials, runtime configuration contents or raw market data are uploaded.

The source paragraph now distinguishes 36 direct relationship rows / 19 mapped HK stocks from the full candidate pool of 701. No count engine, saved run, direction list or selection policy changes. Independent review and deployment have separate receipts. The scheduler helper includes the independently reviewed idle NO_RETRYABLE_TASKS guard in addition to RETRY_BACKOFF; scheduler already deployed at R2 and is not rebuilt for R4.
