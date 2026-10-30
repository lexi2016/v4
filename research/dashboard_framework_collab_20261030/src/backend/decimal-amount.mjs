// Exact decimal comparison of provider CNY amount against its ten-thousand-yuan field.
// Bounded textual input prevents excessive BigInt work; no floating epsilon or threshold widening.
function decimal(value){
 if(typeof value!=='string'||value.length>128||!/^[-+]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(value))return null;
 const negative=value[0]==='-',unsigned=value.replace(/^[-+]/,''),[whole,fraction='']=unsigned.split('.');
 return {coefficient:BigInt((whole||'0')+fraction)*(negative?-1n:1n),scale:fraction.length};
}
export function amountCrosscheckWithinOneYuan(amountYuan,amountTenThousandYuan){
 const a=decimal(amountYuan),b=decimal(amountTenThousandYuan);if(!a||!b)return false;
 const bScale=b.scale-4,scale=Math.max(0,a.scale,bScale),power=n=>10n**BigInt(n);
 const difference=a.coefficient*power(scale-a.scale)-b.coefficient*power(scale-bScale);
 return (difference<0n?-difference:difference)<=power(scale);
}
