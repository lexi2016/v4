# V4 storage write-once candidate source

Candidate application changes are pinned to `eb6abd5877958704e4f574263f4096be47d1ee4f`. The Git branch supplies the changed files. Build each isolated role from its matching, verified installed application inventory to retain its complete source and dependency closure. The branch base `c9baa6d5b02d895ee5ab01650279e76664a18efd` lacks `v4/manager_workbench/engines/strict_us_selection.py` and the current selection contracts. Build Main and API by overlaying the exact files below onto their respective inventories.

| Baseline release | Manifest SHA-256 |
| --- | --- |
| Main `v4-daily-history-delta-20261113-r1/main` | `d3ec529152c9a6b6a0c23acbc93704ff5b80a7fad1449b3618cc7a4cb5d9c6b7` |
| API `v4-us-card-only-20261114-r1-api` | `47f9e83ea0bdfe9d8fee4c445ab4441e22afcdf384a94bc81553db928ee3bbdd` |

| Role and file | Baseline SHA-256 | Candidate SHA-256 |
| --- | --- | --- |
| Main and API `v4/manager_workbench/service.py` | `832cf305b77b7d17ee835fa0fd70cad695615ac6dbebeb859453fe4c99ed4536` | `a3bbd7d96096ef5e20266f5b51485d72f06fd151c88a0cdd3695a87753c9636f` |
| Main `v4/manager_workbench/store.py` | `3717d759a59874a1135f284e1570bbabee8df87654faaa4cae95f173fb3e7df1` | `0206e67a5c309fe038f1300ed9705622a7e16cb4f51f6ea16d4aa4870c9fc9ab` |
| API `v4/manager_workbench/store.py` | `758ba604de2c03547dc77f993ef24eb87fa0ae45a9b89526153ccd3006706e60` | `b71cd3591f2073c1150918f78e9c6b921e36c81772f1843b53914500d02b4331` |
| Main `ops/research_daily_product_parallel.py` | `2bc8eabfb11c5b1e4504ab5200441334b34539c9d8730a3d168b75713f0e0b0b` | `970497c0777f572b8e5fa237955a480ce293b4e505f81aaba48e64ebce6ea306` |

The baseline service blob is `e673993025b2eaf239ef0ca1343cae6e727d5833` in `53a6f18e74f2406ddf754a4e0635bc54e8fdc053` and `19d0576a635dc76b9beaf218dde2d7869bc50144`. The baseline Main store is `d59aec332100bc7e375e04efe3f3022b8816e1bf` in `8f3ca0ecad69e032583d15337cbd4e6411e1b23a`. The baseline API store is `682e6e6264f48a48035ddb72786bb3f32c732f94` in `97574ff2071b95b80ec2bc1b738cc84c58129bcb` of `lexi2016/v4`. Recover the baseline API file from that commit or a verified installed inventory, then apply [api-store.patch](api-store.patch) with `patch -F 0 -o <new-file> <baseline-file> < api-store.patch`. Verify both hashes before overlaying the result. For the other files use `git show eb6abd5877958704e4f574263f4096be47d1ee4f:<file>`. Recalculate each candidate inventory and require its changed file set to match the table for that role.

New `LOAD_INPUTS` files use the snapshot reference format. A compact snapshot keeps the SHA-256 of the original canonical body after hydration. Its physical JSON has a distinct SHA-256. Attempt journals and compact snapshots share hash-verified `overlay_blobs` for the two named US mapping fields. The first encounter with a novel overlay SHA writes its immutable blob once, which can also happen when the first request after adopting this format reuses a legacy plan. Subsequent requests with that overlay reuse the same blob. Old inline snapshots and checkpoints remain readable with the candidate.

For rollback, preserve a verified, compatible reader and its referenced blobs, or restore the exact pre-cutover workbench state in a coordinated rollback. The unmodified previous service expects inline `LOAD_INPUTS` and does not hydrate compact attempt contexts or snapshots. A binary-only rollback over candidate-written state cannot safely resume those attempts.

For the archived D12 independent-close caller, [independent-close.patch](independent-close.patch) applies with zero fuzz to `writer/run_fresh_engine.py` at SHA-256 `1122df51b2adb272faefb05394447298a7f091c46f1245cbca48bd6956b49ab5`. Apply it to a separate file, check SHA-256 `53438611e3fc1b2a58905fce607a69ba81beca2e2eda2957f5c0e66832b553dc`, and keep the patched file at the same directory depth within a detached orchestration copy so its archived input references resolve. It takes the sealed Main candidate plist, disjoint output directory, explicit original history root, and frozen pair ID. It selects the frozen generation under read-only leases, clears the writable event cache setting, and calls `checkpoint_independent_close`. This patch was applied and compiled. The separate three-symbol replay exercised the same owner wrapper with real D12 inputs. The patched full-universe caller was not run as part of candidate admission.
