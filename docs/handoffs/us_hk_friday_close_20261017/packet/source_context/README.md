# Runtime source context for the Friday US selection repair

These files are minimal read-only excerpts from the loaded runtime releases plus focused existing tests. Each excerpt names its original full path, original full-file SHA-256, and copied source line ranges. They are context for a Chat-led source repair; they are not patch targets.

The loaded owners are separate: US digest `futu-industry-us-20261016-r1`, manager scheduler `zsxq-long-pdf-scheduler-20261016-r3`, and selector API `announcement-continuation-api-20261017-r11c`. The active API catalog and the API's NativeAdapters selector path are distinct implementations and must be tested separately.

`../SOURCE_MANIFEST.json` records source and copied-excerpt SHA-256 values, plus whether the corresponding path in the current V4 worktree is byte-identical. The fixed GitHub base named in the issue was not checked by this packet writer; `WORKTREE_PATH_MISSING_TARGET_BASE_CANNOT_CONFIRM` or content-diff entries require Chat to match the target checkout before editing. The manager 16:30 test excerpt is from the current repository and is not present in the loaded r3 release test tree.

Start with `../CHAT_ISSUE.md` for the four gaps and the repair boundary, then copy `../CHAT_PROMPT.md` to start the implementation task. `../evidence/` contains a sanitized runtime identity excerpt, the catalog-versus-consumer count finding, a synthetic date/identity/handoff contract fixture, a compact research-only observation summary, and `real_relation_projection.json`. The relation projection is a field-preserving derived fixture with 667 stock identities and 1,003 relations; it omits quotes and is explicitly not an owner artifact or complete recovery overlay. It supports source-level consumer count/identity tests only. Full overlay runtime/API/UI/natural acceptance remains `CANNOT_CONFIRM` until the actual canonical overlay is consumed and receipts are read back. These documents do not replace matching the target GitHub checkout or obtaining runtime/API/UI receipts.

No full catalog, original mapping input, full recovery overlay, raw quote capture, or credential-bearing config is included. The derived relation projection is the sole packaged mapping-row fixture.

## Reviewed research-output limits

The frozen research outputs and builder are unchanged. Independent review found two non-blocking limits: Top 20 US `linked_hk_codes_json` aggregates HK codes across all relation statuses and may include `OPEN` links; candidate evidence must be taken from the positive closed-scope rows in the candidate/positive-relation CSVs. The builder's `--verify` argument is parsed but still rebuilds/overwrites outputs, so any replay must use an isolated temporary copy and must not call the capture scripts. A positive oil-linked source move can be cost pressure for airlines and similar users, not an automatic beneficiary conclusion.
