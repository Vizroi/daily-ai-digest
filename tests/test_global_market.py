"""Global discovery provenance, eligibility, stable cohorts and partial failures."""
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import global_market as market


class GlobalMarketTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 18, 12, tzinfo=market.TZ)

    def meta(self, appid=1):
        return {"name": f"Game {appid}", "release_date": "2026-10-01", "app_type": "game",
                "coming_soon": False, "is_demo": False, "tags": ["Action"], "genres": ["Action"],
                "metadata_at": market.stamp(self.now), "metadata_status": "fresh"}

    def roster(self, ids, status="fresh", source="recent_releases"):
        definition = next(s for s in market.SOURCES if s["id"] == source)
        return dict(definition, items=[{"appid": appid, "rank": rank} for rank, appid in enumerate(ids, 1)],
                    status=status, observed_at=market.stamp(self.now), scope_verified=True, discovered_count=len(ids))

    def chart(self, country=""):
        data = {"loaderData": [json.dumps({"strCountryCode": country})], "renderContext": {"queryData": json.dumps({"queries": [
            {"queryKey": ["StoreQuery", {"sort": 11, "start": 0, "count": 100}, None],
             "state": {"status": "success", "data": {"rgItemIDs": [{"appid": n} for n in range(1, 101)]}}}
        ]})}}
        return '<script id="valve-ssr-data" type="application/json">' + json.dumps(data) + '</script>'

    def test_global_rank_requires_explicit_global_context(self):
        rows = market.parse_global_chart(self.chart())
        self.assertEqual(rows[19], {"appid": 20, "rank": 20})
        with self.assertRaises(ValueError):
            market.parse_global_chart(self.chart("US"))
        with self.assertRaises(ValueError):
            market.parse_global_chart("<html>no chart</html>")

    def test_release_search_accepts_zero_review_apps_not_packages(self):
        data = {"success": 1, "results_html": '''
          <a class="search_result_row" data-ds-appid="10" href="https://store.steampowered.com/app/10/name/"></a>
          <a class="search_result_row" data-ds-appid="20,30" href="https://store.steampowered.com/sub/4/"></a>
          <a class="other" data-ds-appid="40" href="https://store.steampowered.com/app/40/"></a>'''}
        self.assertEqual(market.parse_search(data), [{"appid": 10}])

    def test_metadata_excludes_non_games_and_keeps_original_release(self):
        for kind in (1, 2, 3, 6):
            with self.assertRaises(ValueError):
                market.normalize_metadata({"success": 1, "type": kind, "name": "other"}, {}, self.now)
        item = {"success": 1, "type": 0, "name": "Example", "release": {
            "steam_release_date": int(self.now.timestamp()),
            "release_from_early_access_date": int(self.now.timestamp()),
            "original_steam_release_date": int((self.now - timedelta(days=100)).timestamp())}}
        result = market.normalize_metadata(item, {}, self.now)
        self.assertEqual(result["release_date"], (self.now.date() - timedelta(days=100)).isoformat())
        self.assertEqual(result["release_1_0_date"], self.now.date().isoformat())
        self.assertFalse(result["coming_soon"])

    def test_early_access_transition_without_original_date_is_unverified(self):
        result = market.normalize_metadata({"success": 1, "type": 0, "name": "EA game", "release": {
            "steam_release_date": int(self.now.timestamp()), "release_from_early_access_date": int(self.now.timestamp())}}, {}, self.now)
        self.assertTrue(result["early_access_transition"])
        self.assertEqual(result["release_date_status"], "first_release_unverified")
        self.assertIsNone(result["first_release_date"])
        self.assertEqual(result["release_date_basis"], "steam_release_date")

    def test_later_full_launch_preserves_previous_observed_early_access_date(self):
        old = {"release_date": "2024-01-24", "metadata_at": "2026-01-01T12:00:00+08:00", "coming_soon": False}
        meta = {"release_date": "2026-10-15", "release_1_0_date": "2026-10-15", "release_date_status": "first_release_unverified"}
        result = market.preserve_earlier_release(meta, old)
        self.assertEqual(result["release_date"], "2024-01-24")
        self.assertEqual(result["release_1_0_date"], "2026-10-15")
        self.assertEqual(result["release_date_basis"], "earliest_observed_store_date")

    def test_reviews_explicit_all_scope_and_no_reviews_not_zero_positive_rate(self):
        with patch.object(market, "request_json", return_value={"success": 1, "query_summary": {
            "total_reviews": 0, "total_positive": 0, "total_negative": 0}}) as request:
            summary = market.fetch_review_summary(1, self.now)
        self.assertIsNone(summary["positive_percent"])
        self.assertEqual(summary["scope"], "all_languages_all_purchase_types")
        self.assertEqual(request.call_args.args[1]["language"], "all")
        self.assertEqual(request.call_args.args[1]["purchase_type"], "all")
        with patch.object(market, "request_json", return_value={"success": 1, "query_summary": {
            "total_reviews": 3, "total_positive": 2, "total_negative": 2}}):
            with self.assertRaises(ValueError):
                market.fetch_review_summary(1, self.now)

    def test_failed_player_snapshot_preserves_value_and_does_not_add_history(self):
        old = dict(self.meta(), appid=1, first_seen="2026-10-17T12:00:00+08:00", current_players=12,
                   players_observed_at="2026-10-17T12:00:00+08:00", review_summary={"status": "fresh", "sampled_at": market.stamp(self.now)})
        with patch.object(market, "request_json", side_effect=requests.Timeout):
            game, success = market.collect_game({"appid": 1, "discovery_sources": []}, old, self.meta(), self.now)
        history = {"apps": {}}
        market.record_sample(history, game, self.now, success)
        self.assertFalse(success)
        self.assertEqual(game["current_players"], 12)
        self.assertEqual(game["players_status"], "stale")
        self.assertEqual(history["apps"]["1"]["days"], {})

    def test_chart_failure_preserves_old_rank_as_stale_and_drop_clears_rank(self):
        old = {"appid": 1, "top_sellers_rank": 6, "top_sellers_observed_at": "2026-10-17T12:00:00+08:00"}
        failed = market.seed_from_game(old, [self.roster([], "unavailable", "global_top_sellers")])
        self.assertEqual(failed["top_sellers_rank"], 6)
        self.assertEqual(failed["top_sellers_status"], "stale")
        dropped = market.seed_from_game(old, [self.roster([2], "fresh", "global_top_sellers")])
        self.assertNotIn("top_sellers_rank", dropped)

    def test_daily_discovery_failure_does_not_replace_roster_with_empty(self):
        old = self.roster([1, 2])
        with patch.object(market, "fetch_roster", side_effect=requests.Timeout):
            result = market.discover([old], self.now, refresh=True)
        self.assertEqual(result[0]["status"], "stale")
        self.assertEqual([r["appid"] for r in result[0]["items"]], [1, 2])
        self.assertEqual(result[1]["status"], "unavailable")

    def fake_collect(self, seed, old, meta, now, refresh, deadline=None):
        return dict(old or {}, **(meta or self.meta(seed["appid"])), appid=seed["appid"],
                    first_seen=old.get("first_seen", market.stamp(now)), last_discovered_at=seed.get("last_discovered_at"),
                    discovery_sources=seed["discovery_sources"], current_players=0, players_status="fresh", status="fresh",
                    review_summary={"status": "fresh"}), True

    def test_stable_cohort_daily_admission_cap_and_excluded_candidates(self):
        old = dict(self.meta(), appid=1, first_seen=market.stamp(self.now - timedelta(days=50)),
                   last_discovered_at=market.stamp(self.now - timedelta(days=49)))
        previous = {"games": [old], "discovery": {"admission": {"date": self.now.date().isoformat(), "count": 6}}}
        metadata = {appid: self.meta(appid) for appid in range(2, 15)}
        metadata[2]["coming_soon"] = True
        metadata[3]["is_demo"] = True
        metadata[4]["app_type"] = "software"
        with patch.object(market, "discover", return_value=[self.roster(list(range(2, 15)))]), \
             patch.object(market, "fetch_metadata", return_value=(metadata, set(), [])), \
             patch.object(market, "collect_game", side_effect=self.fake_collect):
            result, history = market.build_global_market(previous, {"apps": {}}, self.now)
        self.assertEqual({g["appid"] for g in result["games"]}, {1, 5, 6})
        self.assertEqual(result["discovery"]["admission"]["count"], 8)
        self.assertEqual(result["coverage"]["excluded_or_unavailable_candidates"], 3)
        self.assertEqual(result["coverage"]["deferred_candidates"], 8)
        self.assertTrue(all(g["windows"]["7"]["status"] in ("insufficient_history", "missing_data") for g in result["games"]))

    def test_exhausted_budget_keeps_cohort_values_without_network_or_history(self):
        old = dict(self.meta(), appid=1, first_seen=market.stamp(self.now - timedelta(days=30)),
                   current_players=80, players_observed_at="2026-10-17T12:00:00+08:00",
                   players_attempted_at="2026-10-17T12:00:00+08:00",
                   review_summary={"status": "fresh", "total": 20, "sampled_at": "2026-10-17T12:00:00+08:00"})
        with patch.object(market, "request_json") as request, patch.object(market, "fetch_review_summary") as reviews:
            game, success = market.collect_game({"appid": 1, "discovery_sources": []}, old, self.meta(), self.now, deadline=0)
        request.assert_not_called()
        reviews.assert_not_called()
        self.assertFalse(success)
        self.assertEqual(game["current_players"], 80)
        self.assertEqual(game["players_status"], "stale")
        self.assertEqual(game["collection_status"], "deferred_budget")
        self.assertEqual(game["players_attempted_at"], old["players_attempted_at"])
        self.assertEqual(game["review_summary"]["total"], 20)
        self.assertEqual(game["review_summary"]["status"], "stale")
        history = {"apps": {}}
        market.record_sample(history, game, self.now, success)
        self.assertFalse(history["apps"]["1"]["days"])


if __name__ == "__main__":
    unittest.main()
