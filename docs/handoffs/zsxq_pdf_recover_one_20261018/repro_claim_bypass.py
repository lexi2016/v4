from __future__ import annotations

import json
import runpy
import tempfile
from pathlib import Path

from infrastructure.data_store import NativeDataStore
from infrastructure.zsxq_pdf_ingestion import STATE_RELATIVE, process_pdf_batch


fixture = runpy.run_path("tests/test_zsxq_pdf_ingestion.py")
with tempfile.TemporaryDirectory(
    prefix="recover-one-claim-bypass-",
    dir="/Users/lexi/Desktop/学习/agents调试/V4_ZSXQ_RECOVER_ONE_20261018_R1/reviewer",
) as temp_root:
    root, files = fixture["_fixture"](Path(temp_root))
    document_key, _engine_identity, calls = fixture["_seed_recovery_failed"](root, files)
    args = fixture["_recovery_args"](root, files, document_key, "unclaimed-id", calls)
    callback_names = {
        "metadata_lookup",
        "url_lookup",
        "downloader",
        "page_counter",
        "page_renderer",
        "ocr_page",
        "engine_info",
        "now",
    }
    callbacks = {key: value for key, value in args.items() if key in callback_names}
    batch = process_pdf_batch(
        data_root=root,
        trade_date=fixture["DATE"],
        slot=fixture["SLOT"],
        source_run_id=fixture["RUN_ID"],
        document_key=document_key,
        _recovery_authorization_id="unclaimed-id",
        **callbacks,
    )
    index = NativeDataStore(root)._read(STATE_RELATIVE)
    authorization_audit = root / "external_sources/zsxq_hourly/zsxq_pdf_recovery_audit.json"
    print(
        json.dumps(
            {
                "selected_document_key": document_key,
                "batch_status": batch["processed_this_batch"][0]["status"],
                "callbacks": calls,
                "recovery_consumed_entry": index.get("recovery_consumed", {}).get(document_key),
                "authorization_audit_exists": authorization_audit.exists(),
            },
            sort_keys=True,
        )
    )
