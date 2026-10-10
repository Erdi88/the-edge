#!/usr/bin/env python3
"""Package only the files meant for the public GitHub Pages website."""

from pathlib import Path
import shutil

root = Path(__file__).resolve().parent
site = root / "_site"
if site.exists():
    shutil.rmtree(site)
(site / "editions").mkdir(parents=True)
for name in ("index.html", "style.css", "app.js", ".nojekyll"):
    shutil.copy2(root / name, site / name)
for path in (root / "editions").glob("????-??-??.*"):
    if path.suffix in (".html", ".json"):
        shutil.copy2(path, site / "editions" / path.name)
print(f"Packaged {len(list(site.rglob('*')))} public paths in {site}")
