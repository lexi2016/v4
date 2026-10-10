# V5 rebound admission handoff

**Status: `READY_FOR_REVIEW`, admission remains `CANNOT_CONFIRM`.** This folder is a small review package for the private `lexi2016/v4` development branch. The parent plans to create `v5/rebound-admission-handoff-20261010` from verified head `ebe5944ecfbec2f6a161793d7c11946dea063e57`, adding only this handoff directory. That branch and its final commit are not yet created; use the publication receipt for the eventual commit SHA.

The original two-gate rule is unchanged. The historical 694-member batch remains `694_BATCH_HOLD`. No formal per-code selection or same-run manager consumption exists.

This package separates a small code compatibility fix from missing business evidence. The date-storage fix makes added `trade_date` values match the existing panel's integer or string storage type while preserving existing rows exactly. It does not prove a quote's price basis, currency, quantity unit, capture finality, membership, or owner approval. The exact patch and source snapshot are in `source/`.

The patch was produced against the local sequence `ebe5944...` + identity-delivery commit `2bfb4c8c5f770122077e3baf914cf5b05b8a2450` + the local date-storage patch. It has **no new commit**. Do not claim the planned handoff branch already contains that predecessor or the date fix. `source/CHANGE_MANIFEST.json` gives exact before/after file hashes and the patch hash. The patch's source context is the post-identity-fix file; compare/rebase it against the actual publication branch before applying.

## Read next

1. [MINIMAL_ISSUE.md](MINIMAL_ISSUE.md) — decision, actual results, and exact missing proofs.
2. [SOURCE_ROUTES.md](SOURCE_ROUTES.md) — existing TDX, PyTDX, and Futu source contracts and safe prerequisites.
3. [RUNS.md](RUNS.md) — command/result classifications and non-secret receipt summary.
4. [synthetic/README.md](synthetic/README.md) — fictional reproduction and its limits.
5. [PACKAGE_MANIFEST.json](PACKAGE_MANIFEST.json) — content hashes and package scope.

No raw market panel, raw capture, full membership list, credentials, SDK logs, or original private tree is included. The package is not evidence of formal admission and contains no self-signed authority or approval.
