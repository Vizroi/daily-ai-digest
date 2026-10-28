"""Four focused Steam indie pages: discovery, releases, ratings and online players."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
from html import escape
import json
import math
from pathlib import Path
from urllib.parse import urlparse

from site_navigation import SITE_NAV_CSS, render_site_navigation

ROOT = Path(__file__).resolve().parents[1]
TZ = timezone(timedelta(hours=8))
PERIODS = (1, 7, 30)
PAGES = {
    "upcoming": ("indie.html", "新上架 · 待发售"),
    "releases": ("indie-releases.html", "最近已发售"),
    "ratings": ("indie-ratings.html", "好评率"),
    "online": ("indie-online.html", "在线人数"),
}
PLAY_STYLES = {
    "休闲": {"Casual", "Relaxing", "Cozy"},
    "解谜": {"Puzzle", "Logic", "Sokoban"},
    "Roguelike": {"Roguelike", "Roguelite", "Action Roguelike", "Rogue-lite", "Traditional Roguelike"},
    "卡牌": {"Card Game", "Card Battler", "Deckbuilding", "Roguelike Deckbuilder"},
    "动作 / 平台": {"Platformer", "2D Platformer", "Precision Platformer", "Action"},
    "放置 / 增量": {"Idler", "Clicker", "Incremental", "Automation"},
}


def esc(value):
    return escape(str(value if value is not None else ""), quote=True)


def numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def number(value, decimal=False):
    if not numeric(value):
        return "—"
    return f"{value:,.1f}" if decimal else f"{value:,.0f}"


def safe_url(value):
    try:
        parsed = urlparse(str(value or ""))
        return str(value) if parsed.scheme in {"http", "https"} and parsed.netloc else ""
    except ValueError:
        return ""


def timestamp(value):
    return str(value or "尚未取得").replace("T", " ").replace("+08:00", "")[:19]


def day(value):
    try:
        if "T" in str(value):
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return None
            return parsed.astimezone(TZ).date().isoformat()
        return date.fromisoformat(str(value)).isoformat()
    except (ValueError, TypeError):
        return None


def model_game(game):
    windows = {}
    for days in PERIODS:
        item = (game.get("review_windows") or {}).get(str(days), {})
        fresh = item.get("status") == "fresh"
        count, rate = item.get("count"), item.get("positive_percent")
        windows[str(days)] = {
            "count": count if fresh and numeric(count) else None,
            "rate": rate if fresh and numeric(rate) and rate <= 100 else None,
            "status": item.get("status", "unavailable"),
            "sampled_at": item.get("sampled_at"), "start": item.get("start"), "end": item.get("end"),
        }
    return {
        "appid": game["appid"], "name": str(game.get("name") or game["appid"]),
        "tags": [str(t) for t in game.get("tags", [])], "windows": windows,
        "players": game.get("current_players") if game.get("players_status") == "fresh" and numeric(game.get("current_players")) else None,
        "players_at": game.get("players_observed_at"),
        "release_date": day(game.get("release_date")),
        "release_date_status": game.get("release_date_status"),
        "metadata_fresh": game.get("metadata_status") == "fresh",
        "coming_soon": bool(game.get("coming_soon")),
        "first_seen_at": game.get("first_seen_at"),
        "first_seen_date": day(game.get("first_seen_at")),
        "listing_basis": game.get("listing_basis"),
    }


def in_window(value, days, today):
    valid = day(value)
    return bool(valid and today - timedelta(days=days - 1) <= date.fromisoformat(valid) <= today)


def select_games(games, page, days=7, query="", style="", today=None):
    today = today or datetime.now(TZ).date()
    selected = []
    for game in games:
        if query.casefold() not in (game["name"] + " " + " ".join(game["tags"])).casefold():
            continue
        if style and not (set(game["tags"]) & PLAY_STYLES.get(style, set())):
            continue
        if page == "upcoming":
            valid = game["metadata_fresh"] and game["coming_soon"] and game["listing_basis"] == "first_observed" and in_window(game["first_seen_date"], days, today)
        elif page == "releases":
            valid = game["metadata_fresh"] and not game["coming_soon"] and game["release_date_status"] != "first_release_unverified" and in_window(game["release_date"], days, today)
        elif page == "ratings":
            window = game["windows"][str(days)]
            valid = window["count"] is not None and window["count"] >= 20 and window["rate"] is not None
        else:
            valid = game["players"] is not None
        if valid:
            selected.append(game)
    if page in {"upcoming", "releases"}:
        key = "first_seen_at" if page == "upcoming" else "release_date"
        return sorted(selected, key=lambda g: (g[key] or "", -g["appid"]), reverse=True)
    key = (lambda g: (-g["windows"][str(days)]["rate"], -g["windows"][str(days)]["count"], g["appid"])) if page == "ratings" else (lambda g: (-g["players"], g["appid"]))
    return sorted(selected, key=key)


CSS = r'''
:root{color-scheme:light;--paper:#f1ede3;--panel:#faf8f1;--ink:#292d27;--soft:#62675c;--line:#d1d0c1;--sage:#4c6152;--wash:#e6eadf;--rust:#9b493b;--serif:Georgia,"Noto Serif SC","Songti SC",SimSun,serif;--sans:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:14px/1.7 var(--sans)}a{color:inherit;text-underline-offset:4px}a:hover{color:var(--rust)}button,input,select{font:inherit}button{cursor:pointer}button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible{outline:3px solid var(--rust);outline-offset:3px}[hidden]{display:none!important}.wrap{width:min(1160px,100% - 56px);margin:auto}.skip{position:fixed;top:8px;left:8px;transform:translateY(-200%);padding:10px;background:var(--ink);color:white;z-index:10}.skip:focus{transform:none}h1,h2,h3,p{margin:0}h1,h2,h3{font-family:var(--serif)}.masthead{display:flex;justify-content:space-between;align-items:end;gap:25px;padding:32px 0 22px}.eyebrow{font-size:11px;letter-spacing:.12em;color:var(--sage);margin-bottom:7px}.masthead h1{font-size:34px;line-height:1.35}.intro{max-width:760px;color:var(--soft);font-size:13px;margin-top:9px}.stamp{text-align:right;font-size:11px;color:var(--soft);flex-shrink:0}.stamp strong{display:block;color:var(--ink);font-size:13px}.brief{padding:17px 20px;border-top:2px solid var(--sage);background:var(--wash);display:flex;gap:16px;justify-content:space-between;align-items:center;font-size:12px;color:var(--sage)}.brief b{font-size:20px;font-family:var(--serif);margin-right:6px}.brief a{white-space:nowrap}.toolbar{margin-top:27px}.toolbar-top{display:flex;justify-content:space-between;gap:20px;align-items:center;flex-wrap:wrap}.metrics,.windows{display:flex;gap:6px;flex-wrap:wrap}.metrics button,.windows button{border:1px solid var(--line);background:transparent;padding:8px 14px;border-radius:3px;color:var(--soft);font-size:13px}.metrics button[aria-pressed=true]{background:var(--sage);border-color:var(--sage);color:var(--panel)}.windows button[aria-pressed=true]{border-color:var(--sage);color:var(--sage);background:var(--wash)}.windows button:disabled{cursor:default;opacity:.45}.filters{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-top:14px}.filters label{display:flex;white-space:nowrap;min-width:0;gap:8px;align-items:center;color:var(--soft);font-size:12px}.filters input,.filters select{max-width:100%;border:1px solid var(--line);background:var(--panel);color:var(--ink);padding:8px 10px;border-radius:3px;font-size:12px}.filters input{width:220px}.filters .count{margin-left:auto;color:var(--soft);font-size:11px}.ranking-head{display:flex;justify-content:space-between;align-items:baseline;gap:15px;margin-top:23px;padding-bottom:12px;border-bottom:1px solid var(--ink)}.ranking-head h2{font-size:23px}.ranking-head p{font-size:11px;color:var(--soft)}.period-note{font-size:11px;color:var(--soft);padding:10px 0 14px;min-height:42px}.rank-list{list-style:none;margin:0;padding:0}.rank-row{display:grid;grid-template-columns:32px minmax(220px,1.8fr) repeat(4,minmax(85px,.65fr));gap:16px;align-items:center;padding:18px 0;border-top:1px solid var(--line)}.rank-row:first-child{border-top:0}.position{font:22px var(--serif);color:#818579}.rank-row:nth-child(-n+3) .position{color:var(--sage)}.game{display:grid;grid-template-columns:102px minmax(0,1fr);align-items:start;gap:13px;min-width:0}.cover{height:auto;display:block;width:102px;aspect-ratio:460/215;object-fit:cover;background:#e1e3da;border-radius:3px}.game h3{font:600 14px/1.5 var(--sans);overflow-wrap:anywhere}.game h3 a{text-decoration:none}.game .meta{font-size:10px;color:var(--soft);margin-top:4px}.game .tags{font-size:10px;color:var(--sage);margin-top:3px;overflow-wrap:anywhere}.stat{text-align:right;min-width:0}.stat dt{font-size:10px;color:var(--soft);margin:0;white-space:nowrap}.stat dd{font:21px/1.5 var(--serif);margin:3px 0 0;color:var(--soft)}.stat.selected dd{color:var(--sage);font-weight:bold}.stat.selected dt{color:var(--sage)}.stat small{display:block;font-size:9px;color:var(--soft)}dl{margin:0}.empty{padding:30px 20px;border:1px solid var(--line);background:var(--panel);color:var(--soft);font-size:13px}.methodology{margin-top:34px;border-top:1px solid var(--ink);padding-top:15px}.methodology>summary{font-size:14px;font-weight:600;cursor:pointer}.method-body{display:grid;grid-template-columns:1.2fr 1fr;gap:35px;padding:18px 0;font-size:12px;color:var(--soft)}.method-body h3{font-size:17px;color:var(--ink);margin-bottom:10px}.method-body p+p{margin-top:9px}.method-body ul{padding-left:18px;margin:0}.method-body li+li{margin-top:9px}.footer{margin-top:28px;padding:20px 0 30px;border-top:1px solid var(--line);display:flex;justify-content:space-between;gap:20px;color:var(--soft);font-size:11px}.waiting{margin-top:18px;color:var(--soft);font-size:11px}.waiting summary{cursor:pointer}.waiting ul{display:flex;flex-wrap:wrap;gap:6px 22px;padding:12px 0 0 18px}.nojs{font-size:11px;color:var(--soft);margin-top:15px}
@media(max-width:1000px){.rank-row{grid-template-columns:25px minmax(185px,1.7fr) repeat(4,minmax(70px,.65fr));gap:10px}.game{grid-template-columns:80px minmax(0,1fr);gap:10px}.cover{width:80px}.stat dd{font-size:19px}}
@media(max-width:760px){.wrap{width:calc(100% - 30px)}.masthead{display:block;padding:25px 0 18px}.masthead h1{font-size:28px}.stamp{text-align:left;margin-top:12px}.stamp strong{display:inline;margin-left:8px;font-size:11px}.intro{font-size:12px}.brief{padding:14px;font-size:11px}.brief b{font-size:18px}.toolbar{margin-top:21px}.metrics button,.windows button{font-size:12px;padding:7px 10px}.toolbar-top{gap:12px}.filters{gap:10px}.filters label{flex:1}.filters input,.filters select{min-width:0;width:100%}.filters .count{width:100%;margin-left:0}.ranking-head{margin-top:20px;display:block}.ranking-head h2{font-size:22px}.ranking-head p{margin-top:4px}.rank-row{grid-template-columns:24px repeat(4,minmax(0,1fr));gap:12px 8px;padding:17px 0}.position{align-self:start;padding-top:2px;font-size:20px}.game{grid-column:2/-1;grid-template-columns:90px minmax(0,1fr)}.cover{width:90px}.stat{grid-row:2;text-align:left}.stat:nth-of-type(1){grid-column:2}.stat:nth-of-type(2){grid-column:3}.stat:nth-of-type(3){grid-column:4}.stat:nth-of-type(4){grid-column:5}.stat dd{font-size:19px}.stat dt{font-size:9px;white-space:normal}.stat small{font-size:8px}.method-body{grid-template-columns:1fr;gap:20px}.footer{display:block}.footer a{display:inline-block;margin-top:8px}}
@media(max-width:360px){.rank-row{grid-template-columns:20px repeat(4,minmax(0,1fr));gap:10px 5px}.stat dd{font-size:17px}.metrics{gap:5px}.metrics button{font-size:11px;padding:7px 8px}.game{grid-template-columns:75px minmax(0,1fr)}.cover{width:75px}}
'''

CSS += r'''
.subnav{display:flex;gap:25px;flex-wrap:wrap;margin:0 0 22px;border-bottom:1px solid var(--line)}.subnav a{padding:9px 0 12px;text-decoration:none;color:var(--soft);border-bottom:3px solid transparent;font-size:13px}.subnav a[aria-current]{color:var(--sage);border-color:var(--sage);font-weight:bold}.rank-row{grid-template-columns:32px minmax(240px,1fr) minmax(160px,.45fr)}.rank-row.stats2{grid-template-columns:32px minmax(240px,1fr) repeat(2,minmax(120px,.35fr))}.stat dd.date-value{font-size:17px}.baseline{margin-top:27px;border-top:1px solid var(--line);padding-top:15px}.baseline>summary{cursor:pointer;font-family:var(--serif);font-size:21px;font-weight:bold}.baseline-note{font-size:12px;color:var(--soft);margin:10px 0 6px}.baseline .rank-row{opacity:.9}.status-note{margin-top:10px;color:var(--rust);font-size:11px}.toolbar-top>p{font-size:12px;color:var(--soft)}
@media(max-width:760px){.subnav{gap:14px 20px}.subnav a{font-size:12px}.rank-row,.rank-row.stats2{grid-template-columns:24px repeat(2,minmax(0,1fr))}.game{grid-column:2/-1}.stat:nth-of-type(1){grid-column:2}.stat:nth-of-type(2){grid-column:3}.stat dd.date-value{font-size:16px}.baseline>summary{font-size:19px}.brief{align-items:start}.brief a{white-space:normal}}
'''

SCRIPT = r'''
(() => {
 const data=JSON.parse(document.getElementById('ranking-data').textContent);
 const games=data.games, styles=data.styles, page=data.page, list=document.getElementById('rank-list');
 const rows=new Map([...list.children].map(row=>[Number(row.dataset.appid),row]));
 const params=new URLSearchParams(location.search);
 let days=['1','7','30'].includes(params.get('days'))?params.get('days'):'7';
 const query=document.getElementById('game-search'),style=document.getElementById('play-style');
 const fmt=n=>n===null?'—':Number(n).toLocaleString('zh-CN');
 function inWindow(date){return date!==null&&date>=data.cutoffs[days]&&date<=data.today;}
 function eligible(g){
  if(page==='upcoming')return g.metadata_fresh&&g.coming_soon&&g.listing_basis==='first_observed'&&inWindow(g.first_seen_date);
  if(page==='releases')return g.metadata_fresh&&!g.coming_soon&&g.release_date_status!=='first_release_unverified'&&inWindow(g.release_date);
  if(page==='ratings'){const w=g.windows[days];return w.count!==null&&w.count>=20&&w.rate!==null;}
  return g.players!==null;
 }
 function compare(a,b){
  if(page==='upcoming')return String(b.first_seen_at).localeCompare(String(a.first_seen_at))||a.appid-b.appid;
  if(page==='releases')return b.release_date.localeCompare(a.release_date)||a.appid-b.appid;
  if(page==='ratings')return b.windows[days].rate-a.windows[days].rate||b.windows[days].count-a.windows[days].count||a.appid-b.appid;
  return b.players-a.players||a.appid-b.appid;
 }
 function apply(){
  const matching=games.filter(g=>(g.name+' '+g.tags.join(' ')).toLowerCase().includes(query.value.trim().toLowerCase())&&(!style.value||g.tags.some(t=>styles[style.value].includes(t))));
  if(page==='upcoming'){
   const baseline=matching.filter(g=>g.metadata_fresh&&g.coming_soon&&g.listing_basis==='baseline');
   const pool=document.getElementById('baseline');
   if(pool){const visible=new Set(baseline.map(g=>g.appid));pool.querySelectorAll('[data-appid]').forEach(r=>r.hidden=!visible.has(Number(r.dataset.appid)));document.getElementById('baseline-title').textContent='已建立观察池 · '+baseline.length+' 款符合筛选的基线作品';document.getElementById('baseline-empty').hidden=baseline.length>0;}
  }
  const selected=matching.filter(eligible).sort(compare);
  rows.forEach(row=>row.hidden=true);
  selected.forEach((g,index)=>{
   const row=rows.get(g.appid);row.hidden=false;list.append(row);row.querySelector('.position').textContent=String(index+1).padStart(2,'0');
   if(page==='ratings'){
    const w=g.windows[days];row.querySelector('[data-value=count]').textContent=fmt(w.count);
    row.querySelector('[data-value=rate]').textContent=w.rate.toFixed(1)+'%';
    row.querySelector('[data-label=count]').textContent='近 '+days+' 天评价';row.querySelector('[data-label=rate]').textContent='近 '+days+' 天好评率';
    row.querySelectorAll('[data-stat]').forEach(s=>s.title=w.sampled_at?'采集时间：'+w.sampled_at:'尚未取得');
   }
  });
  document.querySelectorAll('[data-days]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.days===days)));
  const titles={upcoming:'首次发现的待发售游戏',releases:'发售游戏',ratings:'好评率排行',online:'当前在线排行'};
  document.getElementById('ranking-title').textContent=(page==='online'?'':'近 '+days+' 天 · ')+titles[page];
  document.getElementById('result-count').textContent=selected.length+' 款符合当前条件';
  document.getElementById('empty-state').hidden=selected.length>0;
  const note=page==='upcoming'?'按本站首次发现日期筛选（北京时间，截至本期采集日的 '+days+' 个自然日）。初次建池作品不计入新增。':page==='releases'?'按 Steam 发售日期筛选（北京时间，截至本期采集日的 '+days+' 个自然日），发售日期由近到远排列。':page==='ratings'?'统计采集时点向前 '+days+' × 24 小时的评价；至少 20 条评价参与排名，同好评率时评价较多者在前。':'按最近成功采样时的同时在线人数排序；不含离线游玩，不代表下载量。';
  document.getElementById('period-note').textContent=note;
  if(page==='ratings'||page==='online'){
   const pending=matching.filter(g=>!eligible(g)),waiting=document.getElementById('waiting');waiting.hidden=!pending.length;
   document.getElementById('waiting-title').textContent=pending.length+' 款未参与当前排名（未取得新数据或未达到评价门槛）';
   const pendingList=document.getElementById('waiting-games');pendingList.replaceChildren();pending.forEach(g=>{const li=document.createElement('li'),a=document.createElement('a');a.href='https://store.steampowered.com/app/'+g.appid+'/';a.textContent=g.name;a.target='_blank';a.rel='noopener noreferrer';li.append(a);pendingList.append(li);});
  }
  const url=new URL(location.href);url.searchParams.delete('metric');if(page!=='online')url.searchParams.set('days',days);else url.searchParams.delete('days');try{history.replaceState(null,'',url.pathname+url.search+url.hash);}catch(_){}
 }
 document.querySelectorAll('[data-days]').forEach(b=>b.addEventListener('click',()=>{days=b.dataset.days;apply();}));
 query.addEventListener('input',apply);style.addEventListener('change',apply);
 document.querySelectorAll('img').forEach(img=>img.addEventListener('error',()=>{img.style.visibility='hidden';}));
 document.getElementById('controls').hidden=false;apply();
})();
'''


def render_row(game, model, page, position=None, baseline=False):
    appid = int(game['appid'])
    image = safe_url(game.get('header_image'))
    cover = f'<img class="cover" src="{esc(image)}" alt="" width="460" height="215" loading="lazy">' if image else '<div class="cover" aria-hidden="true"></div>'
    price = game.get('price', {})
    price = price.get('formatted', '价格未公布') if isinstance(price, dict) else '价格未公布'
    label = game.get('release_label') or game.get('release_date') or '发售时间待定'
    details = []
    if page == 'ratings':
        w = model['windows']['7']
        details = [('rate', '近 7 天好评率', number(w['rate'], True) + '%' if w['rate'] is not None else '—', w['sampled_at'], '期间评价', True),
                   ('count', '近 7 天评价', number(w['count']), w['sampled_at'], '条 · 至少 20 条入榜', False)]
    elif page == 'online':
        details = [('players', '当前在线', number(model['players']), model['players_at'], '人 · 采集快照', True)]
    elif page == 'releases':
        details = [('released', 'Steam 发售日期', model['release_date'] or '待核实', None, '北京时间日期', True)]
    elif baseline:
        details = [('baseline', '预计发售', str(label), None, '观察池基线 · 非本期新增', False)]
    else:
        details = [('discovered', '本站首次发现', model['first_seen_date'] or '尚未记录', model['first_seen_at'], '观察日期 · 非官方上架日', True)]
    stats = []
    for key, title, value, at, suffix, selected in details:
        stats.append(f'<dl class="stat{" selected" if selected else ""}" data-stat="{key}" title="{esc("采集 / 观察时间：" + timestamp(at) if at else title)}"><dt data-label="{key}">{title}</dt><dd class="{"date-value" if page in {"upcoming", "releases"} else ""}" data-value="{key}">{esc(value)}</dd><small>{suffix}</small></dl>')
    release_text = f'预计发售：{label}' if page == 'upcoming' else f'发售：{game.get("release_date") or "未取得"}'
    return (f'<li class="rank-row{" stats2" if page == "ratings" else ""}" data-appid="{appid}"' + ('' if position or baseline else ' hidden') + f'><span class="position">{str(position).zfill(2) if position else "—"}</span>'
            f'<div class="game">{cover}<div><h3><a href="https://store.steampowered.com/app/{appid}/" target="_blank" rel="noopener noreferrer">{esc(model["name"])}</a></h3>'
            f'<p class="meta">{esc(price)} · 美区价格<br>{esc(release_text)}</p><p class="tags">{esc(" / ".join(model["tags"][:3]))}</p></div></div>' + ''.join(stats) + '</li>')


def valid_games(raw):
    return list({g['appid']: g for g in raw if isinstance(g, dict) and isinstance(g.get('appid'), int) and not isinstance(g.get('appid'), bool) and g['appid'] > 0}.values())


def render_indie_market(data, discovery=None, page='upcoming'):
    if page not in PAGES:
        raise ValueError('Unknown indie page')
    discovery = discovery or {}
    source_data = discovery if page in {'upcoming', 'releases'} else data
    key = 'upcoming_games' if page == 'upcoming' else 'release_games' if page == 'releases' else 'games'
    games = valid_games(source_data.get(key, []))
    models = [model_game(g) for g in games]
    by_id = {g['appid']: g for g in games}
    anchor = day(source_data.get('generated_at'))
    today = date.fromisoformat(anchor) if anchor else datetime.now(TZ).date()
    selected = select_games(models, page, today=today)
    positions = {g['appid']: i + 1 for i, g in enumerate(selected)}
    ordered = selected + [g for g in models if g['appid'] not in positions]
    rows = ''.join(render_row(by_id[g['appid']], g, page, positions.get(g['appid'])) for g in ordered)
    payload = json.dumps({'games': models, 'styles': {k: sorted(v) for k, v in PLAY_STYLES.items()}, 'page': page, 'today': today.isoformat(), 'cutoffs': {str(n): (today-timedelta(days=n-1)).isoformat() for n in PERIODS}}, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    title = PAGES[page][1]
    descriptions = {
        'upcoming': '关注刚进入观察范围、尚未发售的独立游戏。',
        'releases': '按发售时间寻找近期已经推出的独立游戏。',
        'ratings': '比较近期玩家评价；至少 20 条评价的作品参与排名。',
        'online': '比较采集时的同时在线人数，观察作品的活跃规模。',
    }
    limits = {
        'upcoming': 'Steam 未提供可核实的商店上架日；这里按本站首次发现记录新增待发售作品。首次快照作为基线，不计作当天新增。',
        'releases': '近 1 / 7 / 30 天筛选的是发售日期；未发售作品不列入，首次发售日期未核实的抢先体验转正式版作品暂不列入。',
        'ratings': '近 1 / 7 / 30 天筛选评价时间。好评率与评价数均不代表销量或下载量。',
        'online': '这是采集快照，展示的时间为数据取得时间；在线人数不代表售出份数或下载次数。',
    }
    notes = {
        'upcoming': '按本站首次发现日期筛选（北京时间，截至本期采集日的 7 个自然日）。初次建池作品不计入新增。',
        'releases': '按 Steam 发售日期筛选（北京时间，截至本期采集日的 7 个自然日），发售日期由近到远排列。',
        'ratings': '统计采集时点向前 7 × 24 小时的评价；至少 20 条评价参与排名，同好评率时评价较多者在前。',
        'online': '按最近成功采样时的同时在线人数排序；不含离线游玩，不代表下载量。',
    }
    subnav = '<nav class="subnav" aria-label="小游戏栏目">' + ''.join(f'<a href="{filename}"' + (' aria-current="page"' if k == page else '') + f'>{label}</a>' for k, (filename, label) in PAGES.items()) + '</nav>'
    scope = source_data.get('scope_note') or 'Steam 独立游戏候选样本，受入口与玩法标签限制，不是 Steam 全库。小体量为筛选线索，未核验团队规模与制作预算。'
    methodology = source_data.get('methodology') or []
    method = ''.join(f'<li>{esc(item)}</li>' for item in methodology)
    sources = ''.join(f'<li><a href="{esc(safe_url(s.get("url")))}" target="_blank" rel="noopener noreferrer">{esc(s.get("name"))}</a><br>{esc(s.get("note", ""))}</li>' for s in source_data.get('sources', []) if isinstance(s, dict) and safe_url(s.get('url')))
    style_options = ''.join(f'<option value="{esc(k)}">{esc(k)}</option>' for k in PLAY_STYLES)
    windows = '' if page == 'online' else '<div class="windows" role="group" aria-label="时间范围">' + ''.join(f'<button type="button" data-days="{n}" aria-pressed="{"true" if n == 7 else "false"}">近 {n} 天</button>' for n in PERIODS) + '</div>'
    window_label = '在线快照 · 按人数排序' if page == 'online' else '按首次发现时间筛选' if page == 'upcoming' else '按发售时间筛选' if page == 'releases' else '按评价时间筛选'
    ranking_title = '当前在线排行' if page == 'online' else '近 7 天 · ' + {'upcoming': '首次发现的待发售游戏', 'releases': '发售游戏', 'ratings': '好评率排行'}[page]
    empty = '本筛选范围尚未记录到新增待发售作品。初次建池作品会单独显示为基线，不计作新增。' if page == 'upcoming' else '本筛选暂无符合条件的作品。可调整时间范围或玩法筛选。'
    baseline_html = ''
    if page == 'upcoming':
        baseline = [g for g in models if g['metadata_fresh'] and g['listing_basis'] == 'baseline' and g['coming_soon']]
        baseline_rows = ''.join(render_row(by_id[g['appid']], g, page, i + 1, True) for i, g in enumerate(baseline))
        baseline_html = f'<details class="baseline" id="baseline" open><summary id="baseline-title">已建立观察池 · {len(baseline)} 款基线作品</summary><p class="baseline-note">建池时间：{esc(timestamp(discovery.get("initialized_at")))}。这些作品在首次采集时已经存在，无法据此确认上架日期；此处支持名称与玩法筛选，不受上方 1 / 7 / 30 天筛选影响。</p><ol class="rank-list">{baseline_rows}</ol><p class="empty" id="baseline-empty" hidden>观察池内暂无符合名称或玩法筛选的作品。</p></details>' if baseline else ''
    pending = [g for g in models if g['appid'] not in positions] if page in {'ratings', 'online'} else []
    waiting = '<details class="waiting" id="waiting"' + ('' if pending else ' hidden') + f'><summary id="waiting-title">{len(pending)} 款未参与当前排名</summary><ul id="waiting-games">' + ''.join(f'<li><a href="https://store.steampowered.com/app/{g["appid"]}/">{esc(g["name"])}</a></li>' for g in pending) + '</ul></details>' if page in {'ratings', 'online'} else ''
    status_note = '<p class="status-note">本轮数据未全部更新，请结合采集时间查看；缺失数据不补为零。</p>' if source_data.get('status') not in (None, 'fresh') else ''
    return f'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)} · 小游戏榜 · 策划日报</title><meta name="description" content="{esc(descriptions[page])}"><style>{CSS}{SITE_NAV_CSS}</style></head><body><a class="skip" href="#rankings">跳转到列表</a><div class="wrap">{render_site_navigation('indie')}<main><header class="masthead"><div><p class="eyebrow">STEAM · INDIE WATCH</p><h1>{esc(title)}</h1><p class="intro">{esc(descriptions[page])}</p><p class="intro">{esc(limits[page])}</p></div><p class="stamp">本期采集 · 北京时间<strong>{esc(timestamp(source_data.get('generated_at')))}</strong></p></header>{subnav}<div class="brief"><span><b>{len(games)}</b>款候选 · {window_label}</span><a href="#methodology">范围与口径 ↓</a></div>{status_note}<section id="rankings" aria-labelledby="ranking-title"><div id="controls" class="toolbar" hidden><div class="toolbar-top"><p>{window_label}</p>{windows}</div><div class="filters"><label>搜索<input id="game-search" type="search" placeholder="游戏名称 / 标签" autocomplete="off"></label><label>玩法<select id="play-style"><option value="">全部玩法</option>{style_options}</select></label><p class="count" id="result-count" aria-live="polite">{len(selected)} 款符合当前条件</p></div></div><div class="ranking-head"><h2 id="ranking-title">{ranking_title}</h2><p>候选样本内比较 · 点击游戏前往 Steam</p></div><p class="period-note" id="period-note">{notes[page]}</p><ol class="rank-list" id="rank-list">{rows}</ol><div class="empty" id="empty-state"{(' hidden' if selected else '')}>{empty}</div>{waiting}<noscript><p class="nojs">当前展示默认列表。启用 JavaScript 可使用时间与玩法筛选。</p></noscript></section>{baseline_html}<details class="methodology" id="methodology"><summary>样本范围、数据口径与来源</summary><div class="method-body"><div><h3>如何读这张列表</h3><p>{esc(scope)}</p><p>{esc(limits[page])}</p><p>{notes[page]}</p><p>Steam 不公开单款销量与下载次数。缺失或旧的评价、在线数据不参与排名；真实的 0 人在线会如实显示。候选受发现入口与筛选规则限制，不是 Steam 全库排名。</p><ul>{method}</ul></div><div><h3>数据来源</h3><ul>{sources or '<li>Steam 商店公开数据；本期尚未取得来源记录。</li>'}</ul></div></div></details></main><footer class="footer"><span>策划日报 · 小体量独立游戏观察</span><a href="market.html">查看 Steam 全局市场 →</a></footer></div><script type="application/json" id="ranking-data">{payload}</script><script>{SCRIPT}</script></body></html>'''


def render_indie_pages(data, discovery=None):
    return {filename: render_indie_market(data, discovery, page) for page, (filename, _) in PAGES.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=ROOT / 'data/indie_market.json')
    parser.add_argument('--discovery', type=Path, default=ROOT / 'data/indie_discovery.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/indie.html')
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding='utf-8')) if args.input.exists() else {}
    discovery = json.loads(args.discovery.read_text(encoding='utf-8')) if args.discovery.exists() else {}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for filename, content in render_indie_pages(data, discovery).items():
        target = args.output if filename == 'indie.html' else args.output.with_name(filename)
        target.write_text(content, encoding='utf-8')
    print(f'Rendered 4 indie pages to {args.output.parent}')


if __name__ == '__main__':
    main()
