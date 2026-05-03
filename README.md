# 🦇 Vampiric Crawler

Vampiric Crawler is a Photon-inspired OSINT crawler with a gothic accent: fast enough for reconnaissance, readable enough for operators, and theatrical only where it helps.

## What it does

- Crawls a target with configurable depth, threads, delay, timeout, headers, cookies, proxies, and user-agent rotation
- Normalizes URLs so duplicate paths, query ordering, redirect trails, and registrable-domain scope checks stay predictable
- Seeds from robots rules, recursive sitemaps, and archive providers
- Supports persistent HTTP sessions with retries, adaptive backoff, robots crawl-delay, checkpoint/resume, and optional JS rendering
- Collects predictable datasets for tooling and follow-up analysis
- Exports loot as plain text, JSON, or CSV

## Datasets

The crawler writes one text file per populated dataset and can also export the same structure as JSON or CSV.

| Dataset | Description |
|---|---|
| `internal` | In-scope URLs |
| `external` | Out-of-scope URLs |
| `fuzzable` | Canonicalized URLs with query parameters |
| `intel` | OSINT findings such as emails, phones, cloud buckets, social profiles, and invite links |
| `keys` | High-value secrets and fallback high-entropy tokens |
| `forms` | HTML forms with action, method, and discovered inputs |
| `files` | Static assets that were linked but not crawled as pages |
| `scripts` | JavaScript files in scope |
| `endpoints` | Paths extracted from JavaScript |
| `robots` | Applicable `robots.txt` rules plus discovered sitemap hints |
| `custom` | Matches from `-r/--regex` |
| `failed` | Requests that failed |
| `skipped` | Responses skipped before extraction |
| `redirects` | Redirect chains followed during crawling |
| `stats` | Crawl counters and telemetry |
| `subdomains` | DNS discoveries from `--dns` |

## Installation

### Direct Python

```bash
pip install -r requirements.txt
python vampire.py -u https://example.com
```

### Web crawler console

```bash
pip install -r requirements.txt
python webapp.py
```

Then open `http://127.0.0.1:8080` for the gothic DOS crawler console. The web UI wraps the existing crawler CLI, streams live crawl output, preserves exports, and writes each run under `webui_runs/`.

### Launcher scripts

Linux/macOS:

```bash
./launch.sh -u https://example.com
```

Web UI:

```bash
./launch-web.sh
```

Windows:

```cmd
launch.bat -u https://example.com
```

Double-click launcher:

```text
🦇 Double-Click to Start Vampiric Crawler.bat
```

Web UI:

```cmd
launch-web.bat
```

Double-click web UI launcher:

```text
🦇 Double-Click to Start Vampiric Web UI.bat
```

If you double-click the crawler launcher instead of passing flags in a terminal:

- the window stays open
- it tells you exactly what to do
- it prompts for the target URL
- it waits for a key press before closing

## Usage

```bash
python vampire.py -u <URL> [options]
```

### Core options

| Flag | Description | Default |
|---|---|---|
| `-u`, `--url` | Target URL | required |
| `-l`, `--level` | Crawl depth | `2` |
| `-t`, `--threads` | Worker threads | `4` |
| `-d`, `--delay` | Delay between requests in seconds | `0` |
| `--timeout` | Request timeout in seconds | `8` |
| `--scope {host,domain}` | Exact host only or the whole registered domain | `host` |
| `--scope-allow REGEX` | Extra regex a URL must match to stay in scope | none |
| `--scope-deny REGEX` | Regex that forces matching URLs out of scope | none |
| `--checkpoint FILE` | Save crawl state for later resume | none |
| `--resume FILE` | Resume from a previous checkpoint | none |
| `-s`, `--seeds` | Additional seed URLs | none |
| `--exclude` | Exclude URLs matching a regex | none |
| `-o`, `--output` | Output directory | target host |
| `-v`, `--verbose` | Verbose crawl output | off |

### Request and network options

| Flag | Description |
|---|---|
| `-c`, `--cookie` | Cookie header value |
| `--user-agent` | Comma-separated custom user agents |
| `-H`, `--header`, `--headers` | Repeatable custom header in `Key: Value` format |
| `-p`, `--proxy` | Comma-separated proxies in `HOST:PORT` form |
| `--respect-robots-delay` | Honor `Crawl-delay` when a robots rule provides one |
| `--host-concurrency` | Maximum concurrent requests per host |
| `--disable-adaptive-backoff` | Disable 429/503 adaptive backoff |

### Extraction options

| Flag | Description |
|---|---|
| `--keys` | Enable secret detection |
| `--dns` | Enumerate common subdomains |
| `--wayback` | Seed from archive providers such as Wayback and Common Crawl |
| `--only-urls` | Skip non-URL extraction |
| `--render-js` | Render pages in headless Chromium before extraction |
| `--render-timeout` | Per-page render timeout in seconds |
| `-r`, `--regex` | Custom regex for extra extraction |

### Output options

| Flag | Description |
|---|---|
| `--stdout DATASET` | Print one dataset to stdout |
| `-e`, `--export {json,csv}` | Export results in addition to text files |

## Examples

Basic crawl:

```bash
python vampire.py -u https://example.com
```

Domain-wide crawl with retries, custom headers, and JSON export:

```bash
python vampire.py \
  -u https://app.example.com \
  --scope domain \
  -H "Authorization: Bearer <token>" \
  -H "X-Night: eternal" \
  --keys \
  -e json
```

Print canonical fuzzables only:

```bash
python vampire.py -u https://example.com --only-urls --stdout fuzzable
```

Use proxies and archived seeds:

```bash
python vampire.py \
  -u https://example.com \
  -p 127.0.0.1:8080,127.0.0.1:8081 \
  --wayback
```

## JavaScript rendering

`--render-js` uses Playwright + headless Chromium so SPA-only routes, forms, and fetch targets can be discovered from the rendered DOM and browser network activity.

After installing requirements, install the browser once:

```bash
python -m playwright install chromium
```

## Checkpoint / resume

Use `--checkpoint crawl.json` to persist crawler state after seeding, each crawl depth, script scanning, and final completion. Restart the same hunt later with `--resume crawl.json`.

## Output structure

Example loot directory:

```text
example.com/
├── custom.txt
├── endpoints.txt
├── external.txt
├── failed.txt
├── files.txt
├── forms.txt
├── fuzzable.txt
├── intel.txt
├── internal.txt
├── keys.txt
├── redirects.txt
├── results.csv
├── results.json
├── robots.txt
├── scripts.txt
├── skipped.txt
├── stats.txt
└── subdomains.txt
```

## Notes on behavior

- URLs are canonicalized before being queued, classified, and exported
- Fuzzable URLs are normalized to stable parameter-key sets
- Redirects, status handling, content-type checks, and optional rendered-DOM extraction happen before analysis
- Robots rules are parsed by user-agent group, crawl-delay can be honored, sitemap indexes recurse with loop protection, and archive seeding is bounded
- Scope is explicit and uses registrable-domain parsing rather than a naive two-label split:
  - `host`: stay on the exact host
  - `domain`: allow the full registered domain, including subdomains

## Current secret coverage

With `--keys`, the crawler looks for patterns such as:

- AWS access key IDs
- GitHub tokens
- Slack tokens
- Stripe live secrets
- Google API keys
- JWTs
- Private key blocks
- Fallback high-entropy tokens

## Current intel coverage

The crawler extracts or records findings such as:

- Emails
- Phone numbers
- IP addresses
- Credit cards and SSNs
- Bitcoin addresses
- AWS / GCP / Azure storage references
- GitHub, LinkedIn, Facebook, Instagram, Reddit, Twitter, YouTube
- Discord invites, Telegram handles, Pastebin links

## Project layout

```text
vampiric-crawler/
├── vampire.py
├── launch.sh
├── launch.bat
├── requirements.txt
├── core/
└── plugins/
```

## License

GPL v3.0. Hunt responsibly.

Inspired by Photon, but dressed for the crypt.
