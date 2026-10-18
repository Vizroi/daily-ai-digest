"""抓取游戏新闻、设计分析与少量 AI；保留日期和正文来源的证据边界。"""
import concurrent.futures as futures
import hashlib
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import feedparser
import requests

from config import (
    RSS_SOURCES, PAGE_SOURCES, IGNORE_KEYWORDS, MAX_RECALL, MAX_PER_SOURCE,
    FRESH_WINDOW_HOURS, POLITE_UA_DOMAINS, POLITE_UA, BROWSER_UA, HEALTH_ALERT_DAYS,
)

TZ = timezone(timedelta(hours=8))
NOW = datetime.now(timezone.utc)
CUTOFF = NOW - timedelta(hours=FRESH_WINDOW_HOURS)
_session = requests.Session()
_session.headers.update({
    "User-Agent": BROWSER_UA,
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/html, */*",
    "Accept-Language": "en,zh-CN;q=0.9",
})
HEALTH: dict[str, int] = {}
SOURCE_REPORT = {}
FETCH_ERRORS = {}
SOURCE_DETAILS = {}
_ACCESS_HTTP_CODES = {401, 403, 412, 429}
_TRANSIENT_HTTP_CODES = {500, 502, 503, 504}


def _empty_signals() -> dict:
    return {"hn_points": 0, "hn_comments": 0, "hf_upvotes": 0, "stars_today": 0, "rank_bonus": 0.0}


def _fetch(url: str, timeout: int = 25) -> str | None:
    headers = {}
    if any(d in urlparse(url).netloc for d in POLITE_UA_DOMAINS):
        headers["User-Agent"] = POLITE_UA
    for attempt in range(2):
        try:
            resp = _session.get(url, timeout=timeout, allow_redirects=True, headers=headers or None)
            resp.raise_for_status()
            # requests 对不含 charset 的 text/html 默认猜 ISO-8859-1，不能据此解中文页面。
            if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
                resp.encoding = resp.apparent_encoding or "utf-8"
            FETCH_ERRORS.pop(url, None)
            return resp.text
        except requests.RequestException as exc:
            response = getattr(exc, "response", None)
            status = response.status_code if response is not None else None
            error = f"HTTP {status}" if status is not None else type(exc).__name__
            transient = isinstance(exc, requests.Timeout) or status in _TRANSIENT_HTTP_CODES
            if attempt == 0 and transient:
                if response is not None:
                    response.close()
                time.sleep(0.5)
                continue
            FETCH_ERRORS[url] = error
            print(f"[WARN] 抓取失败 {url} — {error}")
            return None


def _failure_status(error: str) -> tuple[str, str]:
    if error.startswith("HTTP "):
        code = error.removeprefix("HTTP ")
        if code.isdigit() and int(code) in _ACCESS_HTTP_CODES:
            return "blocked", f"平台访问限制（HTTP {code}）；未重试或绕过验证"
        suffix = "；重试后仍失败" if code.isdigit() and int(code) in _TRANSIENT_HTTP_CODES else ""
        return "error", f"来源返回 HTTP {code}{suffix}"
    if error in {"Timeout", "ConnectTimeout", "ReadTimeout"}:
        return "error", "网络请求超时；重试后仍失败"
    details = {"InvalidFeed": "响应不是可识别的 RSS / Atom 订阅",
               "NoArticleLinks": "已读取列表，但未识别出文章链接；需要检查页面结构"}
    return "error", details.get(error, f"读取异常（{error}）")


def _source_status(src: dict) -> dict:
    count = HEALTH.get(src["name"], 0)
    detail = SOURCE_DETAILS.get(src["url"], {})
    state = "ok" if count else "empty"
    message = detail.get("detail", "已取得候选" if count else "时间窗内未取得可用候选")
    if src["url"] in FETCH_ERRORS:
        state, message = _failure_status(FETCH_ERRORS[src["url"]])
    elif detail.get("state"):
        state = detail["state"]
    return {"id": "web-" + hashlib.sha1(src["url"].encode()).hexdigest()[:10],
            "name": src["name"], "url": src["url"], "platform": "网站 / RSS",
            "state": state, "count": count, "detail": message}


def _url_key(url: str) -> str:
    from cluster import canonical_url
    key = canonical_url(url)
    return hashlib.md5(key.encode()).hexdigest()


def _should_skip(title: str) -> bool:
    return any(kw in title.lower() for kw in IGNORE_KEYWORDS)


_RSS_BOILERPLATE = re.compile(
    r"(submitted by\s*/u/\S+|\[link\]|\[comments\]|Read more|Continue reading.*)$", re.I)


def _clean_html(text: str, max_len: int | None = 600) -> str:
    text = re.sub(r"<(?:script|style)\b[^>]*>.*?</(?:script|style)>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    for _ in range(3):
        cleaned = _RSS_BOILERPLATE.sub("", text).strip(" ·-—|")
        if cleaned == text:
            break
        text = cleaned
    return text[:max_len] if max_len is not None else text


def _parse_date(value: str | None, default_tz=timezone.utc) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    value = value.strip()
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(value)
        except (ValueError, TypeError, OverflowError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=default_tz)
    return dt.astimezone(timezone.utc)


def _entry_time(entry, attr: str = "published") -> datetime | None:
    # updated 不能冒充原始发布日期，单独保存在 updated 字段。
    # FeedParserDict 对缺失 updated 有 published 别名，不能误认作真实更新时间。
    parsed_key = f"{attr}_parsed"
    parsed = entry[parsed_key] if parsed_key in entry else None
    if parsed:
        try:
            return datetime(*parsed[:6], tzinfo=timezone.utc)
        except (ValueError, TypeError):
            pass
    return _parse_date(entry[attr] if attr in entry else None)


def _in_window(published: datetime | None, src: dict) -> bool:
    if published is None:
        return True  # 下游看见 undated，不把缺日期当作当天发布。
    cutoff = NOW - timedelta(hours=src.get("window_hours", FRESH_WINDOW_HOURS))
    return cutoff <= published <= NOW


def _record(title: str, link: str, src: dict, published: datetime | None,
            summary: str, *, rss_content: str = "", content_kind: str = "rss_summary",
            updated: datetime | None = None) -> dict:
    return {
        "title": title, "url": link, "source": src["name"],
        "source_url": src["url"], "tier": src["tier"], "lang": src["lang"],
        "category": src["category"], "pool": src.get("pool", "main"),
        "published": published.isoformat() if published else None,
        "undated": published is None,
        "date_kind": "published" if published else ("updated_only" if updated else "missing"),
        "updated": updated.isoformat() if updated else None,
        "retrieved_at": NOW.isoformat(),
        "summary_raw": _clean_html(summary),
        "rss_content": rss_content,
        "content_kind": content_kind,
        "signals": _empty_signals(),
        "source_id": src.get("id") or "web-" + hashlib.sha1(src["url"].encode()).hexdigest()[:10],
        "platform": src.get("platform", "网站 / RSS"),
        "evidence_kind": src.get("evidence_kind", "publisher_article"),
        "publication_scope": "public",
    }


def _parse_entry(entry, src: dict) -> dict | None:
    link = (entry.get("link") or "").strip()
    title = _clean_html(entry.get("title") or "", 300)
    if urlparse(link).scheme not in ("https", "http") or not title or _should_skip(title):
        return None
    published = _entry_time(entry)
    updated = _entry_time(entry, "updated")
    if not _in_window(published, src):
        return None
    # Atom content / RSS content:encoded 与摘要分开。绝不由摘要长度推断“全文”。
    contents = entry.get("content") or []
    content_html = "\n".join(c.get("value") or "" for c in contents if isinstance(c, dict))
    rss_content = _clean_html(content_html, None)
    summary = entry.get("summary") or content_html
    article = _record(title, link, src, published, summary,
                      rss_content=rss_content,
                      content_kind="rss_content" if rss_content else "rss_summary",
                      updated=updated)
    article["published_precision"] = "day" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(entry.get("published") or "")) else "second" if published else None
    return article


def _fetch_rss(src: dict) -> list[dict]:
    raw = _fetch(src["url"])
    if raw is None:
        HEALTH[src["name"]] = 0
        return []
    feed = feedparser.parse(raw)
    if not feed.entries and not feed.get("version"):
        FETCH_ERRORS[src["url"]] = "InvalidFeed"
    out = []
    for entry in feed.entries:
        article = _parse_entry(entry, src)
        if article:
            out.append(article)
        if len(out) >= src.get("max_per_source", MAX_PER_SOURCE):
            break
    HEALTH[src["name"]] = len(out)
    SOURCE_DETAILS[src["url"]] = {"detail":
        f"读取 {len(feed.entries)} 条订阅记录；{src.get('window_hours', FRESH_WINDOW_HOURS)} 小时时间窗内取得 {len(out)} 条候选"}
    if not out:
        status = _source_status(src)
        print(f"[{'INFO' if status['state'] == 'empty' else 'WARN'}] 零产出: {src['name']}（{status['detail']}）")
    return out


class _ListingParser(HTMLParser):
    def __init__(self, src: dict):
        super().__init__(convert_charrefs=True)
        self.src = src
        self.urls = []
        self.seen = set()

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        href = dict(attrs).get("href") or ""
        url = urljoin(self.src["url"], href)
        parsed = urlparse(url)
        own = urlparse(self.src["url"]).netloc.removeprefix("www.")
        if (parsed.scheme not in ("http", "https")
                or parsed.netloc.removeprefix("www.") != own
                or not re.fullmatch(self.src["link_pattern"], parsed.path)):
            return
        url = parsed._replace(query="", fragment="").geturl()
        if url not in self.seen:
            self.seen.add(url)
            self.urls.append(url)


class _ArticleParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = {}
        self.title_parts = []
        self.in_h1 = False
        self.h1_done = False
        self.in_json = False
        self.json_parts = []
        self.json_documents = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta":
            key = attrs.get("property") or attrs.get("name") or attrs.get("itemprop")
            if key and attrs.get("content"):
                self.meta.setdefault(key.lower(), attrs["content"])
        if tag == "h1" and not self.h1_done:
            self.in_h1 = True
        if tag == "script" and attrs.get("type") == "application/ld+json":
            self.in_json = True
            self.json_parts = []

    def handle_data(self, data):
        if self.in_h1:
            self.title_parts.append(data)
        if self.in_json:
            self.json_parts.append(data)

    def handle_endtag(self, tag):
        if tag == "h1" and self.in_h1:
            self.in_h1 = False
            self.h1_done = True
        if tag == "script" and self.in_json:
            self.in_json = False
            try:
                self.json_documents.append(json.loads("".join(self.json_parts)))
            except (json.JSONDecodeError, TypeError):
                pass


def _json_published(value) -> str | None:
    if isinstance(value, list):
        return next((date for item in value if (date := _json_published(item))), None)
    if isinstance(value, dict):
        if value.get("datePublished"):
            return value["datePublished"]
        if value.get("@graph"):
            return _json_published(value["@graph"])
    return None


def _parse_page_article(raw: str, link: str, src: dict) -> dict | None:
    parser = _ArticleParser()
    parser.feed(raw)
    title = _clean_html(" ".join(parser.title_parts) or parser.meta.get("og:title") or "", 300)
    if not title or _should_skip(title):
        return None
    stamp = (parser.meta.get("article:published_time") or parser.meta.get("datepublished")
             or _json_published(parser.json_documents))
    # indienova 的旧文 header-info 会提供 YYYY-MM-DD；近期只显示 MM-DD 时不猜年份。
    if not stamp:
        header = re.search(r'<span[^>]*class=["\'][^"\']*header-info[^"\']*["\'][^>]*>(.*?)</span>',
                           raw, re.S | re.I)
        if header:
            match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", _clean_html(header.group(1), None))
            stamp = match.group(0) if match else None
    published = _parse_date(stamp, TZ)
    if not _in_window(published, src):
        return None
    summary = parser.meta.get("description") or parser.meta.get("og:description") or ""
    article = _record(title, link, src, published, summary, content_kind="page_excerpt")
    article["published_precision"] = "day" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(stamp or "")) else "second" if published else None
    return article


def _fetch_page_source(src: dict) -> list[dict]:
    raw = _fetch(src["url"])
    if raw is None:
        HEALTH[src["name"]] = 0
        return []
    listing = _ListingParser(src)
    listing.feed(raw)
    if not listing.urls:
        FETCH_ERRORS[src["url"]] = "NoArticleLinks"
    limit = src.get("max_per_source", MAX_PER_SOURCE)

    def one(url):
        page = _fetch(url)
        return _parse_page_article(page, url, src) if page else None

    # 热门推荐可能在新稿前面，适度多看一些候选，但不扫描整个网站。
    with futures.ThreadPoolExecutor(4) as executor:
        attempted = listing.urls[:limit * 2]
        out = [item for item in executor.map(one, attempted) if item]
    out = out[:limit]
    HEALTH[src["name"]] = len(out)
    errors = [FETCH_ERRORS[url] for url in attempted if url in FETCH_ERRORS]
    detail = f"读取 {len(attempted)} 篇文章页面；{src.get('window_hours', FRESH_WINDOW_HOURS)} 小时时间窗内取得 {len(out)} 条候选"
    if errors:
        reasons = "、".join(sorted(set(errors)))
        detail += f"；其中 {len(errors)} 篇未能读取（{reasons}）"
    SOURCE_DETAILS[src["url"]] = {"detail": detail}
    if errors:
        if len(errors) < len(attempted):
            SOURCE_DETAILS[src["url"]]["state"] = "degraded"
        else:
            SOURCE_DETAILS[src["url"]]["state"] = (
                "blocked" if all(_failure_status(error)[0] == "blocked" for error in errors) else "error")
    if not out:
        status = _source_status(src)
        print(f"[{'INFO' if status['state'] == 'empty' else 'WARN'}] 零产出: {src['name']}（{status['detail']}）")
    return out


def _deduplicate(articles: list[dict]) -> list[dict]:
    best = {}
    for item in articles:
        # 私域材料不能与公开报道合并，继承/泄露其正文。
        key = (_url_key(item["url"]), item.get("publication_scope", "public"))
        previous = best.get(key)
        if previous is None:
            best[key] = item
            continue
        quality = lambda x: (x.get("category") == "design", -x["tier"], bool(x.get("rss_content")))
        preferred, other = (item, previous) if quality(item) > quality(previous) else (previous, item)
        merged = dict(preferred)
        # 列表分类更具体时，仍保留 RSS 的正文与真实时间，避免去重丢证据。
        for field in ("rss_content", "summary_raw", "published", "updated", "published_precision"):
            if not merged.get(field) and other.get(field):
                merged[field] = other[field]
        merged["undated"] = merged.get("published") is None
        if merged["published"]:
            merged["date_kind"] = "published"
        if merged.get("rss_content") and merged.get("content_kind") not in {"api_content", "community_selftext", "community_message"}:
            merged["content_kind"] = "rss_content"
        best[key] = merged
    return list(best.values())


def fetch_all() -> tuple[list[dict], dict]:
    HEALTH.clear()
    FETCH_ERRORS.clear()
    SOURCE_DETAILS.clear()
    SOURCE_REPORT.clear()
    tasks = [(src, _fetch_rss) for src in RSS_SOURCES]
    tasks += [(src, _fetch_page_source) for src in PAGE_SOURCES]
    articles, statuses = [], []
    from importlib import import_module
    with futures.ThreadPoolExecutor(8) as executor:
        pending = {executor.submit(fetcher, src): src for src, fetcher in tasks}
        adapters = {executor.submit(import_module(name).fetch_sources, now=NOW): name
                    for name in ("public_sources", "creator_sources")}
        for future in futures.as_completed(pending):
            src = pending[future]
            try:
                articles.extend(future.result())
            except Exception as exc:
                HEALTH[src["name"]] = 0
                FETCH_ERRORS[src["url"]] = type(exc).__name__
                print(f"[WARN] 源解析失败 {src['name']} — {type(exc).__name__}")
        for future in futures.as_completed(adapters):
            name = adapters[future]
            try:
                collected, reports = future.result()
                articles.extend(collected)
                statuses.extend(reports)
                for report in reports:
                    HEALTH[report["name"]] = report.get("count", 0)
            except Exception as exc:
                print(f"[WARN] 平台采集失败 {name} — {type(exc).__name__}")
                from source_registry import catalog
                for src in catalog():
                    if src.get("module") == name:
                        statuses.append({**src, "state": "error", "count": 0,
                                         "detail": "本轮适配器异常，未取得候选"})
    for src, _ in tasks:
        statuses.append(_source_status(src))
    from source_registry import inbox_articles
    manual, inbox_status = inbox_articles(NOW)
    articles.extend(manual)
    statuses.append(inbox_status)
    raw_count = len(articles)
    articles = _deduplicate(articles)
    unique_count = len(articles)
    # Discord 等私域材料只计数；不进入模型、公开 JSON、页面或 RSS。
    restricted = sum(a.get("publication_scope", "public") != "public" for a in articles)
    articles = [a for a in articles if a.get("publication_scope", "public") == "public"]
    articles.sort(key=lambda a: a.get("published") or "", reverse=True)
    articles = articles[:MAX_RECALL]
    # 公开报告只保存汇总状态，频道ID及原始响应不出现在发布目录。
    public_statuses = [{key: status[key] for key in ("id", "name", "platform", "url", "state", "count", "detail")
                        if key in status} for status in statuses]
    SOURCE_REPORT.update(checked_at=NOW.isoformat(), sources=public_statuses,
                         counts={"raw": raw_count, "deduplicated": unique_count,
                                 "retained": len(articles), "restricted_withheld": restricted})
    for index, article in enumerate(articles):
        article["id"] = index
    categories = {}
    for article in articles:
        key = article["category"]
        categories[key] = categories.get(key, 0) + 1
    print(f"[OK] 召回 {len(articles)} 条 — {categories}")
    return articles, dict(HEALTH)


def _health_payload(health: dict, previous: dict, today: str) -> dict:
    previous_streak = previous.get("zero_streak") or {}
    same_day = previous.get("date") == today
    streak = {}
    for name, count in health.items():
        old_count = (previous.get("counts") or {}).get(name)
        old_streak = previous_streak.get(name, 0)
        if count:
            streak[name] = 0
        elif same_day:
            streak[name] = old_streak if old_count == 0 else 1
        else:
            streak[name] = old_streak + 1
    return {"date": today, "counts": health, "zero_streak": streak}


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "data/raw.json"
    health_out = sys.argv[2] if len(sys.argv) > 2 else "data/health.json"
    report_out = sys.argv[3] if len(sys.argv) > 3 else "data/source_report.json"
    articles, health = fetch_all()
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as stream:
        json.dump(articles, stream, ensure_ascii=False, indent=2)
    print(f"[OK] 已写入 {out}")
    os.makedirs(os.path.dirname(os.path.abspath(report_out)), exist_ok=True)
    with open(report_out, "w", encoding="utf-8") as stream:
        json.dump(SOURCE_REPORT, stream, ensure_ascii=False, indent=2)
    if health_out:
        os.makedirs(os.path.dirname(os.path.abspath(health_out)), exist_ok=True)
        previous = {}
        if os.path.exists(health_out):
            try:
                with open(health_out, encoding="utf-8") as stream:
                    previous = json.load(stream)
            except (json.JSONDecodeError, OSError):
                pass
        payload = _health_payload(health, previous, datetime.now(TZ).strftime("%Y-%m-%d"))
        with open(health_out, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
        stale = [name for name, days in payload["zero_streak"].items() if days >= HEALTH_ALERT_DAYS]
        print(f"[OK] 源健康度 → {health_out}" + (f"（长期零产出：{', '.join(stale)}）" if stale else ""))


if __name__ == "__main__":
    main()
