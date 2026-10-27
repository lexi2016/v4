"""Batch-only checks: source dating, top-10 censoring, deltas and CAS evidence."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('watch', Path(__file__).parents[1] / 'scripts/qunhe_20261027_watch.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


def row(name='高盛', net=-1000, total=2000, cash=6000, when='10:00:00', realtime=True):
    return dict(broker_name=name, net_vol=net, total_vol=total, total_turnover=cash, avg_price=3,
                is_real_time=realtime, data_time_str=w.DAY + ' ' + when)


class Frame:
    def __init__(self, rows):
        self.rows = rows

    def to_json(self, **kwargs):
        return json.dumps(self.rows)


class Quote:
    def __init__(self, rows, when='10:00:00', volume=100000):
        self.rows, self.when, self.volume = rows, when, volume
        self.days = []

    def get_market_snapshot(self, codes):
        return 0, Frame([dict(update_time=w.DAY + ' ' + self.when, volume=self.volume,
                              turnover=self.volume * 3.1, last_price=3.1)])

    def get_top_ten_buy_sell_brokers(self, code, days_before):
        self.days.append(days_before)
        return 0, Frame(self.rows)


class WatchTests(unittest.TestCase):
    def test_gross_and_trade_vwap_not_sale_price(self):
        a = w.decode(row())
        b = w.decode(row(net=-1200, total=3000, cash=9400))
        self.assertEqual((a['buy_vol'], a['sell_vol'], a['one_way_ratio']), (500, 1500, .5))
        d = w.delta_metrics(a, b, 2)
        self.assertEqual(d['delta_sell_vol'], 600)
        self.assertEqual(d['gross_sell_per_min'], 300)
        self.assertEqual(d['marginal_exec_price'], 3.4)
        self.assertEqual(w.delta_metrics(b, a, 1)['delta_status'], 'SOURCE_REVISION_NON_MONOTONIC')
        with self.assertRaises(ValueError):
            w.decode(row(net=-3000, total=2000))

    def test_false_or_other_day_never_current(self):
        self.assertTrue(w.current_brokers([row()]))
        self.assertFalse(w.current_brokers([row(realtime=False)]))
        self.assertFalse(w.current_brokers([dict(row(), data_time_str='2026-10-26 16:00:00')]))
        self.assertFalse(w.current_brokers([]))

    @patch.object(w, 'BASE', Path(__file__))
    @patch.object(w, 'FRIDAY', Path(__file__))
    def test_drop_retains_gross_and_signed_bounds_and_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            rows = [row(name='买' + str(i), net=i * 100, total=2000) for i in range(1, 11)]
            rows += [row(name='高盛' if i == 10 else '卖' + str(i), net=-i * 100, total=2000) for i in range(1, 11)]
            with patch.object(w, 'now', return_value=w.parse(w.DAY + ' 10:00:01')):
                watch = w.Watch(folder)
                watch.q = Quote(rows)
                watch.capture()
            rows2 = [dict(r, data_time_str=w.DAY + ' 10:01:00', broker_name='新卖10' if r['broker_name'] == '高盛' else r['broker_name']) for r in rows]
            with patch.object(w, 'now', return_value=w.parse(w.DAY + ' 10:01:01')):
                watch.q = Quote(rows2, '10:01:00', 101000)
                result = watch.capture()
            gs = next(r for r in result['tracked'] if r['broker_name'] == '高盛')
            self.assertEqual(gs['status'], 'DROPPED_FROM_TOP10')
            self.assertEqual(gs['last_known_sell_vol'], 1500)
            self.assertEqual(gs['net_lower_bound'], -100)
            self.assertEqual(gs['net_upper_bound'], 100)
            self.assertEqual(watch.q.days, [0])
            watch.lock.close()
            restarted = w.Watch(folder)
            self.assertEqual(restarted.known['高盛']['row']['sell_vol'], 1500)
            restarted.lock.close()

    def test_cas_requires_auction_not_clock_alone(self):
        close = w.parse(w.DAY + ' 16:10:00')
        market = dict(update_time=w.DAY + ' 16:08:03')
        auction = [dict(type='AUCTION', time=w.DAY + ' 16:08:03')]
        self.assertEqual(w.cas_status(close, market, [], w.DAY + ' 16:10:00')['market_status'], 'POST_CAS_NOT_CONFIRMED')
        result = w.cas_status(close, market, auction, w.DAY + ' 16:00:00')
        self.assertEqual(result['market_status'], 'FINAL_POST_CAS')
        self.assertEqual(result['broker_cas_status'], 'CAS_BROKER_COVERAGE_UNVERIFIED')

    def test_schedule_and_partial_bounds(self):
        slots = w.eligible_minutes()
        self.assertEqual(slots[0].strftime('%H:%M:%S'), '09:15:00')
        self.assertEqual(slots[-1].strftime('%H:%M:%S'), '16:10:30')
        self.assertTrue(any(x.strftime('%H:%M') == '16:00' for x in slots))
        self.assertTrue(all(not ('12:02' <= x.strftime('%H:%M') < '13:00') for x in slots))
        self.assertIsNone(w.top10_bounds([row()])['net_lower_bound'])
        self.assertFalse(w.clean_quality({'quality': ['BROKER_STALE_OVER_120S']}))


if __name__ == '__main__':
    unittest.main()
