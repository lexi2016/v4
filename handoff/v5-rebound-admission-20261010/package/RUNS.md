# Run and receipt summary

Commands below are separated by evidence class. `exit=0` means the command completed; it does not mean the business status was admitted.

## Existing actual runs, summarized

1. **Date-storage regression (prior local fix):**
   `/Users/lexi/Documents/Codex/2026-10-08/task/V5-test-1167ed3/venv/bin/python -B -m unittest test_rebound_date_compat test_rebound_owner_identity test_rebound_panel_repair test_rebound_raw_repair test_rebound_admission test_rebound_observation -v`
   `exit=0`; 104 tests total, 103 pass, 0 fail/error, 1 skip. The skip is the private real-assets/approved-repair-only case because the required native capture/approval binding was not supplied. This is not a formal admission pass.

2. **Actual recorded current-target observation:** `rebound_observation.py --request observation-request-current-20261010.json --output-root observations/current-20261010`, run `158fc60a8926409d8e6e47963f6f2841`; artifact SHA-256 `bdbbb83118b78296e94f27945632453d3f1423d6c03dc5d41c248118f6801cd1`. `exit=0`, status `CANNOT_CONFIRM`, including `ValueError:OBSERVATION_PANEL_BINDING`; no selection published.

3. **Historical synthetic arithmetic observation:** `rebound_observation.py --request observation-request-historical-synthetic-20261009.json --output-root observations/historical-synthetic-20261009`, run `a27af4fc3f6e435b8bd3f5ebb54659e4`; artifact SHA-256 `637c0d3a6ce461c952523da8d7dbb551deca299ccc2824a182da272e163164ec`. `exit=0`, status `SYNTHETIC_TEST`; two-gate counts strict 0 / near 1 / excluded 0 / unresolved 694. This is arithmetic only, with no admitted selection or manager consumption.

4. **Read-only digest verification:** original capture and publication helpers were used to remove each self-digest field and recompute the producer-defined logical digest. `exit=0`: capture `34fcb9611e233a8eb612e47a3c419c0659f332beb97a7b718f807abec21a7e59`; publication `153ab53d3d2f09ac1dfd4931a8144ecacb220caf2e9009be976d3ab513e00c4b`; cross references agree. The raw file-byte SHA values differ because they are a separate hash scheme. No observer/admission rerun was performed for this check.

## Repair receipt summary (lineage only)

- Child panel: `c3dc826061ae0576e8327b07fba328cc0c56aa5e34511d6737b8ec047b186f22`
- Child manifest: `d910c52007a9298e3ff5e45cb55eb70d92a9db9c7568daee9d3f319eb07d31a0`
- Repair receipt: `b39cc5d638ca2cbac7330c429105a69bb0dce986d73e19d10db85ad898df8b55`
- Receipt records byte repair only; `formal_eligibility_verified=false`. Its source binding keeps scale 1 and conversion false.
- The raw capture and repaired panel are intentionally not included.

## Patch package verification

The new fictional cell audit in `synthetic/` is run separately from all business runs. It has no project imports or real data. See its captured result in `evidence/synthetic-run.json` and rerun command in `evidence/command-log.json`.
