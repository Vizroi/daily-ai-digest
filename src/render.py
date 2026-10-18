"""A self-contained newspaper reader for the v3 game-design daily.

Public render(digest, health=None) and CLI arguments remain compatible. Diagnostics
stay in logs, previews are marked, and existing historical HTML is never replaced.
"""
import argparse
import hashlib
import html
import json
import os
import re
import sys
from datetime import date, datetime, timezone, timedelta
from urllib.parse import urlparse

from site_navigation import SITE_NAV_CSS, render_site_navigation

TZ = timezone(timedelta(hours=8))
SITE = os.environ.get("DIGEST_SITE", "https://vizroi.github.io/daily-ai-digest").rstrip("/")
WEEKDAY_CN = ["一", "二", "三", "四", "五", "六", "日"]

CSS = r"""
:root{color-scheme:light;--paper:#f1ede3;--panel:#faf8f1;--ink:#292d27;--soft:#5e635a;--muted:#74796d;--line:#d1d0c1;--rust:#9b493b;--sage:#4c6152;--wash:#e7eadf;--serif:Georgia,"Noto Serif SC","Source Han Serif SC","Songti SC",SimSun,serif;--sans:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;--mono:ui-monospace,SFMono-Regular,Consolas,monospace}
*,*::before,*::after{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:24px;-webkit-text-size-adjust:100%}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.85 var(--sans)}a{color:inherit;text-underline-offset:4px;text-decoration-thickness:1px}a:hover{color:var(--rust)}button,input,select{font:inherit}button,select{cursor:pointer}a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible{outline:3px solid var(--rust);outline-offset:4px}h1,h2,h3,p,dl,dd{margin:0}h1,h2,h3{text-wrap:balance}p{text-wrap:pretty}[hidden]{display:none!important}.wrap{width:min(1180px,100% - 88px);margin-inline:auto}.skip-link{position:fixed;top:10px;left:12px;z-index:20;padding:8px 16px;background:var(--ink);color:var(--panel);transform:translateY(-180%)}.skip-link:focus{transform:translateY(0)}.overline{font:10px var(--mono);letter-spacing:.17em;color:var(--sage)}
.masthead{padding-top:27px}.masthead-top{display:flex;justify-content:space-between;align-items:center;gap:16px;padding-bottom:13px;border-bottom:1px solid var(--line);font-size:11px;letter-spacing:.09em;color:var(--soft)}.top-links{display:flex;gap:22px;flex-wrap:wrap}.top-links a{text-decoration:none}.brand-row{display:flex;justify-content:space-between;align-items:center;gap:30px;padding:30px 0 26px}.brand{min-width:0}.brand h1{font:900 clamp(42px,5.8vw,72px)/1.2 var(--serif);letter-spacing:.06em}.brand-en{margin-top:10px;font:12px var(--mono);letter-spacing:.29em;color:var(--soft)}.edition{text-align:right;flex-shrink:0}.edition-date{font:27px/1.3 var(--serif);letter-spacing:.02em}.edition-day{margin-top:6px;font-size:11px;color:var(--soft);letter-spacing:.06em}.edition-status{display:inline-block;margin-top:10px;padding:2px 9px;border:1px solid var(--sage);color:var(--sage);font-size:10px;letter-spacing:.1em}.edition-status.preview{border-color:var(--rust);color:var(--rust)}.strapline{display:flex;justify-content:space-between;align-items:center;gap:16px;padding:10px 0;border-top:3px solid var(--ink);border-bottom:1px solid var(--ink);font-size:12px;color:var(--soft)}.strapline strong{font-weight:500;color:var(--ink)}.edition-count{font:10px var(--mono);white-space:nowrap}.nav{display:flex;gap:28px;flex-wrap:wrap;padding:14px 0;border-bottom:1px solid var(--line)}.nav a{text-decoration:none;font-size:12px;font-weight:600}.nav small{font:10px var(--mono);color:var(--muted);margin-left:5px}.preview-note{margin-top:20px;padding:12px 16px;border-left:3px solid var(--rust);background:#eee2d6;color:#754235;font-size:12px}.preview-note strong{margin-right:8px}
.edition-grid{display:grid;grid-template-columns:minmax(0,1fr) 258px;gap:48px;align-items:start;margin-top:44px}.main-column,.sidebar{min-width:0}.section-head{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;padding-bottom:18px;border-bottom:2px solid var(--ink)}.section-kicker{display:block;margin-bottom:7px;font:10px var(--mono);letter-spacing:.16em;color:var(--sage)}.section-head h2{font:700 29px/1.35 var(--serif);letter-spacing:.02em}.section-subtitle{margin-top:8px;font-size:12px;color:var(--soft)}.section-count{flex-shrink:0;font-size:11px;color:var(--soft);white-space:nowrap}.section-count b{font:24px/1 var(--serif);color:var(--ink);margin-right:4px}
.filter-panel{padding:17px 0 13px;border-bottom:1px solid var(--line)}.filter-fields{display:grid;grid-template-columns:minmax(180px,1fr) minmax(105px,145px) minmax(90px,116px);gap:10px}.field{display:block;min-width:0}.field span{display:block;margin-bottom:5px;font-size:10px;color:var(--soft);letter-spacing:.07em}.field input,.field select{width:100%;min-width:0;height:39px;border:1px solid #b9bdaf;border-radius:0;background:var(--panel);padding:0 11px;color:var(--ink);font-size:12px}.field input::placeholder{color:var(--muted)}.field input:focus,.field select:focus{border-color:var(--sage)}.filter-footer{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-top:10px;font-size:10px;color:var(--soft)}.text-button{border:0;padding:3px 0;background:transparent;color:var(--sage);font-size:11px;text-decoration:underline;text-underline-offset:3px}.filter-empty{padding:42px 22px;border-bottom:1px solid var(--line);text-align:center}.filter-empty h3{font:21px var(--serif);margin-bottom:8px}.filter-empty p{font-size:12px;color:var(--soft);margin-bottom:14px}
.news-list{list-style:none;padding:0;margin:0}.news-item{padding:23px 0 24px;border-bottom:1px solid var(--line);scroll-margin-top:24px}.story-topline{display:flex;align-items:center;gap:10px;margin-bottom:9px;font-size:10px;line-height:1.5;color:var(--soft)}.story-number{font:11px var(--mono);color:var(--muted);font-variant-numeric:tabular-nums}.topic{color:var(--sage);font-size:10px;letter-spacing:.04em}.topic::before{content:"";display:inline-block;width:5px;height:5px;margin:0 7px 1px 0;background:var(--sage)}.story-date{margin-left:auto;font:10px var(--mono);color:var(--soft);white-space:nowrap}.permalink{text-decoration:none;color:var(--muted);font:12px var(--mono);padding:1px 4px}.news-title{font:700 22px/1.55 var(--serif);letter-spacing:.005em}.news-title a,.feature-title a,.ai-title a{text-decoration:none}.news-list>li:first-child .news-title{font-size:29px;line-height:1.5}.original-title{display:block;margin-top:5px;font:400 11px/1.65 var(--sans);color:var(--muted);letter-spacing:0;text-wrap:wrap}.story-summary{font-size:13px;color:var(--soft);line-height:1.95;margin-top:11px}.planner-note{margin-top:12px;font-size:12px;line-height:1.85;color:var(--soft)}.planner-note span{font-size:10px;font-weight:700;color:var(--sage);margin-right:8px}.story-background{margin-top:10px;font-size:12px;color:var(--soft)}.story-background summary{width:fit-content;cursor:pointer;color:var(--sage);font-size:10px}.story-background p{padding-top:7px;line-height:1.85}.source-line{display:flex;flex-wrap:wrap;align-items:baseline;gap:5px 10px;margin-top:13px;font-size:10px;line-height:1.75;color:var(--muted)}.source-line a{color:var(--soft);text-decoration:none;border-bottom:1px solid #c9cbbb}.source-line a:hover{color:var(--rust);border-color:var(--rust)}.source-line .lang-label{font:9px var(--mono);letter-spacing:.04em;color:var(--sage)}.source-note{font-size:10px;color:var(--muted);margin-top:6px}.no-content{padding:30px 0;font-size:13px;color:var(--soft)}
.sidebar{border-top:2px solid var(--ink);padding-top:16px}.sidebar h2{font:700 20px/1.4 var(--serif)}.sidebar-deck{font-size:12px;color:var(--soft);line-height:1.9;margin-top:10px}.issue-totals{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:21px;padding-bottom:23px;border-bottom:1px solid var(--line)}.issue-totals div{border-right:1px solid var(--line);padding-right:8px}.issue-totals div:last-child{border-right:0}.issue-totals b{display:block;font:28px/1.2 var(--serif)}.issue-totals span{display:block;margin-top:7px;font-size:10px;color:var(--soft)}.guide-title{font-size:10px;font-weight:600;color:var(--sage);letter-spacing:.12em;margin-top:22px}.guide-list{list-style:none;padding:0;margin:8px 0 0}.guide-list li{padding:13px 0;border-bottom:1px solid var(--line)}.guide-list small{font:9px var(--mono);color:var(--muted);letter-spacing:.1em}.guide-list a{display:block;margin-top:4px;text-decoration:none;font:14px/1.7 var(--serif)}.sidebar-quote{margin-top:28px;padding-top:18px;border-top:3px double var(--line);font:16px/1.85 var(--serif);color:var(--sage)}.sidebar-caption{font-size:10px;color:var(--soft);line-height:1.85;margin-top:8px}.source-mix{margin-top:22px;font-size:10px;color:var(--muted);line-height:1.9}
.features-section{margin-top:56px}.feature-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));margin-top:24px;border:1px solid var(--line);background:var(--panel)}.feature-card{min-width:0;padding:25px 24px 26px;border-right:1px solid var(--line);scroll-margin-top:24px}.feature-card:last-child{border-right:0}.feature-top{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:16px}.feature-mark{font:11px var(--mono);letter-spacing:.1em;color:var(--rust)}.feature-kind{font-size:10px;color:var(--sage)}.feature-title{font:700 22px/1.55 var(--serif)}.feature-summary{font-size:13px;color:var(--soft);line-height:1.95;margin-top:16px}.feature-notes{margin-top:20px;border-top:1px solid var(--line)}.feature-note{padding-top:16px}.feature-note dt{font-size:10px;font-weight:700;letter-spacing:.08em;color:var(--sage);margin-bottom:5px}.feature-note dd{font-size:12px;line-height:1.95;color:var(--soft)}.feature-note.takeaway{margin-top:16px;padding:14px;background:var(--wash)}.feature-meta{margin-top:20px;font:9px/1.8 var(--mono);color:var(--muted)}.feature-card .source-line{margin-top:8px}.section-empty{padding:24px 0;font-size:13px;color:var(--soft);border-bottom:1px solid var(--line)}
.ai-section{margin-top:49px;padding-top:24px;border-top:3px double var(--ink)}.ai-section .section-head{padding-bottom:15px;border-bottom:1px solid var(--line)}.ai-section .section-head h2{font-size:23px}.ai-section .section-kicker{font-size:9px}.ai-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:36px;padding-top:21px}.ai-item{min-width:0;scroll-margin-top:24px}.ai-title{font:700 18px/1.6 var(--serif)}.ai-item .story-summary{font-size:12px;margin-top:10px}.ai-top{display:flex;gap:8px;align-items:baseline;margin-bottom:8px;color:var(--sage);font-size:10px}.ai-top .permalink{margin-left:auto}.ai-item .planner-note{font-size:11px}
.archive-section{margin-top:49px;padding-top:22px;border-top:1px solid var(--line)}.archive-section h2{font:700 20px var(--serif)}.archive-deck{margin-top:6px;color:var(--soft);font-size:11px}.archive-list{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px;list-style:none;padding:0}.archive-list a{display:block;font:10px var(--mono);padding:7px 11px;border:1px solid var(--line);text-decoration:none}.archive-list a:hover{border-color:var(--sage);background:var(--wash);color:var(--sage)}.archive-list [aria-current=date]{border-color:var(--sage);color:var(--sage)}.archive-more summary{font-size:11px;color:var(--soft);cursor:pointer;width:fit-content}.footer{margin-top:37px;padding:20px 0 33px;border-top:2px solid var(--ink);display:flex;justify-content:space-between;align-items:flex-start;gap:24px;font-size:10px;line-height:1.9;color:var(--muted)}.footer-brand{font:700 15px var(--serif);color:var(--ink);letter-spacing:.07em}.footer-copy{margin-top:6px;max-width:670px}.footer-links{display:flex;gap:19px;flex-wrap:wrap;justify-content:flex-end;flex-shrink:0}.footer-links a{text-decoration:none}.news-title,.feature-title,.ai-title,.original-title,.story-summary,.feature-summary,.feature-note dd,.guide-list a,.planner-note,.source-line{overflow-wrap:anywhere}article:target{outline:2px solid var(--sage);outline-offset:8px;background:#eef0e6}
@media(min-width:1100px){.sidebar{position:sticky;top:24px}}
@media(max-width:960px){.wrap{width:calc(100% - 48px)}.edition-grid{grid-template-columns:minmax(0,1fr) 216px;gap:30px}.feature-card{padding:22px 18px}.feature-title{font-size:20px}.filter-fields{grid-template-columns:minmax(0,1fr) 112px 90px;gap:7px}.news-title{font-size:21px}.news-list>li:first-child .news-title{font-size:26px}}
@media(max-width:760px){.wrap{width:calc(100% - 36px)}.masthead{padding-top:18px}.masthead-top{font-size:10px}.top-links{gap:15px}.brand-row{gap:15px;padding:25px 0 23px}.brand h1{font-size:45px;letter-spacing:.04em}.brand-en{font-size:9px;letter-spacing:.2em;margin-top:8px}.edition-date{font-size:21px}.edition-day{font-size:10px}.edition-status{font-size:9px;margin-top:7px}.strapline{align-items:flex-start;gap:9px;flex-direction:column;font-size:11px}.edition-count{font-size:9px}.nav{gap:12px 22px;padding:12px 0}.nav a{font-size:11px}.edition-grid{display:block;margin-top:31px}.sidebar{display:none}.section-head{padding-bottom:14px}.section-head h2{font-size:27px}.section-subtitle{font-size:11px}.section-count b{font-size:23px}.filter-fields{grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:9px}.field.search-field{grid-column:1/-1}.field input,.field select{height:41px}.news-item{padding:20px 0}.news-title{font-size:22px}.news-list>li:first-child .news-title{font-size:26px}.features-section{margin-top:39px}.feature-grid{grid-template-columns:1fr;margin-top:19px}.feature-card{padding:23px 22px 25px;border-right:0;border-bottom:1px solid var(--line)}.feature-card:last-child{border-bottom:0}.feature-title{font-size:24px}.feature-notes{display:grid;grid-template-columns:1fr 1fr;gap:18px}.feature-note.takeaway{margin-top:14px;padding:13px}.feature-meta{margin-top:19px}.ai-section{margin-top:36px}.ai-list{grid-template-columns:1fr;gap:24px}.ai-item+.ai-item{border-top:1px solid var(--line);padding-top:21px}.ai-title{font-size:20px}.archive-section{margin-top:34px}.footer{display:block;padding-bottom:27px}.footer-links{justify-content:flex-start;margin-top:15px}.preview-note{font-size:11px;padding:11px 13px}}
@media(max-width:390px){.wrap{width:calc(100% - 28px)}.brand h1{font-size:38px}.brand-en{font-size:8px;letter-spacing:.13em}.edition-date{font-size:18px}.edition-day{font-size:9px}.masthead-top{font-size:9px}.section-head h2{font-size:24px}.section-subtitle{font-size:10px}.feature-notes{display:block}.feature-note.takeaway{margin-top:17px}.story-topline{gap:7px}.story-date{font-size:9px}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}*,*::before,*::after{animation:none!important;transition:none!important}}
@media print{body{background:#fff;color:#111;font-size:11px}.wrap{width:100%;max-width:none}.top-links,.nav,.filter-panel,.filter-empty,.sidebar,.permalink,.footer-links{display:none!important}.edition-grid{display:block}.news-item,.feature-card,.ai-item{break-inside:avoid}.feature-grid,.ai-list{display:block}.feature-card{border-right:0;border-bottom:1px solid #aaa}.news-list>li[hidden]{display:block!important}.footer{margin-top:20px}.brand h1{font-size:40px}}
"""

CSS += SITE_NAV_CSS + r"""
.edition-contents{display:flex;align-items:baseline;flex-wrap:wrap;gap:7px 22px;padding:14px 0;border-bottom:1px solid var(--line);font-size:12px;color:var(--soft)}
.contents-label{font-size:11px;color:var(--muted);margin-right:2px}.edition-contents a{font-size:12px;text-decoration:underline;text-decoration-color:#b2b9aa;text-underline-offset:4px;font-weight:400}.edition-contents small{font-size:10px;color:var(--muted);margin-left:6px}.contents-language{margin-left:auto;font-size:10px;color:var(--muted)}
.masthead{padding-top:15px}.masthead-top{border:0;padding-bottom:0;font-size:10px}.brand-row{padding:20px 0}.brand h1{font-size:44px}.brand-en{font-size:10px;letter-spacing:.18em}.edition-date{font-size:23px}.edition-status{margin-top:6px}.edition-grid{margin-top:32px}
@media(max-width:760px){.wrap{width:calc(100% - 28px)}.brand h1{font-size:35px}.brand-row{padding:18px 0}.brand-en{font-size:8px}.edition-date{font-size:19px}.edition-contents{gap:8px 16px;padding:12px 0}.contents-label{flex-basis:100%}.contents-language{display:none}.masthead-top{gap:10px}.top-links{gap:12px}}
@media print{.edition-contents{display:none}}
"""

SCRIPT = r"""
(() => {
  const form = document.getElementById('news-filters');
  if (!form) return;
  const search = document.getElementById('news-search');
  const topic = document.getElementById('news-topic');
  const language = document.getElementById('news-language');
  const items = Array.from(document.querySelectorAll('[data-news-item]'));
  const status = document.getElementById('filter-status');
  const empty = document.getElementById('filter-empty');
  const normalise = text => text.normalize('NFKC').toLocaleLowerCase().trim();
  const initial = new URLSearchParams(location.search);
  search.value = initial.get('q') || '';
  if (Array.from(topic.options).some(option => option.value === initial.get('topic'))) topic.value = initial.get('topic');
  if (Array.from(language.options).some(option => option.value === initial.get('lang'))) language.value = initial.get('lang');
  function apply() {
    const terms = normalise(search.value).split(/\s+/).filter(Boolean);
    let visible = 0;
    items.forEach(item => {
      const matches = terms.every(term => normalise(item.dataset.search).includes(term))
        && (!topic.value || item.dataset.topic === topic.value)
        && (!language.value || item.dataset.lang === language.value);
      item.hidden = !matches;
      if (matches) visible += 1;
    });
    status.textContent = visible === items.length ? `本期 ${items.length} 条游戏动态` : `显示 ${visible} / ${items.length} 条游戏动态`;
    empty.hidden = visible !== 0;
    const url = new URL(location.href);
    [['q', search.value.trim()], ['topic', topic.value], ['lang', language.value]].forEach(([key, value]) => {
      if (value) url.searchParams.set(key, value); else url.searchParams.delete(key);
    });
    try { history.replaceState(null, '', url.pathname + url.search + url.hash); } catch (_) {}
  }
  function reset() { form.reset(); apply(); search.focus(); }
  form.addEventListener('submit', event => { event.preventDefault(); apply(); });
  search.addEventListener('input', apply);
  topic.addEventListener('change', apply);
  language.addEventListener('change', apply);
  document.querySelectorAll('[data-reset-filters]').forEach(button => button.addEventListener('click', reset));
  document.addEventListener('keydown', event => {
    const target = event.target;
    if (event.key === '/' && !event.ctrlKey && !event.metaKey && !event.altKey
      && !(target instanceof HTMLElement && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)))) {
      event.preventDefault(); search.focus();
    }
  });
  form.hidden = false;
  apply();
})();
"""


def esc(value) -> str:
    return html.escape(str(value or ""), quote=True)


def _text(value) -> str:
    return str(value or "").strip()


def _url(value) -> str:
    value = _text(value)
    parsed = urlparse(value)
    return value if parsed.scheme.lower() in ("http", "https") and parsed.netloc else ""


def _datetime(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except (ValueError, TypeError):
        return None


def _edition_time(digest: dict) -> datetime:
    parsed = _datetime(digest.get("generated_at"))
    if parsed:
        return parsed.astimezone(TZ)
    try:
        return datetime.combine(date.fromisoformat(str(digest.get("date"))), datetime.min.time(), TZ)
    except (ValueError, TypeError):
        return datetime.now(TZ)


def _unique(items) -> list[dict]:
    out, seen = [], set()
    for event in items:
        if not isinstance(event, dict) or not _text(event.get("title")):
            continue
        key = _text(event.get("key") or event.get("url") or event.get("title"))
        if key not in seen:
            seen.add(key)
            out.append(event)
    return out


def _sections(digest: dict) -> tuple[list[dict], list[dict], list[dict]]:
    if digest.get("schema_version") == 3 or any(key in digest for key in ("news", "features", "ai")):
        return (_unique(digest.get("news") or [])[:16], _unique(digest.get("features") or [])[:3],
                _unique(digest.get("ai") or [])[:2])
    news = _unique((digest.get("lead") or []) + (digest.get("threads") or []) + (digest.get("brief") or []))[:16]
    features = _unique((digest.get("relevant") or []) + (digest.get("graphics") or []))[:3]
    ai = _unique((digest.get("papers") or []) + (digest.get("repos") or []))[:2]
    return news, features, ai


TOPIC_CN = {"news": "游戏动态", "game_news": "游戏动态", "industry": "行业动态", "business": "行业动态",
            "release": "新作与更新", "releases": "新作与更新", "update": "新作与更新", "updates": "新作与更新",
            "design": "设计与机制", "combat": "战斗与机制", "development": "开发实践", "dev": "开发实践",
            "technology": "开发技术", "technical": "开发技术", "tools": "开发工具", "tool": "开发工具",
            "level_design": "关卡与世界", "ai": "AI 动态"}


def _topic(ev: dict, fallback: str = "游戏动态") -> str:
    value = ev.get("topic") or ev.get("category") or fallback
    if isinstance(value, list):
        value = value[0] if value else fallback
    value = _text(value)
    return TOPIC_CN.get(value.lower(), value or fallback)


def _lang(ev: dict) -> str:
    value = _text(ev.get("lang")).lower()
    return "zh" if value.startswith("zh") else ("en" if value.startswith("en") else "other")


def _language(ev: dict) -> str:
    return {"zh": "中文原文", "en": "英文原文", "other": "原文"}[_lang(ev)]


def _title_cn(ev: dict) -> str:
    return esc(ev.get("title_cn") or ev.get("title") or "未命名文章")


def _orig_line(ev: dict) -> str:
    original, translated = _text(ev.get("title")), _text(ev.get("title_cn"))
    if _lang(ev) == "zh" or not translated or translated == original:
        return ""
    lang = ' lang="en"' if _lang(ev) == "en" else ""
    return f'<span class="original-title"{lang}>{esc(original)}</span>'


def _title_link(ev: dict) -> str:
    title, url = _title_cn(ev), _url(ev.get("url"))
    if url:
        title = f'<a href="{esc(url)}" target="_blank" rel="noopener noreferrer">{title}</a>'
    return title + _orig_line(ev)


def _anchor(ev: dict, section: str, index: int) -> str:
    key = _text(ev.get("key") or ev.get("url") or ev.get("title"))
    return f'{section}-{hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]}'


def _permalink(anchor: str) -> str:
    return f'<a class="permalink" href="#{esc(anchor)}" aria-label="本条的页内链接" title="本条的页内链接">#</a>'


def _published(ev: dict, *, full: bool = False) -> str:
    parsed = None if ev.get("undated") else _datetime(ev.get("published"))
    if not parsed:
        return "原文日期未标"
    local = parsed.astimezone(TZ)
    label = local.strftime("%Y.%m.%d" if full else "%m.%d")
    day_only = ev.get("published_precision") == "day" or re.fullmatch(r"\d{4}-\d{2}-\d{2}", _text(ev.get("published")))
    machine_date = local.date().isoformat() if day_only else parsed.isoformat()
    return f'<time datetime="{esc(machine_date)}">{label}</time>'


def _source_names(ev: dict) -> list[str]:
    values = ev.get("sources") or ([ev["source"]] if ev.get("source") else [])
    if isinstance(values, str):
        values = [values]
    return list(dict.fromkeys(_text(name) for name in values if _text(name)))


def _sources(ev: dict) -> str:
    links, seen = [], set()
    primary, names = _url(ev.get("url")), _source_names(ev)
    if primary:
        links.append(f'<a href="{esc(primary)}" target="_blank" rel="noopener noreferrer">{esc(names[0] if names else "阅读原文")} ↗</a>')
        seen.add(primary)
    for member in ev.get("members") or []:
        if not isinstance(member, dict):
            continue
        url = _url(member.get("url"))
        if url and url not in seen:
            seen.add(url)
            links.append(f'<a href="{esc(url)}" target="_blank" rel="noopener noreferrer">{esc(member.get("source") or "其他来源")}</a>')
    if not links:
        links = [esc(name) for name in names]
    return f'<div class="source-line"><span class="lang-label">{_language(ev)}</span>{"".join(links)}</div>'


def _summary(ev: dict) -> str:
    return _text(ev.get("what") or ev.get("pitch") or ev.get("summary_raw"))


def _insight(ev: dict) -> str:
    value = _text(ev.get("for_you"))
    return "" if "无直接关系" in value else value


def _summary_note(ev: dict) -> str:
    is_summary = ev.get("has_body") is False or ev.get("content_kind") in ("rss_summary", "rss_content", "page_excerpt")
    return '<p class="source-note">来源摘要 · 细节请参见原文。</p>' if is_summary else ""


def _news_item(ev: dict, index: int) -> str:
    anchor, topic = _anchor(ev, "news", index), _topic(ev)
    search = " ".join(_text(ev.get(key)) for key in ("title", "title_cn", "what", "why", "for_you", "summary_raw"))
    search += " " + " ".join(_source_names(ev)) + " " + topic
    summary = f'<p class="story-summary">{esc(_summary(ev))}</p>' if _summary(ev) else ""
    planner = f'<p class="planner-note"><span>策划视角</span>{esc(_insight(ev))}</p>' if _insight(ev) else ""
    why = _text(ev.get("why"))
    background = (f'<details class="story-background"><summary>背景与变化</summary><p>{esc(why)}</p></details>'
                  if why and why != _summary(ev) else "")
    return (f'<li data-news-item data-topic="{esc(topic)}" data-lang="{_lang(ev)}" data-search="{esc(search)}">'
            f'<article class="news-item" id="{anchor}"><div class="story-topline"><span class="story-number">{index:02d}</span>'
            f'<span class="topic">{esc(topic)}</span><span class="story-date">{_published(ev)}</span>{_permalink(anchor)}</div>'
            f'<h3 class="news-title">{_title_link(ev)}</h3>{summary}{planner}{background}{_sources(ev)}{_summary_note(ev)}</article></li>')


def _reading_minutes(ev: dict) -> str:
    try:
        value = int(ev.get("reading_minutes") or 0)
        return f"约 {value} 分钟" if 0 < value <= 240 else ""
    except (ValueError, TypeError):
        return ""


def _feature_item(ev: dict, index: int) -> str:
    anchor = _anchor(ev, "feature", index)
    kinds = {"analysis": "设计分析", "design": "设计分析", "technical": "开发实践", "tutorial": "开发实践",
             "interview": "开发者访谈", "postmortem": "制作复盘", "video": "设计视频", "evergreen": "设计方法"}
    kind = _text(ev.get("content_type"))
    kind = kinds.get(kind.lower(), kind) or _topic(ev, "设计阅读")
    notes = []
    if ev.get("why"):
        notes.append(f'<div class="feature-note"><dt>设计选择</dt><dd>{esc(ev["why"])}</dd></div>')
    if _insight(ev):
        notes.append(f'<div class="feature-note takeaway"><dt>策划视角</dt><dd>{esc(_insight(ev))}</dd></div>')
    notes_html = f'<dl class="feature-notes">{"".join(notes)}</dl>' if notes else ""
    bits = ["常青阅读" if ev.get("evergreen") else "设计阅读", "原文 " + _published(ev, full=True)]
    if _reading_minutes(ev):
        bits.append(_reading_minutes(ev))
    return (f'<article class="feature-card" id="{anchor}"><div class="feature-top"><span class="feature-mark">精选 {index:02d}</span>'
            f'<span class="feature-kind">{esc(kind)}</span>{_permalink(anchor)}</div><h3 class="feature-title">{_title_link(ev)}</h3>'
            f'<p class="feature-summary">{esc(_summary(ev))}</p>{notes_html}<div class="feature-meta">{" · ".join(bits)}</div>'
            f'{_sources(ev)}{_summary_note(ev)}</article>')


def _ai_item(ev: dict, index: int) -> str:
    anchor = _anchor(ev, "ai", index)
    planner = f'<p class="planner-note"><span>可以留意</span>{esc(_insight(ev))}</p>' if _insight(ev) else ""
    return (f'<article class="ai-item" id="{anchor}"><div class="ai-top"><span>{_published(ev, full=True)}</span>{_permalink(anchor)}</div>'
            f'<h3 class="ai-title">{_title_link(ev)}</h3><p class="story-summary">{esc(_summary(ev))}</p>'
            f'{planner}{_sources(ev)}{_summary_note(ev)}</article>')


def _section_head(number: str, title: str, en: str, subtitle: str, count: int, unit: str = "条") -> str:
    return (f'<div class="section-head"><div><span class="section-kicker">{number} / {esc(en)}</span>'
            f'<h2>{esc(title)}</h2><p class="section-subtitle">{esc(subtitle)}</p></div>'
            f'<span class="section-count"><b>{count}</b>{esc(unit)}</span></div>')


def _filters(news: list[dict]) -> str:
    topics = list(dict.fromkeys(_topic(event) for event in news))
    options = ''.join(f'<option value="{esc(topic)}">{esc(topic)}</option>' for topic in topics)
    available = {_lang(event) for event in news}
    langs = ''.join(f'<option value="{key}">{label}</option>' for key, label in
                    (("zh", "中文原文"), ("en", "英文原文"), ("other", "其他语言")) if key in available)
    return ('<form class="filter-panel" id="news-filters" role="search" aria-label="筛选本期游戏日报" hidden>'
            '<div class="filter-fields"><label class="field search-field" for="news-search"><span>搜索本期</span>'
            '<input type="search" id="news-search" name="q" placeholder="游戏、机制、开发者或来源" autocomplete="off" aria-keyshortcuts="/"></label>'
            f'<label class="field" for="news-topic"><span>主题</span><select id="news-topic" name="topic"><option value="">全部主题</option>{options}</select></label>'
            f'<label class="field" for="news-language"><span>原文语言</span><select id="news-language" name="lang"><option value="">全部语言</option>{langs}</select></label></div>'
            f'<div class="filter-footer"><p id="filter-status" role="status" aria-live="polite">本期 {len(news)} 条游戏动态</p>'
            '<button class="text-button" type="button" data-reset-filters>清除筛选</button></div></form>'
            '<div class="filter-empty" id="filter-empty" hidden><h3>没有找到相关动态</h3><p>换个关键词，或清除主题与语言筛选。</p>'
            '<button class="text-button" type="button" data-reset-filters>查看本期全部动态</button></div>')


def _sidebar(news: list[dict], features: list[dict], ai: list[dict], source_count: int) -> str:
    guide = ''.join(f'<li><small>精选 {index:02d}</small><a href="#{_anchor(event, "feature", index)}">{_title_cn(event)}</a></li>'
                    for index, event in enumerate(features, 1))
    guide_html = f'<p class="guide-title">本期精选文章</p><ol class="guide-list">{guide}</ol>' if guide else ""
    totals = ''.join(f'<div><b>{count:02d}</b><span>{label}</span></div>' for count, label in
                     ((len(news), "游戏动态"), (len(features), "策划精选"), (len(ai), "AI 精华")))
    return ('<aside class="sidebar" aria-labelledby="guide-title"><span class="overline">IN THIS EDITION</span><h2 id="guide-title">本期导读</h2>'
            '<p class="sidebar-deck">本期游戏动态、策划精选与 AI 精华。</p>'
            f'<div class="issue-totals">{totals}</div>{guide_html}'
            '<p class="sidebar-caption">精选包含近期文章与往期文章，保留原始发布日期。</p>'
            f'<p class="source-mix">本期汇集 {source_count} 个来源。<br>中文摘要 · 原文直达 · 保留英文标题</p></aside>')


def _archive(dates: list[str], current: str, archive_page: bool, preview: bool,
             earlier_editions: list[dict] | None = None) -> str:
    prefix = SITE + "/archive/" if preview else ("" if archive_page else "archive/")
    dates = sorted({day for day in dates if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(day))}, reverse=True)
    def links(values):
        return '<ul class="archive-list">' + ''.join(
            f'<li><a href="{prefix}{day}.html"' + (' aria-current="date"' if day == current and not preview else '') + f'>{day}</a></li>'
            for day in values) + '</ul>'
    content = links(dates[:8]) if dates else '<p class="archive-deck">正式刊期将保存在这里。</p>'
    if len(dates) > 8:
        content += f'<details class="archive-more"><summary>查看更早的 {len(dates) - 8} 期</summary>{links(dates[8:])}</details>'
    earlier_links = []
    for edition in earlier_editions or []:
        filename = str(edition.get("file") or "")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}-[a-z0-9-]+\.html", filename):
            earlier_links.append(f'<a href="{prefix}{filename}">{esc(edition.get("label") or filename)}</a>')
    if earlier_links:
        content += '<p class="archive-deck">同日较早刊期：' + ' · '.join(earlier_links) + '</p>'
    return ('<section class="archive-section" id="archive" aria-labelledby="archive-title"><h2 id="archive-title">往期归档</h2>'
            '<p class="archive-deck">已发布刊期，按日期排列。</p>' + content + '</section>')


def render(digest: dict, health: dict | None = None, *, archive_dates: list[str] | None = None,
           archive_page: bool = False, market: dict | None = None) -> str:
    """Render v3 or legacy JSON; ``health`` is accepted without leaking diagnostics."""
    now = _edition_time(digest)
    try:
        issue_date = date.fromisoformat(str(digest.get("date")))
    except (ValueError, TypeError):
        issue_date = now.date()
    date_iso, preview = issue_date.isoformat(), bool(digest.get("preview"))
    news, features, ai = _sections(digest)
    names = {name for event in news + features + ai for name in _source_names(event)}
    languages = {_lang(event) for event in news + features + ai}
    language_label = "中英来源" if {"zh", "en"} <= languages else ("英文来源" if "en" in languages else "多方来源")
    title = f'策划日报 · {date_iso}' + (' · 试刊' if preview else '')
    desc = f'游戏动态 {len(news)} 条，策划精选 {len(features)} 篇，AI 精华 {len(ai)} 条。游戏资讯、设计分析与开发实践。'
    prefix = "../" if archive_page else ""
    market_html = ""
    if market:
        from market_render import render_market_brief
        market_html = render_market_brief(market, href=prefix + "market.html")
    preview_message = _text(digest.get("editorial_note")) or "这是新栏目结构的预览，内容与编排仍在调整，不计入正式归档。"
    preview_html = (f'<div class="preview-note" role="note"><strong>试刊</strong>{esc(preview_message)}</div>' if preview else '')
    news_html = ''.join(_news_item(event, i) for i, event in enumerate(news, 1)) or '<li class="no-content">本期暂未收录游戏动态。</li>'
    features_html = ('<div class="feature-grid">' + ''.join(_feature_item(event, i) for i, event in enumerate(features, 1)) + '</div>'
                     if features else '<p class="section-empty">本期暂未收录策划精选。</p>')
    ai_html = ('<div class="ai-list">' + ''.join(_ai_item(event, i) for i, event in enumerate(ai, 1)) + '</div>'
               if ai else '<p class="section-empty">本期暂未收录 AI 精华。</p>')
    dates = list(archive_dates or [])
    if not preview and date_iso not in dates:
        dates.append(date_iso)
    return f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><title>{esc(title)}</title><meta name="description" content="{esc(desc)}">
<link rel="alternate" type="application/rss+xml" title="策划日报" href="{prefix}feed.xml"><style>{CSS}</style></head>
<body id="top"><a class="skip-link" href="#news">跳到今日游戏日报</a><div class="wrap">
{render_site_navigation("daily", prefix, archive_page=archive_page)}
<header class="masthead"><div class="masthead-top"><span>中英文游戏资讯与开发文章</span><div class="top-links"><a href="#archive">往期归档</a><a href="{prefix}feed.xml">RSS 订阅 ↗</a></div></div>
<div class="brand-row"><div class="brand"><h1>策划日报</h1><p class="brand-en" lang="en">GAME DESIGN DAILY</p></div><div class="edition"><p class="edition-date"><time datetime="{date_iso}">{issue_date:%Y.%m.%d}</time></p><p class="edition-day">星期{WEEKDAY_CN[issue_date.weekday()]} · {now:%H:%M} 整理</p><span class="edition-status{' preview' if preview else ''}">{'试刊 · PREVIEW' if preview else '每日一读 · DAILY EDITION'}</span></div></div>
<nav class="edition-contents" aria-label="本期目录"><span class="contents-label">本期目录</span><a href="#news">游戏日报<small>{len(news)} 条</small></a><a href="#features">策划精选<small>{len(features)} 篇</small></a><a href="#ai">AI 精华<small>{len(ai)} 条</small></a><span class="contents-language">{language_label}</span></nav></header>{preview_html}
<main><div class="edition-grid"><div class="main-column"><section id="news" aria-label="今日游戏日报">
{_section_head('01', '今日游戏日报', 'THE DAILY', '游戏发售、版本更新、行业与开发动态。', len(news))}
{_filters(news) if news else ''}<ol class="news-list">{news_html}</ol></section></div>{_sidebar(news, features, ai, len(names))}</div>
<section class="features-section" id="features" aria-label="策划精选">{_section_head('02', '策划精选', 'THE DESIGN DESK', '游戏机制、设计分析与开发复盘。', len(features), '篇')}{features_html}</section>
<section class="ai-section" id="ai" aria-label="AI 精华">{_section_head('03', 'AI 精华', 'ON THE SIDE', 'AI 工具、模型与开发应用。', len(ai))}{ai_html}</section>
{market_html}{_archive(dates, date_iso, archive_page, preview, digest.get("earlier_editions"))}</main>
<footer class="footer"><div><p class="footer-brand">策划日报</p><p class="footer-copy">收录游戏资讯、开发实践与设计文章。中文摘要与策划视角是阅读导引，完整语境以原文为准；常青阅读保留原始日期。{'本页为试刊预览。' if preview else ''}</p></div><div class="footer-links">{'<a href="../index.html">最新一期</a>' if archive_page else ''}<a href="#archive">往期归档</a><a href="{prefix}feed.xml">RSS 订阅</a><a href="https://github.com/Vizroi/daily-ai-digest" target="_blank" rel="noopener noreferrer">关于与源码 ↗</a><a href="#top">↑ 页首</a></div></footer>
</div><script>{SCRIPT}</script></body></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", default="data/digest.json")
    parser.add_argument("output", nargs="?", default="docs/index.html")
    parser.add_argument("health", nargs="?", help="Compatibility argument for older jobs")
    parser.add_argument("--market", default="data/market.json")
    parser.add_argument("--no-archive", action="store_true", help="Refresh the homepage without creating or changing an edition archive")
    args = parser.parse_args()
    inp, out = args.input, args.output
    with open(inp, encoding="utf-8") as handle:
        digest = json.load(handle)
    output_dir = os.path.dirname(os.path.abspath(out))
    archive_dir = os.path.join(output_dir, "archive")
    dates = [name[:-5] for name in os.listdir(archive_dir)
             if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.html", name)] if os.path.isdir(archive_dir) else []
    market = None
    if os.path.isfile(args.market):
        try:
            with open(args.market, encoding="utf-8") as handle:
                market = json.load(handle)
            if not isinstance(market, dict):
                market = None
        except (OSError, ValueError):
            print("[WARN] 市场数据暂不可读，日报仍可生成")
    page = render(digest, archive_dates=dates, market=market)
    os.makedirs(output_dir, exist_ok=True)
    with open(out, "w", encoding="utf-8") as handle:
        handle.write(page)
    print(f"[OK] 页面已生成 → {out} ({len(page.encode('utf-8')) // 1024} KB)")
    if args.no_archive:
        print("[OK] 仅更新首页，日报内容和历史归档保持原样")
        return
    if digest.get("preview"):
        print("[OK] 试刊预览不写入正式归档")
        return
    day = _edition_time(digest).date().isoformat()
    try:
        day = date.fromisoformat(str(digest.get("date"))).isoformat()
    except (ValueError, TypeError):
        pass
    archive_path = os.path.join(archive_dir, day + ".html")
    if os.path.exists(archive_path):
        print(f"[OK] 保留已有归档 → {archive_path}")
        return
    os.makedirs(archive_dir, exist_ok=True)
    with open(archive_path, "w", encoding="utf-8") as handle:
        handle.write(render(digest, archive_dates=dates + [day], archive_page=True, market=market))
    print(f"[OK] 已归档 → {archive_path}")


if __name__ == "__main__":
    main()
