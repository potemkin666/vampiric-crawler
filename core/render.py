"""Optional Playwright-backed JavaScript rendering."""
import atexit
import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


class RenderResult(object):
    """Rendered page content plus extra discovered URLs."""

    def __init__(self, html='', urls=None, dom_sha256='', screenshot_path='', metadata_path='', final_url='', metadata=None):
        self.html = html or ''
        self.urls = set(urls or ())
        self.dom_sha256 = dom_sha256 or ''
        self.screenshot_path = screenshot_path or ''
        self.metadata_path = metadata_path or ''
        self.final_url = final_url or ''
        self.metadata = dict(metadata or {})


_playwright_lock = threading.Lock()
_playwright_manager = None
_browser = None


COMMON_RENDER_SELECTORS = (
    'a[href]', 'link[href]', 'script[src]', 'img[src]', 'source[src]',
    'iframe[src]', 'form[action]'
)


def render_page(url, timeout=8, headers=None, cookie=None, user_agent=None, evidence_dir=None, evidence_prefix=None):
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
        response = page.goto(url, wait_until='networkidle', timeout=max(int(float(timeout or 8) * 1000), 1000))
        html = page.content()
        dom_sha256 = hashlib.sha256(html.encode('utf-8', 'ignore')).hexdigest() if html else ''
        selector = ', '.join(COMMON_RENDER_SELECTORS)
        dom_urls = page.eval_on_selector_all(
            selector,
            'elements => elements.map(el => el.href || el.src || el.action).filter(Boolean)',
        )
        discovered_urls.update(dom_urls or [])
        final_url = getattr(response, 'url', '') or url
        metadata = {
            'requested_url': url,
            'final_url': final_url,
            'captured_at': datetime.now(timezone.utc).isoformat(),
            'dom_sha256': dom_sha256,
            'html_length': len(html or ''),
            'discovered_urls': sorted(discovered_urls),
        }
        screenshot_bytes = b''
        if hasattr(page, 'screenshot'):
            screenshot_bytes = page.screenshot(full_page=True, type='png') or b''
        screenshot_path = ''
        metadata_path = ''
        if evidence_dir:
            evidence_root = Path(evidence_dir)
            evidence_root.mkdir(parents=True, exist_ok=True)
            stem = _evidence_stem(evidence_prefix or final_url or url)
            if screenshot_bytes:
                screenshot_file = evidence_root / f'{stem}.png'
                screenshot_file.write_bytes(screenshot_bytes)
                screenshot_path = str(screenshot_file)
            metadata_file = evidence_root / f'{stem}.json'
            metadata.update({
                'screenshot_path': screenshot_path,
                'metadata_path': str(metadata_file),
            })
            metadata_file.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding='utf-8')
            metadata_path = str(metadata_file)
        return RenderResult(
            html=html,
            urls=discovered_urls,
            dom_sha256=dom_sha256,
            screenshot_path=screenshot_path,
            metadata_path=metadata_path,
            final_url=final_url,
            metadata=metadata,
        )
    finally:
        context.close()


def _evidence_stem(value):
    parsed = urlsplit(str(value or 'rendered-page'))
    base = parsed.netloc or parsed.path or 'rendered-page'
    safe = ''.join(char if char.isalnum() else '-' for char in base.lower()).strip('-') or 'rendered-page'
    digest = hashlib.sha256(str(value or '').encode('utf-8', 'ignore')).hexdigest()[:12]
    return f'{safe}-{digest}'


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
