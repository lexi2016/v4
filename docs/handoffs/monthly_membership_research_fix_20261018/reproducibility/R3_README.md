# R3 recommendation-count correction

The canonical changes only correct display counts and explain that strict US-mapping selection is not enabled. Saved selections and engines are unchanged.

`runtime_overlay_r3/app/` contains the exact reviewed-runtime source copies: Workbench.vue is rebased on the active R2 API source; the other three copies match canonical source. To reproduce this local candidate build, copy this directory into the handoff `local_only/runtime_overlay_r3/app/`, preserve the fixed active release/config references in ROOT_BASELINE_R3.json, and place the named helpers under `local_only/` as their original commands record. Run build_manager_web_r3.py, then build_api_r3.py with the repository on PYTHONPATH, using the project's v3.5-mac Python. The build touches only the manager entry and declared source deltas. Dependencies come from existing apps/web/node_modules.

verify_r3_actual_counts.py is the read-only saved-snapshot route canary. api_r3_readback.py performs GET only against the same saved run after deployment. activate_api_r3.py requires the independently reviewed activation plan; building a candidate does not authorize or prove activation. Immutable runtime trees, generated bundles, raw research inputs, logs, credentials, and local runtime configuration contents are excluded from this Git package.
