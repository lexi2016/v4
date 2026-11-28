# ACT-077A Route C case adapters

`p4.bind_p4(case)` copies a digest-verified case and binds its five pending P4 rows to fixed 5-, 10-, and 20-session windows ending at D. Each window includes the signed chart bar identities and actual volume. The bound segment describes A-owned evidence windows. The explicit structural segment state stays `UNBOUND`. Undefined ratios retain a null value and `UNCOMPUTABLE` status.

`build_cases.write_bound_case(case_dir, group, trusted_case_sha256=...)` verifies a frozen A case before writing the derivative to a separate location. Chart, output schema, rules and immutable B2 are reused unchanged. `build_cases.case_bundle(case_id, case, market, lock, group)` accepts one strict, verified prefix supplied by A, using the ACT-076A market and lock interface. The inputs require `case.code`, `case.d`, `case.raw_prefix_sha256`, and `lock.raw_archive_sha256`, `lock.price_basis`, `lock.volume_basis`.

`l1.l1_observations(case, indicator_row)` accepts the exact D row from the frozen engine's `compute_indicators_d_only` on A's verified prefix. It produces a separate `OBSERVE_ANOMALY` record. Chart identity and the frozen volume ratio are checked, and native indicator units are preserved.

`shortlist.pre_screen` derives documented mechanical proxies from a same-D ACT-065A record. `choose_slot` preserves A's order and excludes previously selected stocks. The stress proxy uses the native high or extreme position tier and native wick-supply warning. The caller checks exposure and window isolation and keeps the pre-screen audit separate from B input. Structural findings require a separately supplied scoped verdict and frozen technical acceptance.

Run `python -B -m research.act077a.route_c_cli` with the frozen V1.1 validator's arguments for K01–K05 and B01–B16, with A's trusted receipt held separately. `python -B -m research.act077a.selftest` runs synthetic checks without reading market sources or invoking a model.
