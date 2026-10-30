"""Recovery and source-boundary regressions; no real historical evaluation."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('catchup_adapter', ROOT / 'ops/bootstrap_stock_event_history.py')
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


class Owner:
    GROUPS = ('original', 'nav_smallk', 'nav_pullback', 'nav_breakout')
    canonical = staticmethod(adapter.canonical)
    digest = staticmethod(lambda value: hashlib.sha256(adapter.canonical(value)).hexdigest())


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)
        self.states = dict.fromkeys(Owner.GROUPS, 'UNKNOWN')

    def tearDown(self):
        self.tmp.cleanup()

    def test_journal_recovery_and_crash_torn_last_block(self):
        journal = adapter.Journal(self.directory, {'source': 'bound'}, Owner.GROUPS)
        journal.add('20261027', self.states)
        journal.flush()
        with journal.path.open('ab') as stream:
            stream.write(b'{"partial":')
        recovered = adapter.Journal(self.directory, {'source': 'bound'}, Owner.GROUPS)
        self.assertEqual(recovered.values, {'20261027': self.states})
        recovered.add('20261028', dict(self.states, original='TRUE'))
        recovered.flush()
        again = adapter.Journal(self.directory, {'source': 'bound'}, Owner.GROUPS)
        self.assertEqual(len(again.values), 2)
        self.assertEqual(again.values['20261027']['original'], 'UNKNOWN')

    def test_journal_checks_chain_and_fixed_binding(self):
        journal = adapter.Journal(self.directory, {'source': 'bound'}, Owner.GROUPS)
        journal.add('20261027', self.states)
        journal.flush()
        with self.assertRaisesRegex(ValueError, 'BINDING_DRIFT'):
            adapter.Journal(self.directory, {'source': 'new'}, Owner.GROUPS)
        value = json.loads(journal.path.read_text())
        value['dates'][0][1]['original'] = 'TRUE'
        journal.path.write_bytes(adapter.canonical(value) + b'\n')
        with self.assertRaisesRegex(ValueError, 'HASH_CHAIN_DRIFT'):
            adapter.Journal(self.directory, {'source': 'bound'}, Owner.GROUPS)

    def test_journal_blocks_are_small_and_bounded(self):
        journal = adapter.Journal(self.directory, {'source': 'bound'}, Owner.GROUPS)
        for index in range(25):
            journal.add(str(20261001 + index), self.states)
        self.assertEqual(len(journal.pending), 0)
        self.assertEqual(len(journal.path.read_bytes().splitlines()), 1)
        self.assertLess(journal.path.stat().st_size, 6000)
        with self.assertRaisesRegex(ValueError, 'TRISTATE_INVALID'):
            journal.add('20261026', dict(self.states, original=None))

    def test_prefix_hashes_match_original_canonical_digest(self):
        bars = [dict(trade_date=20261026 + index, close=str(index + 1)) for index in range(4)]
        hashes = adapter.prefix_hashes(Owner, bars)
        self.assertEqual(hashes, {length: Owner.digest(bars[:length]) for length in range(1, 5)})

    def test_stale_cache_fails_instead_of_silent_reset(self):
        bars = [dict(trade_date=20261029, close='10')]
        identity = {'source': 'bound'}
        config = {'rule': 'frozen'}
        cache = dict(rule_sha256=adapter.RULE, source_identity=identity, rules_signature=Owner.digest(config),
            prefix_sha256=Owner.digest(bars), evaluations={'20261029': dict(source_identity=identity, groups=self.states)})
        adapter.validate_cache(Owner, cache, bars, identity, config)
        for field in ('rule_sha256', 'source_identity', 'rules_signature', 'prefix_sha256'):
            bad = copy.deepcopy(cache)
            bad[field] = 'drift'
            with self.assertRaises(ValueError):
                adapter.validate_cache(Owner, bad, bars, identity, config)

    def test_reference_drift_is_not_accepted(self):
        path = self.directory / 'source.json'
        reference = adapter.save(path, {'source': 1})
        self.assertEqual(adapter.load(reference), {'source': 1})
        path.write_text('{"source":2}')
        with self.assertRaisesRegex(ValueError, 'REFERENCE_DRIFT'):
            adapter.load(reference)

    def test_lazy_owner_rule_is_loaded_before_worker_cache_setup(self):
        _, _, paths = adapter.load_runtime()
        self.assertIn('domains.research_daily_product', sys.modules)
        self.assertEqual(Path(sys.modules['domains.research_daily_product'].__file__), paths['domains.research_daily_product'])

    def test_projection_dates_and_dimensions_fail_closed(self):
        projection = {'formula_result': dict(mode='prefix', field_count=51, drawing_count=22,
            rows=[dict(trade_date=20261029, ohlcv=dict(open='1', high='2', low='1', close='2', vol='10'))])}
        self.assertEqual(adapter.projection_bars(projection)[0]['close'], '2')
        projection['formula_result']['rows'].append(projection['formula_result']['rows'][0])
        with self.assertRaisesRegex(ValueError, 'DATE_CONFLICT'):
            adapter.projection_bars(projection)

    def test_retained_reader_strings_preserve_cache_digest(self):
        bar = dict(date='20261029', open=1., high=2., low=-1.1102230246251565e-15, close=2., volume=10.)
        source = {'source_generation': 'bound'}
        projection = dict(symbol='TEST.SZ', source=source, formula_result=dict(mode='prefix', field_count=51, drawing_count=22,
            rows=[dict(trade_date=20261029, ohlcv=dict(open='1.0', high='2.0', low='-1.1102230246251565E-15', close='2.0', vol='10.0'))]))
        _, bars = adapter.retained_sample(projection, dict(source=source, samples=[dict(symbol='TEST.SZ', bars=[bar])]))
        self.assertEqual(bars[0]['low'], str(bar['low']))
        bad = copy.deepcopy(projection)
        bad['formula_result']['rows'][0]['ohlcv']['close'] = '3.0'
        with self.assertRaisesRegex(ValueError, 'PRICE_PARITY_FAILED'):
            adapter.retained_sample(bad, dict(source=source, sample=dict(symbol='TEST.SZ', bars=[bar])))

    def test_original_pure_cache_all_prefixes_and_window_boundaries(self):
        rule_spec = importlib.util.spec_from_file_location('frozen_original_rule', ROOT / 'domains/research_daily_product.py')
        rule = importlib.util.module_from_spec(rule_spec)
        rule_spec.loader.exec_module(rule)
        bars, formula = [], []
        for index in range(65):
            price = str(10 + index % 7)
            bars.append(dict(trade_date=20260000 + index + 1, open='10', high='20', low='8', close=price,
                vol='0' if index == 20 else str(1000 + index * 100)))
            formula.append({'values': {'突破': None if index < 3 else index % 13 == 0}})
        bars[40]['low'] = '-0.0001'
        cached = adapter.PurePrefixCache(rule, bars, formula)
        for length in range(1, 66):
            original_rows = cached.original_normalize(cached.parsed[:length])
            rows = cached.normalize(cached.parsed[:length])
            self.assertEqual(rows, original_rows)
            self.assertEqual(cached.fund_keys(rows, cached.breakout[:length]), cached.original_fund_keys(original_rows, cached.breakout[:length]))
        bad = copy.deepcopy(cached.parsed[:41])
        bad[20]['c'] = '99'
        with self.assertRaisesRegex(ValueError, 'NORMALIZE_PREFIX_DRIFT'):
            cached.normalize(bad)
        with self.assertRaisesRegex(ValueError, 'FUND_KEYS_PREFIX_DRIFT'):
            cached.fund_keys(cached.normalized[:41], [True] * 41)


if __name__ == '__main__':
    unittest.main()
