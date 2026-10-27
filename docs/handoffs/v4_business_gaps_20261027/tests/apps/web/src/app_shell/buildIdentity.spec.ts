import { expect, it } from 'vitest';
import { frontendBuildIdentity } from './buildIdentity';

const payload={status:'VERIFIED',script_path:'/assets/main-new.js',bundle_sha256:'a'.repeat(64),api_manifest_sha256:'b'.repeat(64),api_release_id:'current-api'};
it('detects the old executing bundle even when the API banner is current',()=>{
  const value=frontendBuildIdentity('/assets/main-old.js',payload);
  expect(value.status).toBe('MISMATCH');expect(value.message).toContain('请刷新页面');
});
it('reports own frontend identity separately from serving API release',()=>{
  const value=frontendBuildIdentity('/assets/main-new.js',payload);
  expect(value.status).toBe('VERIFIED');expect(value.message).toContain('main-new.js');expect(value.message).toContain('current-api');
});
it('does not verify incomplete static manifest evidence',()=>{
  expect(frontendBuildIdentity('/assets/main-new.js',{...payload,bundle_sha256:null}).status).toBe('CANNOT_CONFIRM');
});
