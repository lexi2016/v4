# Workbench score bridge

Apply `bootstrap-score-bridge.patch` from the root of the existing SHA-listed research panel asset export. The target `workbench-host/bootstrap.mjs` base SHA-256 is `07cac22679412866984219658e519b9002c7f5d47a7caaf1dcd7c49b4285ffb3`. The resulting SHA-256 is `94414e77a50a5ddbe9604b5b2ed5a41ceee69a9b452464222f54e96228e384ff`. Update the existing static allowlist entry for that asset together with `workbench.local.mjs` and add `formula-daily-chart.mjs` under the same shell directory.

The two formula groups share the current stock and exact-day score reader with the existing workbench. They display OHLCV in the existing chart card. The score bridge accepts the current stock identity and skips the historical original-formula renderer for this view. The daily K endpoint checks the active group membership and the same numeric manifest, selector, adjustment snapshot and overlay before serving bars.

Apply `received-company-missing.patch` to `workbench-host/received-research.mjs` in the same asset export. Its base SHA-256 is `2d3023b7e8b8e321a787b15af4f2d78a7415c79002c75d9a708eb8a42a23b63f` and its resulting SHA-256 is `86b497a7659988f164c932928ac5f55e4b19a5e96ce735bff39573b4dec6c1ea`. Keep the asset allowlist aligned. A validated `NOT_MATERIALIZED` response remains a missing-data state on the formula page after a completion notification. Other pages keep their existing completion handling.

## Formula Workbench acceptance before switching a preview

Run the browser check against the assembled loopback candidate with the existing Playwright runtime. Run it again against the selected preview after switching. Set `WORKBENCH_PLAYWRIGHT` to the available Playwright module entry and `WORKBENCH_CHROME` to the local Chrome executable when using the Mac runtime. An ordinary Playwright installation can resolve its browser directly.

```sh
node tests/frontend/check_formula_workbench_browser.mjs \
  --base http://127.0.0.1:18973 --require-f10-completion --exercise-regressions
```

The default fixture pins the November 13 source and November 16 observation. It requires `603658.SH` to show the same-day B1 at `36.89400` on the Canvas, the actual `3/5` score, and the published F10 business and financial fields. It then selects `300015.SZ` and verifies its published source-gap response and the corresponding empty state. For another reviewed batch, pass `--fixture` with `sourceDate`, `observationDate`, `gapSymbol`, and `positive` containing `symbol`, `score`, `marker`, `anchor`, `company`, and `financial`. The last two fields are arrays of expected visible strings from the reviewed source.

The three negative controls simulate missing Canvas text, a missing score and a company response in the F10 route. A pass requires all three controls to fail for their respective reasons. The successful path checks the candidate's real HTTP responses, matching date and generation, current-stock DOM and Canvas paint. Save the command and its final JSON with the release evidence.

The `f10` completion fingerprint is derived from the same validated published receipt used by the formula group's `/f10` reader. The completion check tests wrong-generation rejection and a fresh GET for the selected stock from a same-generation F10-only notification. A failed or rejected refresh retains the current verified card with an update status. A verified missing-data response can replace it, and changing the stock or date clears the prior card. The test changes the notification in the test browser and uses the candidate's actual F10 response. The candidate release bundles the host change alongside `workbench.local.mjs` and `formula-f10.mjs` in the existing static allowlist.

## Publish a subsequent source date

The approved board labels are 192选股 for `b23_entry` and 回测选股 for `pb2_confirm`. Dates with no committed result show both groups as pending. Run the existing exact formula projection from the V4 Reader after the source day's normal product has completed. Use its small `RESULT.json`, `NAME_BINDING.json`, `CANDIDATES.csv` and `CANDIDATES_NAMED.csv` batch to prepare the dated overlay.

```sh
python3 docs/handoffs/v4-formula-groups-workbench/prepare-formula-group-artifact.py \
  --batch "$FORMULA_RESULT_DIR" --output "$TASK_ARTIFACT_DIR/formula-groups.json"
```

After approving the prepared cohort, pass the installed API role's `V4_WORKBENCH_HOST_BINDING` and `V4_WORKBENCH_HOST_BINDING_SHA256` and the existing A_LONG owner lock. `--expected-current ABSENT` is for a new date. To replace the same day's reviewed result after its numeric manifest changes, pass the observed SHA-256 of that date's current `latest.json`.

```sh
python3 docs/handoffs/v4-formula-groups-workbench/publish-formula-group-artifact.py \
  --batch "$FORMULA_RESULT_DIR" \
  --binding "$V4_WORKBENCH_HOST_BINDING" --binding-sha256 "$V4_WORKBENCH_HOST_BINDING_SHA256" \
  --owner-lock "$EXISTING_A_LONG_OWNER_LOCK" --expected-current ABSENT
```

Publication uses the existing daily-product and calendar endpoints to verify the date and canonical manifest, saves a tiny immutable artifact and receipt under the configured Workbench owner directory, and advances only that date's pointer. List completion observes the pointer through the existing date event route. Read back the exact date's Workbench API and group buttons after the commit. The board request path performs no formula computation.
