"""Editorial behavior tests: date boundaries, isolation, provenance and graceful fallback."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import cluster
import rank
import readfull
import summarize

NOW = datetime(2026, 10, 18, 4, tzinfo=timezone.utc)


def event(index, category="games", **overrides):
    value = {
        "key": f"event-{index}", "title": f"New game update {index}",
        "url": f"https://example.com/story/{index}", "category": category,
        "sources": [f"Publisher {index % 5}"], "lang": "en", "tier": 2,
        "published": (NOW - timedelta(hours=12)).isoformat(), "undated": False,
        "summary_raw": "A factual game update with details about the new campaign and features. " * 2,
        "pool": "main", "coverage": 1,
    }
    value.update(overrides)
    return value


class EditorialRules(unittest.TestCase):
    def test_ai_release_wave_cannot_dominate_game_daily(self):
        events = [event(i) for i in range(15)]
        events += [event(i + 100, "ai", title=f"Launch new coding tool {i}", tier=1, coverage=100) for i in range(40)]
        digest = rank.build_digest(events, {}, NOW)
        self.assertEqual(len(digest["news"]), 15)
        self.assertLessEqual(len(digest["ai"]), 2)
        self.assertTrue(all(e["category"] != "ai" for e in digest["news"] + digest["features"]))

    def test_missing_old_and_future_dates_never_become_news(self):
        events = [event(1, published=None, undated=True),
                  event(2, published=(NOW - timedelta(days=10)).isoformat()),
                  event(3, published=(NOW + timedelta(hours=1)).isoformat()), event(4)]
        digest = rank.build_digest(events, {}, NOW)
        self.assertEqual([e["key"] for e in digest["news"]], ["event-4"])

    def test_old_analysis_can_be_a_feature_with_short_page_excerpt(self):
        entry = event(1, "design", title="网状构筑过程设计", summary_raw="研究构筑的转型成本。",
                      content_kind="page_excerpt", published=(NOW - timedelta(days=8)).isoformat())
        digest = rank.build_digest([entry], {}, NOW)
        self.assertEqual(len(digest["features"]), 1)
        self.assertEqual(digest["news"], [])

    def test_previously_reported_url_is_suppressed_even_if_title_changes(self):
        entry = event(1, url="https://example.com/story/1?utm_source=feed")
        memory = {"old-key": {"last_seen": "2026-10-17", "urls": ["https://example.com/story/1"]}}
        self.assertFalse(rank.build_digest([entry], memory, NOW)["news"])

    def test_same_day_rerun_remains_visible_and_does_not_double_count(self):
        with tempfile.TemporaryDirectory() as directory:
            path, memory = os.path.join(directory, "memory.json"), {}
            rank.save_memory(path, memory, [event(1)], "2026-10-18")
            rank.save_memory(path, memory, [event(1)], "2026-10-18")
            self.assertEqual(memory["event-1"]["times"], 1)
            self.assertEqual(len(rank.build_digest([event(1)], memory, NOW)["news"]), 1)

    def test_source_cap_keeps_one_publisher_from_filling_daily(self):
        events = [event(i, sources=["Flood publisher"]) for i in range(20)]
        events += [event(99, sources=["Different publisher"], lang="zh")]
        digest = rank.build_digest(events, {}, NOW)
        self.assertEqual(len(digest["news"]), 4)

    def test_unresolved_community_question_is_not_selected(self):
        entry = event(1, "design", title="Help me with a combat system", tier=3)
        digest = rank.build_digest([entry], {}, NOW)
        self.assertFalse(digest["features"] or digest["news"])

    def test_failed_old_feature_is_not_demoted_to_fresh_news(self):
        digest = rank.build_digest([event(1, "design", published="2020-04-25")], {}, NOW)
        summarize.process_digest(digest)
        self.assertEqual(digest["features"], [])
        self.assertEqual(digest["news"], [])

    def test_readable_reserve_replaces_failed_feature(self):
        entries = [event(i, "design", has_body=False) for i in range(3)]
        entries.append(event(90, "design", library=True, has_body=True, body="Verified original article",
                             published="2020-04-25", sources=["Library Author"]))
        digest = rank.build_digest(entries, {}, NOW)
        self.assertTrue(any(e.get("library") for e in digest["feature_candidates"]))
        response = {"suitable": True, "title_cn": "具体的设计方法", "what": "作者说明了具体设计方法与适用条件。",
                    "why": "作者比较了不同方法的取舍。", "for_you": "可以研究这些条件是否适合自己的项目。"}
        with patch("summarize._call", return_value=response):
            summarize.process_digest(digest, object())
        self.assertEqual(len(digest["features"]), 1)
        self.assertTrue(digest["features"][0]["library"])
        self.assertNotIn("feature_candidates", digest)


class EvidenceAndClustering(unittest.TestCase):
    def raw(self, index, **kwargs):
        value = event(index)
        value.update(id=index, source="Original" if index == 1 else "Other", signals={})
        value.update(kwargs)
        return value

    def test_missing_dates_do_not_crash_or_gain_today(self):
        results = cluster.build_events([self.raw(1, published=None, undated=True)])
        self.assertIsNone(results[0]["published"])
        self.assertTrue(results[0]["undated"])

    def test_same_url_is_deduplicated_without_api(self):
        items = [self.raw(1), self.raw(2, title="Translated title", url="https://example.com/story/1?utm_medium=rss")]
        self.assertEqual(len(cluster.build_events(items)), 1)

    def test_summary_stays_with_its_publisher(self):
        items = [self.raw(1, tier=1, summary_raw="Original excerpt"),
                 self.raw(2, url="https://example.com/story/1", summary_raw="Another publisher's much longer excerpt" * 8)]
        result = cluster.build_events(items)[0]
        self.assertEqual(result["summary_raw"], "Original excerpt")

    def test_long_rss_excerpt_is_never_mislabeled_full_article(self):
        entry = event(1, summary_raw="x" * 600, rss_content="y" * 1800)
        with patch("readfull.extract", return_value=None):
            readfull.enrich([entry], workers=1)
        self.assertFalse(entry["has_body"])
        self.assertEqual(entry["body"], "")

    def test_video_landing_page_is_not_transcript(self):
        entry = event(1, requires_transcript=True)
        with patch("readfull.extract") as extract:
            readfull.enrich([entry], workers=1)
        extract.assert_not_called()
        self.assertFalse(entry["has_body"])

    def test_excerpt_summary_cannot_add_design_claims(self):
        entry = event(1, section="news", has_body=False)
        result = {"suitable": True, "title_cn": "新版本内容", "what": "来源明确列出的新版本内容。",
                  "why": "Unverified inference", "for_you": "Unsupported advice"}
        with patch("summarize._call", return_value=result):
            output = summarize.summarize_one(object(), "mock", entry)
        self.assertEqual(output["why"], "")
        self.assertEqual(output["for_you"], "")
        self.assertEqual(output["degraded"], "source_excerpt")


if __name__ == "__main__":
    unittest.main()
