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
    """爬取 https://github.com/trending 的每日 + 每周热门仓库。
    按 star 增长率排名，和 GitHub Search API 完全不同。"""
    from html.parser import HTMLParser

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
    """从 GitHub Trending 页面 HTML 中解析仓库列表。

    GitHub Trending 实际 HTML 结构（每个仓库块）：
      <article class="Box-row">
        <h2 class="h3 lh-condensed">
          <a href="/owner/repo" class="Link">  ... repo name ... </a>
        </h2>
        <p class="col-9 color-fg-muted my-1 tmp-pr-4">description</p>
        <div class="f6 color-fg-muted mt-2">
          <span itemprop="programmingLanguage">Python</span>
          ... total stars ...
          ... forks ...
          <span> 1,937 stars today </span>
        </div>
      </article>
    """
    articles = []
    now = datetime.now(timezone.utc).isoformat()

    # 按 </article> 分割每个仓库块
    blocks = re.split(r'</article>', html)

    for block in blocks:
        if '<article class="Box-row">' not in block:
            continue

        # 1. 提取仓库路径: <a href="/owner/repo" class="Link">
        repo_m = re.search(
            r'<a[^>]*href="(/([^/"]+)/([^/"]+))"[^>]*class="Link"',
            block
        )
        if not repo_m:
            continue

        repo_path = repo_m.group(1)
        owner = repo_m.group(2)
        repo_name = repo_m.group(3)
        full_name = f"{owner}/{repo_name}"
        html_url = f"https://github.com{repo_path}"

        # 2. 提取描述: <p class="col-9 color-fg-muted my-1 tmp-pr-4">
        desc_m = re.search(
            r'<p\s+class="col-9\s+color-fg-muted\s+my-1\s+tmp-pr-4">\s*(.*?)\s*</p>',
            block, re.DOTALL
        )
        description = ""
        if desc_m:
            description = re.sub(r"<[^>]+>", "", desc_m.group(1)).strip()

        # 3. 提取语言: <span itemprop="programmingLanguage">Python</span>
        lang_m = re.search(r'itemprop="programmingLanguage">\s*([^<\s]+)', block)
        language = lang_m.group(1) if lang_m else ""

        # 4. 提取 stars today: "... stars today" (如 "1,937 stars today")
        stars_today = ""
        stars_today_m = re.search(r'([\d,]+)\s+stars\s+today', block)
        if stars_today_m:
            stars_today = stars_today_m.group(1)

        # 5. 提取 total stars: </svg> 后面跟着数字，然后是 </a>
        total_stars = ""
        total_stars_m = re.search(
            r'octicon-star.*?</svg>\s*([\d,]+)\s*</a>',
            block, re.DOTALL
        )
        if total_stars_m:
            total_stars = total_stars_m.group(1)

        # 6. 提取 forks
        forks = ""
        forks_m = re.search(
            r'octicon-repo-forked.*?</svg>\s*([\d,]+)\s*</a>',
            block, re.DOTALL
        )
        if forks_m:
            forks = forks_m.group(1)

        # 拼接标题
        title_parts = []
        if language:
            title_parts.append(f"[{language}]")
        title_parts.append(full_name)
        title_parts.append(f"⭐{total_stars}")
        title = " ".join(title_parts)

        # 拼接摘要
        summary_parts = []
        if description:
            summary_parts.append(description)
        extra = []
        if forks:
            extra.append(f"🍴{forks}")
        if stars_today:
            extra.append(f"🔥{stars_today} today")
        if extra:
            summary_parts.append(" | ".join(extra))
        summary = " — ".join(summary_parts) if summary_parts else f"GitHub {period} trending"

        articles.append({
            "title": title,
            "url": html_url,
            "source": f"GitHub Trending ({period})",
            "lang": "en",
            "published": now,
            "summary_raw": summary,
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
