import re

from ops.research_panel_f10 import fetch_one


class FakeApi:
    def __init__(self, text, finance):
        self.text = text
        self.finance = finance

    def connect(self, host, port):
        return True

    def get_company_info_category(self, market, code):
        assert (market, code) == (1, '688728')
        return [{'name': '最新提示', 'filename': 'company.dat', 'start': 0, 'length': len(self.text)}]

    def get_company_info_content(self, market, code, filename, start, length):
        return self.text

    def get_finance_info(self, market, code):
        return self.finance

    def disconnect(self):
        return None


class FakeFetch:
    @staticmethod
    def grab(text, label):
        match = re.search(re.escape(label) + r'[^｜]*｜\s*([-0-9.]+)', text)
        return float(match.group(1)) if match else None

    @staticmethod
    def concepts_from(section):
        return [{'name': '图像传感器', 'desc': '测试来源概念'}] if section else []


def source_text(eps='-', bps='1.25', roe='8.5'):
    return '\n'.join([
        '◇688728 格科微 更新日期：2026-11-19',
        '★最新主要指标★｜2026-06-30',
        f'每股收益(元)｜{eps}',
        f'每股净资产(元)｜{bps}',
        f'净资产收益率(%)｜{roe}',
        '【3.概念板块】',
        '｜图像传感器｜测试来源概念',
        '【4.风险提示】',
    ])


def api_factory(text):
    finance = {'code': '688728', 'market': 1, 'updated_date': '2026-11-19',
               'gudongrenshu': 12345, 'industry': 9}
    return lambda: FakeApi(text, finance)


def test_literal_dash_keeps_f10_snapshot_and_other_fields():
    value = fetch_one('688728.SH', 'SH', api_factory=api_factory(source_text()),
                      vendor=(FakeFetch, FakeFetch))

    assert value['status'] == 'OBSERVED'
    assert value['financials']['eps'] is None
    assert value['financials']['bps'] == 1.25
    assert value['financials']['roe_pct'] == 8.5
    assert value['financials']['holder_count'] == 12345
    assert value['concepts'] == [{'name': '图像传感器', 'desc': '测试来源概念'}]
    assert value['source_text'] == source_text()


def test_malformed_number_is_still_a_collector_failure():
    value = fetch_one('688728.SH', 'SH', api_factory=api_factory(source_text(bps='1..25')),
                      vendor=(FakeFetch, FakeFetch))

    assert value['status'] == 'FAILED'
    assert 'could not convert string to float' in value['reason']
