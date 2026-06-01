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
    """爬取 https://github.com/trending?since=daily 的每日热门仓库。
    这是按 star 增长率排名的，和 GitHub Search API 的绝对 star 数完全不同。"""
    from html.parser import HTMLParser

    # 分别抓 daily / weekly 确保不遗漏
    urls = [
        ("daily", "https://github.com/trending?since=daily"),
        ("weekly", "https://github.com/trending?since=weekly"),
    ]

    all_articles = []
    seen = set()

    for period, url in urls:
        html = _safe_fetch(url, timeout=25, headers={
            "User-Agent": "Mozilla/5.0 (compatible; DailyAIDigest/1.0; +https://github.com/daily-ai-digest)",
            "Accept": "text/html",
        })
        if not html:
            print(f"[WARN] GitHub Trending ({period}) 抓取失败")
            continue

        articles = _parse_trending_html(html, period)
        for a in articles:
            key = a["url"]
            if key not in seen:
                seen.add(key)
                all_articles.append(a)

    print(f"[OK] GitHub Trending 抓到 {len(all_articles)} 个热门仓库 (daily+weekly)")
    return all_articles


def _parse_trending_html(html: str, period: str) -> list[dict]:
    """从 GitHub Trending 页面 HTML 中解析仓库列表。"""
    from html.parser import HTMLParser

    articles = []
    now = datetime.now(timezone.utc).isoformat()

    # GitHub Trending 页面结构：每个仓库在一个 <article class="Box-row"> 中
    # 标题在 <h2> 内的 <a>，描述在 <p>，元数据在后面的元素
    # 更简单的方式：用正则提取关键信息

    # 匹配每个仓库块
    repo_blocks = re.findall(
        r'<article\s+class="Box-row"[^>]*>(.*?)</article>',
        html, re.DOTALL
    )

    for block in repo_blocks:
        # 提取仓库名 (h2 里的 a 标签，href 到仓库)
        repo_match = re.search(
            r'<h2[^>]*>.*?<a\s+href="(/([^/]+)/([^"]+))"[^>]*>',
            block, re.DOTALL
        )
        if not repo_match:
            continue

        repo_path = repo_match.group(1)  # /owner/repo
        owner = repo_match.group(2)
        repo = repo_match.group(3).strip()

        full_name = f"{owner}/{repo}"
        html_url = f"https://github.com{repo_path}"

        # 清理仓库名中的 span 标签（如 <span class="text-normal"> / </span>）
        # 这些已经被我们上面的正则跳过了

        # 提取描述
        desc_match = re.search(
            r'<p\s+class="[^"]*col-9[^"]*"[^>]*>(.*?)</p>',
            block, re.DOTALL
        )
        description = ""
        if desc_match:
            description = re.sub(r"<[^>]+>", "", desc_match.group(1)).strip()

        # 提取语言
        lang_match = re.search(
            r'itemprop="programmingLanguage">\s*([^<\s]+)',
            block
        )
        language = lang_match.group(1) if lang_match else ""

        # 提取 stars / forks
        stars = 0
        forks = 0
        stars_match = re.search(r'(\d[\d,]*)\s*stars\s+today', block, re.IGNORECASE)
        if stars_match:
            stars = int(stars_match.group(1).replace(",", ""))

        # 提取 total stars（可选）
        total_stars_match = re.search(r'(\d[\d,]*)\s*stars', block)
        if total_stars_match:
            try:
                stars = int(total_stars_match.group(1).replace(",", ""))
            except:
                pass

        # 简短的 extra info
        star_text = f"⭐{stars}" if stars else ""
        lang_text = f"[{language}]" if language else ""
        title = f"{lang_text} {full_name} {star_text}".strip()

        topics = re.findall(r'topic-tag[^>]*>([^<]+)<', block)
        topics_str = f" | Topics: {', '.join(topics[:5])}" if topics else ""

        articles.append({
            "title": title,
            "url": html_url,
            "source": "GitHub Trending",
            "lang": "en",
            "published": now,
            "summary_raw": f"{description}{topics_str}" if description else f"GitHub {period} trending repository{topics_str}",
        })

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
    trending_articles = []
    for cs in CUSTOM_SOURCES:
        if cs["type"] == "github_trending":
            trending_articles = fetch_github_trending()
            for a in trending_articles:
                key = _url_key(a["url"])
                seen.add(key)  # 标记去重，RSS 不会重复

    # 按发布时间降序排序 RSS 文章
    articles.sort(key=lambda a: a["published"] or "", reverse=True)

    # GitHub Trending 全量保留，RSS 文章填充剩余额度
    gh_count = len(trending_articles)
    remaining = MAX_ARTICLES - gh_count
    if remaining < 0:
        remaining = 0  # 极端情况：trending 超过上限也全留
    rss_articles = articles[:remaining]

    # 合并：GitHub 热门排在前面
    all_articles = trending_articles + rss_articles

    print(f"[OK] 共抓取 {len(all_articles)} 篇文章（GitHub热门 {gh_count} + RSS {len(rss_articles)}）")
    return all_articles


def main():
    output = sys.argv[1] if len(sys.argv) > 1 else "docs/articles_raw.json"
    os.makedirs(os.path.dirname(output), exist_ok=True)
    articles = fetch_all()
    with open(output, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)
    print(f"[OK] 已写入 {output}")


if __name__ == "__main__":
    main()
