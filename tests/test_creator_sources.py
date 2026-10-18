"""Evidence-boundary tests for public creator candidates; no live requests."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import creator_sources as cs
from source_directory import render_directory, _time

NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
CATALOG = json.loads(cs.CATALOG_PATH.read_text(encoding="utf-8"))


class CreatorSourcesTests(unittest.TestCase):
    def source(self, name):
        return next(s for s in CATALOG if s["id"] == name)

    def test_official_atom_preserves_video_evidence(self):
        xml = '''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/">
        <yt:channelId>UCqJ-Xo29CKyLTjn6z2XwYAw</yt:channelId><entry><yt:videoId>abcdefghijk</yt:videoId><title>Design talk</title><published>2026-10-17T10:00:00Z</published><media:group><media:description>A description is not a transcript.</media:description></media:group></entry></feed>'''
        with patch.object(cs, "_get", return_value=xml):
            articles, _ = cs._youtube(self.source("youtube-gmtk"), NOW)
        self.assertEqual(len(articles), 1)
        item = articles[0]
        self.assertEqual(item["published"], "2026-10-17T10:00:00+00:00")
        self.assertEqual(item["published_precision"], "second")
        self.assertTrue(item["requires_transcript"])
        self.assertTrue(item["discovery_only"])
        self.assertFalse(item["has_body"])
        self.assertEqual(item["body"], "")
        self.assertEqual(item["evidence_kind"], "video_metadata")

    def test_html_uses_selected_tab_without_inventing_relative_date(self):
        video = {"contentId": "abcdefghijk", "contentType": "LOCKUP_CONTENT_TYPE_VIDEO", "metadata": {"lockupMetadataViewModel": {
            "title": {"content": "Systems design"}, "metadata": {"contentMetadataViewModel": {"metadataRows": [{"metadataParts": [{"text": {"content": "2mo ago"}, "accessibilityLabel": "2 months ago"}]}]}}}}}
        data = {"contents": {"twoColumnBrowseResultsRenderer": {"tabs": [
            {"tabRenderer": {"selected": True, "title": "Videos", "content": {"lockupViewModel": video}}},
            {"tabRenderer": {"selected": False, "content": {"videoRenderer": {"videoId": "other000000", "title": {"simpleText": "Not selected"}}}}}
        ]}}, "recommendations": {"videoRenderer": {"videoId": "else0000000", "title": {"simpleText": "Unrelated"}}}}
        items = cs._youtube_html("var ytInitialData = " + json.dumps(data) + ";", self.source("youtube-gmtk"), NOW)
        self.assertEqual(len(items), 1)
        self.assertIsNone(items[0]["published"])
        self.assertTrue(items[0]["undated"])
        self.assertEqual(items[0]["published_text"], "2 months ago")

    def test_youtube_never_falls_back_after_platform_block(self):
        with patch.object(cs, "_get", side_effect=cs.SourceError("blocked", "HTTP 403")) as get:
            articles, status = cs._fetch_one(self.source("youtube-gmtk"), NOW)
        self.assertEqual(get.call_count, 1)
        self.assertEqual(articles, [])
        self.assertEqual(status["state"], "blocked")

    def test_bilibili_risk_code_is_blocked(self):
        with patch.object(cs, "_get", return_value='{"code":-352,"message":"risk control"}'):
            items, status = cs._fetch_one(self.source("bilibili-youxiputao"), NOW)
        self.assertEqual(items, [])
        self.assertEqual(status["state"], "blocked")
        self.assertEqual(status["count"], 0)

    def test_bilibili_filters_old_and_future_but_keeps_missing_date_explicit(self):
        vlist = [{"bvid": "BV123", "title": "Fresh", "created": NOW.timestamp() - 3600},
                 {"bvid": "BVold", "title": "Old", "created": NOW.timestamp() - 800 * 3600},
                 {"bvid": "BVfuture", "title": "Future", "created": NOW.timestamp() + 86400},
                 {"bvid": "BVmissing", "title": "Undated", "description": "Metadata only"}]
        with patch.object(cs, "_get", return_value=json.dumps({"code": 0, "data": {"list": {"vlist": vlist}}})):
            items, _ = cs._bilibili(self.source("bilibili-youxiputao"), NOW)
        self.assertEqual([i["title"] for i in items], ["Fresh", "Undated"])
        self.assertTrue(items[1]["undated"])
        self.assertFalse(items[1]["has_body"])

    def test_author_full_text_is_public_but_not_today_news(self):
        listing = "[游戏中的时间](https://docs.xpaidia.com/ficstruction/undo/example.md)"
        body = "# 游戏中的时间\n\n本文写作于2020/09。\n" + "游戏时间与玩家体验。" * 70
        with patch.object(cs, "_get", side_effect=[listing, body]):
            items, _ = cs._author(self.source("author-ye-zitao"), NOW)
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]["has_body"])
        self.assertEqual(items[0]["publication_scope"], "public")
        self.assertTrue(items[0]["classic_discovery"])
        self.assertIsNone(items[0]["published"])
        self.assertEqual(items[0]["url"], "https://docs.xpaidia.com/ficstruction/undo/example")

    def test_member_logs_always_require_review(self):
        source = self.source("indienova-members")
        listing = '<a href="/u/author/blogread/123">Post</a>'
        article = '<meta property="article:published_time" content="2026-10-17T12:00:00+08:00"><h1>开发复盘</h1>'
        with patch.object(cs, "_get", side_effect=[listing, article]):
            items, _ = cs._community(source, NOW)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["tier"], 3)
        self.assertTrue(items[0]["requires_review"])
        self.assertEqual(items[0]["evidence_kind"], "community_post")

    def test_wechat_manual_does_not_fetch(self):
        with patch.object(cs, "_get") as get:
            items, status = cs._fetch_one(self.source("wechat-yutang"), NOW)
        get.assert_not_called()
        self.assertEqual(items, [])
        self.assertEqual(status["state"], "manual")

    def test_member_article_ignores_comment_h1_and_footer_clock(self):
        listing = '<a href="/u/author/blogread/123">Post</a>'
        article = '<title>真实日志标题 | indienova 独立游戏</title><h1>参与此日志的讨论</h1><li><i class="icon-calendar-empty"></i> 昨天 10-17 23:51</li><article>图片与短文</article><footer>2026-10-18 12:00:00</footer>'
        with patch.object(cs, "_get", side_effect=[listing, article]):
            items, _ = cs._community(self.source("indienova-members"), NOW)
        self.assertEqual(items[0]["title"], "真实日志标题")
        self.assertIsNone(items[0]["published"])
        self.assertEqual(items[0]["published_text"], "昨天 10-17 23:51")
        self.assertFalse(items[0]["has_body"])
        self.assertEqual(items[0]["summary_raw"], "图片与短文")

    def test_412_does_not_claim_login_can_fix_access(self):
        class Response:
            status_code = 412
        with patch.object(cs.requests, "get", return_value=Response()):
            with self.assertRaises(cs.SourceError) as caught:
                cs._get("https://api.bilibili.com/public")
        self.assertEqual(caught.exception.state, "blocked")

    def test_member_day_only_date_keeps_day_precision(self):
        listing = '<a href="/u/author/blogread/123">Post</a>'
        article = '<title>日志 | indienova 独立游戏</title><li><i class="icon-calendar-empty"></i> 2026-10-17</li><article>短文</article>'
        with patch.object(cs, "_get", side_effect=[listing, article]):
            items, _ = cs._community(self.source("indienova-members"), NOW)
        self.assertEqual(items[0]["published_precision"], "day")


class SourceDirectoryTests(unittest.TestCase):
    def test_report_time_is_beijing_time(self):
        self.assertEqual(_time("2026-10-18T07:05:00Z"), "2026-10-18 15:05（北京时间）")

    def test_manual_inbox_does_not_inflate_external_source_count(self):
        report = {"sources": [{"id": "manual-inbox", "name": "人工线索收件箱", "platform": "手动收录", "state": "manual", "count": 0}]}
        text = render_directory(report, CATALOG)
        self.assertIn(f'<strong>{len(CATALOG)}</strong><span>外部来源', text)
        self.assertIn(f'{len(CATALOG) + 1} 个入口', text)

    def test_missing_report_is_not_checked_instead_of_zero(self):
        text = render_directory(None, CATALOG)
        self.assertEqual(text.count('class="source"'), len(CATALOG))
        self.assertIn('data-state="not_checked"', text)
        self.assertIn('<strong>—</strong><span>条候选</span>', text)

    def test_untrusted_titles_and_urls_cannot_execute(self):
        report = {"sources": [{"id": "custom", "name": "<script>bad</script>", "platform": "Discord", "url": "javascript:bad()", "state": "needs_auth", "count": 0, "detail": "缺少DISCORD_BOT_TOKEN。 Bearer never-show-me"}]}
        text = render_directory(report, [])
        self.assertNotIn('<script>bad</script>', text)
        self.assertNotIn('javascript:bad()', text)
        self.assertNotIn('never-show-me', text)
        self.assertNotIn('DISCORD_BOT_TOKEN', text)
        self.assertIn('待授权', text)

    def test_private_channel_payload_is_not_rendered(self):
        report = {"sources": [{"id": "custom", "name": "Community", "platform": "Discord", "state": "ok", "count": 2, "detail": "公开采集状态", "channels": [{"messages": "private message contents"}]}], "counts": {"restricted_withheld": 2}}
        text = render_directory(report, [])
        self.assertNotIn('private message contents', text)
        self.assertIn('2 条受限内容', text)


if __name__ == "__main__":
    unittest.main()
