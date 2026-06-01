"""AI 提炼模块：调用 DeepSeek API 批量生成中文摘要 + 分类标签 + 重要度标记。"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from openai import OpenAI

# ---- 从环境变量或 config 读取 ----
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

BATCH_SIZE = 10  # 每次请求处理的文章数

SYSTEM_PROMPT = """你是一个资深 AI & 游戏行业资讯编辑。用户会给你一个 JSON 数组，每项格式为：
{"id": 序号, "title": "标题", "source": "来源", "summary_raw": "原文摘要（可能为空）"}

请基于标题和原文摘要，对每篇文章输出：
1. **summary_cn**: 2-4 句简洁的中文摘要（保留核心信息点，不要废话）。
2. **category**: 从以下 7 个分类中选择一个最合适的：

   🎮 游戏大类：
   - "游戏资讯" — 新游发售、评测、更新、电竞、主机、手游、行业事件
   - "游戏开发" — 引擎技术(Unreal/Unity)、开发工具、编程、GDC相关、独立开发
   - "Reddit游戏热帖" — 来源是 Reddit 游戏相关子版(gaming/games/gamedev/pcgaming)的热门讨论

   🤖 AI 大类：
   - "AI大模型/应用" — LLM、Agent、编程助手、AI新产品、AI功能更新
   - "AI研究/前沿" — 论文、芯片、训练框架、benchmark、融资、政策、企业动态
   - "AI×游戏" — AI在游戏中的具体应用(AI NPC、AI生成内容、AI辅助开发等)
   - "GitHub热门" — 来源是 "GitHub Trending" 的热门开源项目

   注意：
   - 来源包含 "Reddit" + 游戏相关子版 → 必选 "Reddit游戏热帖"
   - 来源是 "GitHub Trending" → 必选 "GitHub热门"
   - 游戏引擎博客、GDC、游戏开发工具 → 必选 "游戏开发"
   - AI 用于游戏相关 → 选 "AI×游戏"
   - 实在归不进上面任何一类的标 "其他"

3. **recommended**: true 或 false — 如果是今天最重要的新闻，标 true。最多 8 篇。
4. **reason**: 如果 recommended=true，用一句中文说明为什么重要。

只返回一个 JSON 数组（不要 markdown 包裹），输出格式示例：
[{"id": 0, "title": "...", "source": "...", "summary_raw": "...",
  "summary_cn": "中文摘要", "category": "AI大模型/应用", "recommended": true, "reason": "..."}]
"""


def _summarize_batch(articles_batch: list[dict]) -> list[dict]:
    """对一批文章调用 DeepSeek API 进行摘要。"""
    # 只发 id, title, source, summary_raw
    compact = [
        {"id": a["id"], "title": a["title"], "source": a["source"], "summary_raw": a.get("summary_raw", "")}
        for a in articles_batch
    ]

    user_msg = json.dumps(compact, ensure_ascii=False)

    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.3,
                max_tokens=4096,
            )
            raw = resp.choices[0].message.content.strip()

            # 尝试剥离可能的 markdown ```json 包裹
            if raw.startswith("```"):
                lines = raw.split("\n")
                raw = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])

            result = json.loads(raw)
            return result

        except json.JSONDecodeError:
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            print(f"[WARN] JSON 解析失败，第 {attempt+1} 次重试，返回原文中…")
            return compact  # fallback
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"[WARN] API 调用失败: {e}，{attempt+1}/{max_retries} 重试…")
                time.sleep(2 ** attempt)
                continue
            print(f"[ERROR] API 调用最终失败: {e}")
            return compact

    return compact


def summarize(articles: list[dict]) -> list[dict]:
    """批量处理所有文章，返回带有摘要、分类、推荐标记的列表。"""
    # 给每篇文章加一个 id
    for i, a in enumerate(articles):
        a["id"] = i

    results = []
    total = len(articles)

    for i in range(0, total, BATCH_SIZE):
        batch = articles[i:i + BATCH_SIZE]
        print(f"  [进度] 处理第 {i+1}-{min(i+BATCH_SIZE, total)} 篇…")
        summarized = _summarize_batch(batch)
        results.extend(summarized)
        # 稍微延迟，避免触发速率限制
        if i + BATCH_SIZE < total:
            time.sleep(0.5)

    # 确保必要字段存在
    for r in results:
        r.setdefault("summary_cn", "")
        r.setdefault("category", "其他")
        r.setdefault("recommended", False)
        r.setdefault("reason", "")

    return results


def main():
    input_file = sys.argv[1] if len(sys.argv) > 1 else "docs/articles_raw.json"
    output_file = sys.argv[2] if len(sys.argv) > 2 else "docs/articles_summarized.json"

    if not API_KEY:
        print("[ERROR] 未设置 DEEPSEEK_API_KEY 环境变量")
        sys.exit(1)

    with open(input_file, "r", encoding="utf-8") as f:
        articles = json.load(f)

    print(f"[INFO] 开始 AI 提炼，共 {len(articles)} 篇文章…")
    summarized = summarize(articles)

    # 将原始字段 (url, published, lang, source) 合并回提炼结果
    fields_to_merge = ("url", "published", "lang", "source")
    for orig in articles:
        for r in summarized:
            if r.get("id") == orig.get("id"):
                for f in fields_to_merge:
                    val = orig.get(f)
                    if val and not r.get(f):
                        r[f] = val
                break

    # 硬编码分类：来源决定分类，不依赖 AI 判断
    for r in summarized:
        src = r.get("source", "")
        if src.startswith("GitHub Trending"):
            r["category"] = "GitHub热门"

    # 按原始 id 顺序重排（fetch_sources 中 GitHub Trending 在前，id 即 trending 排名）
    id_order = {a["id"]: i for i, a in enumerate(articles)}
    summarized.sort(key=lambda r: id_order.get(r.get("id"), 99999))

    # GitHub Trending 硬规则：
    #   1. 全部归入 "GitHub热门"
    #   2. 前 3 名强制标为推荐精选，其余不标
    #   3. 排序保持与 trending 页面一致
    gh_items = [r for r in summarized if (r.get("source") or "").startswith("GitHub Trending")]
    for i, r in enumerate(gh_items):
        r["category"] = "GitHub热门"
        r["recommended"] = (i < 3)
        if r["recommended"]:
            r["reason"] = f"GitHub Trending #{i+1} — 今日热门开源项目"

    os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(summarized, f, ensure_ascii=False, indent=2)

    recommended_count = sum(1 for a in summarized if a.get("recommended"))
    print(f"[OK] 提炼完成。推荐 {recommended_count} 篇，共写入 {output_file}")


if __name__ == "__main__":
    main()
