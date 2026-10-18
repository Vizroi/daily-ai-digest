"""Cross-adapter evidence boundaries and final edition diversity."""
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import cluster
import fetch_sources
import rank
import readfull
import summarize
import source_registry
from test_editorial import event, NOW


class MultiPlatformTests(unittest.TestCase):
    def raw(self, index, **kwargs):
        result = event(index, **kwargs)
        result.update(id=index, source="Source " + str(index))
        return result

    def test_removed_community_sources_are_not_active_or_scheduled(self):
        self.assertFalse(any(source.get("platform") in {"reddit", "discord"}
                             for source in source_registry.catalog()))
        adapter = SimpleNamespace(fetch_sources=lambda **kwargs: ([], []))
        with patch.object(fetch_sources, "RSS_SOURCES", []), patch.object(fetch_sources, "PAGE_SOURCES", []), \
                patch("importlib.import_module", return_value=adapter) as load, \
                patch.object(source_registry, "inbox_articles", return_value=([], {"id": "manual-inbox", "state": "manual"})):
            articles, _ = fetch_sources.fetch_all()
        self.assertEqual(articles, [])
        self.assertEqual(sorted(call.args[0] for call in load.call_args_list), ["creator_sources", "public_sources"])

    def test_youtube_videos_are_not_merged_by_watch_path(self):
        items = [self.raw(1, url="https://www.youtube.com/watch?v=one"),
                 self.raw(2, url="https://www.youtube.com/watch?v=two")]
        self.assertEqual(len(fetch_sources._deduplicate(items)), 2)

    def test_private_material_never_reaches_model_or_event_output(self):
        item = self.raw(1, publication_scope="restricted", summary_raw="Private discussion")
        with patch("cluster._llm_groups") as model:
            output = cluster.build_events([item], object())
        self.assertEqual(output, [])
        model.assert_not_called()

    def test_private_and_public_text_never_merge(self):
        public = self.raw(1, summary_raw="", publication_scope="public")
        private = self.raw(2, url=public["url"], publication_scope="restricted", rss_content="Private text")
        merged = fetch_sources._deduplicate([public, private])
        self.assertEqual(len(merged), 2)
        self.assertFalse(next(a for a in merged if a["publication_scope"] == "public").get("rss_content"))

    def test_video_provenance_survives_cluster_and_enters_review_queue(self):
        raw = self.raw(1, category="design", requires_transcript=True, discovery_only=True,
                       evidence_kind="video_metadata", platform="YouTube")
        output = cluster.build_events([raw])
        digest = rank.build_digest(output, {}, NOW)
        self.assertEqual(output[0]["evidence_kind"], "video_metadata")
        self.assertEqual(len(digest["review_queue"]), 1)
        self.assertFalse(digest["features"] or digest["news"])

    def test_public_substantive_community_post_requires_editor_acceptance(self):
        entry = event(1, "design", tier=3, platform="reddit", requires_review=True,
                      content_kind="community_selftext", evidence_kind="community_post",
                      rss_content="Author's design tradeoffs and observations. " * 40)
        digest = rank.build_digest([entry], {}, NOW)
        self.assertEqual(len(digest["features"]), 1)
        with patch("readfull.extract") as web:
            readfull.enrich(digest["features"], workers=1)
        web.assert_not_called()
        self.assertEqual(digest["features"][0]["content_kind"], "community_body")
        summarize.process_digest(digest, client=None)
        self.assertFalse(digest["features"] or digest["news"])

    def test_steam_platform_cap_applies_across_different_games(self):
        entries = [event(i, tier=1, sources=[f"Game {i}"], platform="steam") for i in range(12)]
        entries += [event(99, sources=["Chinese publication"], platform="网站 / RSS")]
        selected = rank.build_digest(entries, {}, NOW)["news"]
        self.assertEqual(sum(e["platform"] == "steam" for e in selected), 4)
        self.assertEqual(len(selected), 5)

    def test_api_body_is_used_without_requesting_a_landing_page(self):
        entry = event(1, content_kind="api_content", rss_content="Official patch details." * 80)
        with patch("readfull.extract") as web:
            readfull.enrich([entry], workers=1)
        web.assert_not_called()
        self.assertTrue(entry["has_body"])
        self.assertEqual(entry["content_kind"], "official_announcement_body")

    def test_question_and_private_evidence_cannot_bypass_summary_gate(self):
        with patch("summarize._call") as model:
            self.assertIn("excluded", summarize.summarize_one(object(), "model", event(1, is_question=True)))
            self.assertIn("excluded", summarize.summarize_one(object(), "model", event(2, publication_scope="restricted")))
        model.assert_not_called()

    def test_community_adapter_without_question_flag_still_queues_help(self):
        entry = event(1, "design", title="How can I improve player recovery timing", tier=3,
                      evidence_kind="community_post", has_body=True, body="Question context " * 100,
                      requires_review=True)
        digest = rank.build_digest([entry], {}, NOW)
        self.assertFalse(digest["features"] or digest["news"])
        self.assertEqual(len(digest["review_queue"]), 1)


if __name__ == "__main__":
    unittest.main()
