// The framework owner must explicitly emit this context event or call open().
// The frozen public shell does not currently emit it; no private endpoint or
// global-date ownership is inferred from its DOM.
export function installStockContext({target,eventName='v4-stock-context',bridge,onReady,onError}){
  if(!target?.addEventListener||!target?.removeEventListener||typeof bridge?.open!=='function'||typeof bridge?.clear!=='function'||typeof onReady!=='function'||typeof onError!=='function')throw Error('EXPLICIT_HOST_CONTEXT_CALLBACKS_REQUIRED');
  let token=0,disposed=false;
  async function accept(event){const mine=++token;try{const value=await bridge.open(event.detail);if(!disposed&&mine===token)onReady(value)}catch(error){if(!disposed&&mine===token)onError(error)}}
  target.addEventListener(eventName,accept);
  return {dispose(){disposed=true;++token;target.removeEventListener(eventName,accept);bridge.clear()}};
}
