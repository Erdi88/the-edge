#!/usr/bin/env python3
"""Validate a packaged edition and, after deployment, its public homepage."""

from __future__ import annotations

import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.articles = 0
        self.archive_depth = 0
        self.archive_links: list[str] = []
        self.titles: list[str] = []
        self.in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs = dict(attrs)
        if tag == "article" and "story" in (attrs.get("class") or "").split():
            self.articles += 1
        if tag == "nav" and "archive" in (attrs.get("class") or "").split():
            self.archive_depth += 1
        if tag == "a" and self.archive_depth:
            self.archive_links.append(attrs.get("href") or "")
        if tag == "title":
            self.in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "nav" and self.archive_depth:
            self.archive_depth -= 1
        if tag == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.titles.append(data)


def verify_site(edition: dict, homepage: str, archive_page: str, dates: list[str]) -> None:
    from collect import validate_edition

    validate_edition(edition)
    today = edition["date"]
    expected = {f"editions/{date}.html" for date in dates if date != today}
    for text, prefix in ((homepage, ""), (archive_page, "../")):
        if not text.startswith("<!doctype html>") or "</html>" not in text:
            raise ValueError("HTML document is incomplete")
        page = PageParser()
        page.feed(text)
        if "".join(page.titles) != f"The Edge · {today}" or page.articles != len(edition["stories"]):
            raise ValueError("HTML date or story count differs from JSON")
        if set(page.archive_links) != {prefix + link for link in expected} or len(page.archive_links) != len(expected):
            raise ValueError("archive links are inconsistent")


def verify_local(root: Path) -> bytes:
    from collect import validate_edition

    index = (root / "index.html").read_bytes()
    match = re.search(rb"<title>The Edge \xc2\xb7 (\d{4}-\d{2}-\d{2})</title>", index)
    if not match:
        raise ValueError("homepage has no edition date")
    today = match.group(1).decode("ascii")
    editions = root / "editions"
    dates = sorted(path.stem for path in editions.glob("????-??-??.json"))
    if not dates or dates[-1] != today:
        raise ValueError("homepage does not show the latest archived edition")
    edition = json.loads((editions / f"{today}.json").read_text(encoding="utf-8"))
    validate_edition(edition)
    if edition["date"] != today:
        raise ValueError("archive filename and edition date differ")
    for date in dates:
        if not (editions / f"{date}.html").is_file():
            raise ValueError(f"missing archive page: {date}")
        archived = json.loads((editions / f"{date}.json").read_text(encoding="utf-8"))
        if archived["date"] != date:
            raise ValueError(f"archive filename and edition date differ: {date}")
        validate_edition(archived)
    verify_site(edition, index.decode("utf-8"),
                (editions / f"{today}.html").read_text(encoding="utf-8"), dates)
    print(f"Verified local edition {today}: {len(edition['stories'])} stories, {len(dates)} archives")
    return index


def verify_live(expected: bytes, url: str, attempts: int = 8, delay: float = 15) -> None:
    if urlsplit(url).scheme != "https":
        raise ValueError("live URL must use HTTPS")
    error: Exception | None = None
    for attempt in range(attempts):
        try:
            bits = urlsplit(url)
            fresh_url = urlunsplit((bits.scheme, bits.netloc, bits.path,
                                   urlencode({"edge_check": str(time.time_ns())}), ""))
            request = Request(fresh_url, headers={"Cache-Control": "no-cache", "User-Agent": "TheEdgeVerifier/1.0"})
            with urlopen(request, timeout=20) as response:
                if response.status != 200:
                    raise ValueError(f"live site returned HTTP {response.status}")
                actual = response.read()
            if actual == expected:
                print(f"Verified live edition matches published homepage: {url}")
                return
            error = ValueError("live homepage differs from intended edition")
        except Exception as exc:
            error = exc
        print(f"Live verification attempt {attempt + 1}/{attempts} failed: {error}")
        if attempt + 1 < attempts:
            time.sleep(delay)
    raise RuntimeError(f"deployment verification failed after {attempts} attempts: {error}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--live", help="verify the deployed homepage at this URL")
    args = parser.parse_args()
    try:
        expected = verify_local(args.root)
        if args.live:
            verify_live(expected, args.live)
    except Exception as exc:
        parser.exit(1, f"Verification failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
