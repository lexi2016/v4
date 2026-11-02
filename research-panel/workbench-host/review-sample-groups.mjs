// Two locked review samples, separate from the numeric candidate groups.
export const REVIEW_SOURCE_DATE='2026-10-30';
export const REVIEW_SOURCE_LOCKS=Object.freeze({
  first:'ac4882457c522a57c9a02c17eeb4741b33a9f217d83f4377e08555107b756103',
  second:'ce114fffef52469d127b7657cef4d9e09d0e9d849b87cde8ef3a579504ba5617',
});
const FIRST=[
  ['600000.SH','浦发银行'],['600519.SH','贵州茅台'],['601318.SH','中国平安'],['688981.SH','中芯国际'],
  ['688496.SH','*ST清越'],['300206.SZ','理邦仪器'],['002865.SZ','钧达股份'],['301048.SZ','金鹰重工'],
  ['301686.SZ','中塑股份'],['000001.SZ','平安银行'],['920201.BJ','百瑞吉'],['920196.BJ','南方乳业'],
  ['920298.BJ','腾信精密'],['920000.BJ','安徽凤凰'],['920001.BJ','纬达光电'],['600036.SH','招商银行'],
  ['603281.SH','江瀚新材'],['000020.SZ','深华发Ａ'],['000301.SZ','东方盛虹'],['920187.BJ','通领科技'],
];
const SECOND=[
  ['600000.SH','浦发银行'],['300206.SZ','理邦仪器'],['301048.SZ','金鹰重工'],['688496.SH','*ST清越'],
  ['301686.SZ','中塑股份'],['920196.BJ','南方乳业'],['000002.SZ','万 科Ａ'],['603848.SH','好太太'],
  ['603956.SH','威派格'],['603248.SH','锡华科技'],['002991.SZ','甘源食品'],['002581.SZ','ST未名'],
  ['000089.SZ','深圳机场'],['688160.SH','步科股份'],['688208.SH','道通科技'],['688781.SH','视涯科技'],
  ['300115.SZ','长盈精密'],['920642.BJ','通易航天'],['920149.BJ','旭杰科技'],['920455.BJ','汇隆活塞'],
];

export function reviewSampleRows(group='all'){
  if(!['all','first','second'].includes(group))return [];
  const map=new Map();
  for(const [round,items] of [[1,FIRST],[2,SECOND]])for(const [symbol,name] of items){
    const item=map.get(symbol)??{symbol,name,rounds:[]};item.rounds.push(round);map.set(symbol,item);
  }
  const order=group==='first'?FIRST:group==='second'?SECOND:[...map.values()].map(item=>[item.symbol,item.name]);
  return order.map(([symbol])=>({...map.get(symbol),rounds:[...map.get(symbol).rounds]}));
}

export function installReviewSampleGroups({container,document,openSymbol}){
  const make=(tag,text)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;return el};
  let dayAllowed=false;
  const panel=make('details');panel.open=true;panel.hidden=true;panel.style.marginTop='8px';
  const summary=make('summary','抽检汇总 · 34只（40次检查）');panel.append(summary);
  const source=make('p','来源：第一轮固定样本锁、第二轮分层抽检锁 · 来源日 2026-10-30。仅为复查名单，不代表数值入选或买点。');
  source.title=`第一轮 ${REVIEW_SOURCE_LOCKS.first}；第二轮 ${REVIEW_SOURCE_LOCKS.second}`;panel.append(source);
  const label=make('label','查看抽检分组');const selector=make('select');selector.setAttribute('aria-label','查看抽检分组');
  for(const [value,text] of [['all','抽检汇总 · 34只'],['first','第一轮 · 20只'],['second','第二轮 · 20只']]){
    const option=make('option',text);option.value=value;selector.append(option);
  }
  selector.value='all';label.append(selector);panel.append(label);
  const count=make('p');panel.append(count);const list=make('div');list.style.maxHeight='190px';list.style.overflowY='auto';panel.append(list);
  function paint(){
    const rows=reviewSampleRows(selector.value);list.replaceChildren();
    count.textContent=`本组 ${rows.length}只 · 两轮共40次检查，其中6只复验`;
    for(const item of rows){
      const rounds=item.rounds.length===2?'第一、二轮':item.rounds[0]===1?'第一轮':'第二轮';
      const button=make('button',`${item.name} ${item.symbol} · ${rounds}`);button.type='button';
      button.style.display='block';button.style.width='100%';button.style.textAlign='left';
      button.onclick=()=>{if(dayAllowed)openSymbol(item.symbol,item.name)};list.append(button);
    }
  }
  selector.onchange=paint;paint();container.append(panel);
  return {bindDay(day){dayAllowed=day?.source_date===REVIEW_SOURCE_DATE;panel.hidden=!dayAllowed},
    unbindDay(){dayAllowed=false;panel.hidden=true}};
}
