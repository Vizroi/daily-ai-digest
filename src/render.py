"""HTML 渲染模块：将提炼后的文章渲染为响应式静态页面。"""
import json
import sys
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))

CATEGORY_ORDER = [
    "大模型与应用",
    "AI研究与基础设施",
    "AI + 游戏",
    "游戏行业",
    "行业与商业",
    "其他AI资讯",
]

CATEGORY_ICONS = {
    "大模型与应用": "🤖",
    "AI研究与基础设施": "🔬",
    "AI + 游戏": "🎮",
    "游戏行业": "🕹️",
    "行业与商业": "💼",
    "其他AI资讯": "📡",
}

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>每日 AI & 游戏资讯 | {date_str}</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    background: #f5f5f5;
    color: #1a1a1a;
    line-height: 1.6;
  }}
  .container {{ max-width: 900px; margin: 0 auto; padding: 20px 16px; }}
  header {{
    text-align: center;
    padding: 32px 0 20px;
    border-bottom: 2px solid #e0e0e0;
    margin-bottom: 28px;
  }}
  header h1 {{ font-size: 28px; font-weight: 700; color: #111; }}
  header .meta {{ margin-top: 8px; font-size: 14px; color: #888; }}
  .stats {{
    display: flex; gap: 12px; justify-content: center; flex-wrap: wrap;
    margin: 16px 0 0;
  }}
  .stats .stat {{
    background: #fff; border-radius: 8px; padding: 6px 14px;
    font-size: 13px; color: #555; box-shadow: 0 1px 3px rgba(0,0,0,0.06);
  }}
  .stats .stat strong {{ color: #111; }}

  .section {{
    margin-bottom: 32px;
  }}
  .section-title {{
    font-size: 20px; font-weight: 700; color: #222;
    padding-bottom: 8px; border-bottom: 1px solid #e8e8e8;
    margin-bottom: 16px;
  }}
  .card {{
    background: #fff;
    border-radius: 10px;
    padding: 18px 20px;
    margin-bottom: 12px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.05);
    transition: box-shadow 0.15s;
    border-left: 3px solid transparent;
  }}
  .card:hover {{ box-shadow: 0 3px 12px rgba(0,0,0,0.10); }}
  .card.recommended {{ border-left-color: #e63946; background: #fff5f5; }}
  .card-title {{
    font-size: 16px; font-weight: 600; line-height: 1.4;
    margin-bottom: 8px;
  }}
  .card-title a {{
    color: #1a1a1a; text-decoration: none;
  }}
  .card-title a:hover {{ color: #2563eb; text-decoration: underline; }}
  .card-summary {{
    font-size: 14px; color: #555; margin-bottom: 10px;
    line-height: 1.65;
  }}
  .card-meta {{
    display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
    font-size: 12px; color: #999;
  }}
  .card-meta .source {{
    background: #f0f0f0; border-radius: 4px; padding: 2px 8px;
  }}
  .card-meta .tag {{
    background: #e8f0fe; color: #2563eb; border-radius: 4px; padding: 2px 8px;
  }}
  .card-meta .tag.hot {{
    background: #fde8e8; color: #c0392b; font-weight: 600;
  }}
  .card-meta .rec-badge {{
    color: #c0392b; font-weight: 700; font-size: 12px;
  }}

  footer {{
    text-align: center; padding: 32px 0 20px;
    border-top: 1px solid #e0e0e0; margin-top: 32px;
    font-size: 12px; color: #aaa;
  }}
  footer a {{ color: #888; }}

  @media (max-width: 600px) {{
    header h1 {{ font-size: 22px; }}
    .card {{ padding: 14px 15px; }}
    .card-title {{ font-size: 15px; }}
  }}
</style>
</head>
<body>
<div class="container">
<header>
  <h1>🌅 每日 AI & 游戏资讯</h1>
  <p class="meta">{date_str} · 自动抓取并 AI 提炼生成</p>
  <div class="stats">
    <span class="stat">📰 <strong>{total}</strong> 条资讯</span>
    <span class="stat">⭐ <strong>{recommended_count}</strong> 条推荐</span>
    <span class="stat">🕐 更新于 {time_str} (UTC+8)</span>
  </div>
</header>

{sections}

<footer>
  <p>数据来源：AI 科技媒体、研究论文、AI 公司博客、游戏行业媒体</p>
  <p>由 <a href="https://github.com/" target="_blank">GitHub Actions</a> 自动化生成 · Powered by DeepSeek</p>
</footer>
</div>
</body>
</html>"""


def _render_card(article: dict) -> str:
    rec = article.get("recommended", False)
    cls = 'card recommended' if rec else 'card'

    title = article.get("title", "无标题")
    url = article.get("url", "#")
    summary_cn = article.get("summary_cn", "") or article.get("summary_raw", "") or ""
    source = article.get("source", "")
    category = article.get("category", "其他AI资讯")
    reason = article.get("reason", "")

    rec_badge = '<span class="rec-badge">🔥 推荐</span>' if rec else ""
    reason_html = f'<br><span style="color:#c0392b;font-size:12px;">💡 {reason}</span>' if rec and reason else ""
    tag_cls = 'tag hot' if rec else 'tag'

    return f"""<div class="{cls}">
  <div class="card-title"><a href="{url}" target="_blank" rel="noopener">{title}</a> {rec_badge}</div>
  <div class="card-summary">{summary_cn}{reason_html}</div>
  <div class="card-meta">
    <span class="source">{source}</span>
    <span class="{tag_cls}">{category}</span>
    {f'<span style="font-size:11px;">{article.get("published", "")[:10]}</span>' if article.get("published") else ""}
  </div>
</div>"""


def render(summarized: list[dict]) -> str:
    now = datetime.now(TZ)
    date_str = now.strftime("%Y 年 %-m 月 %-d 日")
    time_str = now.strftime("%H:%M")

    # 按分类分组
    categorized = {cat: [] for cat in CATEGORY_ORDER}
    for a in summarized:
        cat = a.get("category", "其他AI资讯")
        if cat not in categorized:
            cat = "其他AI资讯"
        categorized[cat].append(a)

    # 每个分类内：推荐在上，其余在下
    for cat in categorized:
        categorized[cat].sort(key=lambda a: (not a.get("recommended", False)))

    sections = []
    for cat in CATEGORY_ORDER:
        articles = categorized.get(cat, [])
        if not articles:
            continue
        icon = CATEGORY_ICONS.get(cat, "")
        cards = "\n".join(_render_card(a) for a in articles)
        sections.append(f"""<div class="section">
  <div class="section-title">{icon} {cat} <span style="font-weight:400;font-size:14px;color:#999;">({len(articles)})</span></div>
  {cards}
</div>""")

    total = len(summarized)
    recommended_count = sum(1 for a in summarized if a.get("recommended"))

    return HTML_TEMPLATE.format(
        date_str=date_str,
        time_str=time_str,
        total=total,
        recommended_count=recommended_count,
        sections="\n".join(sections),
    )


def main():
    input_file = sys.argv[1] if len(sys.argv) > 1 else "docs/articles_summarized.json"
    output_file = sys.argv[2] if len(sys.argv) > 2 else "docs/index.html"

    with open(input_file, "r", encoding="utf-8") as f:
        articles = json.load(f)

    html = render(articles)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[OK] HTML 页面已生成 → {output_file}")


if __name__ == "__main__":
    main()
