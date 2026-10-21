"""Exact code membership comparison; no formula/data mutation or causal guess."""
import csv, hashlib, json
from pathlib import Path

R = Path('/Users/lexi/Desktop/学习/因子工厂/research/a_share_quarantine_recovery_20261021/windows37_d21_reconcile_20261022')

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p): return json.loads(Path(p).read_text())
def save(p, x):
    with Path(p).open('x') as f: json.dump(x, f, ensure_ascii=False, indent=2); f.write('\n')

def main():
    contract = read(R / 'selection_replay_r2/CONTRACT.json')
    binding = read(contract['input_binding_path'])
    for item in binding['frozen_refs']: assert sha(item['path']) == item['sha256']
    output = Path(contract['output_dir']); result = read(output / 'RESULT.json')
    assert result['execution_id'] == contract['execution_id'] and result['status'] == 'TODAY_TDX_OFFLINE_AND_MAC_EXISTING_UNION_COMPLETE_WITH_EXPLICIT_GAPS'
    for artifact in result['artifacts'].values(): assert sha(artifact['path']) == artifact['sha256']
    handoff = read(output / 'MODEL_UNION_HANDOFF.json')
    old = read(binding['prior_selection_handoff']['path'])
    with Path(binding['saved_windows_membership']['path']).open(encoding='utf-8-sig', newline='') as f: windows_rows = list(csv.DictReader(f))
    windows = {x['canonical_code'] for x in windows_rows}; assert len(windows) == len(windows_rows) == 37
    with (output/'tdx_selected.csv').open(encoding='utf-8-sig', newline='') as f: selected_rows=list(csv.DictReader(f))
    assert all(x['signal_date']=='20261021' and x['selected']=='True' for x in selected_rows)
    current = {x['futu_code'] for x in selected_rows}; previous = set(old['tdx'])
    assert len(current) == len(selected_rows) == result['tdx_selected_count'] and current == set(handoff['tdx'])
    win_a = {c for c in windows if c.split('.')[0] in ('SH', 'SZ', 'BJ')}
    interest = windows ^ current | previous ^ current
    traces = {}
    with (output / 'tdx_signals.jsonl').open() as f:
        for line in f:
            row = json.loads(line)
            if row['futu_code'] in interest: traces[row['futu_code']] = row
    columns = ['canonical_code','windows_saved_member','before_local_member','after_local_member','membership_change','after_state','after_XG','after_observed_history_bars','after_reject_or_unknown','windows_signal_date']
    rows = []
    for c in sorted(windows | previous | current):
        t = traces.get(c, {}); components = t.get('all_255_assignments', {})
        rows.append({'canonical_code':c, 'windows_saved_member':c in windows, 'before_local_member':c in previous,
            'after_local_member':c in current, 'membership_change':'ADDED' if c in current-previous else 'REMOVED' if c in previous-current else 'UNCHANGED',
            'after_state':t.get('state'), 'after_XG':t.get('XG'), 'after_observed_history_bars':t.get('observed_history_bars'),
            'after_reject_or_unknown':json.dumps({k:components.get(k) for k in ('RELAX','ENTRYPOOL','FRESH','CONT0','RISK0','B2ROLE','B3ROLE','XG')}, sort_keys=True) if t else None,
            'windows_signal_date':'20261021_USER_CONFIRMED'})
    with (output/'WINDOWS37_EXACT_CODE_COMPARISON.csv').open('x', encoding='utf-8-sig', newline='') as f:
        writer=csv.DictWriter(f, fieldnames=columns);writer.writeheader();writer.writerows(rows)
    comparison = {'execution_id':contract['execution_id'], 'signal_date':'20261021', 'history_start':'20260101',
        'saved_windows_total':37, 'saved_windows_a_scope_count':len(win_a), 'saved_windows_external_codes':sorted(windows-win_a),
        'before_local_selected_count':len(previous), 'after_local_selected_count':len(current), 'observed_target_universe':result['observed_today_stock_count'],
        'after_unknown_count':result['tdx_unknown_count'], 'newly_selected_codes':sorted(current-previous), 'no_longer_selected_codes':sorted(previous-current),
        'common_all':sorted(windows&current), 'windows_only_all':sorted(windows-current), 'local_only_all':sorted(current-windows),
        'common_a_scope':sorted(win_a&current), 'windows_only_a_scope':sorted(win_a-current), 'local_only_a_scope':sorted(current-win_a),
        'membership_matches_a_scope':win_a==current, 'membership_matches_all37':windows==current,
        'comparison_csv_sha256':sha(output/'WINDOWS37_EXACT_CODE_COMPARISON.csv'),
        'windows_saved_membership_ref':binding['saved_windows_membership'], 'actual_panel_ref':binding['selector'],
        'compared_selection_source':'This execution actual tdx_selected.csv, crosschecked against RESULT artifact SHA and new handoff.tdx; no Mac union',
        'formula_identity':'USER_CONFIRMED_SAME_WINDOWS_FORMULA; LOCAL_FROZEN255_UNCHANGED; ENGINE_PARITY_NOT_INFERRED',
        'windows_source_signal_date':'20261021_USER_CONFIRMED', 'windows_settings_and_formula_body_parity':'SAME_FORMULA_USER_CONFIRMED; ACTUAL_ADJUSTMENT_HISTORY_ENGINE_SETTINGS_CANNOT_CONFIRM',
        'causal_limit':'Membership and local component changes are measured. No unobserved Windows engine mechanism is inferred.',
        'full_schema_ready':False, 'futu_mutations':0, 'research_only':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
    save(output/'WINDOWS37_COMPARISON_RESULT.json', comparison)
    print(json.dumps({k:comparison[k] for k in ('before_local_selected_count','after_local_selected_count','observed_target_universe','after_unknown_count','newly_selected_codes','no_longer_selected_codes','windows_only_all','local_only_all','membership_matches_a_scope')}))

if __name__=='__main__': main()
