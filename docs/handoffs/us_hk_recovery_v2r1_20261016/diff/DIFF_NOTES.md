# Source candidate diff notes

`SOURCE_DIFF.patch` contains the five source/test changes relative to the preserved preimages and the complete new deterministic builder. The large immutable derived projection is fingerprinted rather than expanded into a text patch: `v4/manager_workbench/research_data/us_hk_667_recovery_overlay_20261016.json` is 43,652,024 bytes, SHA-256 `3289f0329f0fe2e447a70386341790cb9821df2e76d13a650143fe07f9e9e91c`, internal integrity SHA-256 `9c33ef21d51516f12e7aeab74192ea0feaa6f1aebfcbba2c42ce97f499b0fedc`.

The projection is deterministically reproduced from the user-provided ZIP by the included builder, which validates the archive identity and selected package members before writing. The original 667-stock catalog and historical 700-relation overlay are retained unchanged. The projection contains no archive code or raw attachments.
