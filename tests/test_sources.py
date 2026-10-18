"""Regression checks for dates, source evidence and the public-page adapters."""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import feedparser
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import config
import fetch_sources as fetch


class SourceIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 18, 5, tzinfo=timezone.utc)
        self.clock = patch.object(fetch, "NOW", self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.source = {"name": "Example", "url": "https://example.com/feed", "tier": 2,
                       "lang": "en", "category": "games"}
        fetch.FETCH_ERRORS.clear()
        fetch.HEALTH.clear()
        fetch.SOURCE_DETAILS.clear()

    @staticmethod
    def response(code=200, text="content"):
        response = requests.Response()
        response.status_code = code
        response.url = "https://example.com/feed"
        response.encoding = "utf-8"
        response._content = text.encode("utf-8")
        response._content_consumed = True
        return response

    def test_transient_failure_recovers_with_one_retry(self):
        for failure in (requests.ReadTimeout(), self.response(503)):
            with self.subTest(failure=type(failure).__name__), \
                    patch.object(fetch._session, "get", side_effect=[failure, self.response()]) as get, \
                    patch.object(fetch.time, "sleep"):
                fetch.FETCH_ERRORS[self.source["url"]] = "PreviousFailure"
                self.assertEqual(fetch._fetch(self.source["url"]), "content")
                self.assertEqual(get.call_count, 2)
                self.assertNotIn(self.source["url"], fetch.FETCH_ERRORS)

    def test_transient_failure_has_a_bounded_retry(self):
        with patch.object(fetch._session, "get", side_effect=requests.ReadTimeout()) as get, \
                patch.object(fetch.time, "sleep"):
            self.assertIsNone(fetch._fetch(self.source["url"]))
        self.assertEqual(get.call_count, 2)
        status = fetch._source_status(self.source)
        self.assertEqual(status["state"], "error")
        self.assertIn("超时", status["detail"])

    def test_access_restrictions_are_not_retried_or_reported_as_parser_errors(self):
        for code in (401, 403, 412, 429):
            with self.subTest(code=code), \
                    patch.object(fetch._session, "get", return_value=self.response(code)) as get, \
                    patch.object(fetch.time, "sleep") as sleep:
                self.assertIsNone(fetch._fetch(self.source["url"]))
                self.assertEqual(get.call_count, 1)
                sleep.assert_not_called()
                status = fetch._source_status(self.source)
                self.assertEqual(status["state"], "blocked")
                self.assertIn(str(code), status["detail"])

    def test_missing_feed_is_reported_with_http_status_without_retry(self):
        with patch.object(fetch._session, "get", return_value=self.response(404)) as get:
            self.assertIsNone(fetch._fetch(self.source["url"]))
        self.assertEqual(get.call_count, 1)
        self.assertIn("HTTP 404", fetch._source_status(self.source)["detail"])

    def test_old_feed_is_empty_rather_than_a_fetch_failure(self):
        xml = ('<rss version="2.0"><channel><item><title>Old update</title>'
               '<link>https://example.com/a</link><pubDate>Tue, 01 Sep 2026 00:00:00 GMT</pubDate>'
               '</item></channel></rss>')
        with patch.object(fetch, "_fetch", return_value=xml):
            self.assertEqual(fetch._fetch_rss(self.source), [])
        status = fetch._source_status(self.source)
        self.assertEqual(status["state"], "empty")
        self.assertIn("读取 1 条订阅记录", status["detail"])

    def test_empty_or_html_feed_response_is_a_format_error_not_no_recent_content(self):
        for raw in ("", "<html><h1>Page unavailable</h1></html>"):
            with self.subTest(raw=raw), patch.object(fetch, "_fetch", return_value=raw):
                self.assertEqual(fetch._fetch_rss(self.source), [])
                status = fetch._source_status(self.source)
                self.assertEqual(status["state"], "error")
                self.assertIn("RSS / Atom", status["detail"])

    def test_partial_detail_failures_remain_visible_alongside_candidates(self):
        source = dict(self.source, link_pattern=r"^/articles/\d+$")
        listing = '<a href="/articles/1">one</a><a href="/articles/2">two</a>'
        article = '<h1>Design notes</h1><meta property="article:published_time" content="2026-10-17T12:00:00Z">'

        def reply(url, **kwargs):
            if url == source["url"]:
                return self.response(text=listing)
            return self.response(text=article) if url.endswith("/1") else self.response(403)

        with patch.object(fetch._session, "get", side_effect=reply):
            items = fetch._fetch_page_source(source)
        self.assertEqual(len(items), 1)
        status = fetch._source_status(source)
        self.assertEqual(status["state"], "degraded")
        self.assertEqual(status["count"], 1)
        self.assertIn("1 篇未能读取（HTTP 403）", status["detail"])

    def test_missing_publication_date_is_not_replaced_with_fetch_time(self):
        entry = feedparser.FeedParserDict(title="Game update", link="https://example.com/a",
                                         updated="2026-10-17T13:00:00Z")
        item = fetch._parse_entry(entry, self.source)
        self.assertIsNone(item["published"])
        self.assertTrue(item["undated"])
        self.assertEqual(item["updated"], "2026-10-17T13:00:00+00:00")

    def test_future_items_are_rejected_and_design_has_its_own_window(self):
        entry = feedparser.FeedParserDict(title="Game design", link="https://example.com/a",
                                         published="2026-10-19T00:00:00Z")
        self.assertIsNone(fetch._parse_entry(entry, self.source))
        entry["published"] = "2026-10-01T00:00:00Z"
        self.assertIsNone(fetch._parse_entry(entry, self.source))
        design = dict(self.source, category="design", window_hours=720)
        self.assertIsNotNone(fetch._parse_entry(entry, design))

    def test_encoded_content_survives_summary_truncation(self):
        body = "<p>" + "content " * 200 + "END_OF_ARTICLE</p>"
        xml = ('<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">'
               '<channel><item><title>Design notes</title><link>https://example.com/a</link>'
               '<description>Short summary</description><content:encoded><![CDATA['
               + body + ']]></content:encoded></item></channel></rss>')
        item = fetch._parse_entry(feedparser.parse(xml).entries[0], self.source)
        self.assertEqual(item["summary_raw"], "Short summary")
        self.assertTrue(item["rss_content"].endswith("END_OF_ARTICLE"))
        self.assertEqual(item["content_kind"], "rss_content")

    def test_long_summary_alone_is_never_promoted_to_rss_content(self):
        entry = feedparser.FeedParserDict(title="Discussion", link="https://example.com/a",
                                         summary="A" * 900)
        item = fetch._parse_entry(entry, self.source)
        self.assertEqual(len(item["summary_raw"]), 600)
        self.assertEqual(item["rss_content"], "")
        self.assertEqual(item["content_kind"], "rss_summary")

    def test_page_adapter_uses_publication_metadata_not_related_article_dates(self):
        raw = ('<meta property="article:published_time" content="2026-10-17T12:00:00+08:00">'
               '<meta property="article:modified_time" content="2026-10-18T09:00:00+08:00">'
               '<h1>Design <em>notes</em></h1><aside>2026-10-18</aside><h1>Related articles</h1>')
        item = fetch._parse_page_article(raw, "https://example.com/a", self.source)
        self.assertEqual(item["published"], "2026-10-17T04:00:00+00:00")
        self.assertEqual(item["title"], "Design notes")

    def test_indienova_yearless_header_remains_undated(self):
        raw = '<h1>设计分析</h1><span class="header-info">作者：某人<br>前天 10-16 14:00</span>'
        item = fetch._parse_page_article(raw, "https://example.com/a", self.source)
        self.assertIsNone(item["published"])
        self.assertTrue(item["undated"])
        full = raw.replace("前天 10-16 14:00", "2026-10-16")
        dated = fetch._parse_page_article(full, "https://example.com/a", self.source)
        self.assertEqual(dated["published"], "2026-10-15T16:00:00+00:00")

    def test_listing_rejects_external_links_and_navigation(self):
        source = dict(self.source, link_pattern=r"^/articles/\d+$")
        listing = fetch._ListingParser(source)
        listing.feed('<a href="/articles/7?utm_source=test">article</a>'
                     '<a href="https://other.com/articles/8">external</a>'
                     '<a href="/articles/">navigation</a><a href="/articles/7">duplicate</a>')
        self.assertEqual(listing.urls, ["https://example.com/articles/7"])

    def test_specific_design_category_retains_rss_evidence_when_deduplicated(self):
        feed_item = fetch._record("Article", "https://example.com/a", self.source,
                                  self.now, "Summary", rss_content="Original text")
        page_item = fetch._record("Article", "https://example.com/a", dict(self.source, category="design"),
                                  None, "", content_kind="page_excerpt")
        result = fetch._deduplicate([feed_item, page_item])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["category"], "design")
        self.assertEqual(result[0]["rss_content"], "Original text")
        self.assertFalse(result[0]["undated"])

    def test_same_day_health_rerun_does_not_increment_streak(self):
        previous = {"date": "2026-10-18", "counts": {"Example": 0}, "zero_streak": {"Example": 4}}
        result = fetch._health_payload({"Example": 0}, previous, "2026-10-18")
        self.assertEqual(result["zero_streak"]["Example"], 4)

    def test_default_sources_do_not_include_broad_community_or_research_pools(self):
        self.assertFalse(config.ENABLE_HN)
        self.assertFalse(config.ENABLE_HF_PAPERS)
        self.assertFalse(config.ENABLE_GITHUB_TRENDING)
        self.assertFalse(config.DIVERSE_SOURCES)
        for source in config.RSS_SOURCES + config.PAGE_SOURCES:
            self.assertIn(source["category"], {"games", "design", "development", "ai"})
            self.assertNotIn("reddit.com", source["url"])


if __name__ == "__main__":
    unittest.main()
