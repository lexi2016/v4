import copy
import pytest
from test_research_panel_qfq_tail_batch_v2 import example, bind, js, ref
from ops import research_panel_qfq as qfq

@pytest.mark.parametrize('mutation', ['unapproved_archive_only', 'approved8_native_already_present', 'physical_native_prefix_changed', 'typed_safety_changed'])
def test_independent_direct_v2_boundaries(example, tmp_path, mutation):
    e = example
    normal = next(c for c in e['changed'] if c not in e['archive_only'])
    special = next(c for c in e['changed'] if c in e['archive_only'])
    scope = qfq._tail_batch_v2_scope(e['delta'], e['target'])
    code = special if mutation == 'approved8_native_already_present' else normal
    before = copy.deepcopy(next(s for s in e['config_obj']['stocks'] if s['code'] == code))
    after = copy.deepcopy(next(s for s in e['new_config_obj']['stocks'] if s['code'] == code))
    old_item = copy.deepcopy(e['old']['symbols'][code])
    new_item = copy.deepcopy(e['new']['symbols'][code])
    binding = copy.deepcopy(e['delta']['codes'][code])
    if mutation == 'unapproved_archive_only':
        before['sources'] = before['sources'][:1]
        old_item['raw_files'] = old_item['raw_files'][:1]
    elif mutation == 'approved8_native_already_present':
        before['sources'].append(dict(**binding['native_before'], name='native', kind='day_bytes'))
        old_item['raw_files'].append(dict(**binding['native_before'], source_role='native'))
    elif mutation == 'physical_native_prefix_changed':
        p = tmp_path / 'prefix_changed.day'
        payload = bytearray(open(binding['native_after']['path'], 'rb').read())
        payload[28] ^= 1
        p.write_bytes(payload)
        new_ref = ref(p)
        binding['native_after'] = new_ref
        scope['reports'][code]['native_after'] = new_ref
        after['sources'][1] = dict(**new_ref, name='native', kind='day_bytes')
        new_item['raw_files'][1] = dict(**new_ref, source_role='native')
    else:
        d = copy.deepcopy(e['delta'])
        review = copy.deepcopy(e['review_obj'])
        review['production_allowed'] = True
        d['independent_raw_review'] = js(tmp_path / 'unsafe_review.json', review)
        with pytest.raises(qfq.QfqGateError, match='ACTUAL_RAW_REVIEW'):
            qfq._tail_batch_v2_scope(d, e['target'])
        return
    match = 'OLD_NATIVE_BYTES_CHANGED' if mutation == 'physical_native_prefix_changed' else 'ARCHIVE_OR_NATIVE_ROLES'
    with pytest.raises(qfq.QfqGateError, match=match):
        qfq._tail_batch_v2_code(scope, code, binding, before, after, old_item, new_item, e['new_retention'], e['target'])
