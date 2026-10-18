"""Render tag-level Steam observations from measured data and explicit coverage."""
from __future__ import annotations

from urllib.parse import urlparse

from market_analysis import build_global_analysis, _review, _players
from market_render import esc, _number, _time, _url, _games, _fresh_players, _day, _dt
from site_navigation import SITE_NAV_CSS, render_site_navigation


def market_navigation(current="global"):
    return '<nav class="market-nav" aria-label="市场页面">' + ''.join(
        f'<a href="{href}"' + (' aria-current="page"' if current == key else '') + f'>{label}</a>'
        for key, href, label in (("global", "market.html", "全局市场"), ("action", "market-action.html", "动作游戏"))
    ) + '</nav>'


CSS = r'''
:root{color-scheme:light;--paper:#f1ede3;--panel:#faf8f1;--ink:#292d27;--soft:#62675c;--muted:#767c70;--line:#d1d0c1;--sage:#4c6152;--wash:#e6eadf;--rust:#9b493b;--serif:Georgia,"Noto Serif SC","Songti SC",SimSun,serif;--sans:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:22px}body{margin:0;background:var(--paper);color:var(--ink);font:14px/1.7 var(--sans)}h1,h2,h3,p,dl,dd{margin:0}h1,h2,h3{font-family:var(--serif)}a{color:inherit;text-underline-offset:4px}a:hover{color:var(--rust)}button,summary{font:inherit;cursor:pointer}button:focus-visible,a:focus-visible,summary:focus-visible{outline:3px solid var(--rust);outline-offset:4px}[hidden]{display:none!important}.wrap{width:min(1120px,100% - 56px);margin:auto}.skip{position:fixed;top:10px;left:10px;transform:translateY(-200%);background:var(--ink);color:white;padding:10px;z-index:9}.skip:focus{transform:none}.masthead{display:flex;justify-content:space-between;align-items:end;gap:24px;padding:30px 0 18px}.masthead h1{font-size:34px;line-height:1.25}.stamp{font-size:11px;color:var(--soft);text-align:right}.stamp b{display:block;font:18px var(--serif);color:var(--ink);margin-bottom:3px}.market-nav{display:flex;gap:26px;border-bottom:1px solid var(--line);margin-bottom:24px}.market-nav a{padding:10px 0;text-decoration:none;color:var(--soft);border-bottom:3px solid transparent}.market-nav a[aria-current]{border-color:var(--sage);color:var(--sage);font-weight:700}
.today{display:grid;grid-template-columns:160px 1fr;gap:22px;background:var(--wash);border-top:2px solid var(--sage);padding:22px 25px}.today h2{font-size:23px}.today time{font-size:11px;color:var(--sage)}.today ol{list-style:none;padding:0;margin:0;counter-reset:observations}.today li{counter-increment:observations;position:relative;padding-left:28px;font-size:13px;line-height:1.9}.today li+li{margin-top:9px}.today li:before{content:"0" counter(observations);position:absolute;left:0;top:2px;font:12px/1.9 Georgia,serif;color:var(--sage)}.coverage{display:flex;flex-wrap:wrap;gap:7px 22px;padding:13px 0;font-size:11px;color:var(--soft)}.coverage a{margin-left:auto}.section{margin-top:31px;scroll-margin-top:22px}.section-head{display:flex;align-items:baseline;justify-content:space-between;gap:20px;padding-bottom:12px;border-bottom:1px solid var(--ink)}.section-head h2{font-size:24px;line-height:1.4}.section-head p{font-size:11px;color:var(--soft)}.section-note{font-size:11px;color:var(--muted);margin:10px 0 15px;line-height:1.8}.section-head small{font:11px var(--sans);color:var(--muted);margin-left:10px}.windows{display:flex;gap:4px}.windows button{font-size:12px;padding:5px 12px;background:transparent;border:1px solid var(--line);border-radius:3px;color:var(--soft)}.windows button[aria-pressed=true]{background:var(--sage);border-color:var(--sage);color:var(--panel)}.empty{padding:20px 22px;background:rgba(250,248,241,.55);border:1px solid var(--line);border-radius:4px}.empty strong{display:block;font-size:15px;font-weight:500}.empty p{margin-top:6px;font-size:12px;color:var(--soft)}.empty .milestones{display:flex;gap:12px 26px;flex-wrap:wrap;font-size:11px;color:var(--muted);margin-top:13px}.tag-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:15px;margin-top:15px}.tag-card{position:relative;min-width:0;background:var(--panel);border:1px solid var(--line);border-radius:5px;overflow:hidden}.tag-main{display:block;text-decoration:none;padding:18px 18px 13px}.tag-main:hover h3{color:var(--rust)}.tag-kicker{display:flex;justify-content:space-between;font-size:10px;color:var(--muted);gap:10px}.tag-card h3{font-size:22px;margin:5px 0 10px;line-height:1.35}.tag-metric{display:flex;align-items:baseline;gap:7px;color:var(--sage)}.tag-metric strong{font:27px/1.25 Georgia,serif}.tag-metric span{font-size:11px}.tag-note{font-size:11px;color:var(--soft);margin-top:6px;min-height:37px}.tag-images{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:5px;padding:0 18px 16px}.mini-game{display:block;min-width:0;text-decoration:none}.cover{display:grid;place-items:center;position:relative;aspect-ratio:460/215;background:#e1e3da;border-radius:3px;overflow:hidden}.cover img{width:100%;height:100%;position:absolute;inset:0;object-fit:cover}.cover span{font-size:9px;color:var(--soft);padding:8px;text-align:center}.mini-game>span{display:block;font-size:9px;line-height:1.4;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:5px;color:var(--soft)}.more-tags{margin-top:15px}.more-tags>summary{font-size:12px;color:var(--sage)}.release-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:15px;margin-top:15px}.release-card{display:block;min-width:0;text-decoration:none;border-bottom:1px solid var(--line);padding-bottom:16px}.release-card h3{font-size:16px;margin-top:9px;line-height:1.5;overflow-wrap:anywhere}.release-card p{font-size:11px;color:var(--soft);margin-top:4px}.release-card .release-age{display:flex;justify-content:space-between;gap:10px;color:var(--sage);font-size:10px;margin-top:9px}.tag-chips{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}.tag-chip{font-size:9px;padding:2px 6px;background:var(--wash);color:var(--sage)}
.tag-detail{border-bottom:1px solid var(--line);scroll-margin-top:22px}.tag-detail>summary{list-style:none;display:flex;align-items:center;gap:14px;padding:15px 0}.tag-detail>summary::-webkit-details-marker{display:none}.tag-detail>summary:after{content:"＋";margin-left:auto;color:var(--sage)}.tag-detail[open]>summary:after{content:"−"}.tag-detail h3{font-size:18px}.tag-detail .detail-count{font-size:11px;color:var(--muted)}.tag-detail:target{border-top:2px solid var(--sage)}.detail-inner{padding:0 0 22px}.evidence-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));border:1px solid var(--line);border-radius:4px;margin-bottom:15px;background:var(--panel)}.evidence-grid>div{padding:14px 18px;min-width:0}.evidence-grid>div+div{border-left:1px solid var(--line)}.evidence-grid dt{font-size:10px;color:var(--soft)}.evidence-grid dd{font-size:19px;margin:3px 0}.evidence-grid p{font-size:10px;color:var(--soft);line-height:1.8}.group-games{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.sample-game{display:grid;grid-template-columns:92px minmax(0,1fr);gap:11px;align-items:start;text-decoration:none;padding:12px;background:var(--panel);border:1px solid var(--line);border-radius:4px;min-width:0}.sample-game h4{font-size:12px;line-height:1.5;margin:0;overflow-wrap:anywhere}.sample-game p{font-size:10px;color:var(--soft);margin-top:3px}.remaining-games{margin-top:12px;font-size:11px;color:var(--soft)}.remaining-games>div{display:flex;flex-wrap:wrap;gap:9px 18px;padding-top:12px}.detail-note{font-size:11px;color:var(--soft);margin:12px 0}.methodology{margin-top:30px;border-top:1px solid var(--ink);padding-top:15px}.methodology>summary{font-size:14px;font-weight:600}.method-body{display:grid;grid-template-columns:1.2fr 1fr;gap:35px;padding:18px 0}.method-body h3{font-size:17px;margin-bottom:10px}.method-body p,.method-body li{font-size:11px;color:var(--soft);line-height:1.9}.method-body p+p{margin-top:9px}.method-body ul{margin:0;padding-left:18px}.method-body li+li{margin-top:8px}.source-status{font-size:10px;color:var(--muted)}.footer{display:flex;justify-content:space-between;gap:20px;padding:24px 0 30px;margin-top:24px;border-top:1px solid var(--line);font-size:11px;color:var(--soft)}.footer nav{display:flex;gap:20px}.up{color:var(--sage)}noscript p{font-size:11px;color:var(--muted);margin:10px 0}
@media(max-width:900px){.tag-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.group-games{grid-template-columns:repeat(2,minmax(0,1fr))}.today{grid-template-columns:130px 1fr}.tag-card h3{font-size:22px}}
@media(max-width:600px){.wrap{width:calc(100% - 30px)}.masthead{display:block;padding:24px 0 12px}.masthead h1{font-size:28px}.stamp{text-align:left;margin-top:9px;font-size:10px}.stamp b{display:inline;font-size:13px;margin-right:12px}.market-nav{margin-bottom:18px;font-size:13px}.today{display:block;padding:17px}.today h2{font-size:20px;margin-bottom:10px}.today li{font-size:12px;padding-left:24px}.coverage{font-size:10px;gap:5px 13px}.coverage a{margin-left:0}.section{margin-top:27px}.section-head{align-items:center;gap:12px}.section-head h2{font-size:21px}.section-head p{font-size:10px}.section-note{font-size:10px}.tag-grid{gap:10px}.tag-main{padding:13px 12px 10px}.tag-card h3{font-size:20px}.tag-metric{flex-wrap:wrap;gap:2px 5px}.tag-metric strong{font-size:23px}.tag-metric span{font-size:10px}.tag-note{font-size:10px;min-height:50px}.tag-images{padding:0 12px 12px;grid-template-columns:repeat(2,minmax(0,1fr))}.tag-images .mini-game:nth-child(3){display:none}.mini-game>span{font-size:8px}.tag-kicker{font-size:9px}.windows button{font-size:11px;padding:4px 8px}.empty{padding:17px}.empty strong{font-size:14px}.empty p{font-size:11px}.release-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:15px 12px}.release-card h3{font-size:14px}.release-card .release-age{font-size:9px;flex-wrap:wrap;gap:0}.release-card p{font-size:10px}.evidence-grid{grid-template-columns:1fr}.evidence-grid>div+div{border-left:0;border-top:1px solid var(--line)}.evidence-grid>div{padding:12px 15px}.evidence-grid dd{font-size:18px}.group-games{grid-template-columns:1fr}.sample-game{grid-template-columns:110px minmax(0,1fr)}.method-body{grid-template-columns:1fr;gap:20px}.tag-detail h3{font-size:17px}.footer{display:block}.footer nav{margin-top:12px}}
@media(max-width:360px){.tag-grid{grid-template-columns:1fr}.tag-images{grid-template-columns:repeat(3,minmax(0,1fr))}.tag-images .mini-game:nth-child(3){display:block}.tag-note{min-height:0}.section-head{flex-wrap:wrap}.tag-card h3{font-size:22px}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}@media print{.windows,.site-header,.market-nav{display:none}body{background:white}.wrap{width:100%}.tag-card{break-inside:avoid}}
'''+SITE_NAV_CSS


SCRIPT = r'''
(() => {
  document.querySelectorAll('.cover img').forEach(image => {
    const fallback=()=>{image.hidden=true;image.nextElementSibling.hidden=false;};
    image.addEventListener('error',fallback);
    if(image.complete&&!image.naturalWidth) fallback();
  });
  const params=new URLSearchParams(location.search);
  let days=['1','7','30'].includes(params.get('days'))?params.get('days'):'7';
  function apply(){
    document.querySelectorAll('[data-period]').forEach(p=>p.hidden=p.dataset.period!==days);
    document.querySelectorAll('[data-days]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.days===days)));
    const url=new URL(location.href);if(days==='7')url.searchParams.delete('days');else url.searchParams.set('days',days);
    try{history.replaceState(null,'',url.pathname+url.search+url.hash);}catch(_){}
  }
  document.querySelectorAll('[data-days]').forEach(b=>b.addEventListener('click',()=>{days=b.dataset.days;apply();}));
  document.querySelectorAll('.windows').forEach(e=>e.hidden=false);apply();
  function reveal(){
    let id;try{id=decodeURIComponent(location.hash.slice(1));}catch(_){return;}
    const target=document.getElementById(id);if(!target)return;
    if(target.tagName==='DETAILS')target.open=true;
    let parent=target.parentElement;while(parent){if(parent.tagName==='DETAILS')parent.open=true;parent=parent.parentElement;}
    requestAnimationFrame(()=>target.scrollIntoView({block:'start'}));
  }
  addEventListener('hashchange',reveal);if(location.hash)reveal();
})();
'''


def cover(game):
    url = _url(game.get("header_image"))
    image = f'<img src="{esc(url)}" alt="{esc(game.get("name"))} 商店封面" width="460" height="215" loading="lazy" decoding="async">' if url else ''
    return f'<div class="cover">{image}<span' + (' hidden' if image else '') + '>封面暂不可用</span></div>'


def store(game):
    return f'https://store.steampowered.com/app/{int(game["appid"])}/'


def lookup(ids, games):
    return [games[str(appid)] for appid in ids if str(appid) in games]


def mini_games(ids, games):
    return '<div class="tag-images">' + ''.join(f'<a class="mini-game" href="{store(g)}" target="_blank" rel="noopener noreferrer">{cover(g)}<span>{esc(g["name"])}</span></a>' for g in lookup(ids, games)[:3]) + '</div>'


def tag_card(group, games, index, basis, days=None):
    pop = group["popularity"]
    if days is not None:
        win = group["windows"][str(days)]
        value = _number(win.get("percent_change"), 1, True) + '%'
        unit = '采样在线均值'
        note = f'{win["up_count"]} / {win["valid_count"]} 款可比作品上涨；绝对变化 {_number(win.get("absolute_change"), 0, True)} 人'
        ids = win.get("representative_ids") or group["representative_ids"]
    elif basis.get("id") == "global_top_sellers":
        value, unit = _number(pop.get("top_seller_count")), '款进入热销样本'
        note = f'最高第 {_number(pop.get("best_rank"))} 位 · 收入榜，包含 DLC 与内购'
        ids = group["representative_ids"]
    else:
        value, unit = _number(pop.get("current_players")), '人 · 采样在线合计'
        share = _number(pop.get("leader_share_percent"), 0)
        note = f'{pop.get("observed_count", 0)} 款本轮有值 · 头部一款占 {share}%'
        ids = group["representative_ids"]
    return f'''<article class="tag-card"><a class="tag-main" href="#tag-{esc(group['id'])}"><div class="tag-kicker"><span>{index:02d}</span><span>{group['sample_count']} 款样本 →</span></div><h3>{esc(group['label'])}</h3><div class="tag-metric"><strong>{value}</strong><span>{unit}</span></div><p class="tag-note">{esc(note)}</p></a>{mini_games(ids, games)}</article>'''


def sample_game(game, now):
    today = now.date() if now else None
    released = _day(game.get("first_release_date") or game.get("release_date"))
    age = f'商店日期距今 {(today-released).days} 天' if today and released and today >= released else '发售日待确认'
    value = _players(game, now) if now else None
    players = f'在线 {_number(value)}' if value is not None else '在线未取得本轮值'
    return f'<a class="sample-game" href="{store(game)}" target="_blank" rel="noopener noreferrer">{cover(game)}<div><h4>{esc(game["name"])} ↗</h4><p>{esc(age)} · {players}</p><p>{esc((game.get("price") or {}).get("formatted") or "价格未取得")}</p></div></a>'


def group_detail(group, games, now):
    pop, new = group["popularity"], group["new_releases"]
    models = group.get('commercial_models') or {}
    model_note = f'免费 {models.get("free",0)} 款 / 付费 {models.get("paid",0)} 款 / 未确认 {models.get("unknown",0)} 款。' if models else ''
    panels = []
    for days in (1, 7, 30):
        win = group["windows"][str(days)]
        valid = win.get("valid_count", 0)
        if win.get("current") is not None:
            value = f'{_number(win.get("previous"), 1)} → {_number(win.get("current"), 1)}'
            note = f'可比 {valid}/{group["sample_count"]} 款，上涨 {win.get("up_count", 0)} 款；{win.get("reason", "")}'
        else:
            value = '历史积累中'
            note = f'可比 {valid}/{group["sample_count"]} 款。' + win.get("reason", "")
        panels.append(f'<div data-period="{days}"' + (' hidden' if days != 7 else '') + f'><dt>{days} 天采样在线均值</dt><dd>{value}</dd><p>{esc(note)}</p></div>')
    chosen_ids = list(dict.fromkeys(group.get("representative_ids", [])[:3] + group.get("ordinary_ids", [])[:3]))
    chosen = lookup(chosen_ids, games)
    if not chosen:
        chosen = lookup(group["game_ids"], games)[:6]
    chosen_set = {str(g['appid']) for g in chosen}
    remainder = [g for g in lookup(group["game_ids"], games) if str(g['appid']) not in chosen_set]
    remaining = ('<details class="remaining-games"><summary>其余 ' + str(len(remainder)) + ' 款样本</summary><div>' + ''.join(f'<a href="{store(g)}" target="_blank" rel="noopener noreferrer">{esc(g["name"])}</a>' for g in remainder) + '</div></details>') if remainder else ''
    age_note = '；'.join(f'{b["label"]}：{b["count"]} 款' + (f'，当前累计评价中位数 {_number(b["median_reviews"])} 条' if b.get('median_reviews') is not None else '') for b in new.get('age_buckets', []))
    online = f'{_number(pop.get("current_players"))} 人' if pop.get('observed_count') else '暂无本轮值'
    return f'''<details class="tag-detail" id="tag-{esc(group['id'])}"><summary><h3>{esc(group['label'])}</h3><span class="detail-count">{group['sample_count']} 款 · 近 90 天发行记录 {new['sample_count']} 款</span></summary><div class="detail-inner"><dl class="evidence-grid"><div><dt>已取得快照的在线合计</dt><dd>{online}</dd><p>本轮覆盖 {pop.get('observed_count', 0)}/{group['sample_count']} 款；头部一款占 {_number(pop.get('leader_share_percent'), 1)}%。不代表市场份额。</p></div>{''.join(panels)}<div><dt>商店发行日期分组</dt><dd>{new['sample_count']} 款</dd><p>{esc(age_note or '样本中暂无近 90 天新作。')}</p></div></dl><p class="detail-note">{esc(model_note)}展示榜单或在线较高的作品，以及本样本中在线较低的作品。在线较低不等于销量较差；点击封面查看原始商店页面。</p><div class="group-games">{''.join(sample_game(g, now) for g in chosen)}</div>{remaining}</div></details>'''


def release_cards(analysis, games, now):
    today = now.date() if now else None
    by_group = {}
    for group in analysis['new_releases']:
        for appid in group['new_releases']['game_ids']:
            by_group.setdefault(str(appid), []).append(group['label'])
    # Most recently released first, not an unsupported commercial-success ranking.
    released = [g for g in games.values() if str(g['appid']) in by_group]
    released.sort(key=lambda g: (g.get('first_release_date') or g.get('release_date') or '', -int(g['appid'])), reverse=True)
    cards = []
    for g in released[:6]:
        day = _day(g.get('first_release_date') or g.get('release_date'))
        age = f'商店日期距今 {(today-day).days} 天' if day and today else '日期待确认'
        review = _review(g, now) if now else None
        reviews = f'{_number(review.get("total"))} 条累计评价' if review else '评价数据暂未取得'
        chips = ''.join(f'<span class="tag-chip">{esc(label)}</span>' for label in by_group[str(g['appid'])][:2])
        cards.append(f'<a class="release-card" href="{store(g)}" target="_blank" rel="noopener noreferrer">{cover(g)}<div class="release-age"><span>{esc(age)}</span><span>{esc(g.get("release_date"))}</span></div><h3>{esc(g["name"])} ↗</h3><p>{reviews}</p><div class="tag-chips">{chips}</div></a>')
    if not cards:
        return '<div class="empty"><strong>暂未取得可分类的新作样本</strong><p>有明确发售日期与玩法标签的作品才进入本区。</p></div>'
    return '<div class="release-grid">' + ''.join(cards) + '</div>'


def methods(data, analysis):
    source_rows = []
    data_coverage = data.get('coverage') or {}
    rosters = (data.get('coverage') or {}).get('source_rosters') or []
    roster_names = {r.get('name'): r for r in rosters if isinstance(r, dict)}
    sources = data.get('sources') or []
    if isinstance(sources, dict):
        sources = list(sources.values())
    for source in sources:
        if not isinstance(source, dict):
            continue
        label = source.get('name') or source.get('label') or source.get('id') or 'Steam 来源'
        roster = roster_names.get(label, {})
        url = _url(source.get('url') or source.get('source_url'))
        link = f'<a href="{esc(url)}" target="_blank" rel="noopener noreferrer">{esc(label)} ↗</a>' if url else esc(label)
        state = {'fresh':'已取得','partial':'部分取得','stale':'沿用旧记录','unavailable':'暂未取得'}.get(roster.get('status') or source.get('status'), '')
        counts = f' · 发现 {roster.get("discovered_count",0)} 款，纳入 {roster.get("tracked_count",0)} 款' if roster else ''
        timestamp = f' · {_time(roster.get("observed_at"))}' if roster.get('observed_at') else ''
        note = source.get('note') or roster.get('scope_note') or ''
        source_rows.append(f'<li>{link}<span class="source-status"> {state}{counts}{timestamp}</span><p>{esc(note)}</p></li>')
    if not source_rows:
        source_rows = ['<li><a href="https://store.steampowered.com/charts/topselling/global" target="_blank" rel="noopener noreferrer">Steam 全球热销榜 ↗</a></li>', '<li>Steam 最新发行、热门游戏与公开接口。</li>']
    notes = ''.join(f'<li>{esc(note)}</li>' for note in analysis.get('methodology', []))
    notes += ''.join(f'<li>{esc(note)}</li>' for note in data.get('methodology', [])[:4])
    if data_coverage.get('deferred_candidates'):
        notes += f'<li>本轮另有 {data_coverage["deferred_candidates"]} 款有效候选因收录上限暂未进入持续采样。</li>'
    return f'''<details class="methodology" id="methodology"><summary>采集范围、数据口径与来源</summary><div class="method-body"><div><h3>如何阅读这些数据</h3><ul>{notes}</ul><p>每天发现新游戏并持续采样。当前为跨类型观察样本，不是 Steam 全站普查；本页保留普通、低关注作品，但仍存在来源与收录上限造成的偏差。</p><p>买断与免费运营游戏在同一方向下可能共存。热销榜含 DLC 与内购，在线人数不等于销量；这些数据不用于直接推算回报率。</p><p>近 90 天新作按商店发售日期观察，可能包含从抢先体验转正式发售的作品。累计评价不是首 7／30 天表现，暂不据此发布新作成功率或竞争饱和度。</p></div><div><h3>已接入来源</h3><ul>{''.join(source_rows)}</ul><h3 style="margin-top:20px">商业估算与竞品工具</h3><p><a href="https://sensortower.com/product-video-game-insights" target="_blank" rel="noopener noreferrer">Video Game Insights</a>、<a href="https://gamalytic.com/about" target="_blank" rel="noopener noreferrer">Gamalytic</a> 的销量、收入估算尚未接入，本页不展示估算销量。</p><p><a href="https://steampeek.hu/" target="_blank" rel="noopener noreferrer">SteamPeek</a> 可用于手动寻找相似作品，尚未自动接入。</p></div></div></details>'''


def render_global_market(data):
    analysis = build_global_analysis(data)
    games = {str(g['appid']):g for g in _games(data)}
    generated = _dt(data.get('generated_at'))
    today = generated.date() if generated else None
    basis = analysis['popularity_basis']
    summaries = analysis.get('summary') or ['尚未取得跨类型游戏样本，等待采集。']
    summary = ''.join(f'<li>{esc(text)}</li>' for text in (summaries[1:3] if len(summaries)>1 else summaries))
    coverage = analysis['coverage']
    periods = []
    for days in (1,7,30):
        rows = analysis['rising'][str(days)]
        content = '<div class="tag-grid">'+''.join(tag_card(g,games,i+1,basis,days) for i,g in enumerate(rows[:6]))+'</div>' if rows else f'<div class="empty"><strong>暂无足够证据确认 {days} 天持续升温的方向</strong><p>比较最近 {days} 个完整日与此前 {days} 日，并检查上涨是否涉及多款作品。历史不足、样本过少或主要由单款拉动时，不列入升温榜。</p><div class="milestones"><span>1 天 · 短期异动</span><span>7 天 · 持续变化</span><span>30 天 · 较长趋势</span></div></div>'
        periods.append(f'<div data-period="{days}"'+(' hidden' if days!=7 else '')+f'>{content}</div>')
    popular = analysis['popular']
    hot = '<div class="tag-grid">'+''.join(tag_card(g,games,i+1,basis) for i,g in enumerate(popular[:6]))+'</div>' if popular else '<div class="empty"><strong>分类样本不足</strong><p>取得足够作品与本轮数据后展示方向排序。</p></div>'
    if len(popular)>6:
        hot += '<details class="more-tags"><summary>查看其余 '+str(len(popular)-6)+' 个方向</summary><div class="tag-grid">'+''.join(tag_card(g,games,i+7,basis) for i,g in enumerate(popular[6:]))+'</div></details>'
    group_details = ''.join(group_detail(g,games,generated) for g in analysis['groups'])
    new_count = coverage.get('recent_games',0)
    new_tags = '<div class="tag-chips">' + ''.join(f'<a class="tag-chip" href="#tag-{esc(g["id"])}">{esc(g["label"])} · {g["new_releases"]["sample_count"]} 款</a>' for g in analysis['new_releases'][:8]) + '</div>'
    rising_section = f'''<section class="section" id="rising"><div class="section-head"><h2>近期升温</h2><div class="windows" role="group" aria-label="趋势时间窗口" hidden><button type="button" data-days="1" aria-pressed="false">1 天</button><button type="button" data-days="7" aria-pressed="true">7 天</button><button type="button" data-days="30" aria-pressed="false">30 天</button></div></div><p class="section-note">按同一批作品的采样在线均值比较，检查增长是否集中在单款游戏。</p>{''.join(periods)}<noscript><p>当前显示 7 天窗口；启用 JavaScript 后可切换。</p></noscript></section>'''
    popular_section = f'''<section class="section" id="popular"><div class="section-head"><h2>当前热门</h2><p>{esc(basis.get('label',''))}</p></div><p class="section-note">{esc(basis.get('note',''))} 标签可以重叠，数量与在线人数不能跨标签相加。</p>{hot}</section>'''
    sections = rising_section + popular_section if any(analysis['rising'].values()) else popular_section + rising_section
    return f'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Steam 全局市场 · 策划日报</title><meta name="description" content="Steam 跨类型市场观察：玩法标签、近期变化与新发行游戏，保留样本范围和原始来源。"><style>{CSS}</style></head><body><a class="skip" href="#today">跳到今日观察</a><div class="wrap">{render_site_navigation('market')}<header class="masthead"><h1>Steam 市场观察</h1><div class="stamp"><b>{esc(generated.strftime('%Y.%m.%d') if generated else '记录建立中')}</b>采集 {_time(data.get('generated_at'),False)} · 北京时间</div></header>{market_navigation()}
<main><section class="today" id="today" aria-labelledby="today-title"><h2 id="today-title">今日观察</h2><ol>{summary}</ol></section><div class="coverage"><span>{coverage.get('total_games',0)} 款收录样本</span><span>在线覆盖 {coverage.get('fresh_games',0)}/{coverage.get('total_games',0)} 款</span><span>{len(analysis['groups'])} 个玩法方向</span><span>{new_count} 款近期发行记录</span><a href="#methodology">覆盖范围与数据来源 ↓</a></div>
{sections}
<section class="section" id="new-releases"><div class="section-head"><h2>新作观察</h2><p>最近发售优先 · 当前快照</p></div><p class="section-note">覆盖近 90 天已发售样本，卡片优先展示最新作品。累计评价仅供浏览，尚未形成同龄新作的首 7／30 天表现比较。</p>{new_tags}{release_cards(analysis,games,generated)}</section>
<section class="section" id="directions"><div class="section-head"><h2>各方向的作品与数据</h2><p>展开查看样本</p></div><p class="section-note">每个方向保留代表作品、在线较低的样本和可比历史覆盖。</p>{group_details or '<div class="empty">暂未取得可分类的游戏。</div>'}</section>{methods(data,analysis)}</main><footer class="footer"><span>策划日报 / Steam 全局市场</span><nav><a href="market-action.html">动作游戏观察</a><a href="index.html">回到日报</a></nav></footer></div><script>{SCRIPT}</script></body></html>'''


def render_global_brief(data, href="market.html"):
    parsed = urlparse(str(href))
    if parsed.scheme not in ('','http','https') or str(href).startswith('//'):
        href='market.html'
    analysis = build_global_analysis(data)
    lines = ''.join(f'<li>{esc(text)}</li>' for text in analysis['summary'][:3])
    return f'''<style>.global-brief{{margin-top:35px;padding-top:22px;border-top:3px double #292d27}}.global-brief>div{{display:flex;justify-content:space-between;gap:15px;align-items:baseline}}.global-brief h2{{font:700 24px Georgia,"Songti SC",serif;margin:0}}.global-brief a{{font-size:12px;color:#4c6152}}.global-brief p{{font-size:10px;color:#74796d}}.global-brief ul{{padding-left:19px;font-size:12px;line-height:1.9;color:#5e635a}}.global-brief li+li{{margin-top:6px}}</style><section class="global-brief" id="steam-market-brief"><div><h2>Steam 市场摘要</h2><a href="{esc(href)}">查看全局市场 →</a></div><p>市场采集 {_time(data.get('generated_at'))} · 北京时间</p><ul>{lines}</ul></section>'''
