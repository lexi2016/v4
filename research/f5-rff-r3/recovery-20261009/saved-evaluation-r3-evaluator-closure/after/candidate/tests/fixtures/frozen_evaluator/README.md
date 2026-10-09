# Historical evaluator source fixture

The seven files under `spike5/` and `config/` preserve complete bytes verified
against `MAC_FIXED_SOURCE_MANIFEST.json` (19,131 bytes; SHA-256
`64fd0f7a5e3d646f7b5b184d44ca10576aab9db73772b3abb2cfceab36862a9b`).
The independent historical package identity receipt authenticates that
manifest. `HISTORICAL_CLOSURE_PROVENANCE.json` is a derived public export of
the source and recovery record: it removes internal storage identifiers and
locator metadata, and replaces workspace paths with package-relative references.
The complete original provenance remains in private input evidence. The export
preserves all seven identities, recovery details and limitations; it does not
modify the original manifest, source files, configuration, or tests. The delivered
independent receipt is at
`evidence/historical/MAC_FIXED_PACKAGE_IDENTITY_RECEIPT.read_text.json`, relative
to the delivery root (not the installed code or this fixture directory).

This is the historical Mac-fixed package configuration: `config/contract.json`
has SHA-256 `17ecffd1304e152da4f611b3ffc4b5e92633fac20d528b93ce9b6f8714b1c4bb`.
It includes the historical Mac metadata amendment. It is not the configuration
identity of the original submitted ZIP.

The 22-byte `spike5/__init__.py` was recovered as a candidate version declaration
whose complete byte count and SHA-256 match the historical manifest. This is
hash-authenticated byte recovery, not an observed read of the actual Mac file
or retrieval of that member from the original archive. The Mac file must pass
the same identity check during preparation and execution.

Tests copy this small source/config closure into temporary directories. The
only positive-loader substitution changes the two absolute path attributes on
an already SHA-verified score-aware wrapper instance. No source SHA, historical
pin, settings implementation, metric function, label or threshold is replaced.
Negative cases alter only temporary copies or explicitly inject invalid cached
module metadata. Test execution reads no original data, model or registry file.
