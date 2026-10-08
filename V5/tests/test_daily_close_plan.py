"""Scheduling decisions reuse the frozen market calendars; planning executes nothing."""
import unittest

class DailyClosePlanTests(unittest.TestCase):
    def plan(self, now):
        from v5_shadow.daily_close_plan import plan_close_day
        result=plan_close_day(now)
        self.assertFalse(result['execution_performed'])
        self.assertFalse(result['natural_verified'])
        return {row['market']:row for row in result['jobs']}
    def test_hk_open_when_a_and_connect_closed(self):
        rows=self.plan('2026-10-07T08:11:00+00:00')
        self.assertEqual(rows['HK']['status'],'DUE');self.assertEqual(rows['A']['status'],'NON_TRADING_DAY')
        self.assertEqual(rows['HK']['connect_state'],'NON_TRADING_DAY')
    def test_oct8_independent_close_times(self):
        rows=self.plan('2026-10-08T07:31:00+00:00')
        self.assertEqual(rows['A']['status'],'DUE');self.assertEqual(rows['HK']['status'],'WAITING_TIME')
        self.assertEqual(rows['HK']['scheduled_at'],'2026-10-08T16:10:00+08:00')
    def test_half_day_uses_hk_noon_close(self):
        rows=self.plan('2026-12-24T04:11:00+00:00')
        self.assertEqual(rows['HK']['scheduled_at'],'2026-12-24T12:10:00+08:00')
        self.assertEqual(rows['HK']['status'],'DUE')
        self.assertEqual(rows['A']['status'],'WAITING_TIME')
    def test_utc_day_not_used_as_target_day(self):
        rows=self.plan('2026-10-07T17:00:00+00:00')
        self.assertTrue(all(r['target_date']=='20261008' for r in rows.values()))
        self.assertTrue(all(r['status']=='WAITING_TIME' for r in rows.values()))
    def test_outside_frozen_calendar_blocks(self):
        rows=self.plan('2027-01-04T09:00:00+00:00')
        self.assertTrue(all(r['status']=='CALENDAR_UNKNOWN' for r in rows.values()))
    def test_naive_time_rejected(self):
        with self.assertRaises(ValueError):self.plan('2026-10-08T16:11:00')
    def test_job_identity_stable_across_ticks(self):
        left=self.plan('2026-10-08T08:11:00+00:00');right=self.plan('2026-10-08T08:12:00+00:00')
        self.assertEqual(left['HK']['job_key'],right['HK']['job_key'])
        self.assertNotEqual(left['HK']['job_key'],left['A']['job_key'])
    def test_next_day_has_different_identity(self):
        left=self.plan('2026-10-08T08:11:00+00:00');right=self.plan('2026-10-09T08:11:00+00:00')
        self.assertNotEqual(left['HK']['job_key'],right['HK']['job_key'])
    def test_predeadline_not_due(self):
        rows=self.plan('2026-10-08T08:09:59+00:00');self.assertEqual(rows['HK']['status'],'WAITING_TIME')
        rows=self.plan('2026-10-08T08:10:00+00:00');self.assertEqual(rows['HK']['status'],'DUE')
    def test_plan_is_not_a_success_receipt(self):
        rows=self.plan('2026-10-08T08:11:00+00:00')
        self.assertTrue(all(r['input_admission']=='NOT_CHECKED' for r in rows.values()))
        self.assertTrue(all(r['run_status']=='NOT_RUN' for r in rows.values()))

if __name__=='__main__':unittest.main()
