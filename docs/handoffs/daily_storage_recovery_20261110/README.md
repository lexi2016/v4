# D20261110 raw-sync storage recovery

Candidate fix only; independent review and real owner recovery remain pending.
Baseline: `26824b180acf8f5b0f13ffca1918a2aaa04d6f78`.

`guarded_raw_run` previously charged both JSON and CSV as twice a generic JSON
encoding. The actual JSON helper writes pretty UTF8 directly; the CSV helper
writes UTF8 with one BOM using `csv.DictWriter`. Exact byte counting now follows
those same serializers. Atomic byte writes still reserve one incoming payload
alongside observed allocations. Source writers, numerical data, quotas, locks,
claim identity, raw history and quarantine are unchanged.

The new actual-source regressions fail twice with `PREDICTED_PEAK_EXCEEDED` on
the baseline. The fixed code passes all 59 targeted tests, including real task
and category exhaustion, unchanged output bytes and original-directory resume.
Interpreter: `/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python`.

```sh
"$PANEL_PYTHON" -m pytest -q tests/test_daily_storage_recovery.py tests/test_research_storage_governance.py tests/test_research_storage_governance_context.py --basetemp /absolute/task-owned/path
```

Persisted D10 summary (16:23) is 95,298,417 bytes, exactly reproduced by the new
counter; the old proxy is 156,490,186 bytes. The 16:45 CSV is from a later run:
its 21,229,694 bytes must not be attributed to that older summary. The exact
failing in-memory payload is **CANNOT_CONFIRM**, not preserved. Fixing this
proven over-admission bug is not yet proof that the real D10 owner completes.

Process receipts, commands, file SHA256 and the existing-owner CLI are in:
`/Users/lexi/Desktop/学习/agents调试/v4_daily_storage_recovery_20261110/HANDOFF.json`
and `RECOVERY_INVOCATION.json`. `RED.txt`, `GREEN.txt`, `RELEASE_TESTS.txt` and
`SERIALIZER_EVIDENCE.json` retain the bounded proof.

A new storage code/path changes the claim key; do not spoof obsolete code SHA
or edit the registry. The original date-bound progress directory is reused as
measured baseline and the old blocked reservation remains. Raw snapshots and
all prior evidence are retained. First-run forecast/direct snapshot billing is
outside this minimal resume fix and is not newly certified.

Prepared release is on branch `codex/daily-storage-release-20261110`; no deploy,
producer run, commit or push was performed by Writer. After independent PASS,
the controller uses the existing owner with `--date 20261110 --lane A`, actual
time and original A_LONG lock. Label it MANUAL_RECOVERY, not natural/PIT. Preserve
all original bindings and 5000 floor; stop on a genuine new admission failure.
