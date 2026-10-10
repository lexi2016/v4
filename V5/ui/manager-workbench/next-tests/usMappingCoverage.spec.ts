import { describe, expect, it } from 'vitest';
import { renderUsMappingCoverage } from './usMappingCoverage';

// Synthetic counts intentionally differ from the unverified live batch.
const diagnostics={schema_version:'v5.us_mapping_scope.v1',status:'PARTIAL',
  scope:'PINNED_REVIEWED_RELATIONS_WITHIN_CONFIGURED_US_SAMPLE',us_session_date:'20261009',
  reviewed_us_symbols:['SYN_A','SYN_B'],reviewed_us_symbol_count:2,
  configured_sample_count:34,rising_individual_count:9,assessed_rising_symbol_count:2,unassessed_rising_symbol_count:7,
  full_market_coverage:false,formal_eligible:false,natural_verified:false,
  reason_codes:['BROADER_US_HK_RELATIONS_NOT_ASSESSED','TARGET_DATE_ELIGIBILITY_CANNOT_CONFIRM']};
const render=(host:HTMLElement,value:unknown)=>renderUsMappingCoverage(host,{coverage_diagnostics:value});
describe('US coverage diagnostics',()=>{
  it('uses actual payload scope and counts without promoting research to formal selection',()=>{
    const host=document.createElement('section');render(host,diagnostics);
    expect(host.textContent).toContain('已审关系键 2');expect(host.textContent).toContain('SYN_A、SYN_B');
    expect(host.textContent).toContain('配置样本 34；上涨个股 9；已评估上涨个股 2；未评估上涨个股 7');
    expect(host.textContent).toContain(diagnostics.scope);expect(host.textContent).toContain('20261009');
    expect(host.textContent).toContain('CANNOT_CONFIRM');expect(host.textContent).toContain('natural_verified=false');
    expect(host.textContent).toContain('RESEARCH_SAVED_NOT_FORMAL_SELECTION');
    expect(host.textContent).toContain('BROADER_US_HK_RELATIONS_NOT_ASSESSED');
  });
  it('preserves valid zero separately from null, missing and invalid counts',()=>{
    const host=document.createElement('section');render(host,{...diagnostics,configured_sample_count:null,
      rising_individual_count:0,assessed_rising_symbol_count:undefined,unassessed_rising_symbol_count:-1});
    expect(host.textContent).toContain('配置样本 未知；上涨个股 0；已评估上涨个股 未知；未评估上涨个股 未知');
  });
  it('does not reuse stale values when unavailable or absent',()=>{
    const host=document.createElement('section');render(host,diagnostics);
    render(host,{...diagnostics,status:'CANNOT_CONFIRM'});
    expect(host.textContent).toContain('配置样本 未知');expect(host.textContent).not.toContain('配置样本 34');
    renderUsMappingCoverage(host,{});expect(host.textContent).toContain('已审关系键 未知');
    expect(host.textContent).not.toContain('SYN_A');
    renderUsMappingCoverage(host,undefined);expect(host.hidden).toBe(true);expect(host.textContent).toBe('');
  });
  it.each([{formal_eligible:true},{full_market_coverage:true},{natural_verified:true},{schema_version:'unexpected'}])('fails closed for incompatible diagnostics %o',patch=>{
    const host=document.createElement('section');render(host,{...diagnostics,...patch});
    expect(host.textContent).toContain('配置样本 未知');expect(host.textContent).toContain('合同不兼容');
    expect(host.textContent).not.toContain('natural_verified=true');
  });
  it('renders scope and reason text without HTML execution',()=>{
    const host=document.createElement('section');render(host,{...diagnostics,reason_codes:['<img src=x onerror=alert(1)>']});
    expect(host.querySelector('img')).toBeNull();expect(host.textContent).toContain('<img');
  });
});

describe('grouped current US match cards',()=>{
  const row=(hk:string,us:string)=>({hk_symbol:hk,hk_name:`示例${hk}`,us_symbol:us,change_pct:1.25,
    relationship_type:'PRODUCT_PEER',reason:'同业产品研究线索，不证明供货关系。',maturity:'原阶段说明',
    limitations:['目标日资格待确认'],official_sources:[{title:'公司官方报告',url:'https://example.com/very/long/report.pdf'},
      {title:'不安全链接',url:'javascript:alert(1)'}]});
  const mapping={coverage_diagnostics:diagnostics,daily_run:{status:'COMPLETED',matches:[
    row('HK.00001','SYN_A'),row('HK.00001','SYN_B'),row('HK.00002','SYN_C'),row('HK.00003','SYN_D')]}};
  it('groups four matches into three stocks without discarding either US clue or raw evidence',()=>{
    const host=document.createElement('section');renderUsMappingCoverage(host,mapping);
    expect(host.querySelectorAll('[data-us-hk-result]')).toHaveLength(3);
    const first=host.querySelector('[data-us-hk-result="HK.00001"]')!;
    expect(first.textContent).toContain('SYN_A +1.25% / SYN_B +1.25%');
    expect(first.textContent).toContain('产品同业（非供货关系）');
    expect(first.querySelectorAll('a')).toHaveLength(1);
    expect(first.querySelector('a')?.textContent).toBe('公司官方报告');
    expect(first.querySelector('a')?.getAttribute('rel')).toContain('noopener');
    expect(first.querySelector<HTMLDetailsElement>('details')?.open).toBe(false);
    expect(first.querySelector('pre')?.textContent).toContain('javascript:alert(1)');
    expect(host.querySelector<HTMLDetailsElement>(':scope > details')?.open).toBe(false);
    expect(host.querySelector(':scope > details pre')?.textContent).toContain('coverage_diagnostics');
  });
  it('distinguishes scoped valid empty from unavailable and clears prior cards',()=>{
    const host=document.createElement('section');renderUsMappingCoverage(host,mapping);
    renderUsMappingCoverage(host,{...mapping,daily_run:{status:'VALID_EMPTY',matches:[]}});
    expect(host.querySelectorAll('[data-us-hk-result]')).toHaveLength(0);
    expect(host.textContent).toContain('本次已审关系范围内无匹配港股');
    renderUsMappingCoverage(host,{...mapping,coverage_diagnostics:{...diagnostics,status:'CANNOT_CONFIRM'}});
    expect(host.querySelectorAll('[data-us-hk-result]')).toHaveLength(0);
    expect(host.textContent).toContain('本次没有可展示的已确认匹配结果，数量未知');
  });
});
