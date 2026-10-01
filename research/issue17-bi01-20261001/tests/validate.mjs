import {readFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
const app=process.argv[2];
const {validateAnnouncementObservation}=await import(pathToFileURL(app+'/apps/web/src/api/managerWorkspace.ts'));
const lane=JSON.parse(readFileSync(process.argv[3],'utf8'));
const checked=validateAnnouncementObservation(lane,'20260930');
console.log('PASS original TS announcement validator: '+checked.eastmoney_hk_documents.length+' instances');
const duplicate=structuredClone(lane);duplicate.eastmoney_hk_documents.push(structuredClone(duplicate.eastmoney_hk_documents[0]));
assert.throws(()=>validateAnnouncementObservation(duplicate,'20260930'),/EASTMONEY_HK_DOCUMENT_IDENTITY_INVALID/);
console.log('PASS original TS validator rejects genuine duplicate ID');
const {JSDOM}=await import(pathToFileURL(process.env.BI01_JSDOM+'/lib/api.js'));
const dom=new JSDOM('<section></section>');globalThis.document=dom.window.document;
const {renderAnnouncementObservation}=await import(pathToFileURL(app+'/apps/web/src/manager-selection/announcementObservation.ts'));
const host=document.querySelector('section');renderAnnouncementObservation(host,checked);
assert.equal(host.querySelectorAll('[data-eastmoney-announcement]').length,3);
for(const doc of checked.eastmoney_hk_documents){
 const rows=host.querySelectorAll(`[data-eastmoney-announcement="${doc.event_id}"]`);assert.equal(rows.length,1);
 assert.equal([...rows[0].querySelectorAll('[data-eastmoney-body-page] pre')].map(p=>p.textContent).join('\n\n'),doc.body_text);
}
console.log('PASS original DOM renderer: all 3 unique IDs and complete bodies');
