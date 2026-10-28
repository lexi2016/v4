
from v4.manager_workbench.inputs.source_bindings import load_us_universe_contract
from v4.manager_workbench.inputs.us_universe import (
    LEGACY_US_SYMBOLS,
    build_legacy_us_universe_contract,
    validate_us_universe_contract,
)


def test_universe_contract_keeps_legacy_scope_and_additive_48():
    contract = load_us_universe_contract(None, ["META", "AMZN"])
    assert contract["version"] == "US_MAPPING_UNIVERSE_CONTRACT_V3"
    assert "AMD" in contract["symbols"]
    assert "META" in contract["symbols"]
    assert len(contract["symbols"]) == 48
    legacy = build_legacy_us_universe_contract()
    assert legacy["symbols"] == list(LEGACY_US_SYMBOLS)
    assert legacy["version"] == "US_MAPPING_UNIVERSE_CONTRACT_V2"


def test_existing_extra_config_hook_adds_symbol_and_recomputes_contract_identity(tmp_path):
    from v4.manager_workbench.config import WorkbenchConfig

    config = WorkbenchConfig.model_validate({
        "state_root": str(tmp_path / "state"),
        "source_bindings": {"_extra": {"us_universe_extra_symbols": ["TSLA"]}},
    })
    contract = load_us_universe_contract(config)

    assert contract["version"] == "US_MAPPING_UNIVERSE_CONTRACT_V3"
    assert contract["symbols"][-1] == "TSLA"
    assert len(contract["symbols"]) == 49
    assert contract["additional_symbols"] == ["TSLA"]
    assert validate_us_universe_contract(contract) == contract

    invalid = dict(contract, contract_sha256="0" * 64)
    try:
        validate_us_universe_contract(invalid)
    except ValueError as error:
        assert str(error) == "US_UNIVERSE_CONTRACT_IDENTITY_MISMATCH"
    else:
        raise AssertionError("altered additive contract SHA must be rejected")
