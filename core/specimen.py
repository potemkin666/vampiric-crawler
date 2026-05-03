"""Specimen classification and ritual/preset resolution."""
from __future__ import annotations

import os
import re
from urllib.parse import parse_qs, unquote, urlsplit

from core.modes import (
    PRESET_DEFINITIONS,
    RITUAL_CHAIN_DEFINITIONS,
    coerce_mode,
    coerce_preset,
    coerce_ritual_chain,
)
from core.utils import normalize_url

DOMAIN_RE = re.compile(r'^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$', re.I)
HANDLE_RE = re.compile(r'^@?[a-z0-9_.-]{2,64}$', re.I)
URL_RE = re.compile(r'^https?://', re.I)
HTML_RE = re.compile(r'<(?:!doctype\s+html|html|head|body|a\b|form\b|script\b)', re.I)
ARCHIVE_HOSTS = ('web.archive.org', 'archive.ph', 'archive.is', 'archive.today')

SPECIMEN_KIND_CHOICES = (
    'auto', 'domain', 'url', 'company', 'handle', 'sitemap',
    'dead_url', 'archived_url', 'pdf', 'js', 'html',
)

SPECIMEN_TO_RITUAL = {
    'domain': 'domain_necropsy',
    'url': 'domain_necropsy',
    'sitemap': 'domain_necropsy',
    'dead_url': 'dead_page_resurrection',
    'archived_url': 'dead_page_resurrection',
    'pdf': 'pdf_fossil_dig',
    'js': 'js_bone_saw',
    'html': 'domain_necropsy',
    'company': 'scam_smell_test',
    'handle': 'scam_smell_test',
}


def classify_specimen(raw_value: str | None, explicit_kind: str | None = None) -> dict[str, object]:
    """Return a normalized specimen profile."""
    raw = (raw_value or '').strip()
    explicit = (explicit_kind or 'auto').strip().lower()
    local_path = raw if raw and os.path.isfile(raw) else ''
    specimen_type = _classify_type(raw, explicit, local_path)
    canonical_target = raw
    crawl_roots: list[str] = []
    notes: list[str] = []
    source = 'inline'
    inline_payload = ''
    archive_hint = False

    if specimen_type == 'html':
        source = 'pasted-html'
        inline_payload = raw if raw and not local_path else _read_text_file(local_path)
        canonical_target = 'inline-html'
    elif local_path:
        source = 'local-file'
        canonical_target = os.path.abspath(local_path)
        if specimen_type in {'pdf', 'js'}:
            notes.append('Local artifact specimen will be analyzed directly without network crawl.')
    elif specimen_type == 'domain':
        source = 'domain'
        canonical_target = raw.lower()
        crawl_roots = [normalize_url('https://' + canonical_target)]
    elif specimen_type in {'url', 'dead_url', 'sitemap', 'pdf', 'js'}:
        source = 'url'
        canonical_target = normalize_url(raw) or raw
        if canonical_target:
            crawl_roots = [canonical_target]
    elif specimen_type == 'archived_url':
        source = 'archive'
        archive_hint = True
        canonical_target = normalize_url(_extract_original_archive_target(raw) or raw) or raw
        if canonical_target:
            crawl_roots = [canonical_target]
        notes.append('Archived specimen will bias toward archive seeding and temporal analysis.')
    elif specimen_type == 'handle':
        source = 'handle'
        canonical_target = raw.lstrip('@')
        notes.append('Social handles do not resolve to a crawl root automatically; provide a URL or domain for live crawling.')
    else:
        source = 'company'
        notes.append('Company-name specimens are classified for ritual selection but require a resolvable URL or domain for live crawling.')

    return {
        'input': raw,
        'type': specimen_type,
        'source': source,
        'canonical_target': canonical_target,
        'crawl_roots': [item for item in crawl_roots if item],
        'archive_hint': archive_hint,
        'confidence': _classification_confidence(specimen_type, raw, explicit),
        'notes': notes,
        'inline_payload': inline_payload,
        'local_path': local_path,
    }


def choose_ritual_chain(specimen: dict[str, object], override: str | None = None) -> str:
    """Return a ritual chain for *specimen*."""
    if override:
        return coerce_ritual_chain(override)
    return coerce_ritual_chain(SPECIMEN_TO_RITUAL.get(str(specimen.get('type')), 'domain_necropsy'))


def resolve_ritual_plan(
    specimen: dict[str, object],
    ritual_chain: str | None = None,
    mode_override: str | None = None,
) -> dict[str, object]:
    """Return a normalized ritual plan for a specimen."""
    ritual = coerce_ritual_chain(ritual_chain or choose_ritual_chain(specimen))
    definition = RITUAL_CHAIN_DEFINITIONS[ritual]
    mode = coerce_mode(mode_override or definition['default_mode'])
    defaults = dict(definition.get('defaults', {}))
    return {
        'ritual_chain': ritual,
        'label': definition['label'],
        'description': definition['description'],
        'mode': mode,
        'defaults': defaults,
        'seed_urls': _ritual_seed_urls(specimen),
    }


def apply_preset(payload: dict[str, object], preset: str | None, explicit_keys: set[str] | None = None) -> dict[str, object]:
    """Apply preset defaults to payload without clobbering explicit keys."""
    explicit = set(explicit_keys or ())
    chosen = coerce_preset(preset)
    definition = PRESET_DEFINITIONS[chosen]
    resolved = dict(payload)
    for key, value in definition.get('defaults', {}).items():
        if key in explicit:
            continue
        resolved[key] = value
    resolved['preset'] = chosen
    return resolved


def resolve_main_target(specimen: dict[str, object]) -> str:
    """Return the primary crawl root for *specimen* or an empty string."""
    roots = specimen.get('crawl_roots') or []
    return str(roots[0]) if roots else ''


def setup_status() -> dict[str, object]:
    """Return friendly first-run dependency status."""
    packages = {}
    for module_name in ('requests', 'urllib3', 'tldextract', 'flask', 'playwright'):
        try:
            __import__(module_name)
            packages[module_name] = 'ok'
        except Exception as exc:
            packages[module_name] = f'missing: {exc}'
    browser = 'unknown'
    try:
        from playwright.sync_api import sync_playwright
        manager = sync_playwright().start()
        try:
            manager.chromium.launch(headless=True).close()
            browser = 'ok'
        finally:
            manager.stop()
    except Exception as exc:
        browser = f'missing: {exc}'
    return {
        'packages': packages,
        'playwright_browser': browser,
        'install_hint': 'python -m pip install -r requirements.txt',
        'browser_hint': 'python -m playwright install chromium',
    }


def _classify_type(raw: str, explicit: str, local_path: str) -> str:
    if explicit and explicit != 'auto':
        return explicit
    lowered = raw.lower()
    if local_path:
        ext = os.path.splitext(local_path)[1].lower()
        if ext == '.js':
            return 'js'
        if ext == '.pdf':
            return 'pdf'
        if ext in ('.html', '.htm'):
            return 'html'
    if HTML_RE.search(raw):
        return 'html'
    if URL_RE.match(raw):
        parsed = urlsplit(raw)
        if parsed.hostname in ARCHIVE_HOSTS:
            return 'archived_url'
        if 'dead' in lowered or '404' in lowered:
            return 'dead_url'
        if lowered.endswith('.xml') or 'sitemap' in lowered:
            return 'sitemap'
        if lowered.endswith('.pdf'):
            return 'pdf'
        if lowered.endswith(('.js', '.mjs', '.cjs')):
            return 'js'
        return 'url'
    if DOMAIN_RE.fullmatch(raw):
        return 'domain'
    if HANDLE_RE.fullmatch(raw) and (raw.startswith('@') or any(ch in raw for ch in '._-')):
        return 'handle'
    return 'company'


def _extract_original_archive_target(raw: str) -> str:
    parsed = urlsplit(raw)
    if parsed.hostname == 'web.archive.org':
        query_target = parse_qs(parsed.query).get('url', [''])[0]
        if query_target:
            return query_target
        path = unquote(parsed.path)
        if '/http' in path:
            _, _, target = path.partition('/http')
            return 'http' + target
    return raw


def _classification_confidence(specimen_type: str, raw: str, explicit: str) -> float:
    if explicit and explicit != 'auto':
        return 0.99
    if specimen_type in {'url', 'domain', 'pdf', 'js', 'sitemap', 'html', 'archived_url'}:
        return 0.95
    if specimen_type == 'dead_url':
        return 0.75
    if specimen_type == 'handle':
        return 0.7
    if raw:
        return 0.6
    return 0.0


def _read_text_file(path: str) -> str:
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            return handle.read()
    except OSError:
        return ''


def _ritual_seed_urls(specimen: dict[str, object]) -> list[str]:
    specimen_type = str(specimen.get('type'))
    roots = list(specimen.get('crawl_roots') or [])
    if specimen_type == 'sitemap' and roots:
        parsed = urlsplit(roots[0])
        site_root = normalize_url(f'{parsed.scheme}://{parsed.netloc}/')
        return [roots[0], site_root] if site_root else roots
    return roots
