"""Buildless Steam observation page and an embeddable daily-edition brief.

Render only collected evidence. A missing historical window stays missing; the
current snapshot, discovery links and dated official events remain browseable.
"""
from __future__ import annotations

import argparse
import html
import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

TZ = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parents[1]


def esc(value):
    return html.escape(str(value if value is not None else ""), quote=True)


def _url(value):
    value = str(value or "").strip()
    parsed = urlparse(value)
    return value if parsed.scheme in ("https", "http") and parsed.netloc else ""


def _link(url, label, cls=""):
    url = _url(url)
    return (f'<a class="{esc(cls)}" href="{esc(url)}" target="_blank" rel="noopener noreferrer">{esc(label)} ↗</a>'
            if url else f'<span class="{esc(cls)}">{esc(label)}</span>')


def _dt(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return (parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed).astimezone(TZ)
    except (ValueError, TypeError):
        return None


def _time(value, full=True):
    parsed = _dt(value)
    if not parsed:
        return "时间未提供"
    label = parsed.strftime("%Y.%m.%d %H:%M" if full else "%m.%d %H:%M")
    return f'<time datetime="{esc(parsed.isoformat())}">{label}</time>'


def _day(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def _number(value, decimals=0, signed=False):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        return "—"
    return format(value, f"{'+' if signed else ''},.{decimals}f")


def _list(value):
    return value if isinstance(value, list) else []


def _labels(value):
    out = []
    for item in _list(value):
        label = item.get("description") or item.get("name") if isinstance(item, dict) else item
        if label and str(label) not in out:
            out.append(str(label))
    return out


def _games(data):
    seen, games = set(), []
    for game in _list(data.get("games")):
        if not isinstance(game, dict) or not game.get("name"):
            continue
        appid = str(game.get("appid", ""))
        if not appid.isdigit() or appid in seen:
            continue
        seen.add(appid)
        games.append(game)
    return games


def _new(game, today):
    released = _day(game.get("release_date"))
    return bool(released and today and 0 <= (today - released).days <= 30 and not game.get("coming_soon"))


def _window(game, days):
    value = (game.get("windows") or {}).get(str(days)) or {}
    return value if isinstance(value, dict) else {}


def _window_ready(game, days):
    window = _window(game, days)
    return (window.get("status") in ("ready", "no_baseline") and
            all(isinstance(window.get(key), (int, float)) and not isinstance(window.get(key), bool)
                and math.isfinite(window[key]) for key in ("current", "previous", "absolute_change")))


def _fresh_players(game):
    """Online freshness is independent of review/event collection freshness."""
    status = game.get("players_status") or game.get("status")
    return status in ("fresh", "partial") and isinstance(game.get("current_players"), (int, float))


def _trend(game, days):
    window = _window(game, days)
    hidden = ' hidden' if days != 7 else ''
    if not _window_ready(game, days):
        status = window.get("status")
        title = {"no_baseline": "暂无可比基数", "not_released": "尚未发售", "missing_data": "记录存在缺口"}.get(status, "历史积累中")
        reason = window.get("reason") or f"需要两个完整的 {days} 天窗口，才显示可比变化。"
        return (f'<div class="trend trend-pending" data-trend="{days}"{hidden}>'
                f'<strong>{title}</strong><span>{esc(reason)}</span></div>')
    delta = window["absolute_change"]
    direction = "up" if delta > 0 else "down" if delta < 0 else "flat"
    pct = _number(window.get("percent_change"), 1, True)
    pct = pct + "%" if pct != "—" else "比例不可比"
    low = '<span class="low-base">低基数，优先看绝对变化</span>' if window.get("low_base") else ''
    return (f'<div class="trend" data-trend="{days}"{hidden}><div class="trend-line">'
            f'<strong class="{direction}">{_number(delta, 1, True)} <small>人</small></strong><b class="{direction}">{pct}</b></div>'
            f'<span>采样在线均值：{_number(window["previous"], 1)} → {_number(window["current"], 1)}</span>'
            f'<span>此前 {days} 天 → 最近 {days} 天 · 有记录日 {esc(window.get("previous_days", "—"))} / {esc(window.get("current_days", "—"))}</span>{low}</div>')


def _events(game):
    events = [item for item in _list(game.get("events")) if isinstance(item, dict) and item.get("title")]
    status = game.get("events_status")
    prefix = "公告沿用旧记录" if status == "stale" else "公告采集"
    source_stamp = f'<p class="detail-caveat">{prefix}：{_time(game.get("events_at"))}</p>' if game.get("events_at") else ''
    if not events:
        return source_stamp + '<p class="muted detail-empty">当前未收录可展示的近期官方公告。</p>'
    rows = []
    for event in events[:3]:
        day = _day(event.get("date") or event.get("published"))
        stamp = day.isoformat() if day else "日期未提供"
        rows.append(f'<li><span class="event-date">{esc(stamp)}</span>{_link(event.get("url"), event["title"])}</li>')
    return source_stamp + '<ul class="event-list">' + ''.join(rows) + '</ul><p class="detail-caveat">公告与曲线在时间上相邻，不代表已经确认因果关系。</p>'


def _reviews(game):
    reviews = [item for item in _list(game.get("reviews")) if isinstance(item, dict) and item.get("text") and _url(item.get("url"))]
    if not reviews:
        return '<p class="muted detail-empty">本轮未取得可引用的中英文评论样本。</p>'
    rows = []
    for review in reviews[:4]:
        language = str(review.get("language") or "")
        lang_label = "中文" if language in ("zh", "schinese", "tchinese") or language.startswith("zh") else "英文" if language in ("en", "english") else "原文"
        lang = ' lang="en"' if lang_label == "英文" else ''
        text = str(review["text"])
        excerpt = text[:220].rstrip() + ("…" if len(text) > 220 else "")
        vote = "推荐" if review.get("voted_up") is True else "不推荐" if review.get("voted_up") is False else ""
        rows.append(f'<blockquote{lang}><p>{esc(excerpt)}</p><footer>{esc(lang_label)} · {esc(vote)} · {_link(review["url"], "查看评论")}</footer></blockquote>')
    return ''.join(rows) + '<p class="detail-caveat">以上为少量原文摘录，不代表全部玩家；未据此自动归纳共识。</p>'


def _cover(game, store):
    image_url = _url(game.get("header_image"))
    image = (f'<img src="{esc(image_url)}" alt="{esc(game["name"])} Steam 商店封面" '
             'width="460" height="215" loading="lazy" decoding="async">') if image_url else ''
    fallback = f'<span class="cover-fallback"{" hidden" if image_url else ""}>封面暂不可用</span>'
    store_url = _url(store)
    if store_url:
        return (f'<a class="game-cover" href="{esc(store_url)}" target="_blank" rel="noopener noreferrer" '
                f'aria-label="在 Steam 查看 {esc(game["name"])}">{image}{fallback}</a>')
    return f'<div class="game-cover">{image}{fallback}</div>'


def _card(game, today):
    appid = str(game["appid"])
    modes, genres = _labels(game.get("player_modes")), _labels(game.get("genres"))
    tags = _labels(game.get("tags"))
    badges = (['动作游戏'] if game.get("is_action") else []) + (['近 30 天新作'] if _new(game, today) else []) + (['Demo 可前往'] if _url(game.get("demo_url")) else [])
    summary = game.get("review_summary") or {}
    positive = _number(summary.get("positive_percent"), 1)
    positive_label = f"{positive}%" if positive != "—" else "—"
    price = game.get("price") or {}
    price_text = price.get("formatted") or "价格未取得"
    region_code = str(price.get("region") or "").upper()
    region_label = {"CN": "国区", "US": "美区"}.get(region_code, f"{region_code} 区" if region_code else "")
    if region_label:
        price_text = f"{price_text} · {region_label}"
    metadata_state = "商店资料沿用旧值" if game.get("metadata_status") == "stale" else "商店资料采集"
    metadata_note = f'<p class="metadata-stamp">{metadata_state} {_time(game.get("metadata_at"), False)}</p>' if game.get("metadata_at") else ''
    released = game.get("release_label") or game.get("release_date") or "发售日未提供"
    if game.get("coming_soon"):
        released = "即将推出 · " + str(released)
    status = game.get("status") or "unavailable"
    players_status = game.get("players_status") or status
    state = {"fresh": "在线本轮已采集", "partial": "在线本轮已采集", "stale": "在线沿用历史快照", "unavailable": "在线数据暂不可用"}.get(players_status, "在线状态待确认")
    review_state = "评价沿用旧值" if summary.get("status") == "stale" else "评价采集"
    review_stamp = f'<small>{review_state} {_time(summary.get("sampled_at"), False)}</small>' if summary.get("sampled_at") else ''
    store = game.get("store_url") or f"https://store.steampowered.com/app/{appid}/"
    data_search = " ".join([str(game["name"]), appid] + genres + tags + modes)
    badge_html = ''.join(f'<span>{esc(badge)}</span>' for badge in badges)
    genre_html = ' · '.join(esc(label) for label in genres[:3]) or "类型待补充"
    review_source = _url(summary.get("source")) or str(store).rstrip('/') + '/#app_reviews_hash'
    mode_html = ' · '.join(esc(label) for label in modes) or "玩家模式待补充"
    demo_link = _link(game.get("demo_url"), "前往 Demo") if _url(game.get("demo_url")) else ''
    errors = '<p class="detail-caveat">部分来源暂未返回结果；缺失值不会记为零。</p>' if game.get("errors") else ''
    return f'''<article class="game-card" id="game-{appid}" data-game data-action="{str(bool(game.get('is_action'))).lower()}" data-new="{str(_new(game, today)).lower()}" data-demo="{str(bool(_url(game.get('demo_url')))).lower()}" data-search="{esc(data_search)}" data-genres="{esc(json.dumps(genres, ensure_ascii=False))}" data-modes="{esc(json.dumps(modes, ensure_ascii=False))}">
{_cover(game, store)}<div class="card-top"><span class="card-number">APP {appid}</span><a class="permalink" href="#game-{appid}" aria-label="{esc(game['name'])}的页内链接">#</a></div>
<div class="game-badges">{badge_html}</div><h3>{_link(store, game['name'])}</h3><p class="game-genres">{genre_html}</p>
<div class="game-meta"><span>{esc(price_text)}</span><span>{esc(released)}</span></div>{metadata_note}
<dl class="game-metrics"><div><dt>{'最近已知在线' if players_status == 'stale' else '当前在线'}</dt><dd>{_number(game.get('current_players'))}<small>人</small></dd></div><div><dt>中英文评价推荐比例</dt><dd>{positive_label}<small>{_number(summary.get('total'))} 条累计评价</small>{review_stamp}</dd></div></dl>
<div class="window-caption"><span data-window-label>7 天变化</span><span>采样在线均值</span></div>{''.join(_trend(game, days) for days in (1, 7, 30))}
<p class="snapshot-state state-{esc(players_status)}">{state} · {_time(game.get('observed_at'), False)}</p>
<details class="game-details"><summary>玩家评价与官方公告 <span aria-hidden="true">＋</span></summary><div class="detail-body">
<p class="detail-mode">玩家模式：{mode_html}</p><h4>官方事件</h4>{_events(game)}<h4>玩家原声 · 原文摘录</h4>{_reviews(game)}
{errors}<div class="game-links">{_link(store, 'Steam 商店')}{_link(review_source, '全部评价')}{demo_link}</div></div></details></article>'''


CSS = r'''
:root{color-scheme:light;--paper:#f1ede3;--panel:#faf8f1;--ink:#292d27;--soft:#5e635a;--muted:#74796d;--line:#d1d0c1;--rust:#9b493b;--sage:#4c6152;--wash:#e7eadf;--serif:Georgia,"Noto Serif SC","Songti SC",SimSun,serif;--sans:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;--mono:ui-monospace,SFMono-Regular,Consolas,monospace}*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:20px}body{margin:0;background:var(--paper);color:var(--ink);font:14px/1.8 var(--sans)}a{color:inherit;text-underline-offset:4px}a:hover{color:var(--rust)}a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible{outline:3px solid var(--rust);outline-offset:4px}[hidden]{display:none!important}button,input,select{font:inherit;color:inherit}button,summary,select{cursor:pointer}button{border-radius:0}h1,h2,h3,h4,p,dl,dd{margin:0}h1,h2,h3{font-family:var(--serif)}.wrap{width:min(1180px,100% - 80px);margin:auto}.skip{position:fixed;left:14px;top:12px;transform:translateY(-200%);z-index:20;background:var(--ink);color:#fff;padding:8px}.skip:focus{transform:none}.masthead{padding-top:26px}.masthead-top{display:flex;justify-content:space-between;gap:20px;border-bottom:1px solid var(--line);padding-bottom:13px;font-size:11px;color:var(--soft)}.masthead-top a{text-decoration:none}.masthead-top span{font:10px var(--mono);letter-spacing:.1em}.brand-row{display:flex;justify-content:space-between;gap:24px;align-items:center;padding:30px 0 25px}.brand-row h1{font-size:clamp(39px,5.5vw,65px);line-height:1.3;letter-spacing:.04em}.brand-en{font:11px var(--mono);letter-spacing:.22em;color:var(--soft);margin-top:10px}.edition{text-align:right;font-size:11px;color:var(--soft)}.edition b{display:block;color:var(--ink);font:23px var(--serif);margin-bottom:8px}.nav{display:flex;flex-wrap:wrap;gap:28px;border-top:3px solid var(--ink);border-bottom:1px solid var(--ink);padding:12px 0;font-size:12px}.nav a{text-decoration:none}.nav [aria-current=page]{color:var(--sage);font-weight:700}.intro{display:grid;grid-template-columns:1.25fr 1fr;gap:50px;padding:34px 0 28px}.eyebrow{font:10px var(--mono);letter-spacing:.16em;color:var(--sage)}.intro h2{font-size:30px;line-height:1.5;margin:8px 0 10px}.intro p{font-size:12px;color:var(--soft);max-width:640px}.overview-stats{display:grid;grid-template-columns:repeat(3,1fr);align-content:center;gap:12px}.overview-stats div{border-left:1px solid var(--line);padding-left:18px}.overview-stats dd{font:31px var(--serif);margin-bottom:9px}.overview-stats dt{font-size:10px;color:var(--soft)}.coverage-note{font-size:11px;line-height:1.8;padding:13px 17px;background:var(--wash);border-left:3px solid var(--sage);color:var(--soft)}.coverage-note strong{color:var(--sage)}.scope-section{margin-top:28px}.section-top{display:flex;align-items:baseline;justify-content:space-between;gap:20px;border-bottom:1px solid var(--line);padding-bottom:12px}.section-top h2{font-size:23px}.section-top p{font-size:10px;color:var(--soft)}.segment-grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:0;margin-top:13px;border:1px solid var(--line)}.segment{padding:13px;border-right:1px solid var(--line)}.segment:last-child{border:0}.segment h3{font:12px var(--sans);margin-bottom:6px;overflow-wrap:anywhere}.segment strong{font:21px var(--serif)}.segment span{font-size:10px;color:var(--soft);display:block;margin-top:5px}.scope-caveat{font-size:10px;color:var(--muted);margin-top:9px}.observation{margin-top:36px}.observation>.section-top{border-bottom:2px solid var(--ink);padding-bottom:16px}.observation h2{font-size:28px}.controls{padding:18px 0 17px;border-bottom:1px solid var(--line)}.control-row{display:flex;justify-content:space-between;gap:20px;align-items:center;flex-wrap:wrap}.button-group{display:flex;flex-wrap:wrap;gap:5px}.button-group button{background:transparent;border:1px solid var(--line);padding:7px 14px;font-size:12px}.button-group button[aria-pressed=true]{background:var(--sage);color:var(--panel);border-color:var(--sage)}.window-controls{display:flex;align-items:center;gap:12px}.window-controls>span{font-size:10px;color:var(--soft)}.filter-fields{display:grid;grid-template-columns:1.8fr 1fr 1fr 1fr;gap:11px;margin-top:16px}.field{min-width:0}.field span{display:block;font-size:10px;color:var(--soft);margin-bottom:5px}.field input,.field select{width:100%;min-width:0;height:40px;border:1px solid #b9bdaf;background:var(--panel);padding:0 10px;font-size:12px;border-radius:0}.filter-footer{display:flex;justify-content:space-between;align-items:center;gap:15px;margin-top:11px;font-size:10px;color:var(--soft)}.reset{border:0;background:none;color:var(--sage);text-decoration:underline;text-underline-offset:4px;padding:4px}.window-note{font-size:11px;color:var(--soft);padding:14px 0}.window-note strong{color:var(--sage)}.games{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:22px;align-items:start}.game-card{min-width:0;border:1px solid var(--line);background:var(--panel);padding:20px 21px 0;scroll-margin-top:24px}.game-card:target{outline:2px solid var(--sage);outline-offset:4px}.card-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}.card-number{font:9px var(--mono);letter-spacing:.08em;color:var(--muted)}.permalink{font:12px var(--mono);text-decoration:none;color:var(--muted);padding:3px}.game-badges{display:flex;gap:5px;flex-wrap:wrap;min-height:23px}.game-badges span{font-size:9px;color:var(--sage);border:1px solid #d2d8c9;padding:0 5px}.game-card h3{font-size:22px;line-height:1.4;margin-top:8px;overflow-wrap:anywhere}.game-card h3 a{text-decoration:none}.game-genres{font-size:10px;color:var(--soft);margin-top:8px;min-height:18px;overflow-wrap:anywhere}.game-meta{display:flex;justify-content:space-between;gap:12px;font-size:10px;color:var(--soft);margin-top:11px;border-bottom:1px solid var(--line);padding-bottom:15px}.game-metrics{display:grid;grid-template-columns:1fr 1fr;gap:14px;padding:17px 0}.game-metrics dt{font-size:10px;color:var(--soft);margin-bottom:6px}.game-metrics dd{font:26px/1.3 var(--serif)}.game-metrics small{font:9px var(--sans);color:var(--muted);display:block;margin-top:5px}.window-caption{display:flex;justify-content:space-between;gap:8px;font-size:9px;color:var(--sage);padding-top:11px;border-top:1px solid var(--line)}.trend{min-height:97px;padding:10px 0 8px}.trend>span{display:block;font-size:10px;color:var(--soft);margin-top:3px}.trend-line{display:flex;justify-content:space-between;align-items:baseline;gap:12px}.trend-line strong{font:23px var(--serif)}.trend-line strong small{font:10px var(--sans)}.trend-line b{font:13px var(--mono)}.up{color:var(--sage)}.down{color:var(--rust)}.flat{color:var(--soft)}.trend-pending strong{font:17px var(--serif);color:var(--soft)}.trend .low-base{color:var(--rust)}.snapshot-state{font-size:9px;color:var(--muted);padding:6px 0 13px}.state-stale,.state-unavailable{color:var(--rust)}.game-details{border-top:1px solid var(--line);margin:0 -21px}.game-details summary{font-size:11px;color:var(--sage);padding:13px 21px;list-style:none;display:flex;justify-content:space-between;gap:12px}.game-details summary::-webkit-details-marker{display:none}.game-details[open] summary{border-bottom:1px solid var(--line)}.game-details[open] summary span{transform:rotate(45deg)}.detail-body{padding:15px 21px 20px}.detail-mode{font-size:10px;color:var(--soft)}.detail-body h4{font:700 12px var(--sans);margin-top:20px;color:var(--sage)}.detail-empty{font-size:11px;margin-top:8px}.event-list{list-style:none;padding:0;margin:8px 0}.event-list li{font-size:11px;padding:8px 0;border-bottom:1px dotted var(--line)}.event-list a{text-decoration:none;overflow-wrap:anywhere}.event-date{display:block;font:9px var(--mono);color:var(--muted);margin-bottom:4px}.detail-caveat{font-size:9px;color:var(--muted);line-height:1.8;margin-top:10px}blockquote{margin:11px 0 0;padding:9px 11px;border-left:2px solid var(--line);background:var(--paper)}blockquote p{font-size:11px;color:var(--soft);overflow-wrap:anywhere}blockquote footer{font-size:9px;color:var(--muted);margin-top:6px}.game-links{display:flex;gap:15px;flex-wrap:wrap;font-size:10px;margin-top:15px}.empty-state{padding:45px 20px;text-align:center;border:1px solid var(--line);background:var(--panel)}.empty-state h3{font-size:23px}.empty-state p{font-size:12px;color:var(--soft);margin-top:10px}.discovery{margin-top:42px}.discovery .section-top h2{font-size:25px}.discovery-deck{font-size:12px;color:var(--soft);margin-top:12px}.discovery-links{display:flex;flex-wrap:wrap;gap:10px;margin-top:17px}.discovery-links a{border:1px solid var(--line);font-size:11px;padding:7px 13px;text-decoration:none}.discovery-list{list-style:none;padding:0;margin:18px 0;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px 24px}.discovery-list li{border-bottom:1px solid var(--line);padding:8px 0;font-size:12px}.discovery-list a{text-decoration:none;overflow-wrap:anywhere}.discovery-list small{display:block;color:var(--muted);font-size:10px;margin-top:4px}.methodology{margin-top:39px;border-top:3px double var(--ink);padding-top:20px}.methodology>summary{font:700 22px var(--serif);padding:8px 0}.method-grid{display:grid;grid-template-columns:1.3fr 1fr;gap:45px;padding:22px 0 10px}.method-grid h3{font-size:18px;margin-bottom:12px}.method-grid p,.method-grid li{font-size:11px;color:var(--soft)}.method-grid ul,.method-grid ol{padding-left:19px;margin:0}.method-grid li+li{margin-top:9px}.method-grid a{overflow-wrap:anywhere}.method-grid p+p{margin-top:12px}.footer{display:flex;justify-content:space-between;gap:25px;border-top:2px solid var(--ink);margin-top:35px;padding:22px 0 30px;font-size:10px;color:var(--muted)}.footer strong{font:700 16px var(--serif);color:var(--ink)}.footer p{margin-top:5px}.footer nav{display:flex;gap:20px;align-items:start}.muted{color:var(--soft)}noscript p{font-size:12px;padding:12px;border:1px solid var(--line)}
@media(max-width:1000px){.wrap{width:calc(100% - 48px)}.games{grid-template-columns:repeat(2,minmax(0,1fr))}.segment-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.segment:nth-child(3){border-right:0}.segment:nth-child(-n+3){border-bottom:1px solid var(--line)}.intro{gap:25px}.filter-fields{grid-template-columns:1.4fr 1fr 1fr}.field-discovery{grid-column:1/-1}.field-discovery select{max-width:300px}.discovery-list{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:650px){.wrap{width:calc(100% - 32px)}.masthead{padding-top:18px}.masthead-top{font-size:10px}.masthead-top span{font-size:8px;letter-spacing:.04em}.brand-row{padding:23px 0 21px;align-items:flex-end;gap:15px}.brand-row h1{font-size:39px}.brand-en{font-size:8px;letter-spacing:.09em}.edition{font-size:9px}.edition b{font-size:17px}.nav{gap:22px;font-size:11px}.intro{display:block;padding:27px 0 22px}.intro h2{font-size:26px}.overview-stats{margin-top:23px}.overview-stats div{padding-left:13px}.overview-stats dd{font-size:27px}.coverage-note{font-size:10px;padding:11px 13px}.section-top{align-items:flex-start;flex-direction:column;gap:5px}.section-top h2{font-size:21px}.segment-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.segment{padding:10px}.segment h3{font-size:10px}.segment span{font-size:9px}.observation{margin-top:28px}.observation h2{font-size:25px}.control-row{gap:13px}.button-group button{font-size:11px;padding:7px 13px}.filter-fields{grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.field-search{grid-column:1/-1}.field-discovery{grid-column:auto}.field-mode{grid-column:auto}.field-discovery select{max-width:none}.games{grid-template-columns:1fr;gap:16px}.game-card{padding-top:17px}.game-card h3{font-size:25px}.game-badges{min-height:0}.game-metrics dd{font-size:29px}.trend{min-height:83px}.window-note{font-size:10px}.discovery-list{grid-template-columns:1fr}.method-grid{grid-template-columns:1fr;gap:24px}.methodology>summary{font-size:20px}.footer{display:block}.footer nav{margin-top:16px}.filter-footer{align-items:flex-start}.snapshot-state{font-size:10px}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}@media print{body{background:#fff}.wrap{width:100%}.controls,.skip,.nav{display:none}.games{grid-template-columns:repeat(2,1fr)}.game-card{break-inside:avoid}.intro{display:block}.methodology{display:none}}
'''


CSS += r'''
.segment-trend{margin-top:11px;padding-top:10px;border-top:1px solid var(--line)}.segment-trend b{font-size:10px;line-height:1.7;font-weight:600;overflow-wrap:anywhere}.segment-trend span{font-size:9px}.other-discovery{margin-top:20px;padding:13px 0;border-top:1px solid var(--line)}.other-discovery>summary{font-size:12px;color:var(--sage)}
.metadata-stamp{font-size:9px;color:var(--muted);margin-top:8px}.discovery-state{font-size:10px;color:var(--soft);margin-top:10px}.collection-alert{color:var(--rust)}
@media(max-width:650px){.brand-row{display:block}.brand-row h1{font-size:clamp(29px,8.4vw,39px)}.edition{text-align:left;margin-top:15px}.edition b{display:inline;font-size:15px;margin-right:13px}.edition br{display:none}.edition time{margin-right:7px}}
'''


CSS += r'''
.game-cover{display:grid;place-items:center;position:relative;aspect-ratio:460/215;margin:-20px -21px 16px;background:#e3e5dc;overflow:hidden;border-bottom:1px solid var(--line);text-decoration:none}
.game-cover img{position:absolute;inset:0;display:block;width:100%;height:100%;object-fit:cover}
.cover-fallback{font-size:12px;color:var(--soft)}
.intro h2{font-size:25px;line-height:1.4}.intro{padding:25px 0 22px}
@media(max-width:650px){.game-cover{margin-top:-17px}.intro h2{font-size:23px}}
'''

SCRIPT = r'''
(() => {
  document.querySelectorAll('.game-cover img').forEach(image => {
    const unavailable = () => {
      image.hidden = true;
      image.nextElementSibling.hidden = false;
    };
    image.addEventListener('error', unavailable);
    if (image.complete && !image.naturalWidth) unavailable();
  });
  const form = document.getElementById('market-filters');
  if (!form) return;
  const cards = Array.from(document.querySelectorAll('[data-game]'));
  const search = document.getElementById('market-search');
  const genre = document.getElementById('market-genre');
  const mode = document.getElementById('market-mode');
  const discovery = document.getElementById('market-discovery');
  const scopes = Array.from(document.querySelectorAll('[data-scope]'));
  const windows = Array.from(document.querySelectorAll('[data-days]'));
  const params = new URLSearchParams(location.search);
  let scope = params.get('scope') === 'action' ? 'action' : 'all';
  let days = ['1', '7', '30'].includes(params.get('days')) ? params.get('days') : '7';
  const normalise = value => value.normalize('NFKC').toLocaleLowerCase().trim();
  search.value = params.get('q') || '';
  [[genre, 'genre'], [mode, 'mode'], [discovery, 'view']].forEach(([select, key]) => {
    if (Array.from(select.options).some(option => option.value === params.get(key))) select.value = params.get(key);
  });
  function apply() {
    const terms = normalise(search.value).split(/\s+/).filter(Boolean);
    let visible = 0;
    let comparable = 0;
    cards.forEach(card => {
      const matches = (scope === 'all' || card.dataset.action === 'true')
        && terms.every(term => normalise(card.dataset.search).includes(term))
        && (!genre.value || JSON.parse(card.dataset.genres).includes(genre.value))
        && (!mode.value || JSON.parse(card.dataset.modes).includes(mode.value))
        && (!discovery.value || (discovery.value === 'new' ? card.dataset.new === 'true' : card.dataset.demo === 'true'));
      card.hidden = !matches;
      card.querySelectorAll('[data-trend]').forEach(panel => { panel.hidden = panel.dataset.trend !== days; });
      card.querySelector('[data-window-label]').textContent = `${days} 天变化`;
      if (matches) {
        visible++;
        if (!card.querySelector(`[data-trend="${days}"]`).classList.contains('trend-pending')) comparable++;
      }
    });
    scopes.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.scope === scope)));
    windows.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.days === days)));
    document.querySelectorAll('[data-segment-trend]').forEach(panel => { panel.hidden = panel.dataset.segmentTrend !== days; });
    document.getElementById('scope-window-label').textContent = `当前快照与 ${days} 天变化 · 按样本数展示分类`;
    document.getElementById('filter-status').textContent = `显示 ${visible} / ${cards.length} 款样本 · ${scope === 'action' ? '动作游戏' : '全局样本'}`;
    document.getElementById('filter-empty').hidden = visible !== 0;
    document.getElementById('window-note').textContent = `${days} 天窗口：当前筛选内 ${comparable} / ${visible} 款具备完整可比记录。比较最近 ${days} 个完整日与此前 ${days} 日的采样在线均值；不足时保留快照，不补造涨幅。`;
    const url = new URL(location.href);
    [['scope', scope === 'all' ? '' : scope], ['days', days === '7' ? '' : days], ['q', search.value.trim()], ['genre', genre.value], ['mode', mode.value], ['view', discovery.value]].forEach(([key, value]) => {
      if (value) url.searchParams.set(key, value); else url.searchParams.delete(key);
    });
    try { history.replaceState(null, '', url.pathname + url.search + url.hash); } catch (_) {}
  }
  function reset() { form.reset(); scope = 'all'; days = '7'; apply(); search.focus(); }
  scopes.forEach(button => button.addEventListener('click', () => { scope = button.dataset.scope; apply(); }));
  windows.forEach(button => button.addEventListener('click', () => { days = button.dataset.days; apply(); }));
  form.addEventListener('submit', event => { event.preventDefault(); apply(); });
  search.addEventListener('input', apply);
  [genre, mode, discovery].forEach(select => select.addEventListener('change', apply));
  document.querySelectorAll('[data-reset-filters]').forEach(button => button.addEventListener('click', reset));
  document.querySelectorAll('[data-discovery-shortcut]').forEach(link => link.addEventListener('click', () => {
    form.reset(); scope = 'all'; discovery.value = link.dataset.discoveryShortcut; apply();
  }));
  form.hidden = false;
  apply();
})();
'''


def _sources(data):
    rows = []
    for source in _list(data.get("sources")):
        if isinstance(source, str):
            rows.append(f'<li>{esc(source)}</li>')
        elif isinstance(source, dict):
            label = source.get("title") or source.get("name") or source.get("id") or "数据来源"
            note = source.get("note") or source.get("description") or ""
            rows.append(f'<li>{_link(source.get("url"), label)}{(" · " + esc(note)) if note else ""}</li>')
    if not rows:
        rows = [f'<li>{_link("https://partner.steamgames.com/doc/webapi/ISteamUserStats#GetNumberOfCurrentPlayers", "Steam 当前在线人数接口")}</li>',
                f'<li>{_link("https://partner.steamgames.com/doc/webapi/IUserReviewsService", "Steam 评价接口")}</li>',
                f'<li>{_link("https://store.steampowered.com/", "Steam 商店与官方公告")}</li>']
    return '<ul>' + ''.join(rows) + '</ul>'


def _segments(games):
    segments = {}
    for game in games:
        for genre in _labels(game.get("genres")):
            segment = segments.setdefault(genre, {"count": 0, "players": 0, "observed": 0, "games": []})
            segment["count"] += 1
            segment["games"].append(game)
            if _fresh_players(game):
                segment["players"] += game["current_players"]
                segment["observed"] += 1
    groups = sorted(segments.items(), key=lambda item: (-item[1]["count"], item[0]))[:6]
    if not groups:
        return '<p class="discovery-deck">分类信息积累中；已有作品仍可在下方查看。</p>'
    return '<div class="segment-grid">' + ''.join(
        f'<div class="segment"><h3>{esc(name)}</h3><strong>{value["count"]}</strong><span>款样本 · {value["observed"]} 款有本轮在线值</span><span>当前在线合计 {_number(value["players"]) if value["observed"] else "—"}</span>{_segment_trends(value["games"])}</div>'
        for name, value in groups) + '</div>'


def _segment_trends(games):
    panels = []
    for days in (1, 7, 30):
        cohort = [game for game in games if _window_ready(game, days)]
        hidden = ' hidden' if days != 7 else ''
        if not cohort:
            content = f'<b>{days} 天变化 · 积累中</b><span>可比覆盖 0 / {len(games)} 款</span>'
        else:
            previous = sum(_window(game, days)["previous"] for game in cohort)
            current = sum(_window(game, days)["current"] for game in cohort)
            delta = current - previous
            pct = f'{_number(delta / previous * 100, 1, True)}%' if previous > 0 else '基数为零'
            up = sum(_window(game, days)["absolute_change"] > 0 for game in cohort)
            down = sum(_window(game, days)["absolute_change"] < 0 for game in cohort)
            direction = 'up' if delta > 0 else 'down' if delta < 0 else 'flat'
            content = (f'<b class="{direction}">{days} 天 {_number(delta, 1, True)} 人 · {pct}</b>'
                       f'<span>可比均值合计<br>{_number(previous, 1)} → {_number(current, 1)}</span>'
                       f'<span>上涨 {up} · 下降 {down} · 持平 {len(cohort) - up - down}</span>'
                       f'<span>可比覆盖 {len(cohort)} / {len(games)} 款</span>')
        panels.append(f'<div class="segment-trend" data-segment-trend="{days}"{hidden}>{content}</div>')
    return ''.join(panels)


def _discovery(data, games, today):
    discovery = data.get("discovery") or {}
    discovery_label = {"fresh": "发现来源已更新", "partial": "部分发现来源暂不可用", "stale": "发现列表沿用旧记录", "unavailable": "发现来源暂不可用"}.get(discovery.get("status"), "发现来源状态未提供")
    discovery_stamp = f' · 最近取得 {_time(discovery.get("updated_at"))}' if discovery.get("updated_at") else ''
    discovery_state = f'<p class="discovery-state">{discovery_label}{discovery_stamp}。以列表日期和商店实际信息为准。</p>'
    discovered = [item for item in _list(discovery.get("items")) if isinstance(item, dict) and item.get("name")]
    items = [item for item in discovered if _new(item, today) or _url(item.get("demo_url"))]
    if not items:
        items = [game for game in games if _new(game, today) or _url(game.get("demo_url"))][:9]
    rows = []
    for item in items[:12]:
        url = item.get("store_url") or item.get("url")
        if not url and str(item.get("appid", "")).isdigit():
            url = f'https://store.steampowered.com/app/{item["appid"]}/'
        label = item.get("release_label") or item.get("release_date") or "前往商店查看详情"
        rows.append(f'<li>{_link(url, item["name"])}<small>{esc(label)}</small></li>')
    body = '<ul class="discovery-list">' + ''.join(rows) + '</ul>' if rows else '<p class="discovery-deck">本轮未取得新作发现列表，可以从 Steam 官方入口继续浏览。</p>'
    other_items = [item for item in discovered if not _new(item, today) and not _url(item.get("demo_url"))]
    other = ''
    if other_items:
        other_rows = ''.join(f'<li>{_link(item.get("store_url") or item.get("url"), item["name"])}<small>公开来源发现 · 尚未判定为新作或 Demo</small></li>' for item in other_items[:6])
        other = f'<details class="other-discovery"><summary>其他公开发现线索 · {len(other_items)} 款</summary><p class="discovery-deck">榜单中的作品可能已经发行多年。这里保留发现入口，不把它们标记为新作。</p><ul class="discovery-list">{other_rows}</ul></details>'
    return f'''<section class="discovery" id="discovery"><div class="section-top"><h2>新作与 Demo</h2><p>近 30 天发行 · Demo</p></div>
<p class="discovery-deck">收录近 30 天发售的作品及已取得 Demo 入口的游戏。</p>
<div class="discovery-links"><a href="#observations" data-discovery-shortcut="new">筛选近 30 天新作</a><a href="#observations" data-discovery-shortcut="demo">筛选可试玩 Demo</a>{_link('https://store.steampowered.com/search/?sort_by=Released_DESC&category1=998', 'Steam 最新发行')}{_link('https://store.steampowered.com/demos/', 'Steam Demo')}</div>{discovery_state}{body}{other}</section>'''


def render_market(data: dict) -> str:
    games = _games(data)
    generated = _dt(data.get("generated_at"))
    today = generated.date() if generated else None
    coverage = data.get("coverage") or {}
    action_count = sum(bool(game.get("is_action")) for game in games)
    fresh_count = sum(_fresh_players(game) for game in games)
    history_days = coverage.get("history_days", 0)
    history_start = coverage.get("history_start") or "尚未开始"
    scope_note = coverage.get("scope_note") or "精选作品与公开发现样本，不代表 Steam 全站；分类之间可能重叠。"
    ready = sum(_window_ready(game, 7) for game in games)
    genres = sorted({genre for game in games for genre in _labels(game.get("genres"))})
    modes = sorted({mode for game in games for mode in _labels(game.get("player_modes"))})
    options = lambda values: ''.join(f'<option value="{esc(value)}">{esc(value)}</option>' for value in values)
    methods = []
    for method in _list(data.get("methodology")):
        text = method.get("text") or method.get("note") or method.get("description") if isinstance(method, dict) else method
        if text:
            methods.append(f'<li>{esc(text)}</li>')
    method_extra = '<ul>' + ''.join(methods) + '</ul>' if methods else ''
    empty = '' if games else '<div class="empty-state"><h3>正在建立第一批市场记录</h3><p>还没有可展示的游戏数据。下方保留 Steam 官方发现入口，采集成功后会显示真实快照。</p></div>'
    return f'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="策划日报的 Steam 市场观察：全局样本与动作游戏，持续记录在线变化、玩家声音、官方事件和新作。"><title>Steam 市场观察 · 策划日报</title><style>{CSS}</style></head><body>
<a class="skip" href="#observations">跳到游戏观察</a><div class="wrap"><header class="masthead"><div class="masthead-top"><a href="index.html">策划日报 · GAME DESIGN DAILY</a><span>STEAM MARKET DATA</span></div><div class="brand-row"><div><h1>Steam 市场观察</h1><p class="brand-en">PLAYER COUNTS / REVIEWS / UPDATES</p></div><div class="edition"><b>{esc(generated.strftime('%Y.%m.%d') if generated else '记录建立中')}</b>本轮采集 {_time(data.get('generated_at'), False)}<br>北京时间 UTC+8</div></div><nav class="nav" aria-label="主导航"><a href="index.html">日报</a><a href="market.html" aria-current="page">Steam 市场</a><a href="sources.html">信息来源</a><a href="#methodology">数据与方法</a></nav></header>
<main><section class="intro"><div><span class="eyebrow">LATEST SNAPSHOT</span><h2>本轮采集概况</h2><p>已取得 {fresh_count} 款游戏的当前在线快照，{ready} 款具备完整的 7 天对比记录。各游戏的评价、发售日期和官方公告见下方卡片。</p></div><dl class="overview-stats"><div><dd>{len(games)}</dd><dt>当前观察样本</dt></div><div><dd>{action_count}</dd><dt>动作游戏</dt></div><div><dd>{esc(history_days)}</dd><dt>已积累自然日</dt></div></dl></section>
<p class="coverage-note"><strong>数据覆盖</strong>　{esc(scope_note)} 本轮取得 {fresh_count} / {len(games)} 款在线快照；历史起点 {esc(history_start)}。完整的 30 天对比需要两段共 60 天记录。</p>
<section class="scope-section" aria-labelledby="scope-heading"><div class="section-top"><h2 id="scope-heading">全局样本概览</h2><p id="scope-window-label">当前快照与 7 天变化 · 按样本数展示分类</p></div>{_segments(games)}<p class="scope-caveat">分类之间可重叠，合计不可相加。变化只比较两段都有完整记录的同一批游戏，显示有效覆盖和涨跌款数；它描述样本内变化，不代表全站板块涨幅或市场份额。当前在线合计来自各作品最近一次采样，并非同一时刻的人数。</p></section>
<section class="observation" id="observations"><div class="section-top"><div><span class="eyebrow">THE WATCH WINDOW</span><h2>作品观察窗口</h2></div><p>在线人数 · 评价 · 官方公告</p></div>
<form class="controls" id="market-filters" hidden><div class="control-row"><div class="button-group" role="group" aria-label="观察范围"><button type="button" data-scope="all" aria-pressed="true">全局样本</button><button type="button" data-scope="action" aria-pressed="false">动作游戏</button></div><div class="window-controls"><span>比较窗口</span><div class="button-group" role="group" aria-label="时间窗口"><button type="button" data-days="1" aria-pressed="false">1 天</button><button type="button" data-days="7" aria-pressed="true">7 天</button><button type="button" data-days="30" aria-pressed="false">30 天</button></div></div></div>
<div class="filter-fields"><label class="field field-search"><span>搜索作品与玩法</span><input id="market-search" type="search" placeholder="游戏名、标签或 App ID" autocomplete="off"></label><label class="field"><span>游戏品类</span><select id="market-genre"><option value="">全部品类</option>{options(genres)}</select></label><label class="field field-mode"><span>玩家模式</span><select id="market-mode"><option value="">全部模式</option>{options(modes)}</select></label><label class="field field-discovery"><span>发现入口</span><select id="market-discovery"><option value="">全部作品</option><option value="new">近 30 天新作</option><option value="demo">有 Demo 可试玩</option></select></label></div>
<div class="filter-footer"><span id="filter-status" role="status" aria-live="polite">显示 {len(games)} 款样本</span><button class="reset" type="button" data-reset-filters>清除筛选</button></div></form><noscript><p>当前展示全部作品的 7 天窗口；启用 JavaScript 后可以切换窗口和筛选。</p></noscript>
<p class="window-note" id="window-note" aria-live="polite">7 天窗口：{ready} / {len(games)} 款具备完整可比记录。历史不足时显示当前快照，不补造涨幅。</p>
<div class="empty-state" id="filter-empty" hidden><h3>当前条件下没有作品</h3><p>没有游戏同时符合当前筛选条件。</p><button class="reset" type="button" data-reset-filters>清除筛选</button></div><div class="games">{''.join(_card(game, today) for game in games)}</div>{empty}</section>
{_discovery(data, games, today)}
<details class="methodology" id="methodology"><summary>数据口径与来源</summary><div class="method-grid"><div><h3>记录边界与比较方式</h3><ol><li>1 / 7 / 30 天窗口分别比较最近完整日与此前等长窗口。每一天先汇总当天采样值，再比较两个窗口；尚未完整积累时不显示趋势。</li><li>当前在线是采样时连接 Steam 的玩家数。采样在线均值不等于全天真实平均在线、日活、销量、收入或玩家留存。</li><li>评价比例是接口返回范围内的累计推荐比例，评论样本仅用于阅读线索。不能将评论增量直接换算为销量。</li><li>官方事件保留来源与日期；事件和在线变化在时间上相邻，不构成因果证据。</li><li>样本包含新作、长线运营、免费与付费作品，游戏类型之间可能重叠。</li><li>来源失败时保留明确标记的历史快照，缺失数据不会记为零。价格、语言与地区以来源记录和 Steam 商店实际显示为准。</li></ol>{method_extra}</div><div><h3>来源与更新时间</h3>{_sources(data)}<p>本轮采集运行于 {_time(data.get('generated_at'))}（北京时间）。单款游戏的快照时间显示在各自卡片上。</p><p>全局概览使用可取得的本轮在线值，排除已标记过期的快照；观察池会随新作发现与编辑维护扩展。</p></div></div></details></main><footer class="footer"><div><strong>策划日报 / 市场观察</strong><p>数据来源：Steam 公开接口与商店。</p></div><nav aria-label="页尾导航"><a href="index.html">回到日报</a><a href="sources.html">信息来源</a><a href="#observations">观察窗口 ↑</a></nav></footer></div><script>{SCRIPT}</script></body></html>'''


def render_market_brief(data: dict, href="market.html") -> str:
    """An honest, self-contained maximum-three-item summary for a daily edition."""
    if not isinstance(data, dict) or not data:
        return ""
    if not (_url(href) or re.fullmatch(r"(?:\.\./)*[\w/-]+\.html", str(href))):
        href = "market.html"
    games = _games(data)
    generated = _dt(data.get("generated_at"))
    today = generated.date() if generated else None
    coverage = data.get("coverage") or {}
    entries = []
    fresh_count = sum(_fresh_players(game) for game in games)
    observed = [_dt(game.get("observed_at")) for game in games if _dt(game.get("observed_at"))]
    newest = max(observed) if observed else None
    collection_note = f'本轮在线取得 {fresh_count} / {len(games)} 款'
    if fresh_count < len(games) and newest:
        collection_note += f' · 最近成功在线采样 {_time(newest)}'
    ready = [game for game in games if _window_ready(game, 7)]
    if ready:
        strongest = max(ready, key=lambda game: abs(_window(game, 7)["absolute_change"]))
        window = _window(strongest, 7)
        pct = _number(window.get("percent_change"), 1, True)
        pct_text = f"（{pct}%）" if pct != "—" else ""
        low = "；低基数，需结合绝对变化" if window.get("low_base") else ""
        entries.append(("7 天观察", strongest["name"], f"采样在线均值 {_number(window['previous'], 1)} → {_number(window['current'], 1)}，变化 {_number(window['absolute_change'], 1, True)} 人{pct_text}{low}。", f"{href}#game-{strongest['appid']}"))
    else:
        entries.append(("观察池已启动" if games else "观察池建立中", f"{len(games)} 款样本，{sum(bool(game.get('is_action')) for game in games)} 款动作游戏", f"已积累 {coverage.get('history_days', 0)} 个自然日；当前可查看快照，7 天对比等待完整历史。", f"{href}#observations"))
    dated_events = []
    for game in games:
        for event in _list(game.get("events")):
            if isinstance(event, dict) and event.get("title"):
                day = _day(event.get("date") or event.get("published"))
                if day and today and 0 <= (today - day).days <= 7:
                    dated_events.append((day, game, event))
    if dated_events:
        day, game, event = max(dated_events, key=lambda row: row[0])
        entries.append(("近期官方事件", str(game["name"]), f"{day.isoformat()} · {event['title']}。", f"{href}#game-{game['appid']}"))
    new_games = sorted([game for game in games if _new(game, today)], key=lambda game: str(game.get("release_date")), reverse=True)
    demo_games = [game for game in games if _url(game.get("demo_url"))]
    if new_games:
        game = new_games[0]
        entries.append(("新作发现", game["name"], f"{game.get('release_label') or game.get('release_date')} 发售。", f"{href}#game-{game['appid']}"))
    elif demo_games:
        game = demo_games[0]
        entries.append(("Demo", game["name"], "已收录 Steam Demo 链接。", f"{href}#game-{game['appid']}"))
    rows = ''.join(f'<article class="sm-brief-item"><span>{esc(label)}</span><h3><a href="{esc(url)}">{esc(title)}</a></h3><p>{esc(description)}</p></article>' for label, title, description, url in entries[:3])
    return f'''<style>.sm-brief{{margin-top:39px;padding-top:23px;border-top:3px double #292d27}}.sm-brief-head{{display:flex;justify-content:space-between;align-items:baseline;gap:15px}}.sm-brief-head h2{{font:700 25px/1.4 Georgia,"Noto Serif SC","Songti SC",SimSun,serif;margin:0}}.sm-brief-head>a{{font-size:11px;color:#4c6152}}.sm-brief-date{{font-size:10px;color:#74796d;margin:7px 0 0}}.sm-brief-grid{{display:grid;grid-template-columns:repeat({len(entries[:3])},minmax(0,1fr));gap:25px;margin-top:19px}}.sm-brief-item{{min-width:0}}.sm-brief-item>span{{font-size:10px;color:#4c6152}}.sm-brief-item h3{{font:700 19px/1.6 Georgia,"Noto Serif SC","Songti SC",SimSun,serif;margin:7px 0}}.sm-brief-item h3 a{{text-decoration:none;color:inherit}}.sm-brief-item p{{font-size:12px;line-height:1.9;color:#5e635a;margin:0;overflow-wrap:anywhere}}@media(max-width:760px){{.sm-brief-grid{{grid-template-columns:1fr;gap:20px}}.sm-brief-head h2{{font-size:23px}}.sm-brief-item+.sm-brief-item{{padding-top:16px;border-top:1px solid #d1d0c1}}}}</style><section class="sm-brief" id="steam-market-brief" aria-labelledby="steam-market-brief-heading"><div class="sm-brief-head"><h2 id="steam-market-brief-heading">Steam 市场观察</h2><a href="{esc(href)}">进入观察窗口 →</a></div><p class="sm-brief-date">市场本轮采集：{_time(data.get('generated_at'))}（北京时间） · 全局样本 / 动作游戏<br>{collection_note}</p><div class="sm-brief-grid">{rows}</div></section>'''


def main():
    parser = argparse.ArgumentParser(description="Render the Steam market observation page")
    parser.add_argument("--input", default=str(ROOT / "data" / "market.json"))
    parser.add_argument("--output", default=str(ROOT / "docs" / "market.html"))
    args = parser.parse_args()
    with open(args.input, encoding="utf-8") as handle:
        data = json.load(handle)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_market(data), encoding="utf-8")
    print(f"Rendered {len(_games(data))} market samples to {output}")


if __name__ == "__main__":
    main()
