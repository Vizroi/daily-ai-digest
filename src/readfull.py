"""阶段④-a 抓正文：只对进入深读区的十几条抓全文。

这是「摘要没信息量」的正面解药。
v1 给 LLM 的输入是 300 字符的 RSS 摘要 —— 它不可能产出比标题更多的信息。
"""
import concurrent.futures as futures
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MAX_CHARS = 6000
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/121.0 Safari/537.36")


def extract(url: str) -> str | None:
    """抓正文。trafilagura 专为此设计，比 readability 干净得多。"""
    try:
        import trafilatura
    except ImportError:
        print("[WARN] 未安装 trafilatura，跳过正文抓取")
        return None
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return None
        text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=True,
            no_fallback=False,
        )
        if not text:
            return None
        text = text.strip()
        return text[:MAX_CHARS] if len(text) > 200 else None
    except Exception:
        return None


def enrich(events: list[dict], workers: int = 6) -> list[dict]:
    """给每个 event 加 body 字段。抓不到就留空，summarize 会降级并诚实标注。"""
    targets = [e for e in events if e.get("url")]

    def one(ev: dict) -> tuple[dict, str | None]:
        # Reddit 自帖：trafilatura 抓不到（页面是 JS 渲染的），但 RSS 摘要本身
        # 就是完整帖子正文，不是截断的导语 —— 直接采用，不算「未取到正文」。
        if "reddit.com" in ev["url"]:
            body = (ev.get("summary_raw") or "").strip()
            return ev, (body if len(body) > 200 else None)
        return ev, extract(ev["url"])

    ok = 0
    with futures.ThreadPoolExecutor(workers) as ex:
        for ev, body in ex.map(one, targets):
            ev["body"] = body or ""
            ev["has_body"] = bool(body)
            if body:
                ok += 1

    print(f"[OK] 正文抓取: {ok}/{len(targets)} 成功")
    return events


def main():
    inp = sys.argv[1] if len(sys.argv) > 1 else "data/ranked.json"
    out = sys.argv[2] if len(sys.argv) > 2 else "data/ranked.json"

    with open(inp, encoding="utf-8") as f:
        digest = json.load(f)

    deep = digest.get("lead", []) + digest.get("relevant", []) + digest.get("threads", [])
    enrich(deep)

    with open(out, "w", encoding="utf-8") as f:
        json.dump(digest, f, ensure_ascii=False, indent=2)
    print(f"[OK] 已写入 {out}")


if __name__ == "__main__":
    main()
