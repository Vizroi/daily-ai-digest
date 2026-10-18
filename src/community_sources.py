"""Read approved Reddit API access and explicitly allowed Discord bot channels.

No anonymous fallbacks, user cookies, personal-token discovery, joins or writes.
All results are discovery evidence in pool='community', never official body text.

Configuration:
  REDDIT_ACCESS_TOKEN: an already approved OAuth access token (no token refresh).
  REDDIT_USER_AGENT: optionally identify the approved app/contact accurately.
  DISCORD_BOT_TOKEN: bot token granted by the server administrator.
  DISCORD_CHANNELS_JSON: explicit allowlist, either a mapping such as
    {"discord_unity": ["123456789012345678"]}
  or a list of {"source_id":"discord_unity", "channel_id":"123456789012345678"}.
  Mapping values also accept objects. If this env is set it replaces catalog
  channel IDs, so an omitted source is never queried implicitly. Without it,
  source.channel_id or source.channel_ids may explicitly identify channels.

Discord defaults to publication_scope='restricted'. Public publication requires
both publication_scope='public' and public_publication_authorized=true in an
explicit channel/source configuration; requires_review stays true either way.
Permission to read is not permission to harvest or republish a server wholesale.

API requirements checked against:
https://support.reddithelp.com/hc/en-us/articles/42728983564564
https://support.reddithelp.com/hc/en-us/articles/16160319875092
https://docs.discord.com/developers/resources/message#get-channel-messages
https://support-dev.discord.com/hc/en-us/articles/6207308062871
"""
import html
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "community_sources.json"
REDDIT_API = "https://oauth.reddit.com"
DISCORD_API = "https://discord.com/api/v10"
USER_AGENT = "python:daily-ai-digest:3.0 (+https://github.com/Vizroi/daily-ai-digest; read-only community discovery)"
SNOWFLAKE = re.compile(r"^[0-9]{15,22}$")
MAX_TEXT = 12000


class _APIError(Exception):
    def __init__(self, state: str, detail: str, http_status: int | None = None):
        super().__init__(detail)
        self.state, self.detail, self.http_status = state, detail, http_status


def load_catalog() -> list[dict]:
    with CATALOG_PATH.open(encoding="utf-8") as handle:
        sources = json.load(handle)
    if not isinstance(sources, list) or any(not isinstance(source, dict) for source in sources):
        raise ValueError("community_sources.json must contain a list of source objects")
    ids = [source.get("id") for source in sources]
    if not all(isinstance(key, str) and key for key in ids) or len(ids) != len(set(ids)):
        raise ValueError("community source IDs must be non-empty and unique")
    return sources


def _status(source: dict, state: str, count: int, detail: str, **extra) -> dict:
    return {"id": source["id"], "name": source.get("name", source["id"]),
            "platform": source.get("platform", "community"), "url": source.get("url", ""),
            "state": state, "count": count, "detail": detail, **extra}


def _api_get(url: str, headers: dict, params: dict | None = None):
    try:
        response = requests.get(url, headers=headers, params=params, timeout=15, allow_redirects=False)
    except requests.RequestException:
        raise _APIError("error", "网络请求失败或超时；未重试。") from None
    code = response.status_code
    if code in (401, 403):
        raise _APIError("needs_auth", f"HTTP {code}：凭据无效、未获批准或无权读取指定内容；未尝试绕过。", code)
    if code == 429:
        retry = str(response.headers.get("Retry-After", ""))
        retry = retry if re.fullmatch(r"[0-9.]{1,16}", retry) else "未提供"
        raise _APIError("error", f"HTTP 429：触发限流，本轮停止该平台后续请求；Retry-After={retry}。", code)
    if code != 200:
        raise _APIError("error", f"HTTP {code}：API未返回成功结果；未跟随重定向或重试。", code)
    try:
        return response.json()
    except (ValueError, requests.RequestException):
        raise _APIError("error", "API返回的内容不是有效JSON。", code) from None


def _web_url(value) -> str:
    value = str(value or "").strip()
    try:
        parsed = urlparse(value)
        return value if parsed.scheme in ("http", "https") and parsed.netloc else ""
    except ValueError:
        return ""


def _clean(value, limit: int = MAX_TEXT) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<(https?://[^>\s]+)>", r"\1", text)
    text = re.sub(r"<@!?[0-9]+>", "@成员", text)
    text = re.sub(r"<@&[0-9]+>", "@角色", text)
    text = re.sub(r"<#[0-9]+>", "#频道", text)
    text = re.sub(r"<script\b[^>]*>.*?</script>", "", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return text.strip()[:limit]


def _published(value) -> datetime | None:
    try:
        parsed = (datetime.fromtimestamp(float(value), timezone.utc) if isinstance(value, (int, float))
                  else datetime.fromisoformat(str(value).replace("Z", "+00:00")))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _bounded_int(value, default: int, maximum: int) -> int:
    try:
        return max(1, min(int(value), maximum))
    except (TypeError, ValueError):
        return default


def _recent(published: datetime | None, source: dict, now: datetime) -> bool:
    window = _bounded_int(source.get("window_hours"), 72, 24 * 90)
    return published is None or now - timedelta(hours=window) <= published <= now + timedelta(minutes=5)


def _question(title: str, flair: str = "") -> bool:
    hint = (title + " " + flair).lower()
    return bool("?" in title or "？" in title
                or re.search(r"\b(question|help|feedback request|resource request)\b", hint)
                or re.match(r"(?:how|why|what|should|can|could|which|does|do|is|are)\b", title.lower())
                or any(word in hint for word in ("求助", "请问", "怎么", "如何")))


def _record(source: dict, title: str, discovery: str, published: datetime | None, text: str,
            *, evidence_kind: str, original_url: str = "", flair: str = "", scope: str = "restricted") -> dict:
    article = {"title": title, "url": discovery, "source": source.get("name", source["id"]),
               "source_id": source["id"], "platform": source["platform"], "tier": source.get("tier", 3),
               "lang": source.get("lang", "en"), "category": source.get("category", "design"),
               "published": published.isoformat() if published else None, "published_precision": "second" if published else None,
               "undated": published is None, "summary_raw": re.sub(r"\s+", " ", text)[:600],
               "rss_content": text, "content_kind": "community_text" if text else "community_link",
               "signals": {"hn_points": 0, "hn_comments": 0, "hf_upvotes": 0, "stars_today": 0, "rank_bonus": 0.0},
               "pool": "community", "evidence_kind": evidence_kind, "discovery_url": discovery,
               "community_flair": flair, "is_question": _question(title, flair),
               "publication_scope": scope, "requires_review": True, "has_body": False}
    if original_url:
        article["original_url"] = original_url
    return article


def parse_reddit_listing(payload, source: dict, now: datetime) -> list[dict]:
    """Keep community text distinct from the body of any external article."""
    if (not isinstance(payload, dict) or not isinstance(payload.get("data"), dict)
            or not isinstance(payload["data"].get("children"), list)):
        raise _APIError("error", "Reddit响应缺少Listing数据。")
    out, seen = [], set()
    maximum = _bounded_int(source.get("max_per_source"), 20, 100)
    for child in payload["data"]["children"]:
        if not isinstance(child, dict) or child.get("kind") != "t3" or not isinstance(child.get("data"), dict):
            continue
        post = child["data"]
        selftext = str(post.get("selftext") or "")
        if post.get("removed_by_category") or selftext.strip().lower() in ("[removed]", "[deleted]") or post.get("over_18"):
            continue
        published = _published(post.get("created_utc"))
        if not _recent(published, source, now):
            continue
        title = _clean(post.get("title"), 300)
        permalink = str(post.get("permalink") or "")
        # Restrict community links to the selected public subreddit, never user input hosts.
        subreddit = str(source.get("subreddit") or "")
        if not title or not permalink.startswith(f"/r/{subreddit}/comments/"):
            continue
        discovery = "https://www.reddit.com" + permalink
        if discovery in seen:
            continue
        seen.add(discovery)
        external = _web_url(post.get("url_overridden_by_dest") or post.get("url"))
        if external and (urlparse(external).hostname or "").lower() in ("reddit.com", "www.reddit.com", "old.reddit.com", "redd.it"):
            external = ""
        flair = _clean(post.get("link_flair_text"), 120)
        item = _record(source, title, discovery, published, _clean(selftext),
                       evidence_kind="community_link" if external and not post.get("is_self") else "community_post",
                       original_url=external, flair=flair, scope="public" if source.get("publication_scope") == "public" else "restricted")
        item["content_kind"] = "community_selftext" if selftext else "community_link"
        # Attention is metadata, never a claim of reliability or an official-source bonus.
        item["signals"]["reddit_score"] = post.get("score", 0) if isinstance(post.get("score"), (int, float)) else 0
        item["signals"]["reddit_comments"] = post.get("num_comments", 0) if isinstance(post.get("num_comments"), int) else 0
        out.append(item)
        if len(out) >= maximum:
            break
    return out


def _reddit(source: dict, now: datetime, token: str) -> list[dict]:
    subreddit = str(source.get("subreddit") or "")
    if not re.fullmatch(r"[A-Za-z0-9_]{2,30}", subreddit):
        raise _APIError("error", "来源配置中的subreddit无效。")
    headers = {"Authorization": "Bearer " + token,
               "User-Agent": os.environ.get("REDDIT_USER_AGENT") or USER_AGENT, "Accept": "application/json"}
    maximum = _bounded_int(source.get("max_per_source"), 20, 100)
    return parse_reddit_listing(_api_get(f"{REDDIT_API}/r/{subreddit}/new", headers,
                                         {"limit": maximum, "raw_json": 1}), source, now)


def _allowlist(raw: str | None) -> dict[str, list[dict]] | None:
    if raw is None:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        raise _APIError("error", "DISCORD_CHANNELS_JSON不是有效JSON；未读取任何Discord频道。") from None
    result = {}
    if isinstance(payload, dict):
        entries = []
        for source_id, values in payload.items():
            for value in values if isinstance(values, list) else [values]:
                entries.append(dict(value, source_id=source_id) if isinstance(value, dict)
                               else {"source_id": source_id, "channel_id": value})
    elif isinstance(payload, list) and all(isinstance(entry, dict) and entry.get("source_id") for entry in payload):
        entries = payload
    else:
        raise _APIError("error", "Discord allowlist须为source_id映射或带source_id的频道对象列表。")
    for entry in entries:
        source_id, channel_id = str(entry.get("source_id") or ""), str(entry.get("channel_id") or "")
        if not source_id or not SNOWFLAKE.fullmatch(channel_id):
            raise _APIError("error", "Discord allowlist含无效source_id或频道ID；未读取任何Discord频道。")
        result.setdefault(source_id, []).append(dict(entry, channel_id=channel_id))
    return result


def _channels(source: dict, allowed: dict[str, list[dict]] | None) -> list[dict]:
    if allowed is not None:
        entries = allowed.get(source["id"], [])
    else:
        values = source.get("channel_ids") or ([source["channel_id"]] if source.get("channel_id") else [])
        entries = [dict(value) if isinstance(value, dict) else {"channel_id": value} for value in values]
    result, seen = [], set()
    for entry in entries:
        channel_id = str(entry.get("channel_id") or "")
        if not SNOWFLAKE.fullmatch(channel_id):
            raise _APIError("error", "指定Discord频道ID无效；未读取该来源。")
        if channel_id not in seen:
            result.append(dict(entry, channel_id=channel_id))
            seen.add(channel_id)
    return result


def _public_scope(source: dict, channel: dict) -> str:
    scope = channel.get("publication_scope", source.get("publication_scope", "restricted"))
    approved = channel.get("public_publication_authorized", source.get("public_publication_authorized", False))
    return "public" if scope == "public" and approved is True else "restricted"


def parse_discord_messages(payload, source: dict, channel: dict, guild_id: str, now: datetime) -> list[dict]:
    if not isinstance(payload, list):
        raise _APIError("error", "Discord消息响应不是列表。")
    out, blank, candidates, seen = [], 0, 0, set()
    for message in payload:
        if not isinstance(message, dict) or message.get("type", 0) not in (0, 19):
            continue
        published = _published(message.get("timestamp"))
        if not _recent(published, source, now):
            continue
        message_id = str(message.get("id") or "")
        if not SNOWFLAKE.fullmatch(message_id) or message_id in seen:
            continue
        if message.get("channel_id") and str(message["channel_id"]) != channel["channel_id"]:
            continue
        seen.add(message_id)
        candidates += 1
        content = _clean(message.get("content"))
        embeds = message.get("embeds") or []
        embed_text = [part for embed in embeds if isinstance(embed, dict)
                      for part in (_clean(embed.get("title"), 300), _clean(embed.get("description"))) if part]
        text = "\n\n".join([content] + embed_text).strip()[:MAX_TEXT]
        if not text:
            if not message.get("attachments") and not message.get("poll"):
                blank += 1
            continue
        title = next((_clean(embed.get("title"), 300) for embed in embeds
                      if isinstance(embed, dict) and _clean(embed.get("title"), 300)), "")
        title = title or re.sub(r"^[#>*\s]+", "", text.splitlines()[0])[:180]
        original = next((_web_url(embed.get("url")) for embed in embeds
                         if isinstance(embed, dict) and _web_url(embed.get("url"))), "")
        if not original:
            original = next((_web_url(match.rstrip(".,;!?)]}。，“”")) for match in re.findall(r"https?://[^\s<>]+", content)), "")
        if original and (urlparse(original).hostname or "").lower() in ("discord.com", "discord.gg", "discordapp.com"):
            original = ""
        discovery = f"https://discord.com/channels/{guild_id}/{channel['channel_id']}/{message_id}"
        item = _record(source, title, discovery, published, text,
                       evidence_kind="community_link" if original else "community_post",
                       original_url=original, scope=_public_scope(source, channel))
        item.update(channel_id=channel["channel_id"], content_kind="community_message")
        out.append(item)
    if candidates and blank == candidates:
        raise _APIError("needs_auth", "API仅返回消息外壳，未返回可读正文；请检查MESSAGE_CONTENT和频道权限。")
    return out


def _discord(source: dict, now: datetime, token: str, channels: list[dict]) -> tuple[list[dict], list[dict], int | None]:
    headers = {"Authorization": "Bot " + token, "User-Agent": USER_AGENT, "Accept": "application/json"}
    out, results, halted = [], [], None
    maximum = _bounded_int(source.get("max_per_source"), 20, 100)
    for channel in channels:
        if len(out) >= maximum or halted:
            break
        channel_id = channel["channel_id"]
        try:
            meta = _api_get(f"{DISCORD_API}/channels/{channel_id}", headers)
            if not isinstance(meta, dict) or not SNOWFLAKE.fullmatch(str(meta.get("guild_id") or "")):
                raise _APIError("needs_auth", "仅支持获准的服务器频道，不读取私信或无法确认归属的频道。")
            if str(meta.get("id")) != channel_id:
                raise _APIError("error", "API返回的频道ID与allowlist不一致，未读取消息。")
            if meta.get("type") not in (0, 5, 10, 11, 12):
                results.append({"channel_id": channel_id, "state": "manual", "count": 0,
                                "detail": "该频道不是文本频道或讨论串；论坛请明确配置具体讨论串ID。"})
                continue
            payload = _api_get(f"{DISCORD_API}/channels/{channel_id}/messages", headers, {"limit": maximum - len(out)})
            items = parse_discord_messages(payload, source, channel, str(meta["guild_id"]), now)[:maximum - len(out)]
            out.extend(items)
            results.append({"channel_id": channel_id, "state": "ok" if items else "empty", "count": len(items),
                            "detail": "仅作社区线索；发布范围及审阅标记保留。"})
        except _APIError as exc:
            results.append({"channel_id": channel_id, "state": exc.state, "count": 0,
                            "detail": exc.detail, "http_status": exc.http_status})
            if exc.http_status in (401, 429):
                halted = exc.http_status
    return out, results, halted


def fetch_sources(now: datetime | None = None) -> tuple[list[dict], list[dict]]:
    """Return bounded discovery records plus explicit status for every source."""
    now = now or datetime.now(timezone.utc)
    now = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)
    try:
        sources = load_catalog()
    except (OSError, ValueError):
        source = {"id": "community_catalog", "name": "社区来源配置", "platform": "community", "url": ""}
        return [], [_status(source, "error", 0, "无法读取有效的community_sources.json；未发起请求。")]
    reddit_token = os.environ.get("REDDIT_ACCESS_TOKEN", "").strip()
    discord_token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if discord_token.startswith("Bot "):
        discord_token = discord_token[4:].strip()
    allowed, allow_error = None, None
    try:
        allowed = _allowlist(os.environ.get("DISCORD_CHANNELS_JSON") or None)
        known = {source["id"] for source in sources if source.get("platform") == "discord"}
        if allowed is not None and set(allowed) - known:
            raise _APIError("error", "Discord allowlist含未登记的source_id；未读取任何Discord频道。")
    except _APIError as exc:
        allow_error = exc
    articles, statuses, halted = [], [], {}
    for source in sources:
        platform = source.get("platform")
        if not source.get("enabled", True):
            statuses.append(_status(source, "manual", 0, "来源已登记但未启用。"))
            continue
        if platform in halted:
            state = "needs_auth" if halted[platform] == 401 else "error"
            statuses.append(_status(source, state, 0, f"因本轮{platform} HTTP {halted[platform]}，未继续请求该平台。", http_status=halted[platform]))
            continue
        try:
            if platform == "reddit" and source.get("adapter") == "reddit_oauth":
                if not reddit_token:
                    statuses.append(_status(source, "needs_auth", 0, "缺少已获批准的REDDIT_ACCESS_TOKEN；未尝试匿名抓取。"))
                    continue
                items = _reddit(source, now, reddit_token)
                articles.extend(items)
                statuses.append(_status(source, "ok" if items else "empty", len(items), "已读取指定社区的新帖；仅作待审阅线索，热度不代表可信。"))
            elif platform == "discord" and source.get("adapter") == "discord_bot":
                if allow_error:
                    raise allow_error
                channels = _channels(source, allowed)
                if not discord_token or not channels:
                    detail = "缺少DISCORD_BOT_TOKEN。" if not discord_token else "未明确配置获准频道ID。"
                    statuses.append(_status(source, "needs_auth", 0, detail + "公开邀请链接不提供历史读取权限；未加入服务器。"))
                    continue
                items, channel_statuses, code = _discord(source, now, discord_token, channels)
                articles.extend(items)
                states = {entry["state"] for entry in channel_statuses}
                state = next((value for value in ("needs_auth", "error", "manual") if value in states), "ok" if items else "empty")
                detail = "仅读取明确指定的频道；条目待审阅，默认不对外发布。"
                if state not in ("ok", "empty"):
                    failures = [entry["detail"] for entry in channel_statuses if entry["state"] not in ("ok", "empty")]
                    detail = "部分或全部指定频道未完成读取：" + " ".join(failures)
                statuses.append(_status(source, state, len(items), detail, channels=channel_statuses))
                if code:
                    halted[platform] = code
            else:
                statuses.append(_status(source, "manual", 0, "已登记入口，尚无支持的只读适配器。"))
        except _APIError as exc:
            statuses.append(_status(source, exc.state, 0, exc.detail, http_status=exc.http_status))
            if exc.http_status in (401, 429):
                halted[platform] = exc.http_status
    return articles, statuses
