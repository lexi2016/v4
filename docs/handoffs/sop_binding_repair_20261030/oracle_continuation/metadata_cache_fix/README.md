# Exact installed SourceContext metadata reuse delta

The sole behavior change caches the original stock reader's parsed metadata inside SourceContext. Formula, rule, statistics, cache identity, checkpoint runkey and publisher remain unchanged. Thirteen focused tests and exact dtype/value/bars/name parity for 000016.SZ,002003.SZ,600025.SH independently passed. Warm reads measured about 0.015 seconds versus about 1 second for this read stage; whole-product throughput is separate.

Apply `daily_product_source_context.patch` only to the existing installed baseline SHA256 `7075e6a96e21aa42c85213e793110b802121bc959ad7476780e4dc632a0186fd`; resulting source SHA256 must equal `abc339c267bc6c4090d06821a922f0266d20d60ccf2823ac91136ad746dd6c48`. The existing GitHub root module is an older baseline, so this handoff deliberately preserves its bytes rather than overwriting another owner's unmerged runtime changes. Integrate the known baseline first or reconcile the small bound patch; do not blindly apply to another revision.

The absolute installed Mac source is `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/sop-binding-fastread-20261030-r2-main/app/ops/research_panel_daily_product.py`. Main manifest `b8ca8d2998596d0a3aa48d6eba1bd2c9ab52ec5ccb27fb0c115a86be1ba1e4ab` differs from its prior release by that file alone; API and Stage are unchanged. The original reader remains SHA `5fd9024fc4ee858a62eaac050532187b171289eac82837bc7ca406e938509ded`.

The first original reader call still validates price basis and paired publication. Reuse checks both pointers, panel/receipt/reader identity and publication journal. Binding drift rejects reuse. Tests are in `tests/test_daily_product_cached_reader.py`. Rollback uses the preserved prior Main release; keep the valid published price pair and all completed stock checkpoints.

Only installation/source behavior is accepted here; final D30 product, API/UI and natural scheduling outcomes require their own actual receipts. No market acquisition, QFQ recomputation or financial chart review was performed by this delta.
