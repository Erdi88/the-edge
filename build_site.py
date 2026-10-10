#!/usr/bin/env python3
"""Package only the files meant for the public GitHub Pages website."""

from pathlib import Path
import shutil


def build(root: Path) -> Path:
    from verify import verify_local

    site = root / "_site"
    if site.exists():
        shutil.rmtree(site)
    (site / "editions").mkdir(parents=True)
    for name in ("index.html", "style.css", "app.js", ".nojekyll"):
        shutil.copy2(root / name, site / name)
    for path in (root / "editions").glob("????-??-??.*"):
        if path.suffix in (".html", ".json"):
            shutil.copy2(path, site / "editions" / path.name)
    verify_local(site)
    print(f"Packaged {len(list(site.rglob('*')))} public paths in {site}")
    return site


if __name__ == "__main__":
    build(Path(__file__).resolve().parent)
