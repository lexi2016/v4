"""Daily close slots: planning never certifies inputs or executes a workload."""
import unittest


class DailyClosePlanTests(unittest.TestCase):
    def plan(self, now):
        from v5_shadow.daily_close_plan import plan_close_day
        result = plan_close_day(now)
        self.assertFalse(result['execution_performed'])
        self.assertFalse(result['natural_verified'])
        return result['jobs']

    def row(self, now, market, slot):
        return next(r for r in self.plan(now) if r['market'] == market and r['slot'] == slot)

    def test_hk_open_when_a_and_connect_closed(self):
        rows = self.plan('2026-10-07T08:11:00+00:00')
        self.assertTrue(all(r['status'] == 'NON_TRADING_DAY' for r in rows if r['market'] == 'A'))
        hk = next(r for r in rows if r['market'] == 'HK')
        self.assertEqual(hk['status'], 'DUE')
        self.assertEqual(hk['connect_state'], 'NON_TRADING_DAY')

    def test_data_floor_is_not_trigger(self):
        rows = self.plan('2026-10-08T07:31:00+00:00')
        self.assertTrue(all(r['status'] == 'WAITING_TIME' for r in rows))
        a = next(r for r in rows if r['market'] == 'A')
        self.assertEqual(a['scheduled_at'], '2026-10-08T16:05:00+08:00')

    def test_a_slots_are_separate(self):
        rows = self.plan('2026-10-08T08:06:00+00:00')
        a = [r for r in rows if r['market'] == 'A']
        self.assertEqual([r['slot'] for r in a], ['1605', '1710'])
        self.assertEqual([r['status'] for r in a], ['DUE', 'WAITING_TIME'])
        self.assertNotEqual(a[0]['job_key'], a[1]['job_key'])
        self.assertEqual(a[0]['logical_run_key'], a[1]['logical_run_key'])
        self.assertEqual(a[1]['input_admission'], 'NOT_CHECKED')

    def test_second_slot_is_not_automatically_successful(self):
        row = self.row('2026-10-08T09:10:00+00:00', 'A', '1710')
        self.assertEqual(row['status'], 'DUE')
        self.assertEqual(row['run_status'], 'NOT_RUN')

    def test_half_day_does_not_invent_trigger(self):
        rows = self.plan('2026-12-24T04:11:00+00:00')
        hk = next(r for r in rows if r['market'] == 'HK')
        self.assertEqual(hk['status'], 'SCHEDULE_BINDING_UNVERIFIED')
        self.assertIsNone(hk['scheduled_at'])
        self.assertEqual(hk['market_state'], 'HALF_TRADING_DAY_AM')
        self.assertTrue(all(r['status'] == 'WAITING_TIME' for r in rows if r['market'] == 'A'))

    def test_utc_day_not_used_as_target_day(self):
        rows = self.plan('2026-10-07T17:00:00+00:00')
        self.assertTrue(all(r['target_date'] == '20261008' for r in rows))
        self.assertTrue(all(r['status'] == 'WAITING_TIME' for r in rows))

    def test_outside_frozen_calendar_blocks(self):
        rows = self.plan('2027-01-04T09:00:00+00:00')
        self.assertTrue(all(r['status'] == 'CALENDAR_UNKNOWN' for r in rows))
        self.assertTrue(all(r['scheduled_at'] is None for r in rows))

    def test_naive_time_rejected(self):
        with self.assertRaises(ValueError):
            self.plan('2026-10-08T16:11:00')

    def test_job_identity_stable_across_ticks(self):
        left = self.plan('2026-10-08T08:11:00+00:00')
        right = self.plan('2026-10-08T08:12:00+00:00')
        self.assertEqual([r['job_key'] for r in left], [r['job_key'] for r in right])
        self.assertEqual(len({r['job_key'] for r in left}), 3)

    def test_next_day_has_different_identity(self):
        left = self.row('2026-10-08T08:11:00+00:00', 'HK', '1610')
        right = self.row('2026-10-09T08:11:00+00:00', 'HK', '1610')
        self.assertNotEqual(left['job_key'], right['job_key'])
        self.assertNotEqual(left['logical_run_key'], right['logical_run_key'])

    def test_hk_deadline_inclusive(self):
        left = self.row('2026-10-08T08:09:59+00:00', 'HK', '1610')
        right = self.row('2026-10-08T08:10:00+00:00', 'HK', '1610')
        self.assertEqual(left['status'], 'WAITING_TIME')
        self.assertEqual(right['status'], 'DUE')

    def test_plan_is_not_a_success_receipt(self):
        rows = self.plan('2026-10-08T10:11:00+00:00')
        self.assertTrue(all(r['input_admission'] == 'NOT_CHECKED' for r in rows))
        self.assertTrue(all(r['run_status'] == 'NOT_RUN' for r in rows))
        self.assertTrue(all(r['deduplication_checked'] is False for r in rows))

    def test_weekend_is_not_due(self):
        rows = self.plan('2026-10-10T10:11:00+00:00')
        self.assertTrue(all(r['status'] == 'NON_TRADING_DAY' for r in rows))

    def test_source_identity_is_returned(self):
        from v5_shadow.daily_close_plan import plan_close_day
        value = plan_close_day('2026-10-08T10:11:00+00:00')
        self.assertEqual(value['schedule_source_sha256'], '7389cae30de08cf68c31e5b0bb6f5b17fead403366946496b7a4de148229d0ef')
        self.assertEqual(len(value['calendar_source_sha256']), 64)
        self.assertEqual(value['schema_version'], 'v5.daily_close_plan.v1')


if __name__ == '__main__':
    unittest.main()
