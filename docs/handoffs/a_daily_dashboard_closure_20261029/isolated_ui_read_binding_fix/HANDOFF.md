Scope: only the existing isolated demo's static/report root bindings, dated
observation-date fallback, and D27 history caption, per
`headless_ui_0300/REPAIR_SCOPE.json`. Other accepted behavior remains unchanged.

The helper accepts `--panel-root` and `--report-data-root`, each an explicit
existing directory. The former mounts the supplied static overlay; the latter
binds the existing GET-only research-lane router to the report data root.
Defaults keep the project's static root and temporary empty lane root. No
proxy/copy framework, index build, download or service configuration was added.
The helper prints the two resolved read roots for verification.

`numeric283-panel.js` uses only the product's declared observation date. A dated
product with missing/null/empty/invalid observation date displays `观察未指定`.
Explicit dates and the original fixed 283 snapshot retain their own dates.
No observation date was inferred, and no numeric rows were changed.

The demo HTML states that its embedded D27 archive is historical reference and
that the numeric module displays its API product date independently. Report
copy explains optional explicit binding instead of claiming every run uses an
empty root.

Targeted checks: `tests/test_daily_dashboard_demo.py` 3 PASS; the existing dated
JS test with new render-date cases PASS. Tests verify actual static GET content,
root arguments reaching reader factories, unchanged defaults, and CLI argument
forwarding with uvicorn mocked (no service started). Exact commands and SHA are
in `RECOVERY.json`; `INCREMENTAL.diff` covers existing-file changes and the new
Python test is listed separately.

Root owns the actual headless recheck. Refresh only the candidate
`numeric283-panel.js` file in its already prepared static overlay, then start
the helper with `--panel-root <static_overlay>` and
`--report-data-root /Users/lexi/Library/Application Support/com.lexi.v35.local/state/data`,
plus the frozen `--daily-product-root`. Writer did not alter Root's overlay or
recover any additional assets. Actual headless/9-resource/report-root acceptance
and independent incremental review are pending. No live deployment, GUI,
package installation, archive mutation, index writes, commit or push occurred.
