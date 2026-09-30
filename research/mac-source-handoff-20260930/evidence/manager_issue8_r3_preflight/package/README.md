# Issue #8 — R3 preflight

This directory is a bounded preflight only. It does **not** modify production code.

Baseline: `cf306997359dfadedb162033554c092d740eca33`.
R2 independent result: `PASS_WITH_P2_FOLLOWUP`.

Remote evidence proves the configured candidate contains the 17:20 owner and that historical 20260928 runs succeeded under an older release. It does **not** prove that current canonical V4 bytes are the source of the configured `20260929-manager-1555-pytdx-r1` package, and the package manifest itself is reported as NOT_ACTIVATED/CANNOT_CONFIRM.

Therefore R3-A is gated on a local read-only source/release binding receipt.

Run on Mac:

```bash
PY="/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python"
"$PY" tools/audit_r3_source_release_binding.py \
  --canonical "/Users/lexi/Desktop/学习/v4_app" \
  --plist "/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist" \
  --output "/tmp/issue8-r3-source-release-binding.json"
```

Also capture, without mutation:
- `git -C /Users/lexi/Desktop/学习/v4_app status --short --branch`
- `git -C /Users/lexi/Desktop/学习/v4_app rev-parse HEAD`
- the configured release manifest bytes/SHA
- the exact LaunchAgent plist bytes/SHA
- if the relevant files are not byte-equal, the build/source receipt that proves which canonical commit/working-tree bytes produced each configured-release path.

### Gate
- If relevant canonical/release files are byte-identical, Writer may modify canonical files only; deployment remains separately unauthorized.
- If they differ, Writer must not patch the release snapshot. First identify the owned canonical source/build transformation for each differing runtime path.
- If no such binding evidence exists, R3-A remains `CANNOT_CONFIRM_SOURCE_RELEASE_BINDING`.

R3-B may be designed independently, but production edits should remain sequential and separately committed.
