from pathlib import Path
import time

from ops.research_storage_governance import unique_roots
from ops.research_storage_retention import under


def old_oracle(paths):
    roots = {Path(path) for path in paths}
    return {p for p in roots if not any(p != other and under(p, other) for other in roots)}


def test_unique_roots_exact_lexical_parent_semantics():
    cases = [[], ['/', '/a', '/a/b'], ['.', 'a', 'a/b', '../a', '../a/b'],
        ['/a/b', '/a/b', '/a/b2', '/a/c', '/a/b/../x'],
        [f'/delta/run/{i}/role/block.parquet' for i in range(100)] +
        ['/delta/run/5', '/unrelated', '/unrelated/a', 'relative/x', 'relative']]
    for paths in cases:
        assert unique_roots(paths) == old_oracle(paths)


def test_unique_roots_ten_thousand_logical_block_paths():
    paths = [f'/data/role/{i % 2}/run/stock/{i}/delta.parquet' for i in range(10000)]
    start = time.perf_counter()
    result = unique_roots(paths)
    elapsed = time.perf_counter() - start
    assert result == {Path(path) for path in paths}
    print(f'10000 distinct logical block roots: {elapsed:.6f}s')
