"""Loopback-only, read-only view of validated V5 committed research artifacts."""
import argparse
from datetime import datetime
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
from urllib.parse import parse_qs, urlencode, urlsplit
from zoneinfo import ZoneInfo

from .composition import shadow_root
from .contracts import trade_date
from .digests import canonical_bytes
from .shadow_store import _load, _ref, read_shadow, wire

MAX_REFS = 2000


def read_run(root, target_date, run_id):
    trade_date(target_date)
    if re.fullmatch(r'[0-9a-f]{32}', run_id) is None:
        raise ValueError('RUN_ID_INVALID')
    record, _ = _load(root, 'refs/' + run_id + '.json')
    if record['target_trade_date'] != target_date:
        raise LookupError('RUN_TARGET_MISMATCH')
    reference = _ref(record['reference'])
    result = read_shadow(root, reference)
    if result.run_id != run_id or result.request.target_trade_date != target_date:
        raise ValueError('RUN_REFERENCE_MISMATCH')
    return {'status': result.business_status, 'reference': wire(reference), 'result': wire(result)}


def list_runs(root, target_date):
    trade_date(target_date)
    refs = root / 'refs'
    if not refs.exists():
        return {'status': 'NOT_RUN', 'target_date': target_date, 'runs': []}
    if refs.is_symlink():
        raise ValueError('REFERENCE_DIRECTORY_INVALID')
    rows = []
    for number, path in enumerate(refs.iterdir(), 1):
        if number > MAX_REFS:
            raise ValueError('REFERENCE_LIMIT_EXCEEDED')
        if path.suffix != '.json':
            continue
        if re.fullmatch(r'[0-9a-f]{32}', path.stem) is None:
            raise ValueError('RUN_ID_INVALID')
        record, _ = _load(root, 'refs/' + path.name)
        if record['target_trade_date'] != target_date:
            continue
        value = read_run(root, target_date, path.stem)
        result = value['result']
        rows.append({'run_id': result['run_id'], 'status': result['business_status'],
                     'finished_at': result['finished_at'], 'data_kind': result['request']['data_kind'],
                     'artifact_sha256': value['reference']['artifact_sha256']})
    rows.sort(key=lambda row: (row['finished_at'], row['run_id']), reverse=True)
    return {'status': 'AVAILABLE' if rows else 'NOT_RUN', 'target_date': target_date, 'runs': rows}


def text(value):
    return escape(str(value if value is not None else '未提供'), quote=True)


def render_page(target_date, inventory, selected=None):
    links = ''.join('<li><a href="/?' + escape(urlencode({'target_date': target_date, 'run_id': r['run_id']}), quote=True)
                    + '">' + text(r['finished_at']) + ' · ' + text(r['status']) + '</a></li>' for r in inventory['runs'])
    content = '<section><h2>尚无已提交结果</h2><p>该日期未读到可核验的运行产物，不能解释为成功筛出零只。</p></section>'
    if selected:
        value = selected['result']; legacy = value['legacy_screen']; request = value['request']
        status = {'COMPLETED': '计算完成', 'VALID_EMPTY': '计算完成，无入选候选', 'PARTIAL': '部分结果',
                  'CANNOT_CONFIRM': '结果无法确认', 'FAILED': '运行失败'}[value['business_status']]
        content = '<section><h2>' + status + '</h2><p class="notice">研究用途 · 正式资格未验证 · 自然运行未验证</p>'
        content += '<dl>'
        facts = [('数据身份', request['data_kind']), ('运行方式', request['execution_kind']),
                 ('目标日期', request['target_trade_date']), ('研究截止', request['research_cutoff']),
                 ('实际完成', value['finished_at']), ('Run ID', value['run_id']),
                 ('Artifact SHA', selected['reference']['artifact_sha256']),
                 ('输入 SHA', request['input_snapshot_sha256']), ('成交量单位状态', legacy.get('volume_unit_status', '未验证'))]
        for label, item in facts:
            content += '<dt>' + text(label) + '</dt><dd>' + text(item) + '</dd>'
        content += '</dl>'
        if request['data_kind'] == 'SYNTHETIC':
            content += '<p class="notice">SYNTHETIC：以下为合成测试数据，不是真实股票推荐。</p>'
        for key, label in [('strict', '严格候选'), ('near', '接近条件'), ('excluded', '排除'), ('pending', '待核实'), ('screen_unresolved', '未能判定')]:
            rows = legacy.get(key, [])
            content += '<h3>' + label + ' · ' + str(len(rows)) + '</h3>'
            if not rows:
                content += '<p>本组无记录；是否成功请以上方运行状态为准。</p>'
                continue
            content += '<div class="scroll"><table><thead><tr><th>股票</th><th>价格</th><th>5日量比</th><th>原因</th></tr></thead><tbody>'
            for row in rows:
                reason = row.get('reason_for_group') or row.get('reason_for_exclusion') or row.get('history_unknown_reasons') or '原结果未提供原因'
                content += '<tr><td>' + text(row.get('code')) + '<br>' + text(row.get('name')) + '</td><td>' + text(row.get('close')) + '</td><td>' + text(row.get('volume_ratio_5d')) + '</td><td>' + text(reason) + '</td></tr>'
            content += '</tbody></table></div>'
        gaps = legacy.get('gaps', [])
        if gaps:
            content += '<h3>数据与证据缺口</h3><ul>' + ''.join('<li>' + text(gap) + '</li>' for gap in gaps) + '</ul>'
        content += '</section>'
    return '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>V5 超跌研究</title><style>
body{margin:0;background:#f3f5f8;color:#172638;font:16px/1.6 system-ui,sans-serif}main{max-width:1120px;margin:auto;padding:28px}header{border-bottom:3px solid #286c79;padding-bottom:18px}h1{margin:0}section{background:white;border:1px solid #d8e1e8;border-radius:12px;padding:24px;margin-top:20px}a{color:#165a89}input,button{font:inherit;padding:8px;margin:5px;border:1px solid #65788c;border-radius:5px}button{background:#175d6b;color:white}.notice{background:#fff3d2;padding:12px;border-left:4px solid #bb8a19}dl{display:grid;grid-template-columns:140px 1fr;gap:8px}dt{font-weight:600}dd{margin:0;overflow-wrap:anywhere}.scroll{overflow:auto}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:10px;border-bottom:1px solid #dde4eb;vertical-align:top}th{background:#eef3f6}footer{margin:20px 0;color:#455568}@media(max-width:600px){main{padding:12px}section{padding:15px}dl{grid-template-columns:1fr}}
</style></head><body><main><header><p>V5 / 独立研究预览</p><h1>超跌选股工作台</h1><p>只读查看已提交结果，每份结果均经过文件一致性核验。</p></header><form method="get" action="/"><label for="date">目标日期（YYYYMMDD）</label><input id="date" name="target_date" inputmode="numeric" pattern="[0-9]{8}" value="''' + text(target_date) + '''" required><button type="submit">查看</button></form>''' + content + '<section><h2>本日运行记录</h2><ul>' + links + '</ul></section><footer>此页面不采集、不执行策略、不产生订单，也不会修改 V4。</footer></main></body></html>'


def create_server(output_root, host='127.0.0.1', port=0):
    if host != '127.0.0.1':
        raise ValueError('LOOPBACK_ONLY')
    root = shadow_root(Path(output_root))
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def reply(self, status, payload, html=False):
            body = payload.encode() if html else canonical_bytes(payload)
            self.send_response(status)
            self.send_header('Content-Type', 'text/html; charset=utf-8' if html else 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")
            self.send_header('Referrer-Policy', 'no-referrer')
            self.end_headers(); self.wfile.write(body)
        def do_POST(self):
            self.reply(405, {'status': 'READ_ONLY'})
        def do_GET(self):
            try:
                allowed = '127.0.0.1:' + str(self.server.server_address[1])
                if self.headers.get('Host') not in (allowed, 'localhost:' + str(self.server.server_address[1])):
                    self.reply(403, {'status': 'HOST_REJECTED'}); return
                origin = self.headers.get('Origin')
                if origin and origin not in ('http://' + allowed, 'http://localhost:' + str(self.server.server_address[1])):
                    self.reply(403, {'status': 'ORIGIN_REJECTED'}); return
                parsed = urlsplit(self.path)
                query = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=4)
                if any(len(v) != 1 for v in query.values()) or set(query) - {'target_date', 'run_id'}:
                    raise ValueError('QUERY_INVALID')
                default = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d') if parsed.path == '/' else ''
                day = query.get('target_date', [default])[0]; trade_date(day)
                if parsed.path == '/api/runs':
                    self.reply(200, list_runs(root, day))
                elif parsed.path == '/api/result':
                    self.reply(200, read_run(root, day, query.get('run_id', [''])[0]))
                elif parsed.path == '/':
                    inventory = list_runs(root, day)
                    run_id = query.get('run_id', [inventory['runs'][0]['run_id'] if inventory['runs'] else None])[0]
                    selected = read_run(root, day, run_id) if run_id else None
                    self.reply(200, render_page(day, inventory, selected), html=True)
                else:
                    self.reply(404, {'status': 'NOT_FOUND'})
            except (FileNotFoundError, LookupError):
                self.reply(404, {'status': 'NOT_FOUND'})
            except ValueError as error:
                reason = str(error)
                invalid_query = reason in ('RUN_ID_INVALID', 'QUERY_INVALID') or reason.startswith('INVALID_') or 'DATE' in reason
                self.reply(400 if invalid_query else 409, {'status': 'INVALID', 'reason_codes': [reason if re.fullmatch('[A-Z0-9_]+', reason) else 'INVALID_REQUEST_OR_ARTIFACT']})
            except (OSError, TypeError):
                self.reply(409, {'status': 'INVALID', 'reason_codes': ['ARTIFACT_UNREADABLE']})
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description='V5 local read-only research preview')
    parser.add_argument('--output-root', required=True)
    parser.add_argument('--port', type=int, default=8895)
    args = parser.parse_args(argv)
    server = create_server(Path(args.output_root), port=args.port)
    print('http://127.0.0.1:' + str(server.server_address[1]), flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()

if __name__ == '__main__':
    main()
