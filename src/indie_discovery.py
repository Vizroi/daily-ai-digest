"""Observe upcoming store pages and genuinely recent releases separately.

Steam does not expose a verified store-page publication date. The initial
upcoming snapshot is a baseline; subsequent first observations are discoveries,
not claims about when a developer made a store page public.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta
from html import unescape
from pathlib import Path
import re
import time

from global_market import METADATA_FIELDS, fetch_metadata, preserve_earlier_release
from indie_market import COMPACT_TAGS, ERRORS, RankedSearchRows, eligible
from steam_market import ROOT, STORE, TZ, parse_release, parse_time, read_json, recent, request_json, safe_error, stamp, write_json

SOURCES = [
    {"id": "upcoming", "name": "Steam 独立游戏待发售入口", "url": STORE + "/search/?filter=comingsoon&tags=492&category1=998&cc=us&l=english&ignore_preferences=1",
     "note": "未登录美国区 Indie 待发售入口前300条，按相关性发现；不是按上架日期排序。", "max_pages": 3},
    {"id": "releases", "name": "Steam 独立游戏最近发行入口", "url": STORE + "/search/?sort_by=Released_DESC&tags=492&category1=998&cc=us&l=english&ignore_preferences=1",
     "note": "发行日期倒序，最多1000条；能确认已跨30天则提前结束。可能无法覆盖全部30天作品。", "max_pages": 10},
]
SCOPE = ("Steam 美国区 Indie 候选样本：待发售入口最多300条、发行日期倒序入口最多1000条，"
         "以休闲、解谜、Roguelike、卡牌、平台动作等标签筛选；已发售要求免费或原价不超过25美元，"
         "待发售允许价格尚未公布。排除DLC、软件和Demo；不代表全部小游戏或已核实制作规模。")


def fetch_source(definition, now, deadline):
    rows, seen, dates, total, complete, stopped = [], set(), [], None, False, False
    cutoff = (now.date() - timedelta(days=29)).isoformat()
    for page in range(definition["max_pages"]):
        if time.monotonic() >= deadline:
            stopped = True
            break
        params = {"start": page * 100, "count": 100, "tags": "492", "category1": 998,
                  "infinite": 1, "cc": "us", "l": "english", "ignore_preferences": 1}
        if definition["id"] == "upcoming":
            params["filter"] = "comingsoon"
        else:
            params["sort_by"] = "Released_DESC"
        try:
            result = request_json(STORE + "/search/results/", params)
        except ERRORS:
            if not rows:
                raise
            stopped = True
            break
        if result.get("success") != 1 or not isinstance(result.get("results_html"), str):
            raise ValueError("search unavailable")
        parser = RankedSearchRows()
        parser.feed(result["results_html"])
        if not parser.rows:
            if result.get("total_count") == 0 or rows:
                complete = True
                break
            raise ValueError("search returned no verified games")
        total = result.get("total_count")
        for item in parser.rows:
            if item["appid"] not in seen:
                seen.add(item["appid"])
                rows.append({"appid": item["appid"], "rank": page * 100 + item["rank"]})
        release_labels = re.findall(r'<div[^>]*class="[^"]*search_released[^\"]*"[^>]*>(.*?)</div>', result["results_html"], re.S)
        page_dates = [parse_release(unescape(re.sub(r"<[^>]*>", "", text)).strip()) for text in release_labels]
        dates.extend(d for d in page_dates if d)
        if definition["id"] == "releases" and page_dates and all(page_dates) and max(page_dates) < cutoff:
            complete = True
            break
        if isinstance(total, int) and (page + 1) * 100 >= total:
            complete = True
            break
    return dict(definition, items=rows, observed_at=stamp(now), status="partial" if stopped else "fresh",
                discovered_count=len(rows), total_count=total, scan_complete=complete,
                oldest_scanned_date=min(dates) if dates else None)


def upcoming_eligible(meta):
    return bool(meta.get("app_type") == "game" and meta.get("coming_soon") and
                not meta.get("is_demo") and set(meta.get("tags", [])) & COMPACT_TAGS)


def recent_release(meta, now):
    day = parse_release(meta.get("release_date"))
    if not day or meta.get("release_date_status") == "first_release_unverified":
        return False
    return (now.date() - timedelta(days=29)).isoformat() <= day <= now.date().isoformat() and eligible(meta, now, True)


def build_discovery(previous, global_market, indie_market, now, refresh=False, budget_seconds=180):
    now = now.astimezone(TZ).replace(microsecond=0)
    if not refresh and previous.get("status") == "fresh" and recent(previous.get("generated_at"), now):
        return deepcopy(previous)
    deadline = time.monotonic() + max(0, budget_seconds)
    prior_sources = {s["id"]: s for s in previous.get("discovery", [])}
    sources, errors = [], []
    for definition in SOURCES:
        try:
            old_source = prior_sources.get(definition["id"], {})
            if not refresh and old_source.get("status") == "fresh" and recent(old_source.get("observed_at"), now):
                source = deepcopy(old_source)
            else:
                source = fetch_source(definition, now, deadline)
        except ERRORS as exc:
            source = deepcopy(prior_sources.get(definition["id"], definition))
            source.update(status="stale" if source.get("observed_at") else "unavailable", error=safe_error(exc))
            source.setdefault("items", [])
            errors.append(definition["name"] + ": " + safe_error(exc))
        sources.append(source)
    previous_games = {g["appid"]: g for g in previous.get("upcoming_games", []) + previous.get("release_games", [])}
    shared = {g["appid"]: g for g in global_market.get("games", []) + indie_market.get("games", [])}
    initialized = previous.get("initialized_at")
    seen = deepcopy(previous.get("seen_upcoming", {}))
    upcoming_source = next(s for s in sources if s["id"] == "upcoming")
    if upcoming_source["status"] == "fresh" and upcoming_source.get("items"):
        baseline = not initialized
        for row in upcoming_source["items"]:
            seen.setdefault(str(row["appid"]), {"first_seen_at": stamp(now), "listing_basis": "baseline" if baseline else "first_observed"})
        initialized = initialized or stamp(now)
    ids = list(dict.fromkeys([row["appid"] for s in sources for row in s.get("items", [])] + list(previous_games)))
    # Refresh release state every day: a coming-soon page may launch today.
    metadata, rejected, meta_errors = fetch_metadata(ids, now, deadline)
    errors.extend(meta_errors)
    unresolved = set(ids) - set(metadata) - rejected
    if unresolved:
        errors.append(f"{len(unresolved)}款商店资料未取得，保留原记录并等待下轮重试")
    upcoming, releases = [], []
    for appid in ids:
        if appid in rejected:
            continue
        old = previous_games.get(appid) or shared.get(appid, {})
        meta = metadata.get(appid)
        if meta:
            meta = preserve_earlier_release(deepcopy(meta), old)
        elif old:
            meta = {k: deepcopy(v) for k, v in old.items() if k in METADATA_FIELDS}
            meta["metadata_status"] = "stale"
        else:
            continue
        game = dict(meta, appid=appid, store_url=STORE + f"/app/{appid}/")
        observation = seen.get(str(appid))
        if upcoming_eligible(game) and observation:
            game.update(observation)
            upcoming.append(game)
        elif recent_release(game, now):
            releases.append(game)
    upcoming.sort(key=lambda g: (g.get("first_seen_at", ""), g["appid"]), reverse=True)
    releases.sort(key=lambda g: (g.get("release_date", ""), g["appid"]), reverse=True)
    # Keep IDs permanently to avoid relabeling re-entry into a bounded roster as new.
    status = "fresh" if all(s["status"] == "fresh" for s in sources) and not errors else "partial"
    return {"schema_version": 1, "generated_at": stamp(now), "initialized_at": initialized,
            "status": status, "scope_note": SCOPE, "discovery": sources, "errors": errors,
            "sources": [{k: v for k, v in s.items() if k != "items"} for s in sources],
            "seen_upcoming": seen, "upcoming_games": upcoming, "release_games": releases,
            "coverage": {"upcoming": len(upcoming), "releases": len(releases), "metadata_requested": len(ids),
                         "metadata_fresh": len(metadata), "new_observations": sum(g["listing_basis"] == "first_observed" for g in upcoming)},
            "methodology": [
                "Steam公开资料未提供可核实的商店首次上架时间。首次发现时间不等于实际上架时间，可能因搜索顺位变化而首次进入样本。",
                "第一次完整待发售快照建立基线，不计入近1/7/30天新增；之后首次进入观察范围的待发售作品才计为本站新发现。",
                "待发售与已发售按商店状态分开。发售窗口按北京时间自然日计算：近1天为采集当天，近7天含当天及此前6天，近30天含当天及此前29天。",
                "最近发售优先使用首次可玩发售日期，含抢先体验首次发售；已知抢先体验转正式而首次日期不明的作品不计入最近发售。",
                "每天更新一次、完整快照缓存23小时；来源失败保留旧数据及原时间，旧资料不计入当前新增或新发售筛选。",
                "近期发售入口有条数上限，可能在覆盖30天之前达到上限。页面展示所采到的样本，不宣称全库完整。"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data/indie_discovery.json")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--budget-seconds", type=int, default=180)
    args = parser.parse_args()
    data = build_discovery(read_json(args.output, {}), read_json(ROOT / "data/global_market.json", {}),
                           read_json(ROOT / "data/indie_market.json", {}), datetime.now(TZ), args.refresh, args.budget_seconds)
    write_json(args.output, data)
    print(f"Indie discovery: {len(data['upcoming_games'])} upcoming, {len(data['release_games'])} recent releases; {data['status']}")
    print("Sources:", [(s["id"], s["status"], s.get("discovered_count")) for s in data["sources"]])


if __name__ == "__main__":
    main()
