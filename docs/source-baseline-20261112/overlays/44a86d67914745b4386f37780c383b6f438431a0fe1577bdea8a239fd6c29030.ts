export const loadedFrontendScript = new URL(import.meta.url).pathname;

export function frontendBuildIdentity(loadedScript: string, payload: unknown) {
  const value = payload as Record<string, unknown> | null;
  if (!value || value.status !== 'VERIFIED' || typeof value.script_path !== 'string'
      || !/^[a-f0-9]{64}$/.test(String(value.bundle_sha256 || ''))
      || !/^[a-f0-9]{64}$/.test(String(value.api_manifest_sha256 || ''))) {
    return { status: 'CANNOT_CONFIRM', message: `前端构建身份待确认 · ${loadedScript.split('/').at(-1) || '未知脚本'}` };
  }
  if (loadedScript !== value.script_path) return {
    status: 'MISMATCH', message: `前端版本与服务端不一致，请刷新页面 · 当前 ${loadedScript.split('/').at(-1)} · 服务端 ${value.script_path.split('/').at(-1)}`,
  };
  return { status: 'VERIFIED', message: `前端 ${loadedScript.split('/').at(-1)} · API ${String(value.api_release_id || 'CANNOT_CONFIRM')} · 构建路径已匹配` };
}
