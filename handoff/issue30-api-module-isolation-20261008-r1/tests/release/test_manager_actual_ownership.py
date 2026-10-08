"""The SHA-matched R2 app actually loads v4/manager_research services."""
from pathlib import Path

import pytest

from ops import api_release_integration as integration
from test_api_release_v2_contract import receipt_fixture


@pytest.mark.parametrize("module, allowed", [("manager", True), ("preselection", False)])
def test_actual_manager_service_path_has_its_own_module_owner(tmp_path, module, allowed):
    relative = "v4/manager_research/service.py"
    _, _, arguments = receipt_fixture(tmp_path, relative=relative, addition=True, module=module)
    if allowed:
        record = integration.build_integrated_app(**arguments)
        assert record["module_scope"]["module"] == "manager"
        assert (arguments["candidate_root"] / "app" / relative).read_bytes() == (
            arguments["source_root"] / relative).read_bytes()
    else:
        with pytest.raises(ValueError, match="MODULE_PATH_NOT_OWNED"):
            integration.build_integrated_app(**arguments)
