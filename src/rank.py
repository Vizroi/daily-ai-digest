"""阶段③打分排序：可解释、可复现、免费。

为什么不让 LLM 决定重要性：
  它没有全局视野（批处理时只能看到 10 条），而且结果不可复现、不可调试。
  v1 的「今日精选」就是这么坏掉的：BATCH_SIZE=10 配「最多选 5 篇」
  = 100 篇能选出 50 篇「精选」。

这里的分数会直接显示在页面上，附带评分依据。
排序逻辑可见 = 排序逻辑可被质疑和调整。
"""
import json
import math
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    RELEVANT_KEYWORDS, RELEVANT_BONUS, COMBAT_KEYWORDS, COMBAT_BONUS,
    DEEP_READ_TOP, DEEP_READ_RELEVANT,
    DEEP_READ_MIN_SCORE, MAX_PAPERS, MAX_REPOS, MAX_DIVERSE, MAX_GRAPHICS,
    MEMORY_DAYS, REPEAT_PENALTY,
    COVERAGE_WEIGHT, HN_FACTOR, HF_FACTOR, STAR_FACTOR,
    HN_FRONTPAGE, HN_FRONTPAGE_BONUS,
)

TZ = timezone(timedelta(hours=8))
COMBAT_SET = frozenset(COMBAT_KEYWORDS)


def match_relevant(text: str) -> list[str]:
    """返回命中的相关词。命中不叠加计分，但全部展示（让人看到为什么被选中）。

    返回顺序沿用 RELEVANT_KEYWORDS 的顺序，而战斗词排在词表最前，
    所以 hits[0] 永远优先是战斗词 —— 页面徽章显示的就是它。
    """
    low = text.lower()
    return [kw for kw in RELEVANT_KEYWORDS if kw in low]


def relevant_text(ev: dict) -> str:
    """决定拿什么文本去撞关键词表。

    tier3（聚合/社区源）只看标题，不看正文 —— 这是「宁缺毋滥」。
    实测 2026-08-04：r/unrealengine 的求助帖正文里随口提一句 "unreal university
    video"，就能拿满 +20 分挤进「能用上的」，而它对读者没有任何增量。
    标题是发帖人自己做的主题声明，正文只是上下文；用正文匹配等于让「提到过」
    冒充「讲的是」。
    一手源和分析源保留正文匹配：它们的标题常是市场化措辞，
    真正的技术关键词往往在正文里（例如 NVIDIA 博客标题不提 Nanite）。
    """
    if ev.get("tier", 2) >= 3:
        return ev.get("title", "")
    return f"{ev.get('title', '')} {ev.get('summary_raw', '')}"


def score_event(ev: dict, memory: dict, now: datetime) -> dict:
    sig = ev.get("signals", {})
    parts = []

    # ① 跨源覆盖 —— 最强信号。多家独立报道同一件事，说明它真的发生了且重要。
    cov = min(ev.get("coverage", 1), 5)
    cov_score = cov * COVERAGE_WEIGHT
    if ev.get("coverage", 1) > 1:
        parts.append((f"{ev['coverage']} 源报道", cov_score))
    else:
        parts.append(("单源", cov_score))

    # ② 源权威档位
    tw = ev.get("tier_weight", 2)
    tier_name = {18: "一手源", 8: "分析源", 2: "聚合源"}.get(tw, "源")
    parts.append((tier_name, tw))

    # ③ 社区热度
    hn = sig.get("hn_points", 0)
    if hn:
        s = math.log1p(hn) * HN_FACTOR
        parts.append((f"HN {hn}", s))
        if hn >= HN_FRONTPAGE:
            parts.append(("HN 头条", HN_FRONTPAGE_BONUS))
    hf = sig.get("hf_upvotes", 0)
    if hf:
        s = math.log1p(hf) * HF_FACTOR
        parts.append((f"HF ▲{hf}", s))
    st = sig.get("stars_today", 0)
    if st:
        s = math.log1p(st) * STAR_FACTOR
        parts.append((f"+{st}★/日", s))
    rb = sig.get("rank_bonus", 0.0)
    if rb:
        parts.append(("社区置顶", rb))

    # ④ 个人相关度 —— 「能用上的」栏目的唯一机制。
    #    战斗策划核心词给 32 分而不是 20：栏目内部按分数排序，
    #    这个差额保证「战斗手感/GAS/帧数据」类条目排在「引擎版本更新」之前。
    hits = match_relevant(relevant_text(ev))
    is_combat = any(h in COMBAT_SET for h in hits)
    if hits:
        bonus = COMBAT_BONUS if is_combat else RELEVANT_BONUS
        label = f"战斗「{hits[0]}」" if is_combat else f"命中「{hits[0]}」"
        parts.append((label, bonus))

    # ⑤ 新颖度惩罚：14 天内报过 → 扣分，但标记为后续追踪
    followup = None
    mem = memory.get(ev["key"])
    if mem:
        parts.append(("已报过", -REPEAT_PENALTY))
        followup = mem

    # ⑥ 无时间戳轻微扣分（无法确认新鲜度）
    if ev.get("undated"):
        parts.append(("无日期", -4))

    total = sum(v for _, v in parts)

    ev["score"] = round(total, 1)
    ev["score_parts"] = [{"label": k, "value": round(v, 1)} for k, v in parts]
    ev["relevant_hits"] = hits
    ev["is_relevant"] = bool(hits)
    ev["is_combat"] = is_combat
    ev["followup"] = followup
    return ev


def load_memory(path: str, now: datetime) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    cutoff = (now - timedelta(days=MEMORY_DAYS)).strftime("%Y-%m-%d")
    return {k: v for k, v in raw.items() if v.get("last_seen", "") >= cutoff}


def save_memory(path: str, memory: dict, published: list[dict], today: str) -> None:
    for ev in published:
        m = memory.get(ev["key"], {"title": ev["title"], "first_seen": today, "times": 0})
        m["title"] = ev["title"]
        # 同一天重跑不重复计数。workflow_dispatch 手动重跑、或失败后重试都会
        # 走到这里，times 被叠加的话「累计出现 N 次」就成了假数据。
        if m.get("last_seen") != today:
            m["times"] = m.get("times", 0) + 1
        m["last_seen"] = today
        memory[ev["key"]] = m
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)


def build_digest(events: list[dict], memory: dict, now: datetime) -> dict:
    for ev in events:
        score_event(ev, memory, now)

    main = sorted((e for e in events if e["pool"] == "main"),
                  key=lambda e: e["score"], reverse=True)
    papers = sorted((e for e in events if e["pool"] == "paper"),
                    key=lambda e: e["score"], reverse=True)[:MAX_PAPERS]
    graphics = sorted((e for e in events if e["pool"] == "graphics"),
                      key=lambda e: e["score"], reverse=True)[:MAX_GRAPHICS]
    repos = sorted((e for e in events if e["pool"] == "repo"),
                   key=lambda e: e["score"], reverse=True)[:MAX_REPOS]
    diverse = sorted((e for e in events if e["pool"] == "diverse"),
                     key=lambda e: e["score"], reverse=True)[:MAX_DIVERSE]

    used = set()

    # 「线索追踪」：14 天内报过、今天又有新报道的事件
    threads = [e for e in main if e.get("followup") and e["coverage"] >= 2][:3]
    used.update(id(e) for e in threads)

    # 「能用上的」先挑 —— 顺序很重要。
    # 如果先挑必读，命中相关词的条目（+20 分）会因为分高被必读区吸走，
    # 专属栏目反而只剩边角料。这个栏目的存在意义就是无条件优先。
    relevant = [e for e in main if id(e) not in used and e["is_relevant"]][:DEEP_READ_RELEVANT]
    used.update(id(e) for e in relevant)

    # 「今日必读」：分数阈值制 —— 宁可当天只有 2 条，也不凑数
    lead = [e for e in main if id(e) not in used and e["score"] >= DEEP_READ_MIN_SCORE][:DEEP_READ_TOP]
    used.update(id(e) for e in lead)

    used.update(id(e) for e in papers + graphics + repos + diverse)
    brief = [e for e in main if id(e) not in used]

    for e in lead:
        e["section"] = "lead"
    for e in relevant:
        e["section"] = "relevant"
    for e in threads:
        e["section"] = "thread"

    return {
        "generated_at": now.astimezone(TZ).isoformat(),
        "date": now.astimezone(TZ).strftime("%Y-%m-%d"),
        "lead": lead,
        "relevant": relevant,
        "threads": threads,
        "papers": papers,
        "graphics": graphics,
        "repos": repos,
        "diverse": diverse,
        "brief": brief,
        "stats": {
            "events": len(events),
            "main_events": len(main),
            "multi_source": sum(1 for e in main if e["coverage"] > 1),
            "deep_read": len(lead) + len(relevant),
        },
    }


def main():
    inp = sys.argv[1] if len(sys.argv) > 1 else "data/events.json"
    out = sys.argv[2] if len(sys.argv) > 2 else "data/ranked.json"
    mem_path = sys.argv[3] if len(sys.argv) > 3 else "data/memory.json"

    now = datetime.now(timezone.utc)
    with open(inp, encoding="utf-8") as f:
        events = json.load(f)

    memory = load_memory(mem_path, now.astimezone(TZ))
    digest = build_digest(events, memory, now)

    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(digest, f, ensure_ascii=False, indent=2)

    s = digest["stats"]
    print(f"[OK] 必读 {len(digest['lead'])} · 能用上 {len(digest['relevant'])} · "
          f"追踪 {len(digest['threads'])} · 论文 {len(digest['papers'])} · "
          f"图形 {len(digest['graphics'])} · 开源 {len(digest['repos'])} · 速览 {len(digest['brief'])}")
    print(f"[OK] {s['main_events']} 个主事件，其中 {s['multi_source']} 个多源报道 → {out}")

    # 注意：这里**不**写 memory.json。
    # 深读阶段还会把不达标的条目降级踢回速览区，如果在这里就记进记忆，
    # 那些条目明天会被扣 30 分「已报过」，等于永久沉底 —— 它们其实从没露过面。
    # 记忆由 commit_memory.py 在流水线最后一步、按最终发布结果写入。


if __name__ == "__main__":
    main()
