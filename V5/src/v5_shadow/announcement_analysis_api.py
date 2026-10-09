"""Publish exact explicit/default announcement queries, never relabel responses."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
from v5_shadow.announcement_offline_reader import read_owner
from v5_shadow.contracts import exact_keys,trade_date,sha
from v5_shadow.digests import sha256_json
from v5_shadow.module_artifacts import publish_generation

ROUTE='/api/v4/manager/research/announcements/analysis'


def response_record(result,config,query):
    exact_keys(query,('date','publication_date') if 'publication_date' in query else ('date',))
    trade_date(query['date'])
    payload=result['analysis']
    explicit='publication_date' in query
    basis='EXPLICIT' if explicit else 'PREVIOUS_HK_TRADING_SESSION'
    if payload.get('target_trade_date')!=query['date'] or payload.get('date_selection_basis')!=basis:
        raise ValueError('ANNOUNCEMENT_API_QUERY_BASIS_MISMATCH')
    publication=payload.get('publication_date')
    if not isinstance(publication,str):raise ValueError('ANNOUNCEMENT_API_PUBLICATION_DATE')
    trade_date(publication.replace('-',''))
    if explicit and query['publication_date'].replace('-','')!=publication.replace('-',''):
        raise ValueError('ANNOUNCEMENT_API_QUERY_DATE_MISMATCH')
    if payload.get('analysis',{}).get('status')!='VERIFIED':raise ValueError('ANNOUNCEMENT_API_READBACK_NOT_VERIFIED')
    sha(payload['analysis']['product_sha256'])
    return dict(schema_version='v5.module_response.v1',module_id=config['module_id'],release_id=config['release_id'],
        path=ROUTE,query=dict(query),payload=payload,payload_sha256=sha256_json(payload),
        source_input_sha256=result['request_sha256'],data_kind='OWNER_RESULT',
        generated_at=datetime.now(timezone.utc).isoformat(),status_code=200)


def publish_analysis(binding,config,*,expected_generation):
    cutoff=datetime.now(timezone.utc).isoformat()
    explicit=read_owner(binding,cutoff)
    default=read_owner(binding,cutoff,default_analysis=True)
    if explicit['analysis']['analysis']['product_sha256']!=default['analysis']['analysis']['product_sha256']:
        raise ValueError('ANNOUNCEMENT_API_READ_PAIR_CHANGED')
    target=binding['target_date'];publication=binding['publication_date']
    # Compact UI query and ISO API query are both explicit, separate exact keys.
    records=[response_record(explicit,config,{'date':target,'publication_date':day})
             for day in sorted({publication,publication.replace('-','')})]
    records.append(response_record(default,config,{'date':target}))
    return publish_generation(config,records,expected_generation=expected_generation)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binding',type=Path,required=True,help='four-field manager announcement_offline_owner binding JSON')
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--expected-generation',required=True,help='current module generation SHA or literal null for empty root')
    args=parser.parse_args()
    result=publish_analysis(json.loads(args.binding.read_bytes()),json.loads(args.config.read_bytes()),
        expected_generation=None if args.expected_generation=='null' else args.expected_generation)
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__':main()
