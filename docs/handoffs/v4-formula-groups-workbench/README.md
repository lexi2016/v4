# Workbench score bridge

Apply `bootstrap-score-bridge.patch` from the root of the existing SHA-listed research panel asset export. The target `workbench-host/bootstrap.mjs` base SHA-256 is `07cac22679412866984219658e519b9002c7f5d47a7caaf1dcd7c49b4285ffb3`. The resulting SHA-256 is `ca66ef760352f9a3b525570aab5f7f631fd1e3d7c1c8e498bb568c1c18d704f7`. Update the existing static allowlist entry for that asset together with `workbench.local.mjs` and add `formula-daily-chart.mjs` under the same shell directory.

The two formula groups share the current stock and exact-day score reader with the existing workbench. They display OHLCV in the existing chart card. The score bridge accepts the current stock identity and skips the historical original-formula renderer for this view. The daily K endpoint checks the active group membership and the same numeric manifest, selector, adjustment snapshot and overlay before serving bars.
