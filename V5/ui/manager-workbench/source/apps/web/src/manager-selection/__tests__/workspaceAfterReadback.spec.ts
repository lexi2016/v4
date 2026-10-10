import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { validateManagerWorkspace } from '../../api/managerWorkspace';
import { renderAnnouncementObservation } from '../announcementObservation';

const workspaceFixture = process.env.V5_EASTMONEY_WORKSPACE_FIXTURE || '/Users/lexi/Desktop/学习/agents调试/EASTMONEY_HK_ANN_20260929/integration/workspace_after.json';

describe('actual Eastmoney owner workspace readback', () => {
  it('validates the complete owner response and renders the announcement lane', () => {
    const payload = JSON.parse(readFileSync(workspaceFixture, 'utf8'));
    expect(() => validateManagerWorkspace(payload, '20260929')).not.toThrow();

    const validated = validateManagerWorkspace(payload, '20260929');
    const host = document.createElement('section');
    renderAnnouncementObservation(host, validated.announcement_observation as any);
    const documents = (validated.announcement_observation as any).eastmoney_hk_documents;
    expect(documents).toHaveLength(2);
    expect(host.textContent).toContain('东方财富港股公告');
    expect(host.querySelectorAll('[data-eastmoney-announcement]')).toHaveLength(2);
    for (const doc of documents) {
      const article = host.querySelector(`[data-eastmoney-announcement="${doc.event_id}"]`)!;
      const renderedPages = [...article.querySelectorAll('[data-eastmoney-body-page] pre')]
        .map((page) => page.textContent || '');
      expect(renderedPages).toHaveLength(doc.content_page_count);
      expect(renderedPages.join('\n\n')).toBe(doc.body_text);
    }
  });
});
