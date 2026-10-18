"""Market refreshes must not rewrite daily content or historical editions."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import render


class MarketIntegrationTests(unittest.TestCase):
    def test_market_only_refresh_preserves_edition_and_archive(self):
        digest = json.loads((ROOT / "data/preview_digest.json").read_text(encoding="utf-8"))
        digest["preview"] = False
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inp = root / "digest.json"
            inp.write_text(json.dumps(digest), encoding="utf-8")
            archive = root / "archive" / (digest["date"] + ".html")
            archive.parent.mkdir()
            archive.write_text("Historical edition: keep byte for byte.", encoding="utf-8")
            before = {p: p.read_bytes() for p in (inp, archive)}
            command = [sys.executable, "-X", "utf8", str(ROOT / "src/render.py"), str(inp), str(root / "index.html"),
                       "--market", str(root / "missing.json"), "--no-archive"]
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            for path, content in before.items():
                self.assertEqual(path.read_bytes(), content)
            self.assertIn('href="market.html"', (root / "index.html").read_text(encoding="utf-8"))
            archive.unlink()
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(archive.exists())

    def test_archive_market_link_is_relative_and_snapshot_timestamp_is_retained(self):
        digest = json.loads((ROOT / "data/preview_digest.json").read_text(encoding="utf-8"))
        market = {"generated_at": "2026-10-18T08:00:00+08:00", "timezone": "Asia/Shanghai",
                  "status": "partial", "coverage": {"total_games": 0, "history_days": 0}, "games": []}
        page = render.render(digest, market=market, archive_page=True)
        self.assertIn('href="../market.html"', page)
        self.assertNotIn("localhost", page)
        self.assertNotIn("127.0.0.1", page)


if __name__ == "__main__":
    unittest.main()
