import { onMounted, readonly, shallowRef } from 'vue';
import { createTestApi } from './api';
export function useAnnouncementTest(transport: typeof fetch) {
  const session = shallowRef<Awaited<ReturnType<typeof createTestApi>> | null>(null);
  const error = shallowRef('');
  const loading = shallowRef(false);
  const revision = shallowRef(0);
  async function refresh() {
    loading.value = true; error.value = '';
    try { session.value = await createTestApi(transport); revision.value++; }
    catch (caught) { error.value = caught instanceof Error ? caught.message : '测试上下文读取失败'; }
    finally { loading.value = false; }
  }
  async function executeCanary() {
    if (!session.value || loading.value) return;
    loading.value = true; error.value = '';
    try { await session.value.executeCanary(); revision.value++; }
    catch (caught) { error.value = caught instanceof Error ? caught.message : '单篇执行未完成'; }
    finally { loading.value = false; }
  }
  onMounted(refresh);
  return { session: readonly(session), error: readonly(error), loading: readonly(loading), revision: readonly(revision), refresh, executeCanary };
}
