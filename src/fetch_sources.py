"""RSS 抓取模块：从多个信息源抓取文章，去重后输出 JSON。
支持 RSS/Atom 源 + GitHub Trending + 论文速递 + 跨界视野。"""
import hashlib
import json
import os
import random
import re
import sys
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import feedparser
import requests

from config import (
    RSS_SOURCES, CUSTOM_SOURCES, HFPAPERS_SOURCE, DIVERSE_SOURCES,
    IGNORE_KEYWORDS, MAX_ARTICLES, MAX_PER_SOURCE, MAX_PAPERS, MAX_DIVERSE,
)

TZ = timezone(timedelta(hours=8))

_session = requests.Session()
_session.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; DailyAIDigest/1.0; +https://github.com/daily-ai-digest)",
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
})


def _safe_fetch(url: str, timeout: int = 20, headers: dict | None = None) -> str | None:
    try:
        resp = _session.get(url, timeout=timeout, allow_redirects=True, headers=headers)
        resp.raise_for_status()
        return resp.text
    except Exception:
        return None


def _url_key(url: str) -> str:
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


def _parse_entry(entry, name: str, lang: str) -> dict | None:
    """解析单个 feedparser entry，返回文章 dict 或 None。"""
    link = entry.get("link", "")
    if not link:
        return None

    title = entry.get("title", "").strip()
    if not title or _should_skip(title):
        return None

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

    return {
        "title": title,
        "url": link,
        "source": name,
        "lang": lang,
        "published": published.isoformat() if published else None,
        "summary_raw": _clean_html(summary),
    }


# ─── HuggingFace 论文速递 ─────────────────────────────────────

def fetch_hf_papers() -> list[dict]:
    """从 HuggingFace Daily Papers 取前 N 篇。"""
    raw = _safe_fetch(HFPAPERS_SOURCE["url"])
    if not raw:
        print("[WARN] HuggingFace Papers 抓取失败")
        return []

    feed = feedparser.parse(raw)
    articles = []
    for entry in feed.entries[:MAX_PAPERS]:
        a = _parse_entry(entry, "HuggingFace Papers", "en")
        if a:
            articles.append(a)

    print(f"[OK] 论文速递: {len(articles)} 篇")
    return articles


# ─── 跨界视野 ─────────────────────────────────────────────────

def fetch_diverse(date_seed: str) -> list[dict]:
    """每天从跨界池中随机抽 5 个源，各取 1 篇。
    用日期做随机种子，同一天结果一致。"""
    rng = random.Random(hash(date_seed))
    selected = rng.sample(DIVERSE_SOURCES, min(MAX_DIVERSE, len(DIVERSE_SOURCES)))

    articles = []
    for src in selected:
        raw = _safe_fetch(src["url"])
        if not raw:
            print(f"[WARN] 跨界源失败: {src['name']}")
            continue

        feed = feedparser.parse(raw)
        for entry in feed.entries[:3]:  # 取前 3 条，取第一条有效的
            a = _parse_entry(entry, src["name"], src["lang"])
            if a:
                articles.append(a)
                break  # 只要 1 篇

    # 保持随机顺序
    rng.shuffle(articles)
    print(f"[OK] 跨界视野: {len(articles)} 篇")
    return articles


# ─── GitHub Trending ───────────────────────────────────────────

def fetch_github_trending() -> list[dict]:
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
            if a["url"] not in seen:
                seen.add(a["url"])
                all_articles.append(a)

    print(f"[OK] GitHub Trending: {len(all_articles)} 个 (daily+weekly)")
    return all_articles


def _parse_trending_html(html: str, period: str) -> list[dict]:
    articles = []
    now = datetime.now(timezone.utc).isoformat()
    blocks = re.split(r'</article>', html)

    for block in blocks:
        if '<article class="Box-row">' not in block:
            continue
        repo_m = re.search(r'<a[^>]*href="(/([^/]+)/([^/"]+))"[^>]*class="Link"', block)
        if not repo_m:
            continue
        repo_path = repo_m.group(1)
        full_name = f"{repo_m.group(2)}/{repo_m.group(3)}"
        html_url = f"https://github.com{repo_path}"

        desc_m = re.search(r'<p\s+class="col-9\s+color-fg-muted\s+my-1\s+tmp-pr-4">\s*(.*?)\s*</p>', block, re.DOTALL)
        description = re.sub(r"<[^>]+>", "", desc_m.group(1)).strip() if desc_m else ""

        lang_m = re.search(r'itemprop="programmingLanguage">\s*([^<\s]+)', block)
        language = lang_m.group(1) if lang_m else ""

        stars_today = ""
        st_m = re.search(r'([\d,]+)\s+stars\s+today', block)
        if st_m:
            stars_today = st_m.group(1)

        total_stars = ""
        ts_m = re.search(r'octicon-star.*?</svg>\s*([\d,]+)\s*</a>', block, re.DOTALL)
        if ts_m:
            total_stars = ts_m.group(1)

        forks = ""
        fk_m = re.search(r'octicon-repo-forked.*?</svg>\s*([\d,]+)\s*</a>', block, re.DOTALL)
        if fk_m:
            forks = fk_m.group(1)

        title = f"[{language}] {full_name} ⭐{total_stars}" if language else f"{full_name} ⭐{total_stars}"
        extra = [f"🍴{forks}" if forks else "", f"🔥{stars_today} today" if stars_today else ""]
        extra_str = " | ".join(e for e in extra if e)
        summary = f"{description} — {extra_str}" if extra_str else description

        articles.append({
            "title": title,
            "url": html_url,
            "source": f"GitHub Trending ({period})",
            "lang": "en",
            "published": now,
            "summary_raw": summary or f"GitHub {period} trending",
        })

    return articles


# ─── 主抓取 ────────────────────────────────────────────────────

def fetch_all() -> list[dict]:
    seen = set()
    today_str = datetime.now(TZ).strftime("%Y-%m-%d")

    # ── 1. 特殊源（全量保留）──
    gh_articles = fetch_github_trending()
    paper_articles = fetch_hf_papers()
    diverse_articles = fetch_diverse(today_str)

    reserved_count = len(gh_articles) + len(paper_articles) + len(diverse_articles)

    # ── 2. RSS 源（每个源最多 2 篇）──
    rss_articles = []
    for src in RSS_SOURCES:
        raw = _safe_fetch(src["url"])
        if raw is None:
            print(f"[WARN] 抓取失败: {src['name']}")
            continue

        feed = feedparser.parse(raw)
        if feed.bozo:
            print(f"[WARN] RSS 解析异常: {src['name']} — {feed.bozo_exception}")

        taken = 0
        for entry in feed.entries:
            if taken >= MAX_PER_SOURCE:
                break
            a = _parse_entry(entry, src["name"], src["lang"])
            if a and _url_key(a["url"]) not in seen:
                seen.add(_url_key(a["url"]))
                rss_articles.append(a)
                taken += 1

    rss_articles.sort(key=lambda a: a["published"] or "", reverse=True)

    # ── 3. 给特殊源文章标记去重 key ──
    for a in gh_articles + paper_articles + diverse_articles:
        seen.add(_url_key(a["url"]))

    # ── 4. 组装：特殊源全保留，RSS 填剩余 ──
    remaining = MAX_ARTICLES - reserved_count
    if remaining < 0:
        remaining = 0
    rss_articles = rss_articles[:remaining]

    all_articles = gh_articles + paper_articles + diverse_articles + rss_articles
    print(f"[OK] 共 {len(all_articles)} 篇 (GitHub:{len(gh_articles)} 论文:{len(paper_articles)} 跨界:{len(diverse_articles)} RSS:{len(rss_articles)})")
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
