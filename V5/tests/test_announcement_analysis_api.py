"""Exact browser query/response contracts; no relabelled default payload."""
import copy
import unittest
from unittest.mock import patch
from v5_shadow.announcement_analysis_api import response_record,publish_analysis

class AnnouncementAnalysisApiTests(unittest.TestCase):
    def setUp(self):
        self.config={'module_id':'announcements','release_id':'synthetic'}
        self.explicit={'request_sha256':'a'*64,'analysis':{'target_trade_date':'20261009','publication_date':'2026-10-08',
            'date_selection_basis':'EXPLICIT','analysis':{'status':'VERIFIED','product_sha256':'b'*64,
            'stock_selection':{'status':'NOT_ASSESSED','stock_count':None}}}}
        self.default=copy.deepcopy(self.explicit);self.default['analysis']['date_selection_basis']='PREVIOUS_HK_TRADING_SESSION'

    def test_explicit_payload_cannot_be_published_under_default_query(self):
        with self.assertRaisesRegex(ValueError,'QUERY_BASIS_MISMATCH'):
            response_record(self.explicit,self.config,{'date':'20261009'})

    def test_default_payload_requires_actual_default_basis(self):
        record=response_record(self.default,self.config,{'date':'20261009'})
        self.assertEqual(record['payload'],self.default['analysis'])
        with self.assertRaisesRegex(ValueError,'QUERY_BASIS_MISMATCH'):
            response_record(self.default,self.config,{'date':'20261009','publication_date':'20261008'})

    def test_explicit_query_formats_preserve_nullable_selection_and_payload(self):
        before=copy.deepcopy(self.explicit)
        for day in ('20261008','2026-10-08'):
            record=response_record(self.explicit,self.config,{'date':'20261009','publication_date':day})
            self.assertEqual(record['payload'],before['analysis'])
            self.assertIsNone(record['payload']['analysis']['stock_selection']['stock_count'])
        self.assertEqual(self.explicit,before)
        with self.assertRaisesRegex(ValueError,'QUERY_DATE_MISMATCH'):
            response_record(self.explicit,self.config,{'date':'20261009','publication_date':'20261007'})

    def test_publisher_reads_default_separately_and_atomically_replaces_bad_default(self):
        binding={'target_date':'20261009','publication_date':'2026-10-08'}
        with patch('v5_shadow.announcement_analysis_api.read_owner',side_effect=[self.explicit,self.default]) as reader, \
             patch('v5_shadow.announcement_analysis_api.publish_generation',return_value={'ok':True}) as publish:
            self.assertEqual(publish_analysis(binding,self.config,expected_generation='c'*64),{'ok':True})
            self.assertEqual(reader.call_args_list[1].kwargs,{'default_analysis':True})
            records=publish.call_args.args[1]
            self.assertEqual(len(records),3)
            self.assertEqual(records[-1]['query'],{'date':'20261009'})
            self.assertEqual(records[-1]['payload']['date_selection_basis'],'PREVIOUS_HK_TRADING_SESSION')
            self.assertEqual(publish.call_args.kwargs,{'expected_generation':'c'*64})
