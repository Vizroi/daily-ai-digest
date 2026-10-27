"""Exact review periods, transparent sample eligibility, and failure retention."""
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import indie_market as market


class IndieMarketTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 27, 12, tzinfo=market.TZ)

    def meta(self):
        return {"app_type": "game", "name": "Small Game", "release_date": "2026-10-01",
                "is_demo": False, "coming_soon": False, "is_free": False,
                "tags": ["Indie", "Puzzle"], "metadata_status": "fresh", "metadata_at": market.stamp(self.now),
                "price": {"currency": "USD", "initial": None, "final": 2499, "discount_percent": 0}}

    def response(self, total=10, positive=8):
        return {"query_summary": {"total_reviews": total, "total_positive": positive, "total_negative": total - positive},
                "total_matching": total, "reviews": [{"timestamp_created": int(self.now.timestamp()) - 1}] if total else []}

    def test_full_price_can_use_final_but_discount_cannot(self):
        meta = self.meta()
        self.assertTrue(market.eligible(meta, self.now))
        meta["price"]["discount_percent"] = 50
        self.assertFalse(market.eligible(meta, self.now))
        meta["price"]["initial"] = 4998
        self.assertFalse(market.eligible(meta, self.now))
        meta["price"]["initial"] = 2500
        self.assertTrue(market.eligible(meta, self.now))

    def test_eligibility_requires_game_release_compact_indie_and_known_price(self):
        for key, value in (("app_type", "dlc"), ("is_demo", True), ("coming_soon", True),
                           ("release_date", "2026-10-28"), ("tags", ["Indie", "Open World"])):
            meta = self.meta()
            meta[key] = value
            self.assertFalse(market.eligible(meta, self.now), (key, value))
        meta = self.meta()
        meta["tags"] = ["Puzzle"]
        self.assertFalse(market.eligible(meta, self.now))
        self.assertTrue(market.eligible(meta, self.now, indie_source_verified=True))
        meta["tags"].append("Indie")
        meta["price"]["final"] = None
        self.assertFalse(market.eligible(meta, self.now))
        meta["is_free"] = True
        self.assertTrue(market.eligible(meta, self.now))

    def test_review_windows_use_explicit_timestamps_not_helpful_day_range(self):
        for days in (1, 7, 30):
            with patch.object(market, "service", return_value=self.response()) as request:
                result = market.review_counts(1, self.now, days)
            payload = request.call_args.args[1]
            self.assertEqual(payload["date_range_end"] - payload["date_range_start"], days * 86400)
            self.assertEqual(payload["filter"], 1)
            self.assertEqual(payload["languages"], ["all"])
            self.assertEqual(payload["purchase_type"], 1)
            self.assertNotIn("day_range", payload)
            self.assertEqual(result["count"], 10)
            self.assertEqual(result["positive_percent"], 80)
            self.assertEqual(result["start"], market.stamp(self.now - timedelta(days=days)))

    def test_zero_reviews_are_real_zero_but_positive_rate_is_missing(self):
        with patch.object(market, "service", return_value=self.response(0, 0)):
            result = market.review_counts(1, self.now, 7)
        self.assertEqual(result["count"], 0)
        self.assertIsNone(result["positive_percent"])
        self.assertEqual(result["status"], "fresh")

    def test_lifetime_summary_uses_consistent_rating_counts_when_matching_cache_lags(self):
        response = self.response(10, 8)
        response["total_matching"] = 12
        with patch.object(market, "service", return_value=response):
            result = market.review_counts(1, self.now)
        self.assertEqual(result["total"], 10)
        self.assertEqual(result["positive_percent"], 80)

    def test_inconsistent_counts_or_ignored_window_fail_closed(self):
        for invalid in ({"total_matching": 11}, {"reviews": [{"timestamp_created": int(self.now.timestamp()) - 2 * 86400}]}):
            response = self.response()
            response.update(invalid)
            with patch.object(market, "service", return_value=response):
                with self.assertRaises(ValueError):
                    market.review_counts(1, self.now, 1)

    def test_failed_window_preserves_original_value_and_period(self):
        old = {"count": 12, "positive": 9, "negative": 3, "positive_percent": 75,
               "start": "2026-10-25T12:00:00+08:00", "end": "2026-10-26T12:00:00+08:00",
               "sampled_at": "2026-10-26T12:00:00+08:00", "status": "fresh"}
        result = market.stale_review(old, self.now, 1, "Timeout")
        self.assertEqual(result["count"], 12)
        self.assertEqual(result["start"], old["start"])
        self.assertEqual(result["end"], old["end"])
        self.assertEqual(result["sampled_at"], old["sampled_at"])
        self.assertEqual(result["status"], "stale")
        missing = market.stale_review({}, self.now, 1, "Timeout")
        self.assertIsNone(missing["count"])
        self.assertEqual(missing["status"], "unavailable")

    def test_failed_online_preserves_old_value_and_unknown_is_not_zero(self):
        old = dict(self.meta(), appid=1, current_players=15, players_observed_at="2026-10-26T12:00:00+08:00")
        with patch.object(market, "request_json", side_effect=requests.Timeout), patch.object(market, "review_counts", side_effect=requests.Timeout):
            game = market.collect_game(1, old, self.meta(), [], {}, {}, self.now, float("inf"))
        self.assertEqual(game["current_players"], 15)
        self.assertEqual(game["players_status"], "stale")
        self.assertEqual(game["players_observed_at"], old["players_observed_at"])
        self.assertIsNone(game["review_windows"]["30"]["count"])

    def test_optional_lifetime_failure_does_not_disable_daily_cache(self):
        def reviews(appid, now, days=None):
            if days is None:
                raise ValueError("optional lifetime counter unavailable")
            return {"count": 10, "positive": 8, "negative": 2, "positive_percent": 80, "status": "fresh"}
        with patch.object(market, "request_json", return_value={"response": {"result": 1, "player_count": 50}}), patch.object(market, "review_counts", side_effect=reviews):
            game = market.collect_game(1, {}, self.meta(), [], {}, {}, self.now, float("inf"))
        self.assertEqual(game["status"], "fresh")
        self.assertEqual(game["review_summary"]["status"], "unavailable")

    def test_global_and_indie_ranks_are_distinct_and_drop_clears_old_rank(self):
        game = {"appid": 1, "top_sellers_rank": 90}
        indie = {"items": [{"appid": 1, "rank": 4}], "observed_at": market.stamp(self.now), "status": "fresh"}
        global_roster = {"items": [{"appid": 2, "rank": 3}], "observed_at": market.stamp(self.now), "status": "fresh"}
        market.apply_rank(game, "indie_top_sellers", indie, self.now)
        market.apply_rank(game, "top_sellers", global_roster, self.now)
        self.assertEqual(game["indie_top_sellers_rank"], 4)
        self.assertIsNone(game["top_sellers_rank"])
        self.assertEqual(game["top_sellers_status"], "not_listed")
        indie["status"] = "stale"
        market.apply_rank(game, "indie_top_sellers", indie, self.now)
        self.assertEqual(game["indie_top_sellers_status"], "stale")

    def test_discovery_failure_retains_old_roster(self):
        old = dict(market.SOURCE_DEFINITIONS[0], items=[{"appid": 10, "rank": 2}],
                   observed_at="2026-10-26T12:00:00+08:00", status="fresh")
        with patch.object(market, "fetch_roster", side_effect=requests.Timeout):
            result = market.discover([old], self.now)
        self.assertEqual(result[0]["items"], old["items"])
        self.assertEqual(result[0]["observed_at"], old["observed_at"])
        self.assertEqual(result[0]["status"], "stale")

    def test_search_ranks_preserve_original_positions_around_packages_and_duplicates(self):
        rows = market.parse_ranked_search({"success": 1, "results_html": '''
          <a class="search_result_row" data-ds-appid="10" href="https://store.steampowered.com/app/10/name/"></a>
          <a class="search_result_row" data-ds-appid="20,30" href="https://store.steampowered.com/sub/4/"></a>
          <a class="search_result_row" data-ds-appid="10" href="https://store.steampowered.com/app/10/name/"></a>
          <a class="search_result_row" data-ds-appid="40" href="https://store.steampowered.com/app/40/"></a>'''} )
        self.assertEqual(rows, [{"appid": 10, "rank": 1}, {"appid": 40, "rank": 4}])

    def test_healthy_daily_cache_makes_no_network_requests(self):
        old = {"generated_at": market.stamp(self.now - timedelta(hours=12)), "status": "fresh", "games": [{"appid": 1}]}
        with patch.object(market, "discover") as discover:
            result = market.build_indie_market(old, {}, self.now)
        discover.assert_not_called()
        self.assertEqual(result, old)
        self.assertIsNot(result, old)

    def test_partial_daily_cache_retries_instead_of_blocking_all_day(self):
        game = dict(self.meta(), appid=1, status="partial", players_status="unavailable",
                    review_windows={str(n): {"status": "unavailable"} for n in (1, 7, 30)})
        old = {"generated_at": market.stamp(self.now - timedelta(hours=1)), "status": "partial", "games": [game]}
        with patch.object(market, "discover", return_value=[]) as discover, patch.object(market, "fetch_metadata", return_value=({}, set(), [])), patch.object(market, "collect_game", return_value=game) as collect:
            market.build_indie_market(old, {}, self.now)
        discover.assert_called_once()
        collect.assert_called_once()


if __name__ == "__main__":
    unittest.main()
