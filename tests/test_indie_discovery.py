"""Discovery baseline, release transitions, and date evidence remain distinct."""
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import indie_discovery as d


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 28, 12, tzinfo=d.TZ)

    def meta(self, upcoming=True):
        return {'name': 'Game', 'app_type': 'game', 'tags': ['Indie', 'Puzzle'],
                'coming_soon': upcoming, 'is_demo': False, 'is_free': False,
                'release_date': '2026-10-28' if not upcoming else None,
                'metadata_status': 'fresh', 'metadata_at': d.stamp(self.now),
                'price': {'currency': 'USD', 'initial': None, 'final': 999 if not upcoming else None, 'discount_percent': 0}}

    def build(self, previous, upcoming_ids, release_ids, metadata, now=None):
        now = now or self.now
        def fetch(definition, current, deadline):
            ids = upcoming_ids if definition['id'] == 'upcoming' else release_ids
            return dict(definition, items=[{'appid': i, 'rank': n} for n, i in enumerate(ids, 1)],
                        status='fresh', observed_at=d.stamp(current))
        with patch.object(d, 'fetch_source', side_effect=fetch), patch.object(d, 'fetch_metadata', return_value=(metadata, set(), [])):
            return d.build_discovery(previous, {}, {}, now, refresh=True)

    def test_first_snapshot_is_baseline_and_later_observation_is_not_backdated(self):
        first = self.build({}, [1], [], {1: self.meta()})
        self.assertEqual(first['upcoming_games'][0]['listing_basis'], 'baseline')
        self.assertEqual(first['coverage']['new_observations'], 0)
        second = self.build(first, [1, 2], [], {1: self.meta(), 2: self.meta()}, self.now + timedelta(days=1))
        games = {g['appid']: g for g in second['upcoming_games']}
        self.assertEqual(games[1]['listing_basis'], 'baseline')
        self.assertEqual(games[1]['first_seen_at'], d.stamp(self.now))
        self.assertEqual(games[2]['listing_basis'], 'first_observed')
        self.assertEqual(games[2]['first_seen_at'], d.stamp(self.now + timedelta(days=1)))

    def test_metadata_failure_during_baseline_does_not_create_fake_new_listing_later(self):
        first = self.build({}, [1, 2], [], {1: self.meta()})
        second = self.build(first, [1, 2], [], {1: self.meta(), 2: self.meta()}, self.now + timedelta(days=1))
        self.assertTrue(all(g['listing_basis'] == 'baseline' for g in second['upcoming_games']))

    def test_launch_moves_game_to_releases_without_forgetting_discovery(self):
        first = self.build({}, [1], [], {1: self.meta()})
        second = self.build(first, [], [1], {1: self.meta(False)}, self.now + timedelta(days=1))
        self.assertEqual(second['upcoming_games'], [])
        self.assertEqual(second['release_games'][0]['appid'], 1)
        self.assertIn('1', second['seen_upcoming'])

    def test_failed_refresh_retains_old_timestamp_and_marks_metadata_stale(self):
        first = self.build({}, [1], [2], {1: self.meta(), 2: self.meta(False)})
        with patch.object(d, 'fetch_source', side_effect=ValueError('offline')), patch.object(d, 'fetch_metadata', return_value=({}, set(), ['offline'])):
            second = d.build_discovery(first, {}, {}, self.now + timedelta(days=1), refresh=True)
        self.assertEqual(second['upcoming_games'][0]['metadata_status'], 'stale')
        self.assertEqual(second['upcoming_games'][0]['first_seen_at'], first['upcoming_games'][0]['first_seen_at'])
        self.assertEqual(second['discovery'][0]['observed_at'], first['discovery'][0]['observed_at'])
        self.assertEqual(second['status'], 'partial')

    def test_upcoming_can_have_unannounced_price_but_released_requires_valid_price(self):
        upcoming = self.meta()
        self.assertTrue(d.upcoming_eligible(upcoming))
        released = self.meta(False)
        self.assertTrue(d.recent_release(released, self.now))
        released['price']['final'] = None
        self.assertFalse(d.recent_release(released, self.now))

    def test_future_old_and_unverified_ea_dates_do_not_enter_release_window(self):
        for date in ('2026-10-29', '2026-09-28'):
            meta = self.meta(False)
            meta['release_date'] = date
            self.assertFalse(d.recent_release(meta, self.now))
        meta = self.meta(False)
        meta['release_date_status'] = 'first_release_unverified'
        self.assertFalse(d.recent_release(meta, self.now))
        meta['release_date_status'] = 'store_date'
        meta['release_date'] = '2026-09-29'
        self.assertTrue(d.recent_release(meta, self.now))


if __name__ == '__main__':
    unittest.main()
