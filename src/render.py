"""HTML 渲染模块：将提炼后的文章渲染为现代杂志风静态页面。"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TZ = timezone(timedelta(hours=8))

# 侧边栏分类定义 — key 非空的是普通分类，key 为空的为分组标题
NAV_CATEGORIES = [
    {"id": "all",          "icon": "📰", "label": "全部资讯", "header": None},
    {"id": "推荐精选",      "icon": "⭐", "label": "推荐精选", "header": None},
    {"id": "",             "icon": "",   "label": "🎮 游戏",  "header": "game"},
    {"id": "游戏资讯",      "icon": "📡", "label": "游戏资讯", "header": "game"},
    {"id": "游戏开发",      "icon": "🛠️", "label": "游戏开发", "header": "game"},
    {"id": "Reddit游戏热帖", "icon": "💬", "label": "Reddit热帖", "header": "game"},
    {"id": "",             "icon": "",   "label": "🤖 AI",   "header": "ai"},
    {"id": "AI大模型/应用",  "icon": "🧠", "label": "大模型/应用", "header": "ai"},
    {"id": "AI研究/前沿",   "icon": "🔬", "label": "研究/前沿", "header": "ai"},
    {"id": "AI×游戏",       "icon": "🎮", "label": "AI × 游戏", "header": "ai"},
    {"id": "GitHub热门",    "icon": "🔥", "label": "GitHub热门", "header": "ai"},
    {"id": "其他",          "icon": "📌", "label": "其他", "header": None},
]

# 分类显示顺序（用于 "全部" 视图排序）
CATEGORY_ORDER = [c["id"] for c in NAV_CATEGORIES[2:]]  # 跳过 "全部" 和 "推荐"

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>每日 AI & 游戏资讯 | {date_str}</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  :root {{
    --bg: #f7f7f8;
    --sidebar-bg: #1e1e2e;
    --sidebar-text: #cdd6f4;
    --sidebar-hover: #313244;
    --sidebar-active: #45475a;
    --card-bg: #ffffff;
    --text: #1e1e2e;
    --text-secondary: #585b70;
    --text-muted: #9399b2;
    --border: #e6e6ea;
    --accent: #8839ef;
    --hot: #d20f39;
    --game: #40a02b;
    --radius: 12px;
    --shadow: 0 1px 3px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.06);
    --shadow-hover: 0 4px 16px rgba(0,0,0,0.08);
    --font: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans SC", sans-serif;
  }}
  body {{
    font-family: var(--font);
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    display: flex;
    min-height: 100vh;
  }}

  /* ---- sidebar ---- */
  .sidebar {{
    width: 220px; min-width: 220px;
    background: var(--sidebar-bg);
    color: var(--sidebar-text);
    padding: 28px 0;
    position: sticky; top: 0; height: 100vh;
    overflow-y: auto;
    display: flex; flex-direction: column;
  }}
  .sidebar-brand {{
    padding: 0 20px 24px;
    border-bottom: 1px solid rgba(255,255,255,0.06);
    margin-bottom: 16px;
  }}
  .sidebar-brand h2 {{
    font-size: 17px; font-weight: 700; color: #fff; letter-spacing: -0.3px;
  }}
  .sidebar-brand p {{ font-size: 11px; color: #a6adc8; margin-top: 4px; }}
  .sidebar-nav {{ list-style: none; flex: 1; padding: 0 10px; }}
  .sidebar-nav li a {{
    display: flex; align-items: center; gap: 10px;
    padding: 10px 14px; border-radius: 8px;
    color: var(--sidebar-text); text-decoration: none;
    font-size: 14px; transition: all 0.15s;
    margin-bottom: 2px; cursor: pointer;
  }}
  .sidebar-nav li a:hover {{ background: var(--sidebar-hover); color: #fff; }}
  .sidebar-nav li a.active {{ background: var(--sidebar-active); color: #fff; font-weight: 600; }}
  .sidebar-nav li.nav-header {{
    padding: 14px 14px 4px; font-size: 11px; font-weight: 700;
    text-transform: uppercase; letter-spacing: 0.5px;
    color: #a6adc8; user-select: none;
  }}
  .sidebar-nav li a .icon {{ font-size: 16px; width: 24px; text-align: center; flex-shrink: 0; }}
  .sidebar-nav li a .count {{
    margin-left: auto; font-size: 11px; opacity: 0.6;
  }}
  .sidebar-footer {{
    padding: 16px 20px 0;
    font-size: 10px; color: #6c7086;
    border-top: 1px solid rgba(255,255,255,0.06);
    margin: 16px 10px 0;
  }}

  /* ---- main ---- */
  .main {{
    flex: 1; padding: 28px 32px; max-width: 960px;
  }}
  .main-header {{
    display: flex; justify-content: space-between; align-items: flex-start;
    margin-bottom: 24px; flex-wrap: wrap; gap: 12px;
  }}
  .main-header h1 {{ font-size: 26px; font-weight: 700; letter-spacing: -0.5px; }}
  .main-header .header-right {{
    display: flex; gap: 10px; flex-wrap: wrap;
  }}
  .main-header .search-box {{
    background: var(--card-bg); border: 1px solid var(--border);
    border-radius: 8px; padding: 8px 14px; font-size: 13px; width: 200px;
    outline: none; font-family: var(--font);
  }}
  .main-header .search-box:focus {{ border-color: var(--accent); }}
  .main-header .btn {{
    background: var(--card-bg); border: 1px solid var(--border);
    border-radius: 8px; padding: 8px 16px; font-size: 13px; cursor: pointer;
    font-family: var(--font); transition: all 0.15s;
  }}
  .main-header .btn:hover {{ border-color: var(--accent); }}

  .stats-bar {{
    display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap;
  }}
  .stat-item {{
    background: var(--card-bg); border-radius: var(--radius);
    padding: 12px 18px; box-shadow: var(--shadow);
    font-size: 13px; color: var(--text-secondary);
    display: flex; align-items: center; gap: 8px;
  }}
  .stat-item strong {{ font-size: 20px; color: var(--text); }}

  /* ---- cards ---- */
  .card-list {{ display: flex; flex-direction: column; gap: 8px; }}
  .card {{
    background: var(--card-bg); border-radius: var(--radius);
    padding: 16px 20px; box-shadow: var(--shadow);
    transition: box-shadow 0.15s; border-left: 3px solid transparent;
    display: flex; gap: 16px; align-items: flex-start;
  }}
  .card:hover {{ box-shadow: var(--shadow-hover); }}
  .card.recommended {{ border-left-color: var(--hot); }}
  .card-body {{ flex: 1; min-width: 0; }}
  .card-source {{
    flex-shrink: 0; width: 42px; height: 42px; border-radius: 8px;
    display: flex; align-items: center; justify-content: center;
    font-size: 12px; font-weight: 700; color: #fff;
    text-align: center; line-height: 1.1;
  }}
  .card-source.ai {{ background: #8839ef; }}
  .card-source.reddit {{ background: #ff4500; }}
  .card-source.gh {{ background: #24292f; }}
  .card-source.gdc {{ background: #e05d29; }}
  .card-source.engine {{ background: #166fe5; }}
  .card-source.game {{ background: #40a02b; }}
  .card-source.research {{ background: #1e66f5; }}
  .card-title {{
    font-size: 15px; font-weight: 600; line-height: 1.4;
    margin-bottom: 4px;
  }}
  .card-title a {{ color: var(--text); text-decoration: none; }}
  .card-title a:hover {{ color: var(--accent); }}
  .card-summary {{
    font-size: 13px; color: var(--text-secondary); line-height: 1.6;
    display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
    overflow: hidden; margin-bottom: 6px;
  }}
  .card-meta {{
    display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
    font-size: 11px; color: var(--text-muted);
  }}
  .card-meta .badge {{
    padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 500;
  }}
  .badge-source {{ background: #f2f2f4; color: var(--text-secondary); }}
  .badge-cat {{ background: #e8e4fb; color: #8839ef; }}
  .badge-game {{ background: #e2f5db; color: #40a02b; }}
  .badge-hot {{ background: #fde8e8; color: var(--hot); font-weight: 700; }}
  .rec-mark {{ color: var(--hot); font-weight: 700; font-size: 12px; white-space: nowrap; }}

  .empty-state {{
    text-align: center; padding: 80px 20px; color: var(--text-muted);
  }}
  .empty-state .icon {{ font-size: 48px; margin-bottom: 16px; }}
  .empty-state p {{ font-size: 15px; }}

  /* ---- responsive ---- */
  @media (max-width: 768px) {{
    body {{ flex-direction: column; }}
    .sidebar {{
      width: 100%; min-width: unset; height: auto; position: static;
      flex-direction: row; flex-wrap: wrap; padding: 12px;
      gap: 6px; overflow-x: auto;
    }}
    .sidebar-brand {{ display: none; }}
    .sidebar-nav {{ display: flex; flex-wrap: wrap; gap: 4px; padding: 0; }}
    .sidebar-nav li a {{ padding: 6px 12px; font-size: 12px; border-radius: 20px; }}
    .sidebar-nav li a .count {{ display: none; }}
    .sidebar-footer {{ display: none; }}
    .main {{ padding: 16px; }}
    .main-header h1 {{ font-size: 20px; }}
    .card {{ padding: 14px; }}
    .card-source {{ width: 34px; height: 34px; font-size: 10px; }}
    .card-title {{ font-size: 14px; }}
  }}

  /* ---- fade in animation ---- */
  @keyframes fadeIn {{ from {{ opacity: 0; transform: translateY(8px); }} to {{ opacity: 1; transform: translateY(0); }} }}
  .card {{ animation: fadeIn 0.3s ease forwards; }}
  .card:nth-child(1) {{ animation-delay: 0s; }}
  .card:nth-child(2) {{ animation-delay: 0.03s; }}
  .card:nth-child(3) {{ animation-delay: 0.06s; }}
  .card:nth-child(n+4) {{ animation-delay: 0.09s; }}
</style>
</head>
<body>

<!-- sidebar -->
<aside class="sidebar">
  <div class="sidebar-brand">
    <h2>🌅 AI 瞭望台</h2>
    <p>AI & 游戏 · 每日速览</p>
  </div>
  <ul class="sidebar-nav" id="sidebar-nav">{sidebar_links}</ul>
  <div class="sidebar-footer">
    Generated by GitHub Actions<br>Powered by DeepSeek · {date_str}
  </div>
</aside>

<!-- main content -->
<main class="main">
  <div class="main-header">
    <div>
      <h1>每日资讯</h1>
      <div style="font-size:12px;color:var(--text-muted);margin-top:4px;">{date_str} · {time_str} 更新</div>
    </div>
    <div class="header-right">
      <input type="text" class="search-box" placeholder="🔍 搜索关键词..." id="search-box" oninput="doFilter()">
      <button class="btn" onclick="showCategory('推荐精选')">⭐ 只看推荐</button>
    </div>
  </div>

  <div class="stats-bar">
    <div class="stat-item">📰 今日收录 <strong>{total}</strong> 条</div>
    <div class="stat-item">⭐ 推荐 <strong>{recommended_count}</strong> 条</div>
    <div class="stat-item">🤖 AI <strong>{ai_count}</strong> 条</div>
    <div class="stat-item">🎮 游戏 <strong>{game_count}</strong> 条</div>
    <div class="stat-item">🔥 热门项目 <strong>{gh_count}</strong> 个</div>
  </div>

  <div class="card-list" id="card-list">
    {cards_all}
  </div>
  <div class="empty-state" id="empty-state" style="display:none;">
    <div class="icon">📭</div>
    <p>没有找到匹配的内容</p>
  </div>
</main>

<script>
// ---- category / filter logic ----
var allCards = document.querySelectorAll('.card-list .card');
var searchBox = document.getElementById('search-box');
var emptyState = document.getElementById('empty-state');

function showCategory(cat) {{
  searchBox.value = '';
  var visible = 0;
  allCards.forEach(function(card) {{
    if (cat === 'all') {{
      card.style.display = '';
      visible++;
    }} else if (cat === '推荐精选') {{
      if (card.classList.contains('recommended')) {{ card.style.display = ''; visible++; }}
      else {{ card.style.display = 'none'; }}
    }} else {{
      var catEl = card.querySelector('.badge-cat, .badge-game');
      if (catEl && catEl.getAttribute('data-cat') === cat) {{ card.style.display = ''; visible++; }}
      else {{ card.style.display = 'none'; }}
    }}
  }});
  emptyState.style.display = visible === 0 ? '' : 'none';

  // update sidebar active
  document.querySelectorAll('.sidebar-nav a').forEach(function(a) {{ a.classList.remove('active'); }});
  var target = document.querySelector('.sidebar-nav a[data-cat="' + cat + '"]');
  if (target) target.classList.add('active');
}}

function doFilter() {{
  var q = searchBox.value.toLowerCase();
  var visible = 0;
  allCards.forEach(function(card) {{
    var text = card.textContent.toLowerCase();
    if (!q || text.indexOf(q) >= 0) {{ card.style.display = ''; visible++; }}
    else {{ card.style.display = 'none'; }}
  }});
  emptyState.style.display = visible === 0 ? '' : 'none';
  // clear sidebar active when searching
  document.querySelectorAll('.sidebar-nav a').forEach(function(a) {{ a.classList.remove('active'); }});
  document.querySelector('.sidebar-nav a[data-cat="all"]').classList.add('active');
}}

// keep empty state in sync on initial load
(function() {{
  var visible = 0;
  allCards.forEach(function(c) {{ if (c.style.display !== 'none') visible++; }});
  emptyState.style.display = visible === 0 ? '' : 'none';
}})();
</script>
</body>
</html>"""


def _source_class(source: str) -> str:
    """根据来源判断类别，用于色块颜色区分。"""
    src_lower = source.lower()

    reddit_keywords = ["reddit"]
    for kw in reddit_keywords:
        if kw in src_lower:
            return "reddit"

    github_keywords = ["github"]
    for kw in github_keywords:
        if kw in src_lower:
            return "gh"

    gdc_keywords = ["gdc"]
    for kw in gdc_keywords:
        if kw in src_lower:
            return "gdc"

    game_keywords = ["game", "games", "kotaku", "polygon", "eurogamer", "ign", "pc gamer",
                     "游民", "陀螺", "80.lv", "indiedb"]
    for kw in game_keywords:
        if kw in src_lower:
            return "game"

    engine_keywords = ["unreal", "unity"]
    for kw in engine_keywords:
        if kw in src_lower:
            return "engine"

    research_keywords = ["hugging", "arxiv", "paper", "marktech", "research"]
    for kw in research_keywords:
        if kw in src_lower:
            return "research"
    return "ai"


def _source_abbr(source: str) -> str:
    """来源缩写，用于色块上的文字。"""
    abbr_map = {
        "TechCrunch AI": "TC",
        "The Verge AI": "Ver",
        "VentureBeat AI": "VB",
        "OpenAI Blog": "OAI",
        "Google AI Blog": "GAI",
        "Meta AI Blog": "Meta",
        "Anthropic Blog": "Ant",
        "DeepMind Blog": "DM",
        "HuggingFace Papers": "HF",
        "GamesIndustry": "GI",
        "Game Developer": "GD",
        "机器之心": "JQ",
        "量子位": "LZ",
        "极客公园": "GK",
        "游民星空": "YM",
        "游戏陀螺": "TL",
        "GitHub Trending": "GH",
        "GDC News": "GDC",
        "GDC Vault": "GDC",
        "80.lv": "80",
        "Unreal Engine Blog": "UE",
        "Unity Blog": "UN",
        "IndieDB News": "IDB",
        "Reddit Gaming": "rGam",
        "Reddit Games": "rGms",
        "Reddit gamedev": "rDev",
        "Reddit pcgaming": "rPC",
    }
    return abbr_map.get(source, source[:3])


def _render_card(article: dict) -> str:
    rec = article.get("recommended", False)
    cls = 'card recommended' if rec else 'card'

    title = article.get("title", "无标题")
    url = article.get("url", "#")
    summary_cn = article.get("summary_cn", "") or article.get("summary_raw", "") or ""
    source = article.get("source", "")
    category = article.get("category", "其他")

    source_cls = _source_class(source)
    source_label = _source_abbr(source)
    rec_mark = '<span class="rec-mark">🔥</span>' if rec else ""

    # 游戏相关分类用绿色 tag
    is_game_cat = "游戏" in category
    cat_cls = "badge-game" if is_game_cat else ("badge-hot" if rec else "badge-cat")

    published = article.get("published", "")
    date_str = published[:10] if published else ""

    return f"""<div class="{cls}" data-cat="{category}">
  <div class="card-source {source_cls}">{source_label}</div>
  <div class="card-body">
    <div class="card-title"><a href="{url}" target="_blank" rel="noopener">{title}</a> {rec_mark}</div>
    <div class="card-summary">{summary_cn}</div>
    <div class="card-meta">
      <span class="badge badge-source">{source}</span>
      <span class="badge {cat_cls}" data-cat="{category}">{category}</span>
      <span>{date_str}</span>
      {rec_mark if rec else ""}
    </div>
  </div>
</div>"""


def render(articles: list[dict]) -> str:
    now = datetime.now(TZ)
    date_str = now.strftime("%Y 年 %-m 月 %-d 日")
    time_str = now.strftime("%H:%M")

    # 统计
    total = len(articles)
    recommended_count = sum(1 for a in articles if a.get("recommended"))
    ai_count = sum(1 for a in articles if (a.get("category") or "").startswith("AI"))
    game_count = sum(1 for a in articles if "游戏" in (a.get("category") or "") or "Reddit" in (a.get("category") or ""))
    gh_count = sum(1 for a in articles if a.get("category") == "GitHub热门")

    # 按分类分组统计
    cat_counts = {}
    for a in articles:
        cat = a.get("category", "其他")
        cat_counts[cat] = cat_counts.get(cat, 0) + 1

    # 侧边栏链接
    sidebar_links_parts = []
    for nav in NAV_CATEGORIES:
        cid = nav["id"]
        if cid == "":
            # 分组标题
            header = nav.get("header", "")
            sidebar_links_parts.append(
                f'<li class="nav-header" data-section="{header}">'
                f'<span>{nav["label"]}</span></li>'
            )
            continue
        count = cat_counts.get(cid, 0)
        if cid == "all":
            count = total
        elif cid == "推荐精选":
            count = recommended_count
        active_cls = ' class="active"' if cid == "all" else ""
        sidebar_links_parts.append(
            f'<li><a data-cat="{cid}" onclick="showCategory(\'{cid}\')"{active_cls}>'
            f'<span class="icon">{nav["icon"]}</span>{nav["label"]}'
            f'<span class="count">{count}</span></a></li>'
        )
    sidebar_links = "\n      ".join(sidebar_links_parts)

    # 所有卡片（按分类排序：推荐在前，其余在后）
    def sort_key(a):
        rec = a.get("recommended", False)
        cat = a.get("category", "其他")
        try:
            cat_idx = CATEGORY_ORDER.index(cat)
        except ValueError:
            cat_idx = 99
        return (not rec, cat_idx)
    sorted_articles = sorted(articles, key=sort_key)

    cards_all = "\n".join(_render_card(a) for a in sorted_articles)

    return HTML_TEMPLATE.format(
        date_str=date_str,
        time_str=time_str,
        total=total,
        recommended_count=recommended_count,
        ai_count=ai_count,
        game_count=game_count,
        gh_count=gh_count,
        sidebar_links=sidebar_links,
        cards_all=cards_all,
    )


def main():
    input_file = sys.argv[1] if len(sys.argv) > 1 else "docs/articles_summarized.json"
    output_file = sys.argv[2] if len(sys.argv) > 2 else "docs/index.html"

    with open(input_file, "r", encoding="utf-8") as f:
        articles = json.load(f)

    html = render(articles)
    os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[OK] HTML 页面已生成 → {output_file}")


if __name__ == "__main__":
    main()
