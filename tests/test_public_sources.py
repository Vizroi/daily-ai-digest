"""Public-source boundaries: official provenance, publication dates and failures."""
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import public_sources as public


class Response:
    def __init__(self, text="", status=200, payload=None):
        self.text, self.status_code, self.payload = text, status, payload
        self.content = text.encode("utf-8")
        self.encoding, self.apparent_encoding = "utf-8", "utf-8"

    def json(self):
        if self.payload is not None:
            return self.payload
        return json.loads(self.text)


class PublicSourceTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 18, 5, tzinfo=timezone.utc)
        self.source = {"id": "example", "name": "Example", "url": "https://example.com/feed",
                       "platform": "developer_blog", "adapter": "rss", "tier": 1,
                       "lang": "en", "category": "design", "window_hours": 720,
                       "max_per_source": 20, "evidence_kind": "developer_article"}
        self.steam = dict(self.source, adapter="steam_announcements", platform="steam",
                          appid=427520, category="games", window_hours=72,
                          evidence_kind="official_announcement")

    def announcement(self, **values):
        row = {"title": "Update", "url": "https://steamstore-a.akamaihd.net/news/externalpost/announcement/1",
               "appid": 427520, "feedname": "steam_community_announcements",
               "date": int((self.now - timedelta(hours=1)).timestamp()),
               "is_external_url": True, "contents": "[h1]Design changes[/h1]" + " fact" * 200}
        row.update(values)
        return row

    def test_steam_filters_external_press_and_wrong_app_but_keeps_official_cdn_links(self):
        entries = [self.announcement(), self.announcement(feedname="PCGamer"),
                   self.announcement(appid=1),
                   self.announcement(date=int((self.now + timedelta(days=1)).timestamp()))]
        payload = {"appnews": {"appid": 427520, "newsitems": entries}}
        with patch.object(public, "_get", return_value=Response(payload=payload)) as get:
            rows, status = public._run(self.steam, self.now)
        self.assertEqual(status["state"], "ok")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["evidence_kind"], "official_announcement")
        self.assertEqual(rows[0]["content_kind"], "api_content")
        self.assertFalse(rows[0]["requires_transcript"])
        self.assertGreater(len(rows[0]["rss_content"]), 600)
        self.assertNotIn("[h1]", rows[0]["rss_content"])
        params = get.call_args.kwargs["params"]
        self.assertEqual(params["feeds"], "steam_community_announcements")
        self.assertEqual(params["maxlength"], 0)
        self.assertNotIn("key", params)

    def test_mismatched_steam_response_is_error_not_empty(self):
        with patch.object(public, "_get", return_value=Response(payload={"appnews": {"appid": 1, "newsitems": []}})):
            rows, status = public._run(self.steam, self.now)
        self.assertFalse(rows)
        self.assertEqual(status["state"], "error")

    def test_missing_date_stays_null_instead_of_becoming_fetch_time(self):
        payload = {"appnews": {"appid": 427520, "newsitems": [self.announcement(date=None)]}}
        with patch.object(public, "_get", return_value=Response(payload=payload)):
            rows, _ = public._run(self.steam, self.now)
        self.assertIsNone(rows[0]["published"])
        self.assertTrue(rows[0]["undated"])

    def test_old_official_announcements_report_empty(self):
        old = self.announcement(date=int((self.now - timedelta(days=20)).timestamp()))
        payload = {"appnews": {"appid": 427520, "newsitems": [old]}}
        with patch.object(public, "_get", return_value=Response(payload=payload)):
            rows, status = public._run(self.steam, self.now)
        self.assertFalse(rows)
        self.assertEqual(status["state"], "empty")
        self.assertEqual(status["count"], 0)

    def test_valid_empty_feed_is_different_from_html_or_invalid_json(self):
        empty = '<rss version="2.0"><channel><title>Devlog</title></channel></rss>'
        with patch.object(public, "_get", return_value=Response(empty)):
            _, status = public._run(self.source, self.now)
        self.assertEqual(status["state"], "empty")
        with patch.object(public, "_get", return_value=Response("<html>Site error</html>")):
            _, status = public._run(self.source, self.now)
        self.assertEqual(status["state"], "error")
        with patch.object(public, "_get", return_value=Response("not json")):
            _, status = public._run(self.steam, self.now)
        self.assertEqual(status["state"], "error")

    def test_factorio_updated_does_not_make_an_old_article_new(self):
        atom = ('<feed xmlns="http://www.w3.org/2005/Atom"><title>Factorio</title>'
                '<entry><title>Friday Facts #1</title><id>https://factorio.com/blog/post/fff-1</id>'
                '<link href="https://factorio.com/blog/post/fff-1"/>'
                '<updated>2026-10-17T00:00:00Z</updated></entry></feed>')
        article = '<h1>Friday Facts #1</h1><div>Posted by <a>Developer</a> on 2013-01-01</div>'
        source = dict(self.source, article_date_fallback="factorio_posted")
        with patch.object(public, "_get", side_effect=[Response(atom), Response(article)]):
            rows, status = public._run(source, self.now)
        self.assertEqual(rows, [])
        self.assertEqual(status["state"], "empty")

    def test_page_metadata_reads_article_date_not_related_content_or_modification(self):
        data = {"@graph": [{"@type": "Organization", "datePublished": "2026-10-18"},
                          {"@type": "NewsArticle", "headline": "Design decision",
                           "datePublished": "2026-10-01T12:00:00Z",
                           "dateModified": "2026-10-17T12:00:00Z"},
                          {"@type": "NewsArticle", "datePublished": "2026-10-18T00:00:00Z"}]}
        raw = '<h1>Design decision</h1><script type="application/ld+json">' + json.dumps(data) + "</script>"
        info, _ = public._page_info(raw)
        self.assertEqual(info["published"], datetime(2026, 10, 1, 12, tzinfo=timezone.utc))

    def test_source_http_and_timeout_failures_are_explicit(self):
        for code, expected in [(401, "needs_auth"), (403, "error"), (429, "error"), (500, "error")]:
            with self.subTest(code=code), patch.object(public.requests, "get", return_value=Response(status=code)):
                _, status = public._run(self.source, self.now)
                self.assertEqual(status["state"], expected)
        with patch.object(public.requests, "get", side_effect=requests.Timeout("test")) as get:
            _, status = public._run(self.source, self.now)
        self.assertEqual(status["state"], "error")
        self.assertEqual(get.call_args.kwargs["timeout"], (5, 20))

    def test_riot_legacy_header_date_is_not_replaced_by_related_card_date(self):
        raw = ('<h1>Swarm technology</h1><ul class="article-header__detail-list list--inline">'
               '<li><svg><path d="x"/></svg></li><li>By <strong>Developer</strong></li>'
               '<li><strong>Jul 25, 2025</strong></li></ul>'
               '<time class="summary__date">Oct 17, 2026</time>')
        info, _ = public._page_info(raw)
        self.assertEqual(info["published"], datetime(2025, 7, 25, tzinfo=timezone.utc))
        self.assertEqual(info["precision"], "date")

    def test_one_broken_source_does_not_discard_another_sources_articles(self):
        good = dict(self.steam, id="good", name="Good", url="https://example.com/good")
        bad = dict(self.steam, id="bad", name="Bad", url="https://example.com/bad", appid=1)
        valid = {"appnews": {"appid": 427520, "newsitems": [self.announcement()]}}
        def request(url, **kwargs):
            if kwargs["params"]["appid"] == 1:
                raise public.SourceFailure("error", "test timeout")
            return Response(payload=valid)
        with patch.object(public, "load_catalog", return_value=[bad, good]), patch.object(public, "_get", side_effect=request):
            rows, statuses = public.fetch_sources(self.now)
        self.assertEqual(len(rows), 1)
        self.assertEqual([s["state"] for s in statuses], ["error", "ok"])

    def test_catalog_has_verified_cross_genre_apps_and_bounded_public_sources(self):
        catalog = public.load_catalog()
        steam = [s for s in catalog if s["platform"] == "steam"]
        self.assertGreaterEqual(len(steam), 8)
        self.assertLessEqual(len(steam), 12)
        self.assertEqual(len({s["appid"] for s in steam}), len(steam))
        self.assertEqual(len({s["id"] for s in catalog}), len(catalog))
        for source in catalog:
            self.assertLessEqual(source["max_per_source"], 20)
            self.assertIn(source["evidence_kind"], {"official_announcement", "developer_article"})
            self.assertTrue(source["verification_url"].startswith("https://"))

    def test_listing_does_not_treat_a_changed_site_as_no_new_articles(self):
        source = dict(self.source, adapter="official_listing", link_pattern=r"^/news/[^/]+/?$")
        with patch.object(public, "_get", return_value=Response('<a href="https://other.com/news/a">Other site</a>')):
            _, status = public._run(source, self.now)
        self.assertEqual(status["state"], "error")


if __name__ == "__main__":
    unittest.main()
