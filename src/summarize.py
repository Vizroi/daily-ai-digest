"""阶段④-b 分级摘要。

深读（Top ~10）：每条**单独**一次调用 + 完整正文 → what / why / for_you 三段
速览（其余）：批量调用，只做标题翻译

为什么深读必须单条调用：
  批处理会摊薄模型注意力，输出退化成模板句。v1 的 BATCH_SIZE=10 就是这个毛病。
  单条 + 全文，质量差别非常明显，而这才十次调用。

禁用词校验是质量下限的保证：套话检出即重试，重试仍失败则降级为纯标题条目，
不让注水内容混进必读区。
"""
import json
import os
import re
import sys
import time
import concurrent.futures as futures

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 套话黑名单：出现即判定为注水，触发重试
BANNED = [
    "据报道", "引发广泛关注", "引发关注", "值得关注", "业界普遍认为", "备受关注",
    "标志着", "新的里程碑", "有望", "或将", "未来可期", "这一举措", "不容忽视",
    "随着技术的不断发展", "在当今", "众所周知", "总的来说", "综上所述",
]

DEEP_PROMPT = """你是一名给「UE5 武侠 PVP 项目的战斗策划」做私人情报简报的编辑。
读者的日常工作是：GAS 技能配置、动画蓝图与 Locomotion、战斗手感、受击与位移、网络同步、性能优化。

给你一篇文章的标题和正文，输出严格的 JSON：

{"what": "...", "why": "...", "for_you": "..."}

- what：这件事**具体**是什么。必须包含正文里的实际事实——数字、版本号、参数、
  价格、时间、模型名。不许只是把标题换个说法。
- why：为什么重要。放进行业上下文里说——它改变了什么、谁受影响、和之前有什么不同。
- for_you：对上述这位读者的项目意味着什么。可以是能直接用的技术、
  值得警惕的趋势、或者可借鉴的做法。
  **如果这条与他的工作确实没有关系，就直接写「与你的项目无直接关系」，
  绝对不许硬凑关联。** 硬凑比留白更糟。

硬性要求：
- 三段各不超过 60 个汉字。信息密度优先于完整性。
- 禁止使用这些词：据报道、引发关注、值得关注、标志着、有望、或将、
  这一举措、未来可期、总的来说、随着技术的不断发展。
- 只返回 JSON，不要 markdown 包裹，不要任何解释。
"""

BRIEF_PROMPT = """把下面每条标题翻译成简洁的中文标题（已经是中文的原样返回）。
保留专有名词原文（模型名、公司名、仓库名、版本号）。不要加书名号，不要解释。
输入是 JSON 数组，输出同长度的 JSON 数组：[{"id":0,"title_cn":"..."}]
只返回 JSON。"""


def _has_banned(text: str) -> str | None:
    for w in BANNED:
        if w in text:
            return w
    return None


def _has_concrete_fact(text: str) -> bool:
    """what 段必须含至少一个具体事实：数字，或拉丁文专有名词。"""
    if re.search(r"\d", text):
        return True
    return bool(re.search(r"[A-Za-z][A-Za-z0-9.\-]{2,}", text))


def _call(client, model, system, user, max_tokens=1024, temperature=0.2):
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    raw = resp.choices[0].message.content.strip()
    return re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()


def deep_read_one(client, model: str, ev: dict) -> dict:
    """单条深读。失败或校验不过 → 标记 degraded，渲染时降级展示。"""
    body = ev.get("body") or ev.get("summary_raw") or ""
    if not body:
        ev["degraded"] = "no_content"
        return ev

    payload = json.dumps({
        "title": ev["title"],
        "sources": ev.get("sources", []),
        "body": body[:6000],
    }, ensure_ascii=False)

    for attempt in range(2):
        try:
            raw = _call(client, model, DEEP_PROMPT, payload,
                        max_tokens=900, temperature=0.2 + attempt * 0.2)
            data = json.loads(raw)
            what = (data.get("what") or "").strip()
            why = (data.get("why") or "").strip()
            for_you = (data.get("for_you") or "").strip()

            if not what or not why:
                continue
            bad = _has_banned(what) or _has_banned(why) or _has_banned(for_you)
            if bad:
                print(f"  [重试] 检出套话「{bad}」— {ev['title'][:32]}")
                continue
            if not _has_concrete_fact(what):
                print(f"  [重试] what 段无具体事实 — {ev['title'][:32]}")
                continue

            ev["what"], ev["why"], ev["for_you"] = what, why, for_you
            ev["degraded"] = None
            return ev
        except json.JSONDecodeError:
            continue
        except Exception as e:
            print(f"  [WARN] 深读失败 {type(e).__name__} — {ev['title'][:32]}")
            time.sleep(1.5)

    ev["degraded"] = "quality"
    print(f"  [降级] 两次未达标，转为速览条目 — {ev['title'][:32]}")
    return ev


def deep_read(client, model: str, events: list[dict], workers: int = 4) -> None:
    if not events:
        return
    print(f"[INFO] 深读 {len(events)} 条（每条单独调用 + 完整正文）…")
    with futures.ThreadPoolExecutor(workers) as ex:
        list(ex.map(lambda e: deep_read_one(client, model, e), events))
    ok = sum(1 for e in events if not e.get("degraded"))
    print(f"[OK] 深读达标 {ok}/{len(events)}")


def translate_titles(client, model: str, events: list[dict], batch: int = 40) -> None:
    """速览区只做标题翻译，不生成摘要 —— 摘要在这里没有信息增量。"""
    todo = [e for e in events if e.get("lang") != "zh"]
    if not todo:
        return
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        payload = json.dumps([{"id": j, "title": e["title"][:150]}
                              for j, e in enumerate(chunk)], ensure_ascii=False)
        try:
            data = json.loads(_call(client, model, BRIEF_PROMPT, payload, max_tokens=4096, temperature=0.1))
            for item in data:
                idx = item.get("id")
                if isinstance(idx, int) and 0 <= idx < len(chunk):
                    chunk[idx]["title_cn"] = (item.get("title_cn") or "").strip()
        except Exception as e:
            print(f"[WARN] 标题翻译失败: {type(e).__name__}（保留原标题）")
    print(f"[OK] 标题翻译 {len(todo)} 条")


def main():
    inp = sys.argv[1] if len(sys.argv) > 1 else "data/ranked.json"
    out = sys.argv[2] if len(sys.argv) > 2 else "data/digest.json"

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        print("[ERROR] 未设置 DEEPSEEK_API_KEY")
        sys.exit(1)

    from openai import OpenAI
    client = OpenAI(api_key=api_key,
                    base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

    with open(inp, encoding="utf-8") as f:
        digest = json.load(f)

    deep = digest.get("lead", []) + digest.get("relevant", []) + digest.get("threads", [])
    deep_read(client, model, deep)

    # 深读降级的条目退回速览区，不占必读位
    for key in ("lead", "relevant", "threads"):
        keep, demoted = [], []
        for e in digest.get(key, []):
            (demoted if e.get("degraded") else keep).append(e)
        digest[key] = keep
        digest["brief"] = demoted + digest.get("brief", [])

    shallow = digest.get("papers", []) + digest.get("repos", []) + digest.get("diverse", []) + digest.get("brief", [])
    translate_titles(client, model, shallow)

    digest["stats"]["deep_read"] = len(digest["lead"]) + len(digest["relevant"])

    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(digest, f, ensure_ascii=False, indent=2)
    print(f"[OK] 已写入 {out}")


if __name__ == "__main__":
    main()
