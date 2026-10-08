# Packaging launcher review — PASS within the isolated-source scope

Reviewed package: `delivery_hk_integrity_r1`. This review did not modify any launcher or product file. It executed **zero product tests**, imported **zero product modules**, and made no deployment, API, collection, live-data, or remote-write action. The root agent's product regression results remain separate evidence.

## Findings found and closed

1. **Unlisted initializer could enter an isolated owner.** The initial launcher verified listed inputs but copied the entire owner directory; its import audit omitted top-level `stage_center` and `infrastructure` packages. The final launcher copies only the thirteen declared files for an owner, validates the exact supplemental file inventory, and audits both top-level package modules. A temporary-copy probe placed unlisted initializers in both owner trees: none entered the copied app. A supplemental initializer was rejected, and synthetic external top-level package records were rejected by the import auditor.
2. **Inherited pytest configuration could alter selection or plugin loading.** The initial launcher inherited `PYTEST_ADDOPTS` and `PYTEST_PLUGINS`. The final launcher clears both, clears `PYTHONPATH`, disables plugin autoload, and passes its pinned `pytest.ini` plus `--confcutdir` explicitly. A subprocess interception captured the actual generated command and environment under deliberately polluted variables and verified all of those controls.

Both findings are closed for the reviewed byte identities. No remaining material packaging issue was identified in the requested scope.

## Verified package boundary

* Each owner contains exactly **13** original files; all 26 before-images retain their declared identities.
* Supplemental imports contain exactly **17** pinned files, with the historic canonical origin and generic namespace-helper alias explicitly distinguished from current runtime identity.
* All **49** input-manifest entries match their bytes and SHA256. They comprise 26 owner sources, 17 support files, three test files, and three launcher/config files.
* `after/` contains exactly one file: `stage_center/_runner_parts/hk_input_validation.py`. The owner copy differs from its thirteen-file preimage only at this path in `after` phase; `before` phase has no overlay.
* The original regression file remains `6a48bd3357a97690d5886c03dff9e31fc84ae1a0357087bcca3f4168841cd930`.
* Targeted invocation includes both `test_hk_split_date_identity_closure.py` and the independent reviewer's `test_root_identity_probe.py`. This packaging review verified their selection in the generated command; it did not rerun or independently claim their product-test results.
* Original-suite invocation still selects the unchanged original test. A simulated subprocess exit `1` remains launcher exit `1`; this control uses no pytest execution or fabricated product-test XML.
* App copies, generated import expectations, and test data/log destinations are beneath the newly created temporary run directory. The launcher does not select an actual Mac application/data root or invoke an ops entry point. It reports `SOURCE_SLICES_WITH_PINNED_SUPPLEMENTS_NOT_FULL_MAC_RUNTIME` / `CANNOT_CONFIRM` for runtime recovery.

## Reviewed identities

| File | SHA256 |
|---|---|
| `harness/run_regressions.py` | `6b69cf58626a0550191b95a36e7516a20cadbf759d2253a23faa369f91438b32` |
| `harness/conftest.py` | `cf0a3268f22f3f67dd34adc876725dd650d2879d8ed66011c807275941fb676a` |
| `harness/pytest.ini` | `8250d20f42b419af40706490ead78aabab9feba93eab09a3f626e3de5256e1f4` |
| `harness/INPUT_MANIFEST.json` | `70431e5e6ae479e67bb9985fd5a9dbc2cc879d36b2041713bcdfcaccbac297dd` |
| Product after-image | `b20baa18d0ee9748971db835f6fb3dd9a0e1d66aabd8da8d450aee3a4a528a8e` |

The product after-image is unchanged by the packaging revision.

## Reproducible reviewer probes

```bash
/workspace/scratch/25c09a595aec/issue28/references/work/test-venv/bin/python -B \
  /workspace/scratch/25c09a595aec/issue28/work/hk_stage_failure_1843/packaging_review/probe_launcher_isolation.py
```

The probe uses only the Python standard library. It copies the declared package inputs into a new temporary directory and intercepts the pytest subprocess before execution. The original-exit control returns a clearly marked synthetic nonzero subprocess result solely to inspect launcher propagation. All temporary copies and simulated outputs are removed. The first probe-development attempt intercepted `platform`'s ordinary `uname` metadata subprocess; the harness was corrected to resolve that metadata before interception, after which the complete probe run passed. This was a reviewer-probe setup issue, not a product or launcher failure.

Final receipt: `LAUNCHER_ISOLATION_PROBES.json`, with **8 PASS controls**, `product_tests_executed=0`, `product_modules_imported=0`, and the exact reviewed hashes. Initial static evidence is retained in `INITIAL_STATIC_REVIEW.json`.

This PASS is limited to the packaged source-test launcher and its declared isolation/reporting controls. It adds no independent product-suite pass count and no actual-owner deployment, live-source, API/UI, natural-slot, or business-restoration claim.
