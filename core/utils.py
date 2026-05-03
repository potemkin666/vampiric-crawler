"""Utility helpers for Vampiric Crawler."""
import math
import re
import sys
import threading

import core.config
from core.colors import crypt


# ---------------------------------------------------------------------------
# Entropy helper
# ---------------------------------------------------------------------------

def entropy(string):
    """Calculate Shannon entropy of *string*."""
    if not string:
        return 0.0
    prob = [float(string.count(c)) / len(string) for c in set(string)]
    return -sum(p * math.log(p, 2) for p in prob)


# ---------------------------------------------------------------------------
# Luhn algorithm (credit card validation)
# ---------------------------------------------------------------------------

def luhn(number):
    """Return True if *number* (str or tuple of digit chars) passes Luhn."""
    if isinstance(number, tuple):
        number = ''.join(number)
    number = re.sub(r'\D', '', str(number))
    total = 0
    reverse_digits = number[::-1]
    for i, digit in enumerate(reverse_digits):
        n = int(digit)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

_FILE_EXTENSIONS = frozenset((
    'pdf', 'jpg', 'jpeg', 'png', 'gif', 'bmp', 'svg', 'ico', 'webp',
    'mp3', 'mp4', 'avi', 'mov', 'webm', 'wav', 'ogg',
    'zip', 'tar', 'gz', 'bz2', '7z', 'rar',
    'exe', 'dll', 'so', 'bin',
    'ttf', 'woff', 'woff2', 'eot',
    'xml', 'json', 'csv', 'txt',
    'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
    'css',
))


def is_link(url, processed, files):
    """Return True if *url* should be enqueued for crawling."""
    if not url or url in processed:
        return False
    if url.startswith(('javascript:', 'mailto:', 'tel:', 'data:', '#', 'void')):
        return False
    ext = url.split('?')[0].rsplit('.', 1)[-1].lower() if '.' in url.split('?')[0] else ''
    if ext in _FILE_EXTENSIONS:
        files.add(url)
        return False
    return True


def top_level(url, fix_protocol=False):
    """Return the registered (eTLD+1) domain of *url*."""
    from urllib.parse import urlparse
    if fix_protocol and not url.startswith('http'):
        url = 'http://' + url
    host = urlparse(url).netloc
    parts = host.split('.')
    return '.'.join(parts[-2:]) if len(parts) >= 2 else host


def remove_regex(urls, pattern):
    """Remove URLs matching *pattern* from the iterable; return a list."""
    if not pattern:
        return list(urls)
    compiled = re.compile(pattern)
    return [u for u in urls if not compiled.search(u)]


def remove_file(url):
    """Strip the last path segment from *url* (used for relative links)."""
    if url.count('/') > 2:
        replaceable = re.search(r'/[^/]*?$', url)
        if replaceable and replaceable.group() != '/':
            return url.replace(replaceable.group(), '')
    return url


# ---------------------------------------------------------------------------
# Verbose output
# ---------------------------------------------------------------------------

def verb(label, value):
    """Print a verbose message if verbose mode is on."""
    if core.config.verbose:
        print(f'{crypt}{label}: {value}')


# ---------------------------------------------------------------------------
# Proxy helper
# ---------------------------------------------------------------------------

def proxy_type(proxy_str):
    """Parse a list of proxy strings into requests-compatible dicts."""
    proxies = []
    for p in proxy_str.split(','):
        p = p.strip()
        if p:
            proxies.append({'http': f'http://{p}', 'https': f'http://{p}'})
    return proxies


def is_good_proxy(proxy):
    """Return True if the proxy is reachable."""
    import requests, warnings
    warnings.filterwarnings('ignore')
    try:
        requests.get('https://example.com', proxies=proxy, timeout=5, verify=False)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Custom regex extractor
# ---------------------------------------------------------------------------

def regxy(pattern, response, suppress, custom):
    """Apply a custom regex *pattern* to *response* and collect matches."""
    if suppress:
        return
    try:
        matches = re.findall(pattern, response)
        for match in matches:
            verb('Custom', match)
            custom.add(match)
    except re.error as exc:
        print(f'Invalid regex pattern: {exc}', file=sys.stderr)


# ---------------------------------------------------------------------------
# Timer
# ---------------------------------------------------------------------------

def timer(diff, processed):
    """Return (minutes, seconds, time_per_request) tuple."""
    minutes = int(diff // 60)
    seconds = int(diff % 60)
    count = len(processed)
    tpr = (diff / count) if count > 0 else 0
    return minutes, seconds, tpr


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

def writer(datasets, dataset_names, output_dir):
    """Write each non-empty dataset to a text file in *output_dir*."""
    import os
    for dataset, name in zip(datasets, dataset_names):
        if dataset:
            fpath = os.path.join(output_dir, f'{name}.txt')
            with open(fpath, 'w', encoding='utf-8') as f:
                for item in sorted(dataset):
                    f.write(str(item) + '\n')


# ---------------------------------------------------------------------------
# Header extractor
# ---------------------------------------------------------------------------

def extract_headers(raw):
    """Parse raw header lines (Key: Value) into a dict."""
    headers = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if ':' not in line:
            raise ValueError(
                f'Header line must use "Key: Value" format: {line}'
            )
        key, _, value = line.partition(':')
        headers[key.strip()] = value.strip()
    return headers


# ---------------------------------------------------------------------------
# Content-type helpers
# ---------------------------------------------------------------------------

_MARKUP_CONTENT_TYPES = (
    'text/html',
    'application/xhtml+xml',
    'application/xml',
    'text/xml',
)

_SCRIPT_CONTENT_HINTS = (
    'javascript',
    'ecmascript',
)

_SKIPPED_CONTENT_PREFIXES = (
    'image/',
    'audio/',
    'video/',
    'font/',
)

_SKIPPED_CONTENT_TYPES = frozenset((
    'application/octet-stream',
    'application/pdf',
    'application/zip',
    'application/x-zip-compressed',
    'application/x-7z-compressed',
    'application/x-rar-compressed',
))


def normalize_content_type(raw):
    """Return the normalized MIME type from a Content-Type header."""
    if not raw:
        return ''
    return raw.split(';', 1)[0].strip().lower()


def should_extract_markup(content_type):
    """Return True if *content_type* should be parsed like a page."""
    if not content_type:
        return True
    if content_type in _MARKUP_CONTENT_TYPES:
        return True
    return content_type.startswith('text/')


def should_extract_script(content_type):
    """Return True if *content_type* should be parsed like script/text."""
    if not content_type:
        return True
    if any(hint in content_type for hint in _SCRIPT_CONTENT_HINTS):
        return True
    return content_type in ('application/json', 'text/plain')


def skip_reason_for_content_type(content_type):
    """Return a machine-readable skip reason for *content_type* or None."""
    if not content_type:
        return None
    if content_type.startswith(_SKIPPED_CONTENT_PREFIXES):
        return 'binary-content'
    if content_type in _SKIPPED_CONTENT_TYPES:
        return 'binary-content'
    return None


# ---------------------------------------------------------------------------
# Crawl stats
# ---------------------------------------------------------------------------

_STAT_KEYS = (
    'requests',
    'successes',
    'redirects',
    'failures',
    'client_errors',
    'server_errors',
    'skipped',
    'binary_skips',
    'empty_responses',
    'markup_pages',
    'script_pages',
)


class CrawlStats(object):
    """Thread-safe crawl counters."""

    def __init__(self):
        self._lock = threading.Lock()
        self._counts = {key: 0 for key in _STAT_KEYS}

    def bump(self, key, amount=1):
        """Increase *key* by *amount*."""
        with self._lock:
            self._counts[key] = self._counts.get(key, 0) + amount

    def snapshot(self, visited=None):
        """Return a stable summary of the current counters."""
        with self._lock:
            counts = dict(self._counts)
        if visited is not None:
            counts['visited'] = visited
        return counts
