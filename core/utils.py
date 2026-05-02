"""Utility helpers for Vampiric Crawler."""
import math
import re
import sys

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
        if ':' in line:
            key, _, value = line.partition(':')
            headers[key.strip()] = value.strip()
    return headers
