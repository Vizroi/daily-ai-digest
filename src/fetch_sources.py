"""RSS 抓取模块：从多个信息源抓取文章，去重后输出 JSON。"""
import json
import hashlib
import os
import sys
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import feedparser
import requests

from config import RSS_SOURCES, IGNORE_KEYWORDS, MAX_ARTICLES

# 东八区
TZ = timezone(timedelta(hours=8))

_session = requests.Session()
_session.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; DailyAIDigest/1.0; +https://github.com/daily-ai-digest)",
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
})


def _safe_fetch(url: str, timeout: int = 20) -> str | None:
    """安全请求 RSS URL，失败返回 None。"""
    try:
        resp = _session.get(url, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except Exception:
        return None


def _url_key(url: str) -> str:
    """将 URL 标准化为去重用的 Key（去协议 + 去末尾斜杠 + 去 www）。"""
    parsed = urlparse(url)
    netloc = parsed.netloc.removeprefix("www.")
    path = parsed.path.rstrip("/")
    key = f"{netloc}{path}{parsed.query}"
    return hashlib.md5(key.encode()).hexdigest()


def _should_skip(title: str) -> bool:
    title_lower = title.lower()
    return any(kw in title_lower for kw in IGNORE_KEYWORDS)


def fetch_all() -> list[dict]:
    """抓取所有 RSS 源，返回去重 + 按时间排序的文章列表。"""
    seen = set()
    articles = []

    for src in RSS_SOURCES:
        name = src["name"]
        url = src["url"]
        lang = src["lang"]

        raw = _safe_fetch(url)
        if raw is None:
            print(f"[WARN] 抓取失败: {name} ({url})")
            continue

        feed = feedparser.parse(raw)
        if feed.bozo:
            print(f"[WARN] RSS 解析异常: {name} — {feed.bozo_exception}")

        for entry in feed.entries[:30]:  # 每个源最多取 30 篇
            link = entry.get("link", "")
            if not link:
                continue

            key = _url_key(link)
            if key in seen:
                continue
            seen.add(key)

            title = entry.get("title", "").strip()
            if not title or _should_skip(title):
                continue

            # 发布时间
            published = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                published = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)

            # 原始摘要
            summary = ""
            if hasattr(entry, "summary"):
                summary = entry.summary
            elif hasattr(entry, "content"):
                summary = entry.content[0].get("value", "") if entry.content else ""

            # 清理 HTML 标签（简单处理）
            import re
            summary = re.sub(r"<[^>]+>", "", summary).strip()
            summary = summary[:300] if len(summary) > 300 else summary

            articles.append({
                "title": title,
                "url": link,
                "source": name,
                "lang": lang,
                "published": published.isoformat() if published else None,
                "summary_raw": summary,
            })

    # 按发布时间降序排序
    articles.sort(key=lambda a: a["published"] or "", reverse=True)

    # 取上限
    articles = articles[:MAX_ARTICLES]

    print(f"[OK] 共抓取 {len(articles)} 篇文章（去重后）")
    return articles


def main():
    output = sys.argv[1] if len(sys.argv) > 1 else "docs/articles_raw.json"
    os.makedirs(os.path.dirname(output), exist_ok=True)
    articles = fetch_all()
    with open(output, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)
    print(f"[OK] 已写入 {output}")


if __name__ == "__main__":
    main()
