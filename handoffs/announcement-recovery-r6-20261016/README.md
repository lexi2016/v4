# Announcement recovery R6

The completed R5 run left 137 eligible legacy tasks unrun because their saved metadata did not match the current verified Stock Connect inputs. Seventeen long-document parts failed the existing fixed-field validator; two previously successful documents were unnecessarily processed again.

This candidate associates legacy pending records with immutable, current eligible versions in the same queue and reuses successful results. A source-bound correction of one failed part gates the remaining corrections in the same workbench run. Failed corrections remain explicit; original payloads, model outputs, semantic validation, and financial safety gates are preserved.

`source-delta.patch` contains only the three changed source/test files. It applies after the prior `announcement-recovery-1457-20261016` handoff; the actual active base is `us-industry-compact-20261016-r2`, whose three baseline files match R5. All unrelated active-release files are preserved.

Status: independently reviewed PASS, 45 targeted tests rerun against the integrated candidate, and actual-input offline proof independently reproduced. One non-blocking P2 concerns missing dedicated negative canary regression cases. The proof uses a synthetic validator-only canary and does not establish actual model behavior.

The reviewed candidate was deployed and its API/runtime identity verified. One existing workbench button click started job `85add37723bf4c5ea1445dcb61202899` at 20:15 on 2026-10-16. Actual model canary, automatic phase-B execution, and the completed batch/API/UI result remain unverified. No parent CLI or manual queue advancement was used. Natural-slot acceptance is not claimed. The user prefers no continuous progress polling; final completion remains pending.
