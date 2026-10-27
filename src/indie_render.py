"""Render measured Steam indie rankings with explicit time and sample scope."""
from __future__ import annotations

import argparse
from html import escape
import json
from pathlib import Path
from urllib.parse import urlparse

from site_navigation import SITE_NAV_CSS, render_site_navigation

ROOT = Path(__file__).resolve().parents[1]
PERIODS = (1, 7, 30)
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


def number(value, decimal=False):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
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


def numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0


def model_game(game):
    windows = {}
    for days in PERIODS:
        item = (game.get("review_windows") or {}).get(str(days), {})
        fresh = item.get("status") == "fresh"
        count = item.get("count")
        rate = item.get("positive_percent")
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
        "rank": game.get("indie_top_sellers_rank") if game.get("indie_top_sellers_status") == "fresh" and numeric(game.get("indie_top_sellers_rank")) and game["indie_top_sellers_rank"] > 0 else None,
        "players_at": game.get("players_observed_at"), "rank_at": game.get("indie_top_sellers_observed_at"),
    }


def metric_value(game, metric, days):
    if metric in {"players", "rank"}:
        return game.get(metric)
    window = game["windows"][str(days)]
    if metric == "rate":
        return window["rate"] if window["count"] is not None and window["count"] >= 20 else None
    return window["count"]


def rank_games(games, metric="count", days=7, query="", style=""):
    selected = []
    for game in games:
        if query.casefold() not in (game["name"] + " " + " ".join(game["tags"])).casefold():
            continue
        if style and not (set(game["tags"]) & PLAY_STYLES.get(style, set())):
            continue
        value = metric_value(game, metric, days)
        if value is not None:
            selected.append(game)
    return sorted(selected, key=lambda g: (metric_value(g, metric, days) if metric == "rank" else -metric_value(g, metric, days), g["appid"]))


CSS = r'''
:root{color-scheme:light;--paper:#f1ede3;--panel:#faf8f1;--ink:#292d27;--soft:#62675c;--line:#d1d0c1;--sage:#4c6152;--wash:#e6eadf;--rust:#9b493b;--serif:Georgia,"Noto Serif SC","Songti SC",SimSun,serif;--sans:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:14px/1.7 var(--sans)}a{color:inherit;text-underline-offset:4px}a:hover{color:var(--rust)}button,input,select{font:inherit}button{cursor:pointer}button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible{outline:3px solid var(--rust);outline-offset:3px}[hidden]{display:none!important}.wrap{width:min(1160px,100% - 56px);margin:auto}.skip{position:fixed;top:8px;left:8px;transform:translateY(-200%);padding:10px;background:var(--ink);color:white;z-index:10}.skip:focus{transform:none}h1,h2,h3,p{margin:0}h1,h2,h3{font-family:var(--serif)}.masthead{display:flex;justify-content:space-between;align-items:end;gap:25px;padding:32px 0 22px}.eyebrow{font-size:11px;letter-spacing:.12em;color:var(--sage);margin-bottom:7px}.masthead h1{font-size:34px;line-height:1.35}.intro{max-width:760px;color:var(--soft);font-size:13px;margin-top:9px}.stamp{text-align:right;font-size:11px;color:var(--soft);flex-shrink:0}.stamp strong{display:block;color:var(--ink);font-size:13px}.brief{padding:17px 20px;border-top:2px solid var(--sage);background:var(--wash);display:flex;gap:16px;justify-content:space-between;align-items:center;font-size:12px;color:var(--sage)}.brief b{font-size:20px;font-family:var(--serif);margin-right:6px}.brief a{white-space:nowrap}.toolbar{margin-top:27px}.toolbar-top{display:flex;justify-content:space-between;gap:20px;align-items:center;flex-wrap:wrap}.metrics,.windows{display:flex;gap:6px;flex-wrap:wrap}.metrics button,.windows button{border:1px solid var(--line);background:transparent;padding:8px 14px;border-radius:3px;color:var(--soft);font-size:13px}.metrics button[aria-pressed=true]{background:var(--sage);border-color:var(--sage);color:var(--panel)}.windows button[aria-pressed=true]{border-color:var(--sage);color:var(--sage);background:var(--wash)}.windows button:disabled{cursor:default;opacity:.45}.filters{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-top:14px}.filters label{display:flex;white-space:nowrap;min-width:0;gap:8px;align-items:center;color:var(--soft);font-size:12px}.filters input,.filters select{max-width:100%;border:1px solid var(--line);background:var(--panel);color:var(--ink);padding:8px 10px;border-radius:3px;font-size:12px}.filters input{width:220px}.filters .count{margin-left:auto;color:var(--soft);font-size:11px}.ranking-head{display:flex;justify-content:space-between;align-items:baseline;gap:15px;margin-top:23px;padding-bottom:12px;border-bottom:1px solid var(--ink)}.ranking-head h2{font-size:23px}.ranking-head p{font-size:11px;color:var(--soft)}.period-note{font-size:11px;color:var(--soft);padding:10px 0 14px;min-height:42px}.rank-list{list-style:none;margin:0;padding:0}.rank-row{display:grid;grid-template-columns:32px minmax(220px,1.8fr) repeat(4,minmax(85px,.65fr));gap:16px;align-items:center;padding:18px 0;border-top:1px solid var(--line)}.rank-row:first-child{border-top:0}.position{font:22px var(--serif);color:#818579}.rank-row:nth-child(-n+3) .position{color:var(--sage)}.game{display:grid;grid-template-columns:102px minmax(0,1fr);align-items:start;gap:13px;min-width:0}.cover{height:auto;display:block;width:102px;aspect-ratio:460/215;object-fit:cover;background:#e1e3da;border-radius:3px}.game h3{font:600 14px/1.5 var(--sans);overflow-wrap:anywhere}.game h3 a{text-decoration:none}.game .meta{font-size:10px;color:var(--soft);margin-top:4px}.game .tags{font-size:10px;color:var(--sage);margin-top:3px;overflow-wrap:anywhere}.stat{text-align:right;min-width:0}.stat dt{font-size:10px;color:var(--soft);margin:0;white-space:nowrap}.stat dd{font:21px/1.5 var(--serif);margin:3px 0 0;color:var(--soft)}.stat.selected dd{color:var(--sage);font-weight:bold}.stat.selected dt{color:var(--sage)}.stat small{display:block;font-size:9px;color:var(--soft)}dl{margin:0}.empty{padding:30px 20px;border:1px solid var(--line);background:var(--panel);color:var(--soft);font-size:13px}.methodology{margin-top:34px;border-top:1px solid var(--ink);padding-top:15px}.methodology>summary{font-size:14px;font-weight:600;cursor:pointer}.method-body{display:grid;grid-template-columns:1.2fr 1fr;gap:35px;padding:18px 0;font-size:12px;color:var(--soft)}.method-body h3{font-size:17px;color:var(--ink);margin-bottom:10px}.method-body p+p{margin-top:9px}.method-body ul{padding-left:18px;margin:0}.method-body li+li{margin-top:9px}.footer{margin-top:28px;padding:20px 0 30px;border-top:1px solid var(--line);display:flex;justify-content:space-between;gap:20px;color:var(--soft);font-size:11px}.waiting{margin-top:18px;color:var(--soft);font-size:11px}.waiting summary{cursor:pointer}.waiting ul{display:flex;flex-wrap:wrap;gap:6px 22px;padding:12px 0 0 18px}.nojs{font-size:11px;color:var(--soft);margin-top:15px}
@media(max-width:1000px){.rank-row{grid-template-columns:25px minmax(185px,1.7fr) repeat(4,minmax(70px,.65fr));gap:10px}.game{grid-template-columns:80px minmax(0,1fr);gap:10px}.cover{width:80px}.stat dd{font-size:19px}}
@media(max-width:760px){.wrap{width:calc(100% - 30px)}.masthead{display:block;padding:25px 0 18px}.masthead h1{font-size:28px}.stamp{text-align:left;margin-top:12px}.stamp strong{display:inline;margin-left:8px;font-size:11px}.intro{font-size:12px}.brief{padding:14px;font-size:11px}.brief b{font-size:18px}.toolbar{margin-top:21px}.metrics button,.windows button{font-size:12px;padding:7px 10px}.toolbar-top{gap:12px}.filters{gap:10px}.filters label{flex:1}.filters input,.filters select{min-width:0;width:100%}.filters .count{width:100%;margin-left:0}.ranking-head{margin-top:20px;display:block}.ranking-head h2{font-size:22px}.ranking-head p{margin-top:4px}.rank-row{grid-template-columns:24px repeat(4,minmax(0,1fr));gap:12px 8px;padding:17px 0}.position{align-self:start;padding-top:2px;font-size:20px}.game{grid-column:2/-1;grid-template-columns:90px minmax(0,1fr)}.cover{width:90px}.stat{grid-row:2;text-align:left}.stat:nth-of-type(1){grid-column:2}.stat:nth-of-type(2){grid-column:3}.stat:nth-of-type(3){grid-column:4}.stat:nth-of-type(4){grid-column:5}.stat dd{font-size:19px}.stat dt{font-size:9px;white-space:normal}.stat small{font-size:8px}.method-body{grid-template-columns:1fr;gap:20px}.footer{display:block}.footer a{display:inline-block;margin-top:8px}}
@media(max-width:360px){.rank-row{grid-template-columns:20px repeat(4,minmax(0,1fr));gap:10px 5px}.stat dd{font-size:17px}.metrics{gap:5px}.metrics button{font-size:11px;padding:7px 8px}.game{grid-template-columns:75px minmax(0,1fr)}.cover{width:75px}}
'''


SCRIPT = r'''
(() => {
 const data=JSON.parse(document.getElementById('ranking-data').textContent);
 const games=data.games, styles=data.styles, list=document.getElementById('rank-list');
 const rows=new Map([...list.children].map(row=>[Number(row.dataset.appid),row]));
 const params=new URLSearchParams(location.search);
 let metric=['count','rate','players','rank'].includes(params.get('metric'))?params.get('metric'):'count';
 let days=['1','7','30'].includes(params.get('days'))?params.get('days'):'7';
 const query=document.getElementById('game-search'), style=document.getElementById('play-style');
 const labels={count:'新增评价排行',rate:'期间好评率排行',players:'当前在线排行',rank:'独立热销顺位'};
 function value(g){const w=g.windows[days];return metric==='count'?w.count:metric==='rate'?(w.count!==null&&w.count>=20?w.rate:null):g[metric];}
 const fmt=n=>n===null?'—':Number(n).toLocaleString('zh-CN');
 function apply(){
  const snapshot=metric==='players'||metric==='rank';
  const matching=games.filter(g=>(g.name+' '+g.tags.join(' ')).toLowerCase().includes(query.value.trim().toLowerCase())&&(!style.value||g.tags.some(t=>styles[style.value].includes(t))));
  const valid=matching.filter(g=>value(g)!==null).sort((a,b)=>(metric==='rank'?value(a)-value(b):value(b)-value(a))||a.appid-b.appid);
  rows.forEach(row=>row.hidden=true);
  valid.forEach((g,index)=>{
   const row=rows.get(g.appid),w=g.windows[days];row.hidden=false;list.append(row);
   row.querySelector('.position').textContent=String(index+1).padStart(2,'0');
   row.querySelector('[data-value=count]').textContent=fmt(w.count);
   row.querySelector('[data-value=rate]').textContent=w.rate===null?'—':w.rate.toFixed(1)+'%';
   row.querySelector('[data-label=count]').textContent='近 '+days+' 天评价';
   row.querySelector('[data-label=rate]').textContent='近 '+days+' 天好评率';
   row.querySelectorAll('[data-stat]').forEach(s=>s.classList.toggle('selected',s.dataset.stat===metric));
   row.querySelector('[data-stat=count]').title=w.sampled_at?'采集时间：'+w.sampled_at:'数据未取得';
   row.querySelector('[data-stat=rate]').title=w.sampled_at?'采集时间：'+w.sampled_at:'数据未取得';
  });
  document.querySelectorAll('[data-metric]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.metric===metric)));
  document.querySelectorAll('[data-days]').forEach(b=>{b.setAttribute('aria-pressed',String(b.dataset.days===days));b.disabled=snapshot;});
  document.getElementById('ranking-title').textContent=(snapshot?'当前':'近 '+days+' 天')+' · '+labels[metric];
  document.getElementById('result-count').textContent=valid.length+' 款参与排名 / '+matching.length+' 款符合筛选';
  document.getElementById('empty-state').hidden=valid.length>0;
  document.getElementById('period-note').textContent=snapshot?(metric==='rank'?'美国区 Indie 搜索热销入口的原始顺位；只比较已取得本轮顺位的候选，时间按钮不适用于这一快照。':'采集时同时在线的人数，不含离线游玩；时间按钮不适用于这一快照。'):'从采集时点向前 '+days+' × 24 小时，按评论创建时间统计。'+(metric==='rate'?'仅至少 20 条评价的作品参与好评率排名。':'评价量反映讨论活跃度，不等于售出份数或下载次数。');
  const pending=matching.filter(g=>value(g)===null);const waiting=document.getElementById('waiting');waiting.hidden=!pending.length;
  document.getElementById('waiting-title').textContent=pending.length+' 款未参与当前排名（数据未取得、旧值或未达到评价门槛）';
  const pendingList=document.getElementById('waiting-games');pendingList.replaceChildren();pending.forEach(g=>{const li=document.createElement('li'),a=document.createElement('a');a.href='https://store.steampowered.com/app/'+g.appid+'/';a.textContent=g.name;a.target='_blank';a.rel='noopener noreferrer';li.append(a);pendingList.append(li);});
  const url=new URL(location.href);url.searchParams.set('days',days);url.searchParams.set('metric',metric);try{history.replaceState(null,'',url.pathname+url.search+url.hash);}catch(_){}
 }
 document.querySelectorAll('[data-metric]').forEach(b=>b.addEventListener('click',()=>{metric=b.dataset.metric;apply();}));
 document.querySelectorAll('[data-days]').forEach(b=>b.addEventListener('click',()=>{days=b.dataset.days;apply();}));
 query.addEventListener('input',apply);style.addEventListener('change',apply);
 document.querySelectorAll('img').forEach(img=>img.addEventListener('error',()=>{img.style.visibility='hidden';}));
 document.getElementById('controls').hidden=false;apply();
})();
'''


def render_row(game, model, position=None):
    appid = int(game["appid"])
    image = safe_url(game.get("header_image"))
    cover = f'<img class="cover" src="{esc(image)}" alt="" width="460" height="215" loading="lazy">' if image else '<div class="cover" aria-hidden="true"></div>'
    window = model["windows"]["7"]
    price = game.get("price", {})
    price = price.get("formatted", "价格未取得") if isinstance(price, dict) else "价格未取得"
    global_rank = game.get("top_sellers_rank") if game.get("top_sellers_status") == "fresh" else None
    global_note = f' · 全球热销 #{number(global_rank)}' if numeric(global_rank) and global_rank > 0 else ''
    stats = []
    for key, label, value, at, suffix in (
        ("count", "近 7 天评价", window["count"], window["sampled_at"], "条"),
        ("rate", "近 7 天好评率", window["rate"], window["sampled_at"], "期间评价"),
        ("players", "当前在线", model["players"], model["players_at"], "人 · 采集快照"),
        ("rank", "独立热销顺位", model["rank"], model["rank_at"], "美国区 · 原榜位次"),
    ):
        shown = (number(value, True) + "%") if key == "rate" and value is not None else ("#" + number(value)) if key == "rank" and value is not None else number(value)
        stats.append(f'<dl class="stat{" selected" if key == "count" else ""}" data-stat="{key}" title="采集时间：{esc(timestamp(at))}"><dt data-label="{key}">{label}</dt><dd data-value="{key}">{shown}</dd><small>{suffix}</small></dl>')
    return (
        f'<li class="rank-row" data-appid="{appid}"' + ('' if position else ' hidden') + f'><span class="position">{str(position).zfill(2) if position else "—"}</span>'
        f'<div class="game">{cover}<div><h3><a href="https://store.steampowered.com/app/{appid}/" target="_blank" rel="noopener noreferrer">{esc(model["name"])}</a></h3>'
        f'<p class="meta">{esc(price)} · 美区价格<br>{esc(game.get("release_date") or "发售日期未取得")}{esc(global_note)}</p><p class="tags">{esc(" / ".join(model["tags"][:3]))}</p></div></div>' + ''.join(stats) + '</li>'
    )


def render_indie_market(data):
    games = [g for g in data.get("games", []) if isinstance(g, dict) and isinstance(g.get("appid"), int) and not isinstance(g.get("appid"), bool) and g["appid"] > 0]
    models = [model_game(g) for g in games]
    by_id = {g["appid"]: g for g in games}
    ranked = rank_games(models)
    positions = {g["appid"]: i + 1 for i, g in enumerate(ranked)}
    ordered = ranked + [g for g in models if g["appid"] not in positions]
    rows = ''.join(render_row(by_id[g["appid"]], g, positions.get(g["appid"])) for g in ordered)
    payload = json.dumps({"games": models, "styles": {k: sorted(v) for k, v in PLAY_STYLES.items()}}, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    scope = data.get("scope_note") or "Indie 标签 + 适合紧凑玩法的标签 + 美区原价不高于 25 美元；这是候选筛选，不代表已核验开发团队规模与制作预算。"
    methodology = data.get("methodology") or []
    method = ''.join(f'<li>{esc(item)}</li>' for item in methodology)
    sources = ''.join(f'<li><a href="{esc(safe_url(s.get("url")))}" target="_blank" rel="noopener noreferrer">{esc(s.get("name"))}</a><br>{esc(s.get("note", ""))}</li>' for s in data.get("sources", []) if isinstance(s, dict) and safe_url(s.get("url")))
    style_options = ''.join(f'<option value="{esc(k)}">{esc(k)}</option>' for k in PLAY_STYLES)
    pending = [g for g in models if g["appid"] not in positions]
    pending_html = ''.join(f'<li><a href="https://store.steampowered.com/app/{g["appid"]}/">{esc(g["name"])}</a></li>' for g in pending)
    return f'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>小游戏榜 · 策划日报</title><meta name="description" content="Steam 小体量独立游戏候选榜：近1、7、30天新增评价、好评率、当前在线和独立热销顺位。"><style>{CSS}{SITE_NAV_CSS}</style></head><body><a class="skip" href="#rankings">跳转到榜单</a><div class="wrap">{render_site_navigation('indie')}<main><header class="masthead"><div><p class="eyebrow">STEAM · INDIE WATCH</p><h1>小游戏榜</h1><p class="intro">发现值得研究的小体量独立游戏。按近期评价、在线人数与热销顺位比较表现。</p><p class="intro">Steam 不公开单款销量与下载次数；这里保留真实指标，不把评价或在线人数换算成销量。</p></div><p class="stamp">本期采集 · 北京时间<strong>{esc(timestamp(data.get('generated_at')))}</strong></p></header><div class="brief"><span><b>{len(games)}</b>款候选 · Steam 公开数据 · 可切换近 1 / 7 / 30 天</span><a href="#methodology">范围与口径 ↓</a></div><section id="rankings" aria-labelledby="ranking-title"><div id="controls" class="toolbar" hidden><div class="toolbar-top"><div class="metrics" role="group" aria-label="排名指标"><button type="button" data-metric="count" aria-pressed="true">新增评价</button><button type="button" data-metric="rate" aria-pressed="false">好评率</button><button type="button" data-metric="players" aria-pressed="false">当前在线</button><button type="button" data-metric="rank" aria-pressed="false">独立热销</button></div><div class="windows" role="group" aria-label="评价时间窗口"><button type="button" data-days="1" aria-pressed="false">近 1 天</button><button type="button" data-days="7" aria-pressed="true">近 7 天</button><button type="button" data-days="30" aria-pressed="false">近 30 天</button></div></div><div class="filters"><label>搜索<input id="game-search" type="search" placeholder="游戏名称 / 标签" autocomplete="off"></label><label>玩法<select id="play-style"><option value="">全部玩法</option>{style_options}</select></label><p class="count" id="result-count" aria-live="polite">{len(ranked)} 款参与排名 / {len(games)} 款候选</p></div></div><div class="ranking-head"><h2 id="ranking-title">近 7 天 · 新增评价排行</h2><p>候选样本内排序 · 点击游戏前往 Steam</p></div><p class="period-note" id="period-note">从采集时点向前 7 × 24 小时，按评论创建时间统计。评价量不等于售出份数或下载次数。</p><ol class="rank-list" id="rank-list">{rows}</ol><div class="empty" id="empty-state"{(' hidden' if ranked else '')}>本筛选暂无可排名的数据。可以调整指标、时间范围或玩法筛选。</div><details class="waiting" id="waiting"{('' if pending else ' hidden')}><summary id="waiting-title">{len(pending)} 款暂未参与当前排名</summary><ul id="waiting-games">{pending_html}</ul></details><noscript><p class="nojs">当前展示近 7 天新增评价榜。启用 JavaScript 可切换窗口、排名指标和筛选。</p></noscript></section><details class="methodology" id="methodology"><summary>样本范围、数据口径与来源</summary><div class="method-body"><div><h3>如何读这张榜</h3><p>{esc(scope)}</p><p>近 1 / 7 / 30 天指采集时点向前的连续 24 / 168 / 720 小时。好评率榜仅纳入期间至少 20 条评价的作品；少量评价仍可能产生较大波动。</p><p>独立热销顺位来自美国区 Indie 搜索热销入口，保留原始顺位；它不是全球销量榜。当前在线是采集快照，时间切换只影响评价指标。鼠标停在数字上可查看采集时间。</p><p>缺失或旧值不参与排名，不按零处理。完整取得的 0 条评价或 0 人在线会如实显示。样本受发现入口与筛选规则限制，不是 Steam 全库排名。</p><ul>{method}</ul></div><div><h3>数据来源</h3><ul>{sources or '<li>Steam 商店公开数据；本期尚未取得来源记录。</li>'}</ul></div></div></details></main><footer class="footer"><span>策划日报 · 小体量独立游戏候选观察</span><a href="market.html">查看 Steam 全局市场 →</a></footer></div><script type="application/json" id="ranking-data">{payload}</script><script>{SCRIPT}</script></body></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "data/indie_market.json")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/indie.html")
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8")) if args.input.exists() else {}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_indie_market(data), encoding="utf-8")
    print(f"Rendered {len(data.get('games', []))} indie candidates to {args.output}")


if __name__ == "__main__":
    main()
