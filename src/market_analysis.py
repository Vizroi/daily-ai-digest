"""Describe a cross-genre Steam sample without presenting it as a market census.

Only observed values are aggregated. Games are matched within each historical
comparison, zero is distinct from missing data, and discovery changes are never
treated as growth. This module has no network or filesystem side effects.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
import math
from statistics import median

TZ = timezone(timedelta(hours=8))
FRESH_HOURS = 30
MIN_TREND_GAMES = 3
MIN_TREND_COVERAGE = 0.6

# Gameplay/genre families only. Modes, visual style and themes are not ranked
# alongside mechanics; broad tags such as Action and Indie cannot identify one.
GAMEPLAY_GROUPS = (
    ("incremental", "增量 / 放置", ("Incremental", "Clicker", "Idler", "Idle")),
    ("automation", "自动化", ("Automation", "Programming")),
    ("deckbuilding", "牌组构筑", ("Deckbuilding", "Roguelike Deckbuilder")),
    ("cards", "卡牌对战", ("Card Battler", "Trading Card Game")),
    ("auto_battler", "自走棋 / 自动战斗", ("Auto Battler",)),
    ("survival", "生存", ("Survival", "Open World Survival Craft")),
    ("crafting", "采集 / 建造", ("Crafting", "Base Building", "Building")),
    ("city_builder", "城市建造", ("City Builder",)),
    ("colony_sim", "殖民地模拟", ("Colony Sim",)),
    ("management", "经营管理", ("Management", "Economy", "Capitalism")),
    ("life_sim", "生活模拟", ("Life Sim",)),
    ("farming", "农场模拟", ("Farming Sim", "Farming")),
    ("roguelike", "Roguelike", ("Roguelike", "Roguelite", "Action Roguelike", "Traditional Roguelike")),
    ("soulslike", "类魂", ("Souls-like", "Soulslike")),
    ("metroidvania", "银河城", ("Metroidvania",)),
    ("platformer", "平台跳跃", ("Platformer", "2D Platformer", "3D Platformer", "Precision Platformer")),
    ("fighting", "格斗", ("Fighting", "2D Fighter", "3D Fighter")),
    ("beat_em_up", "清版动作", ("Beat 'em up", "Beat'em up")),
    ("hack_slash", "砍杀", ("Hack and Slash",)),
    ("fps", "第一人称射击", ("FPS",)),
    ("third_person_shooter", "第三人称射击", ("Third-Person Shooter",)),
    ("tactical_shooter", "战术射击", ("Tactical Shooter",)),
    ("bullet_hell", "弹幕", ("Bullet Hell",)),
    ("shoot_em_up", "清版射击", ("Shoot 'Em Up", "Shoot 'em up")),
    ("turn_based", "回合制策略", ("Turn-Based Strategy", "Turn-Based Tactics", "Tactical RPG")),
    ("turn_based_rpg", "回合制 RPG", ("Turn-Based Combat",)),
    ("rts", "即时战略", ("RTS", "Real-Time Strategy")),
    ("moba", "MOBA", ("MOBA",)),
    ("mmorpg", "MMORPG", ("MMORPG",)),
    ("grand_strategy", "大战略 / 4X", ("Grand Strategy", "4X")),
    ("tower_defense", "塔防", ("Tower Defense",)),
    ("puzzle", "解谜", ("Puzzle", "Puzzle Platformer", "Logic", "Hidden Object")),
    ("narrative", "叙事冒险", ("Visual Novel", "Interactive Fiction", "Choose Your Own Adventure", "Point & Click")),
    ("sandbox", "沙盒", ("Sandbox",)),
    ("racing", "竞速", ("Racing", "Combat Racing")),
    ("sports", "体育", ("Sports", "Football (Soccer)", "Basketball", "Baseball")),
    ("stealth", "潜行", ("Stealth",)),
    ("rhythm", "音游", ("Rhythm",)),
    ("action_rpg", "动作 RPG", ("Action RPG",)),
)


def _time(value):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.astimezone(TZ) if result.tzinfo else None
    except (ValueError, TypeError):
        return None


def _date(value):
    try:
        return date.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def _fresh(status, timestamp, now):
    observed = _time(timestamp)
    return status == "fresh" and observed is not None and timedelta() <= now - observed <= timedelta(hours=FRESH_HOURS)


def _players(game, now):
    value = game.get("current_players")
    return value if _number(value) and _fresh(game.get("players_status"), game.get("players_observed_at"), now) else None


def _rank(game, now):
    value = game.get("top_sellers_rank")
    return int(value) if _number(value) and value >= 1 and value == int(value) and _fresh(
        game.get("top_sellers_status"), game.get("top_sellers_observed_at"), now) else None


def _release(game):
    # An explicit initial release takes precedence over a later 1.0 store date.
    return _date(game.get("first_release_date")) or _date(game.get("release_date"))


def _unverified_release(game):
    return game.get("release_date_status") == "first_release_unverified" or bool(
        game.get("early_access_transition") and not _date(game.get("first_release_date"))
        and game.get("release_date_basis") != "original_steam_release_date")


def _is_recent_release(game, now):
    released = _release(game)
    return not _unverified_release(game) and released is not None and 0 <= (now.date() - released).days <= 90


def _review(game, now):
    review = game.get("review_summary") or {}
    if not _fresh(review.get("status"), review.get("sampled_at"), now):
        return None
    total, positive, negative = (review.get(k) for k in ("total", "positive", "negative"))
    if not all(_number(v) and int(v) == v for v in (total, positive, negative)) or positive + negative != total:
        return None
    scope = review.get("scope")
    if not scope:
        # Old action snapshots include only English/Chinese; do not mix their
        # review totals with a new all-language global sample.
        languages = review.get("languages")
        if not languages:
            return None
        scope = "|".join(sorted(str(v) for v in languages)) + ":" + str(review.get("purchase_type", "unknown"))
    return {"total": int(total), "scope": scope}


def _game_sort(game, now, basis):
    rank, players = _rank(game, now), _players(game, now)
    return ((rank is None, rank or 10**9, -(players or 0), game["appid"]) if basis == "global_top_sellers"
            else (players is None, -(players or 0), game["appid"]))


def _matches_group(game, group_id, aliases):
    tags = {str(tag).casefold() for tag in game.get("tags", [])}
    if not tags.intersection(aliases):
        return False
    # JRPG/CRPG describe RPG families, not necessarily turn-based combat.
    if group_id == "turn_based_rpg":
        return bool(tags.intersection({"rpg", "jrpg", "crpg", "party-based rpg"}))
    return True


def _popularity(games, now, basis):
    observations = [(game, _players(game, now)) for game in games]
    observations = [(game, value) for game, value in observations if value is not None]
    total = sum(value for _, value in observations) if observations else None
    ranks = [_rank(game, now) for game in games]
    ranks = [value for value in ranks if value is not None]
    return {
        "basis": basis,
        "status": ("ready" if ranks else "unobserved") if basis == "global_top_sellers" else (
            "ready" if len(observations) == len(games) else "partial" if observations else "unobserved"),
        "current_players": total,
        "observed_count": len(observations),
        "top_seller_count": len(ranks),
        "best_rank": min(ranks) if ranks else None,
        "leader_share_percent": round(max(value for _, value in observations) / total * 100, 1) if total else None,
    }


def _valid_window(game, days, now):
    window = (game.get("windows") or {}).get(str(days), {})
    if window.get("status") not in ("ready", "no_baseline") or window.get("metric") != "sampled_players_mean":
        return None
    if window.get("required_days") != days or window.get("current_days") != days or window.get("previous_days") != days:
        return None
    expected = {"current_start": days, "current_end": 1, "previous_start": days * 2, "previous_end": days + 1}
    if any(window.get(key) != (now.date() - timedelta(days=offset)).isoformat() for key, offset in expected.items()):
        return None
    if not all(_number(window.get(key)) for key in ("current", "previous")):
        return None
    return window


def _trend(games, days, now):
    valid = [(game, _valid_window(game, days, now)) for game in games]
    valid = [(game, window) for game, window in valid if window is not None]
    coverage = len(valid) / len(games) if games else 0
    result = {
        "status": "insufficient_history", "signal": "insufficient_history",
        "reason": f"需至少 {MIN_TREND_GAMES} 款、覆盖该类样本至少 60% 的作品具有两个完整的 {days} 天窗口。",
        "sample_count": len(games), "valid_count": len(valid), "coverage_percent": round(coverage * 100, 1),
        "current": None, "previous": None, "absolute_change": None, "percent_change": None,
        "up_count": 0, "down_count": 0, "flat_count": 0,
        "positive_leader_share_percent": None, "without_leader_percent_change": None,
        "low_base": False, "representative_ids": [], "comparable_ids": [g["appid"] for g, _ in valid],
        "metric": "same_cohort_sampled_players_mean",
    }
    if len(valid) < MIN_TREND_GAMES or coverage < MIN_TREND_COVERAGE:
        return result
    current = sum(w["current"] for _, w in valid)
    previous = sum(w["previous"] for _, w in valid)
    differences = [(g, w, w["current"] - w["previous"]) for g, w in valid]
    positive = sorted((row for row in differences if row[2] > 0), key=lambda row: (-row[2], row[0]["appid"]))
    up, down = len(positive), sum(row[2] < 0 for row in differences)
    positive_total = sum(row[2] for row in positive)
    concentration = positive[0][2] / positive_total if positive_total else None
    ex_percent = None
    if positive:
        leader_previous, leader_current = positive[0][1]["previous"], positive[0][1]["current"]
        if previous > leader_previous:
            ex_percent = (current - leader_current - previous + leader_previous) / (previous - leader_previous) * 100
    percent = (current - previous) / previous * 100 if previous else None
    low_base = previous / len(valid) < 50
    result.update(
        status="ready" if previous else "no_baseline", current=round(current, 2), previous=round(previous, 2),
        absolute_change=round(current - previous, 2), percent_change=round(percent, 1) if percent is not None else None,
        up_count=up, down_count=down, flat_count=len(valid) - up - down,
        positive_leader_share_percent=round(concentration * 100, 1) if concentration is not None else None,
        without_leader_percent_change=round(ex_percent, 1) if ex_percent is not None else None,
        low_base=low_base, representative_ids=[g["appid"] for g, _, _ in positive[:3]],
    )
    if not previous:
        result.update(signal="no_baseline", reason="此前窗口合计为 0，不计算百分比或升温结论。")
    elif low_base:
        result.update(signal="low_base", reason="此前每款作品的平均在线基数不足 50；保留绝对变化，不列入升温方向。")
    elif current <= previous:
        result.update(signal="declining" if current < previous else "flat", reason="同一批作品的在线采样均值合计未增长。")
    elif concentration is not None and concentration > 0.6:
        result.update(signal="concentrated", reason="单款作品贡献超过 60% 的正向增量，暂不判断整个方向升温。")
    elif percent >= 5 and up >= max(3, math.ceil(len(valid) * 0.6)) and ex_percent is not None and ex_percent > 0:
        result.update(signal="broad_growth", reason=f"同批样本合计增长 {percent:.1f}%；{up}/{len(valid)} 款增长，去掉最大增量作品后仍增长。")
    else:
        result.update(signal="mixed", reason="存在增长，但增长幅度或上涨作品覆盖尚不足以判断整个方向升温。")
    return result


def _new_releases(games, now):
    recent = [(game, (now.date() - _release(game)).days) for game in games if _is_recent_release(game, now)]
    buckets = []
    for key, label, low, high in (("0_7", "商店日期距今 0–7 天", 0, 7), ("8_30", "商店日期距今 8–30 天", 8, 30), ("31_90", "商店日期距今 31–90 天", 31, 90)):
        cohort = [(game, age) for game, age in recent if low <= age <= high]
        reviews = [_review(game, now) for game, _ in cohort]
        reviews = [review for review in reviews if review is not None]
        scopes = Counter(review["scope"] for review in reviews)
        comparable = len(scopes) == 1 and len(reviews) >= 3 and len(reviews) >= len(cohort) * 0.6
        buckets.append({
            "id": key, "label": label, "count": len(cohort), "game_ids": [game["appid"] for game, _ in cohort],
            "reviewed_count": len(reviews), "median_reviews": median(r["total"] for r in reviews) if comparable else None,
            "review_scope": next(iter(scopes)) if len(scopes) == 1 else None,
            "age_min": min((age for _, age in cohort), default=None), "age_max": max((age for _, age in cohort), default=None),
        })
    return {
        "sample_count": len(recent), "game_ids": [game["appid"] for game, _ in sorted(recent, key=lambda row: (row[1], row[0]["appid"]))],
        "excluded_uncertain_count": sum(_unverified_release(game) for game in games),
        "age_buckets": buckets, "reviewed_count": sum(b["reviewed_count"] for b in buckets), "median_reviews": None,
        "metric_note": "按商店标注发售日期分龄；首次发售时间未核实的抢先体验转正式作品不进入新作统计。评论为截至采集时的累计量，不是发售首 7/30 天表现、销量或成功率。",
    }


def build_global_analysis(data, now=None):
    """Return JSON-safe groups and ranked views for a global-market renderer.

    Each ``group`` has id/label, all ``game_ids``, ``representative_ids``,
    ``ordinary_ids``, sample_count, popularity, windows['1'/'7'/'30'], and
    new_releases (90-day sample, separate 0-7/8-30/31-90-day buckets).
    ``popular`` is ordered by verified fresh global bestseller representation,
    falling back explicitly to observed concurrent players. ``rising`` includes
    only sufficiently covered, non-concentrated growth in matched cohorts.
    ``new_releases`` is ordered by sample counts, never by inferred success.
    All views contain the same group objects, not game-level ranking objects.

    Freshness is relative to the snapshot's generated_at; optional aware ``now``
    lets callers invalidate a stale snapshot. No absent observation becomes 0.
    """
    now = now or _time(data.get("generated_at")) or datetime.now(TZ)
    now = now.astimezone(TZ)
    games, seen, excluded = [], set(), Counter()
    for game in data.get("games", []):
        appid = game.get("appid")
        if not isinstance(appid, int) or isinstance(appid, bool) or appid <= 0 or appid in seen:
            excluded["invalid_or_duplicate"] += 1
            continue
        seen.add(appid)
        release = _release(game)
        if game.get("is_demo") or game.get("type") not in (None, 0, "game") or game.get("app_type") not in (None, "game"):
            excluded["not_full_game"] += 1
        elif game.get("coming_soon") or (release and release > now.date()):
            excluded["unreleased"] += 1
        elif release is None:
            excluded["unknown_release"] += 1
        else:
            games.append(game)
    ranked_count = sum(_rank(game, now) is not None for game in games)
    basis = "global_top_sellers" if ranked_count else "sample_current_players"
    basis_info = {
        "id": basis,
        "label": "全球热销榜入榜作品数" if ranked_count else "样本当前在线合计",
        "note": "按已采集的全球热销榜中各类入榜作品数量排序，同数时按最高名次；不是收入份额。" if ranked_count else "未取得可核验的当期全球热销榜，暂按有新鲜在线数据的样本合计排序；不是销量或市场份额。",
    }
    groups = []
    assigned = set()
    for group_id, label, aliases in GAMEPLAY_GROUPS:
        normalized = {tag.casefold() for tag in aliases}
        members = [game for game in games if _matches_group(game, group_id, normalized)]
        if not members:
            continue
        members.sort(key=lambda game: _game_sort(game, now, basis))
        assigned.update(game["appid"] for game in members)
        known = [game for game in members if _players(game, now) is not None]
        ordinary = sorted(known, key=lambda game: (_players(game, now), game["appid"]))
        groups.append({
            "id": group_id, "label": label, "sample_count": len(members), "game_ids": [g["appid"] for g in members],
            "commercial_models": {
                "free": sum(g.get("is_free") is True for g in members),
                "paid": sum(g.get("is_free") is False for g in members),
                "unknown": sum(not isinstance(g.get("is_free"), bool) for g in members),
            },
            "representative_ids": [g["appid"] for g in members[:3]],
            "ordinary_ids": [g["appid"] for g in ordinary[:3]],
            "popularity": _popularity(members, now, basis),
            "windows": {str(days): _trend(members, days, now) for days in (1, 7, 30)},
            "new_releases": _new_releases(members, now),
        })
    popular = [g for g in groups if (g["popularity"]["top_seller_count"] > 0 if ranked_count else g["popularity"]["observed_count"] > 0)]
    popular.sort(key=lambda g: (-g["popularity"]["top_seller_count"], g["popularity"]["best_rank"] or 10**9, g["id"]) if ranked_count else (
        -g["popularity"]["current_players"], -g["popularity"]["observed_count"], g["id"]))
    rising = {}
    for days in (1, 7, 30):
        key = str(days)
        rising[key] = sorted((g for g in groups if g["windows"][key]["signal"] == "broad_growth"),
                             key=lambda g: (-g["windows"][key]["absolute_change"], -g["windows"][key]["percent_change"], g["id"]))
    new = sorted((g for g in groups if g["new_releases"]["sample_count"]), key=lambda g: (-g["new_releases"]["sample_count"], g["id"]))
    fresh_count = sum(_players(game, now) is not None for game in games)
    recent_count = sum(_is_recent_release(g, now) for g in games)
    uncertain_release_count = sum(_unverified_release(g) for g in games)
    summary = [f"本次收录 {len(games)} 款已发售游戏，{fresh_count} 款有新鲜在线数据，覆盖 {len(groups)} 个玩法分类；其中 {recent_count} 款的商店发售日期在近 90 天。"]
    if popular:
        top = popular[:3]
        if ranked_count:
            details = "、".join(f"{g['label']} {g['popularity']['top_seller_count']} 款" for g in top)
            summary.append(f"在已采集的 {ranked_count} 款全球热销榜作品中，入榜作品较多的分类为：{details}。标签可重叠。")
        else:
            details = "、".join(f"{g['label']} {g['popularity']['current_players']:,} 人" for g in top)
            summary.append(f"当前样本在线合计较高的分类为：{details}；在线人数不能换算为销量。")
    comparable = sum(g["windows"]["7"]["status"] in ("ready", "no_baseline") for g in groups)
    if rising["7"]:
        summary.append("近 7 天有多款作品共同增长的分类：" + "、".join(g["label"] for g in rising["7"][:3]) + "；依据为同批作品在线采样均值。")
    elif comparable:
        summary.append(f"{comparable} 个分类具备足够的 7 天对比样本，目前没有分类同时达到增长幅度、上涨覆盖及集中度条件。")
    else:
        summary.append("目前尚无分类具备足够的两个完整 7 天窗口，暂不判断哪些方向正在升温。")
    coverage = dict(data.get("coverage") or {})
    coverage.update(total_games=len(games), input_games=len(data.get("games", [])), fresh_games=fresh_count,
                    classified_games=len(assigned), unclassified_games=len(games) - len(assigned), gameplay_groups=len(groups),
                    top_seller_games=ranked_count, recent_games=recent_count,
                    unverified_release_games=uncertain_release_count, excluded=dict(excluded))
    return {
        "generated_at": data.get("generated_at"), "coverage": coverage, "summary": summary, "popularity_basis": basis_info,
        "groups": groups, "popular": popular, "rising": rising, "new_releases": new,
        "methodology": [
            "跨类型样本包含动作游戏；不是 Steam 全量普查。分类可重叠，分类计数或在线合计不可相加为市场总量。",
            "热门排序使用可核验的全球热销榜入榜作品数；无有效榜单时明确改用样本在线合计。免费、付费游戏均可能入榜，不由在线人数推算收入。",
            "1/7/30 天均比较此前两个同长完整日窗口；只对同一批拥有完整历史的作品求和，新增收录不计为增长。",
            "升温需至少 3 款、覆盖分类样本至少 60%；合计增长至少 5%，至少 3 款且 60% 的可比作品增长，最大作品不超过正向增量的 60%，移除后仍增长。",
            "此前每款平均基数不足 50 人时不列入升温；缺失、过期或未来时间的观测不作为 0。",
            "新作按商店发售日期分龄；累计评论仅描述当前反馈量，不代表同龄首月销量、成功率或 ROI。未接入销量与收入估算。",
            f"{uncertain_release_count} 款已知由抢先体验转正式发售、但首次发售时间未核实的作品保留在市场观察中，排除出新作数量与分龄统计。",
        ],
    }
