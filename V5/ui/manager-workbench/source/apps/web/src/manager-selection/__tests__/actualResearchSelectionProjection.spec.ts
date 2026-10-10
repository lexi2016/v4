// @vitest-environment jsdom
import {createHash} from 'node:crypto';
import {readFileSync,writeFileSync} from 'node:fs';
import {gunzipSync} from 'node:zlib';
import {describe,it,expect} from 'vitest';
import {validateManagerWorkspace} from '../../api/managerWorkspace';
import {renderResearchAttention} from '../researchAttention';
import {fixture,date} from './fixtures/issue8R2.fixture';

const artifactPath=process.env.OCT2_RESEARCH_SELECTION_PROJECTION;
const outputPath=process.env.OCT2_DTO_RENDER_RECEIPT;

describe('actual Oct 2 owner projection through the Manager DTO and renderer',()=>{
  it('validates and renders the complete owner-derived 689-row selection',()=>{
    if(!artifactPath)throw new Error('ORIGINAL_OCT2_RESEARCH_SELECTION_PROJECTION_REQUIRED');
    const compressed=readFileSync(artifactPath);
    const artifact=JSON.parse(gunzipSync(compressed).toString('utf8'));
    const envelope:any=fixture();
    envelope.market_screen=artifact.market_screen;
    envelope.research_attention=artifact.research_attention;
    envelope.selection_diagnostics=artifact.selection_diagnostics;

    const validated=validateManagerWorkspace(envelope,date);
    const host=document.createElement('section');
    (renderResearchAttention as any)(host,validated.research_attention,validated.us_market_attention,
      validated.selection_diagnostics);
    const ledger=validated.research_attention!.research_selection!;
    const counts=ledger.coverage;
    const decisions=host.querySelectorAll('.research-selection-decision');
    const topFive=artifact.summary.top_five;

    expect(counts.input_row_count).toBe(689);
    expect(counts.accounted_input_row_count).toBe(689);
    expect(counts.unique_decision_count).toBe(689);
    expect(counts.selected_count).toBe(58);
    expect(counts.near_watch_count).toBe(349);
    expect(counts.excluded_count).toBe(250);
    expect(counts.unresolved_count).toBe(32);
    expect(decisions).toHaveLength(689);
    expect(host.textContent).toContain('10/2研究候选');
    expect(host.textContent).toContain('HK.00291');
    expect(host.textContent).toContain('市场结构先行，缺公司级原因');
    expect(topFive).toHaveLength(5);
    expect(topFive.every((row:any)=>row.company_cause_present===false)).toBe(true);
    expect(ledger.formal_selection_input).toBe(false);
    expect(host.querySelector('button')).toBeNull();

    if(outputPath){
      writeFileSync(outputPath,JSON.stringify({
        schema_version:'manager.selection_completion.oct2_dto_render_receipt.v1',
        status:'PASS',
        artifact_path:artifactPath,
        artifact_sha256:createHash('sha256').update(compressed).digest('hex'),
        source_get_sha256:artifact.source.frozen_get_sha256,
        screen_input_identity:artifact.source.screen_input_identity,
        dto_validator:'validateManagerWorkspace',
        renderer:'renderResearchAttention',
        wrapper_fixture:'existing Issue8 R2 shell for surrounding fields; actual owner screen, research_attention, and frozen membership with current formal-selection helper output substituted',
        formal_calendar_binding:'CANNOT_CONFIRM with UNKNOWN market states and null calendar SHA',
        live_api_called:false,
        production_page_reloaded:false,
        rendered_selection_rows:decisions.length,
        decision_counts:{
          selected:counts.selected_count,near_watch:counts.near_watch_count,
          excluded:counts.excluded_count,unresolved:counts.unresolved_count,
        },
        formal_selection_input:ledger.formal_selection_input,
        top_five:topFive,
      },null,2)+'\n');
    }
  });
});
