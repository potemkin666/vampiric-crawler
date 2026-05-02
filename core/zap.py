"""Seed harvester: robots.txt, sitemap.xml, and Wayback Machine URLs."""
import re
import warnings

import requests

warnings.filterwarnings('ignore')


def _fetch(url, timeout=8):
    """Return the text body of *url* or ''."""
    try:
        r = requests.get(url, timeout=timeout, verify=False,
                         headers={'User-Agent': 'VampiricCrawler/1.0'})
        return r.text
    except Exception:
        return ''


def _parse_robots(main_url, internal):
    """Add paths from robots.txt to *internal*."""
    body = _fetch(main_url.rstrip('/') + '/robots.txt')
    paths = re.findall(r'(?:Allow|Disallow):\s*(/[^\s]*)', body, re.I)
    for path in paths:
        if '*' not in path:
            internal.add(main_url.rstrip('/') + path)
    return set(paths)


def _parse_sitemap(main_url, internal):
    """Add URLs from sitemap.xml to *internal*."""
    body = _fetch(main_url.rstrip('/') + '/sitemap.xml')
    urls = re.findall(r'<loc>(.*?)</loc>', body, re.I)
    for url in urls:
        internal.add(url.strip())


def _wayback(domain, internal):
    """Fetch archived URLs for *domain* from the Wayback CDX API."""
    api = (
        f'http://web.archive.org/cdx/search/cdx'
        f'?url={domain}/*&output=text&fl=original&collapse=urlkey&limit=200'
    )
    body = _fetch(api, timeout=15)
    for line in body.splitlines():
        line = line.strip()
        if line:
            internal.add(line)


def zap(main_url, use_wayback, domain, host, internal, robots, proxies):
    """Populate *internal* with seed URLs from robots.txt / sitemap / wayback."""
    robots.update(_parse_robots(main_url, internal))
    _parse_sitemap(main_url, internal)
    if use_wayback:
        _wayback(domain, internal)
