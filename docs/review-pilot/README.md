# V4 review pilot

These rules add a bounded implementation-review workflow to V4. They do not change V4 research, market-data lineage, pool, production, or trading behavior. The root `AGENTS.md` in this worktree is a captured copy of the canonical V4 project rules, separate from the user-level global operating contract. This page supplies the V4-specific review and custody rules.

## New implementation tasks

- Start each new task in an isolated branch or worktree. Record its base commit, exact allowed and forbidden paths, relevant undeployed dependencies, input/config/source identities, and a falsifiable pass signal before editing.
- Assign one Writer to each overlapping file set at a time. Serialize overlapping ownership. The controller owns integration at the root.
- Use a Luna Max Writer (`gpt-6-luna`, `max`) and one independent, different-identity, read-only Luna Max Reviewer by default. Review the actual diff against the frozen scope.
- A Reviewer must rerun the required focused acceptance checks before marking `TESTED`; Writer-run checks are supporting evidence. Only an independent Reviewer `PASS` accepts the scoped work. A Writer's handoff is not final acceptance.
- Reuse a valid independent PASS only when code, input, configuration, and frozen scope identities all match and no new evidence, failure, or scope change exists. Otherwise review only the trigger and its direct effects. Do not launch a blanket re-review of historical files. Optional style/refactor suggestions and unrelated pre-existing findings do not block; a concrete defect affecting the target, safety, or scope does.
- Three rounds trigger controller reconsideration; the round count never grants a PASS.

## Existing historical materials and ownership

All historical changed files remain preserved at their current locations and unaccepted until the user decides whether governance will hold the unresolved materials or each original owner should be recovered. Do not infer an author, current owner, integration, or acceptance from a filename, commit, duplicate hash, or receipt reference. Only exact task-linked peer paths may later receive an owner/disposition, and only with direct evidence. Until then, record ownership and disposition as `UNKNOWN` / `CANNOT_CONFIRM` and route the grouped decision to the controller. No blanket review or relocation of the historical set is authorized by this page.

## Evidence and synchronization

This page includes only the minimal policy patches, source hashes, portable preparation/probe scripts, and compact results summary listed in its adjacent manifest. The separate private local pilot bundle contains path-level inventory, provenance references, blinded historical fixtures, an oracle, and raw evaluation evidence. Keep those full inventories, payloads, answers, source data, and logs local; do not upload them with the V4 project docs. Runtime role selection and sandbox enforcement must be verified by a native-process canary; the existence or successful parsing of TOMLs alone does not establish them.

The candidate global role/policy files are evaluation inputs, not active configuration. Do not install them from this page. Parent-controlled runtime validation, independent review, and repository synchronization are separate acceptance stages.

## Local reproduction

`source_hash_manifest.json` records byte identities without including the source or full configuration files. `results.json` is a compact report of the parent-run canaries and their limits; it is not an independent acceptance receipt. The scripts take explicit paths and write only under a caller-selected local output or scratch directory. Run either script with `--help` for its required arguments. Fixture preparation requires a local repository clone that already contains the fixed commit and explicit baseline source/test paths; it does not fetch or create blinded payloads or an oracle. The offline probe accepts the selected source, test module, repository support root, variant, and scratch path; it uses test-defined synthetic data and callbacks only.
