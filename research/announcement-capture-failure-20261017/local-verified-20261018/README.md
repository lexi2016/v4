# Issue 44 local storage fix — 2026-10-18

The two product-store read sites now use a local 256 MiB bound. The shared SafeRoot default remains 64 MiB. The actual canonical source and focused test are included under active-source; actual.diff records the minimal storage change.

Independent Luna Max Reviewer: REVIEWED / BEHAVIOR_VERIFIED / PASS, 7 focused runtime tests passed. Local API release issue44-capture-size-api-20261018-r1 is deployed, with independently verified live plist, PID cwd, manifest and source binding. See verification.json for the exact before/after SHA, test command and runtime identity.

This branch is a bounded handoff/evidence branch based on the existing Issue 44 repair handoff. The rest of its repository tree is not a complete copy of the current live runtime. Embedded immutable candidate activation metadata is not the runtime activation receipt.

No recapture or model inference was run in this batch. The original failed job has no input/result artifacts, and the existing route cannot bind its saved cache without recapture. Therefore new model/API-result/UI acceptance remains NOT_RUN / CANNOT_CONFIRM. Existing UI results do not count as new acceptance. The user has authorized a separate next batch for a cache-only recovery entry.

No raw announcement cache, business response, credentials, plist, or model output is uploaded. Research and trading gates are unchanged.
