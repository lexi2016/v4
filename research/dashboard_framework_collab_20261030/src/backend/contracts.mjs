// Public primitive shim, NOT the private platform policy. No caller flag/header enables writes.
export const H=/^[a-f0-9]{64}$/;
export const canonical=x=>JSON.stringify(x,(_k,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.keys(v).sort().map(k=>[k,v[k]])):v);
export const sha=async b=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',b)),x=>x.toString(16).padStart(2,'0')).join('');
export const encode=x=>new TextEncoder().encode(canonical(x));
export function check(ok,code,status=422){if(!ok)throw Object.assign(new Error(code),{status})}
export function authorize(){check(false,'TRUSTED_PLATFORM_AUTHORIZATION_NOT_CONFIGURED',403)}
