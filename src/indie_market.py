"""Daily Steam compact indie sample with exact rolling review windows.

Public sales units and per-game downloads are unavailable. Search positions are
regional Indie-chart observations, not global ranks or estimates of sales.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
import re
import time

import requests

from global_market import METADATA_FIELDS, fetch_metadata
from steam_market import (API, ROOT, STORE, TZ, parse_time, read_json, recent,
                          request_json, safe_error, service, stamp, write_json)

MAX_GAMES = 60
COMPACT_TAGS = {
    "Casual", "Puzzle", "Arcade", "Platformer", "2D Platformer",
    "Precision Platformer", "Roguelite", "Rogue-like", "Roguelike", "Action Roguelike",
    "Card Game", "Deckbuilding", "Roguelike Deckbuilder", "Clicker", "Idler",
    "Incremental", "Minimalist", "Bullet Hell", "Auto Battler",
    "Top-Down Shooter", "Twin Stick Shooter", "Party Game", "Mini Golf",
    "Word Game", "Hidden Object",
}
SOURCE_DEFINITIONS = [
    {"id": "indie_top_sellers", "name": "Steam 美国区独立游戏热销入口",
     "url": STORE + "/search/?filter=topsellers&tags=492&category1=998&cc=us&l=english&ignore_preferences=1",
     "note": "未登录美国区、Indie标签、游戏类型，热销排序前100条；榜位保留筛选前原始顺位。"},
    {"id": "indie_recent", "name": "Steam 独立游戏最近发行入口",
     "url": STORE + "/search/?sort_by=Released_DESC&tags=492&category1=998&cc=us&l=english&ignore_preferences=1",
     "note": "同一地区与标签，按发行日期排序前100条；随后核实游戏类型、发售状态、玩法标签与价格。"},
]
SCOPE_NOTE = ("动态发现的最多60款独立游戏样本：来自Steam美国区Indie热销/最近发行各前100条，"
              "至少有一个紧凑玩法标签，免费或美国区原价不高于25美元；排除DLC、软件、Demo和未发售作品。"
              "这些条件只是小体量的筛选代理，不代表已核实团队规模、制作预算或Steam全库排名。")
ERRORS = (requests.RequestException, ValueError, KeyError, TypeError)


def nonnegative_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def eligible(meta, now, indie_source_verified=False):
    price = meta.get("price", {})
    tags = set(meta.get("tags", []))
    original = price.get("initial")
    if original is None and price.get("discount_percent") == 0:
        original = price.get("final")
    priced = meta.get("is_free") or (price.get("currency") == "USD" and
              nonnegative_int(original) and 0 < original <= 2500)
    return bool(meta.get("app_type") == "game" and not meta.get("is_demo") and
                not meta.get("coming_soon") and meta.get("release_date") and
                meta["release_date"] <= now.date().isoformat() and
                ("Indie" in tags or indie_source_verified) and tags & COMPACT_TAGS and priced)


class RankedSearchRows(HTMLParser):
    """Keep source positions even when packages or duplicate apps are skipped."""
    def __init__(self):
        super().__init__()
        self.position, self.rows, self.seen = 0, [], set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag != "a" or "search_result_row" not in attrs.get("class", "").split():
            return
        self.position += 1
        appid = attrs.get("data-ds-appid", "")
        if (appid.isdigit() and appid not in self.seen and
                re.search(r"/app/" + appid + r"(?:/|$)", attrs.get("href", ""))):
            self.rows.append({"appid": int(appid), "rank": self.position})
            self.seen.add(appid)


def parse_ranked_search(data):
    if data.get("success") != 1 or not isinstance(data.get("results_html"), str):
        raise ValueError("search response unavailable")
    parser = RankedSearchRows()
    parser.feed(data["results_html"])
    if not parser.rows:
        raise ValueError("search returned no games")
    return [row for row in parser.rows if row["rank"] <= 100]


def fetch_roster(source_id):
    params = {"start": 0, "count": 100, "tags": "492", "category1": 998,
              "infinite": 1, "cc": "us", "l": "english", "ignore_preferences": 1}
    if source_id == "indie_top_sellers":
        params["filter"] = "topsellers"
    else:
        params["sort_by"] = "Released_DESC"
    return parse_ranked_search(request_json(STORE + "/search/results/", params))


def discover(previous, now):
    prior = {row["id"]: row for row in previous}
    rosters = []
    for definition in SOURCE_DEFINITIONS:
        old = prior.get(definition["id"], {})
        row = dict(definition, attempted_at=stamp(now))
        try:
            items = fetch_roster(definition["id"])
            row.update(items=items, observed_at=stamp(now), status="fresh")
        except ERRORS as exc:
            row.update(items=deepcopy(old.get("items", [])), observed_at=old.get("observed_at"),
                       status="stale" if old.get("items") else "unavailable", error=safe_error(exc))
        rosters.append(row)
    return rosters


def candidate_ids(rosters):
    """Reserve discovery opportunities for new games, without fixed seed titles."""
    lists = {row["id"]: row.get("items", []) for row in rosters}
    hot, new = lists.get("indie_top_sellers", []), lists.get("indie_recent", [])
    result = []
    for start in range(max(len(hot), len(new))):
        chunk = hot[start * 4:start * 4 + 4] + new[start:start + 1]
        for item in chunk:
            if item["appid"] not in result:
                result.append(item["appid"])
    return result


def review_counts(appid, now, days=None):
    payload = {"appid": appid, "filter": 1, "languages": ["all"],
               "review_type": 0, "purchase_type": 1, "num_per_page": 1,
               "filter_offtopic_activity": True, "display_language": "schinese"}
    start = None
    if days is not None:
        start = now - timedelta(days=days)
        payload.update(date_range_start=int(start.timestamp()), date_range_end=int(now.timestamp()))
    response = service("IUserReviewsService/GetAppReviews", payload)
    summary = response.get("query_summary", {})
    total, positive, negative = [summary.get(key) for key in ("total_reviews", "total_positive", "total_negative")]
    matching = response.get("total_matching")
    if (not all(nonnegative_int(n) for n in (total, positive, negative, matching)) or
            total != positive + negative or (days is not None and total != matching)):
        raise ValueError("review window summary unavailable or inconsistent")
    # Lifetime query_summary and total_matching can differ by a few records in
    # Steam's independently cached counters. Lifetime ratings use the internally
    # consistent score summary; exact dated windows additionally require equality.
    # The recent filter must honor exact timestamps; a returned row outside the
    # requested interval is a schema failure, never silently a lifetime count.
    if days is not None:
        for row in response.get("reviews", []):
            created = row.get("timestamp_created")
            if not nonnegative_int(created) or not int(start.timestamp()) <= created <= int(now.timestamp()):
                raise ValueError("review window ignored by source")
    result = {"count": total, "positive": positive, "negative": negative,
              "positive_percent": round(positive / total * 100, 1) if total else None,
              "start": stamp(start) if start else None, "end": stamp(now),
              "sampled_at": stamp(now), "status": "fresh", "scope": "all_languages_all_purchase_types",
              "offtopic_filtered": True, "source": "IUserReviewsService/GetAppReviews",
              "source_url": STORE + f"/app/{appid}/#app_reviews_hash"}
    if days is None:
        result["total"] = result.pop("count")
    return result


def stale_review(old, now, days=None, error=None):
    result = deepcopy(old)
    key = "total" if days is None else "count"
    if not result:
        result = {key: None, "positive": None, "negative": None, "positive_percent": None,
                  "start": stamp(now - timedelta(days=days)) if days else None,
                  "end": stamp(now), "sampled_at": None}
    result.update(status="stale" if result.get(key) is not None else "unavailable",
                  attempted_at=stamp(now))
    if error:
        result["error"] = error
    return result


def apply_rank(game, prefix, roster, now):
    row = next((r for r in roster.get("items", []) if r["appid"] == game["appid"]), None)
    key = prefix + "_rank"
    if row is not None:
        fresh = roster.get("status") == "fresh" and recent(roster.get("observed_at"), now)
        game.update({key: row["rank"], prefix + "_observed_at": roster.get("observed_at"),
                     prefix + "_status": "fresh" if fresh else "stale"})
    elif roster.get("status") == "fresh" and recent(roster.get("observed_at"), now):
        game.update({key: None, prefix + "_observed_at": roster.get("observed_at"), prefix + "_status": "not_listed"})
    else:
        game.setdefault(key, None)
        game.setdefault(prefix + "_observed_at", None)
        game[prefix + "_status"] = "stale" if game.get(key) is not None else "unavailable"


def collect_game(appid, old, meta, rosters, global_game, global_roster, now, deadline):
    game = deepcopy(old) or {"appid": appid, "first_seen": stamp(now)}
    if meta:
        game.update(meta)
    else:
        game["metadata_status"] = "stale" if game.get("metadata_at") else "unavailable"
    game.update(appid=appid, store_url=STORE + f"/app/{appid}/", attempted_at=stamp(now), errors=[])
    game["compact_tags"] = sorted(set(game.get("tags", [])) & COMPACT_TAGS)
    indie_roster = next((r for r in rosters if r["id"] == "indie_top_sellers"), {})
    apply_rank(game, "indie_top_sellers", indie_roster, now)
    apply_rank(game, "top_sellers", global_roster, now)
    game["indie_source_verified"] = True
    game["discovery_sources"] = [r["id"] for r in rosters if any(i["appid"] == appid for i in r.get("items", []))]
    global_at = global_game.get("players_observed_at")
    if global_game.get("players_status") == "fresh" and recent(global_at, now) and nonnegative_int(global_game.get("current_players")):
        game.update(current_players=global_game["current_players"], players_observed_at=global_at, players_status="fresh")
    elif time.monotonic() < deadline:
        try:
            response = request_json(API + "/ISteamUserStats/GetNumberOfCurrentPlayers/v1/", {"appid": appid}).get("response", {})
            count = response.get("player_count")
            if response.get("result") != 1 or not nonnegative_int(count):
                raise ValueError("player count unavailable")
            game.update(current_players=count, players_status="fresh", players_observed_at=stamp(now))
        except ERRORS as exc:
            game["players_status"] = "stale" if game.get("current_players") is not None else "unavailable"
            game["errors"].append("当前在线: " + safe_error(exc))
    else:
        game["players_status"] = "stale" if game.get("current_players") is not None else "unavailable"
    game.setdefault("current_players", None)
    game.setdefault("players_observed_at", None)
    windows = {}
    for days in (1, 7, 30):
        prior = game.get("review_windows", {}).get(str(days), {})
        if time.monotonic() >= deadline:
            windows[str(days)] = stale_review(prior, now, days, "本次采集时间预算已用完")
            continue
        try:
            windows[str(days)] = review_counts(appid, now, days)
        except ERRORS as exc:
            windows[str(days)] = stale_review(prior, now, days, safe_error(exc))
    game["review_windows"] = windows
    shared_summary = global_game.get("review_summary", {})
    old_summary = game.get("review_summary", {})
    cached_summary = next((row for row in (shared_summary, old_summary)
                           if row.get("status") == "fresh" and recent(row.get("sampled_at"), now)
                           and row.get("scope") == "all_languages_all_purchase_types"), None)
    if cached_summary:
        game["review_summary"] = deepcopy(cached_summary)
    elif time.monotonic() < deadline:
        try:
            game["review_summary"] = review_counts(appid, now)
        except ERRORS as exc:
            game["review_summary"] = stale_review(old_summary, now, error=safe_error(exc))
    else:
        game["review_summary"] = stale_review(old_summary, now, error="本次采集时间预算已用完")
    # Only displayed rankings govern the daily cache. An optional lifetime
    # summary failure must not make the whole page re-poll every market cycle.
    metrics = [game["players_status"]] + [w["status"] for w in windows.values()]
    game["status"] = "fresh" if all(s == "fresh" for s in metrics) and game.get("metadata_status") == "fresh" else "partial"
    return game


def build_indie_market(previous, global_market, now, refresh=False, workers=3, max_games=MAX_GAMES, budget_seconds=420):
    now = now.astimezone(TZ).replace(microsecond=0)
    if not refresh and previous.get("status") == "fresh" and previous.get("games") and recent(previous.get("generated_at"), now):
        return deepcopy(previous)
    deadline = time.monotonic() + max(0, budget_seconds)
    rosters = discover(previous.get("discovery", []), now)
    candidates = candidate_ids(rosters)
    old_games = {g["appid"]: g for g in previous.get("games", [])}
    global_games = {g["appid"]: g for g in global_market.get("games", [])}
    if not candidates:
        candidates = list(old_games)
    cached = {}
    for appid in candidates:
        # Metadata comes from the same US Browse service as global_market.
        for old in (old_games.get(appid, {}), global_games.get(appid, {})):
            if old.get("metadata_status") == "fresh" and recent(old.get("metadata_at"), now, 7 * 24):
                cached[appid] = {k: deepcopy(v) for k, v in old.items() if k in METADATA_FIELDS}
                break
    metadata, rejected, errors = fetch_metadata([a for a in candidates if a not in cached], now, deadline)
    metadata.update(cached)
    chosen = [a for a in candidates if a not in rejected and eligible(metadata.get(a) or old_games.get(a, {}), now, True)][:max(1, min(max_games, MAX_GAMES))]
    global_roster = next((r for r in global_market.get("discovery", {}).get("sources", []) if r.get("id") == "global_top_sellers" and r.get("scope_verified")), {})
    def run(appid):
        return collect_game(appid, old_games.get(appid, {}), metadata.get(appid), rosters,
                            global_games.get(appid, {}), global_roster, now, deadline)
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 4))) as pool:
        games = list(pool.map(run, chosen))
    fresh = sum(g["status"] == "fresh" for g in games)
    return {
        "schema_version": 1, "generated_at": stamp(now), "timezone": "Asia/Shanghai",
        "status": "fresh" if games and fresh == len(games) and all(r["status"] == "fresh" for r in rosters) and not errors else "partial" if games else "unavailable",
        "scope_note": SCOPE_NOTE,
        "coverage": {"total_games": len(games), "fresh_games": fresh, "candidate_games": len(candidates),
                     "excluded_or_unavailable_candidates": len(candidates) - sum(a not in rejected and eligible(metadata.get(a) or old_games.get(a, {}), now, True) for a in candidates),
                     "max_games": MAX_GAMES, "price_ceiling_usd": 25, "collection_budget_seconds": budget_seconds,
                     "fresh_windows": {str(n): sum(g["review_windows"][str(n)]["status"] == "fresh" for g in games) for n in (1, 7, 30)},
                     "fresh_players": sum(g["players_status"] == "fresh" for g in games)},
        "discovery": rosters, "errors": errors,
        "sources": [{k: v for k, v in d.items() if k != "id"} for d in SOURCE_DEFINITIONS] + [
            {"name": "Steam 用户评价接口", "url": "https://partner.steamgames.com/doc/webapi/IUserReviewsService", "note": "按评论创建时间精确查询滚动窗口，所有语言与购买渠道，过滤离题活动。"},
            {"name": "Steam 热销榜规则", "url": "https://partner.steamgames.com/doc/store/top_sellers", "note": "近24小时收入、最近3小时加权，包含本体、DLC与内购，不是售出份数。"},
            {"name": "Steam 当前在线人数", "url": "https://partner.steamgames.com/doc/webapi/ISteamUserStats#GetNumberOfCurrentPlayers", "note": "采集时连接Steam的正在游玩人数，不含离线玩家，也不是下载量。"},
            {"name": "Steam 财务数据权限", "url": "https://partner.steamgames.com/doc/webapi/IPartnerFinancialsService", "note": "实际日销量和收入需要对应发行商的财务权限，公开接口无法提供全库数据。"}],
        "unavailable_metrics": {"sales_units": "Steam未公开逐游戏销量", "downloads": "Steam未公开逐游戏下载量", "revenue_amount": "公开榜单不提供收入金额"},
        "methodology": [SCOPE_NOTE,
            "候选按4款热销、1款最近发行轮流检查，符合规则后截取最多60款；所有排名仅在这一发现样本内比较。",
            "近1/7/30天评价量按同一采集时点向前24/168/720小时，以评论创建时间统计；不是评论总数差值，也不是销量。",
            "期间好评率=期间好评数/期间评价量；无评价时不计算比例。全部语言、全部购买渠道，过滤Steam离题评论活动。",
            "当前热销为美国区Indie搜索榜顺位；全球榜位仅引用已核实全球来源的前100榜单，未入榜不视为0。",
            "实时热销按近24小时收入并加权最近3小时，不能解释成纯24小时销量榜。没有公开滚动7/30天销量或下载榜。",
            "商店资料缓存7天，本页数据每日采集、23小时内复用；失败保留旧值及原时间并标记过期，不把缺失写成0。",
            "小游戏是本页筛选口径，Indie和低价本身不证明制作规模；玩法标签包括休闲、解谜、平台跳跃、Roguelite、卡牌、放置等。"],
        "games": games,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data/indie_market.json")
    parser.add_argument("--global-market", type=Path, default=ROOT / "data/global_market.json")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--max-games", type=int, default=MAX_GAMES)
    parser.add_argument("--budget-seconds", type=int, default=420)
    args = parser.parse_args()
    result = build_indie_market(read_json(args.output, {}), read_json(args.global_market, {}), datetime.now(TZ),
                                args.refresh, args.workers, args.max_games, args.budget_seconds)
    write_json(args.output, result)
    print(f"Compact Steam sample: {result['coverage']['fresh_games']}/{len(result['games'])} fresh; status={result['status']}")


if __name__ == "__main__":
    main()
