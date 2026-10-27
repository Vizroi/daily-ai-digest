"""Ranking windows, unavailable values and safe rendering."""
import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from indie_render import model_game, rank_games, render_indie_market


def game(appid=1):
    return {"appid": appid, "name": f"Game {appid}", "tags": ["Indie", "Puzzle"],
            "current_players": 0, "players_status": "fresh", "players_observed_at": "2026-10-27T12:00:00+08:00",
            "indie_top_sellers_rank": appid, "indie_top_sellers_status": "fresh",
            "review_windows": {str(days): {"count": days * 10, "positive_percent": 90,
                "status": "fresh", "sampled_at": "2026-10-27T12:00:00+08:00"} for days in (1, 7, 30)}}


class IndieRenderTests(unittest.TestCase):
    def test_window_changes_ranking_and_filters_combine(self):
        first, second = game(1), game(2)
        first["review_windows"]["1"]["count"] = 25
        second["review_windows"]["7"]["count"] = 500
        models = [model_game(first), model_game(second)]
        self.assertEqual(rank_games(models, days=1)[0]["appid"], 1)
        self.assertEqual(rank_games(models, days=7)[0]["appid"], 2)
        self.assertEqual([g["appid"] for g in rank_games(models, query="GAME 2", style="解谜")], [2])
        self.assertEqual(rank_games(models, style="卡牌"), [])

    def test_missing_and_stale_values_are_excluded_without_losing_zero(self):
        first, second = game(1), game(2)
        first["review_windows"]["7"].update(count=0, positive_percent=None)
        second["review_windows"]["7"]["status"] = "stale"
        second["players_status"] = "stale"
        second["indie_top_sellers_status"] = "stale"
        models = [model_game(first), model_game(second)]
        self.assertEqual([g["appid"] for g in rank_games(models)], [1])
        self.assertEqual([g["appid"] for g in rank_games(models, metric="players")], [1])
        self.assertEqual([g["appid"] for g in rank_games(models, metric="rank")], [1])
        self.assertEqual(rank_games(models, metric="rate"), [])
        self.assertEqual(models[0]["players"], 0)

    def test_approval_requires_twenty_reviews(self):
        sample = game()
        sample["review_windows"]["1"].update(count=19, positive_percent=100)
        self.assertEqual(rank_games([model_game(sample)], metric="rate", days=1), [])
        sample["review_windows"]["1"]["count"] = 20
        self.assertEqual(len(rank_games([model_game(sample)], metric="rate", days=1)), 1)

    def test_html_and_json_script_cannot_be_broken_by_external_strings(self):
        sample = game()
        sample["name"] = '</script><script>alert("x")</script>'
        sample["header_image"] = "javascript:alert(1)"
        page = render_indie_market({"games": [sample], "scope_note": "<img src=x onerror=alert(1)>"})
        self.assertNotIn('<script>alert("x")', page)
        self.assertNotIn('src="javascript:', page)
        self.assertNotIn('<img src=x onerror=', page)
        payload = re.search(r'<script type="application/json" id="ranking-data">(.*?)</script>', page, re.S)
        self.assertEqual(json.loads(payload.group(1))["games"][0]["name"], sample["name"])

    def test_empty_page_is_honest_and_retains_functional_structure(self):
        page = render_indie_market({})
        self.assertIn('id="empty-state">本筛选暂无可排名的数据', page)
        self.assertIn('Steam 不公开单款销量与下载次数', page)
        self.assertIn('不是全球销量榜', page)
        self.assertIn('至少 20 条评价', page)
        self.assertIn('b.disabled=snapshot', page)
        self.assertNotIn('data-appid="', page)


if __name__ == "__main__":
    unittest.main()
