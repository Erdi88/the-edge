"""Focused tests for excerpt cleanup and static reading markup."""

from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess
import unittest

import collect


ROOT = Path(__file__).resolve().parents[1]


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.append(dict(attrs))


class LearnMarkupTests(unittest.TestCase):
    def test_feed_excerpt_removes_boilerplate_and_incomplete_tail(self):
        raw = ("The grid needs flexible storage to balance supply. Better controls help deliver power when demand rises. "
               "The post Grid storage appeared first on Example Publisher.")
        self.assertEqual(
            collect.clean_description(raw),
            "The grid needs flexible storage to balance supply. Better controls help deliver power when demand rises.",
        )
        self.assertEqual(
            collect.clean_description("A careful report explains the problem. The proposed solution is still being tested and may…"),
            "A careful report explains the problem.",
        )
        self.assertEqual(collect.clean_description("Short teaser without a complete point…"), collect.FALLBACK_DESCRIPTION)
        self.assertEqual(collect.clean_description("Short teaser without a complete point..."), collect.FALLBACK_DESCRIPTION)
        self.assertEqual(collect.clean_description(None), collect.FALLBACK_DESCRIPTION)

    def test_rendered_cards_escape_feed_text_and_keep_article_links(self):
        url = "https://example.com/story?a=1&b=2"
        story = {
            "id": hashlib.sha256(url.encode()).hexdigest()[:16],
            "category": "AI & Technology",
            "title": '<script>alert("x")</script> New research',
            "description": 'The report describes a new result with <b>quoted evidence</b>.',
            "source": 'Publisher & Co',
            "url": url,
            "published_at": "2026-10-10T06:00:00+00:00",
        }
        edition = {"date": "2026-10-10", "updated_at": datetime(2026, 10, 10, 7, tzinfo=timezone.utc).isoformat(), "stories": [story]}
        for depth in (0, 1):
            page = collect.render(edition, [edition], depth)
            self.assertIn(f'data-article-id="{story["id"]}"', page)
            self.assertIn("Source excerpt", page)
            self.assertIn("Read article ↗", page)
            self.assertNotIn('<script>alert("x")</script>', page)
            self.assertIn("&lt;script&gt;", page)
            self.assertIn("&amp;b=2", page)
            links = Links()
            links.feed(page)
            article_links = [link for link in links.links if link.get("href") == url]
            self.assertEqual(len(article_links), 2)
            self.assertTrue(all(link.get("target") == "_blank" and link.get("rel") == "noopener noreferrer" for link in article_links))

    def test_current_and_archived_pages_load_shared_learning_script(self):
        self.assertIn('src="app.js"', (ROOT / "index.html").read_text(encoding="utf-8"))
        archived = list((ROOT / "editions").glob("????-??-??.html"))
        self.assertTrue(archived)
        for path in archived:
            page = path.read_text(encoding="utf-8")
            self.assertIn('src="../app.js"', page)
            self.assertIn('class="story"', page)
            self.assertIn('class="description"', page)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed for the browser behavior check")
    def test_browser_behavior_without_packages(self):
        result = subprocess.run(["node", str(ROOT / "tests/learn_mode_check.js")],
                                cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
