import { ApiError, createWorkbenchApi } from '../manager-workbench/api';
import { SCHEMA_VERSION } from '../manager-workbench/types';
import type { Envelope } from '../manager-workbench/types';

export interface TestContext {
  test_run_id: string; target_date: string; mode: 'fixture' | 'readonly' | 'canary';
  source_manifest_sha256: string; read_only_material_roots: Record<string, string>;
  independent_state_root: string; code_identity: Record<string, string>; config_identity: string;
  model_identity: { model_id: string; configuration_sha256: string };
  canary_allowed: boolean; evidence_kind: string;
}
const BASE = '/api/v4/announcement-test';
function validEnvelope<T>(value: unknown): Envelope<T> {
  const data = value as Envelope<T> | null;
  if (!data || data.schema_version !== SCHEMA_VERSION || typeof data.state !== 'string' || !('data' in data)
    || data.RESEARCH_ONLY !== true || data.production_allowed !== false || data.buy_gate_updated !== false || data.orders_sent !== false) {
    throw new ApiError('隔离 API 合同无效', 502);
  }
  return data;
}
export async function createTestApi(transport: typeof fetch = fetch) {
  async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await transport(BASE + path, { credentials: 'same-origin', cache: 'no-store', ...init,
      headers: { Accept: 'application/json', ...(init.body ? {'Content-Type':'application/json'} : {}) } });
    if (!response.ok) throw new ApiError('隔离请求被拒绝', response.status);
    const body = validEnvelope<T>(await response.json());
    if (!body.data) throw new ApiError('隔离 API 缺少数据', 502);
    return body.data;
  }
  const context = await request<TestContext>('/context');
  if (!/^[A-Za-z0-9_-]{1,80}$/.test(context.test_run_id) || !/^\d{8}$/.test(context.target_date)
    || !['fixture','readonly','canary'].includes(context.mode) || !/^[a-f0-9]{64}$/.test(context.source_manifest_sha256)
    || !context.model_identity?.model_id || !/^[a-f0-9]{64}$/.test(context.config_identity)
    || !/^[a-f0-9]{64}$/.test(context.model_identity.configuration_sha256) || !context.code_identity
    || !context.read_only_material_roots || !context.independent_state_root) throw new ApiError('测试上下文无效', 502);
  Object.freeze(context);
  const closedTransport: typeof fetch = async (input, init) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
    const parsed = new URL(url, 'http://isolated.invalid');
    if (!url.startsWith('/api/v4/manager-workbench/announcement-flash') || parsed.origin !== 'http://isolated.invalid'
      || parsed.pathname !== '/api/v4/manager-workbench/announcement-flash' || (init?.method || 'GET') !== 'GET'
      || [...parsed.searchParams.keys()].some(key => key !== 'target_date')
      || (parsed.searchParams.has('target_date') && parsed.searchParams.get('target_date') !== context.target_date)) {
      throw new ApiError('隔离模式拒绝正式控制端点或目标日漂移', 409);
    }
    const params = new URLSearchParams({ test_run_id: context.test_run_id, target_date: context.target_date });
    const response = await transport(`${BASE}/announcement-flash?${params}`, { ...init, credentials: 'same-origin', cache: 'no-store' });
    if (response.ok) {
      const payload = validEnvelope<{test_context_binding?: {test_run_id: string; target_date: string; source_manifest_sha256: string}}>(await response.clone().json());
      const binding = payload.data?.test_context_binding;
      if (binding?.test_run_id !== context.test_run_id || binding.target_date !== context.target_date
        || binding.source_manifest_sha256 !== context.source_manifest_sha256) throw new ApiError('隔离响应来源上下文漂移',409);
    }
    return response;
  };
  return { context, announcementApi: createWorkbenchApi(closedTransport), async executeCanary() {
    if (context.mode !== 'canary' || context.canary_allowed !== true) throw new ApiError('尚未冻结授权单篇 canary',409);
    return request<{state:string}>('/canary', {method:'POST',body:JSON.stringify({test_run_id:context.test_run_id,
      target_date:context.target_date,source_manifest_sha256:context.source_manifest_sha256})});
  }};
}
