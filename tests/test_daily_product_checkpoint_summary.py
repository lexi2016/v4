import hashlib
import json

from ops.research_panel_daily_product import read_complete_daily_rows


def test_complete_daily_checkpoint_batch_preserves_scope_order_and_raw_references(tmp_path):
    symbols = ['000001.SZ', '000002.SZ', '600000.SH', '920050.BJ']
    expected = {}
    for symbol in symbols:
        raw = (json.dumps({'symbol': symbol, 'data_date': '20261119', 'value': symbol},
                          sort_keys=True, separators=(',', ':')) + '\n').encode()
        (tmp_path / (symbol + '.json')).write_bytes(raw)
        expected[symbol] = hashlib.sha256(raw).hexdigest()

    rows = read_complete_daily_rows(tmp_path, symbols, 20261119, workers=3, batch_size=2)

    assert [row['symbol'] for row, _ in rows] == symbols
    assert [reference['sha256'] for _, reference in rows] == [expected[symbol] for symbol in symbols]
    assert [reference['path'] for _, reference in rows] == [str((tmp_path / (symbol + '.json')).resolve()) for symbol in symbols]


def test_complete_daily_checkpoint_batch_falls_back_if_any_row_is_missing(tmp_path):
    symbols = ['000001.SZ', '000002.SZ']
    row = {'symbol': symbols[0], 'data_date': '20261119'}
    (tmp_path / (symbols[0] + '.json')).write_text(json.dumps(row))

    assert read_complete_daily_rows(tmp_path, symbols, 20261119, workers=2, batch_size=1) is None
