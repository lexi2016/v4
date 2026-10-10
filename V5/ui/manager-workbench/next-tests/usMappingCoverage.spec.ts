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
