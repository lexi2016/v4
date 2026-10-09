"""Mac-only test candidates; no provider calls and no cloud product execution.

The committed-observation reader and private panel read are explicitly stubbed.
These fixtures test admission, NOT an actual original-owner/source attestation.
Deployment pins, file SHA reads, calendar and per-cell verification are real.
"""
import copy
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from v5_shadow import rebound_admission as admission
from v5_shadow.digests import canonical_bytes, sha256_json


class FixedClock(datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 10, 9, 8, 0, tzinfo=timezone.utc)
        return value.astimezone(tz) if tz else value.replace(tzinfo=None)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class NativeCalendarCandidates(unittest.TestCase):
    def test_real_capsule_loads_pinned_python_and_json_without_mocking_calendar(self):
        module, calendar, calendar_sha = admission._calendar()
        descriptor, sources = admission.observation._capsule()
        self.assertIn('contracts/trading_calendar.py', sources)
        self.assertEqual(calendar_sha, descriptor['bindings']['vendor/rebound_baseline/contracts/market_calendar_2026.json'])
        self.assertEqual(module.resolve_market_states(calendar, '20261001')['hk_securities'], module.TradingDayState.NON_TRADING_DAY)
        self.assertEqual(admission._session_close('20261008', module, calendar, full=True).isoformat(), '2026-10-08T16:10:00+08:00')


class AdmissionCandidates(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        module, calendar, calendar_sha = admission._calendar()
        cursor, prior, five = '20261008', [], []
        while len(prior) < 60 or len(five) < 5:
            cursor = module.previous_session(calendar, cursor, market='hk_securities')
            if len(prior) < 60: prior.append(cursor)
            if module.resolve_market_states(calendar, cursor)['hk_securities'] == module.TradingDayState.FULL_TRADING_DAY and len(five) < 5:
                five.append(cursor)
        self.prior, self.five = sorted(prior), sorted(five)
        self.reference = dict(run_id='1'*32, artifact_sha256='a'*64, manifest_sha256='b'*64, receipt_sha256='c'*64)
        self.identity = admission.observation._identity()
        self.artifact = dict(
            fixture_kind='SYNTHETIC_STUB_NOT_A_COMMITTED_PRODUCT',
            request=dict(target_date='20261009', signal_date='20261008', data_kind='RECORDED_INPUT_CURRENT'),
            computation_status='NATIVE_VALUES_OBSERVED', observed_at='2026-10-09T07:00:00+00:00',
            finished_at='2026-10-09T07:00:02+00:00', source_capsule_sha256=admission.observation.PIN,
            dependencies=dict(status='MATCH', synthetic_fixture=True),
            implementation_identity=self.identity,
            history_sessions=dict(prior60=self.prior, previous5=self.five, calendar_sha256=calendar_sha),
            source_identity=dict(panel_sha256='d'*64, panel_manifest_sha256='e'*64, calendar_sha256=calendar_sha), rows=[])
        self.owner = dict(owner_id='SYNTHETIC_MAC_OWNER', owner_source_sha256='f'*64, reviewer_id='SYNTHETIC_INDEPENDENT_REVIEW')
        self.member_owner = dict(owner_id='SYNTHETIC_MEMBERSHIP_OWNER', owner_source_sha256='1'*64, reviewer_id='SYNTHETIC_MEMBERSHIP_REVIEW')
        raw, member_raw, document = b'SYNTHETIC_DAILY_SOURCE_BYTES', b'SYNTHETIC_TARGET_MEMBERSHIP_BYTES', b'SYNTHETIC_OWNER_REVIEWED_DAILY_CONTRACT'
        for name, content in (('raw.bin', raw), ('members.bin', member_raw), ('contract.txt', document)):
            (self.root/name).write_bytes(content)
        self.contract = dict(owner_source_sha256='f'*64, decoder_sha256='2'*64,
            document=dict(relative='contract.txt', sha256=digest(document)), price_basis='RAW', price_currency='HKD',
            price_scale=1, volume_unit='SHARES', volume_scale=1, finality_rule='DAILY_BARS_CAPTURE_AFTER_NATIVE_CLOSE',
            field_bindings={field: dict(native_field=field+'_v', storage_type=storage,
                storage_locator='SYNTHETIC_RECORD_BYTE_OFFSET_'+str(offset),
                conversion_basis='SYNTHETIC_APPROVED_DOC: scale 1; no conversion',
                adjustment_basis='SYNTHETIC_APPROVED_DOC: raw unadjusted source')
                for field, storage, offset in (('high', 'float32_le', 8), ('close', 'float32_le', 16),
                                               ('trade', 'uint32_le', 24))})
        self.attestation = dict(schema_version='v5.rebound_owner_cell_attestation.v1', owner_identity=self.owner,
            reviewed_at='2026-10-09T07:01:00+00:00', observation_reference=self.reference,
            target_date='20261009', signal_date='20261008', research_cutoff=self.artifact['observed_at'],
            **self.artifact['source_identity'],
            raw_sources=dict(raw=dict(relative='raw.bin', sha256=digest(raw), source_contract_id='native-daily',
                owner_source_sha256='f'*64, decoder_sha256='2'*64, capture_started_at='2026-10-08T09:00:00+00:00',
                captured_at='2026-10-08T09:00:01+00:00', available_at='2026-10-08T09:00:02+00:00')), codes={})
        self.membership = dict(schema_version='v5.rebound_target_membership_attestation.v1', owner_identity=self.member_owner,
            target_date='20261009', capture_started_at='2026-10-09T06:00:00+00:00', captured_at='2026-10-09T06:00:01+00:00',
            available_at='2026-10-09T06:00:02+00:00', reviewed_at='2026-10-09T07:01:00+00:00',
            codes=['HK.00001', 'HK.00002', 'HK.00003', 'HK.00004'],
            raw_source=dict(relative='members.bin', sha256=digest(member_raw)))
        self.membership['codes_sha256'] = sha256_json(self.membership['codes'])
        self.panel = {}
        for code, close, volume, comparisons in (
            ('HK.00001', 80, 150, (True, True)), ('HK.00002', 90, 150, (False, True)),
            ('HK.00003', 90, 50, (False, False)),
        ):
            row = dict(code=code, name=code, name_source='SYMBOL_ONLY', numeric_input_status='KNOWN', input_gaps=[],
                native_numbers=dict(close_native=close, current_volume_native=volume, prior60_high_native=100, previous5_mean_volume_native=100),
                native_comparisons=dict(close_le_prior60_high_times_0_8=comparisons[0], current_to_previous5_ge_1_5=comparisons[1]))
            self.artifact['rows'].append(row)
            for day in self.prior:
                self.panel[(code, day)] = [dict(high=100, close=50, trade=100)]
            self.panel[(code, '20261008')] = [dict(high=100, close=close, trade=volume)]
            required = sorted({(day, 'high') for day in self.prior} | {('20261008', 'close')}
                              | {(day, 'trade') for day in [*self.five, '20261008']})
            self.attestation['codes'][code] = dict(cells=[dict(date=day, field=field,
                value=self.panel[(code, day)][0][field], raw_source_id='raw', raw_locator=f'{code}/{day}/{field}')
                for day, field in required])
        self.policy = dict(schema_version='v5.rebound_deployment_trust.v1', policy_id='SYNTHETIC_DEPLOYMENT_POLICY',
            evidence_root=str(self.root), owner_identity=self.owner, membership_owner_identity=self.member_owner,
            observation_implementation_sha256=sha256_json(self.identity), source_capsule_sha256=admission.observation.PIN,
            admission_implementation_sha256=admission.implementation_sha256(),
            source_contracts={'native-daily': self.contract}, attestations={}, memberships={})
        mocks = (
            patch.object(admission, 'datetime', FixedClock),
            patch.object(admission.observation, 'read_rebound_observation', side_effect=lambda *args: copy.deepcopy(self.artifact)),
            patch.object(admission, '_panel_cells', side_effect=lambda artifact: copy.deepcopy(self.panel)),
            patch.object(admission.owner, 'observe_dependencies', return_value=self.artifact['dependencies']),
        )
        for mock in mocks: mock.start(); self.addCleanup(mock.stop)

    def approve(self):
        for name, document, section, key in (('attestation.json', self.attestation, 'attestations', 'owner'),
                                            ('membership.json', self.membership, 'memberships', 'target')):
            raw = canonical_bytes(document); (self.root/name).write_bytes(raw)
            self.policy[section][key] = dict(relative=name, sha256=digest(raw))
        raw = canonical_bytes(self.policy); (self.root/'policy.json').write_bytes(raw)
        self.authority = admission.load_deployment_authority(self.root/'policy.json', expected_policy_sha256=digest(raw))

    def run_admission(self, *, approve=True):
        if approve: self.approve()
        return admission.admit_rebound_observation(self.root, self.reference, authority=self.authority,
                                                    attestation_id='owner', membership_id='target')

    def test_full_code_proofs_make_strict_near_excluded_reachable_and_missing_member_pending(self):
        result = self.run_admission()
        self.assertEqual(result['counts'], dict(target_members=4, strict=1, near=1, excluded=1, pending=1))
        self.assertEqual(result['status'], 'PARTIAL')
        self.assertEqual(result['strict'][0]['evidence']['verified_cell_count'], 67)
        self.assertEqual(result['strict'][0]['evidence']['status'], 'OWNER_VERIFIED')
        self.assertEqual(result['strict'][0]['evidence']['scope'],
                         'ONE_CODE_EXACT_60_PRICE_AND_SIX_VOLUME_SESSIONS')
        self.assertEqual(result['pending'][0]['code'], 'HK.00004')
        self.assertIn('TARGET_MEMBER_SIGNAL_ROW_MISSING', result['pending'][0]['reason_codes'])
        self.assertFalse(result['full_master_owner_verified']); self.assertFalse(result['natural_verified'])
        self.assertFalse(result['production_allowed']); self.assertNotIn('rank', result['strict'][0])
        self.assertEqual(result['selection_sha256'], sha256_json({k: v for k, v in result.items() if k != 'selection_sha256'}))

    def test_ready_empty_is_coverage_backed_when_all_members_fail_both_original_gates(self):
        self.membership['codes'] = ['HK.00003']; self.membership['codes_sha256'] = sha256_json(self.membership['codes'])
        result = self.run_admission()
        self.assertEqual(result['status'], 'READY')
        self.assertEqual(result['counts'], dict(target_members=1, strict=0, near=0, excluded=1, pending=0))
        self.assertEqual(result['outside_target_membership'], ['HK.00001', 'HK.00002'])

    def test_partly_proven_scope_never_proves_the_whole_panel(self):
        del self.attestation['codes']['HK.00002']
        self.attestation['codes']['HK.00003']['cells'].pop()
        result = self.run_admission()
        self.assertEqual(result['counts']['strict'], 1); self.assertEqual(result['counts']['pending'], 3)
        reasons = {row['code']: row['reason_codes'] for row in result['pending']}
        self.assertIn('OWNER_CODE_EVIDENCE_MISSING', reasons['HK.00002'])
        self.assertIn('ADMISSION_ALL_67_CELLS_REQUIRED', reasons['HK.00003'])

    def test_numeric_incomplete_stays_pending_despite_owner_proof(self):
        self.artifact['rows'][0]['numeric_input_status'] = 'PARTIAL_UNKNOWN'
        self.artifact['rows'][0]['input_gaps'] = ['MISSING_PRIOR_HIGH']
        result = self.run_admission()
        self.assertEqual(result['counts']['strict'], 0)
        self.assertIn('NUMERIC_INPUT_INCOMPLETE', result['pending'][0]['reason_codes'])

    def test_missing_deployment_capability_and_request_selected_approval_fail(self):
        with self.assertRaisesRegex(ValueError, 'DEPLOYMENT_CAPABILITY_REQUIRED'):
            admission.DeploymentAuthority(self.root/'policy.json', '0'*64)
        with self.assertRaisesRegex(ValueError, 'DEPLOYMENT_CAPABILITY_REQUIRED'):
            admission.admit_rebound_observation(self.root, self.reference, authority={}, attestation_id='owner', membership_id='target')
        self.approve()
        with self.assertRaisesRegex(ValueError, 'NOT_DEPLOYMENT_APPROVED'):
            admission.admit_rebound_observation(self.root, self.reference, authority=self.authority,
                                                attestation_id='request-self-signed', membership_id='target')

    def test_rewriting_approved_policy_or_evidence_is_rejected(self):
        for name in ('policy.json', 'attestation.json', 'membership.json', 'raw.bin', 'members.bin', 'contract.txt'):
            with self.subTest(name=name):
                self.approve()
                path = self.root/name; original = path.read_bytes(); path.write_bytes(original+b' ')
                try:
                    with self.assertRaisesRegex(ValueError, 'BOUND_FILE_CHANGED'):
                        self.run_admission(approve=False)
                finally: path.write_bytes(original)

    def test_symlinks_and_wrong_deployment_pin_fail(self):
        self.approve()
        with self.assertRaisesRegex(ValueError, 'BOUND_FILE_CHANGED'):
            admission.load_deployment_authority(self.root/'policy.json', expected_policy_sha256='0'*64)
        (self.root/'linked.json').symlink_to(self.root/'policy.json')
        with self.assertRaisesRegex(ValueError, 'SYMLINK_REJECTED'):
            admission.load_deployment_authority(self.root/'linked.json', expected_policy_sha256=digest((self.root/'policy.json').read_bytes()))

    def test_approved_but_wrong_global_bindings_are_rejected(self):
        for key, replacement in (('panel_sha256', '0'*64), ('calendar_sha256', '0'*64),
                                 ('target_date', '20260930'), ('signal_date', '20261007'),
                                 ('research_cutoff', '2026-10-09T06:59:00+00:00')):
            with self.subTest(key=key):
                previous = self.attestation[key]; self.attestation[key] = replacement
                try:
                    with self.assertRaisesRegex(ValueError, 'ATTESTATION_BINDING'): self.run_admission()
                finally: self.attestation[key] = previous

    def test_incorrect_cell_value_or_duplicate_cell_stays_pending(self):
        for mutation in ('value', 'duplicate', 'raw', 'panel_duplicate'):
            with self.subTest(mutation=mutation):
                proof = copy.deepcopy(self.attestation['codes']['HK.00001'])
                cells = self.attestation['codes']['HK.00001']['cells']
                panel = copy.deepcopy(self.panel)
                if mutation == 'value': cells[0]['value'] += 1
                elif mutation == 'duplicate': cells[0] = copy.deepcopy(cells[1])
                elif mutation == 'raw': cells[0]['raw_source_id'] = 'missing'
                else: self.panel[('HK.00001', cells[0]['date'])].append(self.panel[('HK.00001', cells[0]['date'])][0])
                result = self.run_admission()
                self.assertEqual(result['counts']['strict'], 0)
                self.attestation['codes']['HK.00001'] = proof; self.panel = panel

    def test_finite_values_only_and_no_missing_cells_become_zero(self):
        for bad in (True, float('inf'), float('nan'), -1):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError): admission._number(bad)

    def test_session_finality_uses_native_close_and_actual_provider_capture(self):
        self.attestation['raw_sources']['raw']['capture_started_at'] = '2026-10-08T07:00:00+00:00'
        result = self.run_admission()
        self.assertEqual(result['counts']['strict'], 0)
        self.assertIn('ADMISSION_RAW_CAPTURE_BEFORE_SESSION_CLOSE', result['pending'][0]['reason_codes'])

    def test_mixed_scale_and_units_are_not_inferred_or_converted(self):
        self.policy['source_contracts']['other'] = dict(self.contract, volume_unit='LOTS', volume_scale=100)
        self.attestation['raw_sources']['other'] = dict(self.attestation['raw_sources']['raw'], source_contract_id='other')
        cell = next(c for c in self.attestation['codes']['HK.00001']['cells'] if c['field']=='trade')
        cell['raw_source_id'] = 'other'
        result = self.run_admission()
        self.assertIn('ADMISSION_HISTORY_SCALE_OR_UNIT_MISMATCH', result['pending'][0]['reason_codes'])

    def test_each_cell_needs_approved_original_field_storage_and_transform_basis(self):
        del self.contract['field_bindings']['high']
        result = self.run_admission()
        self.assertEqual(result['counts']['strict'], 0)
        self.assertIn('ADMISSION_CELL_DECODING_CONTRACT', result['pending'][0]['reason_codes'])
        self.contract['field_bindings']['high'] = copy.deepcopy(self.contract['field_bindings']['close'])
        for key in ('native_field', 'storage_type', 'storage_locator', 'conversion_basis', 'adjustment_basis'):
            with self.subTest(key=key):
                binding = self.contract['field_bindings']['trade']; previous = binding[key]
                binding[key] = 'NOT_PROVEN'
                try:
                    with self.assertRaisesRegex(ValueError, 'NATIVE_FIELD_CONTRACT'): self.run_admission()
                finally: binding[key] = previous

    def test_membership_after_cutoff_or_wrong_day_does_not_become_preopen_evidence(self):
        self.membership['captured_at'] = '2026-10-09T07:30:00+00:00'
        self.membership['available_at'] = '2026-10-09T07:30:01+00:00'
        with self.assertRaisesRegex(ValueError, 'MEMBERSHIP_AVAILABILITY'): self.run_admission()
        self.membership['captured_at'] = '2026-09-30T06:00:00+00:00'
        with self.assertRaisesRegex(ValueError, 'MEMBERSHIP_AVAILABILITY'): self.run_admission()

    def test_synthetic_wrong_day_or_wrong_runtime_never_admitted(self):
        self.artifact['request']['data_kind'] = 'SYNTHETIC'
        with self.assertRaisesRegex(ValueError, 'CURRENT_COMMITTED'): self.run_admission()
        self.artifact['request']['data_kind'] = 'RECORDED_INPUT_CURRENT'
        self.policy['observation_implementation_sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'IMPLEMENTATION_BINDING'): self.run_admission()

    def manager(self, selection, **overrides):
        arguments = dict(target_date='20261009', signal_date='20261008',
                         research_cutoff='2026-10-09T08:01:00+00:00')
        arguments.update(overrides)
        return admission.manager_admitted_selection(selection, **arguments)

    def test_manager_consumes_partial_or_ready_with_independent_copy(self):
        result = self.run_admission()
        readback = self.manager(result)
        self.assertEqual(readback, result)
        readback['strict'][0]['name'] = 'MANAGER_LOCAL_CHANGE'
        self.assertNotEqual(readback['strict'][0]['name'], result['strict'][0]['name'])
        self.membership['codes'] = ['HK.00003']
        self.membership['codes_sha256'] = sha256_json(self.membership['codes'])
        ready = self.manager(self.run_admission())
        self.assertEqual(ready['status'], 'READY')
        self.assertEqual(ready['strict'], [])
        self.assertEqual(ready['counts']['excluded'], 1)

    def test_manager_checks_admission_time_not_only_earlier_observation_cutoff(self):
        result = self.run_admission()
        self.assertEqual(result['research_cutoff'], '2026-10-09T07:00:00+00:00')
        with self.assertRaisesRegex(ValueError, 'MANAGER_AFTER_CUTOFF'):
            self.manager(result, research_cutoff='2026-10-09T07:30:00+00:00')
        self.manager(result, research_cutoff=result['evaluated_at'])
        for overrides in (dict(target_date='20261012'), dict(signal_date='20261007'),
                          dict(research_cutoff='2026-10-10T08:00:00+00:00')):
            with self.subTest(overrides=overrides):
                with self.assertRaisesRegex(ValueError, 'MANAGER_DATE_MISMATCH'):
                    self.manager(result, **overrides)

    def test_manager_rejects_digest_mutation(self):
        result = self.run_admission(); result['pending'][0]['reason_codes'] = ['ALTERED']
        with self.assertRaisesRegex(ValueError, 'MANAGER_SELECTION_SHA'): self.manager(result)

    def test_manager_rejects_self_consistent_invalid_counts_groups_scope_and_labels(self):
        result = self.run_admission()
        def mutate(value, case):
            if case == 'duplicate': value['near'][0]['code'] = value['strict'][0]['code']
            elif case == 'count': value['counts']['target_members'] += 1
            elif case == 'boolean_count': value['counts']['strict'] = True
            elif case == 'status': value['status'] = 'READY'
            elif case == 'boolean_comparison': value['strict'][0]['native_comparisons']['close_le_prior60_high_times_0_8'] = 1
            elif case == 'group': value['strict'][0]['native_comparisons']['close_le_prior60_high_times_0_8'] = False
            elif case == 'cells': value['strict'][0]['evidence']['verified_cell_count'] = 1
            elif case == 'scope': value['outside_target_membership'] = [value['strict'][0]['code']]
            elif case == 'pending_reason': value['pending'][0]['reason_codes'] = []
            elif case == 'safety': value['full_master_owner_verified'] = True
            elif case == 'preopen': value['membership_timing'] = 'PREOPEN_VERIFIED'
            elif case == 'reverse_time': value['evaluated_at'] = '2026-10-09T06:00:00+00:00'
            elif case == 'extra_rank': value['strict'][0]['rank'] = 1
        for case in ('duplicate', 'count', 'boolean_count', 'status', 'boolean_comparison', 'group',
                     'cells', 'scope', 'pending_reason', 'safety', 'preopen', 'reverse_time', 'extra_rank'):
            with self.subTest(case=case):
                broken = copy.deepcopy(result); mutate(broken, case)
                broken['selection_sha256'] = sha256_json({key: item for key, item in broken.items() if key != 'selection_sha256'})
                with self.assertRaises(ValueError): self.manager(broken)


if __name__ == '__main__':
    unittest.main()
