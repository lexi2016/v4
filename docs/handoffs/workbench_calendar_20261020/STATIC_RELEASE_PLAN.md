# Manager workbench calendar static release plan

This handoff prepares a local candidate only. No active release file, release manifest, plist, service, or saved research run was changed.

The active API remains `com.lexi.v35.api-only` on `127.0.0.1:8873`, release `announcement-transport-recovery-20261020-r6`. Its plist SHA is `4f341d12c05782895ed7d0d58ea1500d92971b345bef3e8b4db555a1956cc62c`; the pinned and actual `release-manifest.json` SHA is `ab7704b388f1789e4d2a4d18fa91c8538f12282ca83899f5b9bf070e57789d41`. The served `/manager-selection/?date=20261020` entry matched the active release file at SHA `9eefacb48ad4cf2d20dd928f1435a50002b6932c582aa12a9fe53bf5c1169ffc`.

The manifest's `application_inventory` has aggregate SHA `6637da496a116786ef284dcdaea867d7fd7f6a511cc169b5d5a94bccfad0b51a` and enumerates the manager-selection HTML, current JavaScript, current stylesheet, and shared runtime with file hashes. Their actual bytes match the inventory. Editing r6 in place would make its pinned inventory false; do not replace files under that release root or rewrite its manifest.

The first local build, `local_only/candidate-build-r1/`, was built from the isolated worktree and is retained only as a non-releaseable reference. Its reachable build inputs differed from r6 in `AnnouncementCandidates.vue` (`e517c055…` vs active `aa3477bb…`) and `package.json` (`83def8f0…` vs active `c1935335…`). Publishing r1 could regress the active announcement UI.

The corrected r2 build at `local_only/candidate-build-r2/` uses a copy of r6's `apps/web` source/config/package inputs under `local_only/r6-source-r2/apps/web`, overlaid with only this task's three changed source files. It retained r6's `AnnouncementCandidates.vue` bytes and active package metadata. The full build passed. The unchanged root and daily-research HTML and every asset they reference are byte-identical to r6, so a later release can limit the static delta to the manager-selection entry and its new assets. The component test and full web typecheck passed on the isolated worktree. Running the full typecheck in the r6 overlay reported existing errors in unrelated API, App/review, and fixture/test files; it reported none in the three overlaid workbench source files. Vite's production build passed on the r6 overlay.

## Local manager-selection build outputs

| Path | Candidate SHA-256 | Bytes | Later release action |
| --- | --- | ---: | --- |
| `manager-selection/index.html` | `048e0782fa7bd1f7dde36d75f2d1d964b0ebdfe7f71e1da1bd4da9bde563394e` | 588 | Replace this entry only in a new release cloned from r6 |
| `assets/managerSelection-C4fEVFr9.js` | `daa373b3cdce342930256235f96d5d477f5f3c17dcaf4e9f1206975b522a31e9` | 142221 | Add; do not remove the existing hashed bundle |
| `assets/managerSelection-DLQD5xzb.css` | `c1f6a3327b51c1bb3bd934cc5e9cf7824227bd0e70d73253830c903430b3c46a` | 12378 | Add; do not remove the existing hashed stylesheet |
| `assets/runtime-dom.esm-bundler--lJ_qsB2.js` | `9580091f7f63e2c8e3a47666ae054fb1a63bba66d2fca4b258936d37d94794bf` | 65713 | Reuse the identical existing file; do not replace it |

The existing r6 HTML, old manager-selection JS/CSS, other page entries/assets, and other assets remain in place in the proposed clone. Keep any old hashed assets because other entries or cache references may still use them.

## Minimal future release path

After independent review PASS and controller continuation, prepare a new versioned release by cloning the complete active r6 release. Overlay only the manager-selection HTML and two new hashed assets above; reuse the byte-identical shared runtime. Preserve the root and daily-research entries and all existing assets. Generate a fresh release manifest/inventory for the clone, verify every inventory entry and aggregate SHA, then prepare a candidate plist with only the release identity bindings changed and record its exact bytes/SHA. Do not activate it until separately authorized. Before any authorized activation, save the exact current plist bytes and verify their SHA against the recorded value above. A later rollback restores those bytes and reloads only `com.lexi.v35.api-only` after checking the loaded job; keep the previous r6 release intact.

Not run here: independent review, controller IAB popup/render verification, integration into the canonical working tree, new immutable release clone or manifest/plist generation, publication, service reload, post-publication API/UI readback, selection run, commit, push, or natural-period verification.
