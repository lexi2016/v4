"""Targeted tests for an outcome-blind inventory and separate Table B audit."""
from pathlib import Path
import os
import unittest

from ops import act047a_kb47_audit as audit


class Act047AAuditTests(unittest.TestCase):
    def test_quadrants_keep_loss_rally_flat_watch_and_missing(self):
        values = [(audit.GOLD, -.1), (audit.GOLD, 0), (audit.GOLD, None),
                  (audit.REJECT, .1), (audit.REJECT, -.01), (audit.WATCH, .04)]
        rows = [dict(record_index=i, anon_id=str(i), master_verdict=l, result=v)
                for i, (l, v) in enumerate(values, 1)]
        r = audit.quadrant(rows, 'result', 5)
        self.assertEqual(r['counts'][audit.GOLD], dict(up=0, down=1, flat=1, missing=1, rally=0))
        self.assertEqual(r['counts'][audit.REJECT], dict(up=1, down=1, flat=0, missing=0, rally=1))
        self.assertEqual(r['counts'][audit.WATCH]['up'], 1)
        self.assertEqual([r['examples'][label][0]['record_index'] for label in (audit.GOLD, audit.REJECT)],
                         [1, 4])

    def test_active_anchor_must_precede_D_and_close_break_is_strict(self):
        r = dict(trade_date=20200102, D_open=10.2, D_close=9.5, D_pre_close=10.0,
                 D_zge_white_line=10.0, D_zge_yellow_line=10.0,
                 prior_active_anchor_date=20200101, prior_active_anchor_low=9.7)
        self.assertEqual(list(audit.hard_negatives(r, True).values()), [True, True, True])
        self.assertEqual(list(audit.hard_negatives({**r, 'D_close': 9.7}, True).values()),
                         [True, False, False])
        self.assertEqual(list(audit.hard_negatives({**r, 'prior_active_anchor_date': 20200102}, True).values()),
                         [True, None, None])

    def test_v11_reference_denominator_and_unknown_are_separate(self):
        row = dict(master_verdict=audit.GOLD, reviewer_count='2', master_primary_L1='25',
                   master_secondary_L1='[]', v11_candidate_25='FALSE', m25_eligible_state='UNKNOWN')
        for method in audit.L1:
            row.setdefault(f'v11_candidate_{method:02}', 'FALSE')
        r = audit.coverage([row])['ALL']
        b = {x['name']: x for x in r['branches']}
        self.assertEqual(r['frequencies']['25'], dict(primary=1, secondary=0, either=1))
        self.assertEqual(b['V11_25']['gold_ref'], dict(TRUE=0, FALSE=1, UNKNOWN=0))
        self.assertEqual(b['044A_25_eligible']['gold_ref'], dict(TRUE=0, FALSE=0, UNKNOWN=1))
        self.assertEqual(b['V11_05']['gold_ref'], dict(TRUE=0, FALSE=0, UNKNOWN=0))

    def test_m23_note_is_a_separate_review_flag(self):
        def row(note):
            return {'master_partial_or_candidate_notes': note}
        self.assertTrue(audit.m23_candidate_note(row('M23_L1_PARTIAL_FIXED_ANCHOR_NOTE')))
        self.assertTrue(audit.m23_candidate_note(row('OTHER|R4_23_PARTIAL_ONLY_DOWNGRADED')))
        self.assertFalse(audit.m23_candidate_note(row('M25_UNVERIFIED_SEC_MOVED_TO_NOTE')))

    def test_duplicate_keys_fail(self):
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_KEYS'):
            audit.index([{'k': 1}, {'k': 1}], lambda r: r['k'])

    @unittest.skipUnless(os.getenv('ACT047A_NATIVE') and os.getenv('ACT047A_SKELETON'),
                         'Sealed input paths required')
    def test_signed_original_roundtrip_and_no_gold_approval(self):
        native = Path(os.environ['ACT047A_NATIVE']).read_bytes()
        skeleton = Path(os.environ['ACT047A_SKELETON']).read_bytes()
        rows = audit.restore_closeout(native, skeleton)
        self.assertEqual(len(rows), 181)
        self.assertEqual(sum(r['master_verdict'] == audit.GOLD for r in rows), 41)
        self.assertTrue(all(r['training_gold_approved'].upper() == 'FALSE' for r in rows))
        self.assertEqual(audit.sha256(audit.csv_bytes(rows)).hexdigest(), audit.CLOSEOUT_SHA)
