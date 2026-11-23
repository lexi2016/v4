"""Frozen-label + saved-score same-exam scaffold. FIT=MODEL_LOAD=PREDICT=0.

Never opens the original sealed archive or decrypts anything. Whole-240 is
fail-closed until an explicit release receipt binds both supplied file hashes.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re

from ops.pft_act030_features import FLAGS

POS, NEG, EVENT = 'GOLD_POS_CORE', 'GOLD_NEG_HARD', 'STRUCTURE_EVENT_ONLY'
PENDING = 'PENDING_STAGE'
VETO = tuple(f'V{n:02}' for n in range(1, 7))
SUBTYPES = ('S-Pullback', 'S-ReAdvance', 'S-Rebuild')
SCORES = ('raw_S_lr', 'gated_S_lr', 'raw_S_rf', 'gated_S_rf')
THRESHOLD = .50
CALIB100_SHA = 'b8e51cf5223e462086532b5e39144c60b006106fb17ebe74e4c204138b8d07e4'
ASSESSMENT_SHA = '8fb226e6b9c9cdee1cdd4f37f0c1e130d9a52dde544262cab528f36e0a9b6aaf'
ID = re.compile(r'[0-9a-f]{24}')


def need(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def indexed(rows):
    result = {}
    for row in rows:
        eid = row['episode_id']
        need(bool(ID.fullmatch(eid)) and eid not in result, 'INVALID_OR_DUPLICATE_EPISODE_ID')
        result[eid] = row
    need(bool(result), 'EMPTY_INPUT')
    return result


def div(a, b):
    return a / b if b else None


def metrics(rows, score, ks=(20, 30, 50)):
    """ACT026 arithmetic/order retained; ranking unavailable when n<K."""
    ranked = sorted(rows, key=lambda r: (-float(r[score]), r['episode_id']))
    samples = [(float(r[score]), r['unanimous_gold_v1'] == POS) for r in ranked]
    positive = [x for x, y in samples if y]
    negative = [x for x, y in samples if not y]
    tp = sum(x >= THRESHOLD for x in positive)
    fp = sum(x >= THRESHOLD for x in negative)
    fn, tn = len(positive)-tp, len(negative)-fp
    n = len(samples)
    bins = []
    for i in range(5):
        items = [(x, y) for x, y in samples if min(int(x*5), 4) == i]
        if items:
            bins.append(dict(range=i, n=len(items), mean_score=sum(x for x, _ in items)/len(items),
                             positive_rate=sum(y for _, y in items)/len(items)))
    ranking = {}
    for k in ks:
        if n < k:
            ranking[str(k)] = None
            continue
        cut = samples[k-1][0]
        before = [y for x, y in samples if x > cut]
        ties = [y for x, y in samples if x == cut]
        left = k-len(before)
        hits = sum(y for _, y in samples[:k])
        ranking[str(k)] = dict(hits=hits, k=k, precision=hits/k, cut=cut,
                              boundary_tie_count=len(ties), boundary_tie_taken=left,
                              min_hits=sum(before)+max(0, left-(len(ties)-sum(ties))),
                              max_hits=sum(before)+min(left, sum(ties)))
    return dict(n=n, pos=len(positive), neg=len(negative), tp=tp, fp=fp, tn=tn, fn=fn,
                precision=div(tp, tp+fp), recall=div(tp, tp+fn), f1=div(2*tp, 2*tp+fp+fn),
                fpr=div(fp, fp+tn),
                auc=div(sum((p > q)+.5*(p == q) for p in positive for q in negative), len(positive)*len(negative)),
                brier=div(sum((x-y)**2 for x, y in samples), n),
                ece5=div(sum(b['n']*abs(b['mean_score']-b['positive_rate']) for b in bins), n),
                mean_score=div(sum(x for x, _ in samples), n), ranking=ranking, reliability_bins=bins)


def validate_scores(rows, score_pairs, gate_field='gate_reason', gate_policy='binary_zeroing'):
    need(gate_policy in ('binary_zeroing', 'provided_scores'), 'UNKNOWN_GATE_POLICY')
    need(bool(score_pairs), 'SCORE_PAIRS_REQUIRED')
    columns = [c for pair in score_pairs for c in pair]
    need(len(columns) == len(set(columns)), 'DUPLICATE_SCORE_COLUMN')
    for row in rows:
        need(bool(row.get(gate_field)), 'GATE_REASON_REQUIRED')
        for raw, gated in score_pairs:
            try:
                a, b = float(row[raw]), float(row[gated])
            except (ValueError, KeyError, TypeError) as e:
                raise ValueError('SCORE_NOT_NUMERIC') from e
            need(math.isfinite(a) and math.isfinite(b) and 0 <= a <= 1 and 0 <= b <= 1,
                 'SCORE_NONFINITE_OR_OUT_OF_RANGE')
            if gate_policy == 'binary_zeroing':
                need(b == (a if row[gate_field] == 'PASS' else 0), 'SAVED_GATE_INCONSISTENT')
    return columns


def same_exam(labels, predictions, expected_ids, score_pairs=(('raw_score', 'gated_score'),),
              *, gate_field='gate_reason', gate_policy='binary_zeroing'):
    """Join once by episode ID, with deterministic, identical eligible rows."""
    left, right = indexed(labels), indexed(predictions)
    need(set(left) == set(right) == set(expected_ids), 'EXACT_EPISODE_SET_REQUIRED')
    columns = validate_scores(right.values(), score_pairs, gate_field, gate_policy)
    merged = []
    for eid in sorted(left):
        l, p = left[eid], right[eid]
        need(l.get('unanimous_gold_v1', '') in ('', POS, NEG, EVENT, PENDING), 'INVALID_FROZEN_LABEL')
        amount = float(l['adv20_cny'])
        need(math.isfinite(amount) and amount >= 0, 'INVALID_FROZEN_ADV20')
        need(l.get('unanimous_pos_subtype', '') in ('', *SUBTYPES), 'INVALID_MATCHED_SUBTYPE')
        if l.get('unanimous_gold_v1') == NEG:
            need(l.get('chat_primary_veto') in VETO, 'HARD_NEG_PRIMARY_VETO_REQUIRED')
        for identity in ('security_id', 'D', 'board'):
            if identity in p:
                need(p[identity] == l.get(identity), 'SCORE_LABEL_IDENTITY_DRIFT')
        # Label fields can never be supplied/overwritten by a score file.
        merged.append({**l, **{c: float(p[c]) for c in columns}, 'gate_reason': p[gate_field]})
    exam = [r for r in merged if r['unanimous_gold_v1'] in (POS, NEG, EVENT)]
    binary = [r for r in exam if r['unanimous_gold_v1'] in (POS, NEG)]
    neg = [r for r in exam if r['unanimous_gold_v1'] == NEG]
    pos = [r for r in exam if r['unanimous_gold_v1'] == POS]
    for r in merged:
        for field in ('both_v_true', 'chat_v_true'):
            need(set(filter(None, r.get(field, '').split('|'))) <= set(VETO), 'INVALID_VETO_CODE')
    def rate(rows):
        return {c: dict(n=len(rows), hits=sum(r[c] >= THRESHOLD for r in rows),
                        rate=div(sum(r[c] >= THRESHOLD for r in rows), len(rows))) for c in columns}
    result = dict(schema='PFT_ACT030_SAME_EXAM_V1', threshold=THRESHOLD, fit=0, model_load=0,
                  predict=0, score_only=True, **FLAGS, authorized_n=len(merged),
                  gate_policy=gate_policy, consensus_primary={c: metrics(exam, c) for c in columns},
                  consensus_pos_neg_secondary={c: metrics(binary, c) for c in columns},
                  hard_neg_all=rate(neg),
                  hard_neg_by_both_v={v: rate([r for r in neg if v in r.get('both_v_true', '').split('|')]) for v in VETO},
                  hard_neg_by_chat_primary_v={v: rate([r for r in neg if r.get('chat_primary_veto') == v]) for v in VETO},
                  hard_neg_no_joint_v=rate([r for r in neg if not r.get('both_v_true')]),
                  pos_subtype={s: rate([r for r in pos if r.get('unanimous_pos_subtype') == (s if s != 'DISAGREE' else '')])
                               for s in (*SUBTYPES, 'DISAGREE')},
                  hard_neg_adv_ge_3e8=rate([r for r in neg if float(r['adv20_cny']) >= 3e8]),
                  events=rate([r for r in exam if r['unanimous_gold_v1'] == EVENT]))
    return result


def compare_act026(actual, expected):
    """Exact saved-score regression for all existing ACT026 metric fields."""
    def subset(a, e, at):
        if isinstance(e, dict):
            for key, value in e.items():
                need(key in a, 'ACT026_MISSING:'+at+'.'+key)
                subset(a[key], value, at+'.'+key)
        elif isinstance(e, list):
            need(a == e, 'ACT026_DRIFT:'+at)
        elif isinstance(e, (int, float)):
            need(a == e, 'ACT026_DRIFT:'+at)
        else:
            need(a == e, 'ACT026_DRIFT:'+at)
    for old, new in [('exam62', 'consensus_primary'), ('exam54', 'consensus_pos_neg_secondary'),
                     ('hard_neg_all', 'hard_neg_all'), ('hard_neg_by_both_v', 'hard_neg_by_both_v'),
                     ('hard_neg_by_chat_primary_v', 'hard_neg_by_chat_primary_v'),
                     ('hard_neg_no_joint_v', 'hard_neg_no_joint_v'), ('pos_subtype', 'pos_subtype'), ('events', 'events')]:
        subset(actual[new], expected[old], new)
    return dict(status='PASS_EXACT', source='ACT026 approved saved-score assessment',
                legacy_metric_groups=8, extra_ranking_k=50, fit=0, model_load=0, predict=0)


def read_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        need(reader.fieldnames and len(reader.fieldnames) == len(set(reader.fieldnames)), 'DUPLICATE_CSV_HEADER')
        return list(reader)


def validate_release(receipt, labels_path, predictions_path, n):
    need(n == 240 and receipt.get('scope') == 'ACT022_WHOLE240_SAME_EXAM' and
         receipt.get('explicit_user_release') is True and receipt.get('threshold') == THRESHOLD and
         receipt.get('fit_allowed') is False and receipt.get('labels_sha256') == sha(labels_path) and
         receipt.get('predictions_sha256') == sha(predictions_path), 'WHOLE240_NOT_RELEASED_OR_HASH_DRIFT')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--labels', required=True, type=Path)
    parser.add_argument('--predictions', type=Path)
    parser.add_argument('--expected-ids', type=Path, help='Frozen JSON array of episode IDs')
    parser.add_argument('--baseline-only', action='store_true')
    parser.add_argument('--act026-assessment', type=Path)
    parser.add_argument('--release-receipt', type=Path)
    parser.add_argument('--raw-column', default='raw_score')
    parser.add_argument('--gated-column', default='gated_score')
    parser.add_argument('--gate-field', default='gate_reason')
    parser.add_argument('--gate-policy', choices=['binary_zeroing', 'provided_scores'], default='provided_scores')
    parser.add_argument('--baseline', type=Path, help='Approved ACT026 saved-score CSV; defaults to --labels for current calibration')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    if args.release_receipt is not None:
        need(args.predictions is not None, 'RELEASE_REQUIRES_PREDICTIONS')
        validate_release(json.loads(args.release_receipt.read_text()), args.labels, args.predictions, 240)
    else:
        need(sha(args.labels) == CALIB100_SHA, 'ONLY_APPROVED_CALIB100_LABELS_CURRENTLY_RELEASED')
    labels = read_csv(args.labels)
    if args.release_receipt is not None:
        need(len(labels) == 240, 'WHOLE240_RELEASE_REQUIRES_ACTUAL240_LABELS')
    if args.baseline_only:
        need(len(labels) == 100 and all(r.get('calib_100') == 'true' for r in labels), 'BASELINE_ONLY_CALIB100_REQUIRED')
        need(args.act026_assessment is not None and args.predictions is None, 'BASELINE_ONLY_REQUIRES_APPROVED_ASSESSMENT')
        need(sha(args.act026_assessment) == ASSESSMENT_SHA, 'ACT026_ASSESSMENT_SOURCE_DRIFT')
        predictions = labels
        pairs = (('raw_S_lr', 'gated_S_lr'), ('raw_S_rf', 'gated_S_rf'))
        expected_ids = set(indexed(labels))
    else:
        need(args.predictions is not None and args.expected_ids is not None, 'PREDICTIONS_AND_FROZEN_IDS_REQUIRED')
        predictions = read_csv(args.predictions)
        expected_ids = json.loads(args.expected_ids.read_text())
        need(isinstance(expected_ids, list) and len(expected_ids) == len(set(expected_ids)), 'INVALID_EXPECTED_IDS')
        pairs = ((args.raw_column, args.gated_column),)
        if len(labels) == 240:
            need(args.release_receipt is not None, 'WHOLE240_NOT_RELEASED')
            validate_release(json.loads(args.release_receipt.read_text()), args.labels, args.predictions, len(labels))
        else:
            need(len(labels) == 100, 'ONLY_CALIB100_OR_RELEASED240_ALLOWED')
    output = same_exam(labels, predictions, expected_ids, pairs,
        gate_field='gate_reason' if args.baseline_only else args.gate_field,
        gate_policy='binary_zeroing' if args.baseline_only else args.gate_policy)
    output['mode'] = 'BASELINE_ONLY_NO_CHALLENGER' if args.baseline_only else 'SAVED_CHALLENGER_SAME_EXAM'
    output['sources'] = dict(labels_sha256=sha(args.labels), predictions_sha256=sha(args.predictions or args.labels))
    if not args.baseline_only:
        baseline_path = args.baseline or args.labels
        if len(labels) == 100:
            need(sha(baseline_path) == CALIB100_SHA, 'APPROVED_ACT026_BASELINE_REQUIRED')
        else:
            release = json.loads(args.release_receipt.read_text())
            need(release.get('baseline_sha256') == sha(baseline_path), 'WHOLE240_BASELINE_NOT_RELEASED')
        baseline = read_csv(baseline_path)
        output['baseline'] = same_exam(labels, baseline, expected_ids, (('raw_S_lr', 'gated_S_lr'), ('raw_S_rf', 'gated_S_rf')))
        output['baseline']['source_sha256'] = sha(baseline_path)
        output['same_exam_id_set_verified'] = True
    if args.baseline_only:
        output['act026_regression'] = compare_act026(output, json.loads(args.act026_assessment.read_text()))
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n')
    return output


if __name__ == '__main__':
    main()
