"""阶段②事件聚类：把讲同一件事的条目合并成一个 event。

为什么必须做这一步：
  OpenAI 发个模型，量子位 / TechCrunch / Verge / HN 会各报一遍。
  v1 只按 URL 去重，所以同一事件在日报里出现 5 次。
  而「5 家同时报」恰恰是判断重要性最可靠的免费信号 —— 白扔了。

为什么用 LLM 而不是字符串相似度：
  「OpenAI 发布 GPT-5.5」和「OpenAI unveils GPT-5.5 with...」字面重叠为零。
  跨语言聚类只有语义模型做得到。一次调用约 10k token，可以忽略。
"""
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import TIER_WEIGHT

CLUSTER_PROMPT = """你在做新闻去重。下面是今天从多个信息源抓到的条目列表。

任务：把**报道同一件事**的条目分到同一组。

判定标准（严格）：
- 同一事件 = 同一个具体的发布/更新/收购/论文/事故。中英文标题描述同一事件必须合并。
- 同一家公司的两条不同新闻 **不算** 同一事件。
- 同一主题的两篇独立分析文章 **不算** 同一事件。
- 拿不准就不合并。漏合并的代价远小于错合并。

输出：只返回一个 JSON 二维数组，每个子数组是一组的 id 列表。
所有 id 都必须恰好出现一次。不要输出任何解释文字或 markdown 包裹。

示例输出：[[0,17,58],[1],[2],[3,9]]
"""


def _norm_title(t: str) -> str:
    t = re.sub(r"[^\w一-鿿]+", " ", t.lower())
    return re.sub(r"\s+", " ", t).strip()


def _event_key(title: str) -> str:
    return hashlib.md5(_norm_title(title).encode()).hexdigest()[:16]


def _llm_groups(client, model: str, items: list[dict]) -> list[list[int]] | None:
    """调 LLM 做分组。失败返回 None，由调用方降级。"""
    compact = [{"id": a["id"], "title": a["title"][:160], "source": a["source"]} for a in items]
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": CLUSTER_PROMPT},
                {"role": "user", "content": json.dumps(compact, ensure_ascii=False)},
            ],
            temperature=0.0,
            max_tokens=8192,
        )
        raw = resp.choices[0].message.content.strip()
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
        groups = json.loads(raw)
        if not isinstance(groups, list) or not groups:
            return None
        # 校验：id 必须合法且不重复
        valid_ids = {a["id"] for a in items}
        seen, clean = set(), []
        for g in groups:
            if not isinstance(g, list):
                continue
            gg = [i for i in g if isinstance(i, int) and i in valid_ids and i not in seen]
            seen.update(gg)
            if gg:
                clean.append(gg)
        # 补上 LLM 漏掉的 id，各自成组（宁可漏合并，不能漏条目）
        for i in sorted(valid_ids - seen):
            clean.append([i])
        return clean
    except Exception as e:
        print(f"[WARN] 聚类调用失败: {type(e).__name__}: {e}")
        return None


def build_events(items: list[dict], client=None, model: str = "") -> list[dict]:
    """输入 main 池条目，输出 event 列表。"""
    by_id = {a["id"]: a for a in items}

    groups = None
    if client and items:
        groups = _llm_groups(client, model, items)
    if groups is None:
        print("[WARN] 聚类降级：每条各自成组（不影响流水线，只是丢失跨源覆盖信号）")
        groups = [[a["id"]] for a in items]

    events = []
    for g in groups:
        members = [by_id[i] for i in g if i in by_id]
        if not members:
            continue

        # 代表条目：tier 最高；同 tier 时中文优先（标题更好读）
        members.sort(key=lambda a: (a["tier"], 0 if a["lang"] == "zh" else 1))
        lead = members[0]

        # 跨源覆盖 = 独立源数量（不是条目数）
        srcs = []
        for m in members:
            if m["source"] not in srcs:
                srcs.append(m["source"])

        sig = {k: 0 for k in ("hn_points", "hn_comments", "hf_upvotes", "stars_today")}
        sig["rank_bonus"] = 0.0
        for m in members:
            for k in sig:
                sig[k] = max(sig[k], m["signals"].get(k, 0))

        hn_url = next((m.get("hn_url") for m in members if m.get("hn_url")), None)
        best_summary = max((m.get("summary_raw") or "" for m in members), key=len)

        events.append({
            "key": _event_key(lead["title"]),
            "title": lead["title"],
            "url": lead["url"],
            "hn_url": hn_url,
            "lang": lead["lang"],
            "tier": min(m["tier"] for m in members),
            "tier_weight": max(TIER_WEIGHT[m["tier"]] for m in members),
            "coverage": len(srcs),
            "sources": srcs,
            "published": min(m["published"] for m in members),
            "undated": all(m.get("undated") for m in members),
            "summary_raw": best_summary,
            "signals": sig,
            "members": [{"title": m["title"], "url": m["url"], "source": m["source"]} for m in members],
            "pool": "main",
        })

    multi = sum(1 for e in events if e["coverage"] > 1)
    print(f"[OK] 聚类: {len(items)} 条 → {len(events)} 个事件（其中 {multi} 个为多源报道）")
    return events


def main():
    inp = sys.argv[1] if len(sys.argv) > 1 else "data/raw.json"
    out = sys.argv[2] if len(sys.argv) > 2 else "data/events.json"

    with open(inp, encoding="utf-8") as f:
        items = json.load(f)

    main_items = [a for a in items if a.get("pool") == "main"]
    others = [a for a in items if a.get("pool") != "main"]

    client = None
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if api_key:
        from openai import OpenAI
        client = OpenAI(api_key=api_key,
                        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    else:
        print("[WARN] 无 DEEPSEEK_API_KEY，跳过 LLM 聚类")

    events = build_events(main_items, client, os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"))

    # 论文/开源/跨界不参与聚类，原样透传成单条 event
    for a in others:
        events.append({
            "key": _event_key(a["title"]), "title": a["title"], "url": a["url"], "hn_url": None,
            "lang": a["lang"], "tier": a["tier"], "tier_weight": TIER_WEIGHT[a["tier"]],
            "coverage": 1, "sources": [a["source"]], "published": a["published"],
            "undated": a.get("undated", False), "summary_raw": a.get("summary_raw", ""),
            "signals": a["signals"], "members": [], "pool": a["pool"],
            "authors": a.get("authors"), "repo_lang": a.get("repo_lang"), "repo_stars": a.get("repo_stars"),
        })

    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(events, f, ensure_ascii=False, indent=2)
    print(f"[OK] 已写入 {out}")


if __name__ == "__main__":
    main()
