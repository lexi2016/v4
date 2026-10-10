# Source payload and application context

`rebound_panel_repair.py` is the complete local after-image (SHA-256 `9f547b8d2307b847b3d284eff2e5914d715283a06eb427044074b34bdc3114da`). `test_rebound_date_compat.py` is the synthetic regression (SHA-256 `4f707476683c18bc9a55cef77b6e3ab7f26f0da391cd23021ae9877768035135`). `date-storage-compat.patch` is the exact patch (SHA-256 `6ea3ee7054dfeedee4d061225b35cef40c9f540251da399141f4d291b24b22e8`); `CHANGE_MANIFEST.json` binds the baseline and postimage.

Expected source chain: base `ebe5944ecfbec2f6a161793d7c11946dea063e57`, identity-delivery predecessor `2bfb4c8c5f770122077e3baf914cf5b05b8a2450`, then this local patch. The remote handoff branch was only planned from `ebe5944...`; it is not claimed to contain either local step. Patch application should stop if the source preimage SHA differs from the manifest. The package includes the complete after-image so a reviewer can inspect the intended behavior even if the patch needs rebasing.

This fixes a storage representation mismatch only. It does not alter the original two gates, decoder, scale, unit, source, owner authority, manager, or deployed data. No new product commit was created.
