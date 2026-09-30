"""SIMULATED official bytes; real HKEX provider, native master, parser and stores."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from urllib.parse import parse_qs

from v4.manager_research.hkex_provider import HkexOfficialProvider, ACTIVE_STOCK_LIST_URL, TITLE_SEARCH_URL
from v4.manager_research.ports import SourceResponse
from v4.manager_research.materials import MaterialStore
from v4.manager_research.store import ManagerResearchStore
from v4.manager_research.service import ManagerResearchJobService
from upstreams.v3_shared_data.shared_data.hk_security_master import publish_hk_security_master

DAY = '20260924'
HK = timezone(timedelta(hours=8))


def pdf_bytes(text='The Company entered into an agreement.', pages=1):
    # Small complete PDF fixture, no OCR or substitute parser.
    content = ('BT /F1 12 Tf 50 700 Td (' + text.replace('(', '\\(').replace(')', '\\)') + ') Tj ET').encode('ascii')
    kids = ' '.join(f'{5+i} 0 R' for i in range(pages))
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
        f'<< /Type /Pages /Count {pages} /Kids [{kids}] >>'.encode(),
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
        b'<< /Length ' + str(len(content)).encode() + b' >>\nstream\n' + content + b'\nendstream']
    objects += [b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents 4 0 R >>'] * pages
    out = bytearray(b'%PDF-1.4\n'); offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out)); out += f'{i} 0 obj\n'.encode() + obj + b'\nendobj\n'
    xref=len(out);out += f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode()
    out += b''.join(f'{n:010d} 00000 n \n'.encode() for n in offsets[1:])
    out += f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
    return bytes(out)


class OwnerFixture:
    def __init__(self, tmp_path: Path, monkeypatch, codes=('HK.00001', 'HK.09690')):
        self.now = datetime(2026,9,24,8,0,tzinfo=HK)
        self.codes=list(codes); self.calls=[]; self.rows={}; self.pdfs={}; self.fail=set()
        self.master=tmp_path/'master'
        publish_hk_security_master(self.master, trade_date='20260923',
            rows=[dict(code=c,name='Fixture '+c[3:]) for c in codes], universe_codes_sha256='a'*64,
            captured_at='2026-09-23T16:10:00+08:00')
        self.materials=MaterialStore(tmp_path/'state'/'materials')
        self.provider=HkexOfficialProvider(transport=self.transport, timeout=5, material_store=self.materials)
        self.service=ManagerResearchJobService(ManagerResearchStore(tmp_path/'state'), None, self.provider,
            material_store=self.materials, workspace_security_master_root=self.master)
        import v4.manager_research.workspace_announcements as owner
        monkeypatch.setattr(owner, '_now', lambda: self.now.isoformat())
        import v4.manager_research.announcement_source as source
        self.elapsed=0.0
        monkeypatch.setattr(source, 'monotonic', lambda: self.elapsed)
        monkeypatch.setattr(source, 'sleep', lambda seconds: setattr(self,'elapsed',self.elapsed+seconds))

    def add(self, code='HK.09690', *, minute=0, text='The Company entered into an agreement.', pages=1, slug='a'):
        url=f'https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0924/{code[3:]}-{slug}.pdf'
        published=datetime(2026,9,24,8,minute,tzinfo=HK)
        self.rows.setdefault(code, []).append((url,published)); self.pdfs[url]=pdf_bytes(text,pages)
        return url

    def transport(self,url,*,timeout,method='GET',body=None,headers=None):
        self.calls.append(dict(url=url,method=method,body=body,timeout=timeout,headers=headers))
        status=200
        if url==ACTIVE_STOCK_LIST_URL:
            raw=json.dumps([dict(c=c[3:],i=c[3:],n='Fixture '+c[3:]) for c in self.codes]).encode()
        elif method=='POST':
            code='HK.'+parse_qs(body.decode())['stockId'][0]
            if code in self.fail:
                status=503;raw=b'unavailable'
            elif not self.rows.get(code): raw=b'<html>titlesearch No records found</html>'
            else:
                raw=(''.join('<tr><td class="release-time">'+t.strftime('%d/%m/%Y %H:%M')+'</td>'
                    '<td class="stock-short-code">'+code[3:]+'</td><td class="stock-short-name">Fixture</td>'
                    '<td><div class="doc-link"><a href="'+u+'">Official fixture</a></div></td></tr>'
                    for u,t in self.rows[code])).encode()
        elif url in self.pdfs: raw=self.pdfs[url]
        else: raw=b'<html>titlesearch cookie form</html>'
        return SourceResponse(url=url,final_url=url,status_code=status,headers={},body=raw,retrieved_at=self.now.isoformat())
