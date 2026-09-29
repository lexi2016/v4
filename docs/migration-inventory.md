# V3.5 replacement inventory

`contracts/migration/v35_replacement_inventory.json` is the machine-verifiable
replacement ledger frozen from Atlas 038. It records planning obligations only:
every source, entrypoint, runtime-task record, and feature is `PENDING` until
its replacement tests provide machine evidence.

Generate the contract only from an explicitly supplied read-only Atlas path:

```powershell
python -m ops.migration.inventory --atlas <atlas-directory> --output contracts/migration/v35_replacement_inventory.json
```

The checked-in contract contains only relative source and evidence paths. The
generator is an offline planning tool; V3.5 runtime does not read Atlas data,
register tasks, retire tasks, or imply that any replacement is complete.

`validate_inventory` validates the reusable schema, lifecycle states, evidence,
and declared V3.5 owners. `validate_initial_snapshot` additionally locks this
checked-in Atlas 038 contract to its frozen identity, counts, and all
`REWRITE/PENDING` records with empty replacement evidence.
