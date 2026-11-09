# R4 controller locator-only activation

R3 actual activation failed when macOS denied bash access to Desktop. Automatic rollback restored all three original plists and original API/Main identities. R3 packet/PASS/failure/readback remain unchanged. R4 runtime apps/static/policy/pins and service launcher paths are under the existing Library candidate root. Business app/static bytes are preserved; only Stage current Main owner locators and release metadata/plists/dependency seals change.

Final R4 packet is `/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-daily-materials-20261109-r4/PACKET.json`. Required independent receipt verdict is PASS or REVIEWED/PASS with its exact packet_sha256. Use the real R4 review receipt, not R3's receipt.

```sh
PYTHONPATH=/Users/lexi/.codex/worktrees/v4-release-dependency-20261109 '/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python' -B -m ops.activate_daily_materials_release --packet '/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-daily-materials-20261109-r4/PACKET.json' --review '<absolute R4 independent review receipt>'
```

Same command plus --rollback restores the original reviewed CAS tuple. Activation/rollback receipts and backups are now written inside the Library packet root. Do not publish while activation holds A_LONG; wait for its return and exact receipt, then controller serially reprepare/publish existing owner plans.

Writer checked bash -n only; actual launchd access and loaded service/API/UI are controller verification. No TCC, permissions, services, live plist, production data or orders were changed by Writer.
