# Fixed announcement membership handoff

This change applies the user's lock for the announcement module: keep using the currently verified Hong Kong Stock Connect universe until the user explicitly requests an update. Target months do not select a newer membership file, and the source observation date is not turned into an effective interval.

The pinned owner is `FUTU_HKCONNECT_PLATE_MEMBERSHIP`, produced by `v35_dispatcher.research_panel_daily_hk`. The source is the existing full-market artifact dated 2026-10-12, available at `2026-10-12T19:58:59.501065+08:00`. It contains **698 members** with member SHA-256 `ce3c7eb8757c6c4d9dc8540653fb9d355479b5940547a9850147a847963c0446`. The fixed identity SHA-256 over the six existing owner references is `18af7be11537264955cdb0d5c5c6a6daa215e5f921fbe0be2fbabb0f9f1a95a9`.

At runtime, the resolver takes the authority root from the existing `shared_root` configuration value. The policy records only these existing relative references and expected raw-file hashes; it does not copy the symbol list or create a producer.

| Owner file | SHA-256 |
| --- | --- |
| `universes/20261012/HK_CONNECT_FULL_MARKET.json` | `e908f19bed7c46a5837bbf564114958e923e6ebadae55db83175240ea4dd3c7d` |
| `universes/20261012/HK_CONNECT_FULL_MARKET.authority/5edffc17ac372b1008d2a8a1/capture.json` | `d59230d943c97628c7554bd98da16efc291a74f1140ca21d81cf4ba27a36017c` |
| `universes/20261012/HK_CONNECT_FULL_MARKET.current.json` | `4714fe63a5ab73bb2ad6b048639cd3d3e77cc3ab6a3409cf80b8f15526542eef` |
| `universes/20261012/HK_CONNECT_FULL_MARKET.authority/5edffc17ac372b1008d2a8a1/manifest.json` | `916a780d9f713aa1292abbf1eae02abb511cf0e5c0f991a57f1fff0b0949796f` |
| `universes/20261012/HK_CONNECT_FULL_MARKET.authority/5edffc17ac372b1008d2a8a1/publication.json` | `77249ed2b3c8c1b63a3ccc2c7a5e6bec75e204705b5f212a01665008db5fbac5` |
| `universes/20261012/HK_CONNECT_FULL_MARKET.authority/5edffc17ac372b1008d2a8a1/receipt.json` | `ebe22b9f161e85780673e4bf39d92a0531084f7e887e47f0d39480e0894f8d8e` |

The resolver verifies all six raw-file hashes and their owner, producer, market, code-list, publication, receipt, and capture relationships. It still requires the recorded `available_at` to be no later than the run cutoff and the source observation date to be no later than the target date. It emits `basis=USER_FIXED_UNIVERSE`, the pinned source date, count and member SHA, with `effective_from` and `effective_to` both null. Missing or changed owner bytes fail closed. A uniquely identified member is `IN`; an issuer outside the pinned list is `OUT`; invalid or ambiguous issuer identity is `UNKNOWN` and remains excluded. Existing legacy gates retain their prior reason strings.

The fixed gate resolved the real owner for target `20261020` and `20261120` in an offline overlay of the active runtime dependencies. Both returned the same source SHA, 698 members, and null effective endpoints. The focused suite passed 8 tests, covering those target dates, cutoff enforcement, corrupt SHA and missing-source denial, outside, invalid, and ambiguous issuer exclusion, and legacy reason compatibility.

The worktree baseline is commit `55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054`; the unchanged starting SHA for `announcement_membership.py` matched the active runtime at `564e3ae25d78feeaa953153d5b7604d1ecbb24198f9c4e3aeb2c69ee29a844b0`. This is an offline source handoff. Independent review, integration, deployment, live API/UI behavior, and a natural run remain unverified.
