#!/usr/bin/env python3
"""Collect public RSS metadata and publish one static daily edition."""

from __future__ import annotations

import argparse
import email.utils
import hashlib
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
EDITIONS = ROOT / "editions"
OSLO = ZoneInfo("Europe/Oslo")
CATEGORIES = ["Energy & Power Markets", "AI & Technology", "Business & Startups", "Finance & Economics", "Science & Learning", "Opportunities"]
KEYWORDS = {
    "Energy & Power Markets": ("grid", "power", "electricity", "battery", "batteries", "storage", "solar", "wind", "energy", "transmission", "renewable", "market", "nett", "strøm"),
    "AI & Technology": ("ai", "agent", "model", "robot", "chip", "automation", "software", "open source", "machine learning"),
    "Business & Startups": ("startup", "funding", "acquisition", "company", "revenue", "venture", "business", "raises", "launch"),
    "Finance & Economics": ("economy", "inflation", "market", "trade", "investment", "rates", "bank", "tariff", "oil", "geopolitics"),
    "Science & Learning": ("research", "study", "scientist", "discovery", "physics", "mathematics", "optimization", "statistics"),
}
OPPORTUNITY_WORDS = ("startup", "funding", "market", "battery", "storage", "grid", "automation", "robot", "commercial", "investment", "technology")
COMMERCIAL_EVENT_WORDS = ("raises", "funding", "valued", "acquires", "acquisition", "investment", "contract", "launches", "orders", "deal")


class StripMarkup(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def plain(value: str | None) -> str:
    parser = StripMarkup()
    parser.feed(html.unescape(value or ""))
    return re.sub(r"\s+", " ", "".join(parser.parts)).strip()


def child_text(node: ET.Element, name: str) -> str:
    for child in node:
        if child.tag.rsplit("}", 1)[-1] == name:
            return "".join(child.itertext()).strip()
    return ""


def parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def canonical_url(url: str) -> str:
    if any(char.isspace() for char in url):
        return ""
    try:
        bits = urlsplit(url.strip())
        if bits.scheme not in ("http", "https") or not bits.hostname:
            return ""
        bits.port  # Reject malformed ports.
    except ValueError:
        return ""
    query = urlencode([(k, v) for k, v in parse_qsl(bits.query) if not k.lower().startswith("utm_") and k.lower() not in ("fbclid", "gclid")])
    return urlunsplit((bits.scheme.lower(), bits.netloc.lower(), bits.path.rstrip("/") or "/", query, ""))


def collect_source(source: dict, now: datetime) -> list[dict]:
    request = Request(source["url"], headers={"User-Agent": "TheEdge/1.0 (personal RSS reader; github.com/Erdi88/the-edge)", "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"})
    with urlopen(request, timeout=18) as response:
        data = response.read(2_000_001)
    if len(data) > 2_000_000:
        raise ValueError("feed exceeds 2 MB")
    root = ET.fromstring(data)
    items = root.findall(".//item")
    items += root.findall("{http://www.w3.org/2005/Atom}entry")
    if not items:
        raise ValueError("no RSS or Atom items")
    result = []
    for item in items:
        title = plain(child_text(item, "title"))
        description = plain(child_text(item, "description") or child_text(item, "summary"))
        if description.startswith("Article URL:") or description.startswith("Comments URL:"):
            continue
        link = child_text(item, "link")
        if not link:
            for node in item:
                if node.tag.rsplit("}", 1)[-1] == "link" and node.attrib.get("rel", "alternate") == "alternate":
                    link = node.attrib.get("href", "")
                    break
        url = canonical_url(link)
        published = parse_date(child_text(item, "pubDate") or child_text(item, "published") or child_text(item, "date") or child_text(item, "updated"))
        if not title or not description or not url or not published:
            continue
        if not (now - timedelta(days=4) <= published <= now + timedelta(hours=2)):
            continue
        # A complete feed sentence is preferable to an invented summary.
        if len(description) > 320:
            if source["name"] == "TechCrunch":
                continue  # Its RSS terms require the feed text to remain unmodified.
            description = description[:320].rsplit(" ", 1)[0] + "…"
        if len(description) < 35:
            continue
        key = hashlib.sha256(url.encode()).hexdigest()[:16]
        result.append({"id": key, "title": title, "description": description, "url": url,
                       "source": source["name"], "category": source["category"],
                       "published_at": published.isoformat(timespec="seconds")})
    return result


def load_archive() -> list[dict]:
    records = []
    for path in sorted(EDITIONS.glob("????-??-??.json"), reverse=True):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if record["date"] != path.stem or not isinstance(record["stories"], list):
                raise ValueError("archive filename or stories mismatch")
            validate_edition(record)
            records.append(record)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ValueError(f"invalid archive {path.name}: {exc}") from exc
    return records


def select_stories(candidates: list[dict], archive: list[dict], today: str) -> list[dict]:
    recent_ids = {story["id"] for edition in archive if edition.get("date") != today for story in edition.get("stories", [])}
    unique: dict[str, dict] = {}
    for story in candidates:
        title_key = re.sub(r"[^a-z0-9]+", "", story["title"].lower())[:90]
        if story["id"] in recent_ids or not title_key:
            continue
        current = unique.get(title_key)
        if current is None or story["published_at"] > current["published_at"]:
            unique[title_key] = story
    # Different feed titles may still point at the same article.
    pool = []
    seen_ids = set()
    for story in sorted(unique.values(), key=lambda s: s["published_at"], reverse=True):
        if story["id"] not in seen_ids:
            pool.append(story)
            seen_ids.add(story["id"])
    for story in pool:
        terms = (story["title"] + " " + story["description"]).lower()
        story["score"] = sum(2 if word in story["title"].lower() else 1 for word in KEYWORDS[story["category"]] if word in terms)
        story["opportunity_score"] = sum(1 for word in OPPORTUNITY_WORDS if word in terms)
    pool.sort(key=lambda s: (s["score"], s["published_at"]), reverse=True)
    chosen: list[dict] = []
    # Reserve two places for every subject before filling by relevance.
    for category in CATEGORIES[:-1]:
        chosen.extend([s for s in pool if s["category"] == category][:2])
    source_counts: dict[str, int] = {}
    for story in chosen:
        source_counts[story["source"]] = source_counts.get(story["source"], 0) + 1
    for story in pool:
        if len(chosen) >= 12:
            break
        if story in chosen or source_counts.get(story["source"], 0) >= 3 or sum(s["category"] == story["category"] for s in chosen) >= 3:
            continue
        chosen.append(story)
        source_counts[story["source"]] = source_counts.get(story["source"], 0) + 1
    # Reclassify one factual source report as a commercial signal. No business idea is generated.
    opportunities = sorted((s for s in chosen if s["category"] in ("Energy & Power Markets", "AI & Technology", "Business & Startups") and (s["opportunity_score"] >= 2 or any(word in s["title"].lower() for word in COMMERCIAL_EVENT_WORDS))), key=lambda s: (sum(word in s["title"].lower() for word in COMMERCIAL_EVENT_WORDS), sum(c["category"] == s["category"] for c in chosen), s["opportunity_score"]), reverse=True)
    if opportunities:
        signal = opportunities[0]
        signal["original_category"] = signal["category"]
        signal["category"] = "Opportunities"
    for story in chosen:
        story.pop("score", None)
        story.pop("opportunity_score", None)
    return chosen


def escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def render(edition: dict, archive: list[dict], depth: int = 0) -> str:
    prefix = "../" if depth else ""
    cards = []
    for number, story in enumerate(edition["stories"], 1):
        category = story["category"]
        signal = '<span class="signal">Source item · commercial signal</span>' if category == "Opportunities" else ""
        cards.append(f'''<article class="story" data-category="{escape(category)}">
          <div class="story-top"><span class="number">{number:02}</span><span class="pill">{escape(category)}</span>{signal}</div>
          <h2><a href="{escape(story['url'])}" target="_blank" rel="noopener noreferrer">{escape(story['title'])}</a></h2>
          <p class="description">{escape(story['description'])}</p>
          <div class="meta"><span>{escape(story['source'])}</span><span aria-hidden="true">·</span><time datetime="{escape(story['published_at'])}">{escape(story['published_at'][:10])}</time><a href="{escape(story['url'])}" target="_blank" rel="noopener noreferrer">Read original ↗</a></div>
        </article>''')
    options = ''.join(f'<button class="filter" type="button" data-filter="{escape(category)}">{escape(category)}</button>' for category in CATEGORIES)
    archive_links = ''.join(f'<a href="{prefix}editions/{escape(item["date"])}.html">{escape(item["date"])}</a>' for item in archive if item.get("date") != edition["date"])
    archive_links = archive_links or '<span class="empty-archive">Earlier editions will appear here.</span>'
    updated = datetime.fromisoformat(edition["updated_at"]).astimezone(OSLO)
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="The Edge: a concise daily reading edition on technology, business, science, energy and global developments.">
<title>The Edge · {escape(edition['date'])}</title><link rel="stylesheet" href="{prefix}style.css"><script defer src="{prefix}app.js"></script></head>
<body><div class="site-shell"><header class="masthead"><a class="brand" href="{prefix}index.html">THE EDGE<span class="brand-dot">.</span></a><div class="header-right"><span class="header-label">DAILY INTELLIGENCE</span><button id="theme" type="button" aria-label="Toggle dark mode" title="Toggle dark mode">◐</button></div></header>
<main><section class="intro"><div class="eyebrow">THE DAILY EDITION <span class="eyebrow-line"></span> {escape(edition['date'])}</div><h1>Stay curious.<br><em>See what matters.</em></h1><p class="deck">A focused reading list across power markets, technology, business, finance and science. Original reporting, straight from the source.</p><div class="edition-meta"><span>{len(edition['stories'])} STORIES</span><span>ABOUT 15–20 MINUTES</span><span>UPDATED <time datetime="{escape(edition['updated_at'])}">{escape(updated.strftime('%d %b %Y, %H:%M'))} OSLO</time></span></div></section>
<div class="content-grid"><div class="primary"><div class="section-heading"><div><span class="section-kicker">01 / THE BRIEFING</span><h2>Stories in this edition</h2></div><span class="story-count">{len(edition['stories']):02} ARTICLES</span></div><div class="filters" role="group" aria-label="Filter stories"><button class="filter active" type="button" data-filter="All" aria-pressed="true">All stories</button>{options}</div><div id="stories">{''.join(cards)}</div><p id="no-results" hidden>No stories in this category in this edition.</p></div><aside class="sidebar"><div class="side-block"><span class="section-kicker">THE LENS</span><h3>Signal over noise.</h3><p>Selected public feed items with source headlines and excerpts. “Opportunities” highlights factual commercial developments; it does not propose or validate an investment.</p></div><div class="side-block"><span class="section-kicker">02 / THE ARCHIVE</span><h3>Previous editions</h3><nav class="archive" aria-label="Previous editions">{archive_links}</nav></div><div class="side-block"><span class="section-kicker">SOURCES</span><p>Links open the original publisher. Publication dates are shown on every story.</p></div></aside></div></main>
<footer><span>THE EDGE · A PERSONAL DAILY READER</span><span>BUILT FOR A CLEARER VIEW</span></footer></div></body></html>'''


def validate_edition(edition: dict) -> None:
    date = datetime.fromisoformat(edition["date"]).date().isoformat()
    updated = datetime.fromisoformat(edition["updated_at"])
    if updated.tzinfo is None or updated.astimezone(OSLO).date().isoformat() != date:
        raise ValueError("edition date does not match its Oslo update date")
    stories = edition["stories"]
    if not 8 <= len(stories) <= 12 or len({s["category"] for s in stories}) < 4:
        raise ValueError("edition needs 8–12 stories across at least four categories")
    ids = set()
    for story in stories:
        url = story["url"]
        if not canonical_url(url) or urlsplit(url).scheme not in ("http", "https"):
            raise ValueError(f"invalid article URL: {url}")
        if story["id"] != hashlib.sha256(url.encode()).hexdigest()[:16] or story["id"] in ids:
            raise ValueError("duplicate or incorrect article ID")
        if story["category"] not in CATEGORIES or not all(story.get(k) for k in ("title", "description", "source")):
            raise ValueError("incomplete article")
        published = datetime.fromisoformat(story["published_at"])
        if published.tzinfo is None:
            raise ValueError("article date lacks a timezone")
        ids.add(story["id"])


def publish(edition: dict, archive: list[dict]) -> None:
    """Validate staged output, then replace files; roll back any failed replacement."""
    validate_edition(edition)
    today = edition["date"]
    new_archive = [edition] + [item for item in archive if item.get("date") != today]
    for item in archive:
        if item["date"] != today and not (EDITIONS / f"{item['date']}.html").is_file():
            raise ValueError(f"missing archived page: {item['date']}")
    outputs = {
        EDITIONS / f"{today}.json": json.dumps(edition, ensure_ascii=False, indent=2) + "\n",
        EDITIONS / f"{today}.html": render(edition, new_archive, 1),
        ROOT / "index.html": render(edition, new_archive),
    }
    # Keep all temporary files on the same filesystem as the published files.
    with tempfile.TemporaryDirectory(prefix=".edge-stage-", dir=ROOT) as stage_name:
        stage = Path(stage_name)
        for path, content in outputs.items():
            staged = stage / path.name
            staged.write_text(content, encoding="utf-8")
            if staged.read_text(encoding="utf-8") != content:
                raise ValueError(f"staged file did not round trip: {path.name}")
        if json.loads((stage / f"{today}.json").read_text(encoding="utf-8")) != edition:
            raise ValueError("staged JSON is invalid")
        from verify import verify_site
        # Check generated links before touching the current homepage or archives.
        verify_site(edition, outputs[ROOT / "index.html"], outputs[EDITIONS / f"{today}.html"],
                    [item["date"] for item in new_archive])
        backups = {}
        replaced = []
        try:
            for path in outputs:
                if path.exists():
                    backup = stage / (path.name + ".backup")
                    backup.write_bytes(path.read_bytes())
                    backups[path] = backup
                os.replace(stage / path.name, path)
                replaced.append(path)
        except Exception:
            for path in reversed(replaced):
                if path in backups:
                    os.replace(backups[path], path)
                else:
                    path.unlink(missing_ok=True)
            raise


def main(argv: list[str] | None = None, now: datetime | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scheduled", action="store_true", help="skip the early UTC slot outside Norway's morning")
    parser.add_argument("--force", action="store_true", help="refresh an existing edition for the same date")
    args = parser.parse_args(argv)
    now = now or datetime.now(timezone.utc)
    oslo = now.astimezone(OSLO)
    today = oslo.date().isoformat()
    if args.scheduled and oslo.hour < 6:
        print(f"Skipping early UTC slot: {oslo.isoformat()}")
        return 0
    EDITIONS.mkdir(exist_ok=True)
    target = EDITIONS / f"{today}.json"
    if target.exists() and not args.force:
        print(f"Edition {today} already exists; leaving it unchanged")
        return 0
    try:
        sources = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))
        if not isinstance(sources, list) or not sources:
            raise ValueError("sources.json needs at least one feed")
    except (OSError, ValueError) as exc:
        print(f"Collection failed: {exc}; previous edition preserved", file=sys.stderr)
        return 1
    candidates = []
    successful = []
    for source in sources:
        try:
            items = collect_source(source, now)
            candidates.extend(items)
            successful.append(f"{source['name']}: {len(items)} fresh items")
        except Exception as exc:
            print(f"Feed failed: {source['name']}: {exc}", file=sys.stderr)
    print("; ".join(successful) if successful else "No feeds succeeded")
    try:
        archive = load_archive()
    except ValueError as exc:
        print(f"Collection failed: {exc}; previous edition preserved", file=sys.stderr)
        return 1
    stories = select_stories(candidates, archive, today)
    if len(stories) < 8 or len({story['category'] for story in stories}) < 4:
        print(f"Only {len(stories)} stories across {len({s['category'] for s in stories})} categories; preserving last edition", file=sys.stderr)
        return 1
    edition = {"date": today, "updated_at": now.isoformat(timespec="seconds"), "stories": stories}
    try:
        publish(edition, archive)
    except Exception as exc:
        print(f"Publication failed: {exc}; previous edition preserved", file=sys.stderr)
        return 1
    print(f"Published {today}: {len(stories)} stories")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
