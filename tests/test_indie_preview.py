"""The complete preview must contain every indie page without editing editions."""
from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import build_preview


class IndiePreviewIntegrationTests(unittest.TestCase):
    def test_empty_discovery_preview_has_four_linked_pages_and_preserves_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "data").mkdir()
            digest = root / "data/preview_digest.json"
            digest.write_bytes((ROOT / "data/preview_digest.json").read_bytes())
            archive = root / "docs/archive/2026-10-18.html"
            archive.parent.mkdir(parents=True)
            archive.write_text("Historical edition: retain exact contents.", encoding="utf-8")
            before = {p: p.read_bytes() for p in (digest, archive)}
            output = root / "preview"
            with patch.object(build_preview, "ROOT", root), \
                    patch.object(sys, "argv", ["build_preview.py", str(output)]), \
                    patch.object(build_preview.feed, "SITE", "https://example.test"), \
                    redirect_stdout(io.StringIO()):
                build_preview.main()
            pages = ("indie.html", "indie-releases.html", "indie-ratings.html", "indie-online.html")
            for name in pages:
                page = (output / name).read_text(encoding="utf-8")
                self.assertIn("<title>", page)
                for target in pages:
                    self.assertIn(f'href="{target}"', page, (name, target))
            for path, content in before.items():
                self.assertEqual(path.read_bytes(), content)
            self.assertFalse((output / "archive").exists())
            self.assertFalse((root / "data/indie_discovery.json").exists())


if __name__ == "__main__":
    unittest.main()
