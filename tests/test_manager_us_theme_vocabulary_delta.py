"""Focused R3 vocabulary adoption; synthetic issuer only, not a real beneficiary map."""
import pytest

from tests.test_us_relation_pipeline_r2 import cards, collect, material, us, REF
from v4.manager_research.research_evidence import US_LABEL_TO_MANAGER_THEMES


@pytest.mark.parametrize('label,term,theme',[
    ('生物医药','生物医药研发','BIOMEDICINE'),
    ('石油','原油炼化','OIL'),
])
def test_live_us_sector_label_enters_existing_subject_bound_theme_path(label,term,theme):
    assert US_LABEL_TO_MANAGER_THEMES.get(label)==(theme,)
    assert not collect([],us(label)).us_industry
    evidence=collect(cards(material(f'星海科技发布{term}业务订单增长公告。')),us(label))
    assert 'HK.01234' in evidence.us_industry
    relation=evidence.us_industry['HK.01234'][0]['hk_relation']
    assert relation['manager_theme']==theme
    assert relation['source_refs'][0]['payload_sha256']==REF['payload_sha256']
    assert relation['connect_eligibility']=='TARGET_DATE_NOT_CHECKED'
    assert not evidence.us_individual


@pytest.mark.parametrize('label,text',[
    ('生物医药','星海科技发布营业收入增长公告。生物医药行业上涨。'),
    ('石油','星海科技否认从事原油炼化业务。'),
    ('石油','星海科技发布收入公告。另一家公司从事原油炼化业务。'),
])
def test_vocabulary_does_not_create_unanchored_or_negated_issuer_relation(label,text):
    assert not collect(cards(material(text)),us(label)).us_industry
