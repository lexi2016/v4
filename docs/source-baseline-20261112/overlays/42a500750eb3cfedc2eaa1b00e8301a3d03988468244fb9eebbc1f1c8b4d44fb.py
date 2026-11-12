"""Read the frozen 25-stock zero-to-prefix-HIGH position result."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SOURCE_BINDINGS_PATH = Path(
    "/Users/lexi/Desktop/学习/Z哥方法论/research_workflow_v2/integration/SOURCE_BINDINGS.json"
)
SOURCE_BINDINGS_SHA256 = "a5e48f4d933b9ba43b1b33834be08c64c6e49bada24df1efea479b9e1ca273ed"
POSITION_CSV_SHA256 = "d8d61cc9583eea726c4c2f3b4d0705b2caf4af62d74ffa59eebec243688944b7"
RECEIPT_SHA256 = "255ba2680e293b8d9cce3e64cf1f1fafb4d790e421579b4c10b631d5157ffeaf"
EVIDENCE_SHA256 = "43289a0e87d443b7fed7f802d8bd2d7b9192d5399c21ccc437816bd04b0958d0"
FINDINGS_SHA256 = "a340658364e380a847615720a0879ac83d219e0fa7ffc67abe7d47229ffd9b1c"
PREFILTER_SHA256 = "f7ef35e58db0be71d13815d6278a54d77d87c71219b9a5e40a76278eb37054fc"
PREFILTER_REVIEW_SHA256 = "5c03beecb3be782f77d693cb7631bf463a17c334f9d0af47299c26f7842da247"
PREFILTER_SUMMARY_SHA256 = "7909429fb5099e692bd437fbbc0e04aa3b109c8b16d517a1459d1899f10646b1"
PRICE_POSITION_MODULE_PATH = Path(
    "/Users/lexi/Desktop/学习/Z哥方法论/research_workflow_v2/integration/price_position.py"
)
PRICE_POSITION_MODULE_SHA256 = "a909eee7ab4cb51dad305ce9ca9cb277261d7bd5f0c8df8fdfc12da81ae080c2"

ASOF = "20261023"
SOURCE_GENERATION = "f3c4ce582565e4fb431766fd51c02233654e7d384240b7279154ea32691d7104"
FIELD = "zero_to_history_high_position_pct"
FORMULA = "100 * close_D / max(high_t for t<=D)"
METRIC_TYPE = "ZERO_TO_PREFIX_HIGH_POSITION"
METRIC_KIND = "PRICE_INTERVAL_ZERO_TO_HISTORY_HIGH_PCT; not empirical CDF"
PRICE_BASIS = "QFQ_ASOF"
HISTORY_SCOPE = "FULL_AVAILABLE_ACCEPTED_SAME_VINTAGE_PREFIX; NOT_CERTIFIED_LISTING_HISTORY"
EXPECTED_SYMBOLS = (
    "000156.SZ",
    "000690.SZ",
    "000810.SZ",
    "000902.SZ",
    "000999.SZ",
    "002223.SZ",
    "002273.SZ",
    "002568.SZ",
    "002833.SZ",
    "300033.SZ",
    "600000.SH",
    "600019.SH",
    "600028.SH",
    "600114.SH",
    "600398.SH",
    "600499.SH",
    "600566.SH",
    "600571.SH",
    "600785.SH",
    "600814.SH",
    "600863.SH",
    "600886.SH",
    "600887.SH",
    "600987.SH",
    "601225.SH",
)

_DISPLAY_SUMMARY = (
    "0至历史最高价区间位置；不是经验分位；仅覆盖同一冻结版本的完整可得接受前缀，"
    "未认证为上市全历史。"
)


class PositionSourceError(ValueError):
    """Frozen bindings or source artifacts do not match the accepted identity."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_verified(path: Path, expected_sha256: str, label: str) -> bytes:
    try:
        data = path.read_bytes()
    except OSError as error:
        raise PositionSourceError(f"POSITION25_SOURCE_MISSING:{label}") from error
    actual = _sha256(data)
    if actual != expected_sha256:
        raise PositionSourceError(f"POSITION25_SOURCE_SHA256_MISMATCH:{label}")
    return data


def _cannot_confirm(
    ts_code: str,
    asof: str,
    reason: str,
    *,
    positions_sha256: str = POSITION_CSV_SHA256,
    bindings_sha256: str = SOURCE_BINDINGS_SHA256,
) -> dict[str, Any]:
    return {
        "schema_version": "v4.research.zero_to_history_high_position.v1",
        "status": "CANNOT_CONFIRM",
        "ts_code": ts_code,
        "asof": asof,
        "source_asof": ASOF,
        "field": FIELD,
        FIELD: None,
        "basis": None,
        "formula": FORMULA,
        "metric_kind": METRIC_KIND,
        "history_scope": HISTORY_SCOPE,
        "summary": _DISPLAY_SUMMARY,
        "source": {
            "artifact": "25_ZERO_FLOOR_HIGH_POSITION.csv",
            "sha256": positions_sha256,
            "binding_sha256": bindings_sha256,
            "generation": SOURCE_GENERATION,
            "asof": ASOF,
        },
        "cannot_confirm": [reason],
        "write_policy": "read_only",
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


@dataclass(frozen=True)
class Position25Provider:
    """Verify and read only the bound CSV row for one supported symbol."""

    bindings_path: Path = SOURCE_BINDINGS_PATH
    bindings_sha256: str = SOURCE_BINDINGS_SHA256
    positions_sha256: str = POSITION_CSV_SHA256
    receipt_sha256: str = RECEIPT_SHA256
    evidence_sha256: str = EVIDENCE_SHA256
    findings_sha256: str = FINDINGS_SHA256
    prefilter_sha256: str = PREFILTER_SHA256
    prefilter_review_sha256: str = PREFILTER_REVIEW_SHA256
    prefilter_summary_sha256: str = PREFILTER_SUMMARY_SHA256
    price_position_module_path: Path = PRICE_POSITION_MODULE_PATH
    price_position_module_sha256: str = PRICE_POSITION_MODULE_SHA256

    def get(self, ts_code: str, asof: str) -> dict[str, Any]:
        if asof != ASOF:
            return self._cannot_confirm(ts_code, asof, f"UNSUPPORTED_ASOF:{asof}")
        if ts_code not in EXPECTED_SYMBOLS:
            return self._cannot_confirm(ts_code, asof, "TS_CODE_NOT_IN_FROZEN_25_STOCK_COHORT")

        try:
            binding_bytes = _read_verified(
                self.bindings_path,
                self.bindings_sha256,
                "SOURCE_BINDINGS.json",
            )
            bindings = json.loads(binding_bytes.decode("utf-8"))
            if not isinstance(bindings, dict):
                raise PositionSourceError("POSITION25_BINDINGS_SCHEMA_MISMATCH")
            binding = bindings.get("zero_to_history_high_position")
            if not isinstance(binding, dict):
                raise PositionSourceError("POSITION25_FIELD_BINDING_MISSING")
            self._validate_binding(binding)

            self._verify_bound_file(binding, "positions_csv", self.positions_sha256)
            self._verify_bound_file(binding, "receipt", self.receipt_sha256)
            self._verify_bound_file(binding, "evidence", self.evidence_sha256)
            self._verify_bound_file(binding, "findings_csv", self.findings_sha256)
            prefilter_metric = self._metric_from_bound_prefilter(binding, ts_code)
            rows = self._read_rows(Path(binding["positions_csv"]["path"]))
            row = rows.get(ts_code)
            if row is None:
                raise PositionSourceError("POSITION25_SYMBOL_ROW_MISSING")
            return self._ready(ts_code, asof, row, prefilter_metric)
        except (OSError, UnicodeError, json.JSONDecodeError, csv.Error, TypeError, KeyError, ValueError) as error:
            reason = str(error) or "POSITION25_SOURCE_INVALID"
            return self._cannot_confirm(ts_code, asof, reason)

    def _cannot_confirm(self, ts_code: str, asof: str, reason: str) -> dict[str, Any]:
        return _cannot_confirm(
            ts_code,
            asof,
            reason,
            positions_sha256=self.positions_sha256,
            bindings_sha256=self.bindings_sha256,
        )

    def _validate_binding(self, binding: dict[str, Any]) -> None:
        expected = {
            "schema": "zge-zero-to-prefix-high-position-binding/1",
            "asof": ASOF,
            "price_asof": ASOF,
            "price_basis": PRICE_BASIS,
            "source_generation": SOURCE_GENERATION,
            "metric_type": METRIC_TYPE,
            "metric_kind": METRIC_KIND,
            "field": FIELD,
            "formula": FORMULA,
            "zero_floor": 0,
            "history_scope": HISTORY_SCOPE,
            "expected_rows": len(EXPECTED_SYMBOLS),
            "expected_symbols": list(EXPECTED_SYMBOLS),
            "expected_prefilter_rows": 216,
            "expected_prefilter_unique_symbols": 216,
            "expected_prefilter_generation": SOURCE_GENERATION,
            "expected_prefilter_asof": ASOF,
            "expected_prefilter_price_basis": PRICE_BASIS,
            "accepted_prefix_unknown_count": 25,
        }
        for key, value in expected.items():
            if binding.get(key) != value:
                raise PositionSourceError(f"POSITION25_BINDING_MISMATCH:{key}")
        expected_hashes = {
            "positions_csv": self.positions_sha256,
            "receipt": self.receipt_sha256,
            "evidence": self.evidence_sha256,
            "findings_csv": self.findings_sha256,
            "prefilter": self.prefilter_sha256,
            "prefilter_review": self.prefilter_review_sha256,
            "prefilter_summary": self.prefilter_summary_sha256,
        }
        for key, expected_sha256 in expected_hashes.items():
            entry = binding.get(key)
            if not isinstance(entry, dict) or entry.get("sha256") != expected_sha256:
                raise PositionSourceError(f"POSITION25_BINDING_MISMATCH:{key}.sha256")

    def _metric_from_bound_prefilter(self, binding: dict[str, Any], ts_code: str) -> dict[str, Any]:
        source = _read_verified(
            self.price_position_module_path,
            self.price_position_module_sha256,
            "price_position.py",
        )
        module = types.ModuleType("frozen_position_price_position")
        module.__file__ = str(self.price_position_module_path)
        exec(compile(source, str(self.price_position_module_path), "exec"), module.__dict__)
        # The original adapter reads this fixed binding file. Tests may provide
        # an isolated binding, but no request field can choose this path.
        module.CONFIG = self.bindings_path

        prefilter_ref = binding.get("prefilter")
        if not isinstance(prefilter_ref, dict):
            raise PositionSourceError("POSITION25_BINDING_PATH_MISSING:prefilter")
        prefilter_rows = module._read_csv(prefilter_ref)
        matching_rows = [row for row in prefilter_rows if row.get("symbol") == ts_code]
        if len(matching_rows) != 1:
            raise PositionSourceError("POSITION25_PREFILTER_SYMBOL_ROW_MISMATCH")

        metric = module.metric_for_prefilter(matching_rows[0], prefilter_ref)
        if not isinstance(metric, dict):
            raise PositionSourceError("POSITION25_PREFILTER_METRIC_NOT_BOUND")
        if metric.get("status") != "VALID_USER_DEFINED_RANGE_POSITION":
            reason = metric.get("unknown_reason") or "PREFILTER_VALIDATION_REJECTED"
            raise PositionSourceError(f"POSITION25_PREFILTER_REJECTED:{reason}")
        value = metric.get(FIELD)
        if not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value < 0:
            raise PositionSourceError("POSITION25_PREFILTER_VALUE_INVALID")
        return metric

    @staticmethod
    def _verify_bound_file(binding: dict[str, Any], key: str, expected_sha256: str) -> None:
        entry = binding.get(key)
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise PositionSourceError(f"POSITION25_BINDING_PATH_MISSING:{key}")
        if entry.get("sha256") != expected_sha256:
            raise PositionSourceError(f"POSITION25_BINDING_MISMATCH:{key}.sha256")
        _read_verified(Path(entry["path"]), expected_sha256, key)

    def _read_rows(self, path: Path) -> dict[str, dict[str, str]]:
        data = _read_verified(path, self.positions_sha256, "positions_csv")
        text = data.decode("utf-8-sig")
        rows_by_symbol: dict[str, dict[str, str]] = {}
        with io.StringIO(text, newline="") as handle:
            reader = csv.DictReader(handle)
            required_fields = {
                "symbol",
                "name_asof_20261023",
                "asof",
                "metric_type",
                "formula",
                "zero_floor",
                "position_pct",
                "status",
                "price_basis",
                "price_asof",
                "source_generation",
            }
            if not reader.fieldnames or not required_fields.issubset(reader.fieldnames):
                raise PositionSourceError("POSITION25_CSV_SCHEMA_MISMATCH")
            for row in reader:
                symbol = row.get("symbol", "")
                if not symbol or symbol in rows_by_symbol:
                    raise PositionSourceError("POSITION25_CSV_DUPLICATE_OR_EMPTY_SYMBOL")
                if symbol not in EXPECTED_SYMBOLS:
                    raise PositionSourceError("POSITION25_CSV_CONTAINS_UNBOUND_SYMBOL")
                if (
                    row.get("asof") != ASOF
                    or row.get("metric_type") != METRIC_TYPE
                    or row.get("formula") != FORMULA
                    or row.get("zero_floor") != "0"
                    or row.get("status") != "VALID_USER_DEFINED_RANGE_POSITION"
                    or row.get("price_basis") != PRICE_BASIS
                    or row.get("price_asof") != ASOF
                    or row.get("source_generation") != SOURCE_GENERATION
                ):
                    raise PositionSourceError(f"POSITION25_ROW_BINDING_MISMATCH:{symbol}")
                try:
                    value = float(row["position_pct"])
                except (TypeError, ValueError) as error:
                    raise PositionSourceError(f"POSITION25_VALUE_INVALID:{symbol}") from error
                if not math.isfinite(value) or value < 0:
                    raise PositionSourceError(f"POSITION25_VALUE_INVALID:{symbol}")
                rows_by_symbol[symbol] = row

        if len(rows_by_symbol) != len(EXPECTED_SYMBOLS) or set(rows_by_symbol) != set(EXPECTED_SYMBOLS):
            raise PositionSourceError("POSITION25_CSV_COHORT_MISMATCH")
        return rows_by_symbol

    def _ready(
        self,
        ts_code: str,
        asof: str,
        row: dict[str, str],
        prefilter_metric: dict[str, Any],
    ) -> dict[str, Any]:
        value = float(prefilter_metric[FIELD])
        if value != float(row["position_pct"]):
            raise PositionSourceError("POSITION25_PREFILTER_VALUE_MISMATCH")
        return {
            "schema_version": "v4.research.zero_to_history_high_position.v1",
            "status": "READY",
            "ts_code": ts_code,
            "stock_name": row["name_asof_20261023"],
            "asof": asof,
            "source_asof": ASOF,
            "field": FIELD,
            FIELD: value,
            "basis": PRICE_BASIS,
            "formula": FORMULA,
            "metric_kind": METRIC_KIND,
            "history_scope": HISTORY_SCOPE,
            "summary": _DISPLAY_SUMMARY,
            "source": {
                "artifact": "25_ZERO_FLOOR_HIGH_POSITION.csv",
                "sha256": self.positions_sha256,
                "binding_sha256": self.bindings_sha256,
                "generation": SOURCE_GENERATION,
                "asof": ASOF,
            },
            "cannot_confirm": [],
            "write_policy": "read_only",
            "RESEARCH_ONLY": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
