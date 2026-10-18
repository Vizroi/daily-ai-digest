"""Prevent false market signals from discovery, sparse history and proxy data."""
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import market_analysis as analysis


class GlobalAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 18, 20, tzinfo=analysis.TZ)

    def game(self, appid, tags=None, players=100, age=200):
        return {
            "appid": appid, "name": f"Game {appid}", "tags": tags or ["Automation"],
            "release_date": (self.now.date() - timedelta(days=age)).isoformat(),
            "coming_soon": False, "is_demo": False, "current_players": players,
            "players_status": "fresh", "players_observed_at": self.now.isoformat(),
            "windows": {},
        }

    def window(self, game, previous=100, current=120, size=7):
        game["windows"][str(size)] = {
            "status": "ready" if previous else "no_baseline", "metric": "sampled_players_mean",
            "required_days": size, "current_days": size, "previous_days": size,
            "current": current, "previous": previous,
            **{key: (self.now.date() - timedelta(days=offset)).isoformat() for key, offset in {
                "current_start": size, "current_end": 1, "previous_start": size * 2, "previous_end": size + 1}.items()},
        }
        return game

    def review(self, game, total=10, scope="all_languages_all_purchase_types"):
        game["review_summary"] = {"status": "fresh", "sampled_at": self.now.isoformat(), "total": total,
                                  "positive": total, "negative": 0, "scope": scope}
        return game

    def analyze(self, games, **kwargs):
        return analysis.build_global_analysis({"generated_at": self.now.isoformat(), "games": games}, **kwargs)

    def group(self, result, group_id="automation"):
        return next(group for group in result["groups"] if group["id"] == group_id)

    def test_empty_and_cold_start_have_no_invented_trends(self):
        empty = self.analyze([])
        self.assertEqual(empty["groups"], [])
        games = [self.game(n, players=5000 * n) for n in range(1, 5)]
        result = self.analyze(games)
        self.assertEqual(result["rising"], {"1": [], "7": [], "30": []})
        window = self.group(result)["windows"]["7"]
        self.assertIsNone(window["current"])
        self.assertIsNone(window["percent_change"])
        self.assertIn("暂不判断", result["summary"][-1])

    def test_gameplay_groups_do_not_rank_generic_style_or_mode_tags(self):
        result = self.analyze([self.game(1, ["Indie", "Singleplayer", "Action", "Horror", "Pixel Graphics"]),
                               self.game(2, ["FPS", "Tactical Shooter", "Multiplayer"])])
        self.assertEqual({g["id"] for g in result["groups"]}, {"fps", "tactical_shooter"})
        self.assertEqual(result["coverage"]["classified_games"], 1)
        self.assertEqual(result["coverage"]["unclassified_games"], 1)

    def test_action_is_in_global_and_overlapping_tags_count_each_game_once_per_group(self):
        result = self.analyze([self.game(1, ["Action", "Roguelike", "Roguelite", "Action Roguelike", "Hack and Slash"])])
        self.assertEqual(self.group(result, "roguelike")["sample_count"], 1)
        self.assertEqual(self.group(result, "hack_slash")["game_ids"], [1])
        self.assertEqual(result["coverage"]["total_games"], 1)

    def test_moba_mmo_and_auto_battler_have_explicit_gameplay_groups(self):
        result = self.analyze([self.game(1, ["MOBA"]), self.game(2, ["MMORPG"]), self.game(3, ["Auto Battler"])])
        self.assertEqual({g["id"] for g in result["groups"]}, {"moba", "mmorpg", "auto_battler"})

    def test_jrpg_alone_does_not_imply_turn_based_combat(self):
        result = self.analyze([self.game(1, ["JRPG", "Action RPG"]), self.game(2, ["Turn-Based Combat", "RPG"]),
                               self.game(3, ["Turn-Based Combat", "Strategy"])])
        self.assertEqual(self.group(result, "turn_based_rpg")["game_ids"], [2])

    def test_duplicate_dlc_demo_software_unreleased_and_unknown_release_excluded(self):
        good = self.game(1)
        demo, dlc, software, upcoming, future, unknown = [self.game(i) for i in range(2, 8)]
        demo["is_demo"], dlc["type"], software["type"] = True, 1, "software"
        upcoming["coming_soon"] = True
        future["release_date"] = (self.now.date() + timedelta(days=1)).isoformat()
        unknown.pop("release_date")
        result = self.analyze([good, deepcopy(good), demo, dlc, software, upcoming, future, unknown])
        self.assertEqual(result["coverage"]["total_games"], 1)
        self.assertEqual(self.group(result)["game_ids"], [1])
        software["type"] = 6
        self.assertEqual(self.analyze([software])["coverage"]["total_games"], 0)

    def test_stale_missing_future_and_invalid_player_values_do_not_become_zero(self):
        games = [self.game(i) for i in range(1, 8)]
        games[0]["current_players"] = 0
        games[1]["players_status"] = "stale"
        games[2]["current_players"] = None
        games[3]["current_players"] = float("nan")
        games[4]["current_players"] = True
        games[5]["players_observed_at"] = (self.now + timedelta(minutes=1)).isoformat()
        games[6]["players_observed_at"] = (self.now - timedelta(hours=31)).isoformat()
        result = self.analyze(games)
        pop = self.group(result)["popularity"]
        self.assertEqual(pop["observed_count"], 1)
        self.assertEqual(pop["current_players"], 0)
        self.assertEqual(pop["status"], "partial")
        self.assertIsNone(pop["leader_share_percent"])
        self.assertEqual(result["coverage"]["fresh_games"], 1)

    def test_all_unknown_observations_stay_unknown(self):
        game = self.game(1, players=None)
        result = self.analyze([game])
        self.assertIsNone(self.group(result)["popularity"]["current_players"])
        self.assertEqual(result["popular"], [])

    def test_explicit_now_can_invalidate_old_snapshot(self):
        result = self.analyze([self.game(1)], now=self.now + timedelta(days=2))
        self.assertEqual(result["coverage"]["fresh_games"], 0)

    def test_verified_global_sellers_count_is_basis_not_current_online(self):
        games = [self.game(1, ["Automation"], 1), self.game(2, ["Automation"], 2), self.game(3, ["FPS"], 100000)]
        for rank, game in enumerate(games, start=1):
            game.update(top_sellers_rank=rank, top_sellers_status="fresh", top_sellers_observed_at=self.now.isoformat())
        result = self.analyze(games)
        self.assertEqual(result["popularity_basis"]["id"], "global_top_sellers")
        self.assertEqual(result["popular"][0]["id"], "automation")
        self.assertEqual(self.group(result)["popularity"]["top_seller_count"], 2)

    def test_unverified_rank_is_not_a_global_seller_observation(self):
        game = self.game(1)
        game["top_sellers_rank"] = 1
        result = self.analyze([game])
        self.assertEqual(result["popularity_basis"]["id"], "sample_current_players")
        game.update(top_sellers_status="fresh", top_sellers_observed_at=(self.now - timedelta(days=2)).isoformat())
        self.assertEqual(self.analyze([game])["popularity_basis"]["id"], "sample_current_players")

    def test_matched_cohort_ignores_huge_newly_discovered_current_value(self):
        games = [self.window(self.game(i), 100, 100) for i in range(1, 4)]
        games.append(self.game(4, players=1000000))
        result = self.analyze(games)
        trend = self.group(result)["windows"]["7"]
        self.assertEqual(trend["current"], 300)
        self.assertEqual(trend["previous"], 300)
        self.assertEqual(trend["valid_count"], 3)
        self.assertEqual(trend["percent_change"], 0)
        self.assertEqual(result["rising"]["7"], [])

    def test_history_requires_three_games_and_sixty_percent_coverage(self):
        for complete, total in ((2, 2), (3, 6), (3, 7)):
            games = [self.window(self.game(i), 100, 200) if i <= complete else self.game(i) for i in range(1, total + 1)]
            result = self.analyze(games)
            trend = self.group(result)["windows"]["7"]
            self.assertEqual(trend["status"], "insufficient_history")
            self.assertIsNone(trend["percent_change"])

    def test_stale_or_incomplete_window_is_not_accepted(self):
        for corrupt in ("wrong_end", "missing_day", "wrong_metric", "missing_time"):
            games = [self.window(self.game(i)) for i in range(1, 4)]
            window = games[0]["windows"]["7"]
            if corrupt == "wrong_end":
                window["current_end"] = "2026-10-16"
            elif corrupt == "missing_day":
                window["previous_days"] = 6
            elif corrupt == "wrong_metric":
                window["metric"] = "lifetime_reviews"
            else:
                window.pop("previous_start")
            self.assertEqual(self.group(self.analyze(games))["windows"]["7"]["valid_count"], 2, corrupt)

    def test_broad_growth_has_evidence_and_is_ranked(self):
        games = [self.window(self.game(i), 100, 120) for i in range(1, 5)]
        result = self.analyze(games)
        trend = self.group(result)["windows"]["7"]
        self.assertEqual(trend["signal"], "broad_growth")
        self.assertEqual(trend["percent_change"], 20)
        self.assertEqual(trend["up_count"], 4)
        self.assertEqual(trend["positive_leader_share_percent"], 25)
        self.assertEqual(trend["without_leader_percent_change"], 20)
        self.assertEqual([g["id"] for g in result["rising"]["7"]], ["automation"])

    def test_single_breakout_does_not_make_a_rising_category(self):
        games = [self.window(self.game(1), 100, 10000), self.window(self.game(2), 100, 110),
                 self.window(self.game(3), 100, 110), self.window(self.game(4), 100, 100)]
        result = self.analyze(games)
        self.assertEqual(self.group(result)["windows"]["7"]["signal"], "concentrated")
        self.assertEqual(result["rising"]["7"], [])

    def test_majority_decline_is_not_hidden_by_few_winners(self):
        games = [self.window(self.game(i), 100, 200 if i <= 2 else 99) for i in range(1, 7)]
        result = self.analyze(games)
        self.assertEqual(self.group(result)["windows"]["7"]["signal"], "mixed")
        self.assertEqual(result["rising"]["7"], [])

    def test_low_and_zero_baselines_do_not_generate_growth_rankings(self):
        for previous, signal in ((1, "low_base"), (0, "no_baseline")):
            games = [self.window(self.game(i), previous, 1000) for i in range(1, 4)]
            result = self.analyze(games)
            trend = self.group(result)["windows"]["7"]
            self.assertEqual(trend["signal"], signal)
            self.assertEqual(trend["absolute_change"], 3000 - 3 * previous)
            self.assertEqual(result["rising"]["7"], [])
            if not previous:
                self.assertIsNone(trend["percent_change"])

    def test_new_releases_are_age_bucketed_and_never_have_a_cross_age_median(self):
        games = [self.review(self.game(i, age=age), reviews) for i, age, reviews in (
            (1, 1, 2), (2, 5, 4), (3, 7, 6), (4, 25, 200), (5, 80, 10000), (6, 91, 50000))]
        new = self.group(self.analyze(games))["new_releases"]
        self.assertEqual(new["sample_count"], 5)
        self.assertEqual([b["count"] for b in new["age_buckets"]], [3, 1, 1])
        self.assertEqual(new["age_buckets"][0]["median_reviews"], 4)
        self.assertIsNone(new["age_buckets"][1]["median_reviews"])
        self.assertIsNone(new["median_reviews"])
        self.assertIn("不是发售首", new["metric_note"])

    def test_mixed_scope_stale_and_inconsistent_reviews_cannot_create_median(self):
        for corrupt in ("scope", "stale", "inconsistent"):
            games = [self.review(self.game(i, age=3), 20) for i in range(1, 4)]
            review = games[-1]["review_summary"]
            if corrupt == "scope":
                review["scope"] = "english_only"
            elif corrupt == "stale":
                review["status"] = "stale"
            else:
                review["positive"] = 10
            bucket = self.group(self.analyze(games))["new_releases"]["age_buckets"][0]
            self.assertIsNone(bucket["median_reviews"], corrupt)

    def test_initial_release_prevents_one_point_zero_from_becoming_a_new_game(self):
        game = self.game(1, age=2)
        game["first_release_date"] = (self.now.date() - timedelta(days=400)).isoformat()
        self.assertEqual(self.group(self.analyze([game]))["new_releases"]["sample_count"], 0)

    def test_early_access_transition_without_first_date_is_not_a_new_game(self):
        game = self.review(self.game(1, age=3), 100000)
        game.update(early_access_transition=True, first_release_date=None,
                    release_date_status="first_release_unverified", release_date_basis="steam_release_date")
        known = [self.review(self.game(i, age=3), 2 * i) for i in range(2, 5)]
        result = self.analyze([game] + known)
        group = self.group(result)
        self.assertIn(1, group["game_ids"])
        self.assertEqual(group["popularity"]["observed_count"], 4)
        self.assertEqual(group["new_releases"]["sample_count"], 3)
        self.assertNotIn(1, group["new_releases"]["game_ids"])
        self.assertEqual(group["new_releases"]["age_buckets"][0]["median_reviews"], 6)
        self.assertEqual(result["coverage"]["recent_games"], 3)
        self.assertEqual(result["coverage"]["unverified_release_games"], 1)

    def test_low_attention_games_remain_in_tag_details(self):
        games = [self.game(1, players=50000), self.game(2, players=1), self.game(3, players=0), self.game(4, players=None)]
        group = self.group(self.analyze(games))
        self.assertEqual(set(group["game_ids"]), {1, 2, 3, 4})
        self.assertEqual(group["ordinary_ids"][:2], [3, 2])

    def test_commercial_model_uses_explicit_metadata_never_a_missing_price(self):
        games = [self.game(i) for i in range(1, 5)]
        games[0]["is_free"] = True
        games[1]["is_free"] = False
        games[2]["price"] = {"final": 0}
        games[3]["price"] = {"final": None}
        self.assertEqual(self.group(self.analyze(games))["commercial_models"], {"free": 1, "paid": 1, "unknown": 2})

    def test_results_are_json_safe_without_mutating_source(self):
        games = [self.window(self.review(self.game(i), 30)) for i in range(1, 4)]
        before = deepcopy(games)
        result = self.analyze(games)
        json.dumps(result, allow_nan=False)
        self.assertEqual(games, before)


if __name__ == "__main__":
    unittest.main()
