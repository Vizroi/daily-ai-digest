"""公开作者、视频与会员日志候选；平台访问限制不会触发登录或验证绕过。

视频 metadata 始终 discovery_only，不将简介当成字幕或视频全文。
作者旧文/无日期页面保留真实日期边界，社区日志始终等待编辑审核。
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET

import requests

CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "creator_sources.json"
UA = "Mozilla/5.0 (compatible; GameDesignDaily/3.0; +https://github.com/Vizroi/daily-ai-digest)"
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015", "m": "http://search.yahoo.com/mrss/"}


class SourceError(Exception):
    def __init__(self, state, detail):
        super().__init__(detail)
        self.state, self.detail = state, detail


def _get(url):
    try:
        response = requests.get(url, timeout=(8, 20), headers={"User-Agent": UA})
    except requests.RequestException as exc:
        raise SourceError("error", f"公开入口请求失败：{type(exc).__name__}") from exc
    if response.status_code in (403, 412, 429):
        raise SourceError("blocked", f"平台访问限制（HTTP {response.status_code}）；未尝试绕过验证")
    if response.status_code == 401:
        raise SourceError("needs_auth", "公开入口要求登录（HTTP 401）")
    if response.status_code >= 400:
        raise SourceError("error", f"公开入口返回 HTTP {response.status_code}")
    if len(response.content) > 8_000_000:
        raise SourceError("error", "公开页面超过读取大小上限")
    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding or "utf-8"
    return response.text


def _clean(value):
    value = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", value or "", flags=re.S | re.I)
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def _date(value):
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except ValueError:
        return None


def _in_window(published, src, now):
    return published is None or now - timedelta(hours=src.get("window_hours", 720)) <= published <= now


def _record(src, title, url, published, now, *, summary="", body="", evidence="developer_article"):
    video = evidence == "video_metadata"
    community = evidence == "community_post"
    return {
        "title": _clean(title), "url": url, "source": src["name"], "source_url": src["url"],
        "source_id": src["id"], "platform": src["platform"], "tier": src["tier"],
        "lang": src["lang"], "category": src["category"], "pool": "main",
        "published": published.isoformat() if published else None, "undated": published is None,
        "published_precision": "second" if published else None,
        "date_kind": "published" if published else "missing", "updated": None,
        "retrieved_at": now.isoformat(), "summary_raw": _clean(summary)[:600], "rss_content": "",
        "body": body, "has_body": bool(body), "body_truncated": False,
        "content_kind": "article_body" if body else "source_excerpt",
        "evidence_kind": evidence, "requires_transcript": video, "publication_scope": "public",
        "discovery_only": video, "requires_review": community or bool(src.get("requires_review")),
        "classic_discovery": bool(src.get("classic_discovery")),
        "signals": {"hn_points": 0, "hn_comments": 0, "hf_upvotes": 0, "stars_today": 0, "rank_bonus": 0.0},
    }


def _walk(value, key):
    if isinstance(value, dict):
        if key in value:
            yield value[key]
        for item in value.values():
            yield from _walk(item, key)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item, key)


def _text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("content") or value.get("simpleText") or "".join(r.get("text", "") for r in value.get("runs", []))
    return ""


def _youtube_html(raw, src, now):
    match = re.search(r"(?:var\s+)?ytInitialData\s*=\s*", raw)
    if not match:
        raise SourceError("error", "公开视频页未返回可识别的视频列表")
    try:
        data = json.JSONDecoder().raw_decode(raw[match.end():])[0]
    except (ValueError, json.JSONDecodeError) as exc:
        raise SourceError("error", "公开视频列表格式发生变化") from exc
    selected = [tab.get("content") for tab in _walk(data.get("contents", {}), "tabRenderer") if tab.get("selected")]
    if not selected:
        raise SourceError("error", "公开视频页没有选中的内容标签")
    candidates = []
    for tree in selected:
        for video in _walk(tree, "videoRenderer"):
            candidates.append((video.get("videoId"), _text(video.get("title")), _text(video.get("publishedTimeText"))))
        for video in _walk(tree, "lockupViewModel"):
            if video.get("contentType") != "LOCKUP_CONTENT_TYPE_VIDEO":
                continue
            meta = video.get("metadata", {}).get("lockupMetadataViewModel", {})
            parts = [part.get("accessibilityLabel") or _text(part.get("text"))
                     for group in _walk(meta.get("metadata", {}), "metadataParts") for part in group]
            relative = next((part for part in parts if re.search(r"ago|前", part)), "")
            candidates.append((video.get("contentId"), _text(meta.get("title")), relative))
    out, seen = [], set()
    for video_id, title, relative in candidates:
        if not re.fullmatch(r"[\w-]{11}", video_id or "") or not title or video_id in seen:
            continue
        seen.add(video_id)
        item = _record(src, title, f"https://www.youtube.com/watch?v={video_id}", None, now, evidence="video_metadata")
        item["published_text"] = relative  # Rounded relative dates are not exact publication dates.
        item["collection_method"] = "channel_page"
        out.append(item)
        if len(out) >= src["max_per_source"]:
            break
    return out


def _youtube(src, now):
    try:
        raw = _get(src["feed_url"])
        root = ET.fromstring(raw)
        if root.tag != "{" + NS["a"] + "}feed":
            raise SourceError("error", "官方 Atom 未返回有效订阅内容")
    except SourceError as exc:
        if exc.state in ("blocked", "needs_auth"):
            raise
        reason = exc.detail
    except ET.ParseError:
        reason = "官方 Atom 未返回有效 XML"
    else:
        # YouTube's official Atom channelId can omit the UC prefix even though
        # the author/alternate channel URL uses the canonical prefixed ID.
        # Check identity outside the fallback handler: a different channel is
        # not a temporary feed outage and must never be silently accepted.
        declared = root.findtext("yt:channelId", namespaces=NS)
        expected = src["channel_id"]
        allowed_ids = {expected, expected[2:]} if expected.startswith("UC") else {expected}
        if declared and declared not in allowed_ids:
            raise SourceError("error", "频道标识与已核验的官方频道不符")
        identity_urls = [root.findtext("a:author/a:uri", default="", namespaces=NS)]
        identity_urls.extend(link.get("href", "") for link in root.findall("a:link", NS)
                             if link.get("rel") == "alternate")
        for url in identity_urls:
            parsed = urlparse(url)
            if parsed.hostname in ("youtube.com", "www.youtube.com") and parsed.path.startswith("/channel/"):
                if parsed.path.rstrip("/").split("/")[-1] != expected:
                    raise SourceError("error", "频道链接与已核验的官方频道不符")
        out = []
        for entry in root.findall("a:entry", NS):
            video_id = entry.findtext("yt:videoId", namespaces=NS)
            title = entry.findtext("a:title", default="", namespaces=NS)
            published_raw = entry.findtext("a:published", namespaces=NS)
            published = _date(published_raw)
            if not video_id or not title or not _in_window(published, src, now):
                continue
            summary = entry.findtext("m:group/m:description", default="", namespaces=NS)
            item = _record(src, title, f"https://www.youtube.com/watch?v={video_id}", published, now, summary=summary, evidence="video_metadata")
            item["collection_method"] = "official_atom"
            if published and re.fullmatch(r"\d{4}-\d{2}-\d{2}", published_raw or ""):
                item["published_precision"] = "day"
            out.append(item)
        return out[:src["max_per_source"]], "官方 Atom 元数据；未获取字幕，需观看后再编入精选"
    # Read the ordinary public channel page when its declared feed is unavailable.
    # This is never attempted after an authentication/challenge response.
    out = _youtube_html(_get(src["videos_url"]), src, now)
    if not out:
        raise SourceError("degraded", f"{reason}；公开频道页也未取得可识别的视频候选")
    return out, f"{reason}；使用公开频道页标题候选，精确发布日期未知，未获取字幕"


def _bilibili(src, now):
    raw = _get(f"https://api.bilibili.com/x/space/arc/search?mid={src['uid']}&ps={src['max_per_source']}&pn=1&order=pubdate")
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise SourceError("error", "公开接口未返回 JSON") from exc
    code = payload.get("code")
    if code in (-352, -412, -509, -403, -799):
        raise SourceError("blocked", f"平台访问限制（接口代码 {code}）；未尝试绕过验证")
    if code in (-101, -111):
        raise SourceError("needs_auth", f"接口要求登录（代码 {code}）")
    if code != 0:
        raise SourceError("error", f"公开接口返回错误（代码 {code}）")
    out = []
    for video in payload.get("data", {}).get("list", {}).get("vlist", []):
        bvid, title = video.get("bvid"), video.get("title")
        if not bvid or not title:
            continue
        try:
            published = datetime.fromtimestamp(float(video["created"]), timezone.utc)
        except (KeyError, ValueError, TypeError, OverflowError, OSError):
            published = None
        if not _in_window(published, src, now):
            continue
        out.append(_record(src, title, f"https://www.bilibili.com/video/{bvid}", published, now,
                           summary=video.get("description", ""), evidence="video_metadata"))
    return out[:src["max_per_source"]], "公开接口的视频元数据；未获取字幕，需观看后再编入精选"


def _tencent_news(src, now):
    """Read the publisher's public, dated news cards, not its video platform."""
    raw = _get(src["url"])
    out, seen, recognized, latest = [], set(), 0, None
    for match in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', raw, re.S | re.I):
        url = urljoin(src["url"], unescape(match.group(1)))
        parsed = urlparse(url)
        if parsed.hostname != "gameinstitute.qq.com" or not re.fullmatch(r"/news/detail/\d+", parsed.path):
            continue
        card = match.group(2)
        title = re.search(r'<h3\b[^>]*class=["\'][^"\']*\bm-thumbnail2__title\b[^"\']*["\'][^>]*>(.*?)</h3>', card, re.S | re.I)
        date = re.search(r'<span\b[^>]*class=["\'][^"\']*\bdata__text\b[^"\']*["\'][^>]*>\s*(\d{4}\.\d{2}\.\d{2})\s*</span>', card, re.S | re.I)
        if not title or not date:
            continue
        published = _date(date.group(1).replace(".", "-") + "T00:00:00+08:00")
        if published is None:
            continue
        recognized += 1
        if published <= now:
            latest = max(latest, published) if latest else published
        if url in seen or not _in_window(published, src, now):
            continue
        seen.add(url)
        summary = re.search(r'<p\b[^>]*class=["\'][^"\']*\bm-thumbnail2__desc\b[^"\']*["\'][^>]*>(.*?)</p>', card, re.S | re.I)
        item = _record(src, title.group(1), url, published, now, summary=summary.group(1) if summary else "")
        item["published_precision"] = "day"
        item["published_text"] = date.group(1)
        item["collection_method"] = "official_news_listing"
        out.append(item)
    if not recognized:
        raise SourceError("error", "官网资讯列表未找到可核验的标题与发布日期，需检查页面结构")
    out.sort(key=lambda item: item["published"], reverse=True)
    detail = "官网资讯列表的标题、发布日期与摘要；正文待后续读取，进入日报前需编辑审核"
    if latest:
        detail += f"；列表最新日期 {latest.astimezone(timezone(timedelta(hours=8))).date()}"
    return out[:src["max_per_source"]], detail


def _markdown_body(raw):
    raw = re.sub(r"^> For the complete documentation index,.*\n?", "", raw, flags=re.M)
    raw = re.sub(r"!\[[^\]]*\]\([^\n]*?\)", "", raw)
    raw = re.sub(r"\[([^\]]+)\]\([^\n]*?\)", r"\1", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    return raw.strip()


def _author(src, now):
    index = _get(src["listing_url"])
    pairs = re.findall(r"\[([^\]]+)\]\((https://docs\.xpaidia\.com/[^\s)]+\.md)\)", index)
    paths = src.get("article_prefixes", ["/ficstruction/undo/", "/ficstruction/paidia/", "/translate/"])
    out, seen, errors = [], set(), []
    for listed_title, url in pairs:
        if url in seen or not any(urlparse(url).path.startswith(prefix) for prefix in paths):
            continue
        seen.add(url)
        try:
            raw = _get(url)
        except SourceError as exc:
            errors.append(exc)
            continue
        title_match = re.search(r"^#\s+(.+)$", raw, re.M)
        body = _markdown_body(raw)
        if len(body) < 400:
            continue
        # An essay's mentioned/written month and GitBook modification time are not its publication date.
        item = _record(src, title_match.group(1).strip() if title_match else listed_title,
                       url[:-3], None, now, summary=body, body=body)
        item["body_source_url"] = url
        out.append(item)
        if len(out) >= src["max_per_source"]:
            break
    if not out and errors:
        raise errors[0]
    detail = "作者公开 Markdown 正文；原始发布日期未核验，作为经典阅读候选"
    if errors:
        detail += f"；另有 {len(errors)} 篇暂不可读取"
    return out, detail


class _Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.meta, self.title, self._h1 = [], {}, [], False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if tag == "meta":
            self.meta[attrs.get("property") or attrs.get("name")] = attrs.get("content", "")
        if tag == "h1":
            self._h1 = True

    def handle_endtag(self, tag):
        if tag == "h1":
            self._h1 = False

    def handle_data(self, text):
        if self._h1:
            self.title.append(text)


def _community(src, now):
    listing = _Page()
    listing.feed(_get(src["url"]))
    links = list(dict.fromkeys(urljoin(src["url"], link) for link in listing.links
                              if re.fullmatch(r"/u/[^/]+/blogread/\d+/?", urlparse(link).path)))
    out, errors = [], []
    for url in links[:src["max_per_source"] * 2]:
        try:
            raw = _get(url)
        except SourceError as exc:
            errors.append(exc)
            if exc.state in ("blocked", "needs_auth"):
                break
            continue
        page = _Page()
        page.feed(raw)
        page_title = re.search(r"<title[^>]*>(.*?)</title>", raw, re.S | re.I)
        # Member logs use h1 for the comment form, not the article heading.
        title = _clean(page.meta.get("og:title", "")) or (_clean(page_title.group(1)).split(" | indienova")[0] if page_title else "") or _clean(" ".join(page.title))
        published_raw = page.meta.get("article:published_time") or page.meta.get("datePublished")
        published = _date(published_raw)
        calendar = re.search(r'<i\b[^>]*class="icon-calendar-empty"[^>]*></i>(.*?)</li>', raw, re.S | re.I)
        published_text = _clean(calendar.group(1)) if calendar else ""
        if not published and re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?", published_text):
            published = _date(published_text + "+08:00" if " " in published_text else published_text + "T00:00:00+08:00")
            published_raw = published_text
        if not title or not _in_window(published, src, now):
            continue
        article = re.search(r"<article\b[^>]*>(.*?)</article>", raw, re.S | re.I)
        body = _clean(article.group(1)) if article else ""
        excerpt = body[:600]
        if len(body) < 400:
            body = ""
        item = _record(src, title, url, published, now,
                       summary=excerpt, body=body, evidence="community_post")
        item["published_text"] = published_text
        if published and re.fullmatch(r"\d{4}-\d{2}-\d{2}", published_raw or ""):
            item["published_precision"] = "day"
        out.append(item)
        if len(out) >= src["max_per_source"]:
            break
    if not out and errors:
        raise errors[0]
    detail = "公开会员日志候选；作者身份、经验与论证需编辑审核"
    if errors:
        detail += f"；部分详情页受限（{errors[0].detail}）"
    return out, detail


def _fetch_one(src, now):
    status = {k: src[k] for k in ("id", "name", "platform", "url")}
    if src.get("adapter") == "manual":
        return [], dict(status, state="manual", count=0, detail=src.get("manual_reason", "接受人工单篇链接投递"))
    try:
        adapter = {"youtube": _youtube, "bilibili": _bilibili, "tencent_news": _tencent_news,
                   "xpaidia": _author, "indienova_members": _community}[src["adapter"]]
        articles, detail = adapter(src, now)
        state = "ok" if articles else "empty"
        if any(item.get("collection_method") == "channel_page" for item in articles):
            state = "degraded"
        return articles, dict(status, state=state, count=len(articles), detail=detail)
    except SourceError as exc:
        return [], dict(status, state=exc.state, count=0, detail=exc.detail)
    except Exception as exc:
        return [], dict(status, state="error", count=0, detail=f"来源解析失败：{type(exc).__name__}")


def fetch_sources(now=None):
    """Return public candidate articles and one honest status per catalog source."""
    now = now or datetime.now(timezone.utc)
    now = (now if now.tzinfo else now.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    articles, statuses = [], []
    with ThreadPoolExecutor(max_workers=4) as executor:
        for items, status in executor.map(lambda src: _fetch_one(src, now), catalog):
            articles.extend(items)
            statuses.append(status)
    return articles, statuses
