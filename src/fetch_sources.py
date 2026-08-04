"""阶段①宽召回：并发抓取所有源，带时间窗过滤和社区热度信号。

与 v1 的区别：
  - 每源 12 篇而非 2 篇（召回求全，筛选交给 rank.py）
  - 36 小时时间窗（v1 完全没有，源把老文章顶上来就照收）
  - 抓 signals：HN points / HF upvotes / GitHub stars_today
  - Hacker News 改用 Algolia API（RSS 拿不到分数）
  - 并发抓取（v1 是串行，30 个源要几十秒）
  - 写 health.json，让静默失效的源暴露出来
"""
import concurrent.futures as futures
import hashlib
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import feedparser
import requests

from config import (
    RSS_SOURCES, DIVERSE_SOURCES, HFPAPERS_API, GITHUB_TRENDING_URLS,
    HN_API, HN_MIN_POINTS, HN_KEYWORDS,
    IGNORE_KEYWORDS, MAX_RECALL, MAX_PER_SOURCE, FRESH_WINDOW_HOURS,
    POLITE_UA_DOMAINS, POLITE_UA, BROWSER_UA, HEALTH_ALERT_DAYS,
)

TZ = timezone(timedelta(hours=8))
NOW = datetime.now(timezone.utc)
CUTOFF = NOW - timedelta(hours=FRESH_WINDOW_HOURS)

_session = requests.Session()
_session.headers.update({
    "User-Agent": BROWSER_UA,
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    "Accept-Language": "en,zh-CN;q=0.9",
})

HEALTH: dict[str, int] = {}


def _empty_signals() -> dict:
    return {"hn_points": 0, "hn_comments": 0, "hf_upvotes": 0, "stars_today": 0, "rank_bonus": 0.0}


def _fetch(url: str, timeout: int = 25) -> str | None:
    """带域名感知 UA 的抓取。Reddit 需要描述性 UA，伪装浏览器会被 403。"""
    headers = {}
    if any(d in url for d in POLITE_UA_DOMAINS):
        headers["User-Agent"] = POLITE_UA
    try:
        resp = _session.get(url, timeout=timeout, allow_redirects=True, headers=headers or None)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"[WARN] 抓取失败 {url} — {type(e).__name__}")
        return None


def _url_key(url: str) -> str:
    p = urlparse(url)
    key = f"{p.netloc.removeprefix('www.')}{p.path.rstrip('/')}"
    return hashlib.md5(key.encode()).hexdigest()


def _should_skip(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in IGNORE_KEYWORDS)


# Reddit 的 RSS 摘要末尾固定挂一段导航文字。不清掉的话它会跟着进 LLM 的
# 输入，也会显示在页面上 —— 实测样例：
#   "... &#32; submitted by &#32; /u/crazymikeee [link] &#32; [comments]"
_RSS_BOILERPLATE = re.compile(
    r"(submitted by\s*/u/\S+|\[link\]|\[comments\]|Read more|Continue reading.*)$",
    re.I)


def _clean_html(text: str, max_len: int = 600) -> str:
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    # 必须在去标签之后 unescape：先 unescape 会把 &lt;p&gt; 变成真标签再被删掉。
    # 实测 Reddit / The Verge 的 feed 里 &#32; &quot; &#8217; 满天飞。
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    for _ in range(3):
        new = _RSS_BOILERPLATE.sub("", text).strip(" ·-—|")
        if new == text:
            break
        text = new
    return text[:max_len]


def _entry_time(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        val = getattr(entry, attr, None)
        if val:
            try:
                return datetime(*val[:6], tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue
    return None


def _parse_entry(entry, src: dict) -> dict | None:
    link = (entry.get("link") or "").strip()
    # 标题也要清 HTML：Unreal Engine 官方 feed 的 <title> 里塞了 <p> 和 <em> 标签
    title = _clean_html(entry.get("title") or "", 300)
    if not link or not title or _should_skip(title):
        return None

    published = _entry_time(entry)
    # 时间窗过滤。没有时间戳的条目放过（很多官博不带 pubDate），
    # 但标记 undated，rank 阶段会轻微扣分。
    undated = published is None
    if published and published < CUTOFF:
        return None

    summary = entry.get("summary", "")
    if not summary and entry.get("content"):
        summary = entry["content"][0].get("value", "")

    return {
        "title": title,
        "url": link,
        "source": src["name"],
        "tier": src["tier"],
        "lang": src["lang"],
        "published": (published or NOW).isoformat(),
        "undated": undated,
        "summary_raw": _clean_html(summary),
        "signals": _empty_signals(),
        "pool": src.get("pool", "main"),
    }


def _fetch_rss(src: dict) -> list[dict]:
    raw = _fetch(src["url"])
    if raw is None:
        HEALTH[src["name"]] = 0
        return []

    feed = feedparser.parse(raw)
    out, taken = [], 0
    for i, entry in enumerate(feed.entries):
        if taken >= MAX_PER_SOURCE:
            break
        a = _parse_entry(entry, src)
        if not a:
            continue
        # Reddit 拿不到 ups，用 feed 内排位当极弱信号
        if src["name"].startswith("r/"):
            a["signals"]["rank_bonus"] = max(0.0, (10 - i) * 1.2)
        out.append(a)
        taken += 1

    HEALTH[src["name"]] = len(out)
    if not out:
        print(f"[WARN] 零产出: {src['name']}（源可能已失效，或 36h 内无新内容）")
    return out


# ─── Hacker News（Algolia API，带 points）─────────────────────

def fetch_hn() -> list[dict]:
    seen, out = set(), []
    since = int(CUTOFF.timestamp())

    def one(kw: str) -> list[dict]:
        params = {
            "query": kw,
            "tags": "story",
            "numericFilters": f"points>{HN_MIN_POINTS},created_at_i>{since}",
            "hitsPerPage": 10,
        }
        try:
            r = _session.get(HN_API, params=params, timeout=20)
            r.raise_for_status()
            return r.json().get("hits", [])
        except Exception as e:
            print(f"[WARN] HN 检索失败 ({kw}) — {type(e).__name__}")
            return []

    with futures.ThreadPoolExecutor(6) as ex:
        for hits in ex.map(one, HN_KEYWORDS):
            for h in hits:
                oid = h.get("objectID")
                if not oid or oid in seen:
                    continue
                seen.add(oid)
                title = (h.get("title") or "").strip()
                if not title or _should_skip(title):
                    continue
                url = h.get("url") or f"https://news.ycombinator.com/item?id={oid}"
                sig = _empty_signals()
                sig["hn_points"] = h.get("points", 0) or 0
                sig["hn_comments"] = h.get("num_comments", 0) or 0
                out.append({
                    "title": title,
                    "url": url,
                    "source": "Hacker News",
                    "tier": 2,
                    "lang": "en",
                    "published": h.get("created_at") or NOW.isoformat(),
                    "undated": False,
                    "summary_raw": "",
                    "signals": sig,
                    "hn_url": f"https://news.ycombinator.com/item?id={oid}",
                    "pool": "main",
                })

    out.sort(key=lambda a: a["signals"]["hn_points"], reverse=True)
    HEALTH["Hacker News"] = len(out)
    print(f"[OK] Hacker News: {len(out)} 条 (points>{HN_MIN_POINTS})")
    return out


# ─── HuggingFace 每日论文 ─────────────────────────────────────

def fetch_papers() -> list[dict]:
    raw = _fetch(HFPAPERS_API, timeout=25)
    if not raw:
        HEALTH["HuggingFace Papers"] = 0
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        HEALTH["HuggingFace Papers"] = 0
        return []

    out = []
    for item in data[:20]:
        paper = item.get("paper", {}) or {}
        title = (paper.get("title") or "").strip()
        aid = paper.get("id", "")
        if not title:
            continue
        authors = paper.get("authors", []) or []
        names = ", ".join(a.get("name", "") for a in authors[:3])
        if len(authors) > 3:
            names += " et al."
        sig = _empty_signals()
        # ⚠️ upvotes 在 paper 对象里，不在顶层。取错位置会静默返回 0，
        #    整个论文栏就退化成按抓取顺序排列。2026-08-03 实测修正。
        sig["hf_upvotes"] = paper.get("upvotes", 0) or 0
        sig["hn_comments"] = item.get("numComments", 0) or 0
        out.append({
            "title": title,
            "url": f"https://arxiv.org/abs/{aid}" if aid else "https://huggingface.co/papers",
            "source": "HuggingFace Papers",
            "tier": 1,
            "lang": "en",
            "published": paper.get("publishedAt") or NOW.isoformat(),
            "undated": False,
            "summary_raw": _clean_html(paper.get("summary") or ""),
            "authors": names,
            "signals": sig,
            "pool": "paper",
        })

    out.sort(key=lambda a: a["signals"]["hf_upvotes"], reverse=True)
    HEALTH["HuggingFace Papers"] = len(out)
    print(f"[OK] 论文: {len(out)} 篇")
    return out


# ─── GitHub Trending ─────────────────────────────────────────

def fetch_repos() -> list[dict]:
    out, seen = [], set()
    for period, url in GITHUB_TRENDING_URLS:
        html = _fetch(url, timeout=25)
        if not html:
            continue
        for a in _parse_trending(html, period):
            if a["url"] in seen:
                continue
            seen.add(a["url"])
            out.append(a)
    HEALTH["GitHub Trending"] = len(out)
    print(f"[OK] GitHub Trending: {len(out)} 个")
    return out


def _parse_trending(html: str, period: str) -> list[dict]:
    out = []
    for i, block in enumerate(re.split(r"</article>", html)):
        if '<article class="Box-row">' not in block:
            continue
        m = re.search(r'<a[^>]*href="(/([^/]+)/([^/"]+))"[^>]*class="Link"', block)
        if not m:
            continue
        full_name = f"{m.group(2)}/{m.group(3)}"

        dm = re.search(r'<p\s+class="col-9[^"]*">\s*(.*?)\s*</p>', block, re.S)
        desc = re.sub(r"<[^>]+>", "", dm.group(1)).strip() if dm else ""

        lm = re.search(r'itemprop="programmingLanguage">\s*([^<]+)', block)
        lang = lm.group(1).strip() if lm else ""

        sm = re.search(r"([\d,]+)\s+stars\s+today", block)
        stars_today = int(sm.group(1).replace(",", "")) if sm else 0

        tm = re.search(r"octicon-star.*?</svg>\s*([\d,]+)\s*</a>", block, re.S)
        total = int(tm.group(1).replace(",", "")) if tm else 0

        sig = _empty_signals()
        sig["stars_today"] = stars_today
        out.append({
            "title": full_name,
            "url": f"https://github.com/{full_name}",
            "source": "GitHub Trending",
            "tier": 1,
            "lang": "en",
            "published": NOW.isoformat(),
            "undated": False,
            "summary_raw": desc,
            "repo_lang": lang,
            "repo_stars": total,
            "signals": sig,
            "pool": "repo",
        })
    return out


# ─── 主流程 ──────────────────────────────────────────────────

def fetch_all() -> tuple[list[dict], dict]:
    diverse = [dict(s, pool="diverse") for s in DIVERSE_SOURCES]
    all_srcs = list(RSS_SOURCES) + diverse

    # Reddit 必须串行 + 间隔，并发请求会立刻吃 429（实测 4 个并发全挂）
    reddit = [s for s in all_srcs if "reddit.com" in s["url"]]
    normal = [s for s in all_srcs if "reddit.com" not in s["url"]]

    articles: list[dict] = []
    with futures.ThreadPoolExecutor(12) as ex:
        hn_f = ex.submit(fetch_hn)
        pf = ex.submit(fetch_papers)
        rf = ex.submit(fetch_repos)
        for group in ex.map(_fetch_rss, normal):
            articles.extend(group)
        hn, papers, repos = hn_f.result(), pf.result(), rf.result()

    for i, src in enumerate(reddit):
        if i:
            time.sleep(3)
        articles.extend(_fetch_rss(src))

    articles.extend(hn)

    # 全局 URL 去重（保留 tier 更高的那条）
    best: dict[str, dict] = {}
    for a in articles:
        k = _url_key(a["url"])
        if k not in best or a["tier"] < best[k]["tier"]:
            best[k] = a
    articles = list(best.values())
    articles.sort(key=lambda a: a["published"], reverse=True)
    articles = articles[:MAX_RECALL]

    # 论文/开源单独成池，不参与主排序竞争
    all_items = articles + papers + repos
    for i, a in enumerate(all_items):
        a["id"] = i

    pools = {}
    for a in all_items:
        pools[a["pool"]] = pools.get(a["pool"], 0) + 1
    print(f"[OK] 召回 {len(all_items)} 条 — {pools}")

    dead = sorted(k for k, v in HEALTH.items() if v == 0)
    if dead:
        print(f"[HEALTH] 零产出源 ({len(dead)}): {', '.join(dead)}")

    return all_items, dict(HEALTH)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "data/raw.json"
    # 默认就写 health.json。workflow 里是不带参数调用的，
    # 之前默认 None 等于让「零产出源告警」这个功能在线上永远不触发 ——
    # 而源静默失效恰好是这类项目最常见的死法，警报不能靠手动开启。
    health_out = sys.argv[2] if len(sys.argv) > 2 else "data/health.json"

    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    articles, health = fetch_all()

    with open(out, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)
    print(f"[OK] 已写入 {out}")

    if health_out:
        os.makedirs(os.path.dirname(os.path.abspath(health_out)), exist_ok=True)
        today = datetime.now(TZ).strftime("%Y-%m-%d")

        # 零产出天数要连续累计。单看当天 0 条分不清「源挂了」和「人家今天没发」，
        # 而这两件事的处理方式完全不同（前者要换源，后者什么都不用做）。
        prev = {}
        if os.path.exists(health_out):
            try:
                with open(health_out, encoding="utf-8") as f:
                    old = json.load(f)
                # 同一天重跑不推进连续计数
                if old.get("date") != today:
                    prev = old.get("zero_streak") or {}
                else:
                    prev = {k: max(0, v - 1) if health.get(k, 0) == 0 else v
                            for k, v in (old.get("zero_streak") or {}).items()}
            except (json.JSONDecodeError, OSError):
                prev = {}

        streak = {name: (prev.get(name, 0) + 1 if n == 0 else 0)
                  for name, n in health.items()}

        with open(health_out, "w", encoding="utf-8") as f:
            json.dump({"date": today, "counts": health, "zero_streak": streak}, f,
                      ensure_ascii=False, indent=2)
        long_dead = sorted(k for k, v in streak.items() if v >= HEALTH_ALERT_DAYS)
        print(f"[OK] 源健康度 → {health_out}"
              + (f"（连续 {HEALTH_ALERT_DAYS} 天以上零产出：{', '.join(long_dead)}）"
                 if long_dead else ""))


if __name__ == "__main__":
    main()
