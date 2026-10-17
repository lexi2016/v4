## Source excerpt: `contracts/runtime_workloads.json`

Original source path: `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/futu-industry-us-20261016-r1/app/contracts/runtime_workloads.json`

Original full-file SHA-256: `bd9ff31db78fa3eb491799fa389eac2d9871602a191cc4885fd75afb9489e29b`

Release/worktree group: `us_digest`

Enabled US digest workload command and date roles.

### Full-source lines 1732-1765

```jsonc

      "aliases": [
        "us_market_digest_capture"
      ],
      "command": [
        "python",
        "-m",
        "ops.us_market_digest",
        "--data-root",
        "{data_root}",
        "--trade-date",
        "{business_date}",
        "--capture-phase",
        "{capture_phase}"
      ],
      "enabled": true,
      "market_scope": "CROSS_MARKET",
      "owner_id": "v4_dispatcher.us_market_digest",
      "run_policy": "NATURAL_DAY",
      "safety": {
        "buy_gate_updated": false,
        "orders_sent": false,
        "production_allowed": false
      },
      "scheduled_date_role": "SCHEDULED_DATE",
      "session_requirement": "DAY_ELIGIBILITY_ONLY",
      "signal_date_role": "BUSINESS_DATE",
      "slots": [
        "0415",
        "0515",
        "2100",
        "2200"
      ],
      "target_date_role": "BUSINESS_DATE",
      "workload_id": "us_market_digest"

```
