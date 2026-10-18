"""Independent AI reader: short news, verified features and immutable editions."""
import argparse
from datetime import date
import json
from pathlib import Path
import re

import config
from cluster import canonical_url
from render import (CSS as READER_CSS, _anchor, _edition_time, _permalink,
                    _published, _reading_minutes, _sources, _summary, _summary_note,
                    _title_link, _unique, _url, esc)
from site_navigation import render_site_navigation

ROOT = Path(__file__).resolve().parents[1]

CSS = READER_CSS + r'''
.ai-masthead{padding:25px 0 0}.ai-brand-row{display:flex;justify-content:space-between;align-items:center;gap:24px;padding-bottom:22px}.ai-brand-row h1{font:700 36px/1.3 var(--serif)}.ai-edition{text-align:right;font-size:11px;color:var(--soft)}.ai-edition time{display:block;font:23px/1.5 var(--serif);color:var(--ink)}
.ai-section-head{display:flex;justify-content:space-between;align-items:baseline;gap:16px;border-bottom:2px solid var(--ink);padding-bottom:13px}.ai-section-head h2{font:700 25px/1.4 var(--serif)}.ai-section-head span{font-size:11px;color:var(--soft)}.ai-news{margin-top:29px}.ai-news-list{list-style:none;padding:0;margin:0}.ai-news-item{display:grid;grid-template-columns:27px minmax(0,1fr);gap:14px;padding:21px 0;border-bottom:1px solid var(--line)}.ai-news-number{font:11px/2 var(--mono);color:var(--muted);padding-top:3px}.ai-news-title{font:700 21px/1.55 var(--serif);overflow-wrap:anywhere}.ai-news-title a{text-decoration:none}.ai-news-copy{font-size:13px;line-height:1.9;margin-top:8px;color:var(--soft);overflow-wrap:anywhere}.ai-news-meta{display:flex;align-items:baseline;flex-wrap:wrap;gap:8px 14px;margin-top:10px;font-size:10px;color:var(--muted)}.ai-news-meta .source-line{margin:0}.ai-news-meta .permalink{margin-left:auto}.ai-news-title .original-title{font-size:10px;margin-top:2px}
.ai-features{margin-top:38px}.ai-feature-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),1fr));gap:24px;margin-top:20px}.ai-feature-card{min-width:0;background:var(--panel);border:1px solid var(--line);padding:24px}.ai-feature-top{display:flex;align-items:center;justify-content:space-between;gap:10px;font-size:10px;color:var(--sage);margin-bottom:11px}.ai-feature-title{font:700 23px/1.55 var(--serif);overflow-wrap:anywhere}.ai-feature-title a{text-decoration:none}.ai-feature-copy{font-size:13px;line-height:1.9;margin-top:13px;color:var(--soft);overflow-wrap:anywhere}.ai-feature-detail{font-size:12px;line-height:1.9;color:var(--soft);margin-top:15px;padding-top:12px;border-top:1px solid var(--line);overflow-wrap:anywhere}.ai-feature-detail b{display:block;font-size:10px;font-weight:600;color:var(--sage);margin-bottom:4px}.ai-feature-meta{font-size:10px;color:var(--muted);margin-top:17px}.ai-archive{margin-top:35px;padding-top:20px;border-top:1px solid var(--line)}.ai-archive h2{font:700 20px var(--serif)}
@media(max-width:760px){.ai-brand-row h1{font-size:30px}.ai-edition time{font-size:18px}.ai-section-head h2{font-size:23px}.ai-news-item{grid-template-columns:20px minmax(0,1fr);gap:9px;padding:18px 0}.ai-news-title{font-size:20px}.ai-feature-card{padding:20px}.ai-feature-title{font-size:22px}}
@media(max-width:480px){.ai-brand-row{display:block;padding-bottom:17px}.ai-edition{text-align:left;margin-top:9px}.ai-edition time{display:inline;font-size:14px;margin-right:12px}.ai-news{margin-top:24px}.ai-section-head span{font-size:10px}.ai-feature-grid{gap:16px}}
@media print{.ai-news-item,.ai-feature-card{break-inside:avoid}.ai-feature-grid{display:block}.ai-feature-card{margin-top:15px}}
'''


def sections(digest):
    features = [event for event in _unique(digest.get("ai_features") or [])
                if event.get("has_body") and _url(event.get("url"))][:config.AI_FEATURES_MAX]
    featured_keys = {str(event.get("key") or "") for event in features if event.get("key")}
    featured_urls = {canonical_url(event["url"]) for event in features}
    news = [event for event in _unique(digest.get("ai") or [])
            if event.get("key") not in featured_keys and canonical_url(event.get("url") or "") not in featured_urls][:config.AI_MAX]
    return news, features


def _brief_text(event):
    text = re.sub(r"\s+", " ", _summary(event)).strip()
    if len(text) <= 180:
        return text
    end = max(text.rfind(mark, 60, 180) for mark in ("。", "！", "？"))
    return text[:end + 1] if end >= 60 else text[:179].rstrip() + "…"


def _news(event, index):
    anchor = _anchor(event, "ai", index)
    return (f'<li><article class="ai-news-item" id="{anchor}"><span class="ai-news-number">{index:02d}</span><div>'
            f'<h3 class="ai-news-title">{_title_link(event)}</h3><p class="ai-news-copy">{esc(_brief_text(event))}</p>'
            f'<div class="ai-news-meta"><span>{_published(event, full=True)}</span>{_sources(event)}{_permalink(anchor)}</div>'
            f'{_summary_note(event)}</div></article></li>')


def _feature(event, index):
    anchor = _anchor(event, "ai-feature", index)
    note = (f'<p class="ai-feature-detail"><b>文章内容</b>{esc(event["why"])}</p>'
            if event.get("why") and event["why"] != _summary(event) else '')
    metadata = "原文 " + _published(event, full=True)
    if event.get("evergreen"):
        metadata += " · 常青阅读"
    if _reading_minutes(event):
        metadata += " · " + _reading_minutes(event)
    return (f'<article class="ai-feature-card" id="{anchor}"><div class="ai-feature-top"><span>精选 {index:02d}</span>{_permalink(anchor)}</div>'
            f'<h3 class="ai-feature-title">{_title_link(event)}</h3><p class="ai-feature-copy">{esc(_summary(event))}</p>{note}'
            f'<p class="ai-feature-meta">{metadata}</p>{_sources(event)}</article>')


def render_ai(digest, *, archive_dates=None, archive_page=False):
    news, features = sections(digest)
    now = _edition_time(dict(digest, generated_at=digest.get("ai_generated_at") or digest.get("generated_at")))
    try:
        day = date.fromisoformat(str(digest.get("date")))
    except (ValueError, TypeError):
        day = now.date()
    preview = bool(digest.get("preview"))
    prefix = "../../" if archive_page else ""
    archive_prefix = "" if archive_page else "archive/ai/"
    dates = sorted({str(d) for d in (archive_dates or []) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(d))}, reverse=True)
    links = ''.join(f'<li><a href="{archive_prefix}{d}.html">{d}</a></li>' for d in dates)
    archives = f'<ul class="archive-list">{links}</ul>' if links else '<p class="archive-deck">尚无已发布的 AI 刊期归档。</p>'
    preview_note = '<p class="preview-note">试刊预览，不计入正式归档。</p>' if preview else ''
    news_html = ''.join(_news(event, i) for i, event in enumerate(news, 1)) or '<li class="section-empty">本期暂无符合收录条件的 AI 快讯。</li>'
    features_html = ''.join(_feature(event, i) for i, event in enumerate(features, 1))
    features_html = f'<div class="ai-feature-grid">{features_html}</div>' if features_html else '<p class="section-empty">本期暂无已核对正文的精选阅读。</p>'
    return f'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI 快讯与精选 · {day.isoformat()}</title><meta name="description" content="AI 模型、工具与研究动态的简短摘要，以及精选阅读；保留原文入口与发布日期。">
<link rel="alternate" type="application/rss+xml" title="策划日报 · 站点 RSS" href="{prefix}feed.xml"><style>{CSS}</style></head><body id="top">
<a class="skip-link" href="#ai-news">跳到 AI 快讯</a><div class="wrap">{render_site_navigation("ai", prefix, archive_page=archive_page)}
<header class="ai-masthead"><div class="ai-brand-row"><h1>AI 快讯与精选</h1><div class="ai-edition"><time datetime="{day.isoformat()}">{day:%Y.%m.%d}</time>{now:%H:%M} 整理 · 北京时间</div></div>
<nav class="edition-contents" aria-label="本期目录"><span class="contents-label">本期目录</span><a href="#ai-news">AI 快讯<small>{len(news)} 条</small></a><a href="#ai-features">精选阅读<small>{len(features)} 篇</small></a><a href="#ai-archive">往期归档</a></nav></header>{preview_note}
<main><section class="ai-news" id="ai-news" aria-labelledby="ai-news-title"><div class="ai-section-head"><h2 id="ai-news-title">AI 快讯</h2><span>{len(news)} 条 · 模型、工具与研究动态</span></div><ol class="ai-news-list">{news_html}</ol></section>
<section class="ai-features" id="ai-features" aria-labelledby="ai-features-title"><div class="ai-section-head"><h2 id="ai-features-title">精选阅读</h2><span>{len(features)} 篇 · 保留原始发布日期</span></div>{features_html}</section>
<section class="ai-archive" id="ai-archive" aria-labelledby="ai-archive-title"><h2 id="ai-archive-title">AI 往期归档</h2>{archives}</section></main>
<footer class="footer"><div><p class="footer-brand">策划日报 / AI</p><p class="footer-copy">中文简述与原文链接。快讯收录近期动态，精选保留原始发布日期。</p></div><div class="footer-links"><a href="{prefix}ai.html">最新一期</a><a href="{prefix}feed.xml">站点 RSS</a><a href="#top">↑ 页首</a></div></footer></div></body></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", default=str(ROOT / "data/digest.json"))
    parser.add_argument("output", nargs="?", default=str(ROOT / "docs/ai.html"))
    parser.add_argument("--no-archive", action="store_true")
    args = parser.parse_args()
    digest = json.loads(Path(args.input).read_text(encoding="utf-8"))
    output = Path(args.output)
    archive = output.parent / "archive" / "ai"
    dates = [p.stem for p in archive.glob("*.html") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.stem)]
    if not args.no_archive and not digest.get("preview"):
        day = date.fromisoformat(str(digest["date"])).isoformat()
        if day not in dates:
            dates.append(day)
        archive.mkdir(parents=True, exist_ok=True)
        path = archive / (day + ".html")
        if not path.exists():
            path.write_text(render_ai(digest, archive_dates=dates, archive_page=True), encoding="utf-8")
            print(f"[OK] AI 刊期已归档 → {path}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_ai(digest, archive_dates=dates), encoding="utf-8")
    print(f"[OK] AI 页面已生成 → {output}")


if __name__ == "__main__":
    main()
