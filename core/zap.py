"""Seed harvester: robots.txt, sitemap.xml, and Wayback Machine URLs."""
import re
import warnings

from core.requester import get_session

warnings.filterwarnings('ignore')


def _fetch(url, timeout=8, headers=None, proxies=None):
    """Return the text body of *url* or ''."""
    try:
        req_headers = {'User-Agent': 'VampiricCrawler/1.0'}
        if headers:
            req_headers.update(headers)
        r = get_session().get(url, timeout=timeout, verify=False,
                              headers=req_headers, proxies=proxies,
                              allow_redirects=True)
        return r.text
    except Exception:
        return ''


def _parse_robots(main_url, internal, headers=None, proxies=None):
    """Add paths from robots.txt to *internal*."""
    body = _fetch(main_url.rstrip('/') + '/robots.txt', headers=headers,
                  proxies=proxies)
    paths = re.findall(r'(?:Allow|Disallow):\s*(/[^\s]*)', body, re.I)
    for path in paths:
        if '*' not in path:
            internal.add(main_url.rstrip('/') + path)
    return set(paths)


def _parse_sitemap(main_url, internal, headers=None, proxies=None):
    """Add URLs from sitemap.xml to *internal*."""
    body = _fetch(main_url.rstrip('/') + '/sitemap.xml', headers=headers,
                  proxies=proxies)
    urls = re.findall(r'<loc>(.*?)</loc>', body, re.I)
    for url in urls:
        internal.add(url.strip())


def _wayback(domain, internal, proxies=None):
    """Fetch archived URLs for *domain* from the Wayback CDX API."""
    api = (
        f'http://web.archive.org/cdx/search/cdx'
        f'?url={domain}/*&output=text&fl=original&collapse=urlkey&limit=200'
    )
    body = _fetch(api, timeout=15, proxies=proxies)
    for line in body.splitlines():
        line = line.strip()
        if line:
            internal.add(line)


def zap(main_url, use_wayback, domain, host, internal, robots, proxies,
        headers=None):
    """Populate *internal* with seed URLs from robots.txt / sitemap / wayback."""
    proxy = proxies[0] if proxies else None
    robots.update(_parse_robots(main_url, internal, headers=headers,
                                proxies=proxy))
    _parse_sitemap(main_url, internal, headers=headers, proxies=proxy)
    if use_wayback:
        _wayback(domain, internal, proxies=proxy)
