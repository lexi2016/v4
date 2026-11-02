# Supplement inline activation repair · 2026-11-02

The staged plist inherited the Edan WorkingDirectory while its release environment pointed at the supplement candidate. Python module resolution therefore loaded Edan. The previous isolated smoke hardcoded the new cwd and missed this mismatch. The module-origin proof and unchanged manifest SHA are in writer-receipt.json.

The package now sets WorkingDirectory with the four identity environment fields. Its smoke uses the staged ProgramArguments and WorkingDirectory, changing only the spare port. The candidate plist was repaired in place with its preparation SHA updated; no app or manifest bytes changed.

The activation entry follows the existing Edan API release lock and bootout → absent job plus clear socket → guarded atomic install → bootstrap → retry verified release identity/manifest and JS marker. It checks live plist/process immediately before bootout and plist SHA immediately before replace. Recovery validates the actual old plist identity and the exact owned process before touching a service; foreign plist/process drift stops recovery. Attempts receive unique records and inverse filenames, preserving the earlier failure.

Offline regression coverage: old identity followed by new identity, absent job with live socket, socket timeout with no bootstrap, failed activation restoring actual old identity, guard before/after unload, atomic-install drift, unknown recovery process, launch-config mismatch, shared-lock ownership and actual lock contention, and package field preservation. Thirteen individual tests passed; one initial lock-fixture error was fixed by resolving macOS /var temp symlinks, then only that test was rerun.

Run the offline regressions with the existing runtime Python, using `-B -m unittest discover -s tests -v` from this directory. Tests use temporary plists and mock launchctl; the real lock test uses only its temporary directory.

Controller execution entry, only after independent review:

```sh
'/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python' -B '/Users/lexi/Desktop/学习/agents调试/v4_stage_supplement_inline_20261102/activate_release.py' activate --candidate-root '/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-stage-supplement-inline-20261102-89ef3a68'
```

No service action, live plist write, commit, or push was performed by Writer. The candidate configuration and offline checks passed; deployment, HTTP/UI cutover verification, natural-run acceptance and Reviewer verdict remain CANNOT_CONFIRM/NOT_RUN. On observed concurrent drift, stop; do not overwrite the other owner. Same-input retries without new evidence are prohibited.
