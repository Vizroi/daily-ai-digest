"""Four-page routing, calendar windows, discovery baselines and safe output."""
from datetime import date
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from indie_render import PAGES, day, model_game, render_indie_market, render_indie_pages, select_games


def game(appid=1):
    return {'appid': appid, 'name': f'Game {appid}', 'tags': ['Indie', 'Puzzle'],
            'release_date': '2026-10-28', 'coming_soon': False, 'metadata_status': 'fresh',
            'current_players': 0, 'players_status': 'fresh', 'players_observed_at': '2026-10-28T12:00:00+08:00',
            'review_windows': {str(days): {'count': days * 10, 'positive_percent': 90,
                'status': 'fresh', 'sampled_at': '2026-10-28T12:00:00+08:00'} for days in (1, 7, 30)}}


class IndieRenderTests(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 10, 28)

    def test_release_windows_use_release_dates_and_calendar_boundaries(self):
        samples = []
        for appid, released in enumerate(('2026-10-28', '2026-10-22', '2026-10-21', '2026-09-29', '2026-09-28', '2026-10-29'), 1):
            sample = game(appid)
            sample['release_date'] = released
            samples.append(model_game(sample))
        for days, expected in ((1, [1]), (7, [1, 2]), (30, [1, 2, 3, 4])):
            actual = select_games(samples, 'releases', days=days, today=self.today)
            self.assertEqual([g['appid'] for g in actual], expected)

    def test_release_excludes_upcoming_unverified_early_access_and_stale_metadata(self):
        first, second, third, fourth = [game(i) for i in range(1, 5)]
        first['coming_soon'] = True
        second['release_date_status'] = 'first_release_unverified'
        fourth['metadata_status'] = 'stale'
        result = select_games([model_game(g) for g in (first, second, third, fourth)], 'releases', today=self.today)
        self.assertEqual([g['appid'] for g in result], [3])

    def test_upcoming_first_snapshot_is_baseline_not_new_listing(self):
        first, second, released, stale = [game(i) for i in range(1, 5)]
        for sample in (first, second, released, stale):
            sample.update(first_seen_at='2026-10-28T01:00:00+08:00', listing_basis='first_observed')
        first.update(coming_soon=True, listing_basis='baseline')
        second['coming_soon'] = True
        stale.update(coming_soon=True, metadata_status='stale')
        models = [model_game(g) for g in (first, second, released, stale)]
        self.assertEqual([g['appid'] for g in select_games(models, 'upcoming', days=1, today=self.today)], [2])
        page = render_indie_market({}, {'upcoming_games': [first, second], 'initialized_at': '2026-10-28T01:00:00+08:00'})
        self.assertIn('id="baseline" open', page)
        self.assertIn('已建立观察池 · 1 款基线作品', page)
        self.assertIn('首次快照作为基线，不计作当天新增', page)

    def test_timezone_and_search_filters(self):
        self.assertEqual(day('2026-10-27T17:00:00Z'), '2026-10-28')
        self.assertIsNone(day('2026-10-28T01:00:00'))
        models = [model_game(game(1)), model_game(game(2))]
        self.assertEqual([g['appid'] for g in select_games(models, 'releases', query='GAME 2', style='解谜', today=self.today)], [2])
        self.assertEqual(select_games(models, 'releases', style='卡牌', today=self.today), [])

    def test_ratings_keep_minimum_twenty_and_stale_exclusion(self):
        first, second = game(1), game(2)
        first['review_windows']['1'].update(count=19, positive_percent=100)
        second['review_windows']['1'].update(count=30, positive_percent=90)
        self.assertEqual([g['appid'] for g in select_games([model_game(first), model_game(second)], 'ratings', 1)], [2])
        first['review_windows']['1']['count'] = 20
        self.assertEqual(select_games([model_game(first), model_game(second)], 'ratings', 1)[0]['appid'], 1)
        first['review_windows']['1']['status'] = 'stale'
        self.assertEqual([g['appid'] for g in select_games([model_game(first), model_game(second)], 'ratings', 1)], [2])

    def test_online_preserves_zero_excludes_stale_and_has_no_window_controls(self):
        first, second = game(1), game(2)
        second.update(current_players=100, players_status='stale')
        models = [model_game(first), model_game(second)]
        self.assertEqual([g['appid'] for g in select_games(models, 'online')], [1])
        page = render_indie_market({'games': [first, second]}, page='online')
        self.assertNotIn('data-days="', page)
        self.assertIn('data-value="players">0<', page)

    def test_four_real_page_routes_and_no_new_review_primary_tab(self):
        pages = render_indie_pages({'games': [game()]}, {'release_games': [game()]})
        self.assertEqual(set(pages), {entry[0] for entry in PAGES.values()})
        for filename, page in pages.items():
            self.assertIn(f'href="{filename}" aria-current="page"', page)
            self.assertNotIn('data-metric="', page)
            self.assertNotIn('新增评价排行', page)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            result = subprocess.run([sys.executable, str(ROOT / 'src/indie_render.py'), '--input', str(path / 'absent.json'), '--discovery', str(path / 'absent-discovery.json'), '--output', str(path / 'indie.html')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(all((path / filename).exists() for filename in pages))

    def test_html_and_json_script_cannot_be_broken_by_external_strings(self):
        sample = game()
        sample['name'] = '</script><script>alert("x")</script>'
        sample['header_image'] = 'javascript:alert(1)'
        page = render_indie_market({'games': [sample], 'scope_note': '<img src=x onerror=alert(1)>'}, page='ratings')
        self.assertNotIn('<script>alert("x")', page)
        self.assertNotIn('src="javascript:', page)
        self.assertNotIn('<img src=x onerror=', page)
        payload = re.search(r'<script type="application/json" id="ranking-data">(.*?)</script>', page, re.S)
        self.assertEqual(json.loads(payload.group(1))['games'][0]['name'], sample['name'])


if __name__ == '__main__':
    unittest.main()
