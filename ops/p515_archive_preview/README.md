# P515 D17 archive preview

This is an opt-in, loopback-only retrospective archive overlay assembled from the current V4 `workbench.html` shell. It retains that original HTML body and CSS, adds the `D17 档案预览` button in the workbench masthead, and removes the live bootstrap scripts in the isolated copy. The original `workbench.local.mjs` and `workbench-model.mjs` are not executed because they load live application data.

Before serving any archived CSV, `serve_archive_preview.py` verifies the GEMINI V3 ZIP SHA and the exact `selection_output_adapter.py` member SHA, imports those actual ZIP member bytes, calls `build_prefilter_display_view` on the D17 disposition records, and enforces 5,572 disposition rows, 822 original PASS members, and zero score attachments. The 33-row score CSV is counted and displayed separately; no code-only score join is performed.

## Reproduce the captured browser run

Use the configured `PANEL_PYTHON` and the existing Chrome/Playwright installation. The browser verifier starts a fresh `127.0.0.1` server on an ephemeral port, restricts browser requests to that origin, performs the real page clicks/search/filters/sorts/pagination/downloads, and closes both browser and server afterward.

```sh
PREVIEW_TMPROOT="$(mktemp -d /tmp/p515-d17-archive-preview.XXXXXX)"
PREVIEW_UI="$PREVIEW_TMPROOT/ui"
mkdir -p "$PREVIEW_UI"

"$PANEL_PYTHON" ops/p515_archive_preview/assemble_archive_preview.py \
  --original-html "/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-panel-throughput-storage-20261118-r3/api-static/research-panel/workbench.html" \
  --output-html "$PREVIEW_UI/workbench.html"

node ops/p515_archive_preview/verify_browser.mjs \
  "/Users/lexi/Desktop/学习/v4_app/artifacts/p515_d17_anomaly_wave_shrink_d18_review_20261118" \
  "/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-panel-throughput-storage-20261118-r3/api-static/research-panel" \
  "$PREVIEW_UI/workbench.html" \
  "/Users/lexi/.codex/worktrees/p515-d17-archive-preview-20261119/ops/p515_archive_preview/archive_preview.mjs" \
  "/Users/lexi/Desktop/学习/v4_app/artifacts/p515_d18_master_followup_20261119_v2/_reference/gemini-v3.zip" \
  "$PREVIEW_UI/V3_DISPLAY_BINDING.json" \
  "$PREVIEW_UI"

"$PANEL_PYTHON" ops/p515_archive_preview/verify_exports.py \
  --source-root "/Users/lexi/Desktop/学习/v4_app/artifacts/p515_d17_anomaly_wave_shrink_d18_review_20261118" \
  --ui-root "$PREVIEW_UI"

# The command creates a unique temporary path, so it cannot overwrite the captured delivery.
rm -rf -- "$PREVIEW_TMPROOT"
```

The captured browser route was `/research-panel/workbench.html?mode=p515-d17-archive-preview`. This preview is not installed into the production workbench and has no persistent listener after the verifier exits.

## Manual loopback session

After building `workbench.html` in a fresh `PREVIEW_UI`, this foreground command is an optional way to inspect the page without the Playwright run:

```sh
"$PANEL_PYTHON" ops/p515_archive_preview/serve_archive_preview.py \
  --source-root "/Users/lexi/Desktop/学习/v4_app/artifacts/p515_d17_anomaly_wave_shrink_d18_review_20261118" \
  --workbench-root "/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-panel-throughput-storage-20261118-r3/api-static/research-panel" \
  --preview-html "$PREVIEW_UI/workbench.html" \
  --client-module "/Users/lexi/.codex/worktrees/p515-d17-archive-preview-20261119/ops/p515_archive_preview/archive_preview.mjs" \
  --adapter-zip "/Users/lexi/Desktop/学习/v4_app/artifacts/p515_d18_master_followup_20261119_v2/_reference/gemini-v3.zip" \
  --binding-output "$PREVIEW_UI/V3_DISPLAY_BINDING.json" \
  --port 0
```

The first line reports an ephemeral `http://127.0.0.1:<port>` origin; open its `/research-panel/workbench.html?mode=p515-d17-archive-preview` route in a browser. The server binds only to loopback and accepts only the original workbench CSS, the archive module, the three frozen CSVs, and receipts. Press `Ctrl-C` in the foreground terminal to stop it. That is the rollback: the original workbench and production service were never modified or stopped. Remove only the uniquely created `$PREVIEW_TMPROOT` when finished; do not remove or alter the original archive inputs or installed workbench assets.
