"""Shared data fixture, deliberately not a unittest.TestCase."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
from v5_shadow.run_ledger import MARKER


def make_ledger_fixture(add_cleanup):
    temporary = tempfile.TemporaryDirectory()
    add_cleanup(temporary.cleanup)
    root = Path(temporary.name).resolve()
    (root / '.v5-daily-run-ledger').write_bytes(MARKER)
    return SimpleNamespace(temporary=temporary, root=root,
        identity=dict(lane='us_mapping',target_date='20261009',research_cutoff='2026-10-09T00:00:00Z',
            input_sha256='a'*64,code_sha256='b'*64,config_sha256='c'*64,dependency_sha256='d'*64),
        success=dict(status='SUCCEEDED',product_reference={'artifact_sha256':'e'*64},
            readback_verified=True,retry_safe_without_external_effect=False,reason_codes=[]))
