"""Mac candidates for the real frozen decoder with SYNTHETIC JSON captures.

The 45276/38090/47348 values exercise scale preservation only. These fixtures
are not the real 0f45... capture, do not claim its SHA, and do not attest units
or session finality. No live collector or model is imported, and no product
tests are run in the cloud.
"""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from v5_shadow import rebound_raw_repair as raw_repair


THROUGH = '20261008'
DAYS = ('20261005', '20261006', '20261007')
TRADES = (45276, 38090, 47348)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def source_row(day, trade):
    return dict(datetime=datetime.strptime(day, '%Y%m%d').strftime('%Y-%m-%d 15:00'),
        open=10.25, high=12.5, low=8.5, close=11.1234567890123, trade=trade,
        volume=999999999, amount=None)


def seal(record):
    record['request_sha256'] = sha(canonical(record['request']))
    record['response_sha256'] = sha(canonical(record['source_rows']))
    record['returned_count'] = len(record['source_rows'])
    return record


def synthetic_record(code='HK.00001'):
    now = datetime.now(timezone.utc)
    return seal(dict(code=code, status='RESPONSE_CAPTURED', error_code=None,
        request=dict(category=4, market=71, code=code[3:], start=0, count=6,
                     requested_sessions=list(DAYS)),
        source_rows=[source_row(day, trade) for day, trade in zip(DAYS, TRADES)],
        request_started_at=(now-timedelta(seconds=3)).isoformat(timespec='microseconds'),
        response_acquired_at=(now-timedelta(seconds=2)).isoformat(timespec='microseconds'),
        request_finished_at=(now-timedelta(seconds=1)).isoformat(timespec='microseconds')))


class ReboundRawRepairCandidates(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.relative = 'captured/original-response.json'
        self.path = self.root / self.relative
        self.record = synthetic_record()
        self.keys = [dict(code='HK.00001', date=day) for day in DAYS]
        self.sources = self.save({'wrapper': {'records': [self.record]}}, '/wrapper/records/0')

    def save(self, document, pointer='', relative=None):
        relative = self.relative if relative is None else relative
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = canonical(document); path.write_bytes(encoded)
        return [dict(relative=relative, sha256=sha(encoded), record_pointer=pointer)]

    def use_record(self, record=None):
        record = self.record if record is None else record
        self.sources = self.save(record)
        return self.sources

    def decode(self, *, sources=None, keys=None):
        return raw_repair.decode_raw_repair(self.root,
            sources=self.sources if sources is None else sources,
            keys=self.keys if keys is None else keys, through_date=THROUGH)

    def test_explicit_pointer_preserves_three_original_trade_values_and_evidence(self):
        before = self.path.read_bytes()
        sources_before, keys_before = copy.deepcopy(self.sources), copy.deepcopy(self.keys)
        result = self.decode()
        self.assertEqual([row['trade'] for row in result['rows']], list(TRADES))
        self.assertTrue(all(type(row['trade']) is float for row in result['rows']))
        self.assertTrue(all(row['close'] == 11.1234567890123 for row in result['rows']))
        for index, row in enumerate(result['rows']):
            self.assertEqual(row['code_norm'], 'HK.00001')
            self.assertEqual(row['trade_date_compact'], DAYS[index])
            self.assertEqual(row['trade_date'], DAYS[index])
            self.assertIsNone(row['amount'])
            self.assertNotIn('native_fields', row)
            self.assertNotIn('volume', row)
            self.assertNotIn('position', row)
            self.assertEqual(result['row_evidence'][index], dict(code='HK.00001', date=DAYS[index],
                raw_file=self.relative, raw_file_sha256=sha(before), record_pointer='/wrapper/records/0',
                source_row_index=index, source_row_sha256=sha(canonical(self.record['source_rows'][index]))))
        self.assertEqual(result['native_evidence'], dict(volume_unit=None, volume_unit_status='NOT_PROVEN',
            price_basis='NOT_PROVEN', scale_applied=1))
        self.assertEqual(result['raw_files'], {self.relative: sha(before)})
        self.assertEqual(result['capture_started_at'], self.record['request_started_at'])
        self.assertEqual(result['capture_finished_at'], self.record['request_finished_at'])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.sources, sources_before); self.assertEqual(self.keys, keys_before)

    def test_trade_is_required_even_when_a_volume_alias_is_present(self):
        self.record['source_rows'][0].pop('trade')
        self.use_record(seal(self.record))
        with self.assertRaisesRegex(ValueError, 'HK_DAILY_SUPPLEMENT_NUMBER_INVALID'):
            self.decode()

    def test_original_zero_trade_and_missing_optional_amount_are_preserved(self):
        row = self.record['source_rows'][0]
        row['trade'] = 0; row.pop('amount')
        self.use_record(seal(self.record))
        actual = self.decode()['rows'][0]
        self.assertEqual(actual['trade'], 0)
        self.assertIsNone(actual['amount'])

    def test_original_year_month_day_fallback_and_extra_history_selection(self):
        row = self.record['source_rows'][0]
        row.pop('datetime'); row.update(year=2026, month=10, day=5)
        # Unrequested old rows need their real date, but the original decoder
        # does not invent or validate OHLC for rows outside the requested set.
        self.record['source_rows'].insert(0, dict(datetime='2026-09-30 15:00'))
        self.use_record(seal(self.record))
        result = self.decode()
        self.assertEqual([row['trade'] for row in result['rows']], list(TRADES))
        self.assertEqual(result['row_evidence'][0]['source_row_index'], 1)

    def test_pointer_is_never_guessed_and_rfc6901_escapes_are_explicit(self):
        invalid = ('', '/records/0', '/wrapper/records', '/wrapper/records/00',
                   '/wrapper/records/-', '/wrapper/records/3', '#/wrapper/records/0', '/bad~2key')
        for pointer in invalid:
            with self.subTest(pointer=pointer):
                source = dict(self.sources[0], record_pointer=pointer)
                with self.assertRaises(ValueError):
                    self.decode(sources=[source])
        sources = self.save({'a/b~c': [self.record]}, '/a~1b~0c/0')
        self.assertEqual(len(self.decode(sources=sources)['rows']), 3)
        self.use_record()
        self.assertEqual(len(self.decode()['rows']), 3)

    def test_actual_success_enumerations_only(self):
        for status in ('RESPONSE_CAPTURED', 'READY', 'PENDING'):
            with self.subTest(status=status):
                self.record['status'] = status; self.use_record()
                self.assertEqual(len(self.decode()['rows']), 3)
        for status in ('INVALID', 'QUERY_FAILED', 'SUCCESS', ''):
            with self.subTest(status=status):
                self.record['status'] = status; self.use_record()
                with self.assertRaisesRegex(ValueError, 'RAW_REPAIR_RECORD_NOT_SUCCESSFUL'):
                    self.decode()
        self.record['status'] = 'READY'; self.record['error_code'] = 'CAPTURE_FAILED'
        self.use_record()
        with self.assertRaisesRegex(ValueError, 'RAW_REPAIR_RECORD_NOT_SUCCESSFUL'):
            self.decode()

    def test_request_market_category_code_start_and_count_are_exact(self):
        changes = (('market', 70), ('market', 71.0), ('category', 7), ('category', True),
                   ('code', 'HK.00001'), ('code', '00002'), ('start', -1), ('start', False),
                   ('count', 0), ('count', 6.0))
        for field, value in changes:
            with self.subTest(field=field, value=value):
                record = synthetic_record(); record['request'][field] = value
                self.use_record(seal(record))
                with self.assertRaisesRegex(ValueError, 'RAW_REPAIR_REQUEST_IDENTITY'):
                    self.decode()

    def test_request_response_and_raw_file_hashes_are_all_verified(self):
        for field, reason in (('request_sha256', 'RAW_REPAIR_REQUEST_SHA'),
                              ('response_sha256', 'RAW_REPAIR_RESPONSE_SHA')):
            with self.subTest(field=field):
                record = synthetic_record(); record[field] = 'f'*64
                self.use_record(record)
                with self.assertRaisesRegex(ValueError, reason):
                    self.decode()
        self.use_record(synthetic_record())
        self.path.write_bytes(self.path.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError, 'RAW_REPAIR_INPUT_SHA'):
            self.decode()

    def test_returned_count_and_request_count_cannot_hide_rows(self):
        for field, value in (('returned_count', 1), ('returned_count', True), ('request_count', 2)):
            with self.subTest(field=field):
                record = synthetic_record()
                if field == 'request_count':
                    record['request']['count'] = value; seal(record)
                else:
                    record[field] = value
                self.use_record(record)
                with self.assertRaisesRegex(ValueError, 'RAW_REPAIR_RESPONSE_COUNT'):
                    self.decode()

    def test_missing_keys_and_duplicate_dates_fail_without_zero_fill_or_last_wins(self):
        record = synthetic_record(); record['source_rows'].pop()
        self.use_record(seal(record))
        with self.assertRaisesRegex(ValueError, 'RAW_REPAIR_EXACT_KEYS_MISSING'):
            self.decode()
        record = synthetic_record(); record['source_rows'].append(dict(record['source_rows'][0], trade=1))
        self.use_record(seal(record))
        with self.assertRaisesRegex(ValueError, 'RAW_REPAIR_DUPLICATE_SOURCE_DATE'):
            self.decode()

    def test_same_key_from_multiple_records_is_ambiguous_even_when_values_match(self):
        sources = self.save({'records': [self.record, copy.deepcopy(self.record)]}, '/records/0')
        sources.append(dict(sources[0], record_pointer='/records/1'))
        with self.assertRaisesRegex(ValueError, 'RAW_REPAIR_MULTIPLE_SOURCES_FOR_KEY'):
            self.decode(sources=sources)

    def test_each_declared_record_must_contribute_a_requested_key(self):
        unused = synthetic_record()
        unused['source_rows'] = [source_row('20260930', 10)]
        seal(unused)
        sources = self.save({'records': [self.record, unused]}, '/records/0')
        sources.append(dict(sources[0], record_pointer='/records/1'))
        with self.assertRaisesRegex(ValueError, 'RAW_REPAIR_UNUSED_SOURCE'):
            self.decode(sources=sources)

    def test_one_raw_file_with_multiple_records_is_stably_read_only_once(self):
        other = synthetic_record('HK.00002')
        sources = self.save({'records': [self.record, other]}, '/records/0')
        sources.append(dict(sources[0], record_pointer='/records/1'))
        keys = self.keys+[dict(code='HK.00002', date=day) for day in DAYS]
        with patch.object(raw_repair, '_read', wraps=raw_repair._read) as reader:
            result = self.decode(sources=sources, keys=keys)
        input_reads = [call for call in reader.call_args_list if call.args[0] == self.root]
        self.assertEqual(len(input_reads), 1)
        self.assertEqual(len(result['rows']), 6)
        self.assertEqual(result['capture_started_at'], min(self.record['request_started_at'], other['request_started_at']))
        self.assertEqual(result['capture_finished_at'], max(self.record['request_finished_at'], other['request_finished_at']))

    def test_duplicate_reference_conflicting_sha_and_unrequested_code_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'RAW_REPAIR_DUPLICATE_REFERENCE'):
            self.decode(sources=self.sources*2)
        other = dict(self.sources[0], record_pointer='/different', sha256='f'*64)
        with self.assertRaisesRegex(ValueError, 'RAW_REPAIR_CONFLICTING_FILE_SHA'):
            self.decode(sources=self.sources+[other])
        self.use_record(synthetic_record('HK.00002'))
        with self.assertRaisesRegex(ValueError, 'RAW_REPAIR_UNREQUESTED_CODE'):
            self.decode()

    def test_actual_capture_clock_order_timezone_and_future_are_checked(self):
        for mutation in ('reversed', 'future', 'naive'):
            with self.subTest(mutation=mutation):
                record = synthetic_record()
                if mutation == 'reversed':
                    record['response_acquired_at'] = record['request_started_at']
                    record['request_started_at'] = record['request_finished_at']
                elif mutation == 'future':
                    record['request_finished_at'] = (datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
                else:
                    record['request_started_at'] = '2026-10-07T22:07:41'
                self.use_record(record)
                with self.assertRaises(ValueError):
                    self.decode()

    def test_before_close_capture_does_not_invent_finality_or_use_file_mtime(self):
        self.record.update(request_started_at='2026-10-07T00:30:00.000000+00:00',
            response_acquired_at='2026-10-07T00:30:00.100000+00:00',
            request_finished_at='2026-10-07T00:30:00.200000+00:00')
        self.use_record()
        os.utime(self.path, (1, 1))
        result = self.decode()
        self.assertEqual(result['capture_started_at'], self.record['request_started_at'])
        self.assertEqual(result['capture_finished_at'], self.record['request_finished_at'])
        self.assertEqual(result['native_evidence']['price_basis'], 'NOT_PROVEN')
        self.assertNotIn('FULL_DAY_CLOSE', json.dumps(result))
        self.assertNotIn('finality_status', result)

    def test_original_future_bar_and_invalid_ohlc_are_not_silently_filtered(self):
        record = synthetic_record(); record['source_rows'].append(source_row('20261009', 5))
        self.use_record(seal(record))
        with self.assertRaisesRegex(ValueError, 'HK_DAILY_SUPPLEMENT_FUTURE_ROW'):
            self.decode()
        record = synthetic_record(); record['source_rows'][0]['open'] = 20
        self.use_record(seal(record))
        with self.assertRaisesRegex(ValueError, 'HK_DAILY_SUPPLEMENT_OHLC_INVALID'):
            self.decode()

    def test_path_scope_symlink_and_extra_source_fields_are_rejected(self):
        for name in ('../escape.json', '/absolute.json', 'captured/../original-response.json'):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    self.decode(sources=[dict(self.sources[0], relative=name)])
        with self.assertRaises(ValueError):
            self.decode(sources=[dict(self.sources[0], inferred_code='HK.00001')])
        outside = self.root / 'outside.json'; outside.write_bytes(self.path.read_bytes())
        self.path.unlink(); self.path.symlink_to(outside)
        with self.assertRaises((ValueError, OSError)):
            self.decode()

    def test_same_descriptor_change_during_read_is_rejected(self):
        identity = self.path.stat().st_ino
        real_read = os.read
        changed = False
        def drift(fd, size):
            nonlocal changed
            chunk = real_read(fd, size)
            if chunk and not changed and os.fstat(fd).st_ino == identity:
                changed = True
                with self.path.open('ab') as stream:
                    stream.write(b' ')
            return chunk
        with patch.object(raw_repair.os, 'read', side_effect=drift):
            with self.assertRaisesRegex(ValueError, 'MODULE_RECORD_CHANGED'):
                self.decode()
        self.assertTrue(changed)

    def test_sources_keys_and_cumulative_raw_bytes_are_bounded(self):
        with self.assertRaisesRegex(ValueError, 'RAW_REPAIR_SOURCES_BOUND'):
            self.decode(sources=self.sources*2001)
        with self.assertRaisesRegex(ValueError, 'RAW_REPAIR_KEYS_BOUND'):
            self.decode(keys=[])
        with self.assertRaisesRegex(ValueError, 'RAW_REPAIR_KEY_INVALID_OR_DUPLICATE'):
            self.decode(keys=self.keys+[dict(self.keys[0])])
        with self.assertRaisesRegex(ValueError, 'RAW_REPAIR_KEY_INVALID_OR_DUPLICATE'):
            self.decode(keys=[dict(code='HK.00001', date=THROUGH)])
        document = {'wrapper': {'records': [self.record]}}
        second = self.save(document, '/wrapper/records/0', 'captured/second.json')
        with patch.object(raw_repair, 'MAX_RAW_BYTES', 2*self.path.stat().st_size-1):
            with self.assertRaisesRegex(ValueError, 'MODULE_RECORD_SIZE_OR_TYPE'):
                self.decode(sources=self.sources+second)

    def test_json_duplicate_keys_and_nonfinite_constants_are_rejected(self):
        for encoded in (b'{"same":1,"same":2}', b'{"nonfinite":NaN}'):
            with self.subTest(encoded=encoded):
                self.path.write_bytes(encoded)
                sources = [dict(relative=self.relative, sha256=sha(encoded), record_pointer='')]
                with self.assertRaisesRegex(ValueError, 'REBOUND_(DUPLICATE_JSON_KEY|NONFINITE_JSON)'):
                    self.decode(sources=sources)

    def test_frozen_source_and_manifest_are_pinned_without_importing_collector(self):
        self.assertEqual(sha((raw_repair.BASE/raw_repair.DECODER_RELATIVE).read_bytes()), raw_repair.DECODER_SHA)
        self.assertEqual(sha((raw_repair.BASE/raw_repair.MANIFEST_RELATIVE).read_bytes()), raw_repair.MANIFEST_SHA256)
        original_read = raw_repair._read
        for relative, reason in ((raw_repair.DECODER_RELATIVE, 'RAW_REPAIR_DECODER_SOURCE_SHA'),
                                 (raw_repair.MANIFEST_RELATIVE, 'RAW_REPAIR_SOURCE_MANIFEST_SHA')):
            with self.subTest(relative=relative):
                def corrupted(root, name, limit):
                    raw = original_read(root, name, limit)
                    return raw+b' ' if name == relative else raw
                with patch.object(raw_repair, '_read', side_effect=corrupted):
                    with self.assertRaisesRegex(ValueError, reason):
                        self.decode()
        import builtins
        original_import = builtins.__import__
        def no_provider_import(name, *args, **kwargs):
            if name.startswith('pytdx'):
                raise AssertionError('COLLECTOR_IMPORTED')
            return original_import(name, *args, **kwargs)
        with patch.object(builtins, '__import__', side_effect=no_provider_import):
            self.assertEqual(len(self.decode()['rows']), 3)


if __name__ == '__main__':
    unittest.main()
