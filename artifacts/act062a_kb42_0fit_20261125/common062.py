"""Frozen ACT-062A inputs, reproducible identity checks, and bounded measurements."""
from __future__ import annotations

import json
from hashlib import file_digest, sha256
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
from time import perf_counter, process_time

import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent
WORKSPACE = Path.home() / "Desktop/学习"
ART = WORKSPACE / "v4_app/artifacts"
BATCHES = WORKSPACE / "Z哥方法论/research_batches"
ACT061 = ART / "act061a_kb42_exit_20261125"
ACT058 = ART / "act058a_hidden_kb42_20261125"
ACT057 = ART / "act057_local_kb42_20261125"
ACT056 = ART / "act056a_e7b_kb41_20261125"
ACT050 = ART / "pft_act050_kb47_20261125"
ACT046 = ART / "act046_strict_pit_20261124"
ACT053 = ART / "act053_e6_20261124"
ACT024 = BATCHES / "ACT024_CODEX_1Y_LIQUID_BRIDGE_20261123/delivery"
ACT034 = BATCHES / "ACT034_CODEX_E3_ADD10_GATE_AND_24FIT_20261123/delivery"
ACT037 = BATCHES / "ACT037_F01_CODEX_BACKFILL_20261124/delivery"
BASE = "96a5efe0d2ea70aa89b0e66f5662250c95246fdc"
NAMES = {
    "report": "ACT062A_KB42_DICT_BLIND_FLAGSHIP_REPORT.md",
    "dictionary": "ACT062A_KB42_TAG_DICTIONARY_V1.csv",
    "blind": "ACT062A_BLIND_TRUNCATED_PACK.zip",
    "reveal": "ACT062A_BLIND_REVEAL_KEY.csv",
    "recon": "ACT062A_KB42_VS_FLAGSHIP_120D_RECON.csv",
}
GOV = dict(model_fit=0, preprocess_fit=0, cluster_fit=0, model_load=0, predictions=0,
           new_scoring=0, tuning=0, simulated_trades=0, slippage_nav_replay=0,
           orders=0, production_writes=0, cumulative_research_FIT=291, RESEARCH_ONLY=True,
           STRICT_PIT=0, TRAIN_ADMITTED=0, NO_GO_BLOCKED=True, production_allowed=False,
           orders_sent=False, buy_gate_updated=False, knowledge_base_training_complete=False)


def module(name, path):
    spec = spec_from_file_location(name, path)
    m = module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def stamp(path):
    with path.open("rb") as f:
        checksum = file_digest(f, "sha256").hexdigest()
    return dict(path=str(path), bytes=path.stat().st_size, sha256=checksum)


def digest(payload):
    return dict(bytes=len(payload), sha256=sha256(payload).hexdigest())


class Usage:
    def __init__(self):
        self.start = self.mark = perf_counter()
        self.cpu_start = self.cpu_mark = process_time()
        self.wall = {}
        self.cpu = {}
        self.sources = {}
        self.direct_read_bytes = 0
        self.projected_decoded_bytes = 0
        self.write_bytes = 0
        self.reader_accounting = []

    def point(self, stage):
        now, cpu = perf_counter(), process_time()
        self.wall[stage] = round(now - self.mark, 6)
        self.cpu[stage] = round(cpu - self.cpu_mark, 6)
        self.mark, self.cpu_mark = now, cpu
        print(f"{stage} {self.wall[stage]:.3f}s", flush=True)

    def pin(self, path, expected=None):
        identity = stamp(path)
        self.direct_read_bytes += identity["bytes"]
        if expected is not None:
            assert identity["sha256"] == expected["sha256"], path
            if expected.get("bytes") is not None:
                assert identity["bytes"] == int(expected["bytes"]), path
        self.sources[str(path)] = identity
        return identity

    def read(self, path):
        data = path.read_bytes()
        self.direct_read_bytes += len(data)
        self.sources[str(path)] = dict(path=str(path), **digest(data))
        return data

    def json(self, path):
        return json.loads(self.read(path))

    def csv(self, path, columns=None, **options):
        from io import BytesIO
        return pd.read_csv(BytesIO(self.read(path)), usecols=columns, low_memory=False, **options)

    def parquet(self, path, columns, expected, *, filters=None):
        self.pin(path, expected)
        data = pq.read_table(path, columns=columns, filters=filters)
        self.projected_decoded_bytes += data.nbytes
        return data.to_pandas()

    def write(self, path, contents):
        with path.open("xb") as f:
            f.write(contents)
        self.write_bytes += len(contents)


def csv_payload(frame):
    return frame.to_csv(index=False, lineterminator="\n").encode("utf-8")
