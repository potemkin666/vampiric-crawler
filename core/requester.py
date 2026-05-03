"""HTTP requester for Vampiric Crawler."""
import random
import time
import threading

import requests
import warnings
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from core.colors import coffin, crypt
import core.config
from core.utils import normalize_content_type, skip_reason_for_content_type

warnings.filterwarnings('ignore')

# File extensions we treat as static assets (not crawl-worthy HTML pages)
BINARY_EXTENSIONS = frozenset((
    'png', 'jpg', 'jpeg', 'gif', 'bmp', 'svg', 'ico', 'webp',
    'mp3', 'mp4', 'wav', 'ogg', 'webm', 'flv', 'avi', 'mov',
    'zip', 'tar', 'gz', 'bz2', '7z', 'rar',
    'exe', 'dll', 'so', 'bin',
    'ttf', 'woff', 'woff2', 'eot',
))

_thread_local = threading.local()
POOL_CONNECTIONS = 32
POOL_MAXSIZE = 32


class RequestResult(object):
    """Normalized HTTP response metadata for the crawler."""

    def __init__(self, url, final_url=None, text='', status_code=None,
                 content_type='', error=None, redirect_chain=None,
                 skip_reason=None):
        self.url = url
        self.final_url = final_url or url
        self.text = text or ''
        self.status_code = status_code
        self.content_type = content_type
        self.error = error
        self.redirect_chain = tuple(redirect_chain or ())
        self.skip_reason = skip_reason

    @property
    def ok(self):
        """Return True when the request finished with a 2xx status."""
        return self.error is None and self.status_code is not None and 200 <= self.status_code < 300

    @property
    def redirected(self):
        """Return True if the request followed at least one redirect."""
        return bool(self.redirect_chain)


def is_binary_url(url):
    """Return True if the URL points at a binary / non-HTML asset."""
    path = url.split('?')[0].split('#')[0]
    ext = path.rsplit('.', 1)[-1].lower() if '.' in path else ''
    return ext in BINARY_EXTENSIONS


def get_session():
    """Return a thread-local requests session with retry support."""
    session = getattr(_thread_local, 'session', None)
    if session is None:
        session = requests.Session()
        retry = Retry(
            total=3,
            connect=3,
            read=3,
            status=3,
            redirect=5,
            backoff_factor=0.4,
            status_forcelist=(429, 500, 502, 503, 504),
            # urllib3>=1.26.0 accepts allowed_methods; see requirements.txt.
            allowed_methods=frozenset(('GET',)),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(
            max_retries=retry,
            pool_connections=POOL_CONNECTIONS,
            pool_maxsize=POOL_MAXSIZE,
        )
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        _thread_local.session = session
    return session


def requester(url, main_url, delay, cook, headers, timeout, host, proxies,
              user_agents, failed, processed, stats=None):
    """Fetch *url* and return a normalized :class:`RequestResult`."""
    processed.add(url)

    if is_binary_url(url):
        if stats:
            stats.bump('skipped')
            stats.bump('binary_skips')
        return RequestResult(url, skip_reason='binary-extension')

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

        if stats:
            stats.bump('requests')

        session = get_session()
        resp = session.get(
            url,
            headers=req_headers,
            proxies=proxy_dict,
            timeout=timeout,
            verify=False,
            allow_redirects=True,
        )

        status_code = resp.status_code
        content_type = normalize_content_type(resp.headers.get('Content-Type', ''))
        redirect_chain = tuple(hop.url for hop in resp.history)

        if redirect_chain and stats:
            stats.bump('redirects', len(redirect_chain))

        if 400 <= status_code < 500:
            failed.add(url)
            if stats:
                stats.bump('failures')
                stats.bump('client_errors')
            if core.config.verbose:
                print(f'{coffin}Rejected by the prey: {status_code} ← {url}')
            return RequestResult(
                url,
                final_url=resp.url,
                status_code=status_code,
                content_type=content_type,
                redirect_chain=redirect_chain,
                error='client-error',
            )

        if status_code >= 500:
            failed.add(url)
            if stats:
                stats.bump('failures')
                stats.bump('server_errors')
            if core.config.verbose:
                print(f'{coffin}The prey fought back: {status_code} ← {url}')
            return RequestResult(
                url,
                final_url=resp.url,
                status_code=status_code,
                content_type=content_type,
                redirect_chain=redirect_chain,
                error='server-error',
            )

        if stats:
            stats.bump('successes')

        skip_reason = skip_reason_for_content_type(content_type)
        if skip_reason:
            if stats:
                stats.bump('skipped')
                stats.bump('binary_skips')
            if core.config.verbose:
                print(f'{crypt}Skipped dry content ({content_type or "unknown"}) ← {url}')
            return RequestResult(
                url,
                final_url=resp.url,
                status_code=status_code,
                content_type=content_type,
                redirect_chain=redirect_chain,
                skip_reason=skip_reason,
            )

        text = resp.text
        if not text:
            if stats:
                stats.bump('skipped')
                stats.bump('empty_responses')
            return RequestResult(
                url,
                final_url=resp.url,
                status_code=status_code,
                content_type=content_type,
                redirect_chain=redirect_chain,
                skip_reason='empty-response',
            )

        if core.config.verbose:
            redirect_count = len(redirect_chain)
            trail = (
                f' ({redirect_count} redirect'
                f'{"s" if redirect_count != 1 else ""})'
                if redirect_chain else ''
            )
            print(f'{crypt}Drained {status_code}{trail} ← {url}')

        return RequestResult(
            url,
            final_url=resp.url,
            text=text,
            status_code=status_code,
            content_type=content_type,
            redirect_chain=redirect_chain,
        )

    except Exception as exc:
        failed.add(url)
        if stats:
            stats.bump('failures')
        if core.config.verbose:
            print(f'{coffin}Failed to feed on {url} — {exc}')
        return RequestResult(url, error=str(exc))
