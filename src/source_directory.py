"""Render the public source catalog and the most recent collection report."""
from datetime import datetime, timedelta, timezone
from collections import Counter
from html import escape
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

from source_registry import catalog as load_catalog
from site_navigation import SITE_NAV_CSS, render_site_navigation

STATE_LABELS = {
    "ok": "读取正常", "empty": "读取正常 · 无新内容", "degraded": "部分读取",
    "blocked": "平台访问限制", "error": "读取异常",
    "needs_auth": "待接入 / 待授权", "manual": "手动收录", "not_checked": "尚未检查",
}
PLATFORM_LABELS = {"steam": "Steam", "reddit": "Reddit", "discord": "Discord", "youtube": "YouTube", "bilibili": "Bilibili"}


def _safe_url(value):
    return value if isinstance(value, str) and urlsplit(value).scheme in ("https", "http") else ""


def _public_detail(value):
    """Show access explanations, never credentials, environment names or channel payloads."""
    text = str(value or "")
    text = re.sub(r"(?<![A-Z0-9_])[A-Z][A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API_KEY|CLIENT_ID|CHANNEL_IDS?)(?![A-Z0-9_])", "访问授权", text)
    text = re.sub(r"(?i)\bBearer\s+[^\s，。;]+", "[授权信息已隐藏]", text)
    text = re.sub(r"(?i)(?:api[_-]?key|token|password|secret)\s*[:=]\s*[^\s，。;]+", "[授权信息已隐藏]", text)
    return text[:600]


def _count(value):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _time(value):
    if not value:
        return "尚无检查报告"
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        dt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M") + "（北京时间）"
    except ValueError:
        return str(value)[:80]


def render_directory(report, catalog):
    report = report if isinstance(report, dict) else {}
    statuses = {s.get("id"): s for s in report.get("sources", []) if isinstance(s, dict) and s.get("id")}
    entries = list(catalog or [])
    external_count = len(entries)
    alternatives = {}
    for entry in entries:
        for source_id in entry.get("alternative_for", []):
            alternatives.setdefault(source_id, []).append(entry)
    known = {item.get("id") for item in entries}
    # The manual inbox has a run status even though it isn't an external catalog source.
    entries.extend(s for sid, s in statuses.items() if sid not in known)
    rows, platform_options = [], set()
    state_counts = Counter()
    present_states = set()
    for src in entries:
        source_id = str(src.get("id", ""))
        status = statuses.get(source_id, {})
        state = status.get("state", "not_checked")
        if state not in STATE_LABELS:
            state = "error"
        state_counts[state] += 1
        platform = PLATFORM_LABELS.get(src.get("platform"), src.get("platform") or "其他")
        name = str(src.get("name") or status.get("name") or "未命名来源")
        platform_options.add(platform)
        present_states.add(state)
        count = _count(status.get("count")) if status else None
        if state in ("needs_auth", "blocked", "error", "not_checked") and not count:
            count = None
        count_text = str(count) if count is not None else "—"
        url = _safe_url(src.get("url") or status.get("url"))
        title = f'<a href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">{escape(name)} <span aria-hidden="true">↗</span></a>' if url else escape(name)
        detail = _public_detail(status.get("detail")) if status else "此来源已登记，尚未完成本轮检查。"
        tags = []
        if src.get("lang") in ("zh", "en"):
            tags.append("中文" if src["lang"] == "zh" else "英文")
        if src.get("adapter") in ("youtube", "bilibili") or platform in ("YouTube", "Bilibili"):
            tags.append("视频待看")
        if src.get("classic_discovery"):
            tags.append("经典阅读候选")
        if src.get("requires_review") or src.get("tier") == 3:
            tags.append("需编辑审核")
        if src.get("publication_scope") == "restricted":
            tags.append("不对外发布")
        tags_html = "".join(f'<span class="tag">{escape(t)}</span>' for t in tags)
        alternate_links = [f'<a href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">{escape(str(item.get("name") or "官网"))} ↗</a>'
                           for item in alternatives.get(source_id, []) if (url := _safe_url(item.get("url")))]
        alternative_html = '<p class="alternative">同一机构另有公开网站：' + "、".join(alternate_links) + "（独立来源）</p>" if alternate_links else ""
        rows.append(f'''<article class="source" data-platform="{escape(platform, quote=True)}" data-state="{escape(state)}">
  <div class="source-main"><div class="source-platform">{escape(platform)}</div><h2>{title}</h2><div class="tags">{tags_html}</div><p>{escape(detail)}</p>{alternative_html}</div>
  <div class="source-result"><span class="status {escape(state)}">{STATE_LABELS[state]}</span><div class="source-count"><strong>{count_text}</strong><span>条候选</span></div></div>
</article>''')
    platforms = '<option value="">全部平台</option>' + "".join(f'<option value="{escape(p, quote=True)}">{escape(p)}</option>' for p in sorted(platform_options))
    states = '<option value="">全部状态</option>' + "".join(f'<option value="{state}">{label}</option>' for state, label in STATE_LABELS.items() if state in present_states)
    counts = report.get("counts") or {}
    metrics = []
    for key, label in (("raw", "本轮读取"), ("deduplicated", "链接去重后"), ("retained", "本轮保留")):
        value = _count(counts.get(key))
        metrics.append(f'<div class="metric"><strong>{value if value is not None else "—"}</strong><span>{label}</span></div>')
    metrics.append(f'<div class="metric"><strong>{external_count}</strong><span>外部来源 · 含待接入</span></div>')
    summary_groups = (
        ("normal", "正常读取", state_counts["ok"] + state_counts["empty"]),
        ("degraded", "部分读取", state_counts["degraded"]),
        ("blocked", "访问受限", state_counts["blocked"]),
        ("error", "读取异常", state_counts["error"]),
        ("needs_auth", "待接入 / 待授权", state_counts["needs_auth"]),
        ("manual", "手动入口", state_counts["manual"]),
        ("not_checked", "尚未检查", state_counts["not_checked"]),
    )
    summary = "".join(f'<span class="health-item {state}">{label} <strong>{count}</strong></span>'
                      for state, label, count in summary_groups if count)
    withheld = _count(counts.get("restricted_withheld"))
    hidden_note = f"本轮另有 {withheld} 条受限内容未进入公开日报。" if withheld else ""
    report_note = "检查报告暂不可用，下面保留来源登记信息。" if report.get("report_error") else ""
    return '''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>信息来源 · 游戏策划日报</title><meta name="description" content="游戏策划日报的中英文来源、候选采集数量和公开访问状态。">
<style>
:root{color-scheme:light;--paper:#f6f5f0;--ink:#24332e;--muted:#65746c;--line:#dce2d8;--green:#29674b;--soft:#e9f0e8}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font-family:system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;line-height:1.65}a{color:inherit;text-decoration:none}a:hover{text-decoration:underline}a:focus-visible,select:focus-visible,input:focus-visible{outline:3px solid #638e68;outline-offset:4px}.wrap{width:min(1080px,calc(100% - 48px));margin:auto}.top{padding:24px 0;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--line);font-size:14px}.brand{font-weight:750;letter-spacing:.04em}.back{color:var(--green)}header{padding:48px 0 26px}.eyebrow{font-size:12px;letter-spacing:.14em;color:var(--green);font-weight:750}h1{font-size:clamp(30px,5vw,44px);line-height:1.2;letter-spacing:-.04em;margin:10px 0 18px}.intro{max-width:700px;color:var(--muted);margin:0;font-size:16px}.checked{font-size:12px;color:var(--muted);margin-top:18px}.metrics{display:grid;grid-template-columns:repeat(4,1fr);background:#fff;border:1px solid var(--line);border-radius:16px;margin:6px 0 26px;overflow:hidden}.metric{padding:19px 25px;border-right:1px solid var(--line)}.metric:last-child{border:0}.metric strong{font-size:29px;line-height:1.2;font-weight:650;display:block;letter-spacing:-.04em}.metric span{font-size:12px;color:var(--muted)}.guide{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;margin-bottom:30px}.guide strong{font-size:13px;color:var(--green)}.guide p{font-size:12px;color:var(--muted);margin:5px 0 0}.filters{display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap;padding:20px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line);margin-bottom:8px}.filters label{font-size:11px;font-weight:600;color:var(--muted);display:flex;flex-direction:column;gap:5px}.filters select,.filters input{height:40px;font:inherit;font-size:13px;color:var(--ink);background:white;border:1px solid #d3dcd2;border-radius:8px;padding:0 12px;max-width:100%}.filters select{min-width:158px}.filters .search{flex:1;min-width:180px}#visible-count{font-size:12px;color:var(--muted);padding-bottom:8px;white-space:nowrap}.source{display:flex;gap:28px;justify-content:space-between;padding:25px 8px;border-bottom:1px solid var(--line)}.source[hidden]{display:none}.source-main{min-width:0;flex:1}.source-platform{color:var(--muted);font-size:10px;letter-spacing:.08em}.source h2{font-size:18px;line-height:1.4;margin:4px 0 9px;font-weight:650;overflow-wrap:anywhere}.source h2 a span{color:#89a08e;font-size:13px;margin-left:5px}.tags{display:flex;flex-wrap:wrap;gap:5px}.tag{font-size:10px;color:#5a6c60;background:#eaf0e7;border-radius:4px;padding:2px 6px}.source p{font-size:12px;color:var(--muted);margin:10px 0 0;max-width:720px;overflow-wrap:anywhere}.source-result{min-width:105px;text-align:right;flex-shrink:0}.status{font-size:11px;background:#eceeea;color:#647067;border-radius:30px;display:inline-block;padding:3px 10px}.status.ok{color:#225d3c;background:#e1edde}.status.error,.status.blocked{color:#8b532b;background:#f4e6d8}.status.needs_auth,.status.manual{color:#62517e;background:#ece6f3}.source-count{margin-top:11px}.source-count strong{font-weight:600;font-size:25px;line-height:1.2}.source-count span{font-size:10px;color:var(--muted);display:block}#empty{padding:36px;text-align:center;color:var(--muted)}footer{padding:30px 0 40px;color:var(--muted);font-size:11px}.notice{font-size:12px;color:var(--muted)}@media(max-width:640px){.wrap{width:calc(100% - 32px)}.top{padding:18px 0}header{padding-top:32px}.metrics{grid-template-columns:repeat(2,1fr)}.metric{padding:16px 20px;border-bottom:1px solid var(--line)}.metric:nth-child(2){border-right:0}.metric:nth-child(3){border-bottom:0}.guide{grid-template-columns:1fr;gap:14px}.filters{gap:9px}.filters label{flex:1;min-width:0}.filters select{min-width:0;width:100%}.filters .search{flex-basis:100%}.source{gap:12px;padding:22px 0}.source h2{font-size:16px}.source-result{min-width:88px}.status{font-size:10px;padding:3px 7px}.source-count strong{font-size:23px}#visible-count{width:100%;padding:0}}
''' + SITE_NAV_CSS + ''':root{--paper:#f1ede3;--ink:#292d27;--line:#d1d0c1;--green:#4c6152;--muted:#74796d}.wrap{width:min(1180px,calc(100% - 64px))}header{padding:26px 0 22px}h1{font-family:Georgia,"Songti SC",SimSun,serif;font-size:36px;letter-spacing:0;margin:0 0 12px}.intro{font-size:13px}.eyebrow{display:none}.health-summary{display:flex;gap:10px 22px;flex-wrap:wrap;padding:0 0 22px;font-size:12px}.health-item{color:var(--muted)}.health-item strong{margin-left:3px;color:var(--ink)}.status.empty{background:#e1edde;color:#225d3c}.status.degraded{background:#f4e6d8;color:#8b532b}.source-result{max-width:160px}@media(max-width:640px){.wrap{width:calc(100% - 28px)}header{padding-top:22px}h1{font-size:29px}.source-result{max-width:112px}.health-summary{gap:8px 18px}}</style></head><body><div class="wrap">''' + render_site_navigation("sources") + '''
<header><div class="eyebrow">SOURCES &amp; EDITORIAL</div><h1>信息来源</h1><p class="intro">日报与 AI 页的来源登记、最近一次采集状态和候选数量。已登记的来源中，部分仍待接入或需要手动收录。</p><p class="checked"><a href="market.html#methodology">Steam 市场的数据口径与来源</a></p><div class="checked">最近检查：''' + escape(_time(report.get("checked_at"))) + '''</div></header>
<section class="metrics" aria-label="采集统计">''' + "".join(metrics) + '''</section>
<section class="health-summary" aria-label="入口状态汇总">''' + summary + '''</section>
<section class="guide" aria-label="状态说明"><div><strong>无新内容：读取成功</strong><p>来源可以访问，本轮没有符合时间窗口的候选。新闻通常看近 72 小时，慢更新设计源看近 30 天。</p></div><div><strong>部分读取 / 访问受限：查看原因</strong><p>部分读取表示只取到了标题或部分文章；访问受限、读取异常表示本轮未完成采集。读取失败或待接入时，以「—」代替 0。</p></div><div><strong>待接入 / 手动收录：尚非自动来源</strong><p>Reddit、Discord 需要配置获准的访问权限；公众号通过单篇公开链接手动收录。</p></div></section>
<div class="filters" role="search"><label>平台<select id="platform">''' + platforms + '''</select></label><label>访问状态<select id="state">''' + states + '''</select></label><label class="search">搜索来源<input id="query" type="search" placeholder="来源名称、语言或关键词" autocomplete="off"></label><span id="visible-count" aria-live="polite">''' + str(len(entries)) + ''' 个入口</span></div>
<main id="sources">''' + "\n".join(rows) + '''</main><p id="empty" class="empty" hidden>没有符合当前条件的来源。</p>
<p class="notice">''' + escape(" ".join(p for p in (hidden_note, report_note) if p)) + '''</p><footer>候选数量不等于刊登数量；内容还需经过日期、相关性与正文核验。视频标题与简介仅作为待看线索。<br>状态随日报采集更新；没有检查记录时显示「尚未检查」。本页不展示私域消息和访问凭据。</footer></div>
<script>
const rows=[...document.querySelectorAll('.source')],platform=document.querySelector('#platform'),state=document.querySelector('#state'),query=document.querySelector('#query');
function filter(){let count=0;const term=query.value.trim().toLocaleLowerCase();for(const row of rows){const show=(!platform.value||row.dataset.platform===platform.value)&&(!state.value||row.dataset.state===state.value)&&(!term||row.textContent.toLocaleLowerCase().includes(term));row.hidden=!show;if(show)count++;}document.querySelector('#visible-count').textContent=count+' / '+rows.length+' 个入口';document.querySelector('#empty').hidden=count!==0;}
platform.addEventListener('change',filter);state.addEventListener('change',filter);query.addEventListener('input',filter);
</script></body></html>'''


def main():
    inp = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/source_report.json")
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("docs/sources.html")
    report = {}
    if inp.exists():
        try:
            report = json.loads(inp.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            report = {"report_error": True}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_directory(report, load_catalog()), encoding="utf-8")
    print(f"[OK] 信息来源目录 → {out}")


if __name__ == "__main__":
    main()
