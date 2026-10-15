# Independent live cache recovery review

**Verdict: PASS_WITH_CANNOT_CONFIRM.** The controlled run is independently verified as a bounded `PARTIAL_TERMINAL` result. It retained 567 cache-ready records, kept 122 market-data gaps and 124 OVERSOLD evaluation rows unassessed, and remained research-only. No full-coverage, natural-slot, or investment-validity claim is made.

## Runtime and source identity

The active launchd job is `com.lexi.v35.scheduler`, state `running`, PID `39211`, with its working directory and `V35_APP_ROOT` pointing to release `oversold-daily-cache-20261016-r1`. The active manifest path and SHA match the candidate. Actual file SHA-256 values match the pins: release manifest `03f1c61fe881039b286bd4d0d9acbcb29d32593747e7c0119b8e3c261237bfb2`, active plist `12fec20f665af3ce0a20ffd2c989684ff580c36ae2d932fdc285bb798e93d137`, and manager config `65684e5eb7657390747c089db74047d6a2c67d7f5de1bd3fe757a62f120965ca`. The two runtime source files also match the activated source pins: `hk_daily_supplement.py` `7b09a85431b2d4398de4f057a755b8b7398e82e26611297df9ba2efab8dbb250`; `oversold_daily.py` `9ebeed117ee883805ac8a5e3331cb53fa688892905dd8292912ee5ba4b20099e`.

## Controlled result and lineage

The saved cursor and plan bind source HK session `20261015` to target `20261016`, run/job `c1c5e85d691c46f98086b74053fe8ff8`, and capture `bd87816e25bc0bda5f1f95e9`. The cursor records 3 capture attempts, 2 job attempts, one verified classifier migration, and terminal reason `STABLE_OWNER_GAPS_RETAINED`. Its source cutoff is `2026-10-16T03:34:12.977779+08:00`; capture availability is `2026-10-16T03:34:09.286202+08:00`, before that cutoff. The saved plan is `NEXT_DAY`, `HK_CONNECT`, and generated at `2026-10-16T03:34:44.994185+08:00` with the same source session.

The live capture manifest and raw hashes match their files. The capture is `PANEL_GAPS` for 689 codes: the raw records contain 567 `READY`, 122 `UNASSESSED`, 567 cache hits, zero successful `network_bar_requests`, and 244 `ResponseHeaderRecvFails` (122 on each configured endpoint). Zero successful bar requests therefore does not mean no transport attempts. The 122 unresolved market-data gaps remain explicit; the run did not turn them green.

The exact panel and master parents are pinned to manifest SHAs `bf80f6869862c9363f132d8ca0b134e613d919bc0441b52550efcc417726fba0` and `57e15f3cd79535ea7d566a2b1f560692b148ef932b72d8fa14c662ef853b2898`. The capture manifest SHA is `56585e747e7b33f1b48d7edf36aaeb1a7d7ea9225ccf068ed0bbfd0be2bb051d`; raw SHA is `bd87816e25bc0bda5f1f95e9df873fcc95dac37e4bd209244d46c5817352ad43`.

## API, lane preservation, and idempotency

A read-only GET to the existing OVERSOLD recommendation route returned HTTP 200 and `PARTIAL` for the exact run/date/phase. Its lane summary is 689 total: 21 selected, 171 conditional watch, 373 not selected, 124 unassessed, 0 observation-only. `US_MAPPING` remains `INPUT_MISSING` with `US_MAPPING_EXACT_DATE_BINDING_MISSING`; the snapshot still references the existing legacy NEXT_DAY lane source `18425e50e6294f15a6bc02ac881c5af2`. Research-safety flags remain `RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`, and `orders_sent=false`.

The corrected deployment receipt reports one guarded terminal tick at 03:38:05.944526 HKT: the real driver returned `PARTIAL_TERMINAL`, attempted no store mutations, and queued no future. I independently matched the current SHA values for the seven artifacts covered by its before/after check: daily cursor, new plan, new attempt, capture manifest/raw, legacy NEXT_DAY cursor, and legacy NEXT_DAY plan. The old failed automatic recovery `0c72d7ade78249d280b03418e71db681` is also still present in the API version list and on disk at SHA `cd9ec2eee28ec9089bb8eb2e06d8c687eba1fed3f14f14e503cf06b888e97c8c` (mtime 02:37:59 HKT, before the tick). **Its tick-before/tick-after SHA is `CANNOT_CONFIRM`**, as the corrected receipt explicitly records. The distinct legacy NEXT_DAY plan `18425e50e6294f15a6bc02ac881c5af2` remains at SHA `b769e3bf4cea635cf50e546e639a9193493e783a3299065d0d76549fe1ea0f99`; its before/after check is covered by the receipt. The API version list also retains both earlier manual plans.

The existing `UI_REVIEW.md` records `UI_VERIFIED=PASS` and has the hash cited below; its CUA verification was performed by the parent, so I reused that evidence and did not repeat the UI check. The prior independent source review remains `PASS_CACHE_FIRST_REPAIR` with 18 focused tests passing. That review documents two nonblocking P2 limits: corrupt-cache fallback behavior and automated negative coverage for corrupt legacy capture evidence remain `CANNOT_CONFIRM`; they do not change this bounded live result.

## Limits

The controlled result is **not** a natural 16:30 run: `NATURAL_SLOT_UNVERIFIED`. Economic or investment validity is `CANNOT_CONFIRM`. No source tests, scheduler tick, POST, service control, or UI action was run by this reviewer; live API checks were GET-only.

## Evidence pins

- Deployment receipt: `LIVE_CACHE_DEPLOYMENT_RECEIPT.md` SHA-256 `6f46e3096a8a934025e9a2982e81725fd3dbac8dcb6eafc5e0a435e64586b8ff`; JSON `17f206555909f653ed7cd799b425db00051492182d1e4375a68693869bfb87f4`.
- Runtime review JSON: `RUNTIME_CACHE_INDEPENDENT_REVIEW.json` SHA-256 `e3ac3ab46f0797c0179e9a960beffc8b95ce772263d4d3048a1c3d8acf426446`.
- Cache-first source review: `CACHE_FIRST_INDEPENDENT_REVIEW.md` SHA-256 `fcd4541507fd76baa3b49de27d150f01f902e3eb611a78c6a9504786d617cab8`.
- UI receipt: `UI_REVIEW.md` SHA-256 `12ef319bd8918b8f3bf7b32798d1fb01a09fd4e1f8f2b55e3f71a02255b8d2db`.
