# Exact76 Mac history API consumption

The current history reader had no typed path for the captured Futu SDK QFQ prefix. The new branch consumes that prefix through the existing formula kernel, reader and chart envelope. It preserves SDK prices, volume and turnover without applying a second adjustment or splicing an older coordinate. Other symbols retain the existing default reader.

The captured view is dated 2026-10-26. Requests outside each stock prefix or after that date fail closed; automatic capture renewal and natural daily behavior remain unverified. This is a local research history API integration, not a replacement of the canonical selector/backtest panels or a PIT/return acceptance.

Validation: 76 symbols / 100266 rows / 152 source pages reconciled; three actual HTTP/UI samples (000523.SZ, 600030.SH, 601868.SH) match six rows each and 288 displayed cells. The independent candidate review is reused, with an affected-only R2 review after the real R1 publication failure. R1 omitted application_inventory.entry_count; R2 now verifies that field and invokes the unchanged dispatcher against the real package. The failed R1 package and exact-baseline restoration remain local evidence.

Source copies under source/ are byte-identical snapshots of the bounded local batch tools, not another producer or active deployment location. Their original paths and SHA values are recorded in VALIDATION.json. These tools rely on the bound original local runtime, release snapshots, immutable capture, original registry helper and input contracts; a clean standalone checkout without those artifacts was not validated. The two unchanged dependency modules were copied from the deployed source because the Git base did not contain those files. Original preimages and full source custody remain in the local batch.

Only the one history API module changed in the running application; 1314 other application files were preserved. Producer/control code in this branch supports preparation and guarded Root admission, and is not a new scheduled service. Raw market data, runtime packages, credentials, API responses, screenshots and registry history are excluded from this Git delivery.

RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false.
