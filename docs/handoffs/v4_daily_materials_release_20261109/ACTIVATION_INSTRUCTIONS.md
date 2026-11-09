# Controller activation and rollback

Final packet: PACKET_FINAL_R3.json. Required review receipt: verdict PASS or REVIEWED/PASS and packet_sha256 exactly matching this immutable packet. Use the real independent review receipt, never manufacture a PASS field.

From the Writer worktree, with its source bytes unchanged:

```sh
PYTHONPATH=/Users/lexi/.codex/worktrees/v4-release-dependency-20261109 '/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python' -B -m ops.activate_daily_materials_release --packet '/Users/lexi/Desktop/学习/agents调试/v4_daily_materials_release_repair_20261109/release/PACKET_FINAL_R3.json' --review '<absolute independent review receipt>'
```

The same command with `--rollback` restores the exact preceding tuple. A failed activation automatically attempts complete CAS rollback; inspect ACTIVATION_RECEIPT.json rather than assume recovery. Do not invoke concurrent cutovers, publishers, or retry after a CANNOT_CONFIRM recovery without diagnosing its recorded condition.

Company and score publication is separate and serial through existing owner paths, after activation has exited and A_LONG is released. Reprepare publication plans against the then-current index/event CAS; do not replay data/model jobs. Root controller performs actual API/UI/new-record and natural verification.
