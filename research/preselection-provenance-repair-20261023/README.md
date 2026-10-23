# V192 and hourly provenance repair

Missing V192 input and a deterministic18:00 source error caused mixed-slot failures and repeated work on successful sources. The repair admits independently verified partial pools, preserves strict cache/source verification, isolates a rejected research cache, and waits for relevant input changes before retrying deterministic failures. Network deadlines remain independent; SAFETY and unknown terminal failures still block automatic retry.

The collector cutoff comparison is corrected. The actual18:00 source remains rejected because its18:01:32 publication exceeds18:00:59.999999. The configured V192 selector panel still lacks the required2026-10-23 input for target2026-10-26. No fabricated source, altered PIT label or validation relaxation is included.

Independent source/canonical checks and guarded control/continuation checks PASS. Exact reviewed7canonical sources and1test are integrated. FinalR3independent focused checks:15passed per variant, with unchanged earlier acceptance reused. Control28checks and exact-release continuation9checks passed. The focused test requires the local frozen private evidence capsule; raw source/market fixtures and full logs are excluded.

Existing API/UI readback shows A214,HK100,complete A input and a second page containing the final14Arows. Missing subpools retain partial-source diagnostics. These current-input readbacks predate producer activation.

Deployment is waiting for healthy PDF/research work to finish under one event-driven owner. No service switch is claimed by this commit. The reviewed candidate is preselection-provenance-20261023-producer-r3; actual loaded identity and postdeployment behavior require the owner receipt. No whole successful slot, model, collector or manual18:00 recovery is rerun. See verification.json for dated states, exact source before/after hashes and receipt hashes.

The runtime-source directory contains the eight exact compatible producer source files. canonical-integration.patch contains only the seven necessary mapped changes for the newer workspace structure; its facades and newer hourly PIT validator are preserved. control contains the reviewed conditional activation code and focused tests. Nothing is merged or publicly deployed by this branch.
