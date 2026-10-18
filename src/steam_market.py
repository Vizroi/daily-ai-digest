"""Credential-free Steam observation snapshots; no sales estimates or invented history.

Public Steam endpoints may change. Errors retain visibly stale fields, never produce a
new historical observation. UTC+08 complete calendar days need >=2 observations
spanning >=6 hours. The result is a sampling mean, not Steam's daily average/peak.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone, date
import html
import json
import math
from pathlib import Path
import re

import requests
from source_http import failure_reason, get_response

ROOT = Path(__file__).resolve().parents[1]
TZ = timezone(timedelta(hours=8))
API = "https://api.steampowered.com"
STORE = "https://store.steampowered.com"
HEADERS = {"User-Agent": "GameDesignDaily/1.0 (+https://vizroi.github.io/daily-ai-digest/)"}
MODES = {2: "单人", 1: "多人", 9: "合作", 27: "跨平台联机", 36: "在线 PvP", 37: "本地 PvP", 38: "在线合作", 39: "本地合作", 24: "本地多人"}
METADATA_KEYS = {"name", "header_image", "tags", "genres", "player_modes", "is_action", "release_date", "release_label", "coming_soon",
                 "demo_url", "is_demo", "description", "price", "metadata_at", "metadata_source", "metadata_status"}


def stamp(now):
    return now.astimezone(TZ).isoformat(timespec="seconds")


def parse_time(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(TZ)
    except (AttributeError, ValueError, TypeError):
        return None


def read_json(path, fallback):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return deepcopy(fallback)


def write_json(path, value, compact=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=None if compact else 2) + "\n", encoding="utf-8")
    tmp.replace(path)


def request_json(url, params=None):
    response = get_response(url, params=params, headers=HEADERS, timeout=(5, 12))
    response.raise_for_status()
    result = response.json()
    if not isinstance(result, dict):
        raise ValueError("unexpected response")
    return result


def service(method, payload=None):
    return request_json(f"{API}/{method}/v1/", {"input_json": json.dumps(payload or {})}).get("response", {})


def clean_text(value, limit=240):
    value = re.sub(r"<[^>]+>|\[/?[^\]]+\]", " ", str(value or ""))
    return re.sub(r"\s+", " ", html.unescape(value)).strip()[:limit]


def recent(value, now, hours=23):
    t = parse_time(value)
    return t is not None and timedelta() <= now - t < timedelta(hours=hours)


def safe_error(error):
    # Do not serialize request URLs/headers or unrelated environment details.
    if isinstance(error, requests.HTTPError):
        return f"HTTP {error.response.status_code}"
    reason = failure_reason(error)
    if reason == "tls_eof":
        return "TLS 连接提前关闭（EOF）"
    if reason == "tls_certificate":
        return "TLS 证书验证失败（未关闭验证）"
    return type(error).__name__


def parse_release(value):
    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(value, TZ).date().isoformat()
    for fmt in ("%d %b, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value), fmt).date().isoformat()
        except ValueError:
            pass
    return None


def store_asset_url(asset_format, filename):
    """Steam Store Browse uses paths relative to the store_item_assets root."""
    if not isinstance(asset_format, str) or not isinstance(filename, str) or not asset_format or not filename:
        return None
    path = asset_format.replace("${FILENAME}", filename)
    if path.startswith(("https://", "http://")):
        return path
    if path.startswith("//"):
        return "https:" + path
    path = path.lstrip("/")
    if not path.startswith("store_item_assets/"):
        path = "store_item_assets/" + path
    return "https://shared.fastly.steamstatic.com/" + path


def metadata_from_browse(item, tag_names, now, country="CN"):
    if item.get("success") != 1 or not item.get("name"):
        raise ValueError("store item unavailable")
    # type=0 game; type=1 DLC and type=3 software are not market game samples.
    if item.get("type", 0) not in (0, 2):
        raise ValueError("not a game or demo")
    release = item.get("release", {})
    release_date = parse_release(release.get("steam_release_date"))
    price = item.get("best_purchase_option", {})
    assets = item.get("assets", {})
    image = store_asset_url(assets.get("asset_url_format"), assets.get("header"))
    tags = [tag_names[str(t)] for t in item.get("tagids", []) if str(t) in tag_names]
    modes = item.get("categories", {}).get("supported_player_categoryids", [])
    demos = item.get("related_items", {}).get("demo_appid", [])
    if isinstance(demos, int):
        demos = [demos]
    return {
        "name": item["name"], "header_image": image,
        "tags": tags, "genres": [t for t in tags if t in {"Action", "RPG", "Strategy", "Simulation", "Adventure", "Casual", "Racing", "Sports"}],
        "player_modes": [MODES[m] for m in modes if m in MODES], "is_action": 19 in item.get("tagids", []),
        "release_date": release_date, "release_label": release.get("custom_release_date_message") or release_date or "待确认",
        "coming_soon": bool(release.get("is_coming_soon") or (release_date and release_date > now.date().isoformat())),
        "demo_url": f"{STORE}/app/{demos[0]}/" if demos else None,
        "is_demo": item.get("type") == 2,
        "description": clean_text(item.get("basic_info", {}).get("short_description"), 300),
        "price": {"currency": "CNY" if country == "CN" else "USD", "region": country, "final": int(price["final_price_in_cents"]) if price.get("final_price_in_cents") else None,
                  "initial": int(price["original_price_in_cents"]) if price.get("original_price_in_cents") else None,
                  "discount_percent": price.get("discount_pct", 0), "formatted": "免费游玩" if item.get("is_free") else price.get("formatted_final_price", "价格未提供")},
        "metadata_at": stamp(now), "metadata_source": "Steam Store Browse", "metadata_status": "fresh",
    }


def fetch_metadata(appids, now):
    tag_names = {}
    try:
        tag_names = {str(t["tagid"]): t["name"] for t in service("IStoreService/GetTagList", {"language": "english"}).get("tags", [])}
    except (requests.RequestException, ValueError, KeyError):
        tag_names = {"19": "Action", "122": "RPG", "9": "Strategy", "599": "Simulation", "21": "Adventure", "492": "Indie"}
    payload = {"ids": [{"appid": a} for a in appids], "context": {"language": "english", "country_code": "CN", "steam_realm": 1},
               "data_request": {"include_basic_info": True, "include_tag_count": 20, "include_assets": True, "include_release": True,
                                "include_related_items": True, "include_all_purchase_options": True}}
    output, error = {}, None
    try:
        rows = service("IStoreBrowseService/GetItems", payload).get("store_items", [])
        for row in rows:
            try:
                output[int(row["appid"])] = metadata_from_browse(row, tag_names, now)
            except (ValueError, KeyError, TypeError):
                continue
    except (requests.RequestException, ValueError) as exc:
        error = safe_error(exc)
    missing = [a for a in appids if a not in output]
    if missing and output:
        # Some games are unavailable in CN. Ask the same public service for US data;
        # label the currency/region instead of pretending the fallback is a CN price.
        payload["ids"] = [{"appid": a} for a in missing]
        payload["context"]["country_code"] = "US"
        try:
            for row in service("IStoreBrowseService/GetItems", payload).get("store_items", []):
                try:
                    output[int(row["appid"])] = metadata_from_browse(row, tag_names, now, "US")
                except (ValueError, KeyError, TypeError):
                    continue
        except (requests.RequestException, ValueError):
            pass
    # No dozens of unbounded fallback calls if the entire endpoint fails.
    return output, error


def discover(now, previous, refresh=False):
    if not refresh and recent(previous.get("updated_at"), now):
        return deepcopy(previous)
    candidates, errors = [], []
    try:
        categories = request_json(STORE + "/api/featuredcategories", {"cc": "cn", "l": "english"})
        for category in ("new_releases", "coming_soon", "top_sellers"):
            for item in categories.get(category, {}).get("items", [])[:8]:
                if item.get("type") not in (None, 0, 2):
                    continue
                candidates.append({"appid": int(item["id"]), "name": item.get("name", ""), "discovery_reason": category,
                                   "url": f"{STORE}/app/{item['id']}/", "source_url": STORE + "/explore/new/"})
    except (requests.RequestException, ValueError, KeyError) as exc:
        errors.append("Steam 商店新作入口: " + safe_error(exc))
    try:
        ranks = service("ISteamChartsService/GetMostPlayedGames").get("ranks", [])
        # Rank movement only chooses candidates; it is never substituted for our own 7d metric.
        movers = sorted(ranks, key=lambda r: (r.get("last_week_rank", -1) - r.get("rank", 999)) if r.get("last_week_rank", -1) > 0 else 100, reverse=True)
        for item in movers[:12]:
            candidates.append({"appid": int(item["appid"]), "name": "", "discovery_reason": "Steam 热门榜发现",
                               "url": f"{STORE}/app/{item['appid']}/", "source_url": STORE + "/charts/mostplayed"})
    except (requests.RequestException, ValueError, KeyError) as exc:
        errors.append("Steam 热门入口: " + safe_error(exc))
    unique = list({c["appid"]: c for c in candidates}.values())[:24]
    if not unique:
        result = deepcopy(previous) or {"items": [], "updated_at": None}
        result.update(status="stale" if result.get("items") else "unavailable", attempted_at=stamp(now), errors=errors)
        return result
    return {"status": "partial" if errors else "fresh", "updated_at": stamp(now), "attempted_at": stamp(now), "items": unique, "errors": errors}


def review_quality(raw, language):
    if (language == "schinese" and len(re.findall(r"[\u4e00-\u9fff]", raw)) < 25) or (language == "english" and len(raw.split()) < 10):
        return -1
    detail_words = r"combat|mechanic|movement|control|difficulty|story|performance|visual|music|progression|replay|price|multiplayer|match|lag|design|system|build|bug|enemy|dodge|parry|attack|camera|animation|content|variety|network|input|tutorial|战斗|操作|难度|机制|成长|剧情|内容|画面|音乐|联机|优化|帧数|卡顿|重复|价格|手感|关卡|敌人|动作|防御|攻击|引导|节奏"
    score = len(re.findall(detail_words, raw.lower()))
    return score if score or len(raw.split()) >= 40 or len(raw) >= 120 else -1


def fetch_reviews(appid, now):
    data = service("IUserReviewsService/GetAppReviews", {"appid": appid, "filter": 1, "languages": ["english", "schinese"],
                   "num_per_page": 40, "purchase_type": 1, "review_type": 0, "filter_offtopic_activity": True, "display_language": "schinese"})
    summary = data.get("query_summary")
    if not isinstance(summary, dict) or "total_reviews" not in summary:
        raise ValueError("review totals unavailable")
    total = summary["total_reviews"]
    rows = []
    for row in data.get("reviews", []):
        created = row.get("timestamp_created", 0)
        if not created or created > now.timestamp() or row.get("language") not in ("english", "schinese"):
            continue
        raw = clean_text(row.get("review"), 1000)
        language = row["language"]
        detail_score = review_quality(raw, language)
        if detail_score < 0:
            continue
        if language == "schinese":
            text, truncated = raw[:40], len(raw) > 40
        else:
            text, truncated = " ".join(raw.split()[:24]), len(raw.split()) > 24
        if truncated:
            text += "…"
        steamid = str(row.get("author", {}).get("steamid", ""))
        reviewid = str(row.get("recommendationid", ""))
        if not steamid.isdigit() or not reviewid.isdigit():
            continue
        rows.append({"language": language, "text": text, "excerpt_truncated": truncated,
                     "url": f"https://steamcommunity.com/profiles/{steamid}/recommended/{appid}/", "_detail_score": detail_score,
                     "voted_up": bool(row.get("voted_up")), "date": datetime.fromtimestamp(created, TZ).date().isoformat(), "id": reviewid})
    # Include both available languages and polarities; no fabricated translation or inferred sentiment.
    rows.sort(key=lambda r: r["_detail_score"], reverse=True)
    selected = []
    for lang in ("schinese", "english"):
        for positive in (False, True):
            row = next((r for r in rows if r["language"] == lang and r["voted_up"] == positive), None)
            if row and row not in selected:
                selected.append(row)
    selected.extend(r for r in rows if r not in selected)
    selected = [{k: v for k, v in r.items() if k != "_detail_score"} for r in selected[:4]]
    return {"total": total, "positive": summary.get("total_positive"), "negative": summary.get("total_negative"),
            "positive_percent": round(summary.get("total_positive", 0) / total * 100, 1) if total else None,
            "languages": ["english", "schinese"], "purchase_type": "all", "offtopic_filtered": True,
            "source": "IUserReviewsService/GetAppReviews", "status": "fresh", "sampled_at": stamp(now),
            "sample_size": len(data.get("reviews", [])), "sample_note": "最多40条最新中英文评论抽样，过滤过短片段并优先具体体验；不代表全部评价或主题频次。"}, selected


def fetch_events(appid, now):
    data = request_json(API + "/ISteamNews/GetNewsForApp/v2/", {"appid": appid, "count": 5, "feeds": "steam_community_announcements", "maxlength": 250})
    news = data.get("appnews", {})
    if news.get("appid") != appid:
        raise ValueError("mismatched app news")
    result = []
    for item in news.get("newsitems", []):
        created = item.get("date", 0)
        if item.get("feedname") != "steam_community_announcements" or item.get("appid") != appid or not 0 < created <= now.timestamp():
            continue
        if now.timestamp() - created > 90 * 86400:
            continue
        title = clean_text(item.get("title"), 180)
        low = title.lower()
        kind = "更新公告" if re.search(r"update|patch|hotfix|更新|补丁", low) else "官方公告"
        gid = str(item.get("gid", ""))
        url = f"{STORE}/news/app/{appid}/view/{gid}" if gid.isdigit() else f"{STORE}/news/app/{appid}"
        result.append({"title": title, "url": url, "date": datetime.fromtimestamp(created, TZ).date().isoformat(), "kind": kind,
                       "note": "事件已确认，是否导致在线变化尚未验证。"})
    return result[:3]


def collect_game(seed, old, meta, now, refresh=False):
    game = deepcopy(old) or {"appid": seed["appid"], "name": seed.get("name", str(seed["appid"])), "first_seen": stamp(now),
                              "is_action": seed.get("is_action", False), "tags": [], "genres": [], "player_modes": [], "reviews": [], "events": []}
    appid = int(seed["appid"])
    game.update(appid=appid, store_url=f"{STORE}/app/{appid}/", origin=seed.get("origin", "curated"), errors=[], attempted_at=stamp(now))
    if meta:
        game.update(meta)
    elif not recent(game.get("metadata_at"), now):
        game["metadata_status"] = "stale" if game.get("metadata_at") else "unavailable"
        game["errors"].append("商店资料未刷新")
    if seed.get("is_action"):
        game["is_action"] = True
    player_success = False
    try:
        response = request_json(API + "/ISteamUserStats/GetNumberOfCurrentPlayers/v1/", {"appid": appid}).get("response", {})
        players = response.get("player_count")
        if response.get("result") != 1 or not isinstance(players, int) or isinstance(players, bool) or players < 0:
            raise ValueError("player count unavailable")
        game.update(current_players=players, observed_at=stamp(now), players_observed_at=stamp(now), players_status="fresh")
        player_success = True
    except (requests.RequestException, ValueError) as exc:
        game["players_status"] = "stale" if game.get("current_players") is not None else "unavailable"
        game["errors"].append("在线人数: " + safe_error(exc))
    if refresh or not recent(game.get("review_summary", {}).get("sampled_at"), now, 6):
        try:
            game["review_summary"], game["reviews"] = fetch_reviews(appid, now)
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            game.setdefault("review_summary", {})["status"] = "stale" if game.get("review_summary", {}).get("sampled_at") else "unavailable"
            game["reviews"] = [r for r in game.get("reviews", []) if review_quality(r.get("text", ""), r.get("language", "")) >= 0]
            game["errors"].append("中英文评论: " + safe_error(exc))
    if refresh or not recent(game.get("events_at"), now, 6):
        try:
            game["events"] = fetch_events(appid, now)
            game.update(events_at=stamp(now), events_status="fresh")
        except (requests.RequestException, ValueError, KeyError) as exc:
            game["events_status"] = "stale" if game.get("events_at") else "unavailable"
            game["errors"].append("公告: " + safe_error(exc))
    game["status"] = ("partial" if game["errors"] else "fresh") if player_success else ("stale" if game.get("observed_at") else "unavailable")
    return game, player_success


def record_sample(history, game, now, success, retention_days=190):
    now = now.astimezone(TZ)
    apps = history.setdefault("apps", {})
    app = apps.setdefault(str(game["appid"]), {"first_seen": game["first_seen"], "days": {}})
    cutoff = (now.date() - timedelta(days=retention_days)).isoformat()
    app["days"] = {d: v for d, v in app.get("days", {}).items() if d >= cutoff}
    if not success or game.get("current_players") is None or game.get("coming_soon"):
        return
    day = app["days"].setdefault(now.date().isoformat(), {"samples": []})
    ts = int(now.timestamp())
    # Retried workflow runs in the same hour replace their own sample; no false coverage.
    samples = [s for s in day["samples"] if int(s[0]) // 3600 != ts // 3600]
    samples.append([ts, game["current_players"]])
    day["samples"] = sorted(samples)[-12:]


def valid_samples(entry, target):
    samples = []
    for s in entry.get("samples", []):
        try:
            if len(s) == 2 and not isinstance(s[1], bool) and isinstance(s[1], (int, float)) and math.isfinite(s[1]) and s[1] >= 0 and datetime.fromtimestamp(s[0], TZ).date().isoformat() == target:
                samples.append(s)
        except (TypeError, ValueError, OverflowError, OSError):
            continue
    return samples


def compare_window(days, now, size, first_seen=None, coming_soon=False, min_samples=2, min_span_hours=6):
    now = now.astimezone(TZ)
    result = {"status": "insufficient_history", "current": None, "previous": None, "absolute_change": None, "percent_change": None,
              "low_base": False, "current_days": 0, "previous_days": 0, "required_days": size, "metric": "sampled_players_mean",
              "current_start": (now.date() - timedelta(days=size)).isoformat(), "current_end": (now.date() - timedelta(days=1)).isoformat(),
              "previous_start": (now.date() - timedelta(days=2 * size)).isoformat(), "previous_end": (now.date() - timedelta(days=size + 1)).isoformat(),
              "reason": f"需两个各{size}天的完整窗口；每天至少{min_samples}次有效采样且跨度不少于{min_span_hours}小时。"}
    if coming_soon:
        result.update(status="not_released", reason="尚未发售，不生成在线增长对比。")
        return result
    groups = []
    for start, end in ((size, 0), (size * 2, size)):
        values = []
        for offset in range(start, end, -1):
            target = (now.date() - timedelta(days=offset)).isoformat()
            samples = valid_samples(days.get(target, {}), target)
            unique = {int(s[0]) // 3600: s for s in samples}
            samples = list(unique.values())
            if len(samples) >= min_samples and max(s[0] for s in samples) - min(s[0] for s in samples) >= min_span_hours * 3600:
                values.append(sum(s[1] for s in samples) / len(samples))
        groups.append(values)
    current, previous = groups
    result.update(current_days=len(current), previous_days=len(previous))
    if len(current) != size or len(previous) != size:
        first = parse_time(first_seen)
        if first and first.date() <= now.date() - timedelta(days=2 * size):
            result.update(status="missing_data", reason="窗口内有缺失或采样覆盖不足的日期；缺失没有按0计入。")
        return result
    cur, prev = sum(current) / size, sum(previous) / size
    result.update(current=round(cur, 2), previous=round(prev, 2), absolute_change=round(cur - prev, 2), low_base=prev < 50)
    if prev == 0:
        result.update(status="no_baseline", reason="前一窗口采样均值为0，不计算增长百分比。")
    else:
        result.update(status="ready", percent_change=round((cur - prev) / prev * 100, 1), reason="低基数：百分比容易放大，请同时查看绝对变化。" if prev < 50 else "完整日期内有效采样的均值对比；不代表销量、留存或全天真实平均在线。")
    return result


def build_market(config, previous, history, now, refresh=False, workers=4):
    now = now.astimezone(TZ)
    cutoff = (now.date() - timedelta(days=config.get("retention_days", 190))).isoformat()
    for app in history.get("apps", {}).values():
        app["days"] = {d: values for d, values in app.get("days", {}).items() if d >= cutoff}
    old_games = {int(g["appid"]): g for g in previous.get("games", [])}
    discovery = discover(now, previous.get("discovery", {}), refresh)
    seeds = [dict(g, origin="curated") for g in config["games"]]
    curated_ids = {g["appid"] for g in seeds}
    dynamic = [dict(g, origin="discovered") for g in previous.get("games", []) if g.get("origin") == "discovered" and g["appid"] not in curated_ids]
    limit = config.get("dynamic_limit", 16)
    # Preserve at least 60d of discovered titles where possible, then rotate oldest slots.
    fresh_candidates = [c for c in discovery.get("items", []) if c["appid"] not in curated_ids and c["appid"] not in {g["appid"] for g in dynamic}]
    for candidate in fresh_candidates:
        if len(dynamic) >= limit:
            eligible = [g for g in dynamic if parse_time(g.get("first_seen")) and (now - parse_time(g["first_seen"])).days >= 60]
            if not eligible:
                break
            dynamic.remove(min(eligible, key=lambda g: g["first_seen"]))
        dynamic.append(dict(candidate, origin="discovered"))
    seeds += dynamic[:limit]
    ids = list(dict.fromkeys([g["appid"] for g in seeds] + [c["appid"] for c in discovery.get("items", [])]))
    cached_metadata = {a: {k: v for k, v in old_games[a].items() if k in METADATA_KEYS} for a in ids if a in old_games and not refresh and recent(old_games[a].get("metadata_at"), now)}
    needed_ids = [a for a in ids if a not in cached_metadata]
    metadata, metadata_error = fetch_metadata(needed_ids, now) if needed_ids else ({}, None)
    metadata.update(cached_metadata)
    # Unknown/non-game discovery candidates remain leads, not counted sample games.
    seeds = [g for g in seeds if g["origin"] == "curated" or g["appid"] in metadata or old_games.get(g["appid"], {}).get("metadata_at")]
    for item in discovery.get("items", []):
        meta = metadata.get(item["appid"], old_games.get(item["appid"], {}))
        for key in ("name", "release_date", "demo_url", "coming_soon", "is_action", "header_image"):
            if key in meta:
                item[key] = meta[key]
        item["name"] = item.get("name") or f"Steam App {item['appid']}"
        item["tracked"] = item["appid"] in {g["appid"] for g in seeds}
    def run(seed):
        return collect_game(seed, old_games.get(seed["appid"], {}), metadata.get(seed["appid"]), now, refresh)
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 6))) as pool:
        collected = list(pool.map(run, seeds))
    games = []
    history.update(schema_version=1, timezone="Asia/Shanghai", retention_days=config.get("retention_days", 190))
    for game, success in collected:
        record_sample(history, game, now, success, config.get("retention_days", 190))
        app_history = history["apps"][str(game["appid"])]
        game["windows"] = {str(n): compare_window(app_history["days"], now, n, game["first_seen"], game.get("coming_soon", False),
                             config.get("minimum_daily_samples", 2), config.get("minimum_daily_span_hours", 6)) for n in (1, 7, 30)}
        game["history"] = [{"date": d, "sample_mean": round(sum(s[1] for s in entry["samples"]) / len(entry["samples"]), 2), "samples": len(entry["samples"])}
                           for d, entry in sorted(app_history["days"].items())[-60:] if entry["samples"]]
        games.append(game)
    all_dates = sorted({d for app in history.get("apps", {}).values() for d in app.get("days", {})})
    fresh = sum(g.get("players_status") == "fresh" for g in games)
    history["updated_at"] = stamp(now)
    sources = [
        {"name": "Steam 当前在线人数", "url": "https://partner.steamgames.com/doc/webapi/ISteamUserStats#GetNumberOfCurrentPlayers", "note": "当前连接Steam的在线人数；不含离线游玩，不是销量。"},
        {"name": "Steam 中英文玩家评论", "url": "https://partner.steamgames.com/doc/webapi/IUserReviewsService", "note": "新版公开接口，全部购买渠道，中英文，过滤离题活动；总数与最新评论抽样分开。"},
        {"name": "Steam 官方公告", "url": "https://partner.steamgames.com/doc/webapi/ISteamNews", "note": "仅游戏官方公告，不混入媒体转载。"},
        {"name": "Steam 商店资料与新作入口", "url": STORE + "/explore/new/", "note": "Steam公开商店端点（非稳定性承诺API），优先中国区，缺失时美国区且保留币种；不可用时标示旧值。"},
        {"name": "Steam 热门游戏发现", "url": STORE + "/charts/mostplayed", "note": "只用于扩展样本，榜单移动不替代自建1/7/30天趋势。"},
    ]
    return {"schema_version": 1, "generated_at": stamp(now), "observed_at": max((g.get("observed_at") for g in games if g.get("observed_at")), default=None),
            "timezone": "Asia/Shanghai", "status": "fresh" if all(g["status"] == "fresh" for g in games) and discovery.get("status") == "fresh" and not metadata_error else "partial" if fresh else "stale",
            "coverage": {"total_games": len(games), "action_games": sum(bool(g.get("is_action")) for g in games), "fresh_games": fresh,
                         "history_start": all_dates[0] if all_dates else None, "history_days": len(all_dates), "scope_note": config["description"],
                         "minimum_daily_samples": config.get("minimum_daily_samples", 2), "minimum_daily_span_hours": config.get("minimum_daily_span_hours", 6)},
            "sources": sources, "discovery": discovery, "games": games,
            "methodology": ["全局指本页覆盖的跨品类样本，不是全Steam普查或市场份额。", "1/7/30天均为Asia/Shanghai完整日，对比此前同长窗口；当前日不参与。",
                            "每天至少2个小时槽、跨度至少6小时才计为覆盖；显示采样在线均值，不能推导销量、收入、愿望单或留存。",
                            "冷启动、缺失和0基数分别标记；失败不新增采样，不伪造历史。完整30天前后对比需60个覆盖日。",
                            "玩家评论是中英文片段抽样；公告是事件证据，不自动认定变化的原因。", "数据采集无需Steam账号或模型密钥。"]}, history


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data/market.json")
    parser.add_argument("--history", type=Path, default=ROOT / "data/market_history.json")
    parser.add_argument("--config", type=Path, default=ROOT / "data/market_sources.json")
    parser.add_argument("--refresh", action="store_true", help="Refresh daily metadata, reviews, announcements and discovery now")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    config = read_json(args.config, {})
    if not config.get("games"):
        parser.error("config requires games")
    now = datetime.now(TZ)
    market, history = build_market(config, read_json(args.output, {}), read_json(args.history, {"apps": {}}), now, args.refresh, args.workers)
    write_json(args.history, history, compact=True)
    write_json(args.output, market)
    print(f"Steam market: {market['coverage']['fresh_games']}/{market['coverage']['total_games']} fresh player snapshots; status={market['status']}")


if __name__ == "__main__":
    main()
