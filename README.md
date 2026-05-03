# 🦇 Vampiric Crawler

> *"The night yields no secrets to those who do not hunt."*

A **gothic-themed OSINT web crawler** inspired by [Photon](https://github.com/s0md3v/Photon).  
Built to run from anywhere — including an **external hard drive** — with a single command.

---

## ✦ Features

| Feature | Description |
|---|---|
| 🕸️ **Multi-threaded crawling** | Configurable fangs (threads) for fast, deep hunts |
| 📧 **Intel extraction** | Emails, phone numbers, social accounts, cloud buckets |
| 🔑 **Secret key detection** | High-entropy strings: API keys, auth tokens |
| 📄 **File harvesting** | PDFs, images, archives and other assets |
| ⚡ **JS endpoint scanning** | Extracts API paths from JavaScript files |
| 🔗 **Fuzzable URL collection** | URLs with query parameters, ready for testing |
| 🌐 **Subdomain enumeration** | Common subdomain bruteforce via `--dns` |
| 📜 **Wayback Machine seeds** | Pull archived URLs as extra crawl seeds |
| 🗂️ **Export** | Save loot as JSON or CSV in addition to plain text |
| 🎭 **Custom regex** | Extract anything you want with `-r <pattern>` |
| 🛡️ **Proxy support** | Route traffic through one or more proxies |
| 🔄 **User-agent rotation** | Blend into the night with random user agents |

---

## 🚀 Quick Start

### Prerequisites
- **Python 3.6+** (the only requirement)
- Internet access

### From an External Hard Drive (or any directory)

**Linux / macOS:**
```bash
# Navigate to the drive
cd /media/yourname/VampireDrive/vampiric-crawler

# One-shot launch (installs deps automatically)
./launch.sh -u https://example.com
```

**Windows:**
```cmd
:: Navigate to the drive
cd E:\vampiric-crawler

:: Double-click launch.bat or run:
launch.bat -u https://example.com
```

**Direct Python:**
```bash
pip install -r requirements.txt
python vampire.py -u https://example.com
```

---

## 🦇 Usage

```
python vampire.py -u <URL> [options]
```

### Essential Options

| Flag | Description | Default |
|---|---|---|
| `-u URL` | Target URL (the prey) | *required* |
| `-l N` | Crawl depth | `2` |
| `-t N` | Threads (fangs) | `4` |
| `-d N` | Delay between requests (seconds) | `0` |
| `--timeout N` | HTTP timeout (seconds) | `8` |
| `-o DIR` | Output directory | `<hostname>` |
| `-v` | Verbose (show every drop) | off |

### Extraction Options

| Flag | Description |
|---|---|
| `--keys` | Extract high-entropy strings (API keys, tokens) |
| `--dns` | Enumerate subdomains |
| `--wayback` | Seed from Wayback Machine archive |
| `--only-urls` | Skip intel extraction, harvest URLs only |
| `-r PATTERN` | Extract strings matching custom regex |
| `--exclude PATTERN` | Skip URLs matching this regex |

### Network Options

| Flag | Description |
|---|---|
| `-c COOKIE` | Cookie header value |
| `--user-agent UA` | Custom user agent(s), comma-separated |
| `-H "Key: Value"` | Add a custom header (repeatable) |
| `-p HOST:PORT` | Proxy or proxies (comma-separated) |

### Output Options

| Flag | Description |
|---|---|
| `-e json\|csv` | Export results as JSON or CSV |
| `--stdout DATASET` | Print a dataset to stdout (`internal`, `intel`, `keys`, …) |

---

## 📖 Examples

```bash
# Basic hunt
python vampire.py -u https://example.com

# Deep hunt with 8 threads, verbose output
python vampire.py -u https://example.com -l 3 -t 8 -v

# Extract secret keys + export as JSON
python vampire.py -u https://example.com --keys -e json

# Seed from Wayback Machine + enumerate subdomains
python vampire.py -u https://example.com --wayback --dns

# Use a proxy and a custom cookie
python vampire.py -u https://example.com -p 127.0.0.1:8080 -c "session=abc123"

# Send custom headers with every nocturnal request
python vampire.py -u https://example.com -H "Authorization: Bearer token" -H "X-Night: eternal"

# Only collect URLs with parameters (fuzzable), pipe to another tool
python vampire.py -u https://example.com --only-urls --stdout fuzzable

# Find all email addresses
python vampire.py -u https://example.com --stdout intel | grep EMAIL
```

---

## 🗂️ Output

Results are saved in a directory named after the target host (or the path you specify with `-o`):

```
example.com/
├── internal.txt    # In-scope URLs
├── external.txt    # Out-of-scope URLs
├── fuzzable.txt    # URLs with query parameters
├── files.txt       # Static assets
├── scripts.txt     # JavaScript files
├── endpoints.txt   # JS-extracted API paths
├── intel.txt       # Emails, accounts, buckets
├── keys.txt        # Potential API/auth keys
├── robots.txt      # robots.txt entries
├── custom.txt      # Custom regex matches
├── failed.txt      # URLs that could not be fetched
├── skipped.txt     # Responses skipped before extraction
├── redirects.txt   # Redirect trails followed during the crawl
├── stats.txt       # Crawl counters and telemetry
├── subdomains.txt  # (--dns only)
├── results.json    # (-e json only)
└── results.csv     # (-e csv only)
```

---

## 🏗️ Architecture

```
vampiric-crawler/
├── vampire.py          ← main entry point
├── launch.sh           ← one-click launcher (Linux/macOS)
├── launch.bat          ← one-click launcher (Windows)
├── requirements.txt    ← Python dependencies
├── core/
│   ├── colors.py       ← terminal colour codes
│   ├── config.py       ← global settings & intel domain list
│   ├── flash.py        ← thread-pool executor
│   ├── regex.py        ← all compiled regex patterns
│   ├── requester.py    ← HTTP fetcher
│   ├── utils.py        ← utility functions
│   ├── user-agents.txt ← user-agent pool
│   └── zap.py          ← seed harvester (robots/sitemap/wayback)
└── plugins/
    └── exporter.py     ← JSON / CSV exporter
```

---

## 💡 Tips for External Hard Drive Use

1. **No installation needed** — `launch.sh` / `launch.bat` auto-installs Python deps.
2. **Set `-o /path/on/drive`** to save loot directly on the external drive.
3. Use `--timeout 12` on slow network connections.
4. On Windows: run as Administrator if the drive is NTFS to avoid permission issues.

---

## ⚖️ License

GPL v3.0 — Hunt responsibly. Only use on targets you have permission to crawl.

---

*Inspired by [Photon](https://github.com/s0md3v/Photon) by s0md3v.*
