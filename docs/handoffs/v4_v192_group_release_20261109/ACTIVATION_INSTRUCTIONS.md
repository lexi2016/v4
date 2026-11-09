# Controller activation

Use the real independent V192 joint review receipt with verdict PASS/REVIEWED/PASS and this packet's exact packet_sha256. Do not reuse the previous R4 review receipt. Wait for healthy Main scheduled children to finish; never stop them to force activation.

```sh
PYTHONPATH=/Users/lexi/.codex/worktrees/v4-v192-group-release-20261109 '/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python' -B -m ops.activate_daily_materials_release --packet '/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-v192-group-20261109-r1/PACKET.json' --review '<absolute joint review receipt>'
```

The same command with --rollback restores the successful R4 service/policy tuple. Company/score publication and the original371 data are not touched or rolled back. Inspect the actual activation/rollback receipt; real API19/371/31 and UI group selection remain controller acceptance.
