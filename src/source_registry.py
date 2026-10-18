"""公开来源目录与本地人工线索入口；不把缺日期/视频标题当新闻。"""
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
import config

DATA = Path(__file__).resolve().parent.parent / "data"


def catalog():
    entries = [{**s, "id": "web-" + hashlib.sha1(s["url"].encode()).hexdigest()[:10],
                "platform": "网站 / RSS", "module": "fetch_sources"}
               for s in config.RSS_SOURCES + config.PAGE_SOURCES]
    for module in ("public_sources", "creator_sources", "community_sources"):
        path = DATA / (module + ".json")
        if path.exists():
            values = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(values, dict):
                values = values.get("sources", [])
            entries.extend({**s, "module": module} for s in values)
    return entries


def inbox_articles(now, path=None):
    """用户保存公开文章链接后进入候选队列，文件本身不提交。"""
    path = Path(path) if path else DATA / "source_inbox.json"
    status = {"id": "manual-inbox", "name": "人工线索收件箱", "platform": "手动收录",
              "url": "", "state": "manual", "count": 0, "detail": "可补充公众号、知乎或其他公开原文链接"}
    if not path.exists():
        return [], status
    try:
        items = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(items, list):
            raise ValueError("inbox must be a list")
    except (OSError, ValueError):
        return [], {**status, "state": "error", "detail": "人工线索文件格式不可读取"}
    out = []
    from fetch_sources import _parse_date
    for item in items[:200]:
        if not isinstance(item, dict) or item.get("publication_scope", "public") != "public":
            continue
        url = item.get("url", "")
        if not isinstance(url, str) or urlsplit(url).scheme not in {"https", "http"}:
            continue
        title = str(item.get("title") or "待核验的公开文章")[:300]
        date = _parse_date(item.get("published"))
        out.append({"title": title, "url": url, "source": str(item.get("source") or "人工收录"),
                    "source_id": str(item.get("source_id") or "manual-inbox"), "source_url": url,
                    "platform": str(item.get("platform") or "手动收录"), "tier": 3,
                    "lang": item.get("lang", "zh"), "category": "design", "pool": "main",
                    "published": date.isoformat() if date else None, "undated": date is None,
                    "retrieved_at": now.isoformat(), "summary_raw": "", "rss_content": "",
                    "content_kind": "link_only", "evidence_kind": "manual_link",
                    "discovery_only": True, "requires_review": True, "publication_scope": "public",
                    "signals": {}})
    status.update(count=len(out), detail=f"已收录 {len(out)} 条公开链接，等待核验正文与日期")
    return out, status
