"""公开的一手公告与开发者文章。只发起 GET，不登录、不订阅、不加入社区。

目录在 data/public_sources.json。Steam 严格限制官方公告 feed；日期未知保留
null。rss_content 是兼容现有流水线的正文槽，content_kind 说明 API/RSS/页面来源。
"""
import concurrent.futures as futures
import html
import json
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import feedparser
import requests

from source_http import failure_reason, get_response

SOURCE_FILE = Path(__file__).resolve().parents[1] / "data" / "public_sources.json"
STEAM_API = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
STEAM_OFFICIAL_FEED = "steam_community_announcements"
USER_AGENT = "DailyGameDigest/3.1 (+https://github.com/Vizroi/daily-ai-digest)"
REQUEST_TIMEOUT = (5, 20)


class SourceFailure(Exception):
    def __init__(self, state, detail):
        super().__init__(detail)
        self.state, self.detail = state, detail


def load_catalog():
    with SOURCE_FILE.open(encoding="utf-8") as stream:
        catalog = json.load(stream)
    if not isinstance(catalog, list):
        raise ValueError("public_sources.json must contain a list")
    return catalog


def _get(url, *, params=None):
    try:
        response = get_response(url, params=params, timeout=REQUEST_TIMEOUT,
                                headers={"User-Agent": USER_AGENT})
    except requests.RequestException as exc:
        details = {
            "tls_eof": "TLS 连接被中途断开；有限重试后仍失败",
            "tls_certificate": "TLS 证书校验失败；已停止请求",
            "timeout": "网络请求超时；有限重试后仍失败",
        }
        detail = details.get(failure_reason(exc), f"请求失败：{type(exc).__name__}")
        raise SourceFailure("error", detail) from exc
    if response.status_code == 401:
        raise SourceFailure("needs_auth", "HTTP 401：入口要求身份验证；未尝试登录")
    if response.status_code in (403, 412):
        raise SourceFailure("blocked", f"HTTP {response.status_code}：公开入口访问受限；未尝试登录或绕过")
    if response.status_code == 429:
        raise SourceFailure("blocked", "HTTP 429：平台限制请求频率，等待后续采集")
    if response.status_code >= 400:
        raise SourceFailure("error", f"HTTP {response.status_code}")
    return response


def _text(raw):
    raw = re.sub(r"<(?:script|style)\b[^>]*>.*?</(?:script|style)>", " ", raw or "", flags=re.S | re.I)
    raw = re.sub(r"\[img\].*?\[/img\]", " ", raw, flags=re.S | re.I)
    raw = re.sub(r"\[/?(?:h[1-6]|b|i|u|s|list|olist|\*|quote|code|table|tr|td|th|url|img|previewyoutube)(?:[=\s][^\]]*)?\]",
                 " ", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(raw)).strip()


def _date(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if value <= 0:
            return None
        try:
            return datetime.fromtimestamp(value, timezone.utc)
        except (ValueError, OverflowError, OSError):
            return None
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (ValueError, TypeError, OverflowError):
            parsed = None
            for date_format in ("%b %d, %Y", "%B %d, %Y"):
                try:
                    parsed = datetime.strptime(value.strip(), date_format)
                    break
                except ValueError:
                    continue
            if parsed is None:
                return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _feed_date(entry, field="published"):
    # FeedParserDict has compatibility aliases from updated to published: use real keys only.
    parsed_key = f"{field}_parsed"
    if parsed_key in entry and entry[parsed_key]:
        try:
            return datetime(*entry[parsed_key][:6], tzinfo=timezone.utc)
        except (ValueError, TypeError):
            pass
    return _date(entry[field]) if field in entry else None


def _in_window(stamp, source, now):
    return stamp is None or now - timedelta(hours=source.get("window_hours", 72)) <= stamp <= now


def _date_exclusion(stamp, source, now):
    if stamp is not None and stamp > now:
        return "future"
    if not _in_window(stamp, source, now):
        return "old"
    return None


def _read_detail(total, rows, excluded, dates, source, now, *, partial=False):
    """Describe successful reads separately from why candidates were not retained."""
    if total and excluded.get("invalid", 0) == total:
        raise SourceFailure("error", f"入口有响应，但 {total} 条候选均缺少有效标题或链接；需检查内容格式")
    outcome = "部分读取成功" if partial else "读取正常"
    parts = [f"{outcome}，共检查 {total} 条，收录 {len(rows)} 条"]
    labels = {"old": f"早于最近 {source.get('window_hours', 72)} 小时",
              "future": "发布时间在未来", "source": "不符合来源规则", "invalid": "标题或链接无效"}
    parts.extend(f"{label} {excluded[reason]} 条" for reason, label in labels.items() if excluded.get(reason))
    known_dates = [stamp for stamp in dates if stamp is not None and stamp <= now]
    if known_dates:
        latest = max(known_dates).astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
        parts.append(f"本轮最新原文日期 {latest}（北京时间）")
    unknown_dates = sum(row["undated"] for row in rows)
    if unknown_dates:
        parts.append(f"{unknown_dates} 条原文日期未知，需核验后才能作为新消息")
    return "；".join(parts)


def _limit(source):
    return max(0, min(20, int(source.get("max_per_source", 20))))


def _article(source, title, url, stamp, text="", *, content="", kind="rss_summary",
             author=None, precision="timestamp"):
    row = {
        "title": _text(title), "url": url, "source": source["name"],
        "source_id": source["id"], "source_url": source["url"],
        "platform": source["platform"], "evidence_kind": source.get("evidence_kind", "developer_article"),
        "requires_transcript": False,
        "tier": source["tier"], "lang": source["lang"], "category": source["category"],
        "published": stamp.isoformat() if stamp else None, "undated": stamp is None,
        "published_precision": precision if stamp else "unknown",
        "summary_raw": _text(text or content)[:600], "rss_content": _text(content),
        "content_kind": kind, "pool": "main",
        "signals": {"hn_points": 0, "hn_comments": 0, "hf_upvotes": 0,
                    "stars_today": 0, "rank_bonus": 0.0},
    }
    if author:
        row["author"] = author
    return row


def _status(source, state, count, detail):
    return {"id": source.get("id", "unknown"), "name": source.get("name", "Unknown"),
            "platform": source.get("platform", "developer_blog"), "url": source.get("url", ""),
            "state": state, "count": count, "detail": detail}


def _steam(source, now, *, diagnostics=None):
    appid = int(source["appid"])
    response = _get(source.get("endpoint", STEAM_API), params={
        "appid": appid, "count": _limit(source), "maxlength": 0,
        "feeds": STEAM_OFFICIAL_FEED,
    })
    payload = response.json().get("appnews")
    if not isinstance(payload, dict) or payload.get("appid") != appid:
        raise SourceFailure("error", "Steam 响应缺少匹配的 appnews/AppID")
    entries = payload.get("newsitems")
    if not isinstance(entries, list):
        raise SourceFailure("error", "Steam 响应缺少 newsitems 数组")
    rows, excluded, dates = [], {}, []
    for entry in entries:
        if not isinstance(entry, dict):
            excluded["invalid"] = excluded.get("invalid", 0) + 1
            continue
        # is_external_url can be true even for Steam's own Akamai announcement links.
        # Publisher feedname + matching AppID provide the source boundary, not this flag.
        if (entry.get("feedname") != STEAM_OFFICIAL_FEED
                or entry.get("appid", appid) != appid):
            excluded["source"] = excluded.get("source", 0) + 1
            continue
        stamp = _date(entry.get("date"))
        url, title = entry.get("url") or "", entry.get("title") or ""
        if not title or urlparse(url).scheme not in ("https", "http"):
            excluded["invalid"] = excluded.get("invalid", 0) + 1
            continue
        dates.append(stamp)
        reason = _date_exclusion(stamp, source, now)
        if reason:
            excluded[reason] = excluded.get(reason, 0) + 1
            continue
        content = entry.get("contents") or ""
        row = _article(source, title, url, stamp, content=content, kind="api_content",
                       author=entry.get("author"))
        row["appid"] = appid
        row["announcement_id"] = entry.get("gid")
        rows.append(row)
    rows = rows[:_limit(source)]
    partial = bool(excluded.get("invalid"))
    if partial and diagnostics is not None:
        diagnostics["state"] = "degraded"
    return rows, _read_detail(len(entries), rows, excluded, dates, source, now, partial=partial)


class _PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta, self.documents, self.links = {}, [], []
        self.h1, self.in_h1, self.h1_done = [], False, False
        self.in_json, self.json_parts = False, []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta":
            key = attrs.get("property") or attrs.get("name") or attrs.get("itemprop")
            if key and attrs.get("content"):
                self.meta.setdefault(key.lower(), attrs["content"])
        elif tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        elif tag == "h1" and not self.h1_done:
            self.in_h1 = True
        elif tag == "script" and attrs.get("type") == "application/ld+json":
            self.in_json, self.json_parts = True, []

    def handle_data(self, data):
        if self.in_h1:
            self.h1.append(data)
        if self.in_json:
            self.json_parts.append(data)

    def handle_endtag(self, tag):
        if tag == "h1" and self.in_h1:
            self.in_h1, self.h1_done = False, True
        elif tag == "script" and self.in_json:
            self.in_json = False
            try:
                self.documents.append(json.loads("".join(self.json_parts)))
            except (ValueError, TypeError):
                pass


def _article_nodes(value):
    if isinstance(value, list):
        for node in value:
            yield from _article_nodes(node)
    elif isinstance(value, dict):
        kind = value.get("@type", "")
        kinds = kind if isinstance(kind, list) else [kind]
        if any(k in ("Article", "NewsArticle", "BlogPosting") for k in kinds):
            yield value
        if value.get("@graph"):
            yield from _article_nodes(value["@graph"])


def _page_info(raw, *, factorio=False):
    parser = _PageParser()
    parser.feed(raw)
    nodes = list(_article_nodes(parser.documents))
    node = nodes[0] if nodes else {}
    stamp_raw = parser.meta.get("article:published_time") or node.get("datePublished")
    precision = "timestamp"
    # Riot's older corporate pages print a full date in the article header but no
    # publication JSON-LD. Restrict this fallback to that header, not related cards.
    if not stamp_raw:
        header = re.search(r'<ul[^>]*class=["\'][^"\']*article-header__detail-list[^"\']*["\'][^>]*>(.*?)</ul>',
                           raw, re.S | re.I)
        if header:
            date_match = re.search(r"\b[A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}\b", _text(header.group(1)))
            header_date = date_match.group(0) if date_match else None
            if header_date and _date(header_date):
                stamp_raw, precision = header_date, "date"
    if not stamp_raw and factorio:
        match = re.search(r"Posted by[\s\S]{0,1200}?\bon\s+(\d{4}-\d{2}-\d{2})", raw)
        if match:
            stamp_raw, precision = match.group(1), "date"
    author = node.get("author")
    if isinstance(author, list):
        author = ", ".join(a.get("name", "") for a in author if isinstance(a, dict))
    elif isinstance(author, dict):
        author = author.get("name")
    title = " ".join(parser.h1) or node.get("headline") or parser.meta.get("og:title") or ""
    summary = parser.meta.get("description") or parser.meta.get("og:description") or node.get("description") or ""
    return {"title": _text(title), "published": _date(stamp_raw), "precision": precision,
            "summary": summary, "author": author}, parser.links


def _html(response):
    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding or "utf-8"
    return response.text


def _rss(source, now, *, diagnostics=None):
    response = _get(source["url"])
    feed = feedparser.parse(response.content)
    if not feed.version and not feed.entries:
        raise SourceFailure("error", "HTTP 成功但不是可识别的 RSS/Atom；不能视作没有新稿")
    rows, excluded, dates, date_failures = [], {}, [], 0
    entries = feed.entries[:_limit(source)]

    def one(entry):
        title, url = entry.get("title") or "", entry.get("link") or ""
        if not title or urlparse(url).scheme not in ("http", "https"):
            return None, False, "invalid", None
        if (source.get("include_url_pattern")
                and not re.search(source["include_url_pattern"], url)):
            return None, False, "source", None
        stamp = _feed_date(entry)
        precision = "timestamp"
        failed = False
        if stamp is None and source.get("article_date_fallback") == "factorio_posted":
            try:
                info, _ = _page_info(_html(_get(url)), factorio=True)
                stamp, precision = info["published"], info["precision"]
                failed = stamp is None
            except SourceFailure:
                failed = True
        reason = _date_exclusion(stamp, source, now)
        if reason:
            return None, failed, reason, stamp
        content = "\n".join(c.get("value") or "" for c in entry.get("content", []) if isinstance(c, dict))
        row = _article(source, title, url, stamp, entry.get("summary") or content,
                       content=content, kind="rss_content" if content else "rss_summary",
                       author=entry.get("author"), precision=precision)
        updated = _feed_date(entry, "updated")
        if updated:
            row["updated"] = updated.isoformat()
        return row, failed, None, stamp

    with futures.ThreadPoolExecutor(4) as executor:
        for row, failed, reason, stamp in executor.map(one, entries):
            date_failures += int(failed)
            dates.append(stamp)
            if row:
                rows.append(row)
            elif reason:
                excluded[reason] = excluded.get(reason, 0) + 1
    partial = bool(date_failures or excluded.get("invalid"))
    if partial and diagnostics is not None:
        diagnostics["state"] = "degraded"
    detail = _read_detail(len(entries), rows, excluded, dates, source, now, partial=partial)
    if date_failures:
        detail += f"；{date_failures} 条详情日期读取失败，未知日期保持 null"
    return rows, detail


def _official_listing(source, now, *, diagnostics=None):
    raw = _html(_get(source["url"]))
    parser = _PageParser()
    parser.feed(raw)
    own_host = urlparse(source["url"]).netloc.removeprefix("www.")
    urls, seen = [], set()
    for href in parser.links:
        parsed = urlparse(urljoin(source["url"], href))
        if (parsed.scheme not in ("http", "https")
                or parsed.netloc.removeprefix("www.") != own_host
                or not re.fullmatch(source["link_pattern"], parsed.path)):
            continue
        url = parsed._replace(query="", fragment="").geturl()
        if url not in seen:
            seen.add(url)
            urls.append(url)
    if not urls:
        raise SourceFailure("error", "公开列表未识别出文章链接，可能结构变化；不能视作没有新稿")

    def one(url):
        try:
            info, _ = _page_info(_html(_get(url)))
            if not info["title"]:
                return None, None, "invalid", None
            reason = _date_exclusion(info["published"], source, now)
            if reason:
                return None, None, reason, info["published"]
            return _article(source, info["title"], url, info["published"], info["summary"],
                            kind="page_excerpt", author=info["author"],
                            precision=info["precision"]), None, None, info["published"]
        except SourceFailure as exc:
            return None, exc, None, None

    rows, failures, excluded, dates, examined = [], [], {}, [], urls[:_limit(source)]
    with futures.ThreadPoolExecutor(4) as executor:
        for row, failure, reason, stamp in executor.map(one, examined):
            dates.append(stamp)
            if row:
                rows.append(row)
            if failure:
                failures.append(failure)
            if reason:
                excluded[reason] = excluded.get(reason, 0) + 1
    if not rows and failures:
        raise SourceFailure(failures[0].state,
                            f"详情读取失败 {len(failures)}/{len(examined)}；{failures[0].detail}")
    partial = bool(failures or excluded.get("invalid"))
    if partial and diagnostics is not None:
        diagnostics["state"] = "degraded"
    detail = _read_detail(len(examined), rows, excluded, dates, source, now, partial=partial)
    if failures:
        detail += f"；{len(failures)} 篇详情读取失败"
    return rows, detail


def _run(source, now):
    if source.get("adapter") == "manual" or source.get("enabled") is False:
        return [], _status(source, "manual", 0, source.get("notes", "仅供人工收录"))
    adapters = {"steam_announcements": _steam, "rss": _rss, "official_listing": _official_listing}
    adapter = adapters.get(source.get("adapter"))
    if adapter is None:
        return [], _status(source, "error", 0, "未知采集适配器")
    try:
        diagnostics = {}
        rows, detail = adapter(source, now, diagnostics=diagnostics)
        state = diagnostics.get("state") or ("ok" if rows else "empty")
        return rows, _status(source, state, len(rows), detail)
    except SourceFailure as exc:
        return [], _status(source, exc.state, 0, exc.detail)
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        return [], _status(source, "error", 0, f"数据格式错误：{type(exc).__name__}")
    except Exception as exc:
        return [], _status(source, "error", 0, f"采集异常：{type(exc).__name__}")


def fetch_sources(now=None):
    """Return (raw articles, per-source statuses), isolating every source failure."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    try:
        catalog = load_catalog()
    except (OSError, ValueError) as exc:
        source = {"id": "public-catalog", "name": "公开来源目录", "platform": "developer_blog",
                  "url": ""}
        return [], [_status(source, "error", 0, f"目录读取失败：{type(exc).__name__}")]
    articles, by_id = [], {}
    with futures.ThreadPoolExecutor(6) as executor:
        pending = [executor.submit(_run, source, now) for source in catalog]
        for future in futures.as_completed(pending):
            rows, status = future.result()
            articles.extend(rows)
            by_id[status["id"]] = status
    articles.sort(key=lambda row: row.get("published") or "", reverse=True)
    statuses = [by_id[source["id"]] for source in catalog]
    return articles, statuses
