# 🦇 Vampiric Crawler

Vampiric Crawler is a Photon-inspired OSINT crawler with a gothic accent: fast enough for reconnaissance, readable enough for operators, and theatrical only where it helps.

## What it does

- Crawls a target with configurable depth, threads, delay, timeout, headers, cookies, proxies, and user-agent rotation
- Normalizes URLs so duplicate paths, query ordering, and redirect trails stay predictable
- Seeds from robots rules, recursive sitemaps, and archive providers
- Supports persistent HTTP sessions with retries
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

### Launcher scripts

Linux/macOS:

```bash
./launch.sh -u https://example.com
```

Windows:

```cmd
launch.bat -u https://example.com
```

If you double-click the launcher instead of passing flags in a terminal, it will prompt for the target URL first.

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

### Extraction options

| Flag | Description |
|---|---|
| `--keys` | Enable secret detection |
| `--dns` | Enumerate common subdomains |
| `--wayback` | Seed from archive providers such as Wayback and Common Crawl |
| `--only-urls` | Skip non-URL extraction |
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
- Redirects, status handling, and content-type checks happen before extraction
- Robots rules are parsed by user-agent group, sitemap indexes recurse with loop protection, and archive seeding is bounded
- Scope is explicit:
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
