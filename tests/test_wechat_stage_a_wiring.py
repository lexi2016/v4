"""Static integration invariants, explicitly NOT a full V4 runtime/UI test."""
from pathlib import Path
import ast

ROOT=Path(__file__).parents[1]


def test_reader_router_is_mounted_under_existing_research_namespace():
    router=(ROOT/'apps/api/v35_api/research_router.py').read_text()
    app=(ROOT/'apps/api/v35_api/app.py').read_text()
    assert 'create_wechat_research_router' in router
    assert 'wechat_archive_root' in router
    assert 'V4_WECHAT_ARCHIVE_ROOT' in app
    ast.parse(router); ast.parse(app)


def test_archive_panel_is_mounted_inside_the_middle_feed_reader():
    view=(ROOT/'apps/web/src/views/ResearchView.vue').read_text()
    feed=(ROOT/'apps/web/src/components/research/ResearchFeedPane.vue').read_text()
    assert 'import ResearchFeedPane' in view
    assert 'import WechatResearchPanel' not in view
    assert ':archive-date="archiveDate"' in view
    assert 'import WechatResearchPanel' in feed
    assert '{ id: "wechat", label: "公众号" }' in feed
    assert "feedFilter === 'wechat'" in feed
    assert '<WechatResearchPanel v-if="feedFilter === \'wechat\'" :archive-date="archiveDate" />' in feed
    # Existing load paths remain intact, no mutation to stock/research calculations.
    assert 'void run(() => loadResearchLane(props.archiveDate), props.archiveDate)' in view
    assert 'void run(loadResearchLaneLatest)' in view


def test_report_panel_never_executes_untrusted_html_or_paths():
    file=ROOT/'apps/web/src/components/research/WechatResearchPanel.vue'
    assert file.exists(), 'Stage A Vue panel is not implemented'
    text=file.read_text()
    for forbidden in ('v-html','innerHTML','<iframe','<object','<embed','eval('):
        assert forbidden not in text
    assert '{{ detail.report.content }}' in text
    assert 'safeArticleUrl' in text and 'wechatArtifactUrl' in text
    assert 'AbortController' in text and 'onBeforeUnmount' in text
    assert 'listVersion' in text and 'detailVersion' in text
