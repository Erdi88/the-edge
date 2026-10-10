"""Offline recovery tests. Every published file lives in a temporary folder."""

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from xml.sax.saxutils import escape

import build_site
import collect
import verify


class FeedResponse(BytesIO):
    status = 200


class DailyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "editions").mkdir()
        self.sources = [
            {"name": f"Feed {i}", "url": f"https://feeds.example/{i}", "category": category}
            for i, category in enumerate(collect.CATEGORIES[:-1])
        ]
        (self.root / "sources.json").write_text(json.dumps(self.sources), encoding="utf-8")
        for name in ("style.css", "app.js", ".nojekyll"):
            (self.root / name).write_text("", encoding="utf-8")
        self.now = datetime(2026, 10, 11, 5, 30, tzinfo=timezone.utc)
        self.fail = set()
        self.invalid = set()
        self.variant = "a"
        self.root_patch = patch.object(collect, "ROOT", self.root)
        self.editions_patch = patch.object(collect, "EDITIONS", self.root / "editions")
        self.root_patch.start()
        self.editions_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.addCleanup(self.editions_patch.stop)
        self.feed_patch = patch.object(collect, "urlopen", side_effect=self.urlopen)
        self.feed_patch.start()
        self.addCleanup(self.feed_patch.stop)

    def urlopen(self, request, timeout=18):
        number = int(request.full_url.rsplit("/", 1)[-1])
        if number in self.fail:
            raise TimeoutError("simulated feed timeout")
        if number in self.invalid:
            return FeedResponse(b"<rss><broken>")
        items = []
        for item in range(2):
            title = f"Research and market update {number}-{item}-{self.variant}"
            url = f"https://articles.example/{number}/{item}/{self.variant}"
            date = format_datetime(self.now - timedelta(hours=item + 1))
            items.append(f"<item><title>{escape(title)}</title><link>{url}</link>"
                         f"<description>A detailed factual report on research and market developments number {number}.</description>"
                         f"<pubDate>{date}</pubDate></item>")
        return FeedResponse(("<rss><channel>" + "".join(items) + "</channel></rss>").encode())

    def run_daily(self, *args):
        return collect.main(list(args), now=self.now)

    def snapshot(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob("*") if path.is_file() and path.name not in ("sources.json", "style.css", "app.js", ".nojekyll")}

    def make_previous(self):
        self.now -= timedelta(days=1)
        self.assertEqual(self.run_daily(), 0)
        self.now += timedelta(days=1)
        self.variant = "b"

    def test_successful_generation_and_valid_outputs(self):
        self.assertEqual(self.run_daily(), 0)
        edition = json.loads((self.root / "editions/2026-10-11.json").read_text())
        self.assertEqual(edition["date"], "2026-10-11")
        self.assertEqual(len(edition["stories"]), 10)
        verify.verify_local(self.root)
        self.assertEqual(len(list((self.root / "editions").glob("*.json"))), 1)

    def test_second_run_skips_without_fetching(self):
        self.assertEqual(self.run_daily(), 0)
        before = self.snapshot()
        with patch.object(collect, "collect_source", side_effect=AssertionError("feed fetched")):
            self.assertEqual(self.run_daily(), 0)
        self.assertEqual(self.snapshot(), before)

    def test_one_source_timeout_succeeds(self):
        self.fail.add(0)
        self.assertEqual(self.run_daily(), 0)
        self.assertEqual(len(json.loads((self.root / "editions/2026-10-11.json").read_text())["stories"]), 8)

    def test_all_sources_unavailable_preserves_previous_files(self):
        self.make_previous()
        before = self.snapshot()
        self.fail.update(range(5))
        self.assertEqual(self.run_daily(), 1)
        self.assertEqual(self.snapshot(), before)

    def test_insufficient_fresh_articles_preserves_previous_files(self):
        self.make_previous()
        before = self.snapshot()
        self.fail.update((0, 1))
        self.assertEqual(self.run_daily(), 1)
        self.assertEqual(self.snapshot(), before)

    def test_invalid_rss_and_json_preserve_previous_files(self):
        self.make_previous()
        before = self.snapshot()
        self.invalid.update(range(5))
        self.assertEqual(self.run_daily(), 1)
        self.assertEqual(self.snapshot(), before)
        (self.root / "sources.json").write_text("{invalid", encoding="utf-8")
        self.assertEqual(self.run_daily(), 1)
        self.assertEqual(self.snapshot(), before)

    def test_duplicate_ids_from_previous_editions_and_current_feeds(self):
        self.assertEqual(self.run_daily(), 0)
        archive = collect.load_archive()
        old_ids = {story["id"] for story in archive[0]["stories"]}
        self.now += timedelta(days=1)
        candidates = [item for source in self.sources for item in collect.collect_source(source, self.now)]
        # A differently titled copy of the same URL must also be removed.
        duplicate = dict(candidates[0], title="A second title for the same URL")
        chosen = collect.select_stories(candidates + [duplicate], archive, "2026-10-12")
        self.assertFalse(old_ids.intersection(story["id"] for story in chosen))
        self.variant = "b"
        candidates = [item for source in self.sources for item in collect.collect_source(source, self.now)]
        chosen = collect.select_stories(candidates + [dict(candidates[0], title="A second title")], archive, "2026-10-12")
        self.assertEqual(len({story["id"] for story in chosen}), len(chosen))

    def test_render_failure_preserves_previous_files_and_recovers(self):
        self.make_previous()
        before = self.snapshot()
        with patch.object(collect, "render", side_effect=RuntimeError("simulated renderer error")):
            self.assertEqual(self.run_daily(), 1)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.run_daily(), 0)
        self.assertEqual(len(list((self.root / "editions").glob("*.json"))), 2)
        verify.verify_local(self.root)

    def test_replacement_failure_rolls_back_then_recovers(self):
        self.make_previous()
        before = self.snapshot()
        original = os.replace
        failed = False

        def fail_once(source, destination):
            nonlocal failed
            if Path(destination) == self.root / "index.html" and not failed:
                failed = True
                raise OSError("simulated replacement error")
            return original(source, destination)

        with patch.object(collect.os, "replace", side_effect=fail_once):
            self.assertEqual(self.run_daily(), 1)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.run_daily(), 0)

    def test_oslo_daylight_saving_schedule(self):
        self.now = datetime(2026, 3, 29, 4, 30, tzinfo=timezone.utc)
        self.assertEqual(self.now.astimezone(collect.OSLO).strftime("%H:%M %z"), "06:30 +0200")
        self.assertEqual(self.run_daily("--scheduled"), 0)
        self.assertTrue((self.root / "editions/2026-03-29.json").exists())
        self.now = datetime(2026, 10, 25, 4, 30, tzinfo=timezone.utc)
        with patch.object(collect, "collect_source", side_effect=AssertionError("early slot fetched")):
            self.assertEqual(self.run_daily("--scheduled"), 0)
        self.now += timedelta(hours=1)
        self.assertEqual(self.now.astimezone(collect.OSLO).strftime("%H:%M %z"), "06:30 +0100")
        self.variant = "b"
        self.assertEqual(self.run_daily("--scheduled"), 0)
        self.assertTrue((self.root / "editions/2026-10-25.json").exists())

    def test_morning_retry_recovers_after_visible_failure(self):
        self.fail.update(range(5))
        self.assertEqual(self.run_daily("--scheduled"), 1)
        self.assertFalse((self.root / "index.html").exists())
        self.now += timedelta(hours=1)  # 07:30 Oslo
        self.fail.clear()
        self.assertEqual(self.run_daily("--scheduled"), 0)
        before = self.snapshot()
        self.now += timedelta(hours=1)  # 08:30 Oslo
        with patch.object(collect, "collect_source", side_effect=AssertionError("unnecessary retry fetched")):
            self.assertEqual(self.run_daily("--scheduled"), 0)
        self.assertEqual(self.snapshot(), before)

    def test_packaging_links_and_live_verification_recovery(self):
        self.make_previous()
        self.assertEqual(self.run_daily(), 0)
        site = build_site.build(self.root)
        expected = verify.verify_local(site)
        self.assertIn(b'editions/2026-10-10.html', expected)
        self.assertTrue((site / "editions/2026-10-10.html").exists())
        previous = self.snapshot()
        with patch.object(verify, "urlopen", side_effect=lambda *_args, **_kwargs: FeedResponse(b"old page")):
            with self.assertRaises(RuntimeError):
                verify.verify_live(expected, "https://example.com/the-edge/", attempts=2, delay=0)
        self.assertEqual(self.snapshot(), previous)
        with patch.object(verify, "urlopen", return_value=FeedResponse(expected)):
            verify.verify_live(expected, "https://example.com/the-edge/", attempts=1, delay=0)


if __name__ == "__main__":
    unittest.main()
