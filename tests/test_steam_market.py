"""Coverage, temporal alignment, data provenance and graceful Steam failures."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import steam_market as market


class MarketTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 18, 10, tzinfo=market.TZ)

    def days(self, count, value=100):
        rows = {}
        for offset in range(1, count + 1):
            dt = (self.now - timedelta(days=offset)).replace(hour=1, minute=0)
            rows[dt.date().isoformat()] = {"samples": [[int(dt.timestamp()), value], [int((dt + timedelta(hours=12)).timestamp()), value]]}
        return rows

    def test_cold_start_never_fakes_change(self):
        result = market.compare_window({}, self.now, 30, market.stamp(self.now))
        self.assertEqual(result["status"], "insufficient_history")
        self.assertIsNone(result["percent_change"])
        self.assertIsNone(result["current"])

    def test_complete_days_exclude_today_and_weight_days_equally(self):
        days = self.days(14)
        for offset in range(1, 8):
            key = (self.now.date() - timedelta(days=offset)).isoformat()
            for sample in days[key]["samples"]:
                sample[1] = 200
        days[self.now.date().isoformat()] = {"samples": [[int(self.now.timestamp()), 999999]]}
        result = market.compare_window(days, self.now, 7)
        self.assertEqual((result["current"], result["previous"], result["absolute_change"], result["percent_change"]), (200, 100, 100, 100))
        self.assertEqual(result["status"], "ready")

    def test_missing_day_is_not_zero(self):
        days = self.days(14)
        del days[(self.now.date() - timedelta(days=5)).isoformat()]
        result = market.compare_window(days, self.now, 7, "2026-08-01T00:00:00+08:00")
        self.assertEqual(result["status"], "missing_data")
        self.assertEqual(result["current_days"], 6)
        self.assertIsNone(result["current"])

    def test_one_sample_or_short_span_does_not_qualify_day(self):
        for scenario in ("one", "short", "duplicate"):
            days = self.days(2)
            key = (self.now.date() - timedelta(days=1)).isoformat()
            samples = days[key]["samples"]
            if scenario == "one":
                samples.pop()
            elif scenario == "short":
                samples[1][0] = samples[0][0] + 5 * 3600
            else:
                samples[1][0] = samples[0][0] + 10
            result = market.compare_window(days, self.now, 1)
            self.assertNotEqual(result["status"], "ready", scenario)
            self.assertEqual(result["current_days"], 0)

    def test_low_base_and_zero_baseline_are_explicit(self):
        low = market.compare_window(self.days(2, 5), self.now, 1)
        self.assertTrue(low["low_base"])
        zero = market.compare_window(self.days(2, 0), self.now, 1)
        self.assertEqual(zero["status"], "no_baseline")
        self.assertIsNone(zero["percent_change"])
        self.assertEqual(zero["previous"], 0)

    def test_full_month_comparison_needs_sixty_days(self):
        self.assertNotEqual(market.compare_window(self.days(59), self.now, 30)["status"], "ready")
        self.assertEqual(market.compare_window(self.days(60), self.now, 30)["status"], "ready")

    def test_utc_input_uses_shanghai_calendar_dates(self):
        utc = self.now.astimezone(timezone.utc)
        self.assertEqual(market.compare_window(self.days(2), utc, 1), market.compare_window(self.days(2), self.now, 1))
        history = {}
        late_utc = datetime(2026, 10, 17, 18, tzinfo=timezone.utc)
        market.record_sample(history, {"appid": 1, "first_seen": market.stamp(late_utc), "current_players": 1}, late_utc, True)
        self.assertIn("2026-10-18", history["apps"]["1"]["days"])

    def test_bad_timestamps_and_wrong_day_samples_are_ignored(self):
        days = self.days(2)
        key = (self.now.date() - timedelta(days=1)).isoformat()
        days[key]["samples"].extend([["invalid", 10], [10**30, 20], [int(self.now.timestamp()), 50000], [0, float("nan")]])
        result = market.compare_window(days, self.now, 1)
        self.assertEqual(result["current"], 100)

    def test_upcoming_game_not_trended(self):
        result = market.compare_window(self.days(60), self.now, 30, coming_soon=True)
        self.assertEqual(result["status"], "not_released")

    def test_failed_players_keep_old_timestamp_and_never_append_sample(self):
        old = {"appid": 1, "name": "Game", "first_seen": "2026-10-01T00:00:00+08:00", "observed_at": "2026-10-17T13:00:00+08:00", "current_players": 123,
               "metadata_at": market.stamp(self.now), "review_summary": {"sampled_at": market.stamp(self.now)}, "events_at": market.stamp(self.now)}
        with patch.object(market, "request_json", side_effect=requests.Timeout()):
            game, success = market.collect_game({"appid": 1}, old, {}, self.now)
        self.assertFalse(success)
        self.assertEqual(game["observed_at"], old["observed_at"])
        self.assertEqual(game["current_players"], 123)
        self.assertEqual(game["players_status"], "stale")
        self.assertEqual(game["status"], "stale")
        history = {"apps": {}}
        market.record_sample(history, game, self.now, success)
        self.assertEqual(history["apps"]["1"]["days"], {})
        self.assertNotIn("players_status", old)

    def test_retries_same_hour_do_not_create_extra_coverage(self):
        game = {"appid": 1, "current_players": 50, "first_seen": market.stamp(self.now)}
        history = {}
        market.record_sample(history, game, self.now, True)
        game["current_players"] = 55
        market.record_sample(history, game, self.now + timedelta(minutes=1), True)
        samples = history["apps"]["1"]["days"][self.now.date().isoformat()]["samples"]
        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0][1], 55)

    def test_review_sampling_does_not_change_total_or_invent_analysis(self):
        review = {"recommendationid": "123", "author": {"steamid": "76561198000000000"}, "language": "english", "review": "Combat feels responsive and the readable moves are enjoyable throughout each match.",
                  "timestamp_created": int((self.now - timedelta(days=1)).timestamp()), "voted_up": True}
        payload = {"query_summary": {"total_reviews": 1000, "total_positive": 900, "total_negative": 100}, "reviews": [review]}
        with patch.object(market, "service", return_value=payload) as call:
            summary, reviews = market.fetch_reviews(10, self.now)
        self.assertEqual(summary["total"], 1000)
        self.assertEqual(summary["sample_size"], 1)
        self.assertEqual(summary["positive_percent"], 90)
        self.assertNotIn("steamid", reviews[0])
        self.assertEqual(call.call_args.args[1]["languages"], ["english", "schinese"])
        self.assertEqual(call.call_args.args[1]["filter"], 1)

    def test_short_jokes_are_excluded_and_real_excerpts_mark_truncation(self):
        base = {"recommendationid": "123", "author": {"steamid": "76561198000000000"}, "language": "english", "timestamp_created": int(self.now.timestamp()) - 1, "voted_up": True}
        rows = [dict(base, review="wouldn't let me kill da dog"), dict(base, recommendationid="456", review="Combat mechanics provide readable movement and varied enemy attacks. " * 5)]
        payload = {"query_summary": {"total_reviews": 1000, "total_positive": 900}, "reviews": rows}
        with patch.object(market, "service", return_value=payload):
            _, reviews = market.fetch_reviews(1, self.now)
        self.assertEqual(len(reviews), 1)
        self.assertTrue(reviews[0]["excerpt_truncated"])
        self.assertTrue(reviews[0]["text"].endswith("…"))
        self.assertLessEqual(len(reviews[0]["text"].split()), 24)

    def test_announcements_filter_media_other_apps_and_future(self):
        good = {"appid": 1, "date": int(self.now.timestamp()) - 3600, "feedname": "steam_community_announcements", "title": "Update 1.0", "gid": "123"}
        rows = [good, dict(good, feedname="PC Gamer"), dict(good, appid=2), dict(good, date=int(self.now.timestamp()) + 3600)]
        with patch.object(market, "request_json", return_value={"appnews": {"appid": 1, "newsitems": rows}}):
            events = market.fetch_events(1, self.now)
        self.assertEqual(len(events), 1)
        self.assertIn("/news/app/1/view/123", events[0]["url"])
        self.assertIn("尚未验证", events[0]["note"])


if __name__ == "__main__":
    unittest.main()
