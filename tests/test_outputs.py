"""Output checks: preserve dates, escape external content, keep editions usable."""
import json
import os
import sys
import unittest
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import feed
import render

ROOT = os.path.join(os.path.dirname(__file__), "..")


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.anchors = [], []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "a" and attrs.get("href", "").startswith("#"):
            self.anchors.append(attrs["href"][1:])


class OutputTests(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, "data", "preview_digest.json"), encoding="utf-8") as handle:
            self.digest = json.load(handle)

    def test_preview_has_three_sections_and_valid_deep_links(self):
        page = render.render(self.digest)
        parser = Links()
        parser.feed(page)
        self.assertEqual(len(parser.ids), len(set(parser.ids)))
        self.assertTrue(all(anchor in parser.ids for anchor in parser.anchors))
        self.assertIn("试刊", page)
        self.assertIn("news-language", page)
        self.assertIn("news-search", page)
        self.assertIn("策划精选", page)

    def test_feed_contains_all_three_sections_with_unique_ids(self):
        tree = ET.fromstring(feed.build(self.digest))
        items = tree.findall("./channel/item")
        expected = sum(len(self.digest[section]) for section in ("news", "features", "ai"))
        self.assertEqual(len(items), expected)
        self.assertEqual(len({e.findtext("guid") for e in items}), expected)
        self.assertEqual({e.findtext("category") for e in items}, {"今日游戏日报", "策划精选", "AI 精华"})

    def test_unknown_and_day_precision_dates_do_not_invent_timestamps(self):
        self.assertEqual(feed._pubdate({"published": None, "undated": True}), "")
        self.assertEqual(feed._pubdate({"published": "2026-10-17", "published_precision": "day"}), "")
        self.assertIn("2026.10.17", render._published({"published": "2026-10-16T16:00:00+00:00"}, full=True))

    def test_untrusted_text_and_unsafe_links_are_escaped(self):
        self.digest["news"][0].update(title_cn="<script>alert(1)</script>", url="javascript:alert(1)")
        page = render.render(self.digest)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertNotIn('href="javascript:', page)
        ET.fromstring(feed.build(self.digest))

    def test_formal_edition_keeps_earlier_issue_accessible(self):
        self.digest.pop("preview", None)
        self.digest["earlier_editions"] = [
            {"file": "2026-10-18-ai.html", "label": "改版前的 AI 日报"},
            {"file": "../outside.html", "label": "invalid"},
        ]
        page = render.render(self.digest)
        archived = render.render(self.digest, archive_page=True)
        self.assertIn('href="archive/2026-10-18-ai.html"', page)
        self.assertIn('href="2026-10-18-ai.html"', archived)
        self.assertNotIn('href="../outside.html"', page)
        self.assertNotIn('<div class="preview-note"', page)
        tree = ET.fromstring(feed.build(self.digest))
        self.assertTrue(tree.findtext("./channel/title").startswith("策划日报"))
        self.assertNotIn("试刊", tree.findtext("./channel/title"))
        self.assertNotIn("127.0.0.1", feed.build(self.digest))


if __name__ == "__main__":
    unittest.main()
