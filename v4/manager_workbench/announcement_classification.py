"""Conservative, version-bound classification before announcement model admission.

Only complete, source-verified documents with full template coverage may bypass
model review. A classification is never a stock-selection/model conclusion.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from pathlib import Path
from typing import Any

VERSION = "announcement-classification-20261020-v2"
POLICY = {"version": VERSION, "mode": "CONSERVATIVE_FULL_BODY", "legacy_default": "MODEL_REVIEW",
          "classifier_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
MODEL = "MODEL_REVIEW"
ROUTINE = "SKIPPED_ROUTINE_BY_RULE"
STRUCTURED = "STRUCTURED_EVENT_ONLY"
QUARANTINE = "SOURCE_INCOMPLETE_QUARANTINED"
# Fingerprints are of public HKEX form boilerplate with ONLY validated typed
# fields removed. They are not hashes of issuers or announcement IDs.
REPURCHASE_TEMPLATE_SHA256 = frozenset({"faf8130c2dc7eeadb6ac89b9ab8cb457afe82defd78ebf61a59001e266dc6830"})
N = r"(?:[1-9]\d{0,2}(?:,\d{3})+|0|[1-9]\d*)(?:\.\d+)?(?![\d,.])"
D = r"\d{4}年\s*\d{1,2}月\s*\d{1,2}日"
RISK = re.compile(r"盈警|盈利警告|業績預告|业绩预告|違約|违约|訴訟|诉讼|停牌|復牌|复牌|清盤|清盘|核數師辭任|核数师辞任|重大不確定|重大不确定|profit\s*warning|default|litigation|suspension", re.I)


def policy() -> dict[str, str]:
    return dict(POLICY)


def frozen_policy(input_value: dict[str, Any], source_input: dict[str, Any] | None = None, *, allow_replay: bool = False) -> dict[str, str] | None:
    """Missing policy is legacy, including every pre-classification recovery."""
    value = input_value.get("classification_policy")
    if value is not None and value != POLICY:
        if not (allow_replay and isinstance(value, dict) and value.get('version') == VERSION
                and value.get('mode') == POLICY['mode']
                and re.fullmatch(r'[a-f0-9]{64}', str(value.get('classifier_sha256', '')))):
            raise ValueError("ANNOUNCEMENT_CLASSIFICATION_POLICY_UNSUPPORTED")
    if source_input is not None and value != source_input.get("classification_policy"):
        raise ValueError("ANNOUNCEMENT_CLASSIFICATION_RESUME_POLICY_CHANGED")
    return deepcopy(value)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _number(text: str, *, integer: bool = False) -> str:
    if not re.fullmatch(N, text):
        raise ValueError("NUMBER_AMBIGUOUS")
    value = Decimal(text.replace(",", ""))
    if not value.is_finite() or value < 0 or (integer and value != value.to_integral_value()):
        raise ValueError("NUMBER_AMBIGUOUS")
    return format(value, "f")


def _price_reconciles(price: str, amount: str, shares: str) -> bool:
    # Only rounding uncertainty at the price's printed decimal precision is
    # allowed. This is a source reconciliation bound, not a trading threshold.
    scale = len(price.partition('.')[2])
    half_unit = Decimal(1).scaleb(-scale) / 2
    return (Decimal(shares) > 0 and Decimal(price) > 0
            and abs(Decimal(amount)/Decimal(shares)-Decimal(price)) <= half_unit)


def _date(text: str) -> str:
    digits = re.findall(r"\d+", text)
    return date(*map(int, digits)).isoformat()


def _sub_one(text: str, expression: str, marker: str, *, flags: int = 0):
    matches = list(re.finditer(expression, text, flags))
    if len(matches) != 1:
        raise ValueError("TEMPLATE_FIELD_AMBIGUOUS")
    found = matches[0]
    return text[:found.start()] + marker + text[found.end():], found


def _form(body: str, publication_date: str, symbol: str) -> tuple[str, dict[str, Any]]:
    """Parse one HK ordinary-share repurchase table and unchanged issued capital.

    Every unmatched character is retained in the boilerplate fingerprint; no
    general free-text field or arbitrary numeric masking is allowed.
    """
    text = re.sub(r"\s+", " ", body).strip()
    text = re.sub(r"第\s*\d+\s*頁\s*共\s*\d+\s*頁\s*v\s*1\.3\.0", "", text)
    text, header = _sub_one(text, rf"公司名稱[:：]\s*(?P<issuer>[^:：]{{1,100}}?)\s*呈交日期[:：]\s*(?P<date>{D})", "<ISSUER_DATE>")
    if _SUBSTANTIVE.search(header['issuer']) or not re.fullmatch(r'[\u3400-\u9fffA-Za-z（）() ,.&-]{2,90}(?:有限公司|Limited)', header['issuer'].strip()):
        raise ValueError('ISSUER_FIELD_UNCOVERED')
    submitted = _date(header['date'])
    if submitted > publication_date or RISK.search(header['issuer']):
        raise ValueError("DATE_OR_ISSUER_AMBIGUOUS")
    code_matches = list(re.finditer(r"證券代號\s*\(如上市\)\s*(\d{5})\s*說明", text))
    if len(code_matches) != 2 or any("HK." + m[1] != symbol for m in code_matches):
        raise ValueError("SECURITY_AMBIGUOUS")
    text = re.sub(r"證券代號\s*\(如上市\)\s*\d{5}\s*說明", "<SECURITY>", text)
    balance = (rf"於下列日期開始時的結存\s*\(註1\)\s*(?P<start_date>{D})\s+"
               rf"(?P<issued>{N})\s+(?P<treasury>{N})\s+(?P<total>{N})\s+"
               rf"1\)\.\s*其他\s*\(請註明\)\s*(?:0\s+0\s*%\s*0\s+HKD\s+0|%)\s*"
               rf"(?:請)?見B部分\s*變動日期\s*(?P<change_date>{D})\s*"
               rf"於下列日期結束時的結存\s*\(註5及6\)\s*(?P<end_date>{D})\s+"
               rf"(?P<end_issued>{N})\s+(?P<end_treasury>{N})\s+(?P<end_total>{N})")
    text, balances = _sub_one(text, balance, "<UNCHANGED_BALANCES>")
    capital = {key: _number(balances[key], integer=True) for key in (
        "issued", "treasury", "total", "end_issued", "end_treasury", "end_total")}
    if (any(capital[key] != capital['end_' + key] for key in ('issued', 'treasury', 'total'))
            or Decimal(capital['issued']) + Decimal(capital['treasury']) != Decimal(capital['total'])):
        raise ValueError("CAPITAL_CHANGED_OR_INCONSISTENT")
    capital.update({key: _date(balances[key]) for key in ('start_date', 'change_date', 'end_date')})
    if not capital['start_date'] <= capital['change_date'] == capital['end_date'] <= submitted:
        raise ValueError("CAPITAL_DATE_INCONSISTENT")
    pending_pattern = (rf"(?P<index>\d+)\)\.\s*(?:已購回(?:作|以作)註銷但尚未註銷(?:的|之)股份|於(?P<label_date>{D})回購但尚未註銷的股份)\s*(?P<shares>{N})\s*"
                       rf"(?P<percent>{N})?\s*%\s*HKD\s*(?P<price>{N})\s*變動日期\s*(?P<date>{D})")
    pending_matches = list(re.finditer(pending_pattern, text))
    if not pending_matches:
        raise ValueError("PENDING_REPURCHASE_TABLE_MISSING")
    pending = []
    for index, item in enumerate(pending_matches, 1):
        if (int(item['index']) != index or _date(item['date']) > submitted
                or (item['label_date'] and _date(item['label_date']) != _date(item['date']))):
            raise ValueError("PENDING_REPURCHASE_AMBIGUOUS")
        pending.append({"shares": _number(item['shares'], integer=True), "share_unit": "shares",
                        "percent": _number(item['percent']) if item['percent'] else None,
                        "price": _number(item['price']), "currency": "HKD", "date": _date(item['date'])})
    first, last = pending_matches[0].start(), pending_matches[-1].end()
    if re.sub(pending_pattern, "", text[first:last]).strip():
        raise ValueError("PENDING_REPURCHASE_UNCOVERED_TEXT")
    text = text[:first] + "<PENDING_REPURCHASES>" + text[last:]
    purchase_pattern = (rf"1\)\.\s*(?P<date>{D})\s+(?P<shares>{N})\s*於本交易所進行\s*HKD\s*"
                        rf"(?P<high>{N})\s*HKD\s*(?P<low>{N})\s*HKD\s*(?P<amount>{N})\s*"
                        rf"合共購回股份總數\s*(?P<total_shares>{N})\s*合共付出的價格總額\s*\(元\)\s*HKD\s*"
                        rf"(?P<total_amount>{N})\s*購回股份\s*（擬註銷）數目\s*(?P<cancel>{N})\s*"
                        rf"購回股份\s*（擬持作庫存股份）\s*(?:0\s*)?數目")
    text, purchase = _sub_one(text, purchase_pattern, "<COMPLETED_REPURCHASE>")
    event = {key: _number(purchase[key], integer=key in ('shares', 'total_shares', 'cancel'))
             for key in ('shares', 'high', 'low', 'amount', 'total_shares', 'total_amount', 'cancel')}
    event.update({"date": _date(purchase['date']), "currency": "HKD", "share_unit": "shares", "price_unit": "HKD/share",
                  "amount_unit": "HKD", "cumulative_percent_unit": "percent", "event_type": "COMPLETED_ON_EXCHANGE_REPURCHASE"})
    if (event['shares'] != event['total_shares'] or event['shares'] != event['cancel']
            or event['amount'] != event['total_amount'] or Decimal(event['shares']) <= 0
            or not Decimal(event['low']) <= Decimal(event['amount']) / Decimal(event['shares']) <= Decimal(event['high'])
            or not event['date'] <= submitted):
        raise ValueError("REPURCHASE_TOTAL_OR_PRICE_INCONSISTENT")
    auth_patterns = {
        'authorization_date': rf"購回授權的決議獲通過的日期\s*({D})",
        'authorized_shares': rf"發行人可根據購回授權購回股份的總數\s*({N})",
        'cumulative_shares': rf"根據購回授權在本交易所或其他證券交易所購回股份的數目\s*\(a\)\s*({N})",
        'cumulative_percent': rf"佔購回授權的決議獲通過當日的已發行股份（不包括庫存股份）數目的百分比\s*({N})\s*%",
        'moratorium_until': rf"截至\s*({D})",
        'explanatory_letter_date': rf"而已呈交貴交易所日期為\s*({D})\s*的說明函件",
    }
    for field, pattern in auth_patterns.items():
        text, found = _sub_one(text, pattern, '<' + field.upper() + '>')
        event[field] = (_date(found[1]) if field.endswith('date') or field == 'moratorium_until'
                        else _number(found[1], integer=field.endswith('shares')))
    if (len({(item['date'],item['shares'],item['price']) for item in pending}) != len(pending)
            or sum(Decimal(item['shares']) for item in pending) > Decimal(capital['issued'])
            or any(item['percent'] is not None and Decimal(item['percent']) > 100 for item in pending)):
        raise ValueError('PENDING_TABLE_AMBIGUOUS')
    if not any(item['date'] == event['date'] and item['shares'] == event['shares']
               and Decimal(event['low']) <= Decimal(item['price']) <= Decimal(event['high'])
               and _price_reconciles(item['price'],event['amount'],event['shares']) for item in pending):
        raise ValueError("REPURCHASE_PENDING_FACTS_INCONSISTENT")
    if (not event['authorization_date'] <= event['date'] <= event['moratorium_until']
            or event['explanatory_letter_date'] > event['date']
            or Decimal(event['cumulative_shares']) > Decimal(event['authorized_shares'])
            or Decimal(event['cumulative_shares']) < Decimal(event['shares'])
            or Decimal(event['cumulative_percent']) > 100):
        raise ValueError("AUTHORIZATION_FACTS_INCONSISTENT")
    text, sender = _sub_one(text, r"呈交者[:：]\s*([\u3400-\u9fffA-Za-z·. ]{2,60})\s*\(姓名\)\s*職銜[:：]\s*(董事|公司秘書|董事會秘書|執行董事|財務總監)\s*\(董事、秘書或其他獲正式授權的人員\)", "<AUTHORIZED_SENDER>")
    return _digest(re.sub(r"\s+", "", text)), {"issuer": header['issuer'].strip(), "submitted_date": submitted,
        "symbol": symbol, "capital": capital, "pending_cancellation": pending, "events": [event],
        "signatory": sender[1].strip(), "signatory_role": sender[2]}


def _address(body: str, issuer: str) -> dict[str, str]:
    # A small complete grammar, not a bag of keywords. Unrecognized forms,
    # proxy resolutions and address announcements with additional business
    # statements keep model review. Address accepts only an English postal
    # line ending in Hong Kong with a street number and road/street label.
    text = re.sub(r"\s+", " ", body).strip()
    if not isinstance(issuer, str) or not issuer or len(issuer) > 80:
        raise ValueError("ISSUER_MISSING")
    expression = (rf"通訊地址變更 本公司謹此通知,?自(?P<effective>{D})起,?本公司之通訊地址更改為[:：]"
        rf"(?P<address>(?=[A-Za-z0-9 ,./#-]{{15,200}}[。.])(?=[^。]*[0-9])"
        rf"[A-Za-z0-9 ,./#-]+(?:Road|Street|Rd|St)[A-Za-z0-9 ,./#-]*Hong Kong)[。.]\s*"
        rf"本公司之電話、傳真及電郵地址維持不變。 承董事會命 {re.escape(issuer)} 公司秘書 "
        rf"(?P<sender>[\u3400-\u9fff]{{2,4}}) 香港,?(?P<published>{D})")
    found = re.fullmatch(expression, text)
    if found is None or re.search(r"profit|revenue|contract|loan|capital|dividend|loss|warning", found['address'], re.I):
        raise ValueError("ADDRESS_TEMPLATE_UNCOVERED")
    return {"event_type": "CORRESPONDENCE_ADDRESS_CHANGE", "address": found['address'],
        "effective_date": _date(found['effective']), "published_date": _date(found['published'])}


def classify(article: dict[str, Any], *, enabled_policy: dict[str, Any] | None) -> dict[str, Any]:
    meta = article.get('article_metadata') or {}
    body = article.get('article_body')
    record = {"schema": "v4.manager_workbench.announcement_classification.v1", "classifier_version": VERSION,
        "classifier_sha256": POLICY['classifier_sha256'],
        "article_id": article.get('article_id'), "source_sha256": article.get('source_sha256'),
        "body_sha256": article.get('body_sha256'), "publication_date": meta.get('publication_date'),
        "title": meta.get('title'), "symbol": meta.get('symbol'), "source_origins": deepcopy(meta.get('source_origins', [])),
        "pit_status": meta.get('pit_status', 'CANNOT_CONFIRM'), "route": MODEL,
        "analysis_status": "MODEL_REVIEW_REQUIRED", "model_analyzed": False,
        "reason_codes": [], "evidence": {}, "structured_events": []}
    if (not isinstance(body, str) or not body or _digest(body) != article.get('body_sha256')
            or not re.fullmatch(r'[a-f0-9]{64}', str(article.get('source_sha256', '')))):
        record.update(route=QUARANTINE, analysis_status=QUARANTINE, reason_codes=['SOURCE_INCOMPLETE_OR_SHA_MISMATCH'])
        return annotate_record(record, body)
    if enabled_policy is None:
        record['classifier_version'] = 'LEGACY_MODEL_ONLY'
        record['reason_codes'] = ['FROZEN_LEGACY_POLICY']
        return annotate_record(record, body)
    if enabled_policy != POLICY:
        raise ValueError('ANNOUNCEMENT_CLASSIFICATION_POLICY_UNSUPPORTED')
    gap = source_gap_reason(body)
    if gap:
        record.update(route=QUARANTINE, analysis_status=QUARANTINE, reason_codes=[gap])
        return annotate_record(record, body)
    record.update(document_type='UNKNOWN', event_tags=[], evidence_spans=[span(body)],
                  source_date=meta.get('publication_date'), body_publication_date='CANNOT_CONFIRM',
                  date_conflict='CANNOT_CONFIRM', unknowns=['HISTORICAL_CHANGE_NOT_ASSESSED'])
    title = re.sub(r'\s+', '', str(meta.get('title') or ''))
    try:
        if re.fullmatch(r'董事[会會][会會][议議](?:召[开開]日期|日期|通知|通告)', title):
            facts = _meeting(body, meta['publication_date'], meta['symbol'])
            record.update(route=ROUTINE, analysis_status=ROUTINE, document_type='MEETING_TIMING_ONLY',
                event_tags=['ADMINISTRATIVE_MEETING_DATE'], body_publication_date=facts['body_publication_date'],
                date_conflict=False, structured_events=[facts], reason_codes=['FULL_BODY_MEETING_GRAMMAR'],
                evidence={'full_body_coverage': True, 'grammar': 'BOARD_DATE_V2'})
            return annotate_record(record, body)
        date.fromisoformat(meta['publication_date'])
        if title in ('翌日披露报表', '翌日披露報表'):
            for parser, templates in ((_form, REPURCHASE_TEMPLATE_SHA256), (_treasury_form, TREASURY_TEMPLATE_SHA256)):
                try:
                    fingerprint, facts = parser(body, meta['publication_date'], meta['symbol'])
                except (ValueError, KeyError, TypeError, InvalidOperation):
                    continue
                if fingerprint in templates:
                    record.update(route=STRUCTURED, analysis_status=STRUCTURED,
                        reason_codes=['COMPLETE_STANDARD_REPURCHASE_TEMPLATE'], structured_events=[facts],
                        document_type='COMPLETED_REPURCHASE_FORM', event_tags=['COMPLETED_REPURCHASE'],
                        evidence={'full_body_template_sha256': fingerprint, 'full_body_coverage': True,
                                  'checks': ['SINGLE_SECURITY', 'NO_NEW_ISSUANCE', 'SHARES_AND_MONEY_RECONCILED',
                                             'EXISTING_AUTHORIZATION', 'NO_TREASURY_SALE', 'NO_UNCOVERED_TEXT']})
                    return annotate_record(record, body)
            record['reason_codes'] = ['TEMPLATE_PARSE_AMBIGUOUS_OR_INCOMPLETE']
            return annotate_record(record, body)
        if title in ('通訊地址變更', '通讯地址变更'):
            facts = _address(body, meta.get('issuer_name'))
            if facts['published_date'] != meta['publication_date']:
                raise ValueError('PUBLICATION_DATE_CONFLICT')
            record.update(route=ROUTINE, analysis_status=ROUTINE,
                reason_codes=['COMPLETE_CORRESPONDENCE_ADDRESS_GRAMMAR'], structured_events=[facts],
                evidence={'full_body_template': 'CORRESPONDENCE_ADDRESS_V1', 'full_body_coverage': True})
            return annotate_record(record, body)
    except (ValueError, KeyError, TypeError, InvalidOperation):
        record['reason_codes'] = ['TEMPLATE_PARSE_AMBIGUOUS_OR_INCOMPLETE']
        return annotate_record(record, body)
    risk = RISK.search(body)
    if risk:
        record['reason_codes'] = ['RISK_OR_SUBSTANTIVE_CONTENT']
        record['evidence'] = {'upgrade_token': risk.group(0)}
        return annotate_record(record, body)
    record['reason_codes'] = ['UNKNOWN_MIXED_OR_UNCOVERED_FULL_BODY']
    return annotate_record(record, body)


PLAN_SCHEMA = "v4.manager_workbench.announcement_classification_plan.v2"
_NUMERALS = dict(zip("零〇一二三四五六七八九", (0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9)))
_DATE_ANY = r"(?:\d{4}|[二零〇一三四五六七八九]{4})年(?:\d{1,2}|[一二三四五六七八九十]{1,3})月(?:\d{1,2}|[一二三四五六七八九十]{1,3})日"
_SUBSTANTIVE = re.compile(r"收購|收购|配售|增發|增发|供股|融資|融资|激勵|激励|違約|违约|訴訟|诉讼|盈警|盈喜|盈利預告|盈利预告|重大交易|中標|中标|簽訂|签订|出售資產|出售资产|控制權|控制权|淨利潤|净利润|虧損|亏损|營業收入|营业收入|profit\s*(?:warning|increase)|revenue", re.I)


def _cn_number(value: str) -> int:
    if value.isdigit():
        return int(value)
    if "十" in value:
        left, right = value.split("十")
        return (_NUMERALS.get(left, 1) * 10 + _NUMERALS.get(right, 0))
    return int("".join(str(_NUMERALS[x]) for x in value))


def _date_any(value: str) -> str:
    match = re.fullmatch(r"(.+)年(.+)月(.+)日", value)
    if not match:
        raise ValueError("DATE_AMBIGUOUS")
    return date(*(_cn_number(match[i]) for i in (1, 2, 3))).isoformat()


def span(body: str, start: int = 0, end: int | None = None, *, supports: str = "FULL_DOCUMENT") -> dict[str, Any]:
    end = len(body) if end is None else end
    return {"start_cp": start, "end_cp": end, "source_locator": f"article_body[codepoint:{start}:{end}]",
            "text_sha256": _digest(body[start:end]), "supports": supports}


def source_gap_reason(body: Any) -> str | None:
    if not isinstance(body, str) or not body.strip():
        return "BODY_MISSING"
    flat = re.sub(r"\s+", "", body)
    if (re.search(r"https?://[^\s<>]+\.pdf(?:\?[^\s<>]*)?", body, re.I)
            and re.search(r"(?:網址如下|网址如下|網站.*上載|网站.*上传|詳見.*連結|详见.*链接|availableat|followinglink)", flat, re.I)
            and len(flat) < 6000):
        return "EXTERNAL_BODY_LINK_ONLY"
    return None


def _meeting(body: str, publication_date: str, symbol: str) -> dict[str, Any]:
    """Whole-document grammar for board dates, never a title-only filter."""
    flat = re.sub(r"\s+", "", body)
    if _SUBSTANTIVE.search(flat) or RISK.search(flat):
        raise ValueError("SUBSTANTIVE_MEETING")
    title_re = r"董事會會議(?:召開日期|日期|通知|通告)"
    titles = list(re.finditer(title_re, flat))
    if len(titles) != 1 or flat.count("承董事會命") != 1:
        raise ValueError("MEETING_TEMPLATE_UNCOVERED")
    header = flat[:titles[0].start()]
    main, footer = flat[titles[0].end():].split("承董事會命")
    company = r"[\u3400-\u9fff（）()]{2,65}(?:股份有限公司|有限公司)"
    statement = (rf"(?P<issuer>{company})（「本公司」(?:，連同其附屬公司統稱「本集團」)?）(?:之)?"
        rf"董事(?:（「董事」）)?會（「董事會」）謹此(?:宣佈|公佈)，?(?:董事會會議|董事會)?將於"
        rf"(?P<meeting>{_DATE_ANY})（星期[一二三四五六日天]）(?:舉行董事會會議|召開董事會會議|舉行會議|舉行)，?"
        rf"(?:藉以|以)(?:（其中包括）)?(?:審議及批准|審議及通過|考慮及批准)(?:（其中包括）)?"
        rf"(?:本公司及其附屬公司|本集團|本公司)截至(?P<period>{_DATE_ANY})止(?:九個月|三個月)(?:期間)?(?:的|之)?"
        rf"(?:第三季度報告|第三季度業績|第三季季度業績|未經審核業績|未經審計之第三季度業績)"
        rf"(?:及其發佈|及╱或其他議題（如適用）)?(?:，?以及處理任何其他事項|及其他事項（如有）)?。")
    found = re.fullmatch(statement, main)
    if not found:
        raise ValueError("MEETING_MAIN_UNCOVERED")
    issuer = found['issuer']
    disclaimer = (r"香港交易及結算所有限公司及香港聯合交易所有限公司對本公告(?:的|之)內容概不負責，"
        r"對其準確性或完整性亦不發表任何聲明，並明確表示，?概不(?:對因本公告全部或任何部[份分]內容而產生或因倚賴該等內容而引致的|"
        r"就因本公告全部或任何部[份分]內容所產生或因倚賴該等內容而引致的|因本公告全部或任何部[份分]內容而產生或因依賴該等內容而引致的)任何損失承擔任何責任。")
    header = re.sub(disclaimer, "", header)
    header = header.replace(issuer, "")
    header = re.sub(r"（於(?:中華人民共和國|香港|開曼群島)(?:註冊)?成立(?:的|之)?(?:股份)?有限公司）", "", header)
    codes = re.findall(r"（股份代號[:：](\d{3,5})[）)]", header)
    if codes and any('HK.' + code.zfill(5) != symbol for code in codes):
        raise ValueError("MEETING_SECURITY_CONFLICT")
    header = re.sub(r"（股份代號[:：]\d{3,5}[）)]", "", header)
    if not re.fullmatch(r"(?:[A-Za-z.,()&\-]{2,120}(?:Limited|LIMITED|Ltd\.?|LTD\.?|Corp\.?|CORP\.?))?", header):
        raise ValueError("MEETING_HEADER_UNCOVERED")
    board = re.search(r"(?:於本公告(?:刊發)?日期|截至本公告日期|於本公告之日)", footer)
    if board is None:
        raise ValueError("MEETING_DIRECTOR_LIST_MISSING")
    signature, directors = footer[:board.start()], footer[board.start():]
    dates = re.findall(_DATE_ANY, signature)
    if len(dates) != 1 or _date_any(dates[0]) != publication_date:
        raise ValueError("MEETING_PUBLICATION_DATE_CONFLICT")
    signature = signature.replace(issuer, '').replace(dates[0], '')
    signature = re.sub(r"(?:中國(?:江蘇省無錫市|北京|，?深圳)?|香港)", "", signature)
    signature = re.sub(r"董事長、執行董事兼總經理|董事會主席|公司秘書|董事長|主席", "", signature)
    signature = re.sub(r"[，,·。]", "", signature)
    if not re.fullmatch(r"[\u3400-\u9fff]{2,5}", signature):
        raise ValueError("MEETING_SIGNATURE_UNCOVERED")
    # Only typed director identities/roles may follow. A financial sentence,
    # even without any listed risk keyword, leaves uncovered characters.
    for term in sorted(('於本公告刊發日期', '截至本公告日期', '於本公告日期', '於本公告之日',
        '本公司董事會的成員包括', '本公司董事會成員包括', '董事會成員包括', '董事會包括以下人士',
        '本公司獨立非執行董事為', '本公司非執行董事為', '本公司職工董事為', '獨立非執行董事為',
        '非執行董事為', '執行董事為', '職工董事為', '獨立非執行董事', '非執行董事', '執行董事',
        '職工董事', '董事為', '本公司', '以及', '及', '和', '為'), key=len, reverse=True):
        directors = directors.replace(term, '')
    directors = re.sub(r"[\u3400-\u9fff]{2,5}(?:先生|女士|博士|工程師)", "", directors)
    if re.sub(r"[，、；:：。()（）ivxⅠⅡⅢ]+", '', directors, flags=re.I):
        raise ValueError("MEETING_FOOTER_UNCOVERED")
    meeting, period = _date_any(found['meeting']), _date_any(found['period'])
    if not period <= publication_date < meeting:
        raise ValueError("MEETING_DATES_INCONSISTENT")
    return {"event_type": "BOARD_MEETING_TIMING_ONLY", "issuer": issuer, "meeting_date": meeting,
            "report_period_end": period, "body_publication_date": publication_date,
            "event_status": "FUTURE_ADMINISTRATIVE_MEETING", "substantive_results": "NOT_DISCLOSED"}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def seal_plan(catalogue: list[dict[str, Any]], *, capture_product: dict[str, Any],
              target_date: str, cutoff: Any, membership_gate: dict[str, Any],
              processing_contract: dict[str, Any], enabled_policy: dict[str, Any]) -> dict[str, Any]:
    from collections import Counter
    decisions = Counter(row['processing_disposition'] for row in catalogue)
    routes = Counter(row['route_group'] for row in catalogue if row['processing_disposition'] == 'NEW_INPUT')
    if sum(decisions.values()) != len(catalogue) or sum(routes.values()) != decisions.get('NEW_INPUT', 0):
        raise ValueError('CLASSIFICATION_ACCOUNTING_MISMATCH')
    return {'schema': PLAN_SCHEMA, 'policy': deepcopy(enabled_policy), 'capture_product': deepcopy(capture_product),
        'target_date': target_date, 'cutoff': cutoff,
        'membership_gate_sha256': hashlib.sha256(canonical_bytes(membership_gate)).hexdigest(),
        'processing_contract': deepcopy(processing_contract), 'items': catalogue,
        'preview': {'catalogue_rows': len(catalogue), 'processing_disposition_counts': dict(decisions),
            'new_input_route_counts': {route: routes.get(route, 0) for route in ('A', 'B', 'C', 'D')},
            'eligible_new_bypass_articles': sum(row['membership_status'] == 'IN' and row['route_group'] in {'A', 'B'}
                and row['processing_disposition'] == 'NEW_INPUT' for row in catalogue),
            'model_task_estimates': 'C_ONLY_FULL_BODY_PLANNING_FOLLOWS_FROZEN_CLASSIFICATION',
            'actual_model_savings': 'NOT_MEASURED_PREVIEW_ONLY'}}


TREASURY_TEMPLATE_SHA256 = frozenset({"4f3da4591817180bdc70d3172efe4027636e102447430afa0db38023af5113fb"})


def _treasury_form(body: str, publication_date: str, symbol: str) -> tuple[str, dict[str, Any]]:
    """Single completed repurchase held as treasury, with conserved capital."""
    text = re.sub(r"\s+", " ", body).strip()
    text = re.sub(r"第\s*\d+\s*頁\s*共\s*\d+\s*頁\s*v\s*1\.3\.0", "", text)
    text, head = _sub_one(text, rf"公司名稱[:：]\s*(?P<issuer>[^:：]{{1,100}}?)\s*呈交日期[:：]\s*(?P<date>{D})", '<ISSUER_DATE>')
    if _SUBSTANTIVE.search(head['issuer']) or not re.fullmatch(r'[\u3400-\u9fffA-Za-z（）() ,.&-]{2,90}(?:有限公司|Limited)', head['issuer'].strip()):
        raise ValueError('ISSUER_FIELD_UNCOVERED')
    submitted = _date(head['date'])
    if submitted > publication_date:
        raise ValueError('SUBMISSION_DATE_CONFLICT')
    codes = re.findall(r"證券代號\s*\(如上市\)\s*(\d{5})\s*說明", text)
    classes = re.findall(r"股份類別\s*(不適用|H)\s*於香港聯交所上市\s*是", text)
    if len(codes) != 2 or len(classes) != 2 or len(set(classes)) != 1 or any('HK.'+x != symbol for x in codes):
        raise ValueError('SECURITY_OR_CLASS_AMBIGUOUS')
    text = re.sub(r"證券代號\s*\(如上市\)\s*\d{5}\s*說明", '<SECURITY>', text)
    text = re.sub(r"股份類別\s*(不適用|H)\s*於香港聯交所上市\s*是", '<LISTED_ORDINARY_CLASS>', text)
    pattern = (rf"於下列日期開始時的結存\s*\(註1\)\s*(?P<start>{D})\s+"
        rf"(?P<issued>{N})\s+(?P<treasury>{N})\s+(?P<total>{N})\s+"
        rf"1\)\.\s*購回股份\s*\(股份被持作庫存股份\)\s*-(?P<change>{N})\s+"
        rf"(?P<percent>{N})\s*%\s*(?P<added>{N})\s*HKD\s*(?P<average>{N})\s*"
        rf"變動日期\s*(?P<changed>{D})\s*於下列日期結束時的結存\s*\(註5及6\)\s*(?P<end>{D})\s+"
        rf"(?P<end_issued>{N})\s+(?P<end_treasury>{N})\s+(?P<end_total>{N})")
    text, balance = _sub_one(text, pattern, '<TREASURY_TRANSFER_BALANCES>')
    cap = {k: _number(balance[k], integer=k not in {'percent', 'average'}) for k in
        ('issued','treasury','total','change','percent','added','average','end_issued','end_treasury','end_total')}
    if (Decimal(cap['change']) <= 0 or cap['change'] != cap['added'] or cap['total'] != cap['end_total']
        or Decimal(cap['issued']) - Decimal(cap['change']) != Decimal(cap['end_issued'])
        or Decimal(cap['treasury']) + Decimal(cap['change']) != Decimal(cap['end_treasury'])
        or Decimal(cap['issued']) + Decimal(cap['treasury']) != Decimal(cap['total'])
        or Decimal(cap['end_issued']) + Decimal(cap['end_treasury']) != Decimal(cap['end_total'])):
        raise ValueError('CAPITAL_RECONCILIATION_FAILED')
    cap.update({k:_date(balance[k]) for k in ('start','changed','end')})
    cap.update(share_unit='shares',percent_unit='percent',average_price_unit='HKD/share')
    if not cap['start'] <= cap['changed'] == cap['end'] <= submitted:
        raise ValueError('CAPITAL_DATES_AMBIGUOUS')
    # No pending-cancellation row or alternative capital event may be hidden here.
    text, _ = _sub_one(text, r"B\.\s*贖回/購回股份\s*\(擬註銷但截至期終結存日期尚未註銷\)\s*\(註5及6\)\s*確認", '<NO_PENDING_CANCELLATION>')
    pattern = (rf"1\)\.\s*(?P<date>{D})\s+(?P<shares>{N})\s*於本交易所進行\s*HKD\s*"
        rf"(?P<high>{N})\s*HKD\s*(?P<low>{N})\s*HKD\s*(?P<amount>{N})\s*"
        rf"合共購回股份總數\s*(?P<total_shares>{N})\s*合共付出的價格總額\s*\(元\)\s*HKD\s*(?P<total_amount>{N})\s*"
        rf"購回股份\s*（擬註銷）數目\s*(?:0\s*)?購回股份\s*（擬持作庫存股份）\s*(?P<held>{N})\s*數目")
    text, purchase = _sub_one(text, pattern, '<COMPLETED_TREASURY_REPURCHASE>')
    event = {k:_number(purchase[k], integer=k in {'shares','total_shares','held'}) for k in
             ('shares','high','low','amount','total_shares','total_amount','held')}
    event.update(date=_date(purchase['date']), currency='HKD', share_unit='shares', amount_unit='HKD',
        price_unit='HKD/share', cumulative_percent_unit='percent',
        event_type='COMPLETED_ON_EXCHANGE_REPURCHASE', event_status='HELD_AS_TREASURY',
        issued_capital_change='NO_NEW_ISSUANCE', cancellation='NONE')
    if (event['shares'] != cap['change'] or event['held'] != event['shares'] or event['total_shares'] != event['shares']
        or event['amount'] != event['total_amount'] or event['date'] != cap['changed']
        or Decimal(cap['percent']) > 100
        or not _price_reconciles(cap['average'],event['amount'],event['shares'])
        or not Decimal(event['low']) <= Decimal(cap['average']) <= Decimal(event['high'])
        or not Decimal(event['low']) <= Decimal(event['amount'])/Decimal(event['shares']) <= Decimal(event['high'])):
        raise ValueError('CROSS_TABLE_REPURCHASE_CONFLICT')
    auth = {
        'authorization_date':rf"購回授權的決議獲通過的日期\s*({D})",
        'authorized_shares':rf"發行人可根據購回授權購回股份的總數\s*({N})",
        'cumulative_shares':rf"根據購回授權在本交易所或其他證券交易所購回股份的數目\s*\(a\)\s*({N})",
        'cumulative_percent':rf"佔購回授權的決議獲通過當日的已發行股份（不包括庫存股份）數目的百分比\s*({N})\s*%",
        'moratorium_until':rf"截至\s*({D})",
        'explanatory_letter_date':rf"而已呈交貴交易所日期為\s*({D})\s*的說明函件"}
    for k,p in auth.items():
        text,m = _sub_one(text,p,'<'+k.upper()+'>')
        event[k] = _date(m[1]) if k.endswith('date') or k == 'moratorium_until' else _number(m[1], integer=k.endswith('shares'))
    if (not event['authorization_date'] <= event['date'] <= event['moratorium_until']
        or event['explanatory_letter_date'] > event['date']
        or not Decimal(event['shares']) <= Decimal(event['cumulative_shares']) <= Decimal(event['authorized_shares'])
        or Decimal(event['cumulative_percent']) > 100):
        raise ValueError('AUTHORIZATION_FACTS_INCONSISTENT')
    text,sender = _sub_one(text,r"呈交者[:：]\s*([\u3400-\u9fffA-Za-z·. ]{2,60})\s*\(姓名\)\s*職銜[:：]\s*(董事|公司秘書|董事會秘書|執行董事|財務總監)\s*\(董事、秘書或其他獲正式授權的人員\)", '<AUTHORIZED_SENDER>')
    return _digest(re.sub(r'\s+','',text)), {'issuer':head['issuer'].strip(), 'submitted_date':submitted,
        'symbol':symbol,'share_class':classes[0], 'capital':cap,'events':[event], 'signatory':sender[1].strip()}


def annotate_record(record: dict[str, Any], body: Any) -> dict[str, Any]:
    record['route_group'] = {ROUTINE:'A', STRUCTURED:'B', MODEL:'C', QUARANTINE:'D'}[record['route']]
    record.setdefault('document_type', 'SOURCE_GAP' if record['route'] == QUARANTINE else 'UNKNOWN')
    record.setdefault('source_date', record.get('publication_date'))
    record.setdefault('body_publication_date', 'CANNOT_CONFIRM')
    record.setdefault('date_conflict', 'CANNOT_CONFIRM')
    record.setdefault('unknowns', ['HISTORICAL_CHANGE_NOT_ASSESSED'])
    record.setdefault('event_tags', [])
    record.setdefault('evidence_spans', [span(body)] if isinstance(body, str) and body else [])
    record['fact_evidence'] = []
    if not isinstance(body, str):
        return record
    for found in _SUBSTANTIVE.finditer(re.sub(r'\s+', '', body)):
        if record['route'] == MODEL:
            tag = 'SUBSTANTIVE_OR_MIXED_CONTENT'
            if tag not in record['event_tags']:
                record['event_tags'].append(tag)
    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():visit(item, path + '.' + key)
        elif isinstance(value, list):
            for index, item in enumerate(value):visit(item, path + f'[{index}]')
        elif isinstance(value, str) and value:
            candidates = []
            pattern = re.escape(value)
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
                y,m,d = map(int,value.split('-'));pattern=rf'{y}年\s*0?{m}月\s*0?{d}日'
            elif re.fullmatch(r'\d+(?:\.\d+)?', value):
                integer, dot, fraction = value.partition('.')
                groups=[]
                while integer:groups.insert(0,integer[-3:]);integer=integer[:-3]
                pattern=r'(?<![\d.,])'+',?'.join(groups)+(r'\.'+fraction if dot else '')+r'(?![\d.,])'
            for found in re.finditer(pattern,body):
                candidates.append(span(body,found.start(),found.end(),supports=path))
                if len(candidates)>=20:break
            record['fact_evidence'].append({'fact_path':path,'value':value,'candidate_source_spans':candidates,
                'evidence_kind':'SOURCE_LITERAL_IN_VALIDATED_GRAMMAR' if candidates else 'DERIVED_OR_NORMALIZED_FROM_VALIDATED_DOCUMENT',
                'document_evidence':span(body,supports=path)})
    visit(record.get('structured_events',[]),'structured_events')
    return record
