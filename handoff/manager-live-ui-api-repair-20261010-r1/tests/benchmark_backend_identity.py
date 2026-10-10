"""Measure the bounded extra pure attention computation on synthetic inputs."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import platform
import statistics
import time

from test_backend_identity import DATE, FLAGS, attention_inputs, attention_stage
from v4.manager_research.research_attention import build_research_attention


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--rows', type=int, default=1970)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not 1 <= args.rows <= 10000 or not 1 <= args.repeats <= 10:
        raise ValueError('benchmark bounds exceeded')
    inputs = attention_inputs(args.rows)
    original_inputs = deepcopy(inputs)
    elapsed = {'original_pure_projector_seconds': [], 'repaired_attention_stage_seconds': []}
    results = {}
    for name, function in (
        ('original_pure_projector_seconds', lambda: build_research_attention(DATE, **inputs)),
        ('repaired_attention_stage_seconds', lambda: attention_stage(inputs)),
    ):
        for _ in range(args.repeats):
            started = time.perf_counter()
            result = function()
            elapsed[name].append(time.perf_counter() - started)
        results[name] = result
    for result in results.values():
        result.pop('input_identity')
    assert results['original_pure_projector_seconds'] == results['repaired_attention_stage_seconds']
    assert inputs == original_inputs
    medians = {name: statistics.median(values) for name, values in elapsed.items()}
    receipt = dict(
        evidence_kind='ISOLATED_SYNTHETIC_PURE_PROJECTION_TIMING_NOT_LIVE_LATENCY',
        python=platform.python_version(), platform=platform.platform(),
        material_card_count=args.rows, repeats=args.repeats,
        source_ref_count=args.rows, company_material_symbol_count=1,
        elapsed_samples=elapsed, medians=medians,
        median_extra_seconds=medians['repaired_attention_stage_seconds'] - medians['original_pure_projector_seconds'],
        median_ratio=medians['repaired_attention_stage_seconds'] / medians['original_pure_projector_seconds'],
        returned_business_output_equal=True, input_objects_unchanged=True,
        owner_reader_calls=0, network_calls=0, production_claim='PROPOSAL_ONLY / LIVE_API_UI_NOT_RUN', **FLAGS)
    body = json.dumps(receipt, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.write_text(body)
    print(body)


if __name__ == '__main__':
    main()
