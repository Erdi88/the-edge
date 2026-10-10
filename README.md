# The Edge

A small daily intelligence reader. Python collects dated headlines, source excerpts and links from public feeds. It creates a static HTML page and a JSON archive. No API key, package installation, database or local server is needed to update it.

## Run locally

Use Python 3.10 or newer. Run `python3 collect.py` to collect an edition, then open `index.html` in a browser. For a local HTTP preview, run `python3 -m http.server 8000` and visit `http://localhost:8000`. The page itself needs no server; a web connection is needed only for the optional Google Fonts.

## Manual updates

Run `python3 collect.py`. A second run on the same Oslo date leaves that edition untouched. Run `python3 collect.py --force` to refresh it. If fewer than eight usable fresh stories remain across four categories, the command exits with an error and leaves the previous edition as the homepage. The displayed edition date and update time always come from that edition.

## GitHub Pages

Create a public GitHub repository, push this folder to its `main` branch, then in **Settings → Pages → Build and deployment**, choose **GitHub Actions**. Run **Actions → Daily edition → Run workflow** if a deployment is not already running. The live URL is `https://Erdi88.github.io/the-edge/`. The Actions workflow needs repository Actions enabled and permission to write repository contents. Its update job uses `contents: write`; its deployment job uses `pages: write` and `id-token: write`.

## Schedule and archive

GitHub Actions runs at 04:30 and 05:30 UTC. The collector skips the slot before 06:00 in Norway, producing an edition around 06:30 Oslo time in both daylight saving and standard time. GitHub may delay scheduled jobs. A later run on the same Oslo date skips an existing edition. Every successful update commits `editions/YYYY-MM-DD.json` and `editions/YYYY-MM-DD.html` alongside the homepage; old editions stay in Git and remain linked from the homepage. Failed feeds are ignored individually. If the whole update is too thin, the workflow fails and the last successful page stays online.

## Windows Desktop shortcut

After deployment, right-click the Windows Desktop and choose **New → Shortcut**. Enter `https://Erdi88.github.io/the-edge/` as the location, name it **The Edge**, and finish. This opens the live site in your default browser, so it always shows the latest successful edition.

## Sources

Edit `sources.json` to add or remove RSS/Atom sources. Each entry needs a source `name`, feed `url`, and one of the first five `category` names in `collect.py`. The Opportunities category is an automatically selected factual source report about a commercial development; it is clearly marked and contains no generated business idea. Source headlines, excerpts and metadata are used; there is no AI summarization. Feed terms remain the publisher's responsibility, so review terms when adding sources.

## Troubleshooting

Check **Actions → Daily edition → latest run → Collect and render** for failed feeds or a thin edition. A single bad feed is tolerated. Check that GitHub Pages is set to **GitHub Actions** if deployment fails. GitHub disables scheduled workflows after prolonged repository inactivity; re-enable the workflow in the Actions tab. If the page shows an older date, the last attempt did not meet the freshness threshold; check the run log and use **Run workflow** after fixing the source. You can use `python3 collect.py --force` locally to investigate, then commit the resulting files.
