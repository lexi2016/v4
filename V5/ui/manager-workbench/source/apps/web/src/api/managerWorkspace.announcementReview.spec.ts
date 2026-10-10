/// <reference types="node" />
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { validateAnnouncementReview, type AnnouncementReview } from './managerWorkspace';

const evidenceRoot=process.env.V5_ANNOUNCEMENT_REVIEW_FIXTURES || '/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_CHECKPOINT_20261003/announcement_deployment';
const load=(date:string):AnnouncementReview=>JSON.parse(readFileSync(join(evidenceRoot,`ANNOUNCEMENTS_${date}.json`),'utf8')) as AnnouncementReview;
const time=(value:unknown):number=>Date.parse(String(value));

describe('exact-publication-day announcement review time contract',()=>{
  it.each([['20261002',243],['20261001',8]] as const)(
    'accepts the full saved %s payload when retrieval follows the query coverage cutoff',
    (date,count)=>{
      const payload=load(date);
      const before=JSON.stringify(payload);
      const validated=validateAnnouncementReview(payload,date);
      const cutoff=time(payload.coverage.source_coverage_cutoff);
      expect(validated.official_documents).toHaveLength(count);
      expect(validated.coverage.observed_document_count).toBe(count);
      expect(validated.official_documents.every(doc=>time(doc.available_at)>cutoff)).toBe(true);
      expect(validated.official_documents.every(doc=>time(doc.retrieved_at)>cutoff)).toBe(true);
      expect(JSON.stringify(payload)).toBe(before);
    },
  );

  it('still rejects an announcement published after the source coverage cutoff',()=>{
    const payload=load('20261002');
    const cutoff=time(payload.coverage.source_coverage_cutoff);
    const doc=payload.official_documents[0];
    const after=new Date(cutoff+60_000).toISOString();
    doc.published_at=after;
    doc.available_at=new Date(cutoff+120_000).toISOString();
    doc.retrieved_at=new Date(cutoff+180_000).toISOString();
    expect(()=>validateAnnouncementReview(payload,'20261002')).toThrow('ANNOUNCEMENT_REVIEW_DOCUMENT_TIME_INVALID');
  });

  it('retains explicit timezone and publication-before-acquisition checks',()=>{
    const noTimezone=load('20261002');
    noTimezone.official_documents[0].available_at='2026-10-02T19:03:12';
    expect(()=>validateAnnouncementReview(noTimezone,'20261002')).toThrow('ANNOUNCEMENT_EXPLICIT_TIME_REQUIRED');

    const inverted=load('20261002');
    const published=time(inverted.official_documents[0].published_at);
    inverted.official_documents[0].available_at=new Date(published-60_000).toISOString();
    expect(()=>validateAnnouncementReview(inverted,'20261002')).toThrow('ANNOUNCEMENT_REVIEW_DOCUMENT_TIME_INVALID');
  });
});
