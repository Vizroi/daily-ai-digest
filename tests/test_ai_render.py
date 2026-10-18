"""Independent AI page, source safety and non-destructive archives."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import ai_render


def event(index, **overrides):
    value = {"key": f"ai-{index}", "title": f"Update {index}", "title_cn": f"动态 {index}",
             "url": f"https://example.com/{index}", "what": "模型与工具的实际更新。", "lang": "en",
             "published": "2026-10-17", "published_precision": "day", "sources": ["Source"]}
    value.update(overrides)
    return value


def digest():
    return {"schema_version": 3, "date": "2026-10-18", "generated_at": "2026-10-18T19:00:00+08:00",
            "ai": [event(i) for i in range(4)], "ai_features": [event(10, has_body=True)]}


class Links(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.ids, self.anchors = [], []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.ids.append(attrs["id"])
        if tag == "a" and attrs.get("href", "").startswith("#"):
            self.anchors.append(attrs["href"][1:])


class AiPageTests(unittest.TestCase):
    def test_short_news_and_features_are_separate_with_valid_links(self):
        data = digest()
        page = ai_render.render_ai(data)
        links = Links(page)
        self.assertEqual(len(links.ids), len(set(links.ids)))
        self.assertTrue(all(anchor in links.ids for anchor in links.anchors))
        self.assertEqual(page.count('class="ai-news-item"'), 4)
        self.assertEqual(page.count('class="ai-feature-card"'), 1)
        self.assertIn('href="ai.html" aria-current="page"', page)
        self.assertNotIn('<form', page)
        self.assertNotIn('<script', page)
        self.assertNotIn('策划视角', page)

    def test_no_duplicate_article_or_unread_feature_is_rendered(self):
        data = digest()
        data["ai"] += [event(10, key="duplicate-url", url="https://example.com/10?utm_source=feed")]
        data["ai_features"].append(event(11, has_body=False))
        page = ai_render.render_ai(data)
        self.assertEqual(page.count('class="ai-news-item"'), 4)
        self.assertEqual(page.count('class="ai-feature-card"'), 1)
        self.assertNotIn('动态 11', page)

    def test_short_copy_safe_source_links_and_empty_state(self):
        data = digest()
        data["ai"][0].update(what="简短事实。" * 100, title_cn='<script>alert(1)</script>', url='javascript:alert(1)')
        page = ai_render.render_ai(data)
        self.assertLessEqual(len(ai_render._brief_text(data["ai"][0])), 180)
        self.assertNotIn('<script>', page)
        self.assertNotIn('href="javascript:', page)
        self.assertIn('&lt;script&gt;', page)
        empty = ai_render.render_ai({"date": "2026-10-18", "ai": [], "ai_features": []})
        self.assertIn("本期暂无符合收录条件的 AI 快讯", empty)
        self.assertIn("本期暂无已核对正文的精选阅读", empty)

    def test_archives_keep_old_bytes_and_use_two_level_navigation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "digest.json"
            source.write_text(json.dumps(digest()), encoding="utf-8")
            output = root / "docs/ai.html"
            command = [sys.executable, "-X", "utf8", str(ROOT / "src/ai_render.py"), str(source), str(output)]
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            archive = root / "docs/archive/ai/2026-10-18.html"
            old = archive.read_bytes()
            self.assertIn('href="../../index.html"', old.decode("utf-8"))
            self.assertIn('href="../../ai.html" aria-current="true"', old.decode("utf-8"))
            self.assertIn('href="archive/ai/2026-10-18.html"', output.read_text(encoding="utf-8"))
            data = digest()
            data["ai"].append(event(5))
            source.write_text(json.dumps(data), encoding="utf-8")
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(archive.read_bytes(), old)
            self.assertEqual(output.read_text(encoding="utf-8").count('class="ai-news-item"'), 5)
            archive.unlink()
            result = subprocess.run(command + ["--no-archive"], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(archive.exists())


if __name__ == "__main__":
    unittest.main()
