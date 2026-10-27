"""HEAD-only fixed official source metadata. No data body, redirect, code or upload."""
import argparse, datetime, json, re, urllib.request, urllib.error
from zoneinfo import ZoneInfo

def source_urls(date):
 if not re.fullmatch(r'\d{8}',date):raise ValueError('INVALID_DATE')
 datetime.datetime.strptime(date,'%Y%m%d')
 return ['https://data.tdx.com.cn/vipdoc/hsjday.zip','https://www.tdx.com.cn/products/data/data/dbf/gbbq.zip',f'https://www.tdx.com.cn/products/data/data/g4day/{date}.zip']

def conditionals(headers):
 headers={k.lower():v for k,v in headers.items()}
 return {h:headers[k] for k,h in [('etag','If-None-Match'),('last-modified','If-Modified-Since')] if headers.get(k)}

class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):return None

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--date');p.add_argument('--previous',help='Prior JSON list from this probe');a=p.parse_args()
 date=a.date or datetime.datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d')
 previous={}
 if a.previous:
  with open(a.previous) as f:previous={r['url']:r.get('headers',{}) for r in json.load(f)}
 opener=urllib.request.build_opener(NoRedirect());results=[]
 for url in source_urls(date):
  headers=conditionals(previous.get(url,{}));r={'url':url,'target_date':date,'method':'HEAD','request_headers':headers,'observed_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'body_downloaded':False,'PIT':False,'known_at_status':'FIRST_OBSERVATION_NOT_HISTORICAL_KNOWN_AT','fresh_market_bytes_verified':False}
  try:
   with opener.open(urllib.request.Request(url,headers=headers,method='HEAD'),timeout=15) as response:r.update(status=response.status,headers=dict(response.headers))
  except urllib.error.HTTPError as e:
   r.update(status=e.code,headers=dict(e.headers),error=str(e))
  except Exception as e:r.update(status='UNAVAILABLE',error=type(e).__name__+': '+str(e))
  results.append(r)
 print(json.dumps(results,ensure_ascii=False,indent=2))
 return 0 if all(r['status'] in (200,304) for r in results) else 2
if __name__=='__main__':raise SystemExit(main())
