"""Utility helpers for Vampiric Crawler."""
import ipaddress
import math
import posixpath
import re
import sys
import threading
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import tldextract

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
    'xml', 'json', 'csv', 'txt', 'map',
    'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
    'css',
))

_EXTRACT = tldextract.TLDExtract(suffix_list_urls=None)


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
    """Return the registrable domain (eTLD+1) of *url*."""
    if fix_protocol and not url.startswith('http'):
        url = 'http://' + url
    host = urlsplit(url).hostname or ''
    if not host:
        return ''
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    extracted = _EXTRACT(host)
    if extracted.domain and extracted.suffix:
        return extracted.top_domain_under_public_suffix
    return host


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


def normalize_query_string(query):
    """Return a stable query string with sorted key/value pairs."""
    if not query:
        return ''
    pairs = parse_qsl(query, keep_blank_values=True)
    pairs.sort(key=lambda item: item[0])
    return urlencode(pairs, doseq=True)


def normalize_url(url, base_url=None, keep_query=True):
    """Return a canonical HTTP(S) URL with stable host/path/query formatting."""
    if not url:
        return ''
    candidate = url.strip()
    if not candidate:
        return ''
    if base_url:
        candidate = urljoin(base_url, candidate)
    elif candidate.startswith('//'):
        candidate = 'http:' + candidate

    parts = urlsplit(candidate)
    if parts.scheme and parts.scheme not in ('http', 'https'):
        return candidate

    scheme = (parts.scheme or '').lower()
    hostname = (parts.hostname or '').lower()
    if scheme in ('http', 'https') and not hostname:
        return ''

    port = parts.port
    netloc = hostname
    if port and not ((scheme == 'http' and port == 80) or
                     (scheme == 'https' and port == 443)):
        netloc = f'{hostname}:{port}'

    path = parts.path or '/'
    if not path.startswith('/'):
        path = '/' + path
    path = re.sub(r'/+', '/', path)
    path = posixpath.normpath(path)
    if not path.startswith('/'):
        path = '/' + path
    if path != '/':
        path = path.rstrip('/')

    query = normalize_query_string(parts.query) if keep_query else ''
    return urlunsplit((scheme, netloc, path, query, ''))


def normalize_fuzzable_url(url):
    """Return a canonical fuzzable URL with sorted unique parameter keys."""
    normalized = normalize_url(url)
    if not normalized:
        return ''
    parts = urlsplit(normalized)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    if not pairs:
        return ''
    keys = sorted({key for key, _ in pairs})
    fuzz_query = urlencode([(key, '') for key in keys], doseq=True)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, fuzz_query, ''))


def matches_scope_filters(url, allow_patterns=None, deny_patterns=None):
    """Return True when *url* passes optional allow/deny regex filters."""
    deny_patterns = deny_patterns or ()
    allow_patterns = allow_patterns or ()
    for pattern in deny_patterns:
        if pattern.search(url):
            return False
    if allow_patterns:
        return any(pattern.search(url) for pattern in allow_patterns)
    return True


def is_in_scope(url, host, domain, scope='host', allow_patterns=None, deny_patterns=None):
    """Return True if *url* belongs to the configured crawl scope."""
    hostname = (urlsplit(url).hostname or '').lower()
    target_host = (host or '').split(':', 1)[0].lower()
    if not hostname or not target_host:
        return False
    if not matches_scope_filters(url, allow_patterns, deny_patterns):
        return False
    if scope == 'host':
        return hostname == target_host
    if scope == 'domain':
        target_domain = (domain or '').lower()
        if hostname == target_host:
            return True
        return top_level(url, fix_protocol=True) == target_domain
    return False


# ---------------------------------------------------------------------------
# Verbose output
# ---------------------------------------------------------------------------

def verb(message):
    """Print a verbose message if verbose mode is on."""
    if core.config.verbose:
        print(f'{crypt}{message}')


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
            verb(f'Custom: {match}')
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
            raise ValueError('Header lines must use "Key: Value" format.')
        key, _, value = line.partition(':')
        key = key.strip()
        if not key:
            raise ValueError('Header name cannot be empty.')
        headers[key] = value.strip()
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

    def __init__(self, initial=None):
        self._lock = threading.Lock()
        self._counts = {key: 0 for key in _STAT_KEYS}
        if initial:
            for key, value in initial.items():
                if key in self._counts:
                    self._counts[key] = int(value)

    @classmethod
    def from_snapshot(cls, snapshot):
        """Restore stats from a previous :meth:`snapshot` result."""
        return cls(initial=snapshot or {})

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
