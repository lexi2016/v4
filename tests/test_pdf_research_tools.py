from __future__ import annotations

import json
import hashlib
import unittest
from types import SimpleNamespace

import httpx

from infrastructure import pdf_research_tools as tools


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _model_completion(action: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(
        final_text=json.dumps(
            {"analysis_markdown": json.dumps(action, ensure_ascii=False, separators=(",", ":"))},
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


class PdfResearchToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = {
            "page_input_sha256": "a" * 64,
            "pages": [
                {
                    "page_number": 1,
                    "page_total": 2,
                    "text": "Acme Technologies Limited reported revenue of 100 million.\nAnnual report.",
                    "text_sha256": _sha("Acme Technologies Limited reported revenue of 100 million.\nAnnual report."),
                },
                {
                    "page_number": 2,
                    "page_total": 2,
                    "text": "The report says Acme Technologies remains a core supplier and is delivering in batches.",
                    "text_sha256": _sha("The report says Acme Technologies remains a core supplier and is delivering in batches."),
                },
            ],
        }

    def test_model_selects_local_pdf_math_and_official_web_actions(self) -> None:
        url = "https://www.hkexnews.hk/example/annual-report.html"
        actions = [
            {"action": "read", "arguments": {"page_number": 2}},
            {"action": "search_pdf", "arguments": {"query": "delivering in batches"}},
            {"action": "calculator", "arguments": {"operation": "percent_change", "values": ["100", "105"]}},
            {"action": "web_search", "arguments": {"entity": "Acme Technologies Limited", "topic": "official_delivery"}},
            {"action": "fetch", "arguments": {"url": url}},
            {"action": "final", "report": "PDF delivery evidence (p. 2); calculated growth is 5%; external supplement is labeled separately."},
        ]
        calls: list[list[dict[str, str]]] = []
        web_calls: list[tuple[str, dict[str, str]]] = []
        receipts: list[dict[str, object]] = []

        def request_turn(messages):
            calls.append([dict(message) for message in messages])
            return _model_completion(actions[len(calls) - 1])

        def web_call(name, arguments):
            web_calls.append((name, dict(arguments)))
            if name == "web_search":
                return (
                    {
                        "ok": True,
                        "provider": "configured-provider",
                        "results": [{"title": "Official delivery announcement", "url": url, "published_date": "2026-10-18"}],
                    },
                    {"status": "ok", "input_sha256": "d" * 64},
                )
            self.assertEqual(name, "fetch_url")
            return (
                {
                    "ok": True,
                    "url": url,
                    "title": "Official delivery announcement",
                    "publication_date": "2026-10-18",
                    "content": "Official notice: batch delivery is continuing.",
                },
                {"status": "ok", "input_sha256": "e" * 64},
            )

        result = tools.run_action_loop(
            [{"role": "system", "content": "PDF research"}, {"role": "user", "content": "Analyze the source."}],
            context=self.context,
            response_schema={"type": "object"},
            request_turn=request_turn,
            web_call=web_call,
            on_tool_receipt=receipts.append,
        )

        self.assertEqual(result["analysis_markdown"], actions[-1]["report"])
        self.assertEqual(result["tool_actions"], 5)
        self.assertEqual(result["turns"], 6)
        self.assertEqual([name for name, _args in web_calls], ["web_search", "fetch_url"])
        self.assertIn("Acme Technologies Limited", web_calls[0][1]["query"])
        self.assertNotIn("delivering in batches", web_calls[0][1]["query"])
        self.assertNotIn("Annual report", web_calls[0][1]["query"])
        self.assertEqual([receipt["name"] for receipt in receipts], ["read", "search_pdf", "calculator", "web_search", "fetch"])
        self.assertTrue(all(receipt["status"] == "ok" for receipt in receipts))
        read_observation = calls[1][-1]["content"]
        search_observation = calls[2][-1]["content"]
        self.assertIn('"page_number":2', read_observation)
        self.assertIn("不可信资料", read_observation)
        self.assertIn('"snapshot_sha256":"' + "a" * 64 + '"', search_observation)
        self.assertIn('"value":"5"', calls[3][-1]["content"])
        self.assertIn("Official notice", calls[5][-1]["content"])

    def test_page_context_must_be_complete_and_fetch_must_follow_same_search(self) -> None:
        incomplete = {"page_input_sha256": "a" * 64, "pages": [self.context["pages"][0]]}
        with self.assertRaisesRegex(tools.PdfToolError, "PDF_PAGE_CONTEXT_INCOMPLETE"):
            tools.run_action_loop(
                [{"role": "system", "content": "PDF research"}],
                context=incomplete,
                response_schema={"type": "object"},
                request_turn=lambda _messages: self.fail("incomplete context must fail before model request"),
                web_call=lambda *_args: self.fail("no external lookup expected"),
            )

        action = {"action": "fetch", "arguments": {"url": "https://www.hkexnews.hk/private.html"}}
        observation, _receipt = tools._execute_action(
            action,
            context=self.context,
            web_call=lambda *_args: self.fail("fetch without a search grant must not call the provider"),
            web_state={"searches": 0, "fetches": 0, "qualified_urls": {}},
        )
        self.assertEqual(observation["error"], "FETCH_URL_NOT_FROM_THIS_SEARCH")

        with self.assertRaisesRegex(tools.PdfToolError, "WEB_SEARCH_ENTITY_INVALID"):
            tools._public_entity_name(
                {"entity": "Acme Technologies reported revenue", "topic": "official_results"},
                self.context,
            )

    def test_decimal_calculation_and_official_url_validation(self) -> None:
        self.assertEqual(
            tools._calculate({"operation": "percent_change", "values": ["100", "105"]})["value"],
            "5",
        )
        self.assertIsNone(tools._normalized_public_https_url("https://user:pass@hkexnews.hk/report"))
        self.assertIsNone(tools._normalized_public_https_url("https://@hkexnews.hk/report"))
        self.assertIsNone(tools._normalized_public_https_url("http://hkexnews.hk/report"))
        self.assertIsNone(tools._normalized_public_https_url("https://169.254.169.254/latest/meta-data"))

    def test_safe_fetch_validates_every_redirect_and_public_dns_before_request(self) -> None:
        start_url = "https://www.hkexnews.hk/start"
        for location in ("http://www.hkexnews.hk/report", "https://example.com/report"):
            with self.subTest(location=location):
                requested: list[str] = []

                def redirect(request):
                    requested.append(str(request.url))
                    return httpx.Response(302, headers={"location": location}, request=request)

                payload, receipt = tools.fetch_public_official_url(
                    start_url,
                    transport=httpx.MockTransport(redirect),
                    resolver=lambda _host: ["93.184.216.34"],
                )
                self.assertFalse(payload["ok"])
                self.assertEqual(payload["error"], "UNSAFE_REDIRECT_OR_FINAL_URL")
                self.assertEqual(requested, [start_url])
                self.assertEqual(receipt["redirect_count"], 0)

        requested = []

        def never_called(request):
            requested.append(str(request.url))
            return httpx.Response(200, text="must not fetch", request=request)

        payload, _receipt = tools.fetch_public_official_url(
            start_url,
            transport=httpx.MockTransport(never_called),
            resolver=lambda _host: ["127.0.0.1"],
        )
        self.assertEqual(payload["error"], "WEB_FETCH_PRIVATE_HOST_BLOCKED")
        self.assertEqual(requested, [])

    def test_safe_fetch_allows_same_official_https_redirect_and_bounds_visible_text(self) -> None:
        requested: list[str] = []

        def route(request):
            requested.append(str(request.url))
            if request.url.path == "/start":
                return httpx.Response(302, headers={"location": "/report"}, request=request)
            return httpx.Response(
                200,
                text=(
                    "<html><head><title>Official report</title>"
                    "<meta property='article:published_time' content='2026-10-18'></head>"
                    "<body><script>ignore me</script><p>Revenue was 100 million.</p></body></html>"
                ),
                headers={"content-type": "text/html; charset=utf-8"},
                request=request,
            )

        payload, receipt = tools.fetch_public_official_url(
            "https://www.hkexnews.hk/start",
            transport=httpx.MockTransport(route),
            resolver=lambda _host: ["93.184.216.34"],
        )
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["url"], "https://www.hkexnews.hk/report")
        self.assertEqual(payload["title"], "Official report")
        self.assertEqual(payload["publication_date"], "2026-10-18")
        self.assertIn("Revenue was 100 million.", payload["content"])
        self.assertNotIn("ignore me", payload["content"])
        self.assertEqual(payload["redirect_count"], 1)
        self.assertEqual(receipt["status"], "ok")
        self.assertEqual(len(requested), 2)

    def test_invalid_lookup_is_reported_as_unknown_without_failing_the_report(self) -> None:
        actions = [
            {"action": "web_search", "arguments": {"entity": "Acme Technologies reported revenue", "topic": "official_results"}},
            {"action": "final", "report": "未能核实该项外部资料，故标为未知。"},
        ]
        calls = 0

        def request_turn(_messages):
            nonlocal calls
            action = actions[calls]
            calls += 1
            return _model_completion(action)

        result = tools.run_action_loop(
            [{"role": "system", "content": "PDF research"}],
            context=self.context,
            response_schema={"type": "object"},
            request_turn=request_turn,
            web_call=lambda *_args: self.fail("invalid entity must not be sent to the provider"),
        )
        self.assertEqual(result["analysis_markdown"], actions[-1]["report"])
        self.assertEqual(result["tool_receipts"][0]["status"], "failed")

    def test_action_parser_rejects_duplicate_keys_and_nonfinite_values(self) -> None:
        duplicated_action = '{"action":"final","action":"read","report":"ignored"}'
        completion = SimpleNamespace(
            final_text=json.dumps({"analysis_markdown": duplicated_action}, ensure_ascii=False)
        )
        with self.assertRaisesRegex(tools.PdfToolError, "PDF_ACTION_JSON_INVALID"):
            tools._action_from_completion(completion)

        nonfinite_outer = SimpleNamespace(final_text='{"analysis_markdown":NaN}')
        with self.assertRaisesRegex(tools.PdfToolError, "PDF_ACTION_RESPONSE_INVALID"):
            tools._action_from_completion(nonfinite_outer)


if __name__ == "__main__":
    unittest.main()


def test_budgeted_read_keeps_complete_initial_chunk_and_history(monkeypatch):
    messages=[{'role':'system','content':'research only'},{'role':'user','content':'complete original chunk完整原文'*50}]
    page='中文123ABC'*500
    context={'page_input_sha256':'a'*64,'pages':[{'page_number':1,'page_total':1,'text':page,'text_sha256':_sha(page)}]}
    read={'action':'read','arguments':{'page_number':1,'start_offset':5,'max_characters':2000}}
    raw=_model_completion(read).final_text;schema={'type':'object'}
    original=json.dumps(messages,ensure_ascii=False,sort_keys=True)
    limit=tools._envelope_size(messages,schema)+len(raw.encode())+1500
    monkeypatch.setattr(tools,'MAX_REQUEST_ENVELOPE_BYTES',limit)
    observation=tools._read_pdf(context,read['arguments'])
    shown,limited=tools._budget_read_observation(messages,raw,read,observation,schema)
    assert limited and shown['text']==page[5:shown['end_offset']]
    assert shown['start_offset']==5 and shown['truncated'] and shown['page_text_sha256']==_sha(page)
    assert shown['next_action_required']=='final' and shown['observation_budget_limited']
    assert tools._envelope_size(messages+[{'role':'assistant','content':raw},tools._observation_message(shown)],schema)<=limit
    assert json.dumps(messages,ensure_ascii=False,sort_keys=True)==original


def test_budgeted_loop_requires_final_after_explicit_limited_read(monkeypatch):
    import pytest
    messages=[{'role':'system','content':'research'},{'role':'user','content':'full chunk'*40}]
    page='中文'*1500;context={'page_input_sha256':'a'*64,'pages':[{'page_number':1,'page_total':1,'text':page,'text_sha256':_sha(page)}]}
    read={'action':'read','arguments':{'page_number':1,'max_characters':2000}}
    schema={'type':'object'};limit=tools._envelope_size(messages,schema)+len(_model_completion(read).final_text.encode())+1500
    monkeypatch.setattr(tools,'MAX_REQUEST_ENVELOPE_BYTES',limit)
    calls=[];receipts=[]
    def request(conversation):
        calls.append(conversation)
        return _model_completion(read if len(calls)==1 else {'action':'final','report':'bounded supplied source only'})
    result=tools.run_action_loop(messages,context=context,response_schema=schema,request_turn=request,
        web_call=lambda *a:pytest.fail('no external tools'),on_tool_receipt=receipts.append)
    assert len(calls)==2 and result['analysis_markdown']=='bounded supplied source only'
    assert receipts[0]['observation_budget_limited'] and receipts[0]['next_action_required']=='final'
    observation=json.loads(calls[1][-1]['content'].split('\n',1)[1])
    assert receipts[0]['result_sha256']==tools._sha(observation)
    assert calls[1][:2]==messages
    calls.clear()
    with pytest.raises(tools.PdfToolError,match='FINAL_REQUIRED_AFTER_BUDGET'):
        tools.run_action_loop(messages,context=context,response_schema=schema,request_turn=lambda c:(_model_completion(read)),web_call=lambda *a:None)


def test_budget_no_fit_or_nonread_is_fail_closed_without_more_request(monkeypatch):
    import pytest
    messages=[{'role':'system','content':'original complete input'}];schema={'type':'object'}
    monkeypatch.setattr(tools,'MAX_REQUEST_ENVELOPE_BYTES',tools._envelope_size(messages,schema)+1)
    with pytest.raises(tools.PdfToolError,match='ENVELOPE_BUDGET_EXCEEDED'):
        tools._budget_read_observation(messages,'large model action',{'action':'read','arguments':{}},
            {'ok':True,'text':'x','start_offset':0,'page_characters':1},schema)
    with pytest.raises(tools.PdfToolError,match='ENVELOPE_BUDGET_EXCEEDED'):
        tools._budget_read_observation(messages,'action',{'action':'search_pdf'},{'ok':True,'matches':['x'*5000]},schema)
