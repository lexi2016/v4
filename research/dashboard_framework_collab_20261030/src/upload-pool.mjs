// Bounded data-upload concurrency; failures settle in-flight work before returning.
// Caller may commit only after this promise resolves successfully.
export async function runUploadPool(items,upload,concurrency=4){
 if(!Number.isInteger(concurrency)||concurrency<1||concurrency>4)throw Error('UPLOAD_CONCURRENCY_LIMIT');
 let cursor=0,hasFailed=false,failure;const results=new Array(items.length);
 async function worker(){while(!hasFailed){const i=cursor++;if(i>=items.length)return;try{results[i]=await upload(items[i],i)}catch(error){if(!hasFailed){hasFailed=true;failure=error}}}}
 await Promise.all(Array.from({length:Math.min(concurrency,items.length)},worker));
 if(hasFailed)throw failure instanceof Error?failure:new Error('UPLOAD_FAILED',{cause:failure});return results;
}
