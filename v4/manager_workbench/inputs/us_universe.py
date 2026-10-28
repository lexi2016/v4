from __future__ import annotations

from hashlib import sha256
import json
import re
from collections.abc import Sequence
from typing import Any, Mapping


US_UNIVERSE_SCHEMA = "v4.manager_workbench.us_universe_contract.v1"
LEGACY_UNIVERSE_VERSION = "US_MAPPING_UNIVERSE_CONTRACT_V2"

LEGACY_US_SYMBOLS = (
    "AMD",
    "ARKX",
    "AVGO",
    "BOTZ",
    "CIEN",
    "CLOU",
    "COHR",
    "COPX",
    "DLR",
    "DRIV",
    "EQIX",
    "FCG",
    "GLD",
    "GRID",
    "ICLN",
    "ITA",
    "KBE",
    "LIT",
    "LITE",
    "MU",
    "NLR",
    "NVDA",
    "REMX",
    "SOXX",
    "STX",
    "TAN",
    "UFO",
    "VRT",
    "WDC",
    "XBI",
    "XLE",
    "XLP",
    "XLY",
)

ADDITIONAL_INTERNET_SYMBOLS = (
    "META",
    "GOOG",
    "GOOGL",
    "AMZN",
    "BABA",
    "JD",
    "PDD",
    "DASH",
    "UBER",
    "BKNG",
    "EXPE",
    "TCOM",
    "BIDU",
    "BILI",
    "NTES",
)

UNIVERSE_VERSION = "US_MAPPING_UNIVERSE_CONTRACT_V3"
_SAFE_US_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.\\-]{0,9}$")


def _additional_symbols(value: Sequence[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError("US_UNIVERSE_ADDITIONAL_SYMBOLS_INVALID")
    result: list[str] = []
    base = set(LEGACY_US_SYMBOLS) | set(ADDITIONAL_INTERNET_SYMBOLS)
    for symbol in value:
        if (not isinstance(symbol, str) or symbol != symbol.strip()
                or not _SAFE_US_SYMBOL.fullmatch(symbol)):
            raise ValueError("US_UNIVERSE_ADDITIONAL_SYMBOL_INVALID")
        if symbol in base:
            continue
        if symbol in result:
            raise ValueError("US_UNIVERSE_ADDITIONAL_SYMBOL_DUPLICATE")
        result.append(symbol)
    return result


def build_legacy_us_universe_contract() -> dict[str, Any]:
    contract = {
        "schema_version": US_UNIVERSE_SCHEMA,
        "version": LEGACY_UNIVERSE_VERSION,
        "source_owner": "external_finance",
        "symbols": list(LEGACY_US_SYMBOLS),
    }
    contract["contract_sha256"] = sha256(
        json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return contract


def build_us_universe_contract(extra_symbols: Sequence[str] | None = None) -> dict[str, Any]:
    additional_symbols = _additional_symbols(extra_symbols)
    symbols = list(dict.fromkeys(
        [
            *LEGACY_US_SYMBOLS,
            *ADDITIONAL_INTERNET_SYMBOLS,
            *additional_symbols,
        ]
    ))

    contract = {
        "schema_version": US_UNIVERSE_SCHEMA,
        "version": UNIVERSE_VERSION,
        "source_owner": "external_finance",
        "legacy_symbols": list(LEGACY_US_SYMBOLS),
        "symbols": symbols,
        "categories": {
            "internet_social_ads": [
                "META",
                "GOOG",
                "GOOGL",
                "BIDU",
                "BILI",
                "NTES",
            ],
            "platform_ecommerce": [
                "AMZN",
                "BABA",
                "JD",
                "PDD",
            ],
            "local_delivery": [
                "DASH",
                "UBER",
            ],
            "online_travel": [
                "BKNG",
                "EXPE",
                "TCOM",
            ],
        },
        "gaps": [],
    }
    if additional_symbols:
        contract["additional_symbols"] = additional_symbols

    contract["contract_sha256"] = sha256(
        json.dumps(
            {
                key: value
                for key, value in contract.items()
                if key != "contract_sha256"
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    return contract


def validate_us_universe_contract(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the default/additive V3 contract or frozen legacy 33 scope."""
    contract = dict(value)
    version = contract.get("version")
    symbols = contract.get("symbols")
    if (
        contract.get("schema_version") != US_UNIVERSE_SCHEMA
        or not isinstance(symbols, list)
        or any(not isinstance(symbol, str) or not symbol for symbol in symbols)
        or len(symbols) != len(set(symbols))
    ):
        raise ValueError("US_UNIVERSE_CONTRACT_INVALID")
    if version == UNIVERSE_VERSION:
        extras = _additional_symbols(contract.get("additional_symbols", []))
        canonical = build_us_universe_contract(extras)
        if contract != canonical:
            raise ValueError("US_UNIVERSE_CONTRACT_IDENTITY_MISMATCH")
    elif version == LEGACY_UNIVERSE_VERSION:
        if symbols != list(LEGACY_US_SYMBOLS):
            raise ValueError("US_LEGACY_FIXED_33_SCOPE_INVALID")
        expected_sha = contract.get("contract_sha256")
        if expected_sha is not None:
            expected = build_legacy_us_universe_contract()["contract_sha256"]
            if expected_sha != expected:
                raise ValueError("US_LEGACY_CONTRACT_SHA_INVALID")
    else:
        raise ValueError("US_UNIVERSE_CONTRACT_VERSION_UNSUPPORTED")
    return contract


def load_us_universe_contract(configuration: Any = None,
                              extra_symbols: Sequence[str] | None = None) -> dict[str, Any]:
    """Load the shared quote-scope contract from the existing config hook.

    ``source_bindings._extra.us_universe_extra_symbols`` is an additive V3
    configuration seam. An explicitly pinned full contract remains
    authoritative. Historical V2 stays fixed at its exact 33-symbol scope.
    """
    if configuration is None:
        bindings: Mapping[str, Any] = {}
    elif isinstance(configuration, Mapping):
        candidate = configuration.get("source_bindings", {})
        if not isinstance(candidate, Mapping):
            raise ValueError("US_UNIVERSE_CONFIG_SOURCE_BINDINGS_INVALID")
        bindings = candidate
    else:
        candidate = getattr(configuration, "source_bindings", {})
        if not isinstance(candidate, Mapping):
            raise ValueError("US_UNIVERSE_CONFIG_SOURCE_BINDINGS_INVALID")
        bindings = candidate

    pinned = bindings.get("us_universe_contract")
    extension = bindings.get("_extra", {})
    if not isinstance(extension, Mapping):
        raise ValueError("US_UNIVERSE_CONFIG_EXTRA_INVALID")
    configured_extras = extension.get("us_universe_extra_symbols", [])
    if not isinstance(configured_extras, (list, tuple)):
        raise ValueError("US_UNIVERSE_ADDITIONAL_SYMBOLS_INVALID")
    requested_extras = [*configured_extras, *_additional_symbols(extra_symbols)]

    if pinned is not None:
        if not isinstance(pinned, Mapping):
            raise ValueError("US_UNIVERSE_CONFIG_CONTRACT_INVALID")
        contract = validate_us_universe_contract(pinned)
        if requested_extras:
            if contract.get("version") != UNIVERSE_VERSION:
                raise ValueError("US_LEGACY_CONTRACT_CANNOT_BE_EXTENDED")
            current_extras = list(contract.get("additional_symbols", []))
            contract = build_us_universe_contract([*current_extras, *requested_extras])
        return validate_us_universe_contract(contract)

    return validate_us_universe_contract(build_us_universe_contract(requested_extras))


def normalize_relation_registry(value: Mapping[str, Any]) -> dict[str, Any]:
    relations = []

    for item in value.get("relations", value.get("cards", [])):
        if not isinstance(item, Mapping):
            continue

        us_symbols = item.get("us_symbols") or (
            [item["us_symbol"]]
            if item.get("us_symbol")
            else []
        )

        hk_symbols = item.get("hk_symbols") or (
            [item["hk_symbol"]]
            if item.get("hk_symbol")
            else []
        )

        for us_symbol in us_symbols:
            for hk_symbol in hk_symbols:
                relations.append(
                    {
                        **dict(item),
                        "us_symbol": us_symbol,
                        "hk_symbol": hk_symbol,
                        "status": item.get(
                            "status",
                            "PROPOSED",
                        ),
                        "pit_status": item.get(
                            "pit_status",
                            value.get("pit_status", "PIT_UNCONFIRMED"),
                        ),
                    }
                )

    return {
        "schema_version": value.get(
            "schema_version",
            "v4.manager_workbench.us_relation_registry.v2",
        ),
        "relations": relations,
        "source_asof": value.get("source_asof"),
        "pit_status": value.get(
            "pit_status",
            "PIT_UNCONFIRMED",
        ),
        "status": value.get("status", value.get("review_status", "PROPOSED")),
        "contract_version": value.get("contract_version", value.get("universe_version")),
        "limitations": list(value.get("limitations") or []),
    }
