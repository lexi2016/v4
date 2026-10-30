import {check as fail} from './contracts.mjs';
export async function readBoundedJson(request,limit=16*1024*1024){
 fail(Number.isSafeInteger(limit)&&limit>0&&limit<=16*1024*1024,'BODY_LIMIT');
 const announced=request.headers.get('content-length');if(announced!==null)fail(/^\d+$/.test(announced)&&Number(announced)<=limit,'BODY_TOO_LARGE');
 fail(request.body,'BODY_REQUIRED');const reader=request.body.getReader(),chunks=[];let size=0;
 try{while(true){const {done,value}=await reader.read();if(done)break;size+=value.byteLength;if(size>limit){await reader.cancel();fail(false,'BODY_TOO_LARGE')}chunks.push(value)}}finally{reader.releaseLock()}
 const data=new Uint8Array(size);let pos=0;for(const b of chunks){data.set(b,pos);pos+=b.byteLength}
 try{return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(data))}catch{fail(false,'INVALID_JSON')}
}
