"""阶段⑤-b 输出 RSS：docs/feed.xml。

为什么要有这个：日报最大的失败方式是「忘了打开」。
推给阅读器（或微信读书 / Reeder / Inoreader）比指望每天想起来点书签靠谱得多。

只放深读区（必读 + 能用上的 + 线索追踪）。速览区的 111 条塞进 RSS
等于把「宁缺毋滥」这条原则在另一个出口上作废掉 —— 想看全的人会点进页面。
"""
import html
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TZ = timezone(timedelta(hours=8))

SITE = os.environ.get("DIGEST_SITE", "https://vizroi.github.io/daily-ai-digest")
REPO = "https://github.com/Vizroi/daily-ai-digest"

SECTION_CN = {"lead": "今日必读", "relevant": "能用上的", "threads": "线索追踪"}


def esc(s) -> str:
    return html.escape(str(s or ""), quote=False)


def _title(ev: dict) -> str:
    if ev.get("lang") == "zh":
        return ev["title"]
    return ev.get("title_cn") or ev["title"]


def _pubdate(ev: dict, fallback: datetime) -> str:
    raw = ev.get("published")
    if not raw:
        return format_datetime(fallback)
    try:
        # 源里两种写法都有：+00:00 和 Z。fromisoformat 在 3.11 前不认 Z
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return format_datetime(dt)
    except ValueError:
        return format_datetime(fallback)


def _description(ev: dict, section: str) -> str:
    """条目正文。RSS 阅读器只吃 HTML，所以这里独立于 render.py 重排一遍，
    保持朴素 —— 阅读器会剥掉大部分样式。"""
    rows = []
    n = ev.get("coverage", 1)
    cov = f"{n} 家独立源报道" if n > 1 else (ev.get("sources") or ["单源"])[0]
    rows.append(f'<p><strong>{ev.get("score", 0):g} 分</strong> · {esc(cov)} · '
                f'{esc(SECTION_CN.get(section, section))}</p>')

    if ev.get("what"):
        rows.append(f'<p><strong>发生了什么</strong><br>{esc(ev["what"])}</p>')
        if ev.get("why"):
            rows.append(f'<p><strong>为什么重要</strong><br>{esc(ev["why"])}</p>')
        if ev.get("for_you"):
            rows.append(f'<p><strong>对你而言</strong><br>{esc(ev["for_you"])}</p>')
    elif ev.get("summary_raw"):
        rows.append(f'<p>{esc(ev["summary_raw"][:300])}</p>')

    if not ev.get("has_body", True):
        rows.append('<p><em>未取到正文，以上基于 RSS 摘要生成。</em></p>')

    parts = [f'{esc(p["label"])} {"+" if p["value"] > 0 else ""}{p["value"]:g}'
             for p in ev.get("score_parts", [])]
    if parts:
        rows.append(f'<p><small>评分依据：{esc(" / ".join(parts))}</small></p>')

    members = ev.get("members") or []
    if len(members) > 1:
        links = " · ".join(f'<a href="{esc(m["url"])}">{esc(m["source"])}</a>' for m in members)
        rows.append(f'<p><small>全部来源：{links}</small></p>')

    return "".join(rows)


def build(digest: dict) -> str:
    now = (datetime.fromisoformat(digest["generated_at"])
           if digest.get("generated_at") else datetime.now(TZ))
    date = digest.get("date", now.strftime("%Y-%m-%d"))

    items = []
    for section in ("lead", "relevant", "threads"):
        for ev in digest.get(section, []):
            # guid 用事件 key（跨源聚类后的稳定 hash），不用 URL：
            # 同一件事换个源报道，不该在阅读器里变成一条新条目。
            guid = f'{REPO}#{date}-{ev.get("key", "")[:12]}'
            items.append(
                "<item>\n"
                f'  <title>{esc(_title(ev))}</title>\n'
                f'  <link>{esc(ev["url"])}</link>\n'
                f'  <guid isPermaLink="false">{esc(guid)}</guid>\n'
                f'  <pubDate>{_pubdate(ev, now)}</pubDate>\n'
                f'  <category>{esc(SECTION_CN.get(section, section))}</category>\n'
                f'  <description><![CDATA[{_description(ev, section)}]]></description>\n'
                "</item>"
            )

    stats = digest.get("stats", {})
    desc = (f'每天一期。召回 {stats.get("events", 0)} 个事件，'
            f'只有 {len(items)} 条进深读区。排序公式与权重公开在 {REPO}。')

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        '<channel>\n'
        '<title>每日内参 · AI 与游戏开发</title>\n'
        f'<link>{SITE}/</link>\n'
        f'<atom:link href="{SITE}/feed.xml" rel="self" type="application/rss+xml"/>\n'
        f'<description>{esc(desc)}</description>\n'
        '<language>zh-CN</language>\n'
        f'<lastBuildDate>{format_datetime(now)}</lastBuildDate>\n'
        f'<generator>daily-ai-digest v2</generator>\n'
        + "\n".join(items) + "\n"
        '</channel>\n</rss>\n'
    )


def main():
    inp = sys.argv[1] if len(sys.argv) > 1 else "data/digest.json"
    out = sys.argv[2] if len(sys.argv) > 2 else "docs/feed.xml"

    with open(inp, encoding="utf-8") as f:
        digest = json.load(f)

    xml = build(digest)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(xml)
    print(f"[OK] RSS 已生成 → {out}（{xml.count('<item>')} 条）")


if __name__ == "__main__":
    main()
