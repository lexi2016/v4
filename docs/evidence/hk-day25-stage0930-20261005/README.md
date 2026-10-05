# 2026-09-25 HK 09:30-09:35 historical stage publication

This branch archives the necessary source patches, source snapshot, adapter and tests. It is not a merge of the concurrent canonical working-tree changes. Base commit: `04c03068bddcbddd49923dc6aa0a44b1d1139aef`. Canonical repository integration remains CANNOT_CONFIRM; the selector pre-edit file was not captured, so its archived file is explicitly a reviewed source snapshot, not a complete attributable delta.

## Verified result

- Target: 20260925 / STAGE_0930_0935 / HK_CONNECT only.
- Actual backfill run: `55742332ec504f119a54c42ce9cad3cd`.
- D-1 pool: target 20260925, signal 20260924; SHA-256 `c6202648a73d0103b2ec43e393618ca31e67183c730a4df4db018eced2cfacd0`.
- Raw input: 96 of 100 rows; SHA-256 `02229d41078a562a3863124dc799c37c1c087759744d4254b640873c1b5adefd`.
- Selection: 10 historical observation rows, PARTIAL_WITH_ROWS, WATCH_ONLY/NO_BUY.
- Selection artifact SHA-256: `8e32219e33962113527f78f0d0a2bc44276a39345264dd2c968d533bc324ed01`.
- Verified runner receipt SHA-256: `57c0ebadf08e372f2165b624d54b9287737451a9545cc11a9c2015e42c51deae`.
- Independent tests: stage/adapter 14 passed; calendar/source-binding 29 passed; exact API 4 passed. The API rejects wrong runs and missing/altered runner receipts.
- Final one-line UI fix and Vite output independently reviewed. Actual browser readback confirmed 10 HK cards, observation count 10/96, A-share market not requested, correct date/stage/run and R13 release identity.
- API_VERIFIED and UI_VERIFIED for this explicit historical URL. Formal PIT and natural-run verification are NOT established. Production, buy-gate and order flags remain false.

## Runtime and remaining limit

Runtime release: `hk-day25-stage0930-r13-20261005-ui-r1`.
Manifest SHA-256: `52a0bf950c65d6265c13c1718d670aaf543a3f74f762f87ef0c768355d016cab`.
Actual R13 activation receipt SHA-256: `7bb90e1c5007e71a72bf32cf9058f73e155a7f23e5a2cda403922f2438060ac4`.

The single local 127.0.0.1:8873 listener was independently identified as PID 17792 in the R13 app directory. It runs through a controlled background launch using the reviewed plist's arguments and environment. LaunchAgent bootstrap returned OS error 5; the original R11 plist was restored unchanged and its launchd job is not loaded. Automatic startup/restart remains CANNOT_CONFIRM. Do not describe this as managed-service recovery. An earlier launcher NameError was recovered to R12 before the corrected helper was validated and R13 started.

Local result:
[Open this historical run](http://127.0.0.1:8873/?date=20260925&stage=STAGE_0930_0935&backfill_run_id=55742332ec504f119a54c42ce9cad3cd&market=HK_CONNECT)

## Reproducibility boundary

Actual market data, selection manifests, full runner receipts, runtime JSON, credentials, dependencies and compiled assets are intentionally excluded from GitHub. Some tests require those frozen local fixtures; the source/test archive alone is not a claim that all tests run without them. The R11-to-API and R12-to-UI patches apply to their recorded release baselines; do not overwrite a newer canonical source tree with the snapshots.

Source and patch SHA-256:
- `runner_exact_delta.patch`: `809af38ed02ba1bd73d2c596de8e3a56f48d2672dff43c8afe12b3bad689ca8f`
- `selection_builder_registry.snapshot.py`: `19fef96cedb1c23f1fdeceef2fd4dd8e148057d00f9aba8dd933f56435ac4522`
- `test_hk_stage0930_historical_observation.py`: `9addfc431b416e0252a65ac2ace2814c4e6617c83684aaeb5d978c6336445364`
- `run_stage0930_research_only.py`: `afc25020c32e733b2827c36f38c9dd4acea4d570aa4cce43f6c3fac35cd241c2`
- `test_adapter_time_provenance.py`: `9a57e8722ae9fca6280b68f9861c38df8530b2299a8ac7c71ea37260d072c423`
- `day25_exact_api.patch`: `139775242db164f703db7e320b8b0ac04072947b2e5c2bd5334d1f32c8d81795`
- `test_hk_stage0930_exact_backfill_binding.py`: `9834d20f80e7407dd0378a558b2c25a831f614f94d34277c6bc0227e2425af36`
- `day25_ui_observation_count.patch`: `665c42ad8136cea29c69ab491ecf0db521623d36eee58bf592f8e8873cf9c27f`
