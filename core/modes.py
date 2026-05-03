"""Mode metadata and heuristics for specialized crawl runs."""
from __future__ import annotations

import io
import json
import re
import zipfile
from html import unescape
from urllib.parse import urlsplit
from xml.etree import ElementTree


MODE_DEFINITIONS = {
    'generic': {
        'label': 'Generic crawler',
        'description': 'Balanced reconnaissance across pages, forms, scripts, and linked assets.',
    },
    'document': {
        'label': 'Document harvester',
        'description': 'Prioritize linked office documents and extract metadata, authors, paths, and email leaks; depth never falls below one layer.',
    },
    'js-intel': {
        'label': 'JS intelligence crawler',
        'description': 'Expand script analysis to extract routes, tokens, feature flags, source maps, and config blobs; secret hunting is forced on.',
    },
    'forum': {
        'label': 'Forum/thread deep crawler',
        'description': 'Track thread structure, replies, quotes, and deleted-user placeholders across discussion pages.',
    },
    'geo': {
        'label': 'Geo-intelligence crawler',
        'description': 'Collect coordinates, geo tags, and location references into map-ready records.',
    },
    'news': {
        'label': 'News propagation tracker',
        'description': 'Extract story records with publication metadata, language, and outward references.',
    },
    'hidden': {
        'label': 'Hidden directory hybrid',
        'description': 'Blend observed paths with a bounded wordlist to probe for undiscovered in-scope routes.',
    },
    'scam': {
        'label': 'Dark pattern / scam detector',
        'description': 'Flag urgency cues, suspicious payment flows, cloned branding, and manipulative funnels.',
    },
    'temporal': {
        'label': 'Temporal change crawler',
        'description': 'Compare the current crawl snapshot to a prior snapshot and record added, removed, and changed findings.',
    },
}

MODE_DATASET_NAMES = (
    'document_metadata',
    'document_leaks',
    'js_intel',
    'threads',
    'locations',
    'stories',
    'hidden_paths',
    'scam_signals',
    'temporal_diffs',
)

DOCUMENT_EXTENSIONS = frozenset((
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.odt', '.ods', '.odp', '.rtf',
))

HIDDEN_WORDLIST = (
    'admin', 'login', 'portal', 'dashboard', 'hidden', 'private', 'backup',
    'staging', 'internal', 'dev', 'test', 'old', 'api', 'config', '.git',
)

EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
PATH_RE = re.compile(
    r'(?:[A-Za-z]:\\(?:[^\\\r\n\t ]+\\){1,8}[^\\\r\n\t ]+|/(?:Users|home|var|srv|opt|etc)/[^\s<>"\']+)',
)
TAG_RE = re.compile(r'<[^>]+>')
TITLE_RE = re.compile(r'<title[^>]*>(.*?)</title>', re.I | re.S)
TIME_RE = re.compile(r'<time[^>]*datetime=["\']([^"\']+)["\']', re.I)
LANG_RE = re.compile(r'<html[^>]*lang=["\']([^"\']+)["\']', re.I)
META_RE = re.compile(
    r'<meta[^>]+(?:name|property)=["\']([^"\']+)["\'][^>]+content=["\']([^"\']+)["\']',
    re.I,
)
QUOTE_RE = re.compile(r'"([^"\n]{12,160})"')
ABSOLUTE_LINK_RE = re.compile(r'href=["\'](https?://[^"\']+)["\']', re.I)
THREAD_BLOCK_RE = re.compile(
    r'<(?:article|div|li)[^>]+(?:class|id)=["\'][^"\']*(?:post|comment|reply|message)[^"\']*["\'][^>]*>(.*?)</(?:article|div|li)>',
    re.I | re.S,
)
AUTHOR_RE = re.compile(
    r'(?:data-author=["\']([^"\']+)["\']|class=["\'][^"\']*(?:author|user|username)[^"\']*["\'][^>]*>([^<]+)<)',
    re.I | re.S,
)
QUOTE_BLOCK_RE = re.compile(r'<blockquote[^>]*>(.*?)</blockquote>', re.I | re.S)
REPLY_RE = re.compile(r'(?:data-parent|href)=["\']#?([^"\']+)["\']', re.I)
COORD_RE = re.compile(r'(-?\d{1,3}\.\d{3,})\s*,\s*(-?\d{1,3}\.\d{3,})')
PLACE_RE = re.compile(r'\b(?:in|at|from|near)\s+([A-Z][a-z]+(?:[\s-][A-Z][a-z]+){0,2})')
NEWS_META_KEYS = (
    'og:title', 'twitter:title', 'article:published_time', 'og:site_name',
    'article:section', 'news_keywords',
)
SCAM_PATTERNS = (
    ('FAKE_URGENCY', re.compile(r'\b(?:limited time|act now|ends today|expires in|hurry|last chance)\b', re.I)),
    ('LOW_STOCK', re.compile(r'\b(?:only\s+\d+\s+left|low stock|selling fast)\b', re.I)),
    ('PRESSURE_PAYMENT', re.compile(r'\b(?:crypto only|wire transfer|gift card|bank transfer only)\b', re.I)),
    ('COUNTDOWN', re.compile(r'\b(?:countdown|timer ends|offer ends in)\b', re.I)),
    ('TRUST_CLONE', re.compile(r'\b(?:official store|verified seller|trusted by millions)\b', re.I)),
)
JS_TOKEN_RE = re.compile(r'(?i)\b(api[_-]?key|token|secret|auth[_-]?token)\b["\']?\s*[:=]\s*["\']([^"\']{6,200})["\']')
JS_FEATURE_RE = re.compile(r'(?i)\b([A-Za-z0-9_$]{3,64}(?:Flag|Feature|Toggle|Enabled))\b\s*[:=]\s*(true|false|["\'][^"\']{1,80}["\'])')
JS_CONFIG_RE = re.compile(r'(?i)\b(config|settings|runtimeConfig|env)\b\s*[:=]\s*(\{.{1,240}?\})', re.S)
JS_ROUTE_RE = re.compile(r'(?i)\b(?:route|router|path|pathname)\b[^"\']{0,40}["\']([^"\']{2,200})["\']')
JS_METHOD_RE = re.compile(r'\b(GET|POST|PUT|PATCH|DELETE)\b\s*["\']([^"\']{1,200})["\']')


def coerce_mode(value: str | None) -> str:
    """Return a supported crawl mode."""
    if value in MODE_DEFINITIONS:
        return value
    return 'generic'


def strip_tags(value: str) -> str:
    """Return a compact, tag-free text snippet."""
    return re.sub(r'\s+', ' ', TAG_RE.sub(' ', unescape(value or ''))).strip()


def normalize_story_title(value: str) -> str:
    """Return a stable story identifier for a title."""
    return re.sub(r'[^a-z0-9]+', '-', (value or '').lower()).strip('-')


def extract_document_records(document_url: str, payload: bytes, content_type: str) -> tuple[set[str], set[str]]:
    """Extract document metadata and leak records from raw bytes."""
    metadata = set()
    leaks = set()
    lowered_path = urlsplit(document_url).path.lower()
    kind = content_type or 'application/octet-stream'
    text = payload.decode('utf-8', 'ignore') or payload.decode('latin-1', 'ignore')

    if lowered_path.endswith('.pdf') or 'pdf' in kind:
        for key in ('Title', 'Author', 'Creator', 'Producer', 'Subject', 'CreationDate'):
            match = re.search(rf'/{re.escape(key)}\s*\((.*?)\)', text)
            if match:
                metadata.add(f'url={document_url} type=pdf {key.lower()}={match.group(1).strip()}')
    elif lowered_path.endswith(('.docx', '.xlsx', '.pptx', '.odt', '.ods', '.odp')):
        metadata.update(_extract_zip_document_metadata(document_url, payload, leaks))
    elif lowered_path.endswith(('.doc', '.xls', '.ppt', '.rtf')):
        author = re.search(r'(?i)\b(?:author|lastsavedby|creator)\b[:= ]{1,4}([^\r\n]{2,120})', text)
        if author:
            metadata.add(f'url={document_url} type=legacy author={author.group(1).strip()}')

    for email in EMAIL_RE.findall(text):
        leaks.add(f'url={document_url} kind=email value={email}')
    for path in PATH_RE.findall(text):
        leaks.add(f'url={document_url} kind=path value={path}')
    return metadata, leaks


def _extract_zip_document_metadata(document_url: str, payload: bytes, leaks: set[str]) -> set[str]:
    metadata = set()
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = archive.namelist()
            for name in names[:80]:
                leaks.add(f'url={document_url} kind=internal-path value={name}')
            if 'docProps/core.xml' in names:
                root = ElementTree.fromstring(archive.read('docProps/core.xml'))
                fields = {
                    'title': './/{http://purl.org/dc/elements/1.1/}title',
                    'author': './/{http://purl.org/dc/elements/1.1/}creator',
                    'last_modified_by': './/{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}lastModifiedBy',
                }
                for label, xpath in fields.items():
                    node = root.find(xpath)
                    if node is not None and (node.text or '').strip():
                        metadata.add(f'url={document_url} type=ooxml {label}={node.text.strip()}')
            for name in names:
                if name.endswith('.xml'):
                    try:
                        text = archive.read(name).decode('utf-8', 'ignore')
                    except OSError:
                        continue
                    for email in EMAIL_RE.findall(text):
                        leaks.add(f'url={document_url} kind=email value={email}')
                    for path in PATH_RE.findall(text):
                        leaks.add(f'url={document_url} kind=path value={path}')
    except (OSError, zipfile.BadZipFile, ElementTree.ParseError):
        return metadata
    return metadata


def extract_js_intel(script_url: str, response: str) -> set[str]:
    """Extract higher-value JavaScript intelligence records."""
    findings = set()
    for name, value in JS_TOKEN_RE.findall(response):
        findings.add(f'script={script_url} token={name} value={value}')
    for name, value in JS_FEATURE_RE.findall(response):
        findings.add(f'script={script_url} feature={name} value={value.strip("\"").strip("\'")}')
    for name, value in JS_CONFIG_RE.findall(response):
        compact = re.sub(r'\s+', ' ', value)
        findings.add(f'script={script_url} config={name} value={compact[:220]}')
    for route in JS_ROUTE_RE.findall(response):
        findings.add(f'script={script_url} route={route}')
    for method, route in JS_METHOD_RE.findall(response):
        findings.add(f'script={script_url} api={method}:{route}')
    return findings


def extract_thread_records(page_url: str, response: str) -> set[str]:
    """Extract lightweight forum/thread reconstruction records."""
    records = set()
    title_match = TITLE_RE.search(response)
    title = strip_tags(title_match.group(1)) if title_match else urlsplit(page_url).path or page_url
    blocks = THREAD_BLOCK_RE.findall(response)
    for index, block in enumerate(blocks, start=1):
        author_match = AUTHOR_RE.search(block)
        author = strip_tags((author_match.group(1) or author_match.group(2) or 'deleted-user') if author_match else 'deleted-user')
        quote_match = QUOTE_BLOCK_RE.search(block)
        quote = strip_tags(quote_match.group(1))[:120] if quote_match else ''
        reply_match = REPLY_RE.search(block)
        reply_to = reply_match.group(1) if reply_match else 'root'
        snippet = strip_tags(block)[:180]
        records.add(
            f'thread={title} post={index} author={author or "deleted-user"} reply_to={reply_to} '
            f'quote={quote or "-"} url={page_url} text={snippet}'
        )
    return records


def extract_location_records(page_url: str, response: str) -> set[str]:
    """Extract map-ready coordinate and location records."""
    records = set()
    seen = set()
    for lat, lon in COORD_RE.findall(response):
        key = (lat, lon)
        if key in seen:
            continue
        seen.add(key)
        records.add(f'url={page_url} kind=coordinate label=coordinate lat={lat} lon={lon}')

    meta = dict((key.lower(), value) for key, value in META_RE.findall(response))
    if 'geo.position' in meta and ';' in meta['geo.position']:
        lat, lon = [part.strip() for part in meta['geo.position'].split(';', 1)]
        records.add(f'url={page_url} kind=meta label=geo.position lat={lat} lon={lon}')

    visible_text = strip_tags(response)
    for place in PLACE_RE.findall(visible_text):
        records.add(f'url={page_url} kind=place label={place} source=text')
    return records


def extract_story_records(page_url: str, response: str) -> set[str]:
    """Extract article/news propagation records."""
    records = set()
    meta = {key.lower(): value for key, value in META_RE.findall(response) if key.lower() in NEWS_META_KEYS}
    title_match = TITLE_RE.search(response)
    title = meta.get('og:title') or meta.get('twitter:title') or (strip_tags(title_match.group(1)) if title_match else '')
    if not title:
        return records
    story_id = normalize_story_title(title) or 'story'
    published = meta.get('article:published_time') or (TIME_RE.search(response).group(1) if TIME_RE.search(response) else '')
    language = LANG_RE.search(response)
    site_name = meta.get('og:site_name') or (urlsplit(page_url).netloc or '')
    references = sorted(set(ABSOLUTE_LINK_RE.findall(response)))
    quotes = QUOTE_RE.findall(strip_tags(response))
    records.add(
        f'story={story_id} title={title} source={site_name} published={published or "-"} '
        f'lang={(language.group(1) if language else "-")} url={page_url} refs={len(references)}'
    )
    for reference in references[:10]:
        records.add(f'story={story_id} reference={reference} url={page_url}')
    for quote in quotes[:5]:
        records.add(f'story={story_id} quote={quote} url={page_url}')
    return records


def extract_scam_signals(page_url: str, response: str) -> set[str]:
    """Extract dark-pattern or scam heuristics."""
    signals = set()
    visible_text = strip_tags(response)
    for label, pattern in SCAM_PATTERNS:
        for match in pattern.findall(visible_text):
            evidence = match if isinstance(match, str) else ' '.join(match)
            signals.add(f'url={page_url} signal={label} evidence={evidence}')
    return signals


def build_hidden_candidates(main_url: str, internal: set[str], scripts: set[str], endpoints: set[str]) -> list[str]:
    """Return a bounded list of hidden-path guesses."""
    parsed = urlsplit(main_url)
    root = f'{parsed.scheme}://{parsed.netloc}/'
    tokens = set(HIDDEN_WORDLIST)
    for collection in (internal, scripts):
        for item in collection:
            path = urlsplit(item).path
            for part in path.split('/'):
                part = part.strip().strip('.')
                if re.fullmatch(r'[a-z0-9][a-z0-9._-]{1,24}', part or ''):
                    tokens.add(part)
    for endpoint in endpoints:
        for part in endpoint.split('/'):
            part = part.strip().strip('.')
            if re.fullmatch(r'[a-z0-9][a-z0-9._-]{1,24}', part or ''):
                tokens.add(part)
    candidates = []
    for token in sorted(tokens):
        candidates.append(root + token)
        candidates.append(root + token + '/')
    deduped = []
    seen = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        deduped.append(candidate)
        if len(deduped) >= 48:
            break
    return deduped


def build_temporal_diffs(previous_snapshot: dict[str, object], current_snapshot: dict[str, object]) -> set[str]:
    """Return added/removed/changed records between two snapshots."""
    diffs = set()
    dataset_names = set(previous_snapshot) | set(current_snapshot)
    for name in sorted(dataset_names):
        previous = previous_snapshot.get(name)
        current = current_snapshot.get(name)
        if isinstance(previous, dict) or isinstance(current, dict):
            previous = previous or {}
            current = current or {}
            keys = set(previous) | set(current)
            for key in sorted(keys):
                prev_value = previous.get(key)
                curr_value = current.get(key)
                if prev_value != curr_value:
                    diffs.add(f'dataset={name} metric={key} before={prev_value} after={curr_value}')
            continue
        previous_values = set(previous or [])
        current_values = set(current or [])
        for item in sorted(current_values - previous_values):
            diffs.add(f'dataset={name} change=added value={item}')
        for item in sorted(previous_values - current_values):
            diffs.add(f'dataset={name} change=removed value={item}')
    return diffs
