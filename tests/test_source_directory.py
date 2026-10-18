"""The public directory distinguishes inactivity, failed reads and pending access."""
import os
import sys
import unittest
from html.parser import HTMLParser

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from source_directory import render_directory


class SourceRows(HTMLParser):
    def __init__(self, page):
        super().__init__()
        self.rows = {}
        self.state = None
        self.feed(page)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "article" and attrs.get("class") == "source":
            self.state = attrs["data-state"]
            self.rows[self.state] = ""

    def handle_data(self, data):
        if self.state:
            self.rows[self.state] += data

    def handle_endtag(self, tag):
        if tag == "article":
            self.state = None


class SourceStatusTests(unittest.TestCase):
    def page(self, entries):
        return render_directory({"sources": [dict(id=state, name=state, state=state, count=count)
                                             for state, count in entries]}, [])

    def test_zero_new_items_are_not_reported_as_fetch_failure(self):
        page = self.page([("empty", 0), ("error", 0), ("blocked", 0), ("needs_auth", 0)])
        rows = SourceRows(page).rows
        self.assertIn("读取正常 · 无新内容", rows["empty"])
        self.assertIn("0条候选", rows["empty"])
        for state in ("error", "blocked", "needs_auth"):
            self.assertIn("—条候选", rows[state])
            self.assertNotIn("0条候选", rows[state])

    def test_partial_collection_keeps_count_without_claiming_normal_read(self):
        page = self.page([("degraded", 4)])
        row = SourceRows(page).rows["degraded"]
        self.assertIn("部分读取", row)
        self.assertIn("4条候选", row)
        self.assertNotIn("读取正常", row)

    def test_summary_separates_working_pending_and_manual_entries(self):
        page = self.page([("ok", 2), ("empty", 0), ("needs_auth", 0), ("manual", 0)])
        self.assertIn('正常读取 <strong>2</strong>', page)
        self.assertIn('待接入 / 待授权 <strong>1</strong>', page)
        self.assertIn('手动入口 <strong>1</strong>', page)
        self.assertNotIn('读取异常 <strong>', page)

    def test_unchecked_catalog_never_claims_success(self):
        page = render_directory({}, [{"id": "registered", "name": "Registered source"}])
        self.assertIn('尚未检查 <strong>1</strong>', page)
        self.assertNotIn('正常读取 <strong>', page)


if __name__ == "__main__":
    unittest.main()
