"""Global UI must retain evidence scope, safe links and progressive disclosure."""
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from global_market_render import render_global_market
from market_render import render_action_market, render_market_brief
import render


def fixture():
    stamp = '2026-10-18T14:00:00+08:00'
    return {'market_scope':'global', 'generated_at':stamp, 'games':[
        {'appid':100, 'name':'Factory <One>', 'tags':['Automation'], 'is_action':False,
         'release_date':'2026-10-17', 'header_image':'https://example.com/cover.jpg',
         'current_players':0, 'players_status':'fresh', 'players_observed_at':stamp,
         'top_sellers_rank':7, 'top_sellers_status':'fresh', 'top_sellers_observed_at':stamp,
         'review_summary':{'total':12,'positive':10,'negative':2,'status':'fresh','sampled_at':stamp,'scope':'all_languages_all_purchases'},
         'windows':{}}
    ]}


class Page(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.ids=[];self.anchors=[];self.periods=[];self.links=[]
        self.feed(source)
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if attrs.get('id'):self.ids.append(attrs['id'])
        if 'data-period' in attrs:self.periods.append(attrs)
        if tag=='a':
            self.links.append(attrs.get('href',''))
            if attrs.get('href','').startswith('#'):self.anchors.append(attrs['href'][1:])


class GlobalMarketRenderTests(unittest.TestCase):
    def test_real_global_rank_is_not_rendered_as_concurrent_players(self):
        page=render_global_market(fixture())
        self.assertIn('全球热销榜入榜作品数', page)
        self.assertIn('最高第 7 位', page)
        self.assertIn('款进入热销样本', page)
        self.assertIn('0 人', page)
        self.assertNotIn('0%', page.split('id="popular"')[1].split('id="new-releases"')[0])

    def test_hash_targets_and_default_seven_day_periods(self):
        page=Page(render_global_market(fixture()))
        self.assertEqual(len(page.ids),len(set(page.ids)))
        self.assertTrue(all(target in page.ids for target in page.anchors))
        self.assertNotIn('market-action.html',page.links)
        for period in page.periods:
            self.assertEqual('hidden' in period,period['data-period']!='7')

    def test_stale_review_and_untrusted_names_are_not_published_as_fresh(self):
        data=fixture();game=data['games'][0]
        game['name']='</h3><script>alert(1)</script>'
        game['header_image']='javascript:alert(1)'
        game['review_summary']['sampled_at']='2026-09-01T14:00:00+08:00'
        page=render_global_market(data)
        self.assertNotIn('<script>alert',page)
        self.assertNotIn('src="javascript:',page)
        self.assertNotIn('12 条累计评价',page)
        self.assertIn('评价数据暂未取得',page)

    def test_empty_data_does_not_invent_market_leaders_or_trends(self):
        page=render_global_market({})
        self.assertIn('暂无足够证据确认 7 天持续升温',page)
        self.assertIn('分类样本不足',page)
        self.assertIn('尚未接入',page)
        self.assertNotIn('最高第 0',page)

    def test_previous_action_address_redirects_to_the_single_market_page(self):
        page=render_action_market()
        self.assertIn('http-equiv="refresh" content="0;url=market.html"',page)
        self.assertNotIn('id="game-100"',page)
        self.assertNotIn('动作游戏观察',page)
        self.assertIn('href="market.html"',page)

    def test_build_outputs_market_and_compatibility_redirect_and_keeps_archive_intact(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp);inp=path/'global.json'
            inp.write_text(json.dumps(fixture()),encoding='utf8')
            archive=path/'archive.html';archive.write_text('keep',encoding='utf8')
            result=subprocess.run([sys.executable,str(ROOT/'src/market_render.py'),'--input',str(inp),'--output',str(path/'market.html')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('content="0;url=market.html"',(path/'market-action.html').read_text(encoding='utf8'))
            self.assertEqual(archive.read_text(),'keep')
            self.assertIn('全局市场', (path/'market.html').read_text(encoding='utf8'))

    def test_complete_summary_is_on_market_page_before_observations_and_not_in_daily(self):
        digest=json.loads((ROOT/'data/digest.json').read_text(encoding='utf8'))
        daily=render.render(digest,market=fixture())
        self.assertNotIn('steam-market-brief',daily)
        self.assertIn('href="market.html"',daily)
        market=render_global_market(fixture())
        self.assertIn('本次收录 1 款',market)
        self.assertEqual(market.count('id="steam-market-brief"'),1)
        self.assertLess(market.index('id="steam-market-brief"'),market.index('id="popular"'))


if __name__=='__main__':unittest.main()
