import re
import pytest
from ops.render_original_formula_projection import interactive_chart_html, pinned, OWNER_RENDERER


def test_local_r19_viewport_adapter_preserves_original_paint_and_payload():
    html=pinned(OWNER_RENDERER).decode();adapted=interactive_chart_html(html)
    assert "view.count*(e.deltaY>0?1.2:.8)" in adapted
    assert 'originalCanvas.onpointercancel' in adapted and 'originalCanvas.onlostpointercapture' in adapted
    assert 'id="original-view-reset"' in adapted
    assert 'rows=state.rows.slice(offset,offset+state.view.count)' in adapted
    assert re.search(r'function choose\(i\).*?\n',html).group()==re.search(r'function choose\(i\).*?\n',adapted).group()
    assert interactive_chart_html(adapted)==adapted
    with pytest.raises(ValueError,match='VIEWPORT_ADAPTER'):interactive_chart_html('<html>unknown renderer</html>')
