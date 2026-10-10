"""Actual daily mapping cutoff admission; synthetic saved reader returns only."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_plan_semantic_identity import W, DATE, CUTOFF, FLAGS
from v4.manager_research import us_mapping_research


class MappingCutoffIdentity(unittest.TestCase):
    def test_after_cutoff_daily_artifact_is_not_added_to_plan_identity(self):
        for stamp, state, expected_count in (
                ('2026-10-10T08:59:00+08:00', 'CONSUMED', 1),
                ('2026-10-10T09:01:00+08:00', 'NOT_CONSUMED_AFTER_CUTOFF', 0)):
            with self.subTest(available_at=stamp):
                saved = dict(daily_run=dict(status='VALID_EMPTY', target_trade_date=DATE,
                    run_id='4' * 32, generated_at=stamp, artifact_sha256='b' * 64,
                    matches=[], coverage={'reviewed_us_symbol_count': 4, 'full_market_coverage': False}, **FLAGS))
                with patch.object(us_mapping_research, 'read_workspace_mapping', return_value=deepcopy(saved)):
                    read, reference, identities = W._daily_mapping_plan_reference(
                        SimpleNamespace(), DATE, {'research_cutoff': CUTOFF})
                self.assertEqual(reference['status'], state)
                self.assertEqual(len(identities), expected_count)
                self.assertEqual(read['daily_run']['coverage']['reviewed_us_symbol_count'], 4)
                self.assertFalse(read['daily_run']['coverage']['full_market_coverage'])
                for key, value in FLAGS.items():
                    self.assertIs(reference[key], value)


if __name__ == '__main__':
    unittest.main(verbosity=2)
