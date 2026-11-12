"""Reproducible, conservative mapping of the supplied Par109 version to V4 exports.
Reads explicit archived sources only. No formula execution or data mutation.
"""
import argparse, ast, csv, hashlib, json, re
from collections import Counter
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evidence(path, start=1, end=None, root=None):
    lines = path.read_text().splitlines()
    end = end or len(lines)
    return dict(path=str(path.relative_to(root)) if root else str(path), sha256=sha(path),
                lines=[start, end], code='\n'.join(lines[start-1:end]))


def functions(path, root):
    tree = ast.parse(path.read_bytes())
    return {n.name: evidence(path, n.lineno, n.end_lineno, root) for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.ClassDef))}


def build(par, v4, output):
    hand = par/'handoff'; unified=hand/'unified_candidate_20261102'
    schema_path=unified/'FIELD_SCHEMA_109.json'; schema=json.loads(schema_path.read_bytes())
    sf=v4/'20261112/V4/FIELD_SCHEMAS.json'; schemas=json.loads(sf.read_bytes())
    cols={role:{c['name']:c['type'] for c in obj['columns']} for role,obj in schemas.items()}
    paths=list(hand.rglob('*.py')); sources={str(p.relative_to(par)):functions(p,par) for p in paths}
    indexed=[]
    for p in paths:
        for line,text in enumerate(p.read_text().splitlines(),1):
            for name in set(re.findall(r'\bkb_[a-z0-9_]+\b',text)):
                indexed.append((name,evidence(p,line,line,par)))
    native=hand/'junda_single_stock_acceptance_20261101/kb_source_signal_view/native_view.py'
    core=hand/'mac_native_dependencies_20261101/extracted/skill/modules/indicators/core.py'
    foundation=hand/'panel_field_algorithms_20261102/foundation_action_candidate/foundation.py'
    kb8=hand/'panel_field_algorithms_20261102/kb8_local_candidate/candidate.py'
    score=hand/'junda_n_score_candidate_20261102/n_score.py'
    actions=hand/'panel_field_algorithms_20261102/foundation_action_candidate/actions_candidate.py'
    vformula=v4/'shared/source_versions/074a038699eae84d093602ee6df551b5279368c5800ad78067902a496c990258/build_canonical_formula_research_panel.py'
    if sha(vformula)!=vformula.parent.name:raise ValueError('ARCHIVED_V4_FORMULA_SHA_MISMATCH')
    vlines=vformula.read_text().splitlines()
    candidates={'kb_b1':'B1','kb_b2':'B2','kb_b3':'B3','kb_brick_value':'brick_type_value',
      'kb_hold_bbi':'bbi','kb_hold_k':'K','kb_hold_d':'D','kb_b1_j':'J','kb_b2_j':'J',
      'kb_rsl_short':'brick_short','kb_rsl_long':'brick_long','kb_macd_gold_cross':'macd_golden_cross',
      'kb_hold_above_bbi':'close_above_bbi','kb_needle_20':'brick_single_needle_under20',
      'kb_white_cross_down':'white_yellow_death_cross','kb_hold_close_up':'ref_score_close_up'}
    reasons={
      'kb_b1':'Par native four-condition score>=3 with rounded KDJ; V4 BBI>white>yellow and J<=13.',
      'kb_b2':'Par native score/follows-B1 detector; V4 recent J<13, volume>prior4 mean*1.25, return>4 and white>yellow.',
      'kb_b3':'Par recent >=4% bullish anchor, 2..5 bars and low>=0.98*anchor; V4 prior J/volume/return breakout expression.',
      'kb_brick_value':'Par begins four-bar RSV at index3, seeds SMA from first RSV and rounds2; V4 rolling min_periods1, tdx_sma arithmetic/order and unrounded output differ.',
      'kb_hold_bbi':'Par native BBI round2; V4 full precision BBI.',
      'kb_hold_k':'Par K starts at row9 from seed50, round2; V4 rec_sma begins at first row with fill50 and different operation order; stored K float32.',
      'kb_hold_d':'Par D starts at row9 from seed50, round2; V4 rec_sma starts at first row; stored D float32.',
      'kb_b1_j':'Par source rounded KDJ J; V4 early-prefix KDJ and unrounded J differ.',
      'kb_b2_j':'Par source rounded KDJ J; V4 early-prefix KDJ and unrounded J differ.',
      'kb_rsl_short':'Par min3, denominator must>0, round2; V4 min_periods1, fill0 and no round2.',
      'kb_rsl_long':'Par min21, denominator must>0, round2; V4 min_periods1, fill0 and no round2.',
      'kb_macd_gold_cross':'Par foundation DEA seed first valid DIF at row26; V4 DEA uses DIF from row1.',
      'kb_hold_above_bbi':'Par strict close>roundedBBI and equality UNKNOWN; V4 close>=fullprecisionBBI.',
      'kb_needle_20':'Par native short<=20 and long>=60; V4 short<=20 and long>=75 OR long-short>=70.',
      'kb_white_cross_down':'Par prior white>=yellow and current white<yellow, both round2, gate116; V4 prior white>yellow, unrounded.',
    }
    gates={'kb_b1':9,'kb_b2':13,'kb_b3':15,'kb_b1_j':9,'kb_b2_j':13,
      'kb_hold_bbi':24,'kb_hold_k':9,'kb_hold_d':9,'kb_rsl_short':3,'kb_rsl_long':21,
      'kb_brick_value':12,'kb_brick_trend_up':121,'kb_white_cross_up':116,'kb_white_cross_down':116,
      'kb_needle_20':22,'kb_needle_30':22,'kb_in_bowl':120,'kb_bull_rope_status':120,
      'kb_rebuild':124,'kb_double_gun':24,'kb_violence_k':21}
    for name in schema:
        if name.startswith('kb_b1'):gates[name]=9
        if name.startswith('kb_b2'):gates[name]=13
        if name.startswith('kb_macd_'):
            suffix=name.removeprefix('kb_macd_');gates[name]=26 if suffix in ('dif_positive','veto') else 29 if suffix.endswith('fake') else 85 if 'divergence' in suffix else 27
        if name.startswith('kb_action_'):gates[name]=1
        if name.startswith('kb_hold_') and name.endswith('_reason'):gates[name]=1
    gates.update(kb_breath_n_type=10,kb_breath_phase=10,kb_beidou=2,kb_suoliang=2,kb_jiayin_zhenyang=2,kb_jiayang_zhenyin=2,kb_fangliang_yinxian=2,kb_fanbao=14,kb_brick_flip_green=13,kb_brick_consecutive=13,kb_brick_action=13,kb_brick_trend=13,kb_brick_action_desc=13,kb_sb1=8,kb_sb1_detailed=15,kb_nana=20,kb_didi=20,kb_centipede=21,kb_ready=30,kb_kirin_position=60,kb_kirin_vol=60,kb_hold_close_up=2,kb_hold_above_bbi=24,kb_hold_volume_ok=1,kb_hold_j_not_dead=9,kb_hold_score_min=1,kb_hold_score_max=1,kb_hold_score_status=1,kb_yidong_vol_ratio_5=6,kb_yidong_bullish_count_5=5,kb_yidong_is=65,kb_yidong_james=65,kb_yidong_type=65,kb_yidong_status=1,kb_yidong_ma60_distance_pct=60,kb_yidong_yellow_distance_pct=114,kb_yidong_vol_peak_5=5,kb_yidong_vol_peak_prior20=25,kb_yidong_peak_ratio_5_20=25,kb_yidong_price_volume_up_days_5=6,kb_yidong_phase_status=1,kb_yidong_rule_sha256=1,kb_yidong_above_60d=65,kb_double_gun_vol1=24,kb_double_gun_vol2=24,kb_double_gun_gap_days=24,kb_violence_k_type=21,kb_violence_k_body=21)
    rows=[]
    for name,sp in sorted(schema.items(),key=lambda kv:kv[1]['ordinal']):
        hits=[e for n,e in indexed if n==name]
        owner=native;fn='compute'
        if name.startswith('kb_macd_') or name.startswith('kb_yidong_') and name!='kb_yidong_above_60d' or name in ('kb_rsl_short','kb_rsl_long','kb_kirin_position','kb_kirin_vol'):owner=foundation;fn='project_history'
        if name.startswith('kb_hold_'):owner=score;fn='score_at'
        if name.startswith('kb_action_'):owner=actions;fn='project_actions'
        if name in ('kb_fanbao','kb_brick_trend','kb_brick_action_desc','kb_brick_flip_green','kb_brick_action','kb_brick_consecutive','kb_double_gun_vol1','kb_double_gun_vol2','kb_double_gun_gap_days','kb_yidong_above_60d','kb_violence_k_type','kb_violence_k_body'):owner=kb8;fn='project_prefix'
        if name in ('kb_s1','kb_s2','kb_s3','kb_didi_1455','kb_concepts','kb_concept_count','kb_kirin_stage','kb_kirin_conf'):owner=unified/'producer.py';fn='compute'
        oe=functions(owner,par)[fn]
        formulas=[oe,functions(unified/'producer.py',par)['compute']]
        if owner==native:formulas.append(functions(unified/'native_adapter.py',par)['fast_adapted_source'])
        # Native detector definitions referenced by the field's source line are retained verbatim.
        names=set(re.findall(r'(?:layer|base|brick|helper|rope|complex_mod|core)\.([a-zA-Z_0-9]+)', '\n'.join(e['code'] for e in hits)))
        if name.startswith('kb_b1'):names.add('detect_b1_today')
        if name.startswith('kb_b2'):names.add('detect_b2_today')
        for funcs in sources.values():
            for called in names:
                if called in funcs and funcs[called] not in formulas:formulas.append(funcs[called])
        candidate=candidates.get(name);present={r:c[candidate] for r,c in cols.items() if candidate in c} if candidate else {}
        ve=[evidence(vformula,i,i) for i,l in enumerate(vlines,1) if candidate and ('"'+candidate+'"' in l or '"'+('BBI' if candidate=='bbi' else 'kdj_'+candidate.lower() if candidate in ('K','D') else candidate)+'"' in l)]
        typ=sp['type'].rstrip('?')
        unit='boolean' if typ=='bool' else 'enum/text/hash' if typ=='string' else 'count/score (see source)' if typ.startswith('int') else 'CANNOT_CONFIRM'
        if name in ('kb_hold_bbi',):unit='same as input close; currency/adjustment CANNOT_CONFIRM'
        if name in ('kb_hold_k','kb_hold_d','kb_b1_j','kb_b2_j','kb_rsl_short','kb_rsl_long','kb_brick_value'):unit='dimensionless oscillator points'
        if name.endswith(('pct_chg','amplitude','distance_pct','_body')):unit='percent (source expression included)'
        if name in ('kb_yidong_vol_ratio_5','kb_yidong_peak_ratio_5_20','kb_double_gun_vol1','kb_double_gun_vol2'):unit='dimensionless volume ratio'
        if name in ('kb_yidong_vol_peak_5','kb_yidong_vol_peak_prior20'):unit='input volume units; absolute source unit CANNOT_CONFIRM'
        if name=='kb_yidong_phase_anchor_date':unit='YYYYMMDD when known; supplied kernel always UNKNOWN'
        rows.append(dict(field=name,ordinal=sp['ordinal'],par_type=sp['type'],comparison='DIFFERENT' if name in reasons and present else 'UNKNOWN',
          reason=reasons.get(name,'No proven semantically identical V4 233/85 counterpart; field-name similarity does not establish equivalence.'),
          v4_candidate=candidate,v4_candidate_roles_and_types=present,par_unit=unit,
          input_basis='Supplied Par bound same-source OHLCV prefix; source.normalize derives pct from Decimal close ratio. Native consumes float64. Adjustment/PIT/suspension CANNOT_CONFIRM without source bindings.',
          warmup=dict(minimum_rows=gates.get(name),unknown_if_unspecified=True,authoritative_rule='Necessary startup minimum only, not proof value becomes known. Verbatim owner/detector and composition gates below control all conditional/UNKNOWN branches.'),
          precision_rounding='Native primitive Python binary float64; explicit round(...,2) retained in formula evidence. Scoring also Decimal(str(value)); exact context/version is source bound. UNKNOWN is not false.',
          formula_evidence=formulas,field_occurrence_evidence=hits,v4_formula_evidence=ve))
    assert len(rows)==109 and len({r['field'] for r in rows})==109
    output.mkdir(parents=True,exist_ok=True)
    payload=dict(schema='par109.v4_mapping.v1',status='MAPPING_COMPLETE_COMPATIBILITY_NOT_ESTABLISHED',
      original_schema=evidence(schema_path,root=par),v4_schema_binding=dict(path=str(sf),sha256=sha(sf),roles={r:len(c) for r,c in cols.items()}),
      source_root=str(par),v4_source_root=str(v4),counts=dict(Counter(r['comparison'] for r in rows)),
      exact_means='Same formula, arithmetic, initialization, warmup, basis, type/rounding and proven output parity; zero EXACT claims here.',rows=rows)
    (output/'PAR109_TO_V4_MAPPING.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
    with (output/'PAR109_TO_V4_MAPPING.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=['ordinal','field','par_type','comparison','v4_candidate','reason','par_unit','minimum_rows','source_sha256','source_lines'])
        w.writeheader()
        for r in rows:
            e=r['formula_evidence'][0]
            w.writerow({**{k:r[k] for k in ('ordinal','field','par_type','comparison','v4_candidate','reason','par_unit')},'minimum_rows':r['warmup']['minimum_rows'],'source_sha256':e['sha256'],'source_lines':str(e['lines'])})
    print(json.dumps(dict(rows=109,counts=payload['counts'],json_sha256=sha(output/'PAR109_TO_V4_MAPPING.json'))))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--par',type=Path,required=True);p.add_argument('--v4',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();build(a.par,a.v4,a.output)
