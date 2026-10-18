"""Bounded, cross-genre Steam observations from public first-party sources.

Discovery is daily; online-player observations may run four times daily. This is
an explicitly described sample, not a Steam census, revenue or sales estimate.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time

import requests

from steam_market import (API, STORE, HEADERS, ROOT, TZ, clean_text, compare_window,
                          metadata_from_browse, parse_release, parse_time, read_json,
                          recent, record_sample, request_json, safe_error, service,
                          stamp, valid_samples, write_json)

GLOBAL_CHART = STORE + "/charts/topselling/global"
RECENT_SEARCH = STORE + "/search/?sort_by=Released_DESC&category1=998&ignore_preferences=1"
SOURCES = [
    {"id": "recent_releases", "name": "Steam 最近发行", "url": RECENT_SEARCH, "sample_cap": 100,
     "scope_note": "未登录美国区商店，按发行日期排序前100条；不设评论数门槛，商店可见性限制仍存在。"},
    {"id": "global_top_sellers", "name": "Steam 全球热销榜", "url": GLOBAL_CHART, "sample_cap": 100,
     "scope_note": "全球实时应用榜前100位，收入包含内购与DLC；排除非游戏后保留原榜位次。"},
    {"id": "most_played", "name": "Steam 热门游玩榜", "url": STORE + "/charts/mostplayed", "sample_cap": 50,
     "scope_note": "Steam公开热门游玩榜前50款，仅用于发现活跃作品；不是销量榜。"},
]
METADATA_FIELDS = {"name", "header_image", "tags", "genres", "player_modes", "is_action", "release_date",
                   "release_1_0_date", "release_date_basis", "release_date_status", "release_date_evidence_at", "first_release_date", "early_access_transition",
                   "release_label", "coming_soon", "is_demo", "description", "price",
                   "metadata_at", "metadata_source", "metadata_status", "is_free", "app_type"}


def request_text(url, params=None):
    response = requests.get(url, params=params, headers=HEADERS, timeout=(5, 20))
    response.raise_for_status()
    return response.text


class SearchRows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag != "a" or "search_result_row" not in attrs.get("class", "").split():
            return
        appid = attrs.get("data-ds-appid", "")
        if appid.isdigit() and re.search(r"/app/" + appid + r"(?:/|$)", attrs.get("href", "")):
            self.rows.append({"appid": int(appid)})


def parse_search(data, limit=100):
    if data.get("success") != 1 or not isinstance(data.get("results_html"), str):
        raise ValueError("search response unavailable")
    parser = SearchRows()
    parser.feed(data["results_html"])
    rows = list({r["appid"]: r for r in parser.rows}.values())[:limit]
    if not rows:
        raise ValueError("search returned no games")
    return rows


def parse_global_chart(document):
    match = re.search(r'<script\b[^>]*\bid="valve-ssr-data"[^>]*>(.*?)</script>', document, re.S)
    if not match:
        raise ValueError("chart data unavailable")
    data = json.loads(match.group(1))
    loaders = [json.loads(v) if isinstance(v, str) else v for v in data.get("loaderData", [])]
    chart_context = [v for v in loaders if isinstance(v, dict) and "strCountryCode" in v]
    if len(chart_context) != 1 or chart_context[0]["strCountryCode"] != "":
        raise ValueError("chart is not explicitly global")
    query_data = data.get("renderContext", {}).get("queryData", {})
    if isinstance(query_data, str):
        query_data = json.loads(query_data)
    for query in query_data.get("queries", []):
        key = query.get("queryKey", [])
        if len(key) < 2 or key[0] != "StoreQuery" or not isinstance(key[1], dict):
            continue
        options = key[1]
        # sort=11 is the live global top-seller query on this verified chart.
        if options.get("sort") != 11 or options.get("start", 0) != 0:
            continue
        state = query.get("state", {})
        items = state.get("data", {}).get("rgItemIDs", [])
        if state.get("status") != "success" or len(items) < 20:
            continue
        return [{"appid": int(row["appid"]), "rank": rank} for rank, row in enumerate(items[:100], 1)
                if isinstance(row, dict) and isinstance(row.get("appid"), int) and row["appid"] > 0]
    raise ValueError("global live chart query unavailable")


def fetch_roster(source_id):
    if source_id == "recent_releases":
        return parse_search(request_json(STORE + "/search/results/", {
            "start": 0, "count": 100, "sort_by": "Released_DESC", "category1": 998,
            "infinite": 1, "cc": "us", "l": "english", "ignore_preferences": 1,
        }))
    if source_id == "global_top_sellers":
        return parse_global_chart(request_text(GLOBAL_CHART, {"l": "english"}))
    ranks = service("ISteamChartsService/GetMostPlayedGames").get("ranks", [])
    rows = [{"appid": int(row["appid"]), "rank": int(row["rank"])} for row in ranks
            if isinstance(row.get("appid"), int) and isinstance(row.get("rank"), int)]
    if not rows:
        raise ValueError("most played list unavailable")
    return sorted(rows, key=lambda row: row["rank"])[:50]


def discover(previous, now, refresh=False):
    previous = {row["id"]: row for row in previous}
    output = []
    for source in SOURCES:
        old = previous.get(source["id"], {})
        if not refresh and recent(old.get("observed_at"), now) and old.get("status") == "fresh":
            output.append(deepcopy(old))
            continue
        roster = dict(source, attempted_at=stamp(now), scope_verified=source["id"] != "global_top_sellers")
        try:
            rows = fetch_roster(source["id"])
            roster.update(items=rows, discovered_count=len(rows), observed_at=stamp(now), status="fresh", scope_verified=True)
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            roster.update(items=deepcopy(old.get("items", [])), observed_at=old.get("observed_at"),
                          discovered_count=len(old.get("items", [])), status="stale" if old.get("items") else "unavailable",
                          scope_verified=old.get("scope_verified", False), error=safe_error(exc))
        output.append(roster)
    return output


def normalize_metadata(item, tag_names, now):
    if item.get("type") != 0 or item.get("success") != 1:
        raise ValueError("not a released game")
    result = metadata_from_browse(item, tag_names, now, "US")
    release = item.get("release", {})
    dates = [parse_release(release.get(field)) for field in ("original_steam_release_date", "steam_release_date")]
    dates = [value for value in dates if value]
    original = parse_release(release.get("original_steam_release_date"))
    transition = parse_release(release.get("release_from_early_access_date"))
    result["release_date"] = min(dates) if dates else None
    result["release_1_0_date"] = transition
    result["release_date_basis"] = "original_steam_release_date" if original and original == result["release_date"] else "steam_release_date"
    result["first_release_date"] = original
    result["early_access_transition"] = bool(transition)
    result["release_date_status"] = "first_release_unverified" if transition and not original else "store_date"
    result["release_date_evidence_at"] = stamp(now)
    result["coming_soon"] = bool(release.get("is_coming_soon") or not dates or min(dates) > now.date().isoformat())
    result.update(is_free=bool(item.get("is_free")), app_type="game")
    return result


def preserve_earlier_release(meta, old):
    """A later1.0 release must not erase an earlier date already observed here."""
    previous = old.get("release_date")
    if previous and meta.get("release_date") and previous < meta["release_date"] and not old.get("coming_soon"):
        meta["release_date"] = previous
        meta["release_date_basis"] = "earliest_observed_store_date"
        meta["release_date_evidence_at"] = old.get("release_date_evidence_at") or old.get("metadata_at")
        meta["first_release_date"] = old.get("first_release_date")
        meta["release_date_status"] = old.get("release_date_status", "store_date")
    return meta


def fetch_metadata(appids, now, deadline=None):
    output, rejected, errors = {}, set(), []
    if not appids:
        return output, rejected, errors
    if deadline is not None and time.monotonic() >= deadline:
        return output, rejected, ["商店资料: 本次采集时间预算已用完"]
    try:
        tags = {str(t["tagid"]): t["name"] for t in service("IStoreService/GetTagList", {"language": "english"}).get("tags", [])}
        if not tags:
            raise ValueError("tags unavailable")
    except (requests.RequestException, ValueError, KeyError) as exc:
        return output, rejected, ["标签资料: " + safe_error(exc)]
    for start in range(0, len(appids), 50):
        if deadline is not None and time.monotonic() >= deadline:
            errors.append("商店资料: 本次采集时间预算已用完")
            break
        ids = appids[start:start + 50]
        payload = {"ids": [{"appid": appid} for appid in ids],
                   "context": {"language": "english", "country_code": "US", "steam_realm": 1},
                   "data_request": {"include_basic_info": True, "include_tag_count": 20, "include_assets": True,
                                    "include_release": True, "include_all_purchase_options": True}}
        try:
            for row in service("IStoreBrowseService/GetItems", payload).get("store_items", []):
                appid = row.get("appid")
                if appid not in ids:
                    continue
                if row.get("success") == 1 and row.get("type") != 0:
                    rejected.add(appid)
                    continue
                try:
                    output[appid] = normalize_metadata(row, tags, now)
                except (ValueError, KeyError, TypeError):
                    continue
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            errors.append("商店资料: " + safe_error(exc))
    return output, rejected, errors


def fetch_review_summary(appid, now):
    data = request_json(STORE + f"/appreviews/{appid}", {
        "json": 1, "language": "all", "purchase_type": "all", "review_type": "all",
        "filter": "all", "filter_offtopic_activity": 1, "num_per_page": 1,
    })
    summary = data.get("query_summary", {})
    values = [summary.get(k) for k in ("total_reviews", "total_positive", "total_negative")]
    if data.get("success") != 1 or any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in values):
        raise ValueError("review totals unavailable")
    total, positive, negative = values
    if total != positive + negative:
        raise ValueError("review totals inconsistent")
    return {"total": total, "positive": positive, "negative": negative,
            "positive_percent": round(positive / total * 100, 1) if total else None,
            "scope": "all_languages_all_purchase_types", "offtopic_filtered": True,
            "sampled_at": stamp(now), "status": "fresh", "source_url": STORE + f"/app/{appid}/#app_reviews_hash"}


def collect_game(seed, old, meta, now, refresh=False, deadline=None):
    appid = seed["appid"]
    game = deepcopy(old) or {"appid": appid, "first_seen": stamp(now), "tags": [], "genres": []}
    if meta:
        game.update(meta)
    elif refresh or not recent(game.get("metadata_at"), now, 7 * 24):
        game["metadata_status"] = "stale" if game.get("metadata_at") else "unavailable"
    game.update(appid=appid, store_url=STORE + f"/app/{appid}/", attempted_at=stamp(now), errors=[], collection_status="attempted",
                origin="global_discovery", discovery_sources=seed["discovery_sources"], last_discovered_at=seed.get("last_discovered_at"))
    for field in ("top_sellers_rank", "top_sellers_observed_at", "top_sellers_status"):
        if field in seed:
            game[field] = seed[field]
        else:
            game.pop(field, None)
    success = False
    within_budget = lambda: deadline is None or time.monotonic() < deadline
    if within_budget():
        game["players_attempted_at"] = stamp(now)
        try:
            response = request_json(API + "/ISteamUserStats/GetNumberOfCurrentPlayers/v1/", {"appid": appid}).get("response", {})
            count = response.get("player_count")
            if response.get("result") != 1 or not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise ValueError("players unavailable")
            game.update(current_players=count, observed_at=stamp(now), players_observed_at=stamp(now), players_status="fresh")
            success = True
        except (requests.RequestException, ValueError) as exc:
            game["players_status"] = "stale" if game.get("current_players") is not None else "unavailable"
            game["errors"].append("在线人数: " + safe_error(exc))
    else:
        game["players_status"] = "stale" if game.get("current_players") is not None else "unavailable"
        game["collection_status"] = "deferred_budget"
        game["errors"].append("在线人数: 本次采集时间预算已用完，留待下次采样")
    if refresh or game.get("review_summary", {}).get("status") != "fresh" or not recent(game.get("review_summary", {}).get("sampled_at"), now):
        if within_budget():
            try:
                game["review_summary"] = fetch_review_summary(appid, now)
            except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
                game.setdefault("review_summary", {})["status"] = "stale" if game.get("review_summary", {}).get("sampled_at") else "unavailable"
                game["errors"].append("全部语言评论统计: " + safe_error(exc))
        else:
            game.setdefault("review_summary", {})["status"] = "stale" if game.get("review_summary", {}).get("sampled_at") else "unavailable"
            game["collection_status"] = "deferred_budget"
            game["errors"].append("评论统计: 本次采集时间预算已用完，留待下次采样")
    game["status"] = "fresh" if success and not game["errors"] and game.get("metadata_status") == "fresh" and game.get("review_summary", {}).get("status") == "fresh" else "partial" if success else "stale" if game.get("players_observed_at") else "unavailable"
    return game, success


def seed_from_game(old, rosters):
    sources = {s["id"]: dict(s, status="historical") for s in old.get("discovery_sources", [])}
    seed = {"appid": old["appid"], "last_discovered_at": old.get("last_discovered_at")}
    for roster in rosters:
        found = next((row for row in roster["items"] if row["appid"] == old["appid"]), None)
        if found:
            sources[roster["id"]] = {"id": roster["id"], "name": roster["name"], "url": roster["url"],
                                     "observed_at": roster["observed_at"], "status": roster["status"]}
            if "rank" in found:
                sources[roster["id"]]["rank"] = found["rank"]
            if roster["status"] == "fresh":
                seed["last_discovered_at"] = max(seed.get("last_discovered_at") or "", roster["observed_at"])
        if roster["id"] == "global_top_sellers":
            if found and roster.get("scope_verified"):
                seed.update(top_sellers_rank=found["rank"], top_sellers_observed_at=roster["observed_at"], top_sellers_status=roster["status"])
            elif roster["status"] != "fresh" and old.get("top_sellers_rank"):
                seed.update(top_sellers_rank=old["top_sellers_rank"], top_sellers_observed_at=old.get("top_sellers_observed_at"), top_sellers_status="stale")
    seed["discovery_sources"] = list(sources.values())
    return seed


def choose_candidates(rosters):
    result = []
    # Interleave the sources so later daily admissions retain both ordinary new
    # releases and chart discoveries rather than always exhausting the first list.
    for index in range(max((len(r["items"]) for r in rosters), default=0)):
        for roster in rosters:
            if roster["status"] == "fresh" and index < len(roster["items"]):
                appid = roster["items"][index]["appid"]
                if appid not in result:
                    result.append(appid)
    return result


def build_global_market(previous, history, now, refresh=False, workers=4, max_games=1000, daily_admissions=8, budget_seconds=480):
    deadline = time.monotonic() + max(0, budget_seconds)
    now = now.astimezone(TZ)
    rosters = discover(previous.get("discovery", {}).get("sources", []), now, refresh)
    old_games = {g["appid"]: g for g in previous.get("games", [])}
    candidates = choose_candidates(rosters)
    today = now.date().isoformat()
    previous_admissions = previous.get("discovery", {}).get("admission", {})
    already_admitted = previous_admissions.get("count", 0) if previous_admissions.get("date") == today else 0
    allowance = max(0, daily_admissions - already_admitted) if old_games else 250
    # Keep observed titles for >=90d and until they have been absent from all
    # discovery sources for90d. Full slots defer new admissions; no early eviction.
    keep = {}
    for appid, game in old_games.items():
        last = parse_time(game.get("last_discovered_at") or game.get("first_seen"))
        if appid in candidates or last is None or now - last < timedelta(days=90):
            keep[appid] = game
    candidate_new = [appid for appid in candidates if appid not in keep]
    # Fetch the bounded daily roster's metadata to screen DLC/software before
    # admission. Later online/review requests only concern admitted games.
    ids = list(dict.fromkeys(list(keep) + candidate_new))
    cached = {appid: {k: v for k, v in keep[appid].items() if k in METADATA_FIELDS}
              for appid in keep if not refresh and keep[appid].get("metadata_status") == "fresh" and recent(keep[appid].get("metadata_at"), now, 7 * 24)}
    metadata, rejected, metadata_errors = fetch_metadata([appid for appid in ids if appid not in cached], now, deadline)
    for appid, meta in metadata.items():
        preserve_earlier_release(meta, old_games.get(appid, {}))
    metadata.update(cached)
    def eligible(appid):
        meta = metadata.get(appid) or keep.get(appid, {})
        return appid not in rejected and meta.get("app_type") == "game" and bool(meta.get("release_date")) and not meta.get("coming_soon") and not meta.get("is_demo") and meta["release_date"] <= today
    keep = {appid: game for appid, game in keep.items() if eligible(appid)}
    admitted = [appid for appid in candidate_new if eligible(appid)][:min(allowance, max(0, max_games - len(keep)))]
    seeds = [seed_from_game(keep.get(appid, {"appid": appid}), rosters) for appid in list(keep) + admitted]
    seeds.sort(key=lambda seed: old_games.get(seed["appid"], {}).get("players_attempted_at") or "")
    def run(seed):
        return collect_game(seed, old_games.get(seed["appid"], {}), metadata.get(seed["appid"]), now, refresh, deadline)
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 4))) as pool:
        collected = list(pool.map(run, seeds))
    history.update(schema_version=1, timezone="Asia/Shanghai", retention_days=190, updated_at=stamp(now))
    games = []
    for game, success in collected:
        record_sample(history, game, now, success, 190)
        days = history["apps"][str(game["appid"])]["days"]
        game["windows"] = {str(n): compare_window(days, now, n, game["first_seen"], False) for n in (1, 7, 30)}
        game["history"] = []
        for day, entry in sorted(days.items())[-60:]:
            samples = valid_samples(entry, day)
            if samples:
                game["history"].append({"date": day, "sample_mean": round(sum(s[1] for s in samples) / len(samples), 2), "samples": len(samples)})
        games.append(game)
    cutoff = (now.date() - timedelta(days=190)).isoformat()
    for app in history.get("apps", {}).values():
        app["days"] = {d: v for d, v in app.get("days", {}).items() if d >= cutoff}
    history["apps"] = {appid: app for appid, app in history.get("apps", {}).items() if app.get("days") or int(appid) in keep or int(appid) in admitted}
    tracked = {g["appid"] for g in games}
    source_rosters = []
    for roster in rosters:
        roster["tracked_count"] = sum(row["appid"] in tracked for row in roster["items"])
        source_rosters.append({k: v for k, v in roster.items() if k != "items"})
    all_dates = sorted({d for app in history.get("apps", {}).values() for d in app.get("days", {})})
    fresh = sum(g.get("players_status") == "fresh" for g in games)
    any_fresh = fresh or any(g.get("review_summary", {}).get("status") == "fresh" for g in games) or (games and any(r["status"] == "fresh" for r in rosters))
    return {
        "schema_version": 1, "market_scope": "global", "generated_at": stamp(now), "timezone": "Asia/Shanghai",
        "status": "fresh" if games and all(g["status"] == "fresh" for g in games) and all(r["status"] == "fresh" for r in rosters) and not metadata_errors else "partial" if any_fresh else "stale",
        "coverage": {"total_games": len(games), "fresh_games": fresh, "action_games": sum(g.get("is_action", False) for g in games),
                     "fresh_review_games": sum(g.get("review_summary", {}).get("status") == "fresh" for g in games),
                     "history_start": all_dates[0] if all_dates else None, "history_days": len(all_dates),
                     "candidate_games": len(candidates), "excluded_or_unavailable_candidates": sum(not eligible(a) for a in candidates),
                     "deferred_candidates": sum(eligible(a) and a not in tracked for a in candidates),
                     "source_rosters": source_rosters, "minimum_daily_samples": 2, "minimum_daily_span_hours": 6,
                     "cohort_retention_days": 90, "max_tracked_games": max_games, "daily_admission_limit": daily_admissions,
                     "collection_budget_seconds": budget_seconds, "deferred_collection_games": sum(g.get("collection_status") == "deferred_budget" for g in games),
                     "scope_note": "跨类型发现样本，包含动作游戏；由最近发行、全球热销及热门游玩三个入口组成，不是Steam全库或市场份额。"},
        "discovery": {"sources": rosters, "admission": {"date": today, "count": already_admitted + len(admitted)}, "errors": metadata_errors},
        "sources": [{"name": s["name"], "url": s["url"], "note": s["scope_note"]} for s in SOURCES] + [
            {"name": "Steam 全部语言评论统计", "url": "https://partner.steamgames.com/doc/store/getreviews", "note": "所有语言、全部购买渠道，过滤离题活动；累计评论不是销量。"},
            {"name": "Steam 当前在线人数", "url": "https://partner.steamgames.com/doc/webapi/ISteamUserStats#GetNumberOfCurrentPlayers", "note": "采样时在线人数，不含离线游玩，不是销售额。"}],
        "methodology": ["榜单、近期发行与活跃游戏采用不同的发现入口，均保留样本上限及采集状态。",
                        "商店资料默认缓存7天，发现及全语言评论统计每日更新，在线人数每次运行采样；不获取完整评论正文。",
                        "已发售游戏排除DLC、软件、Demo和未发售作品；优先原始商店日期，EA转正式版日期单独保存；接口缺少原始日期时不视为已核实首次发售。",
                        "样本至少保留90天，每日最多新纳入8款；初次建立样本最多250款，总上限1000款，满额时延迟新加入。",
                        "单轮采集默认8分钟预算；到时保留未采样作品的旧值并标旧，不新增历史，下次优先处理更久未尝试的作品。",
                        "1/7/30天对比两个同长完整窗口，每天至少2次采样且跨6小时；缺失不计0，不补造历史。",
                        "全球热销榜按收入排序但没有金额；评论和在线人数均不能转换为销量、收入或ROI。"],
        "games": games,
    }, history


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data/global_market.json")
    parser.add_argument("--history", type=Path, default=ROOT / "data/global_market_history.json")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--budget-seconds", type=int, default=480)
    args = parser.parse_args()
    market, history = build_global_market(read_json(args.output, {}), read_json(args.history, {"apps": {}}), datetime.now(TZ), args.refresh, args.workers, budget_seconds=args.budget_seconds)
    write_json(args.history, history, compact=True)
    write_json(args.output, market)
    print(f"Global Steam: {market['coverage']['fresh_games']}/{market['coverage']['total_games']} player snapshots; status={market['status']}")
    for source in market["coverage"]["source_rosters"]:
        print(f"  {source['id']}: {source['status']}; discovered={source['discovered_count']}; tracked={source['tracked_count']}")


if __name__ == "__main__":
    main()
