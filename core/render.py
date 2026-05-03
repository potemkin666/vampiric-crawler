"""Optional Playwright-backed JavaScript rendering."""
import atexit
import threading
from urllib.parse import urlsplit


class RenderResult(object):
    """Rendered page content plus extra discovered URLs."""

    def __init__(self, html='', urls=None):
        self.html = html or ''
        self.urls = set(urls or ())


_playwright_lock = threading.Lock()
_playwright_manager = None
_browser = None


COMMON_RENDER_SELECTORS = (
    'a[href]', 'link[href]', 'script[src]', 'img[src]', 'source[src]',
    'iframe[src]', 'form[action]'
)


def render_page(url, timeout=8, headers=None, cookie=None, user_agent=None):
    """Render *url* in a headless browser and return a :class:`RenderResult`."""
    browser = _get_browser()
    context_kwargs = {
        'ignore_https_errors': True,
    }
    if user_agent:
        context_kwargs['user_agent'] = user_agent
    if headers:
        context_kwargs['extra_http_headers'] = dict(headers)
    context = browser.new_context(**context_kwargs)
    try:
        _apply_cookie_header(context, url, cookie)
        page = context.new_page()
        discovered_urls = set()
        page.on('response', lambda response: discovered_urls.add(response.url))
        page.goto(url, wait_until='networkidle', timeout=max(int(float(timeout or 8) * 1000), 1000))
        html = page.content()
        selector = ', '.join(COMMON_RENDER_SELECTORS)
        dom_urls = page.eval_on_selector_all(
            selector,
            'elements => elements.map(el => el.href || el.src || el.action).filter(Boolean)',
        )
        discovered_urls.update(dom_urls or [])
        return RenderResult(html=html, urls=discovered_urls)
    finally:
        context.close()


def _apply_cookie_header(context, url, cookie_header):
    """Translate a Cookie header string into browser cookies."""
    if not cookie_header:
        return
    parsed = urlsplit(url)
    domain = parsed.hostname or ''
    secure = parsed.scheme == 'https'
    cookies = []
    for pair in str(cookie_header).split(';'):
        name, sep, value = pair.strip().partition('=')
        if not sep or not name:
            continue
        cookies.append({
            'name': name.strip(),
            'value': value.strip(),
            'domain': domain,
            'path': '/',
            'httpOnly': False,
            'secure': secure,
        })
    if cookies:
        context.add_cookies(cookies)


def _get_browser():
    """Return a shared Chromium browser instance."""
    global _playwright_manager, _browser
    with _playwright_lock:
        if _browser is not None:
            return _browser
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                'JavaScript rendering requires the playwright package. '
                'Install dependencies and run "python -m playwright install chromium".'
            ) from exc
        try:
            _playwright_manager = sync_playwright().start()
            _browser = _playwright_manager.chromium.launch(headless=True)
        except Exception as exc:
            raise RuntimeError(
                'Failed to launch Playwright Chromium. Run "python -m playwright install chromium" '
                'before using --render-js.'
            ) from exc
        return _browser


@atexit.register
def _shutdown_browser():
    global _playwright_manager, _browser
    with _playwright_lock:
        if _browser is not None:
            try:
                _browser.close()
            except Exception:
                pass
            _browser = None
        if _playwright_manager is not None:
            try:
                _playwright_manager.stop()
            except Exception:
                pass
            _playwright_manager = None
