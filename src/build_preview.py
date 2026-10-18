"""Build a complete local edition from reviewed preview content."""
import argparse
import json
from pathlib import Path

import feed
import render
from ai_render import render_ai
from market_render import render_action_market
from global_market_render import render_global_market
from source_directory import render_directory
from source_registry import catalog

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", nargs="?", default="docs/preview-site")
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    digest = json.loads((ROOT / "data/preview_digest.json").read_text(encoding="utf-8"))
    if not digest.get("preview"):
        parser.error("预览构建仅接受带 preview 标记的试刊内容")
    report_path = ROOT / "data/source_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    dates = [p.stem for p in (ROOT / "docs/archive").glob("*.html")]
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    market_path = ROOT / "data/global_market.json"
    market = json.loads(market_path.read_text(encoding="utf-8")) if market_path.exists() else {}
    (output / "index.html").write_text(render.render(digest, archive_dates=dates, market=market), encoding="utf-8")
    (output / "ai.html").write_text(render_ai(digest), encoding="utf-8")
    (output / "market.html").write_text(render_global_market(market), encoding="utf-8")
    action_path = ROOT / "data/market.json"
    action = json.loads(action_path.read_text(encoding="utf-8")) if action_path.exists() else {}
    (output / "market-action.html").write_text(render_action_market(action), encoding="utf-8")
    feed.SITE = args.base_url.rstrip("/")
    (output / "feed.xml").write_text(feed.build(digest), encoding="utf-8")
    (output / "sources.html").write_text(render_directory(report, catalog()), encoding="utf-8")
    print(f"[OK] 完整试刊 → {output}")
    print(f"[OK] 日报 {len(digest['news'])} · 精选 {len(digest['features'])} · AI {len(digest['ai'])}")


if __name__ == "__main__":
    main()
