from pathlib import Path

import pytest

from ops.prepare_v192_assets_release import extend_stage_history


def test_current_stage_extra_owner_preserves_existing_reader_bytes():
    path = Path.home() / ('Library/Application Support/com.lexi.v4.local/candidates/'
                         'v4-daily-materials-20261109-r4/v4-daily-materials-20261109-r4-stage/'
                         'app/infrastructure/manager_input_attestation.py')
    if not path.is_file():
        pytest.skip('installed Stage baseline fixture not available')
    before = path.read_text()
    after = extend_stage_history(before)
    assert after.replace('len(historical) > 6', 'len(historical) > 5') == before
    compile(after, '<six-exact-historical-owners>', 'exec')
    with pytest.raises(ValueError, match='EXACT_FIVE_OWNER_STAGE_PREIMAGE_REQUIRED'):
        extend_stage_history(after)
