"""Market output contract: honest histories, source links and safe HTML."""
import copy
import os
import sys
import unittest
from html.parser import HTMLParser

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import market_render


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.ids = []
        self.anchors = []
        self.game_articles = []
        self.trend_panels = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.ids.append(attrs["id"])
        if tag == "a" and attrs.get("href", "").startswith("#"):
            self.anchors.append(attrs["href"][1:])
        if tag == "article" and "data-game" in attrs:
            self.game_articles.append(attrs)
        if "data-trend" in attrs:
            self.trend_panels.append(attrs)


def fixture():
    return {
        "generated_at": "2026-10-18T06:00:00Z",
        "coverage": {"history_start": "2026-10-18", "history_days": 1},
        "games": [{
            "appid": 100, "name": "Arena <One>", "is_action": True,
            "store_url": "https://store.steampowered.com/app/100/",
            "genres": ["Action", "Indie"], "player_modes": ["Online PvP"],
            "tags": ["Combat"], "status": "fresh", "current_players": 0,
            "observed_at": "2026-10-18T06:00:00Z", "release_date": "2026-10-01",
            "price": {"formatted": "¥ 38.00"},
            "review_summary": {"total": 102, "positive_percent": 89.2},
            "events": [{"title": "Combat update", "date": "2026-10-17", "url": "https://store.steampowered.com/news/app/100/view/1"}],
            "reviews": [{"language": "english", "text": "Readable attacks.", "voted_up": True, "url": "https://steamcommunity.com/id/test/recommended/100/"}],
            "windows": {str(days): {"status": "insufficient_history", "reason": "等待完整记录"} for days in (1, 7, 30)},
        }],
    }


class MarketRenderTests(unittest.TestCase):
    def test_summary_explains_cold_start_without_inventing_growth(self):
        data = fixture()
        summary = market_render._market_summary(data, data["games"])
        self.assertIn("包含 1 款动作游戏、0 款其他类型", summary)
        self.assertIn("取得 1/1 款的本轮在线快照", summary)
        self.assertIn("记录覆盖 1 个自然日", summary)
        self.assertIn("暂不能判断上涨或下降", summary)
        self.assertNotIn("%", summary)
        self.assertIn("Arena &lt;One&gt;", summary)

    def test_summary_excludes_stale_and_invalid_current_players(self):
        for value, status in ((999999, "stale"), (None, "fresh"), (True, "fresh"),
                              (float("nan"), "fresh"), (float("inf"), "fresh"), (-1, "fresh")):
            with self.subTest(value=value, status=status):
                data = fixture()
                other = copy.deepcopy(data["games"][0])
                other.update(appid=101, name="Excluded", current_players=value, players_status=status)
                data["games"].append(other)
                summary = market_render._market_summary(data, data["games"])
                self.assertIn("取得 1/2 款", summary)
                self.assertNotIn("Excluded", summary)

    def test_summary_ranks_daily_absolute_changes_and_dates_complete_days(self):
        data = fixture()
        base = data["games"][0]
        base["windows"]["1"] = {"status": "ready", "previous": 100, "current": 70,
                                  "absolute_change": -30, "percent_change": -30}
        small = copy.deepcopy(base)
        small.update(appid=101, name="Tiny growth")
        small["windows"]["1"] = {"status": "ready", "previous": 1, "current": 3,
                                  "absolute_change": 2, "percent_change": 200, "low_base": True}
        data["games"].append(small)
        summary = market_render._market_summary(data, data["games"])
        self.assertIn("10.17 较 10.16", summary)
        self.assertIn("2 款可比样本中 1 款上涨、1 款下降、0 款持平", summary)
        self.assertIn("100.0 → 70.0 人（-30.0 人，-30.0%）", summary)
        self.assertNotIn("+200.0%", summary)
        self.assertNotIn("暂不能判断", summary)

    def test_summary_handles_zero_base_failed_collection_and_no_games(self):
        data = fixture()
        game = data["games"][0]
        game.update(players_status="stale", current_players=99999)
        game["windows"]["1"] = {"status": "no_baseline", "previous": 0, "current": 100,
                                 "absolute_change": 100, "percent_change": None}
        summary = market_render._market_summary(data, data["games"])
        self.assertIn("本轮在线采集未成功", summary)
        self.assertNotIn("当前在线最高", summary)
        self.assertIn("基数为零，不计算百分比", summary)
        self.assertNotIn("%", summary)
        self.assertIn("暂无在线人数与涨跌摘要", market_render._market_summary({}, []))

    def test_cold_start_keeps_current_snapshot_and_real_sources(self):
        page = market_render.render_market(fixture())
        self.assertIn("历史积累中", page)
        self.assertIn("等待完整记录", page)
        self.assertIn("89.2%", page)
        self.assertIn("¥ 38.00", page)
        self.assertIn("Combat update", page)
        self.assertIn("Readable attacks.", page)
        self.assertIn("0<small>人</small>", page)
        self.assertNotIn("+0.0%", page)
        self.assertIn("不代表全部玩家", page)

    def test_available_delta_exposes_base_absolute_and_percent(self):
        data = fixture()
        data["games"][0]["windows"]["7"] = {
            "status": "ready", "previous": 10, "current": 25,
            "absolute_change": 15, "percent_change": 150,
            "previous_days": 7, "current_days": 7, "low_base": True,
        }
        page = market_render.render_market(data)
        self.assertIn("10.0 → 25.0", page)
        self.assertIn("+15.0", page)
        self.assertIn("+150.0%", page)
        self.assertIn("低基数，优先看绝对变化", page)
        self.assertIn("有记录日 7 / 7", page)

    def test_ready_label_without_values_does_not_fake_a_trend(self):
        data = fixture()
        data["games"][0]["windows"]["7"] = {"status": "ready"}
        page = market_render.render_market(data)
        self.assertIn("0 / 1 款具备完整可比记录", page)
        self.assertNotIn("比例不可比", page)

    def test_default_seven_day_view_and_valid_anchor_targets(self):
        page = Page(market_render.render_market(fixture()))
        self.assertEqual(len(page.ids), len(set(page.ids)))
        self.assertTrue(all(anchor in page.ids for anchor in page.anchors))
        self.assertEqual(len(page.game_articles), 1)
        for panel in page.trend_panels:
            self.assertEqual("hidden" in panel, panel["data-trend"] != "7")

    def test_untrusted_source_text_and_urls_are_not_executable(self):
        data = fixture()
        game = data["games"][0]
        game.update(name='<script>alert("name")</script>', store_url="javascript:alert(1)", genres=['Action" onmouseover="alert(1)'])
        game["events"][0].update(title="<img src=x onerror=alert(1)>", url="javascript:alert(1)")
        game["reviews"][0].update(text="</p><script>alert(1)</script>", url="https://example.com/review")
        data["sources"] = [{"name": "<b>Source</b>", "url": "data:text/html,evil"}]
        page = market_render.render_market(data)
        self.assertNotIn('href="javascript:', page)
        self.assertNotIn('href="data:', page)
        self.assertNotIn('<img src=x', page)
        self.assertNotIn('<script>alert', page)
        self.assertIn('&lt;script&gt;', page)
        self.assertIn('Action&quot; onmouseover=&quot;', page)

    def test_missing_and_stale_metrics_are_distinct_from_zero(self):
        data = fixture()
        data["games"][0].update(current_players=None, status="stale")
        data["games"][0]["review_summary"] = {}
        page = market_render.render_market(data)
        self.assertIn("沿用历史快照", page)
        self.assertIn("—<small>人</small>", page)
        self.assertIn("0 款有本轮在线值", page)
        self.assertIn("在线合计 —", page)

    def test_new_release_does_not_include_upcoming_or_old_games(self):
        data = fixture()
        game = data["games"][0]
        self.assertIn('data-new="true"', market_render.render_market(data))
        game["coming_soon"] = True
        self.assertIn('data-new="false"', market_render.render_market(data))
        game["coming_soon"] = False
        game["release_date"] = "2024-01-01"
        self.assertIn('data-new="false"', market_render.render_market(data))

    def test_duplicate_invalid_ids_cannot_break_permalinks(self):
        data = fixture()
        data["games"].append(copy.deepcopy(data["games"][0]))
        data["games"].append({"appid": '" onclick="evil', "name": "Bad ID"})
        page = Page(market_render.render_market(data))
        self.assertEqual(len(page.game_articles), 1)
        self.assertEqual(len(page.ids), len(set(page.ids)))

    def test_empty_data_still_has_methodology_and_discovery(self):
        page = market_render.render_market({})
        self.assertIn("正在建立第一批市场记录", page)
        self.assertIn("Steam 最新发行", page)
        self.assertIn("Steam Demo", page)
        self.assertIn('<details class="methodology" id="methodology">', page)
        self.assertNotIn("1970", page)

    def test_daily_brief_has_its_own_timestamp_and_max_three_entries(self):
        data = fixture()
        brief = market_render.render_market_brief(data, "../market.html")
        self.assertIn("2026.10.18 14:00", brief)
        self.assertIn('href="../market.html#game-100"', brief)
        self.assertIn("7 天对比等待完整历史", brief)
        self.assertEqual(brief.count('<article class="sm-brief-item">'), 3)

    def test_brief_rejects_unsafe_href_and_omits_old_events(self):
        data = fixture()
        data["games"][0]["events"][0]["date"] = "2020-01-01"
        brief = market_render.render_market_brief(data, 'javascript:alert(1)')
        self.assertNotIn("javascript:", brief)
        self.assertNotIn("Combat update", brief)
        self.assertEqual(market_render.render_market_brief({}), "")

    def test_segment_changes_use_the_same_comparable_cohort(self):
        data = fixture()
        base = data["games"][0]
        base["windows"]["7"] = {"status": "ready", "previous": 10, "current": 25, "absolute_change": 15}
        missing = copy.deepcopy(base)
        missing.update(appid=101, name="Missing baseline", current_players=100000)
        missing["windows"]["7"] = {"status": "insufficient_history"}
        data["games"].append(missing)
        segments = market_render._segments(data["games"])
        self.assertIn("可比均值合计<br>10.0 → 25.0", segments)
        self.assertIn("可比覆盖 1 / 2 款", segments)
        self.assertIn("上涨 1 · 下降 0 · 持平 0", segments)
        self.assertNotIn("100,025", segments)

    def test_online_freshness_is_not_inferred_from_reviews(self):
        data = fixture()
        game = data["games"][0]
        game.update(status="partial", players_status="stale", current_players=500)
        game["review_summary"]["status"] = "fresh"
        page = market_render.render_market(data)
        self.assertIn("最近已知在线", page)
        self.assertIn("在线沿用历史快照", page)
        self.assertIn("0 款有本轮在线值", page)

    def test_old_discovery_is_not_presented_as_a_new_release(self):
        data = fixture()
        data["discovery"] = {"items": [{"appid": 200, "name": "Old chart game", "release_date": "2013-01-01", "url": "https://store.steampowered.com/app/200/"}]}
        section = market_render._discovery(data, data["games"], market_render._day("2026-10-18"))
        self.assertIn("其他公开发现线索", section)
        self.assertIn("尚未判定为新作或 Demo", section)
        self.assertNotIn("Old chart game", section.split('class="other-discovery"')[0])

    def test_independent_stale_fields_and_failed_collection_are_labelled(self):
        data = fixture()
        game = data["games"][0]
        game.update(status="stale", players_status="stale", observed_at="2026-10-17T01:00:00Z",
                    metadata_status="stale", metadata_at="2026-10-16T01:00:00Z",
                    events_status="stale", events_at="2026-10-16T01:00:00Z")
        data["discovery"] = {"status": "stale", "updated_at": "2026-10-16T01:00:00Z", "items": []}
        page = market_render.render_market(data)
        self.assertIn("商店资料沿用旧值", page)
        self.assertIn("公告沿用旧记录", page)
        self.assertIn("发现列表沿用旧记录", page)
        brief = market_render.render_market_brief(data)
        self.assertIn("本轮在线取得 0 / 1 款", brief)
        self.assertIn("最近成功在线采样", brief)
        self.assertIn("2026.10.17 09:00", brief)

    def test_zero_baseline_preserves_absolute_change_without_percentage(self):
        data = fixture()
        data["games"][0]["windows"]["7"] = {
            "status": "no_baseline", "previous": 0, "current": 100,
            "absolute_change": 100, "percent_change": None, "current_days": 7, "previous_days": 7,
        }
        panel = market_render._trend(data["games"][0], 7)
        self.assertIn("0.0 → 100.0", panel)
        self.assertIn("+100.0", panel)
        self.assertIn("比例不可比", panel)
        self.assertNotIn("历史积累中", panel)
        self.assertNotIn("%", panel)
        self.assertIn("可比覆盖 1 / 1 款", market_render._segments(data["games"]))

    def test_price_region_and_review_language_scope_are_explicit(self):
        data = fixture()
        data["games"][0]["price"] = {"formatted": "$9.99", "region": "US"}
        page = market_render.render_market(data)
        self.assertIn("$9.99 · 美区", page)
        self.assertIn("中英文评价推荐比例", page)
        self.assertIn("102 条累计评价", page)
        data["games"][0]["price"] = {"formatted": "¥38.00", "region": "CN"}
        self.assertIn("¥38.00 · 国区", market_render.render_market(data))
        data["games"][0]["price"] = {"formatted": "9.99 €", "region": "DE"}
        self.assertIn("9.99 € · DE 区", market_render.render_market(data))


if __name__ == "__main__":
    unittest.main()
