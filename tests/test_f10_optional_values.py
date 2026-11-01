import hashlib

from ops.research_panel_f10 import _comparison, _grab_optional, project_company_comparison, project_observed_history


class Source:
    @staticmethod
    def grab(text, label):
        return float(text[label])


def test_f10_placeholder_keeps_other_known_financial_values():
    text = {'eps': '-', 'roe': '3.2'}
    assert _grab_optional(Source, text, 'eps') is None
    assert _grab_optional(Source, text, 'roe') == 3.2


def test_historical_report_periods_keep_capture_and_unknown_publication_dates():
    text = '''｜★最新主要指标★｜2026-09-30｜2026-06-30｜
｜每股收益(元)｜-｜1.2｜
｜总股本(股)｜2亿｜1亿｜
｜★股东户数变化:截止2026-09-30,公司股东数10000,比上期(2026-06-30)减少100户｜
｜★最新公告:2026-10-20公司公告｜
【2.机构持股变化】
｜报告日期｜2026-09-30｜2026-06-30｜
｜基金持仓比例｜13.5%｜12%｜
【3.概念板块】'''
    snapshot = dict(symbol='600000.SH',status='OBSERVED',historical_PIT=False,
                    captured_at='2026-11-01T15:00:00+00:00',source_text=text,
                    source_text_sha256=hashlib.sha256(text.encode()).hexdigest())
    out = project_observed_history(snapshot)
    assert out['captured_at'] == snapshot['captured_at']
    assert out['financial_reports'][0]['report_period'] == '2026-06-30'
    assert out['financial_reports'][1]['values']['eps'] is None
    assert out['financial_reports'][1]['values']['total_share'] == 200000000
    assert out['financial_reports'][1]['values']['fund_hold_ratio_pct'] == 13.5
    assert out['financial_reports'][1]['publication_date'] is None
    assert out['holder_count']['previous_count'] == 10100
    assert out['announcements'][0]['publication_date'] == '2026-10-20'
    assert out['historical_PIT'] is False


def test_current_company_comparison_labels_cumulative_and_keeps_unknown_prior():
    text = '''｜★最新主要指标★｜2026-09-30｜2026-06-30｜
｜每股收益(元)｜1.4｜1.2｜
｜净资产收益率(%)｜10｜8｜
｜2026-09-30  营业总收入(元):2亿  同比增3.50%｜
｜2026-09-30  净利润(元):1000万  同比增4.00%｜
｜★股东户数变化:截止2026-09-30,公司股东数10000,比上期(2026-06-30)减少100户｜
｜【分红】:2025年度 10派2元 股权登记日: 2026-07-30 除权除息日: 2026-07-31｜
｜【分红】:2026半年度 利润不分配｜
【2.机构持股变化】
｜报告日期｜2026-09-30｜2026-06-30｜
｜基金持仓比例｜13.5%｜12%｜
【3.概念板块】'''
    snapshot = dict(symbol='600000.SH',status='OBSERVED',historical_PIT=False,
                    captured_at='2026-11-01T15:00:00+00:00',source_updated_date='2026-11-01',
                    finance_updated_date='20261009',financials={'holder_count':10050},source_text=text,
                    source_text_sha256=hashlib.sha256(text.encode()).hexdigest())
    company=project_company_comparison(snapshot);comparison=company['comparison']
    assert comparison['latest_report_period']=='2026-09-30' and comparison['prior_report_period']=='2026-06-30'
    assert round(comparison['financial_metrics']['eps']['absolute_change'],2)==.2
    assert comparison['financial_metrics']['eps']['basis']=='CUMULATIVE_VALUE_DIFFERENCE_NOT_QOQ_GROWTH'
    assert comparison['financial_metrics']['revenue_yi']['latest']==2
    assert comparison['financial_metrics']['revenue_yi']['status']=='UNKNOWN_PRIOR'
    assert comparison['holdings']['fund_hold_ratio_pct']['percentage_point_change']==1.5
    assert comparison['shareholder_count']['absolute_change']==-100
    assert comparison['shareholder_count']['source_comparison']=='DIFFERENT_VALUES_DIFFERENT_SOURCE_TIMES'
    assert comparison['single_quarter_values'].startswith('UNKNOWN')
    assert comparison['dividends']['latest']['report_period']=='2026-06-30'
    assert comparison['dividends']['prior']['ex_dividend_date']=='2026-07-31'
    assert comparison['dividends']['prior']['publication_date'] is None
    assert comparison['dividends']['content_changed'] is True


def test_loss_and_zero_bases_never_misstate_growth():
    narrowed=_comparison(-2,-4,basis='CUMULATIVE_VALUE_DIFFERENCE',unit='yuan',loss_sensitive=True)
    assert narrowed['absolute_change']==2 and narrowed['change_class']=='LOSS_NARROWED'
    assert narrowed['relative_change_pct'] is None
    assert narrowed['relative_status']=='NOT_MEANINGFUL_LOSS_OR_SIGN_CHANGE'
    turned=_comparison(3,-4,basis='CUMULATIVE_VALUE_DIFFERENCE',unit='yuan',loss_sensitive=True)
    assert turned['change_class']=='TURNED_PROFIT' and turned['relative_change_pct'] is None
    zero=_comparison(3,0,basis='CUMULATIVE_VALUE_DIFFERENCE',unit='yuan',loss_sensitive=True)
    assert zero['relative_status']=='UNKNOWN_ZERO_BASE'


def test_share_structure_date_is_not_a_new_financial_report():
    text='''｜★最新主要指标★｜2026-10-21｜2026-09-30｜2026-06-30｜
｜每股收益(元)｜-｜0.9｜0.4｜
｜总股本(股)｜7亿｜8亿｜8亿｜'''
    snapshot=dict(symbol='000716.SZ',status='OBSERVED',historical_PIT=False,
                  captured_at='2026-11-01T15:00:00+00:00',source_text=text,
                  source_text_sha256=hashlib.sha256(text.encode()).hexdigest())
    comparison=project_company_comparison(snapshot)['comparison']
    assert comparison['latest_report_period']=='2026-09-30'
    assert comparison['prior_report_period']=='2026-06-30'
    assert comparison['financial_metrics']['eps']['latest']==.9
    assert comparison['financial_metrics']['total_share']['latest_period']=='2026-10-21'
    assert comparison['financial_metrics']['total_share']['latest']==700000000
    assert comparison['financial_metrics']['total_share']['prior']==800000000
