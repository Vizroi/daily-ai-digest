"""读取本期候选原文；RSS 摘要永远不会被标成已获取正文。"""
import concurrent.futures as futures
import json
import os
import sys

MAX_CHARS = 10000


def extract(url):
    try:
        import requests
        import trafilatura
        response = requests.get(url, timeout=(8, 20), headers={
            "User-Agent": "GameDesignDaily/3.0 (+https://github.com/Vizroi/daily-ai-digest)"})
        response.raise_for_status()
        if len(response.content) > 6_000_000:
            return None
        # Pass bytes so trafilatura can determine the site's encoding.
        text = trafilatura.extract(response.content, include_comments=False, include_tables=True)
        if not text or len(text.strip()) < 400:
            return None
        return text.strip()
    except Exception:
        return None


def enrich(events, workers=6):
    def one(event):
        if event.get("publication_scope", "public") != "public" or event.get("requires_transcript"):
            return event, None
        if event.get("has_body") and event.get("body"):
            return event, event["body"]
        if event.get("content_kind") in {"api_content", "community_selftext"} and event.get("rss_content"):
            return event, event["rss_content"]
        # An excerpt of a question is not a solved problem or full post.
        if "reddit.com" in event.get("url", ""):
            return event, None
        return event, extract(event["url"])
    targets = [event for event in events if event.get("url")]
    with futures.ThreadPoolExecutor(max_workers=workers) as executor:
        for event, body in executor.map(one, targets):
            event["body"] = (body or "")[:MAX_CHARS]
            event["has_body"] = bool(body)
            event["body_truncated"] = bool(event.get("body_truncated") or (body and len(body) > MAX_CHARS))
            kind = event.get("content_kind", "source_excerpt")
            event["content_kind"] = ("community_body" if kind == "community_selftext" else
                                     "official_announcement_body" if kind == "api_content" else
                                     "article_body") if body else kind
    print(f"[OK] 原文读取 {sum(bool(e.get('has_body')) for e in targets)}/{len(targets)}")
    return events


def main():
    inp = sys.argv[1] if len(sys.argv) > 1 else "data/ranked.json"
    out = sys.argv[2] if len(sys.argv) > 2 else inp
    with open(inp, encoding="utf-8") as handle:
        digest = json.load(handle)
    sections = ("news", "features", "feature_candidates", "ai", "ai_features", "ai_feature_candidates") if digest.get("schema_version") == 3 else ("lead", "relevant", "threads")
    enrich([e for section in sections for e in digest.get(section, [])])
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(digest, handle, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
