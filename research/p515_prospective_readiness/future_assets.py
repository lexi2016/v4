"""Exact-byte V1 source bridge. No prediction or model asset is opened on import."""
from __future__ import annotations

from dataclasses import dataclass
import builtins
from pathlib import Path
from types import ModuleType

from .drive_store import sha256_bytes

V1_INFERENCE_SOURCE_SHA256 = "dfcc6a64ee00952ea4fe145d90256a1b680bcaf1eaff252aca427fab18138290"
V1_IO_GUARD_SOURCE_SHA256 = "1409cc63a13861234ba045cf8f88d6e6c650e5798c8791b2e4104727d224d212"
MODEL_SHA256 = "68b3391542330b0b847e3c8c847f4bebef79e6bd9955fb5051ef90214f03b217"
SCALER_SHA256 = "e63cbcdff0bda3b67c9c98ef1db1223f3ab68ef3b9d332d6b8bedabdc79f825b"
PARAMS_SHA256 = "8545969bc7c11e0bb91c6ded82d4411428089654518df10d97368314d0f24949"


def _require(raw, expected, label):
    if not isinstance(raw, bytes) or sha256_bytes(raw) != expected:
        raise ValueError(f"V1 frozen {label} bytes mismatch")
    return raw


@dataclass(frozen=True)
class V1SourceAssets:
    inference_code: bytes
    guard_code: bytes

    def __post_init__(self):
        _require(self.inference_code, V1_INFERENCE_SOURCE_SHA256, "inference source")
        _require(self.guard_code, V1_IO_GUARD_SOURCE_SHA256, "guard source")

    def load_guard(self):
        guard = ModuleType("non_overwrite_io_guard_patch_v2")
        exec(compile(self.guard_code, "<pinned V1 file guard>", "exec"), vars(guard))
        return guard

    def load_inference(self):
        guard = self.load_guard()

        def import_pinned(name, globals=None, locals=None, fromlist=(), level=0):
            if name == guard.__name__ and level == 0:
                return guard
            return builtins.__import__(name, globals, locals, fromlist, level)

        inference = ModuleType("p515_pinned_prospective_inference_v1")
        inference.__dict__["__builtins__"] = dict(vars(builtins), __import__=import_pinned)
        exec(compile(self.inference_code, "<pinned V1 future inference>", "exec"), vars(inference))
        return inference


@dataclass(frozen=True)
class FrozenV1Predictor:
    """Future-only adapter. The coordinator must run its real gates before invoking it."""

    sources: V1SourceAssets
    model_path: Path
    scaler_path: Path
    params_path: Path

    def __call__(self, daily, eligible_rows, *, append_call):
        from .coordinator import FEATURE_NAMES

        rows = tuple(sorted(eligible_rows, key=lambda row: row.rank))
        if not rows or daily.synthetic_fixture:
            raise ValueError("real nonempty sealed input required")
        asset_blobs = (
            _require(self.model_path.read_bytes(), MODEL_SHA256, "model"),
            _require(self.scaler_path.read_bytes(), SCALER_SHA256, "scaler"),
            _require(self.params_path.read_bytes(), PARAMS_SHA256, "parameter"),
        )
        model_call = self.sources.load_inference().future_predict_paired
        u, c, _ = model_call(tuple(row.features for row in rows), FEATURE_NAMES,
                             *asset_blobs, append_call=append_call)
        return [{"rank": row.rank, "ts_code": row.ts_code, "arm": arm, "probability": float(value)}
                for arm, values in (("U", u), ("C", c)) for row, value in zip(rows, values, strict=True)]
