"""HTTP requester for Vampiric Crawler."""
import random
import time

import requests
import warnings

from core.colors import coffin, crypt
import core.config

warnings.filterwarnings('ignore')

# File extensions we treat as static assets (not crawl-worthy HTML pages)
BINARY_EXTENSIONS = frozenset((
    'png', 'jpg', 'jpeg', 'gif', 'bmp', 'svg', 'ico', 'webp',
    'mp3', 'mp4', 'wav', 'ogg', 'webm', 'flv', 'avi', 'mov',
    'zip', 'tar', 'gz', 'bz2', '7z', 'rar',
    'exe', 'dll', 'so', 'bin',
    'ttf', 'woff', 'woff2', 'eot',
))


def is_binary_url(url):
    """Return True if the URL points at a binary / non-HTML asset."""
    path = url.split('?')[0].split('#')[0]
    ext = path.rsplit('.', 1)[-1].lower() if '.' in path else ''
    return ext in BINARY_EXTENSIONS


def requester(url, main_url, delay, cook, headers, timeout, host, proxies,
              user_agents, failed, processed):
    """Fetch *url* and return the response body as a string (or '')."""
    processed.add(url)

    if is_binary_url(url):
        return ''

    time.sleep(delay)

    try:
        proxy = random.choice(proxies)
        proxy_dict = proxy if proxy else None

        ua = random.choice(user_agents) if user_agents else (
            'Mozilla/5.0 (compatible; VampiricCrawler/1.0)'
        )

        req_headers = {'User-Agent': ua}
        if cook:
            req_headers['Cookie'] = cook
        if headers:
            req_headers.update(headers)

        resp = requests.get(
            url,
            headers=req_headers,
            proxies=proxy_dict,
            timeout=timeout,
            verify=False,
            allow_redirects=True,
        )

        if core.config.verbose:
            print(f'{crypt}Drained {resp.status_code} ← {url}')

        return resp.text

    except Exception as exc:
        failed.add(url)
        if core.config.verbose:
            print(f'{coffin}Failed to feed on {url} — {exc}')
        return ''
