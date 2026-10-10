"""Actual admitted-card research-attention identity regression, all data synthetic."""
from copy import deepcopy
import unittest
from test_plan_semantic_identity import material, DATE, CUTOFF, FLAGS
from v4.manager_research.research_attention import build_research_attention


def card():
    row = material()
    row.update(card_id='synthetic-card', symbol='HK.00001', name='Synthetic issuer',
        semantic_status='ACCEPTED', published_at='2026-10-08T16:00:00+08:00',
        retrieved_at='2026-10-08T17:00:00+08:00', available_at='2026-10-08T17:00:00+08:00')
    return row


def attention(row):
    return build_research_attention(DATE,
        context=dict(plan_trade_date=DATE, research_cutoff=CUTOFF,
            focus_window_start='2026-10-07T16:00:00+08:00'),
        market_screen={}, stocks=[], material_cards=[row], themes=[],
        announcement_observation={'status': 'NOT_RUN'}, us_market={'status': 'CANNOT_CONFIRM'})


class AttentionIdentityRegression(unittest.TestCase):
    def test_admitted_card_global_registry_change_does_not_invalidate_attention(self):
        before = card()
        after = deepcopy(before)
        after['source_refs'][0]['manifest_sha256'] = 'e' * 64
        a, b = attention(before), attention(after)
        self.assertEqual(len(a['cards']), 1, 'Fixture must exercise actual admitted evidence.')
        self.assertEqual(len(b['cards']), 1)
        self.assertEqual(a['input_identity'], b['input_identity'])
        for key, value in FLAGS.items():
            self.assertIs(b[key], value)
            self.assertIs(b['cards'][0][key], value)
        self.assertEqual(before['source_refs'][0]['manifest_sha256'], 'c' * 64)
        self.assertEqual(after['source_refs'][0]['manifest_sha256'], 'e' * 64)

    def test_consumed_card_payload_receipt_and_availability_still_invalidate(self):
        base = card()
        expected = attention(base)['input_identity']
        for field in ('payload_sha256', 'receipt_sha256', 'available_at'):
            with self.subTest(field=field):
                changed = deepcopy(base)
                if field == 'available_at':
                    changed[field] = '2026-10-08T18:00:00+08:00'
                else:
                    changed['source_refs'][0][field] = '9' * 64
                self.assertNotEqual(expected, attention(changed)['input_identity'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
