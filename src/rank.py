"""游戏与 AI 分页筛选；各自保留快讯和正文精选。"""
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
import config
from cluster import canonical_url, _event_key

TZ = timezone(timedelta(hours=8))
SECTIONS = ("news", "features", "ai", "ai_features")
TOPICS = {
    "战斗设计": ["combat", "战斗", "打击感", "boss", "招式"],
    "关卡设计": ["level design", "关卡", "open world", "开放世界", "blockout"],
    "系统设计": ["game design", "mechanic", "system design", "系统设计", "机制", "构筑", "数值"],
    "玩家体验": ["onboarding", "accessibility", "player experience", "玩家体验", "引导", "无障碍"],
    "开发动态": ["engine", "unreal", "unity", "godot", "开发工具", "制作流程", "原型"],
    "行业动态": ["acquisition", "layoff", "sales", "裁员", "收购", "销量", "市场"],
}
ANALYSIS = ["postmortem", "design decisions", "designing", "lessons", "interview", "behind the",
            "how we", "复盘", "拆解", "分析", "设计思路", "专访", "访谈", "经验", "设计方法"]
NOISE = ["抽奖", "优惠码", "购买指南", "招聘", "求助", "首席营销官", "出任首席", "广告变现",
         "help me", "how do i", "hiring", "giveaway", "chief marketing officer"]
GAME_CHANGES = ["dlc", "patch", "expansion", "early access", "demo", "gameplay", "试玩", "版本", "更新", "新作", "玩法", "关卡"]
AI_USEFUL = ["release", "launch", "introduc", "available", "workflow", "tool", "coding", "agent",
             "发布", "上线", "开放", "编程", "工具", "工作流", "原型", "研究", "更新"]
AI_ANALYSIS = ["case study", "tutorial", "guide", "evaluation", "evaluating", "benchmark",
               "how to", "how we", "lessons", "workflow", "deep dive", "explained",
               "复盘", "拆解", "分析", "实测", "评测", "教程", "实践", "工作流", "方法", "经验"]


def parse_date(value):
    if not value:
        return None
    try:
        date = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return date.replace(tzinfo=timezone.utc) if date.tzinfo is None else date
    except (ValueError, TypeError):
        return None


def relevant_text(event):
    return f"{event.get('title', '')} {event.get('summary_raw', '')}".lower()


def match_relevant(text):
    return [word for words in TOPICS.values() for word in words if word in text.lower()]


def event_urls(event):
    return {canonical_url(url) for url in [event.get("url")] +
            [m.get("url") for m in event.get("members", [])] if url}


def load_memory(path, now):
    try:
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
        cutoff = (now - timedelta(days=config.MEMORY_DAYS)).strftime("%Y-%m-%d")
        return {k: v for k, v in raw.items() if v.get("last_seen", "") >= cutoff}
    except (OSError, ValueError):
        return {}


def save_memory(path, memory, published, today):
    for event in published:
        old = memory.get(event["key"], {"first_seen": today, "times": 0})
        if old.get("last_seen") != today:
            old["times"] = old.get("times", 0) + 1
        old.update(title=event["title"], last_seen=today,
                   urls=sorted(set(old.get("urls", [])) | event_urls(event)))
        memory[event["key"]] = old
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(memory, handle, ensure_ascii=False, indent=2)


def score_event(event, memory, now):
    text = relevant_text(event)
    category = event.get("category", "games")
    published = parse_date(event.get("published"))
    hours = (now - published).total_seconds() / 3600 if published else None
    analysis_words = list(getattr(config, "ANALYSIS_KEYWORDS", [])) + ANALYSIS
    analysis = category == "design" or any(word.lower() in event.get("title", "").lower() for word in analysis_words)
    topic = next((name for name, words in TOPICS.items() if any(w in text for w in words)),
                 "开发动态" if category == "development" else "产品观察" if analysis else "新游动态")
    parts = [{"label": "来源", "value": {1: 18, 2: 12, 3: 2}.get(event.get("tier", 2), 2)},
             {"label": "游戏与玩法变化", "value": 8 if category != "ai" and any(word in event.get("title", "").lower() for word in GAME_CHANGES) else 0},
             {"label": "近期", "value": 10 if hours is not None and 0 <= hours <= 24 else 5 if hours is not None and 0 <= hours <= 72 else 0},
             {"label": "分析与方法", "value": 12 if analysis else 0},
             {"label": "多源", "value": min(max(event.get("coverage", 1) - 1, 0), 2) * 3}]
    event.update(score=sum(p["value"] for p in parts), score_parts=parts,
                 topic=topic, is_analysis=analysis, age_hours=hours,
                 evergreen=bool(event.get("library") or event.get("classic_discovery")),
                 content_type="经典阅读" if event.get("library") or event.get("classic_discovery") else "分析" if analysis else "新闻")
    return event


def diverse_pick(events, limit, max_per_source=3):
    """Quality ordering with a source cap; no forced 50/50 language quota."""
    if limit <= 0:
        return []
    picked, counts, platforms = [], {}, {}
    for event in sorted(events, key=lambda e: (e["score"], e.get("published") or ""), reverse=True):
        source = (event.get("sources") or [""])[0]
        platform = event.get("platform", "")
        if counts.get(source, 0) >= max_per_source:
            continue
        if platforms.get(platform, 0) >= config.PLATFORM_CAPS.get(platform, limit):
            continue
        picked.append(event)
        counts[source] = counts.get(source, 0) + 1
        platforms[platform] = platforms.get(platform, 0) + 1
        if len(picked) >= limit:
            break
    return picked


def build_digest(events, memory, now):
    today = now.astimezone(TZ).strftime("%Y-%m-%d")
    # Re-running today's issue is idempotent; prior days' published links are excluded.
    previous = {k: v for k, v in memory.items() if v.get("last_seen") != today}
    reported_urls = {u for value in previous.values() for u in value.get("urls", [])}
    candidates, review_queue, seen_urls, seen_keys = [], [], set(), set()
    for source_event in events:
        event = dict(source_event)
        if event.get("publication_scope", "public") != "public":
            continue
        urls = event_urls(event)
        if (event["key"] in previous or urls & reported_urls or urls & seen_urls
                or event["key"] in seen_keys):
            continue
        score_event(event, memory, now)
        if event["age_hours"] is not None and event["age_hours"] < 0:
            continue
        reason = None
        community = event.get("requires_review") or str(event.get("evidence_kind", "")).startswith("community")
        title = event.get("title", "").lower()
        if community and (re.search(r"\b(?:how|what|where|which) (?:can|could|should|do) i\b|\bhelp me\b", title)
                          or any(word in title for word in ("求助", "请问", "求推荐"))):
            event["is_question"] = True
        if event.get("requires_transcript") or event.get("discovery_only"):
            reason = "待字幕或正文核验" if event.get("requires_transcript") else "待核验公开原文"
        elif event.get("is_question"):
            reason = "社区提问，尚不能作为分析结论"
        elif event.get("requires_review") or event.get("tier", 2) > 2:
            text = event.get("body") or event.get("rss_content") or ""
            reviewable = (event.get("platform") != "discord" and event.get("is_analysis")
                          and len(text) >= 500 and (event.get("has_body")
                          or event.get("content_kind") == "community_selftext"))
            if not event.get("reviewed") and not reviewable:
                reason = "社区线索待核验正文与上下文"
        if reason:
            review_queue.append({key: event.get(key) for key in
                                 ("key", "title", "url", "sources", "source_id", "platform", "published",
                                  "original_url", "discovery_url", "evidence_kind", "content_kind", "is_question")}
                                | {"reason": reason})
            continue
        if any(word in relevant_text(event) for word in NOISE):
            continue
        candidates.append(event)
        seen_urls |= urls
        seen_keys.add(event["key"])

    game = [e for e in candidates if e.get("category", "games") in {"games", "design", "development"}]
    feature_pool = [e for e in game if e["is_analysis"] and
                    (e.get("category") == "design" or e.get("library")
                     or len(e.get("summary_raw", "")) >= 80 or e.get("rss_content"))]
    features = diverse_pick([e for e in feature_pool if not e.get("library")], config.FEATURES_MAX, 1)
    if len(features) < config.FEATURES_MAX:
        features.extend(diverse_pick([e for e in feature_pool if e.get("library")],
                                     config.FEATURES_MAX - len(features), 1))
    used = {e["key"] for e in features}
    reserves = diverse_pick([e for e in feature_pool if e["key"] not in used], config.FEATURES_MAX, 1)
    used.update(e["key"] for e in reserves)
    news = diverse_pick([e for e in game if e["key"] not in used and not e.get("library")
                         and not e.get("undated") and e["age_hours"] is not None
                         and 0 <= e["age_hours"] <= config.FRESH_WINDOW_HOURS], config.NEWS_MAX)
    ai_pool = [e for e in candidates if e.get("category") == "ai"]
    ai_feature_pool = [e for e in ai_pool
                       if (e["is_analysis"] or any(word in e.get("title", "").lower() for word in AI_ANALYSIS))
                       and (e.get("has_body") or e.get("rss_content") or len(e.get("summary_raw", "")) >= 80)
                       and (e.get("library") or (e["age_hours"] is not None
                            and 0 <= e["age_hours"] <= config.AI_FEATURE_WINDOW_HOURS))]
    ai_features = diverse_pick(ai_feature_pool, config.AI_FEATURES_MAX, 1)
    ai_used = {e["key"] for e in ai_features}
    ai_reserves = diverse_pick([e for e in ai_feature_pool if e["key"] not in ai_used],
                              config.AI_FEATURES_MAX, 1)
    ai_used.update(e["key"] for e in ai_reserves)
    # The AI page has its own quota, even on days with no selected game news.
    ai = diverse_pick([e for e in ai_pool if e["key"] not in ai_used
                       and not e.get("undated") and e["age_hours"] is not None
                       and 0 <= e["age_hours"] <= config.FRESH_WINDOW_HOURS
                       and any(word in relevant_text(e) for word in AI_USEFUL)], config.AI_MAX, 2)
    for name, entries in (("news", news), ("features", features), ("ai", ai), ("ai_features", ai_features)):
        for entry in entries:
            entry["section"] = name
    return {"schema_version": 3, "date": today, "generated_at": now.astimezone(TZ).isoformat(),
            "news": news, "features": features, "feature_candidates": reserves, "ai": ai,
            "ai_features": ai_features, "ai_feature_candidates": ai_reserves,
            "review_queue": review_queue,
            "stats": {"events": len(events), "news": len(news), "features": len(features), "ai": len(ai),
                      "ai_features": len(ai_features),
                      "review_candidates": len(review_queue),
                      "multi_source": sum(e.get("coverage", 1) > 1 for e in news + features + ai + ai_features)}}


def load_library(path):
    try:
        with open(path, encoding="utf-8") as handle:
            entries = json.load(handle)
    except OSError:
        return []
    for entry in entries:
        entry.update(key=_event_key(entry["title"]), pool="main", category=entry.get("category", "design"), library=True,
                     coverage=1, tier=1, tier_weight=18, undated=not bool(entry.get("published")))
    return entries


def main():
    inp = sys.argv[1] if len(sys.argv) > 1 else "data/events.json"
    out = sys.argv[2] if len(sys.argv) > 2 else "data/ranked.json"
    mem_path = sys.argv[3] if len(sys.argv) > 3 else "data/memory.json"
    with open(inp, encoding="utf-8") as handle:
        events = json.load(handle)
    events += load_library(os.path.join(os.path.dirname(__file__), "..", "data", "reading_library.json"))
    now = datetime.now(timezone.utc)
    digest = build_digest(events, load_memory(mem_path, now.astimezone(TZ)), now)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(digest, handle, ensure_ascii=False, indent=2)
    queue_path = os.path.join(os.path.dirname(os.path.abspath(out)), "review_queue.json")
    with open(queue_path, "w", encoding="utf-8") as handle:
        json.dump(digest["review_queue"], handle, ensure_ascii=False, indent=2)
    print(f"[OK] 日报 {len(digest['news'])} · 精选 {len(digest['features'])} · AI 快讯 {len(digest['ai'])} · AI 精选 {len(digest['ai_features'])} → {out}")


if __name__ == "__main__":
    main()
