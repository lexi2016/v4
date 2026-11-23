"""Clean NumPy fixed-parameter transform appendix; no estimator or fit step.

Inspired by published MiniRocket/MultiRocket transform descriptions. This is
not upstream MultiRocket, does not vendor GPL code and is not numerically or
statistically comparable to its fitted transform. Biases/channel combinations
are fixed before observing any data, and all seven channels are transformed
individually (no learned or random channel sums).
"""
from __future__ import annotations

from itertools import combinations
import hashlib
import resource
import sys
import time
from typing import Any

import numpy as np

VERSION = "ACT021_NUMPY_FIXED_TRANSFORM_V1"
SEED = 20261123
DILATIONS = (1, 2, 4)
BIASES = (-.5, 0., .5)
OPERATORS = ("PPV", "MEAN_POSITIVE", "MEAN_POSITIVE_INDEX", "LONGEST_POSITIVE_STRETCH")
CHANNELS = ("open_prevclose", "high_prevclose", "low_prevclose", "close_prevclose",
            "volume_prior5", "close_white_deviation", "close_yellow_deviation")


def kernels() -> np.ndarray:
    result = np.full((84, 9), -1., dtype=np.float64)
    for i, positions in enumerate(combinations(range(9), 3)):
        result[i, list(positions)] = 2.
    return result


def channels(frame: Any) -> np.ndarray:
    """60 observations from at least 65 real bars; no padding/imputation here."""
    values = frame.loc[:, ["open", "high", "low", "close", "vol", "zge_white_line", "zge_yellow_line"]].to_numpy(dtype=float)
    if len(values) < 65 or not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("TRANSFORM_REQUIRES_65_VALID_BARS")
    prev = values[:-1, 3]
    ohlc = values[1:, :4] / prev[:, None] - 1
    volume = np.array([values[i, 4] / values[i-5:i, 4].mean() for i in range(5, len(values))])
    result = np.column_stack([ohlc[4:], volume,
                              values[5:, 3]/values[5:, 5]-1,
                              values[5:, 3]/values[5:, 6]-1])[-60:]
    if result.shape != (60, 7) or not np.isfinite(result).all():
        raise ValueError("TRANSFORM_NONFINITE_OR_SHAPE")
    return result.T


def _pool(convolution: np.ndarray, bias: float) -> np.ndarray:
    z = convolution-bias
    positive = z > 0
    count = positive.sum(axis=-1)
    denom = np.maximum(count, 1)
    ppv = count/z.shape[-1]
    mean = np.where(positive, z, 0.).sum(axis=-1)/denom
    # Zero-based index normalized to [0,1]; -1 explicitly marks no positives.
    index = np.where(count > 0, (positive*np.arange(z.shape[-1])).sum(axis=-1)/denom/max(z.shape[-1]-1, 1), -1.)
    run = np.zeros(z.shape[:-1], dtype=np.int32)
    longest = np.zeros_like(run)
    for j in range(z.shape[-1]):
        run = np.where(positive[..., j], run+1, 0)
        longest = np.maximum(longest, run)
    return np.stack([ppv, mean, index, longest/z.shape[-1]], axis=-1)


def transform(batch: np.ndarray) -> np.ndarray:
    """(N,7,60) -> (N,84672), fixed raw/difference/kernel/dilation/pad/bias pools.

    Peak temporary memory is bounded per dilation and sample; no fit, labels,
    training set, empirically selected thresholds or outcome enters this API.
    """
    x = np.asarray(batch, dtype=np.float64)
    if x.ndim != 3 or x.shape[1:] != (7, 60) or not np.isfinite(x).all():
        raise ValueError("EXPECTED_FINITE_N_7_60")
    k = kernels()
    # A seeded permutation fixes feature order only, independent of observations.
    order = np.random.default_rng(SEED).permutation(len(k))
    k = k[order]
    features = []
    for sample in x:
        parts = []
        for values in (sample, np.diff(sample, axis=-1)):
            for dilation in DILATIONS:
                span = 8*dilation+1
                for padded in (False, True):
                    work = np.pad(values, ((0, 0), (span//2, span//2))) if padded else values
                    windows = np.lib.stride_tricks.sliding_window_view(work, span, axis=-1)[..., ::dilation]
                    conv = np.einsum("ctj,kj->ckt", windows, k, optimize=False)
                    for bias in BIASES:
                        parts.append(_pool(conv, bias).ravel())
        features.append(np.concatenate(parts))
    width = 2*7*84*len(DILATIONS)*2*len(BIASES)*len(OPERATORS)
    return np.stack(features) if features else np.empty((0, width), dtype=np.float64)


def benchmark(batch: np.ndarray) -> dict[str, Any]:
    """First call cold in-process and second warm; ru_maxrss is process lifetime."""
    first = time.perf_counter()
    cold = transform(batch)
    cold_seconds = time.perf_counter()-first
    first = time.perf_counter()
    warm = transform(batch)
    warm_seconds = time.perf_counter()-first
    checksum = lambda a: hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {"variant": VERSION, "seed": SEED, "fit_count": 0,
            "cold_definition": "first transform call in this process; imports and input construction excluded",
            "cold_wall_seconds": cold_seconds, "warm_wall_seconds": warm_seconds,
            "peak_rss_bytes": int(rss if sys.platform == "darwin" else rss*1024),
            "peak_rss_scope": "whole process lifetime high-water mark, including input and both outputs",
            "input_shape": list(batch.shape), "output_shape": list(cold.shape),
            "input_sha256": checksum(batch), "output_sha256": checksum(cold),
            "deterministic": bool(np.array_equal(cold, warm)), "channels": CHANNELS,
            "dilations": DILATIONS, "biases": BIASES, "operators": OPERATORS,
            "kernels": {"count": 84, "length": 9, "positive_weights": 3, "positive_value": 2, "negative_value": -1},
            "representations": ["raw", "first_difference"], "padding": ["valid", "symmetric_zero_same"],
            "comparability": "engineering fixed-bias variant only; not fitted upstream MiniRocket/MultiRocket accuracy or speed equivalence",
            "upstream_references": ["https://github.com/ChangWeiTan/MultiRocket", "https://arxiv.org/abs/2102.00457"],
            "operator_definitions": {"PPV":"fraction convolution > fixed bias", "MEAN_POSITIVE":"mean bias-subtracted positive response", "MEAN_POSITIVE_INDEX":"mean zero-based positive index divided by length-1", "LONGEST_POSITIVE_STRETCH":"longest consecutive positive run divided by response length"},
            "no_positive_convention": {"PPV": 0, "MEAN_POSITIVE": 0, "MEAN_POSITIVE_INDEX": -1, "LONGEST_POSITIVE_STRETCH": 0}}
