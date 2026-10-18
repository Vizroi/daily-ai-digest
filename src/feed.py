"""RSS for game news, design features and a small AI selection.

Original publication dates are preserved. Undated articles omit pubDate instead
of pretending their generation time is a new publication. Legacy JSON is accepted.
"""
import hashlib
import html
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime
from urllib.parse import urlparse

TZ = timezone(timedelta(hours=8))
SITE = os.environ.get("DIGEST_SITE", "https://vizroi.github.io/daily-ai-digest").rstrip("/")
REPO = "https://github.com/Vizroi/daily-ai-digest"
SECTION_CN = {"news": "今日游戏日报", "features": "策划精选", "ai": "AI 精华",
              "lead": "今日必读", "relevant": "能用上的", "threads": "线索追踪"}


def esc(value) -> str:
    return html.escape(str(value or ""), quote=True)


def _url(value) -> str:
    value = str(value or "").strip()
    parsed = urlparse(value)
    return value if parsed.scheme.lower() in ("https", "http") and parsed.netloc else ""


def _title(ev: dict) -> str:
    return str(ev.get("title_cn") or ev.get("title") or "未命名文章")


def _datetime(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except (ValueError, TypeError):
        return None


def _pubdate(ev: dict, fallback: datetime | None = None) -> str:
    # RSS permits omission; a generation timestamp is not an original pubDate.
    if ev.get("published_precision") == "day" or re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(ev.get("published") or "")):
        return ""
    parsed = None if ev.get("undated") else _datetime(ev.get("published"))
    return format_datetime(parsed) if parsed else ""


def _source_names(ev: dict) -> list[str]:
    names = ev.get("sources") or ([ev["source"]] if ev.get("source") else [])
    if isinstance(names, str):
        names = [names]
    return list(dict.fromkeys(str(name) for name in names if name))


def _description(ev: dict, section: str) -> str:
    rows = [f'<p><strong>{esc(SECTION_CN.get(section, section))}</strong>'
            + (' · 常青阅读' if ev.get("evergreen") else '') + '</p>']
    if not str(ev.get("lang", "")).lower().startswith("zh") and ev.get("title_cn") and ev.get("title_cn") != ev.get("title"):
        rows.append(f'<p><small>原标题：{esc(ev.get("title"))}</small></p>')
    what = ev.get("what") or ev.get("pitch") or ev.get("summary_raw")
    if what:
        rows.append(f'<p>{esc(what)}</p>')
    if ev.get("why"):
        label = "设计选择" if section == "features" else "背景与变化"
        rows.append(f'<p><strong>{label}</strong><br>{esc(ev["why"])}</p>')
    insight = str(ev.get("for_you") or "")
    if insight and "无直接关系" not in insight:
        rows.append(f'<p><strong>策划视角</strong><br>{esc(insight)}</p>')
    if ev.get("has_body") is False or ev.get("content_kind") in ("rss_summary", "rss_content", "page_excerpt"):
        rows.append('<p><small>来源摘要 · 细节请参见原文。</small></p>')
    links, seen = [], set()
    url, names = _url(ev.get("url")), _source_names(ev)
    if url:
        links.append(f'<a href="{esc(url)}">{esc(names[0] if names else "原文")}</a>')
        seen.add(url)
    for member in ev.get("members") or []:
        if not isinstance(member, dict):
            continue
        member_url = _url(member.get("url"))
        if member_url and member_url not in seen:
            links.append(f'<a href="{esc(member_url)}">{esc(member.get("source") or "其他来源")}</a>')
            seen.add(member_url)
    if links:
        rows.append('<p><small>来源：' + ' · '.join(links) + '</small></p>')
    elif names:
        rows.append('<p><small>来源：' + esc(' · '.join(names)) + '</small></p>')
    published = _datetime(ev.get("published")) if not ev.get("undated") else None
    if published:
        day_only = ev.get("published_precision") == "day" or re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(ev.get("published") or ""))
        date_format = "%Y-%m-%d" if day_only else "%Y-%m-%d %H:%M"
        zone_label = "" if day_only else "（北京时间）"
        rows.append(f'<p><small>原文发布：{esc(published.astimezone(TZ).strftime(date_format))}{zone_label}</small></p>')
    else:
        rows.append('<p><small>原文日期未标</small></p>')
    return ''.join(rows)


def _entries(digest: dict):
    sections = ((("news", 16), ("features", 3), ("ai", 2))
                if digest.get("schema_version") == 3 or any(key in digest for key in ("news", "features", "ai"))
                else (("lead", 5), ("relevant", 5), ("threads", 3)))
    seen = set()
    for section, maximum in sections:
        taken = 0
        for event in digest.get(section) or []:
            if not isinstance(event, dict) or not event.get("title"):
                continue
            key = str(event.get("key") or event.get("url") or event["title"])
            if key in seen:
                continue
            seen.add(key)
            yield section, event, key
            taken += 1
            if taken >= maximum:
                break


def build(digest: dict) -> str:
    now = _datetime(digest.get("generated_at")) or datetime.now(TZ)
    preview = bool(digest.get("preview"))
    items, counts = [], {"news": 0, "features": 0, "ai": 0}
    for section, event, key in _entries(digest):
        counts[section] = counts.get(section, 0) + 1
        event_id = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
        guid = f'{REPO}#article-{event_id}' + ('-preview' if preview else '')
        pubdate = _pubdate(event)
        date_element = f'  <pubDate>{pubdate}</pubDate>\n' if pubdate else ''
        url = _url(event.get("url"))
        link_element = f'  <link>{esc(url)}</link>\n' if url else ''
        description = _description(event, section).replace(']]>', ']]]]><![CDATA[>')
        title = ('[试刊] ' if preview else '') + _title(event)
        items.append('<item>\n' f'  <title>{esc(title)}</title>\n' f'{link_element}'
                     f'  <guid isPermaLink="false">{esc(guid)}</guid>\n' f'{date_element}'
                     f'  <category>{esc(SECTION_CN.get(section, section))}</category>\n'
                     f'  <description><![CDATA[{description}]]></description>\n' '</item>')
    desc = (f'游戏资讯、设计分析与开发实践。游戏动态 {counts.get("news", 0)} 条，'
            f'策划精选 {counts.get("features", 0)} 篇，AI 精华 {counts.get("ai", 0)} 条。')
    if not any(key in digest for key in ("news", "features", "ai")):
        desc = '游戏与开发阅读精选，保留原文来源和发布时间。'
    if preview:
        desc = '试刊预览，非正式发布。' + desc
    channel_title = '策划日报 · 游戏资讯与设计' + (' · 试刊' if preview else '')
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n<channel>\n'
            f'<title>{esc(channel_title)}</title>\n<link>{esc(SITE)}/</link>\n'
            f'<atom:link href="{esc(SITE)}/feed.xml" rel="self" type="application/rss+xml"/>\n'
            f'<description>{esc(desc)}</description>\n<language>zh-CN</language>\n'
            f'<lastBuildDate>{format_datetime(now)}</lastBuildDate>\n<generator>daily-ai-digest v3</generator>\n'
            + '\n'.join(items) + '\n</channel>\n</rss>\n')


def main():
    inp = sys.argv[1] if len(sys.argv) > 1 else "data/digest.json"
    out = sys.argv[2] if len(sys.argv) > 2 else "docs/feed.xml"
    with open(inp, encoding="utf-8") as handle:
        digest = json.load(handle)
    xml = build(digest)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as handle:
        handle.write(xml)
    print(f"[OK] RSS 已生成 → {out}（{xml.count('<item>')} 条）")


if __name__ == "__main__":
    main()
