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

from site_navigation import SITE_NAV_CSS, render_site_navigation

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
    value = game.get("current_players")
    return (status in ("fresh", "partial") and isinstance(value, (int, float))
            and not isinstance(value, bool) and math.isfinite(value) and value >= 0)


def _market_summary(data, games):
    """Summarise this dated snapshot without treating current size as growth."""
    if not games:
        text = "尚未取得可展示的游戏样本，暂无在线人数与涨跌摘要。"
    else:
        fresh = [game for game in games if _fresh_players(game)]
        actions = sum(bool(game.get("is_action")) for game in games)
        history_days = (data.get("coverage") or {}).get("history_days", 0)
        sentences = [f"本轮观察 {len(games)} 款游戏，包含 {actions} 款动作游戏、{len(games) - actions} 款其他类型；取得 {len(fresh)}/{len(games)} 款的本轮在线快照。"]
        if fresh:
            highest = max(fresh, key=lambda game: game["current_players"])
            leaders = [game for game in fresh if game["current_players"] == highest["current_players"]]
            link = f'<a href="#game-{esc(highest["appid"])}">{esc(highest["name"])}</a>'
            tie = f"等 {len(leaders)} 款并列" if len(leaders) > 1 else ""
            sentences.append(f"已取得快照的样本中，{link}{tie}当前在线最高，为 {_number(highest['current_players'])} 人。")
        else:
            sentences.append("本轮在线采集未成功，旧快照不参与当前在线比较。")
        cohorts = {days: [game for game in games if _window_ready(game, days)] for days in (1, 7, 30)}
        if not any(cohorts.values()):
            sentences.append(f"记录覆盖 {esc(history_days)} 个自然日，1 / 7 / 30 天窗口均暂无完整可比数据，暂不能判断上涨或下降。")
        else:
            coverage = "、".join(f"{len(cohorts[days])}/{len(games)} 款" for days in (1, 7, 30))
            sentences.append(f"记录覆盖 {esc(history_days)} 个自然日，1 / 7 / 30 天的可比覆盖分别为 {coverage}。")
            daily = cohorts[1]
            if daily:
                generated = _dt(data.get("generated_at"))
                period = (f"{(generated.date() - timedelta(days=1)):%m.%d} 较 {(generated.date() - timedelta(days=2)):%m.%d}"
                          if generated else "最近完整日较前一日")
                up = sum(_window(game, 1)["absolute_change"] > 0 for game in daily)
                down = sum(_window(game, 1)["absolute_change"] < 0 for game in daily)
                sentences.append(f"{period}，{len(daily)} 款可比样本中 {up} 款上涨、{down} 款下降、{len(daily) - up - down} 款持平。")
                strongest = max(daily, key=lambda game: abs(_window(game, 1)["absolute_change"]))
                window = _window(strongest, 1)
                if window["absolute_change"] != 0:
                    link = f'<a href="#game-{esc(strongest["appid"])}">{esc(strongest["name"])}</a>'
                    pct = _number(window.get("percent_change"), 1, True)
                    relative = f"，{pct}%" if window["previous"] > 0 and pct != "—" else ""
                    caution = "，此前基数为零，不计算百分比" if window["previous"] == 0 else "，基数较低" if window.get("low_base") else ""
                    sentences.append(f"按采样在线均值的绝对变化，{link}变化最大：{_number(window['previous'], 1)} → {_number(window['current'], 1)} 人（{_number(window['absolute_change'], 1, True)} 人{relative}{caution}）。")
            else:
                sentences.append("1 天窗口暂无完整可比数据，暂不判断日涨跌。")
        text = "".join(sentences)
    return f'<section class="daily-summary" aria-labelledby="daily-summary-title"><h2 id="daily-summary-title">数据摘要</h2><p>{text}</p></section>'


def _group_history_days(games, today):
    """Count evidenced dates within this group, never the whole pool's age."""
    dates = set()
    for game in games:
        for point in _list(game.get("history")):
            if isinstance(point, dict):
                day = _day(point.get("date"))
                if day and (today is None or day <= today):
                    dates.add(day)
        observed = _dt(game.get("players_observed_at") or game.get("observed_at"))
        if observed and (today is None or observed.date() <= today):
            dates.add(observed.date())
    return len(dates)


def _group_summary(data, games):
    """Three pre-rendered group-only summaries; the selected window is visible."""
    generated = _dt(data.get("generated_at"))
    today = generated.date() if generated else None
    fresh = [game for game in games if _fresh_players(game)]
    base = [f"本组 {len(games)} 款游戏，本轮取得 {len(fresh)}/{len(games)} 款在线快照。"]
    if fresh:
        highest = max(fresh, key=lambda game: game["current_players"])
        tied = sum(game["current_players"] == highest["current_players"] for game in fresh)
        tie = f"等 {tied} 款并列" if tied > 1 else ""
        link = f'<a href="#game-{esc(highest["appid"])}">{esc(highest["name"])}</a>'
        base.append(f"本组有效快照中，{link}{tie}当前在线最高，为 {_number(highest['current_players'])} 人。")
    elif games:
        base.append("本轮在线采集未成功，旧快照不参与当前在线比较。")
    history_days = _group_history_days(games, today)
    history = f"组内已有记录涉及 {history_days} 个自然日。" if history_days else "组内历史日期尚未取得。"
    panels = []
    for days in (1, 7, 30):
        hidden = ' hidden' if days != 7 else ''
        if not games:
            text = "本组尚未取得可展示的游戏样本，暂无在线人数与涨跌摘要。"
        else:
            cohort = [game for game in games if _window_ready(game, days)]
            sentences = base + [history, f"{days} 天窗口：{len(cohort)} / {len(games)} 款具备完整可比记录。"]
            if not cohort:
                sentences.append("暂不能判断本组上涨或下降。")
            else:
                up = sum(_window(game, days)["absolute_change"] > 0 for game in cohort)
                down = sum(_window(game, days)["absolute_change"] < 0 for game in cohort)
                sentences.append(f"本组可比作品中 {up} 款上涨、{down} 款下降、{len(cohort) - up - down} 款持平。")
                strongest = max(cohort, key=lambda game: abs(_window(game, days)["absolute_change"]))
                window = _window(strongest, days)
                if window["absolute_change"] != 0:
                    link = f'<a href="#game-{esc(strongest["appid"])}">{esc(strongest["name"])}</a>'
                    pct = _number(window.get("percent_change"), 1, True)
                    relative = f"，{pct}%" if window["previous"] > 0 and pct != "—" else ""
                    caution = "，此前基数为零，不计算百分比" if window["previous"] == 0 else "，基数较低" if window.get("low_base") else ""
                    sentences.append(f"按采样在线均值的绝对变化，{link}变化最大：{_number(window['previous'], 1)} → {_number(window['current'], 1)} 人（{_number(window['absolute_change'], 1, True)} 人{relative}{caution}）。")
            text = ''.join(sentences)
        panels.append(f'<p data-group-summary="{days}"{hidden}>{text}</p>')
    return '<div class="daily-summary group-summary">' + ''.join(panels) + '</div>'


def _group_section(data, games, today, kind):
    title = "动作游戏观察" if kind == "action" else "其他类型观察"
    anchor = f"{kind}-observation"
    empty = '<p class="group-empty">本组暂时没有已收录的游戏。</p>' if not games else ''
    return (f'<section class="observation-group" id="{anchor}" data-market-group="{kind}" aria-labelledby="{anchor}-title">'
            f'<div class="section-top"><h2 id="{anchor}-title">{title}</h2><p>{len(games)} 款 · 本组单独统计</p></div>'
            f'{_group_summary(data, games)}<div class="games">' + ''.join(_card(game, today) for game in games) +
            f'</div>{empty}</section>')


def _trend(game, days):
    window = _window(game, days)
    hidden = ' hidden' if days != 7 else ''
    if not _window_ready(game, days):
        status = window.get("status")
        title = {"no_baseline": "暂无可比基数", "not_released": "尚未发售", "missing_data": "记录存在缺口"}.get(status, "历史积累中")
        reason = window.get("reason") or f"需要两个完整的 {days} 天窗口，才显示可比变化。"
        return (f'<div class="trend trend-pending" data-trend="{days}"{hidden}>'
                f'<strong title="{esc(reason)}">{title}</strong><span>{esc(reason)}</span></div>')
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
    badge_html = ''.join(f'<span>{esc(badge)}</span>' for badge in badges)
    genre_html = ' · '.join(esc(label) for label in genres[:3]) or "类型待补充"
    review_source = _url(summary.get("source")) or str(store).rstrip('/') + '/#app_reviews_hash'
    mode_html = ' · '.join(esc(label) for label in modes) or "玩家模式待补充"
    demo_link = _link(game.get("demo_url"), "前往 Demo") if _url(game.get("demo_url")) else ''
    errors = '<p class="detail-caveat">部分来源暂未返回结果；缺失值不会记为零。</p>' if game.get("errors") else ''
    stale_review = ' · 旧值' if summary.get("status") == "stale" else ''
    stale_price = ' · 旧值' if game.get("metadata_status") == "stale" else ''
    return f'''<article class="game-card" id="game-{appid}" data-game data-action="{str(bool(game.get('is_action'))).lower()}" data-new="{str(_new(game, today)).lower()}" data-demo="{str(bool(_url(game.get('demo_url')))).lower()}">
<div class="game-row">{_cover(game, store)}<div class="game-identity"><div class="game-badges">{badge_html}</div><h3>{_link(store, game['name'])}</h3><p class="game-genres">{genre_html}</p><div class="game-meta"><span>{esc(price_text)}{stale_price}</span><span>{esc(released)}</span></div></div>
<dl class="game-metrics"><div><dt>{'最近已知在线' if players_status == 'stale' else '当前在线'}</dt><dd>{_number(game.get('current_players'))}<small>人</small></dd></div><div><dt>中英文评价推荐比例</dt><dd>{positive_label}</dd><small>{_number(summary.get('total'))} 条累计评价{stale_review}</small></div></dl>
<div class="card-trend"><div class="window-caption"><span data-window-label>7 天变化</span><span>采样在线均值</span></div>{''.join(_trend(game, days) for days in (1, 7, 30))}</div></div>
<details class="game-details"><summary><span class="snapshot-state state-{esc(players_status)}">{state} · {_time(game.get('observed_at'), False)}</span><span class="detail-toggle">玩家评价与官方公告 <span aria-hidden="true">＋</span></span></summary><div class="detail-body">
<p class="detail-mode">玩家模式：{mode_html}</p>{metadata_note}<p class="detail-caveat">{review_stamp}</p>
<div class="detail-columns"><section><h4>官方事件</h4>{_events(game)}</section><section><h4>玩家原声 · 原文摘录</h4>{_reviews(game)}</section></div>
{errors}<div class="game-links">{_link(store, 'Steam 商店')}{_link(review_source, '全部评价')}{demo_link}<a class="permalink" href="#game-{appid}" aria-label="{esc(game['name'])}的页内链接">页内链接 #</a></div></div></details></article>'''



CSS = r'''
:root{color-scheme:light;--paper:#f1ede3;--panel:#faf8f1;--ink:#292d27;--soft:#5e635a;--muted:#74796d;--line:#d1d0c1;--rust:#9b493b;--sage:#4c6152;--wash:#e7eadf;--serif:Georgia,"Noto Serif SC","Songti SC",SimSun,serif;--sans:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;--mono:ui-monospace,SFMono-Regular,Consolas,monospace}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:20px}body{margin:0;background:var(--paper);color:var(--ink);font:14px/1.65 var(--sans)}a{color:inherit;text-underline-offset:4px}a:hover{color:var(--rust)}a:focus-visible,button:focus-visible,summary:focus-visible{outline:3px solid var(--rust);outline-offset:4px}[hidden]{display:none!important}button,summary{font:inherit;cursor:pointer}h1,h2,h3,h4,p,dl,dd{margin:0}h1,h2,h3{font-family:var(--serif)}.wrap{width:min(1180px,100% - 64px);margin:auto}.skip{position:fixed;left:14px;top:12px;transform:translateY(-200%);z-index:20;background:var(--ink);color:#fff;padding:8px}.skip:focus{transform:none}
.masthead{padding-top:22px}.masthead-top{display:flex;justify-content:space-between;gap:16px;font-size:11px;color:var(--soft)}.masthead-top a{text-decoration:none}.masthead-top span{font:10px var(--mono);letter-spacing:.08em}.brand-row{display:flex;justify-content:space-between;align-items:center;gap:20px;padding:18px 0}.brand-row h1{font-size:36px;line-height:1.25}.edition{font-size:11px;color:var(--soft);text-align:right}.edition b{display:block;font:18px var(--serif);color:var(--ink);margin-bottom:3px}.nav{display:flex;flex-wrap:wrap;gap:26px;border-top:2px solid var(--ink);border-bottom:1px solid var(--line);padding:11px 0;font-size:12px}.nav a{text-decoration:none}.nav [aria-current=page]{color:var(--sage);font-weight:700}
.daily-summary{padding:19px 0 12px}.daily-summary h2{font:600 13px var(--sans);color:var(--sage);margin-bottom:8px}.daily-summary p{font-size:14px;line-height:1.95;color:var(--soft);overflow-wrap:anywhere}.daily-summary a{color:var(--ink);text-decoration-color:var(--line)}.coverage-note{font-size:11px;color:var(--muted);line-height:1.8}.coverage-note a{color:var(--sage)}
.observation{margin-top:24px}.section-top{display:flex;justify-content:space-between;align-items:center;gap:20px}.section-top h2{font-size:23px}.section-top p{font-size:11px;color:var(--soft)}.window-controls{display:flex;align-items:center;gap:12px;font-size:11px;color:var(--soft)}.button-group{display:flex;gap:4px}.button-group button{padding:5px 12px;font-size:12px;border:1px solid var(--line);background:transparent;color:var(--soft);border-radius:3px}.button-group button[aria-pressed=true]{background:var(--sage);color:var(--panel);border-color:var(--sage)}.window-note{font-size:11px;color:var(--soft);line-height:1.8;margin:10px 0 14px}.games{display:flex;flex-direction:column;gap:10px}
.game-card{min-width:0;border:1px solid var(--line);background:var(--panel);scroll-margin-top:20px;border-radius:5px;overflow:hidden}.game-card:target{outline:2px solid var(--sage);outline-offset:3px}.game-row{display:grid;grid-template-columns:150px minmax(200px,1fr) 224px 245px;gap:22px;align-items:center;padding:17px 20px}.game-cover{display:grid;place-items:center;position:relative;aspect-ratio:460/215;background:#e3e5dc;overflow:hidden;border-radius:3px;text-decoration:none}.game-cover img{position:absolute;inset:0;display:block;width:100%;height:100%;object-fit:cover}.cover-fallback{font-size:11px;color:var(--soft)}.game-identity{min-width:0}.game-badges{display:flex;gap:5px;flex-wrap:wrap}.game-badges span{font-size:9px;color:var(--sage);background:var(--wash);padding:1px 5px;border-radius:2px}.game-identity h3{font-size:20px;line-height:1.35;margin:5px 0;overflow-wrap:anywhere}.game-identity h3 a{text-decoration:none}.game-genres{font-size:10px;color:var(--muted)}.game-meta{display:flex;flex-wrap:wrap;gap:3px 12px;font-size:10px;color:var(--soft);margin-top:6px}.game-metrics{display:grid;grid-template-columns:1fr 1.2fr;gap:15px}.game-metrics dt{font-size:10px;color:var(--soft);margin-bottom:5px}.game-metrics dd{font:24px/1.3 var(--serif)}.game-metrics dd small{display:inline;font:10px var(--sans);margin-left:4px}.game-metrics small{display:block;font:9px/1.6 var(--sans);color:var(--muted);margin-top:4px}.card-trend{min-width:0;border-left:1px solid var(--line);padding-left:20px}.window-caption{display:flex;justify-content:space-between;gap:8px;font-size:10px;color:var(--soft)}.window-caption>span:last-child{font-size:9px;color:var(--muted)}.trend{padding-top:7px}.trend>span{display:block;font-size:9px;color:var(--soft);margin-top:3px;line-height:1.6}.trend-line{display:flex;justify-content:space-between;align-items:baseline;gap:7px}.trend-line strong{font:22px var(--serif)}.trend-line strong small{font:10px var(--sans)}.trend-line b{font:12px var(--mono)}.trend-pending strong{font-size:14px;font-weight:400;color:var(--muted)}.trend-pending>span{display:none}.up{color:var(--sage)}.down,.low-base{color:var(--rust)}.flat{color:var(--soft)}
.game-details{border-top:1px solid var(--line)}.game-details>summary{display:flex;justify-content:space-between;align-items:center;gap:14px;list-style:none;padding:7px 20px;background:rgba(231,234,223,.25)}.game-details>summary::-webkit-details-marker{display:none}.snapshot-state{font-size:9px;color:var(--muted)}.state-stale,.state-unavailable{color:var(--rust)}.detail-toggle{display:flex;align-items:center;gap:12px;font-size:10px;color:var(--sage);white-space:nowrap}.detail-toggle>span{font-size:15px;line-height:1}.game-details[open] .detail-toggle>span{transform:rotate(45deg)}.detail-body{padding:18px 20px 20px;border-top:1px solid var(--line)}.detail-mode{font-size:11px;color:var(--soft)}.metadata-stamp,.detail-caveat{font-size:10px;color:var(--muted);margin-top:6px;line-height:1.8}.detail-caveat small{font-size:inherit}.detail-columns{display:grid;grid-template-columns:1fr 1fr;gap:30px;margin-top:14px}.detail-columns h4{font-size:12px;color:var(--sage);margin-bottom:8px}.detail-empty{font-size:11px;color:var(--soft)}.event-list{list-style:none;padding:0;margin:8px 0}.event-list li{font-size:12px;padding:9px 0;border-bottom:1px dotted var(--line)}.event-list a{text-decoration:none;overflow-wrap:anywhere}.event-date{display:block;font:10px var(--mono);color:var(--muted);margin-bottom:4px}blockquote{margin:10px 0 0;padding:10px 12px;border-left:2px solid var(--line);background:var(--paper)}blockquote p{font-size:12px;color:var(--soft);overflow-wrap:anywhere}blockquote footer{font-size:10px;color:var(--muted);margin-top:6px}.game-links{display:flex;flex-wrap:wrap;gap:18px;font-size:11px;margin-top:16px}.muted{color:var(--soft)}
.scope-section{margin-top:14px;border-top:1px solid var(--line);padding:12px 0}.scope-section>summary{display:flex;justify-content:space-between;align-items:center;font-size:14px;color:var(--soft)}.scope-section>summary span{font-size:10px;color:var(--muted)}.overview-summary{display:flex;align-items:center;gap:12px}.disclosure-symbol{font-size:14px!important}.scope-section[open] .disclosure-symbol{transform:rotate(45deg)}.segment-grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));margin-top:15px;border:1px solid var(--line)}.segment{padding:13px;border-right:1px solid var(--line)}.segment:last-child{border:0}.segment h3{font:12px var(--sans);margin-bottom:5px}.segment strong{font:21px var(--serif)}.segment span{font-size:10px;color:var(--soft);display:block;margin-top:5px}.segment-trend{margin-top:11px;padding-top:10px;border-top:1px solid var(--line)}.segment-trend b{font-size:10px;line-height:1.7;overflow-wrap:anywhere}.segment-trend span{font-size:9px}.scope-caveat{font-size:10px;color:var(--muted);margin-top:10px;line-height:1.8}
.discovery{margin-top:28px;padding-top:22px;border-top:1px solid var(--line)}.discovery .section-top h2{font-size:22px}.discovery-deck{font-size:12px;color:var(--soft);margin-top:10px}.discovery-links{display:flex;gap:16px;flex-wrap:wrap;margin-top:12px;font-size:11px}.discovery-state{font-size:10px;color:var(--muted);margin-top:12px}.discovery-list{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px 24px;list-style:none;padding:0;margin:12px 0}.discovery-list li{border-bottom:1px solid var(--line);padding:8px 0;font-size:12px}.discovery-list a{text-decoration:none;overflow-wrap:anywhere}.discovery-list small{display:block;font-size:10px;color:var(--muted);margin-top:4px}.other-discovery{margin-top:15px}.other-discovery>summary{font-size:12px;color:var(--soft)}.methodology{margin-top:24px;border-top:1px solid var(--line);padding-top:14px}.methodology>summary{font-size:15px;font-weight:600}.method-grid{display:grid;grid-template-columns:1.3fr 1fr;gap:35px;padding:20px 0}.method-grid h3{font-size:17px;margin-bottom:10px}.method-grid p,.method-grid li{font-size:11px;color:var(--soft);line-height:1.9}.method-grid ul,.method-grid ol{padding-left:19px;margin:0}.method-grid li+li,.method-grid p+p{margin-top:9px}.method-grid a{overflow-wrap:anywhere}.empty-state{padding:35px;text-align:center;border:1px solid var(--line)}.empty-state h3{font-size:20px}.empty-state p{font-size:12px;margin-top:8px;color:var(--soft)}.footer{display:flex;justify-content:space-between;gap:25px;border-top:1px solid var(--line);margin-top:26px;padding:20px 0 25px;font-size:10px;color:var(--muted)}.footer strong{font-size:13px;color:var(--soft)}.footer p{margin-top:4px}.footer nav{display:flex;gap:20px}noscript p{font-size:11px;color:var(--soft);margin:10px 0}
@media(max-width:1100px){.game-row{grid-template-columns:125px minmax(150px,1fr) 192px 190px;gap:16px;padding:16px}.game-metrics{gap:10px}.card-trend{padding-left:15px}.game-identity h3{font-size:18px}.game-metrics dd{font-size:22px}.trend-line{flex-wrap:wrap;gap:3px}.trend-line strong{font-size:19px}}
@media(max-width:850px){.wrap{width:calc(100% - 40px)}.game-row{grid-template-columns:150px minmax(0,1fr);gap:15px 20px}.game-metrics{grid-column:1;gap:14px;grid-template-columns:1fr 1fr}.card-trend{grid-column:2;align-self:stretch}.game-identity h3{font-size:21px}.game-metrics dt{font-size:9px}.game-metrics dd{font-size:22px}.segment-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.segment:nth-child(3){border-right:0}.segment:nth-child(-n+3){border-bottom:1px solid var(--line)}.detail-columns{gap:20px}.discovery-list{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:550px){.wrap{width:calc(100% - 28px)}.masthead{padding-top:16px}.masthead-top{font-size:10px}.masthead-top span{font-size:8px}.brand-row{display:block;padding:16px 0 13px}.brand-row h1{font-size:29px}.edition{text-align:left;margin-top:9px;font-size:10px}.edition b{display:inline;font-size:13px;margin-right:12px}.nav{gap:20px;font-size:11px;padding:10px 0}.daily-summary{padding-top:15px}.daily-summary p{font-size:13px}.coverage-note{font-size:10px}.observation{margin-top:20px}.section-top{gap:12px;align-items:center;flex-wrap:wrap}.section-top h2{font-size:21px}.window-controls{gap:7px}.window-controls>span{display:none}.button-group button{font-size:11px;padding:5px 10px}.window-note{font-size:10px;margin:10px 0}.game-row{grid-template-columns:112px minmax(0,1fr);gap:14px;padding:14px}.game-identity h3{font-size:18px}.game-badges span{font-size:8px}.game-meta,.game-genres{font-size:9px}.game-metrics{grid-column:1/-1;display:grid;grid-template-columns:1fr 1fr;border-top:1px solid var(--line);padding-top:12px}.game-metrics dt{font-size:10px}.game-metrics dd{font-size:24px}.card-trend{grid-column:1/-1;border-left:0;border-top:1px solid var(--line);padding:10px 0 0;display:grid;grid-template-columns:96px minmax(0,1fr);gap:12px;align-items:start}.window-caption{display:block;line-height:1.7}.window-caption>span{display:block}.trend{padding-top:0}.trend-pending strong{font-size:13px}.trend-line{justify-content:flex-start;gap:12px}.game-details>summary{padding:8px 14px;gap:8px}.snapshot-state{font-size:8px}.detail-toggle{font-size:9px;gap:7px}.detail-body{padding:14px}.detail-columns,.method-grid{grid-template-columns:1fr;gap:20px}.detail-columns h4{font-size:12px}.discovery-list{grid-template-columns:1fr}.scope-section>summary{align-items:flex-start;gap:12px}.scope-section>summary span{max-width:150px;text-align:right}.segment{padding:10px}.segment h3{font-size:10px}.segment span{font-size:9px}.footer{display:block}.footer nav{margin-top:12px}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}@media print{body{background:#fff}.wrap{width:100%}.nav,.window-controls,.skip{display:none}.game-card{break-inside:avoid}.game-row{grid-template-columns:110px 1fr 180px 180px;gap:12px}.methodology{display:none}}
'''


CSS += SITE_NAV_CSS


CSS += r'''
.observation-directory{display:flex;gap:10px 24px;flex-wrap:wrap;font-size:13px}.observation-directory a{text-decoration:none;color:var(--sage);border-bottom:1px solid var(--line);padding:4px 0}.observation-directory small{font-size:10px;color:var(--muted);margin-left:5px}.observation-group{scroll-margin-top:20px}.observation-group+.observation-group{margin-top:32px;padding-top:24px;border-top:2px solid var(--line)}.group-summary{padding:9px 0 14px}.group-summary p{font-size:12px;line-height:1.85}.group-empty{font-size:12px;color:var(--muted);padding:16px 0}.observations-toolbar{margin-bottom:12px}.observations-toolbar .window-note{margin-bottom:0}
@media(max-width:650px){.observations-toolbar>.section-top{align-items:flex-start;flex-direction:column;gap:12px}.observation-directory{gap:10px 19px}.observation-group>.section-top{gap:10px}.observation-group>.section-top h2{font-size:22px}.observation-group>.section-top p{font-size:10px}.group-summary p{font-size:12px}}
'''


SCRIPT = r'''
(() => {
  document.querySelectorAll('.game-cover img').forEach(image => {
    const unavailable = () => { image.hidden = true; image.nextElementSibling.hidden = false; };
    image.addEventListener('error', unavailable);
    if (image.complete && !image.naturalWidth) unavailable();
  });
  const buttons = Array.from(document.querySelectorAll('[data-days]'));
  const cards = Array.from(document.querySelectorAll('[data-game]'));
  const params = new URLSearchParams(location.search);
  let days = ['1', '7', '30'].includes(params.get('days')) ? params.get('days') : '7';
  function apply() {
    cards.forEach(card => {
      card.querySelectorAll('[data-trend]').forEach(panel => { panel.hidden = panel.dataset.trend !== days; });
      card.querySelector('[data-window-label]').textContent = `${days} 天变化`;
    });
    buttons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.days === days)));
    document.querySelectorAll('[data-segment-trend]').forEach(panel => { panel.hidden = panel.dataset.segmentTrend !== days; });
    document.querySelectorAll('[data-group-summary]').forEach(panel => { panel.hidden = panel.dataset.groupSummary !== days; });
    document.getElementById('scope-window-label').textContent = `当前快照与 ${days} 天变化`;
    document.getElementById('window-note').textContent = `两组统一查看 ${days} 天窗口，分别统计可比覆盖。比较最近 ${days} 个完整日与此前 ${days} 日；当前在线规模不代表涨幅。`;
    const url = new URL(location.href);
    ['scope', 'q', 'genre', 'mode', 'view'].forEach(key => url.searchParams.delete(key));
    if (days === '7') url.searchParams.delete('days'); else url.searchParams.set('days', days);
    try { history.replaceState(null, '', url.pathname + url.search + url.hash); } catch (_) {}
  }
  buttons.forEach(button => button.addEventListener('click', () => { days = button.dataset.days; apply(); }));
  const controls = document.querySelector('.window-controls');
  if (controls) controls.hidden = false;
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
<div class="discovery-links">{_link('https://store.steampowered.com/search/?sort_by=Released_DESC&category1=998', 'Steam 最新发行')}{_link('https://store.steampowered.com/demos/', 'Steam Demo')}</div>{discovery_state}{body}{other}</section>'''


def render_market(data: dict) -> str:
    games = _games(data)
    generated = _dt(data.get("generated_at"))
    today = generated.date() if generated else None
    coverage = data.get("coverage") or {}
    history_start = coverage.get("history_start") or "尚未开始"
    scope_note = coverage.get("scope_note") or "精选作品与公开发现样本，不代表 Steam 全站；分类之间可能重叠。"
    action_games = [game for game in games if game.get("is_action")]
    other_games = [game for game in games if not game.get("is_action")]
    methods = []
    for method in _list(data.get("methodology")):
        text = method.get("text") or method.get("note") or method.get("description") if isinstance(method, dict) else method
        if text:
            methods.append(f'<li>{esc(text)}</li>')
    method_extra = '<ul>' + ''.join(methods) + '</ul>' if methods else ''
    empty = '' if games else '<div class="empty-state"><h3>正在建立第一批市场记录</h3><p>还没有可展示的游戏数据。下方保留 Steam 官方发现入口，采集成功后会显示真实快照。</p></div>'
    return f'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="策划日报的 Steam 市场观察：全局样本与动作游戏，持续记录在线变化、玩家声音、官方事件和新作。"><title>Steam 市场观察 · 策划日报</title><style>{CSS}</style></head><body>
<a class="skip" href="#observations">跳到游戏观察</a><div class="wrap">{render_site_navigation("market")}<header class="masthead"><div class="brand-row"><div><h1>Steam 市场观察</h1></div><div class="edition"><b>{esc(generated.strftime('%Y.%m.%d') if generated else '记录建立中')}</b>本轮采集 {_time(data.get('generated_at'), False)} · 北京时间</div></div></header>
<main><p class="coverage-note">动作与其他类型分组观察，每款游戏只列入一组。样本不代表 Steam 全市场。<a href="#methodology">数据口径</a></p>
<section class="observation" id="observations"><div class="observations-toolbar"><div class="section-top"><nav class="observation-directory" aria-label="市场观察分区"><a href="#action-observation">动作游戏观察<small>{len(action_games)} 款</small></a><a href="#other-observation">其他类型观察<small>{len(other_games)} 款</small></a></nav><div class="window-controls" hidden><span>变化窗口</span><div class="button-group" role="group" aria-label="时间窗口"><button type="button" data-days="1" aria-pressed="false">1 天</button><button type="button" data-days="7" aria-pressed="true">7 天</button><button type="button" data-days="30" aria-pressed="false">30 天</button></div></div></div>
<noscript><p>当前显示 7 天窗口；启用 JavaScript 后可以切换时间窗口。</p></noscript>
<p class="window-note" id="window-note" aria-live="polite">两组统一查看 7 天窗口，分别统计可比覆盖。比较最近 7 个完整日与此前 7 日；当前在线规模不代表涨幅。</p></div>
{_group_section(data, action_games, today, 'action')}{_group_section(data, other_games, today, 'other')}{empty}</section>
<details class="scope-section" id="market-overview"><summary>全部样本的分类概览 <span class="overview-summary"><span id="scope-window-label">当前快照与 7 天变化</span><span class="disclosure-symbol" aria-hidden="true">＋</span></span></summary>{_segments(games)}<p class="scope-caveat">{esc(scope_note)} 此处汇总动作与其他类型全部样本，不是其他类型的分组摘要。分类之间可重叠，合计不可相加。变化仅比较两段都有完整记录的同一批游戏；当前在线合计来自各作品最近一次采样，并非同一时刻的人数。</p></details>

{_discovery(data, games, today)}
<details class="methodology" id="methodology"><summary>数据口径与来源</summary><div class="method-grid"><div><h3>记录边界与比较方式</h3><p>观察池由固定跟踪作品和自动发现作品组成。自动发现读取 Steam 新发行、即将推出、热销与热门游戏榜，覆盖各类游戏；动作标记来自 Steam 标签及维护名单。发现线索需确认游戏资料并有空余观察名额，才加入持续采样。</p><ol><li>1 / 7 / 30 天窗口分别比较最近完整日与此前等长窗口。每一天先汇总当天采样值，再比较两个窗口；尚未完整积累时不显示趋势。</li><li>当前在线是采样时连接 Steam 的玩家数。采样在线均值不等于全天真实平均在线、日活、销量、收入或玩家留存。</li><li>评价比例是接口返回范围内的累计推荐比例，评论样本仅用于阅读线索。不能将评论增量直接换算为销量。</li><li>官方事件保留来源与日期；事件和在线变化在时间上相邻，不构成因果证据。</li><li>样本包含新作、长线运营、免费与付费作品，游戏类型之间可能重叠。</li><li>来源失败时保留明确标记的历史快照，缺失数据不会记为零。价格、语言与地区以来源记录和 Steam 商店实际显示为准。</li></ol>{method_extra}</div><div><h3>来源与更新时间</h3>{_sources(data)}<p>本轮采集运行于 {_time(data.get('generated_at'))}（北京时间）。单款游戏的快照时间显示在各自卡片上。</p><p>全局概览使用可取得的本轮在线值，排除已标记过期的快照；观察池会随新作发现与编辑维护扩展。</p></div></div></details></main><footer class="footer"><div><strong>策划日报 / 市场观察</strong><p>数据来源：Steam 公开接口与商店。</p></div><nav aria-label="页尾导航"><a href="index.html">回到日报</a><a href="sources.html">信息来源</a><a href="#observations">观察窗口 ↑</a></nav></footer></div><script>{SCRIPT}</script></body></html>'''


def render_market_brief(data: dict, href="market.html") -> str:
    """An honest, self-contained maximum-three-item summary for a daily edition."""
    if not isinstance(data, dict) or not data:
        return ""
    if data.get("market_scope") == "global":
        from global_market_render import render_global_brief
        return render_global_brief(data, href)
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
    return f'''<style>.sm-brief{{margin-top:39px;padding-top:23px;border-top:3px double #292d27}}.sm-brief-head{{display:flex;justify-content:space-between;align-items:baseline;gap:15px}}.sm-brief-head h2{{font:700 25px/1.4 Georgia,"Noto Serif SC","Songti SC",SimSun,serif;margin:0}}.sm-brief-head>a{{font-size:11px;color:#4c6152}}.sm-brief-date{{font-size:10px;color:#74796d;margin:7px 0 0}}.sm-brief-grid{{display:grid;grid-template-columns:repeat({len(entries[:3])},minmax(0,1fr));gap:25px;margin-top:19px}}.sm-brief-item{{min-width:0}}.sm-brief-item>span{{font-size:10px;color:#4c6152}}.sm-brief-item h3{{font:700 19px/1.6 Georgia,"Noto Serif SC","Songti SC",SimSun,serif;margin:7px 0}}.sm-brief-item h3 a{{text-decoration:none;color:inherit}}.sm-brief-item p{{font-size:12px;line-height:1.9;color:#5e635a;margin:0;overflow-wrap:anywhere}}@media(max-width:760px){{.sm-brief-grid{{grid-template-columns:1fr;gap:20px}}.sm-brief-head h2{{font-size:23px}}.sm-brief-item+.sm-brief-item{{padding-top:16px;border-top:1px solid #d1d0c1}}}}</style><section class="sm-brief" id="steam-market-brief" aria-labelledby="steam-market-brief-heading"><div class="sm-brief-head"><h2 id="steam-market-brief-heading">Steam 市场摘要</h2><a href="{esc(href)}">查看市场页 →</a></div><p class="sm-brief-date">市场本轮采集：{_time(data.get('generated_at'))}（北京时间） · 全局样本 / 动作游戏<br>{collection_note}</p><div class="sm-brief-grid">{rows}</div></section>'''


def render_action_market(data=None):
    """Keep existing bookmarks working after merging into the global page."""
    return '''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="0;url=market.html"><link rel="canonical" href="market.html"><title>Steam 市场观察</title></head><body><p><a href="market.html">前往 Steam 市场观察</a></p></body></html>'''


def main():
    parser = argparse.ArgumentParser(description="Render the Steam market observation page")
    parser.add_argument("--input", default=str(ROOT / "data" / "global_market.json"))
    parser.add_argument("--output", default=str(ROOT / "docs" / "market.html"))
    args = parser.parse_args()
    data = json.loads(Path(args.input).read_text(encoding="utf-8")) if Path(args.input).exists() else {}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    from global_market_render import render_global_market
    output.write_text(render_global_market(data), encoding="utf-8")
    output.with_name("market-action.html").write_text(render_action_market(), encoding="utf-8")
    print(f"Rendered {len(_games(data))} market samples to {output}")


if __name__ == "__main__":
    main()
