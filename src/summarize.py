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
{"id": 序号, "title": "英文标题", "source": "来源", "summary_raw": "原文摘要（可能为空）"}

请基于标题和原文摘要，对每篇文章输出：
1. **summary_cn**: 2-4 句简洁的中文摘要（保留核心信息点，不要废话）。
    - 如果内容不够清楚做不了摘要，则设为空字符串。
2. **category**: 从以下分类中选择一个最合适的：
   - "大模型与应用" (LLM、Agent、编程工具、新产品等)
   - "AI研究与基础设施" (论文、芯片、训练框架、benchmark等)
   - "行业与商业" (融资、政策、企业动态)
   - "游戏行业" (与传统游戏相关，非AI游戏)
   - "AI + 游戏" (AI在游戏中的应用)
   - "其他AI资讯" (够AI相关但归不进上面)
3. **recommended**: true 或 false —— 如果这条是今天最重要的新闻之一（重大发布、突破性论文、行业地震），标 true。最多标 5 篇。
4. **reason**: 如果 recommended=true，用一句中文说明为什么重要。如果是false则为空字符串。

只返回一个 JSON 数组（不要 markdown 包裹，不要解释），每项保持原结构并加上新字段。

输出格式示例（只返回以下结构，不要多余内容）：
[
  {"id": 0, "title": "...", "source": "...", "summary_raw": "...",
   "summary_cn": "中文摘要", "category": "大模型与应用", "recommended": true, "reason": "Anthropic发布全新旗舰模型，性能大幅超越GPT-5"}
]
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
        r.setdefault("category", "其他AI资讯")
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

    # 将原始字段 (url, published 等) 合并回提炼结果
    fields_to_merge = ("url", "published", "lang")
    for orig in articles:
        for r in summarized:
            if r.get("id") == orig.get("id"):
                for f in fields_to_merge:
                    val = orig.get(f)
                    if val and not r.get(f):
                        r[f] = val
                break

    os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(summarized, f, ensure_ascii=False, indent=2)

    recommended_count = sum(1 for a in summarized if a.get("recommended"))
    print(f"[OK] 提炼完成。推荐 {recommended_count} 篇，共写入 {output_file}")


if __name__ == "__main__":
    main()
