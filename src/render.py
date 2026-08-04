"""阶段⑤渲染：少年漫分镜版式（低饱和印刷版）。

设计意图
────────
读者是一个人，不是流量。页面的唯一任务：让他在 60 秒内决定今天什么值得看，
并且看得见凭什么排这个序。

视觉方向取自少年漫的分镜页：黑墨粗框 + 硬投影分格、集中線、伤害数字、对话气泡。
选它的理由不是好看，是**它天生就是一套优先级语言** —— 一页漫画里哪一格重要，
读者不用被告知，格子大小和网点密度已经说完了。日报要的正是这个。

饱和度按使用者要求整体压低一档：朱红从 #D0021B 降到 #A8423A，
高亮黄从荧光 #FFE94A 降到旧纸黄 #D8BF74，纸色用报纸灰而非亮白。
低饱和让长文能读下去 —— 原色四色印刷适合封面，不适合每天读二十条。

签名元素：标题右上角那个歪着的**伤害数字**。它就是 rank.py 算出的分数，
底下压一条分段覆盖条（几家独立源报道了）。分数被画成打击力度，
而不是藏在角标里 —— 排序逻辑可见 = 排序逻辑可被质疑和调整。

克制的地方（Chanel 的那条建议）：集中線**只给今日必读的第一条**，
伤害数字只出现在深读区；深水区和速览区退回安静的等宽小字。
一页上五个爆点等于没有爆点。
"""
import html
import json
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import DEEP_READ_MIN_SCORE, COVERAGE_WEIGHT, HEALTH_ALERT_DAYS

TZ = timezone(timedelta(hours=8))

WEEKDAY_CN = ["一", "二", "三", "四", "五", "六", "日"]

CSS = """
:root{color-scheme:light}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}

:root{
  /* 报纸灰，不是亮白也不是 AI 默认奶油色 */
  --paper:#EDEAE1;
  --panel:#F8F6F0;
  --ink:#1F1C19;
  --ink-line:#2A2622;      /* 硬投影用，比正文墨色浅一点，边界不至于糊成一团 */
  --ink-soft:#5A554D;
  --ink-faint:#8B8579;
  --rule:#C9C3B6;
  --rule-soft:#DCD7CB;
  /* 降饱和朱红：只用于分数与优先级，绝不他用 */
  --red:#A8423A;
  --red-deep:#8A332C;
  /* 旧纸黄：只用于命中徽章 */
  --mustard:#D8BF74;
  --mono:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  --sans:"Noto Sans SC","PingFang SC","Microsoft YaHei",-apple-system,system-ui,sans-serif;
  --num:"Bangers","Noto Sans SC",var(--sans);
}

html{-webkit-text-size-adjust:100%}
body{
  background:var(--paper);color:var(--ink);
  font-family:var(--sans);font-size:15px;line-height:1.8;
  font-feature-settings:"tnum";
  padding:0 0 90px;
}

.wrap{max-width:820px;margin:0 auto;padding:0 22px}

/* ── 报头 ── */
.masthead{padding:38px 0 0}
.masthead-top{display:flex;align-items:flex-end;gap:16px;flex-wrap:wrap;
  border-bottom:5px solid var(--ink);padding-bottom:8px}
.masthead h1{
  font-weight:900;font-size:42px;line-height:.95;letter-spacing:-.02em;
  transform:skewX(-7deg);text-shadow:4px 4px 0 var(--red);
}
.masthead .dateline{margin-left:auto;font-family:var(--mono);font-size:11px;
  color:var(--ink-soft);text-align:right;line-height:1.65;padding-bottom:3px}
.masthead .dateline b{color:var(--ink);font-weight:700}

/* 读数条：黑白交替的胶片格，编码今天这一期的加工量 */
.readout{display:flex;flex-wrap:wrap;border-bottom:3px solid var(--ink)}
.readout span{font-family:var(--mono);font-size:10.5px;font-weight:700;letter-spacing:.02em;
  padding:5px 11px;border-right:3px solid var(--ink);background:var(--ink);color:var(--paper)}
.readout span:nth-child(even){background:transparent;color:var(--ink)}
.readout span:last-child{border-right:0}

/* ── 栏目名：斜切黑标签 ── */
.section{margin-top:44px}
.lbl{display:flex;align-items:baseline;gap:10px;
  background:var(--ink);color:var(--paper);padding:5px 14px;
  transform:skewX(-7deg);margin-bottom:16px}
.lbl h2{font-weight:900;font-size:14px;letter-spacing:.3em;transform:skewX(7deg)}
.lbl .en{font-family:var(--mono);font-size:9.5px;letter-spacing:.16em;text-transform:uppercase;
  color:var(--mustard);transform:skewX(7deg)}
.lbl .n{margin-left:auto;font-family:var(--mono);font-size:10px;transform:skewX(7deg);
  color:#BDB6A6}
.note{font-family:var(--mono);font-size:11px;color:var(--ink-soft);line-height:1.7;
  margin:-6px 0 16px;padding-left:2px}

/* ── 分格 ── */
.panel{border:3px solid var(--ink);background:var(--panel);
  box-shadow:6px 6px 0 var(--ink-line);margin-bottom:26px}
.panel .top{position:relative;padding:22px 20px 16px}

/* 集中線：只给头条一格。低饱和方案里它靠密度而不是颜色出效果 */
.panel.hero .top::before{content:"";position:absolute;inset:-45%;pointer-events:none;
  background:repeating-conic-gradient(from 0turn at 64% 38%,var(--ink) 0 .5deg,transparent .5deg 3.6deg);
  -webkit-mask:radial-gradient(circle at 64% 38%,transparent 24%,#000 64%);
  mask:radial-gradient(circle at 64% 38%,transparent 24%,#000 64%);opacity:.26}
.panel.hero .top>*{position:relative}

.panel h3{font-weight:900;font-size:26px;line-height:1.32;letter-spacing:-.005em;
  max-width:23em;padding-right:96px}
.panel.hero h3{font-size:30px}
.panel h3 a{color:var(--ink);text-decoration:none;
  border-bottom:2px solid transparent;transition:border-color .15s}
.panel h3 a:hover,.panel h3 a:focus-visible{border-bottom-color:var(--red)}
.panel h3 .orig{display:block;font-size:12px;font-weight:400;color:var(--ink-faint);
  margin-top:7px;line-height:1.55;letter-spacing:0;padding-right:0}

/* ── 签名元素：伤害数字 + 覆盖条 ── */
.dmg{position:absolute;top:14px;right:16px;text-align:center;transform:rotate(8deg);z-index:2}
.dmg b{display:block;font-family:var(--num);font-weight:400;font-size:54px;line-height:.82;
  color:var(--red);-webkit-text-stroke:3px var(--ink);paint-order:stroke fill;letter-spacing:.02em}
.dmg .unit{display:block;font-family:var(--mono);font-size:8.5px;font-weight:700;letter-spacing:.2em;
  color:var(--ink-soft);margin-top:1px}
.bars{display:flex;gap:2px;justify-content:center;margin-top:5px}
.bar{width:7px;height:13px;background:var(--paper);border:2px solid var(--ink);
  transform-origin:bottom;animation:rise .4s cubic-bezier(.2,.8,.2,1) backwards}
.bar.on{background:var(--red)}
.cov{display:block;font-family:var(--mono);font-size:9px;font-weight:700;color:var(--ink);
  margin-top:3px;letter-spacing:.06em}
@keyframes rise{from{transform:scaleY(.12);opacity:0}to{transform:scaleY(1);opacity:1}}

/* ── 评分依据徽章 ── */
/* 留出右上角伤害数字的地盘：标题只有一行时徽章会撞上去 */
.why{display:flex;gap:6px;flex-wrap:wrap;margin-top:14px;padding-right:100px}
.why i{font-style:normal;font-family:var(--mono);font-size:10px;font-weight:700;
  border:2px solid var(--ink);background:var(--mustard);padding:1.5px 7px;white-space:nowrap}
.why i.rel{background:var(--ink);color:var(--paper)}
.why i.neg{background:transparent;border-style:dashed;color:var(--ink-soft);font-weight:400}

/* ── 三段式 ──
   网点底纹只走左侧那条窄带（.segs::before）。
   压在正文下面会明显吃掉可读性 —— 6px 的点阵和 15px 的汉字笔画同一个量级，
   笔画和网点会互相干扰。漫画的网点本来也是铺在留白上，不是铺在对白上。 */
.segs{position:relative;border-top:3px solid var(--ink);padding:18px 20px 8px 40px;
  background:#FCFAF5}
.segs::before{content:"";position:absolute;left:0;top:0;bottom:0;width:16px;
  background-image:radial-gradient(circle at 1px 1px,var(--rule) 1.1px,transparent 1.2px);
  background-size:6px 6px;border-right:1px solid var(--rule-soft)}
.seg{display:grid;grid-template-columns:82px 1fr;gap:16px;padding-bottom:15px}
.seg dt{font-weight:900;font-size:11px;letter-spacing:.06em;text-align:right;padding:4px 10px 0 0;
  border-right:3px solid var(--ink);color:var(--ink)}
.seg dd{font-size:15.5px;line-height:1.9;color:var(--ink)}
.seg.hint dt{border-right-color:var(--rule);color:var(--ink-faint)}
.seg.hint dd{font-size:13px;color:var(--ink-faint)}

/* 对话气泡：只给「对你而言」。全文唯一的圆角，所以它一定被先看到 */
.bub{position:relative;background:#fff;border:3px solid var(--ink);border-radius:20px;
  padding:13px 18px;margin:2px 20px 24px;box-shadow:5px 5px 0 var(--red)}
.bub::after{content:"";position:absolute;left:42px;bottom:-16px;width:0;height:0;
  border:9px solid transparent;border-top:16px solid var(--ink)}
.bub b{display:block;font-size:10.5px;font-weight:900;letter-spacing:.22em;
  color:var(--red-deep);margin-bottom:4px}
.bub p{font-size:15.5px;line-height:1.88;color:var(--ink)}
.bub.none{box-shadow:5px 5px 0 var(--rule);border-color:var(--rule)}
.bub.none::after{border-top-color:var(--rule)}
.bub.none b,.bub.none p{color:var(--ink-faint)}

/* ── 来源脚注 ── */
.srcs{font-family:var(--mono);font-size:10.5px;color:var(--ink-faint);
  padding:0 20px 15px;line-height:1.9}
.srcs a{color:var(--ink-soft);text-decoration:none;border-bottom:1px dotted var(--rule)}
.srcs a:hover,.srcs a:focus-visible{color:var(--red);border-bottom-color:var(--red)}
.srcs .sep{opacity:.5;padding:0 5px}
.fu{font-family:var(--mono);font-size:10.5px;color:var(--ink-soft);margin-top:11px}

/* ── 深水区：安静的窄格，不给伤害数字 ── */
.quiet{border:3px solid var(--ink);background:var(--panel)}
.quiet .sub{font-family:var(--mono);font-size:9.5px;font-weight:700;letter-spacing:.14em;
  text-transform:uppercase;background:var(--ink);color:var(--mustard);padding:4px 14px}
.qi{padding:15px 18px;border-bottom:1px solid var(--rule-soft)}
.qi:last-child{border-bottom:0}
.qi h4{font-size:16px;font-weight:700;line-height:1.5}
.qi h4 a{color:var(--ink);text-decoration:none;border-bottom:1.5px solid transparent}
.qi h4 a:hover,.qi h4 a:focus-visible{border-bottom-color:var(--red)}
.qi .meta{font-family:var(--mono);font-size:10px;color:var(--ink-faint);margin-top:5px}
.qi .pitch{font-size:13.5px;color:var(--ink-soft);margin-top:6px;line-height:1.72}
.qi .pitch b{font-family:var(--mono);font-size:9.5px;font-weight:700;letter-spacing:.1em;
  color:var(--red-deep);margin-right:7px}

/* ── 速览 ── */
details.brief{border:3px solid var(--ink);background:var(--panel)}
details.brief summary{font-family:var(--mono);font-size:11.5px;font-weight:700;color:var(--ink);
  cursor:pointer;padding:11px 16px;list-style:none;display:flex;align-items:center;gap:9px}
details.brief summary::-webkit-details-marker{display:none}
details.brief summary::before{content:"＋";color:var(--red);font-size:13px;width:14px}
details.brief[open] summary::before{content:"－"}
details.brief[open] summary{border-bottom:3px solid var(--ink)}
.brief-row{display:flex;gap:12px;align-items:baseline;padding:7px 16px;font-size:13.5px;
  line-height:1.6;border-bottom:1px solid var(--rule-soft)}
.brief-row:last-child{border-bottom:0}
.brief-row .s{font-family:var(--mono);font-size:10.5px;font-weight:700;color:var(--ink-faint);
  min-width:28px;text-align:right;flex-shrink:0}
.brief-row a{color:var(--ink-soft);text-decoration:none;flex:1}
.brief-row a:hover,.brief-row a:focus-visible{color:var(--red)}
.brief-row .o{font-family:var(--mono);font-size:10px;color:var(--ink-faint);flex-shrink:0}

/* ── 空区块 ── */
.empty{border:3px dashed var(--rule);padding:20px;font-family:var(--mono);font-size:11.5px;
  color:var(--ink-soft);line-height:1.85}

/* ── 页脚 ── */
footer{margin-top:56px;border-top:5px solid var(--ink);padding-top:13px;
  font-family:var(--mono);font-size:10.5px;color:var(--ink-faint);line-height:1.95}
footer a{color:var(--ink-soft)}
footer .health{margin-top:6px;color:#8A6A22}

a:focus-visible,summary:focus-visible{outline:3px solid var(--red);outline-offset:2px}

@media (max-width:640px){
  body{font-size:14.5px}
  .wrap{padding:0 15px}
  .masthead{padding:24px 0 0}
  .masthead h1{font-size:30px}
  .masthead .dateline{margin-left:0;text-align:left}
  .panel{box-shadow:4px 4px 0 var(--ink-line);margin-bottom:20px}
  .panel .top{padding:18px 15px 14px}
  /* 伤害数字在窄屏改成标题上方的横排，不再压住标题 */
  .dmg{position:static;transform:none;text-align:left;display:flex;align-items:flex-end;gap:10px;
    margin-bottom:10px}
  .dmg b{font-size:40px;-webkit-text-stroke:2.5px var(--ink)}
  .dmg .unit{margin:0 0 6px}
  .bars{margin:0 0 7px}
  .cov{margin:0 0 6px}
  .panel h3,.panel.hero h3{font-size:21px;padding-right:0}
  .why{padding-right:0}
  .segs{padding:15px 15px 5px 28px}
  .segs::before{width:12px}
  .seg{grid-template-columns:1fr;gap:1px;padding-bottom:13px}
  .seg dt{text-align:left;border-right:0;border-left:3px solid var(--ink);padding:0 0 0 9px}
  .bub{margin:2px 15px 20px;padding:12px 15px}
  .srcs{padding:0 15px 13px}
  .section{margin-top:34px}
}

@media (prefers-reduced-motion:reduce){
  *{animation:none!important;transition:none!important}
}

@media print{
  body{background:#fff}
  .panel{box-shadow:none;break-inside:avoid}
  .panel.hero .top::before,.bars,details.brief{display:none}
}
"""

TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<meta name="description" content="__DESC__">
<link rel="alternate" type="application/rss+xml" title="每日内参" href="feed.xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bangers&family=Noto+Sans+SC:wght@400;700;900&family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>__CSS__</style>
</head>
<body>
<div class="wrap">

<header class="masthead">
  <div class="masthead-top">
    <h1>每日内参</h1>
    <div class="dateline">
      <b>__DATE_CN__</b> 周__WEEKDAY__<br>__TIME__ 生成 · 第 __ISSUE__ 期
    </div>
  </div>
  <div class="readout">__READOUT__</div>
</header>

__SECTIONS__

<footer>
  排序由 rank.py 计算，公式与权重见仓库 <a href="https://github.com/Vizroi/daily-ai-digest">src/rank.py</a>。<br>
  分数 = 跨源覆盖×__COVW__ + 源权威档位 + log(社区热度) + 相关词命中 − 重复报道惩罚。<br>
  召回 __RECALL__ 源 · 聚类 __EVENTS__ 事件 · 深读 __DEEPN__ 条抓取正文全文<br>
  <a href="feed.xml">RSS 订阅</a>（只推深读区）<span style="opacity:.5;padding:0 6px">·</span><a href="archive/__DATE_ISO__.html">本期归档</a>__HEALTH__
</footer>

</div>
</body>
</html>
"""


# ─── 工具 ────────────────────────────────────────────────────

def esc(s) -> str:
    return html.escape(str(s or ""), quote=True)


def _title_cn(ev: dict) -> str:
    """中文标题优先，英文原标题作副标题。"""
    if ev.get("lang") == "zh":
        return esc(ev["title"])
    return esc(ev.get("title_cn") or ev["title"])


def _orig_line(ev: dict) -> str:
    if ev.get("lang") == "zh" or not ev.get("title_cn"):
        return ""
    return f'<span class="orig">{esc(ev["title"])}</span>'


def _dmg(ev: dict) -> str:
    """签名元素：歪着的伤害数字 + 分段覆盖条。数字就是 rank.py 的分数。"""
    cov = min(int(ev.get("coverage", 1)), 5)
    bars = "".join(
        f'<span class="bar{" on" if i < cov else ""}" style="animation-delay:{i * 45}ms"></span>'
        for i in range(5)
    )
    n = ev.get("coverage", 1)
    cov_label = f"{n} 源" if n > 1 else "单源"
    return (
        f'<div class="dmg">'
        f'<b>{ev.get("score", 0):g}</b><span class="unit">PTS</span>'
        f'<span class="bars" role="img" '
        f'aria-label="跨源覆盖 {cov_label}，计 {cov * COVERAGE_WEIGHT} 分">{bars}</span>'
        f'<span class="cov">{esc(cov_label)}</span>'
        f'</div>'
    )


def _why(ev: dict) -> str:
    """评分依据徽章。覆盖度已由读数条表达，这里不重复。"""
    chips = []
    for p in ev.get("score_parts", []):
        label, val = p["label"], p["value"]
        if label == "单源" or label.endswith("源报道"):
            continue
        cls = ""
        if val < 0:
            cls = "neg"
        elif label.startswith("命中") or label.startswith("战斗"):
            cls = "rel"
        sign = "+" if val > 0 else ""
        attr = f' class="{cls}"' if cls else ""
        chips.append(f'<i{attr}>{esc(label)} {sign}{val:g}</i>')
    return f'<div class="why">{"".join(chips)}</div>' if chips else ""


def _sources(ev: dict) -> str:
    members = ev.get("members") or []
    if len(members) <= 1:
        srcs = ev.get("sources") or []
        base = (f'<a href="{esc(ev["url"])}" target="_blank" rel="noopener">'
                f'{esc(srcs[0] if srcs else "原文")}</a>')
    else:
        base = '<span class="sep">/</span>'.join(
            f'<a href="{esc(m["url"])}" target="_blank" rel="noopener">{esc(m["source"])}</a>'
            for m in members
        )
    hn = ev.get("hn_url")
    extra = (f'<span class="sep">·</span><a href="{esc(hn)}" target="_blank" '
             f'rel="noopener">HN 讨论</a>') if hn else ""
    return f'<div class="srcs">{base}{extra}</div>'


def _segments(ev: dict) -> str:
    """三段式。「对你而言」单独做成对话气泡，脱离网点格。"""
    what, why, you = ev.get("what"), ev.get("why"), ev.get("for_you")
    if not what:
        raw = ev.get("summary_raw") or ""
        if not raw:
            return ""
        return ('<div class="segs"><dl class="seg"><dt>原文摘要</dt>'
                f'<dd>{esc(raw[:260])}</dd></dl></div>')

    rows = [f'<dl class="seg"><dt>发生了什么</dt><dd>{esc(what)}</dd></dl>']
    if why:
        rows.append(f'<dl class="seg"><dt>为什么重要</dt><dd>{esc(why)}</dd></dl>')
    if not ev.get("has_body", True):
        rows.append('<dl class="seg hint"><dt>提示</dt>'
                    '<dd>未取到正文，以上基于 RSS 摘要生成</dd></dl>')
    out = f'<div class="segs">{"".join(rows)}</div>'

    if you:
        none = " none" if "无直接关系" in you else ""
        out += (f'<div class="bub{none}"><b>对你而言</b>'
                f'<p>{esc(you)}</p></div>')
    return out


def _item(ev: dict, hero: bool = False) -> str:
    followup = ""
    if ev.get("followup"):
        fu = ev["followup"]
        followup = (f'<div class="fu">↳ {esc(fu.get("first_seen", ""))} 首次报道，'
                    f'累计出现 {fu.get("times", 1)} 次</div>')
    cls = "panel hero" if hero else "panel"
    return (
        f'<article class="{cls}">'
        f'<div class="top">{_dmg(ev)}'
        f'<h3><a href="{esc(ev["url"])}" target="_blank" rel="noopener">{_title_cn(ev)}</a>'
        f'{_orig_line(ev)}</h3>{_why(ev)}{followup}</div>'
        f'{_segments(ev)}{_sources(ev)}'
        f'</article>'
    )


def _section(title: str, en: str, count: str, inner: str, note: str = "") -> str:
    note_html = f'<div class="note">{note}</div>' if note else ""
    return (f'<section class="section"><div class="lbl">'
            f'<h2>{esc(title)}</h2><span class="en">{esc(en)}</span>'
            f'<span class="n">{esc(count)}</span></div>{note_html}{inner}</section>')


def _quiet_item(ev: dict, kind: str) -> str:
    """深水区条目：不给伤害数字，保持安静。"""
    meta_bits = []
    if kind == "paper":
        up = ev.get("signals", {}).get("hf_upvotes", 0)
        if up:
            meta_bits.append(f"社区 ▲{up}")
        if ev.get("authors"):
            meta_bits.append(esc(ev["authors"]))
    else:
        if ev.get("repo_lang"):
            meta_bits.append(esc(ev["repo_lang"]))
        st = ev.get("signals", {}).get("stars_today", 0)
        if st:
            meta_bits.append(f"+{st}★ 今日")
        if ev.get("repo_stars"):
            meta_bits.append(f"{ev['repo_stars']:,} ★ 总计")

    pitch = ev.get("pitch") or ev.get("what") or ev.get("summary_raw") or ""
    pitch_html = ""
    if pitch:
        lead = "<b>值得读</b>" if kind == "paper" else "<b>做什么的</b>"
        pitch_html = f'<div class="pitch">{lead}{esc(pitch[:200])}</div>'

    meta_html = f'<div class="meta">{" · ".join(meta_bits)}</div>' if meta_bits else ""
    return (f'<div class="qi">'
            f'<h4><a href="{esc(ev["url"])}" target="_blank" rel="noopener">{_title_cn(ev)}</a></h4>'
            f'{meta_html}{pitch_html}</div>')


def _brief_rows(items: list[dict]) -> str:
    rows = []
    for ev in items:
        srcs = ev.get("sources") or []
        cov = f'{ev.get("coverage",1)}源' if ev.get("coverage", 1) > 1 else (srcs[0] if srcs else "")
        rows.append(
            f'<div class="brief-row"><span class="s">{ev.get("score",0):g}</span>'
            f'<a href="{esc(ev["url"])}" target="_blank" rel="noopener">{_title_cn(ev)}</a>'
            f'<span class="o">{esc(cov)}</span></div>'
        )
    return "".join(rows)


# ─── 主渲染 ──────────────────────────────────────────────────

def render(digest: dict, health: dict | None = None) -> str:
    now = (datetime.fromisoformat(digest["generated_at"])
           if digest.get("generated_at") else datetime.now(TZ))
    lead = digest.get("lead", [])
    relevant = digest.get("relevant", [])
    threads = digest.get("threads", [])
    papers = digest.get("papers", [])
    graphics = digest.get("graphics", [])
    repos = digest.get("repos", [])
    diverse = digest.get("diverse", [])
    brief = digest.get("brief", [])
    stats = digest.get("stats", {})

    secs = []

    # ① 今日必读 —— 阈值制，宁可只有 2 条。第一条给集中線，其余不给
    if lead:
        inner = "".join(_item(e, hero=(i == 0)) for i, e in enumerate(lead))
        secs.append(_section("今日必读", "lead", f"{len(lead)} 条", inner))
    else:
        secs.append(_section(
            "今日必读", "lead", "0 条",
            f'<div class="empty">今天没有事件达到必读阈值（{DEEP_READ_MIN_SCORE} 分）。<br>'
            '这是阈值制的正常结果，不是抓取失败 —— 与其凑数，不如留白。</div>'))

    # ② 能用上的 —— 为空则整块隐藏，不塞垃圾
    if relevant:
        inner = "".join(_item(e) for e in relevant)
        secs.append(_section(
            "能用上的", "for your work", f"{len(relevant)} 条", inner,
            "命中 战斗设计 / UE / 动画 / 网络同步 / 性能 相关词，无论分数高低都会冒头；"
            "战斗类词加权更高，所以排在前面。<br>社区源只算标题命中，正文里顺口提一句不算；"
            "抓不到正文的一律退回速览。"))

    # ③ 线索追踪
    if threads:
        inner = "".join(_item(e) for e in threads)
        secs.append(_section("线索追踪", "follow-up", f"{len(threads)} 条", inner,
                             "14 天内报过、今天又有新报道的事件。"))

    # ④ 深水区
    deep_inner = ""
    if graphics:
        deep_inner += ('<div class="sub">图形学 / 动画 · arXiv cs.GR</div>'
                       + "".join(_quiet_item(e, "paper") for e in graphics))
    if papers:
        deep_inner += ('<div class="sub">AI 论文 · HuggingFace 社区票选</div>'
                       + "".join(_quiet_item(e, "paper") for e in papers))
    if repos:
        deep_inner += ('<div class="sub">开源 · GitHub Trending</div>'
                       + "".join(_quiet_item(e, "repo") for e in repos))
    if deep_inner:
        secs.append(_section("深水区", "papers & repos",
                             f"{len(graphics) + len(papers)} 论文 · {len(repos)} 开源",
                             f'<div class="quiet">{deep_inner}</div>'))

    # ⑤ 跨界视野
    if diverse:
        secs.append(_section(
            "跨界视野", "off-topic", "1 条",
            f'<div class="quiet">{"".join(_quiet_item(e, "repo") for e in diverse)}</div>',
            "固定优质池取最高分，不随机抽取。"))

    # ⑥ 一行速览
    if brief:
        secs.append(_section(
            "一行速览", "the rest", f"{len(brief)} 条",
            f'<details class="brief"><summary>展开其余 {len(brief)} 条（按分数排序）</summary>'
            f'{_brief_rows(brief)}</details>'))

    readout = "".join([
        f'<span>召回 {stats.get("events", 0)} 事件</span>',
        f'<span>多源交叉 {stats.get("multi_source", 0)}</span>',
        f'<span>深读 {len(lead) + len(relevant)}</span>',
        f'<span>速览 {len(brief)}</span>',
    ])

    health_html = ""
    if health:
        # 只报连续零产出的源。当天 0 条不算异常 —— 官方博客本来就不天天发，
        # 天天喊警报的结果是这行字被彻底忽略，真挂了也看不见。
        streak = health.get("zero_streak") or {}
        dead = sorted((v, k) for k, v in streak.items() if v >= HEALTH_ALERT_DAYS)
        if dead:
            items = "、".join(f"{esc(k)}（{v} 天）" for v, k in reversed(dead))
            health_html = (f'<div class="health">⚠ 连续 {HEALTH_ALERT_DAYS} 天以上零产出，'
                           f'建议在 config.py 里换掉：{items}</div>')

    issue = (now.date() - datetime(2026, 1, 1, tzinfo=TZ).date()).days + 1
    out = TEMPLATE
    for k, v in {
        "__TITLE__": f'每日内参 · {now.strftime("%Y-%m-%d")}',
        "__DESC__": (f'今日必读 {len(lead)} 条，深读 {len(lead) + len(relevant)} 条，'
                     f'速览 {len(brief)} 条。'),
        "__CSS__": CSS,
        "__DATE_CN__": f'{now.year} 年 {now.month} 月 {now.day} 日',
        "__DATE_ISO__": digest.get("date") or now.strftime("%Y-%m-%d"),
        "__WEEKDAY__": WEEKDAY_CN[now.weekday()],
        "__TIME__": now.strftime("%H:%M"),
        "__ISSUE__": str(issue),
        "__READOUT__": readout,
        "__SECTIONS__": "".join(secs),
        "__COVW__": str(COVERAGE_WEIGHT),
        "__RECALL__": str(len(set(
            s for e in (lead + relevant + threads + brief) for s in e.get("sources", [])))),
        "__EVENTS__": str(stats.get("events", 0)),
        "__DEEPN__": str(sum(1 for e in lead + relevant + threads if e.get("has_body"))),
        "__HEALTH__": health_html,
    }.items():
        out = out.replace(k, v)
    return out


def main():
    inp = sys.argv[1] if len(sys.argv) > 1 else "data/digest.json"
    out = sys.argv[2] if len(sys.argv) > 2 else "docs/index.html"
    # 默认就读 health.json —— 源健康度警告是设计的一部分，不该需要手动开启
    health_path = sys.argv[3] if len(sys.argv) > 3 else "data/health.json"

    with open(inp, encoding="utf-8") as f:
        digest = json.load(f)

    health = None
    if health_path and os.path.exists(health_path):
        with open(health_path, encoding="utf-8") as f:
            health = json.load(f)

    page = render(digest, health)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"[OK] 页面已生成 → {out} ({len(page) // 1024} KB)")

    # 归档一份，避免早晚两版互相覆盖（v1 的 bug#7）
    arch_dir = os.path.join(os.path.dirname(os.path.abspath(out)), "archive")
    os.makedirs(arch_dir, exist_ok=True)
    arch = os.path.join(arch_dir, f'{digest.get("date", "unknown")}.html')
    # 归档页深一层目录，页脚那两个相对链接要跟着改，否则点开是 404
    arch_page = (page.replace('href="feed.xml"', 'href="../feed.xml"')
                     .replace('href="archive/', 'href="'))
    with open(arch, "w", encoding="utf-8") as f:
        f.write(arch_page)
    print(f"[OK] 已归档 → {arch}")


if __name__ == "__main__":
    main()
