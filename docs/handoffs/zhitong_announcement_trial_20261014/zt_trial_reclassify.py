#!/usr/bin/env python3
"""Offline, deterministic title/digest candidate flags for the saved trial."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path


OUT = Path(__file__).resolve().parent
ARTICLES_JSON = OUT / 'articles_window.json'
RECEIPT_JSON = OUT / 'trial_receipt.json'
FLAG_KEYS = [
    'quantified_order_contract_candidate',
    'earnings_improvement_candidate',
    'approved_commercialization_candidate',
    'material_transaction_candidate',
    'expanded_buyback_plan_candidate',
    'routine_daily_buyback',
    'excluded_non_catalyst_tags',
    'core_candidate_flag',
    'review_candidate_flag',
    'candidate_rule_note',
]


def candidate_flags(row: dict) -> dict:
    # Use the listing digest and title only. Full body text is retained for
    # human review but can mention unrelated matters and is not a flag input.
    text = f"{row.get('title') or ''} {row.get('digest') or ''}"
    quantified = bool(
        re.search(r'订单|合同|合约|订立|签订|中标|供货|采购|EPC|销售协议|销售合同', text, re.I)
        and re.search(r'\d[\d,.]*\s*(?:亿元|亿港元|亿港币|亿元人民币|万元|万港元|万港币|万美元|百万|千万|港元|人民币|美元)', text)
    )
    earnings = bool(re.search(r'发盈喜|预增|扭亏|净利润.{0,12}(?:同比)?(?:增长|上升|增加)|盈利.{0,12}增长|收入.{0,12}增长|业绩.{0,12}(?:增长|改善|大增)', text))
    approval = bool(
        re.search(r'获批|获准|获得.{0,8}批准|批准.{0,8}(?:上市|注册|商业化)|授出.{0,8}上市批准|获发.{0,8}注册证明书|取得.{0,8}注册证明书|获颁.{0,8}注册证', text)
        and re.search(r'药|医疗|注册证|上市许可|商业化|产品|药品|生物', text)
    )
    transaction = bool(
        re.search(r'收购|出售|转让|投资|注资|并购|合资|资产交易|股权交易|购入|收购事项', text)
        and re.search(r'\d[\d,.]*\s*(?:亿元|亿港元|亿港币|亿元人民币|万元|万港元|万港币|万美元|百万|千万|港元|人民币|美元)', text)
    )
    buyback = bool(re.search(r'回购|购回', text))
    buyback_plan = bool(buyback and re.search(r'计划|授权|扩大|增加|调整|最高|不超过|额度|延长', text))
    routine_buyback = bool(buyback and not buyback_plan and re.search(r'斥资|耗资|购回.{0,12}股|回购.{0,12}股|今日|当日|10月\d{1,2}日', text))
    excluded = []
    if re.search(r'配售|配股|供股|认购|融资|发行.{0,20}(?:债券|票据|公司债|优先股)|可续期公司债|配售股份|发行新股', text):
        excluded.append('financing')
    if re.search(r'全流通', text):
        excluded.append('full_float')
    if re.search(r'委任|获委任|辞任|辞职|核数师|董事会主席|任命', text):
        excluded.append('personnel')
    eligible = not excluded
    core = eligible and (quantified or earnings or approval or transaction)
    review = eligible and (core or buyback_plan)
    return {
        'quantified_order_contract_candidate': quantified,
        'earnings_improvement_candidate': earnings,
        'approved_commercialization_candidate': approval,
        'material_transaction_candidate': transaction,
        'expanded_buyback_plan_candidate': buyback_plan,
        'routine_daily_buyback': routine_buyback,
        'excluded_non_catalyst_tags': excluded,
        'core_candidate_flag': bool(core),
        'review_candidate_flag': bool(review),
        'candidate_rule_note': 'title+digest keyword/amount screen only; no semantic judgment; human review and original-filing verification required',
    }


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            flat = dict(row)
            body = row.get('body') or {}
            flat.update({k: body.get(k) for k in ('body_fetch_status', 'body_text', 'body_text_chars', 'body_text_utf8_bytes', 'body_html', 'digest_html')})
            flat['hkconnect_matched_codes'] = ';'.join(row.get('hkconnect_matched_codes') or [])
            flat['excluded_non_catalyst_tags'] = ';'.join(row.get('excluded_non_catalyst_tags') or [])
            flat['author_info'] = json.dumps(row.get('author_info'), ensure_ascii=False, separators=(',', ':'))
            raw_meta = row.get('raw_api_metadata')
            if raw_meta is not None:
                flat['raw_metadata_json'] = json.dumps(raw_meta, ensure_ascii=False, separators=(',', ':'))
            writer.writerow(flat)


def main() -> None:
    raw = ARTICLES_JSON.read_bytes()
    rows = json.loads(raw.decode('utf-8'))
    old_counts = {key: sum(bool(row.get(key)) for row in rows) for key in FLAG_KEYS if key.endswith('_candidate') or key in {'core_candidate_flag', 'review_candidate_flag', 'routine_daily_buyback'}}
    for row in rows:
        row['initial_body_keyword_flags_v0'] = {key: row.get(key) for key in FLAG_KEYS}
        row.update(candidate_flags(row))
    ARTICLES_JSON.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    title_fields = [
        'content_id', 'title', 'stock_list', 'hkconnect_match', 'hkconnect_matched_codes',
        'publish_time_iso_shanghai', 'create_time_iso_shanghai', 'update_time_iso_shanghai', 'digest',
        'core_candidate_flag', 'review_candidate_flag', 'quantified_order_contract_candidate',
        'earnings_improvement_candidate', 'approved_commercialization_candidate',
        'material_transaction_candidate', 'expanded_buyback_plan_candidate',
        'routine_daily_buyback', 'excluded_non_catalyst_tags', 'body_fetch_status',
    ]
    write_csv(OUT / 'titles_for_semantic_review.csv', rows, title_fields)
    all_fields = [
        'content_id', 'title', 'category_name', 'stock_list', 'hkconnect_match', 'hkconnect_matched_codes',
        'publish_time', 'publish_time_iso_shanghai', 'create_time', 'create_time_iso_shanghai',
        'update_time', 'update_time_iso_shanghai', 'digest', 'url', 'keywords', 'author_info',
        'body_fetch_status', 'body_text', 'body_text_chars', 'body_text_utf8_bytes', 'body_html', 'digest_html',
        'core_candidate_flag', 'review_candidate_flag', 'quantified_order_contract_candidate',
        'earnings_improvement_candidate', 'approved_commercialization_candidate',
        'material_transaction_candidate', 'expanded_buyback_plan_candidate',
        'routine_daily_buyback', 'excluded_non_catalyst_tags', 'raw_metadata_json',
    ]
    write_csv(OUT / 'articles_window.csv', rows, all_fields)

    new_counts = {
        'hk_announcement_window_rows': len(rows),
        'stockconnect_matched_rows': sum(bool(row.get('hkconnect_match')) for row in rows),
        'core_candidate_flag_rows': sum(bool(row.get('core_candidate_flag')) for row in rows),
        'review_candidate_flag_rows': sum(bool(row.get('review_candidate_flag')) for row in rows),
        'quantified_order_contract_candidate_rows': sum(bool(row.get('quantified_order_contract_candidate')) for row in rows),
        'earnings_improvement_candidate_rows': sum(bool(row.get('earnings_improvement_candidate')) for row in rows),
        'approved_commercialization_candidate_rows': sum(bool(row.get('approved_commercialization_candidate')) for row in rows),
        'material_transaction_candidate_rows': sum(bool(row.get('material_transaction_candidate')) for row in rows),
        'expanded_buyback_plan_candidate_rows': sum(bool(row.get('expanded_buyback_plan_candidate')) for row in rows),
        'routine_daily_buyback_rows': sum(bool(row.get('routine_daily_buyback')) for row in rows),
        'body_extracted_rows': sum((row.get('body') or {}).get('body_fetch_status') == 'extracted' for row in rows),
        'body_failed_or_skipped_rows': sum((row.get('body') or {}).get('body_fetch_status') != 'extracted' for row in rows),
    }
    receipt = json.loads(RECEIPT_JSON.read_text(encoding='utf-8'))
    receipt['counts'].update(new_counts)
    receipt['candidate_semantics'] = 'Final flags use title and digest only, with amount-plus-event screens for contracts and transactions. Core candidate excludes financing, personnel, and full-float notices. Expanded buyback plans are separate review candidates; routine daily buybacks are separate. Flags are not a final financial ranking. Original filings were not all cross-checked.'
    receipt['classification_reconciliation'] = {
        'pass_type': 'offline post-process of the saved capture; no network requests',
        'input_sha256_before_reclassification': hashlib.sha256(raw).hexdigest(),
        'classifier': str(OUT / 'zt_trial_reclassify.py'),
        'classifier_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'candidate_fields_used': ['title', 'digest'],
        'body_text_used_for_flags': False,
        'old_body_keyword_flag_counts': old_counts,
        'final_title_digest_flag_counts': {key: value for key, value in new_counts.items() if key.endswith('_rows') and ('candidate' in key or 'buyback' in key)},
        'rules': [
            'quantified contract/order requires a contract/order term and a numeric monetary amount',
            'earnings flag requires explicit improvement language',
            'approved-commercialization flag requires approval/registration language and a relevant product/medical term',
            'material-transaction flag requires a transaction term and numeric monetary amount',
            'financing, personnel, and full-float notices are excluded from core candidates',
            'expanded buyback plans are separate review candidates; routine daily repurchases are not core candidates',
        ],
    }
    RECEIPT_JSON.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'input_sha256': receipt['classification_reconciliation']['input_sha256_before_reclassification'], 'old_counts': old_counts, 'new_counts': new_counts, 'body_coverage_complete': receipt['body_coverage_complete']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
