"""RSS 抓取模块：从多个信息源抓取文章，去重后输出 JSON。
支持 RSS/Atom 源 + GitHub Trending 自定义源。"""
import json
import hashlib
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import feedparser
import requests

from config import RSS_SOURCES, IGNORE_KEYWORDS, MAX_ARTICLES, CUSTOM_SOURCES

# 东八区
TZ = timezone(timedelta(hours=8))

_session = requests.Session()
_session.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; DailyAIDigest/1.0; +https://github.com/daily-ai-digest)",
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
})


def _safe_fetch(url: str, timeout: int = 20, headers: dict | None = None) -> str | None:
    """安全请求 URL，失败返回 None。"""
    try:
        resp = _session.get(url, timeout=timeout, allow_redirects=True, headers=headers)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        return None


def _safe_fetch_json(url: str, timeout: int = 20, headers: dict | None = None) -> dict | None:
    """请求 JSON API，失败返回 None。"""
    try:
        resp = _session.get(url, timeout=timeout, allow_redirects=True, headers=headers)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def _url_key(url: str) -> str:
    """将 URL 标准化为去重用的 Key。"""
    parsed = urlparse(url)
    netloc = parsed.netloc.removeprefix("www.")
    path = parsed.path.rstrip("/")
    key = f"{netloc}{path}{parsed.query}"
    return hashlib.md5(key.encode()).hexdigest()


def _should_skip(title: str) -> bool:
    title_lower = title.lower()
    return any(kw in title_lower for kw in IGNORE_KEYWORDS)


def _clean_html(text: str, max_len: int = 300) -> str:
    text = re.sub(r"<[^>]+>", "", text).strip()
    return text[:max_len] if len(text) > max_len else text


# ─── GitHub Trending ───────────────────────────────────────────

def fetch_github_trending() -> list[dict]:
    """通过 GitHub Search API 拉取近期最热项目（按 stars 排序，近 7 天创建/更新）。
    不需要 token 也能用，但有 token 可以提升速率上限。"""
    articles = []

    # 策略：搜索近 7 天创建 且 stars > 50 的仓库，按 stars 降序
    since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    queries = [
        # AI 相关
        f"ai+machine+learning+created:>={since}+stars:>100+fork:true",
        # 游戏相关
        f"game+created:>={since}+stars:>50+fork:true",
        # 通用 trending
        f"created:>={since}+stars:>200+fork:true",
    ]

    gh_token = os.environ.get("GITHUB_TOKEN", "")
    headers = {"Accept": "application/vnd.github+json"}
    if gh_token:
        headers["Authorization"] = f"Bearer {gh_token}"

    seen_repos = set()

    for q in queries:
        url = f"https://api.github.com/search/repositories?q={q}&sort=stars&order=desc&per_page=10"
        data = _safe_fetch_json(url, headers=headers)
        if not data:
            print(f"[WARN] GitHub API 请求失败: {q[:40]}...")
            continue

        for repo in data.get("items", []):
            rid = repo.get("id")
            if rid in seen_repos:
                continue
            seen_repos.add(rid)

            name = repo.get("full_name", "")
            description = repo.get("description") or ""
            html_url = repo.get("html_url", "")
            stars = repo.get("stargazers_count", 0)
            lang = repo.get("language") or ""
            created = repo.get("created_at", "")
            topics = repo.get("topics", [])

            title = f"[{lang}] {name} — ⭐{stars}"
            summary = description
            if topics:
                summary += f" | Topics: {', '.join(topics[:5])}"

            articles.append({
                "title": title,
                "url": html_url,
                "source": "GitHub Trending",
                "lang": "en",
                "published": created if created else None,
                "summary_raw": summary,
            })

    print(f"[OK] GitHub Trending 抓到 {len(articles)} 个热门仓库")
    return articles


# ─── 主抓取 ────────────────────────────────────────────────────

def fetch_all() -> list[dict]:
    """抓取所有 RSS 源 + 自定义源，返回去重 + 按时间排序的文章列表。"""
    seen = set()
    articles = []

    # ── RSS 源 ──
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

        for entry in feed.entries[:30]:
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

            published = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                published = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)

            summary = ""
            if hasattr(entry, "summary"):
                summary = entry.summary
            elif hasattr(entry, "content"):
                summary = entry.content[0].get("value", "") if entry.content else ""

            articles.append({
                "title": title,
                "url": link,
                "source": name,
                "lang": lang,
                "published": published.isoformat() if published else None,
                "summary_raw": _clean_html(summary),
            })

    # ── 自定义源 ──
    for cs in CUSTOM_SOURCES:
        if cs["type"] == "github_trending":
            trending = fetch_github_trending()
            for a in trending:
                key = _url_key(a["url"])
                if key in seen:
                    continue
                seen.add(key)
                articles.append(a)

    # 按发布时间降序排序
    articles.sort(key=lambda a: a["published"] or "", reverse=True)

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
