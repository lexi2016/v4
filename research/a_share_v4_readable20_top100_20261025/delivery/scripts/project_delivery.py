"""Delivery-only projection of completed results. No source input/truth/reevaluation."""
from pathlib import Path
import csv
import hashlib
import json
import shutil

ROOT=Path('/Users/lexi/Desktop/学习/因子工厂/research/a_share_v4_readable20_top100_20261025')
SOURCE=ROOT/'results_r3c'
DEST=ROOT/'final_results'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    DEST.mkdir(exist_ok=False)
    original={p.name:sha(p) for p in SOURCE.iterdir() if p.is_file()}
    for p in SOURCE.iterdir():
        if p.is_file() and p.name!='OUTPUT_MANIFEST.json':shutil.copyfile(p,DEST/p.name)
    p=DEST/'stock_stage_detail.csv'
    with p.open(newline='') as f:rows=list(csv.reader(f))
    header=rows[0];keep=[];first={};duplicate=[]
    for index,name in enumerate(header):
        if name in first:duplicate.append((index,first[name],name))
        else:first[name]=index;keep.append(index)
    assert duplicate==[(header.index('resolve_provenance')+1,header.index('resolve_provenance'),'resolve_provenance')]
    for row in rows[1:]:
        for duplicate_index,first_index,_ in duplicate:assert row[duplicate_index]==row[first_index]
    with p.open('w',newline='') as f:
        writer=csv.writer(f,lineterminator='\n');writer.writerows([[row[i] for i in keep] for row in rows])
    detail=DEST/'STOCK_STAGE_DETAIL.md';text=detail.read_text().replace('| 入选名次 | 代码 | 名称 |','| 入选名次 | 代码 | 来源响应/当前面板/旧捕获池展示名称（历史绑定待确认） |')
    text=text.replace('UNKNOWN不计为MISS。','UNKNOWN不计为MISS。名称按CSV的name_basis逐行追溯，缺失名称保持null；展示名称不证明历史名称绑定。raw_code、resolved_ts_code和resolve_provenance在CSV中分别保留。')
    detail.write_text(text)
    report=DEST/'READABLE_20X7.md';text=report.read_text();text+='\n同一日跨阶段重复席位与唯一代码数量分别见daily_unique_summary.csv；不是把7个阶段命中简单相加作为每日唯一命中。\n'
    text+='\n来源桥接：100格使用已验收R2_SHARED metadata+逐格摘要，40格绑定保存原响应；并未声称100格有新rawpayload。身份连接只使用exact-date qualified ts_code唯一键；6个旧证券身份冲突数字保持UNKNOWN。收益解析复用旧accepted pd.read_csv语义，20日严格Top100成员/名次缓存parity全部通过。\n'
    report.write_text(text)
    manifest={'schema':'DELIVERY_PROJECTION_ONLY_NO_NEW_EXPERIMENT_EVENT','source_output_directory':str(SOURCE),'source_output_hashes':original,'changed_outputs':['stock_stage_detail.csv','STOCK_STAGE_DETAIL.md','READABLE_20X7.md'],'csv_change':'Remove duplicate identical resolve_provenance column only; 341 data rows/all remaining cells retained','numeric_result_unchanged':True,'executed_source_unchanged':True,'full_rerun':False,'files':{p.name:sha(p) for p in sorted(DEST.iterdir()) if p.is_file()}}
    (DEST/'OUTPUT_MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'output_manifest':str(DEST/'OUTPUT_MANIFEST.json'),'sha256':sha(DEST/'OUTPUT_MANIFEST.json'),'detail_csv_sha256':sha(DEST/'stock_stage_detail.csv'),'detail_data_rows':len(rows)-1}))
if __name__=='__main__':main()
