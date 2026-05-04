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

RITUAL_CHAIN_DEFINITIONS = {
    'domain_necropsy': {
        'label': 'Domain necropsy',
        'description': 'Classify a web target, walk the live surface, and summarize exposed organs.',
        'default_mode': 'generic',
        'supported_specimens': ('url', 'domain', 'sitemap', 'html'),
        'defaults': {
            'archive_seeds': True,
            'respect_robots_delay': True,
        },
    },
    'dead_page_resurrection': {
        'label': 'Dead page resurrection',
        'description': 'Use archive hints, temporal diffs, and broken-path analysis to revive dead surfaces.',
        'default_mode': 'temporal',
        'supported_specimens': ('dead_url', 'archived_url', 'url'),
        'defaults': {
            'archive_seeds': True,
            'respect_robots_delay': True,
        },
    },
    'js_bone_saw': {
        'label': 'JS bone saw',
        'description': 'Prioritize script extraction and endpoint archaeology over broad page walking.',
        'default_mode': 'js-intel',
        'supported_specimens': ('js', 'url', 'domain'),
        'defaults': {
            'extract_secrets': True,
            'render_js': False,
        },
    },
    'pdf_fossil_dig': {
        'label': 'PDF fossil dig',
        'description': 'Harvest linked documents, metadata, and archive shadows around document trails.',
        'default_mode': 'document',
        'supported_specimens': ('pdf', 'url', 'domain'),
        'defaults': {
            'archive_seeds': True,
            'render_js': False,
        },
    },
    'scam_smell_test': {
        'label': 'Scam smell test',
        'description': 'Bias the crawl toward manipulative flows, cloned trust signals, and fake urgency.',
        'default_mode': 'scam',
        'supported_specimens': ('url', 'domain', 'company', 'handle'),
        'defaults': {
            'render_js': True,
        },
    },
    'forum_bloodline': {
        'label': 'Forum bloodline',
        'description': 'Track thread ancestry, replies, quotes, and deleted-user shadows across discussions.',
        'default_mode': 'forum',
        'supported_specimens': ('url', 'domain'),
        'defaults': {
            'render_js': True,
        },
    },
    'news_mutation_trace': {
        'label': 'News mutation trace',
        'description': 'Map how a story mutates across article surfaces, archives, and references.',
        'default_mode': 'news',
        'supported_specimens': ('url', 'domain'),
        'defaults': {
            'archive_seeds': True,
            'render_js': True,
        },
    },
}

PRESET_DEFINITIONS = {
    'balanced': {
        'label': 'Balanced',
        'description': 'Sensible defaults for most hunts.',
        'defaults': {'depth': 2, 'threads': 4, 'delay': 0.0, 'timeout': 8.0},
    },
    'quick': {
        'label': 'Quick',
        'description': 'Fast first pass with shallow depth and minimal ceremony.',
        'defaults': {'depth': 1, 'threads': 6, 'delay': 0.0, 'timeout': 6.0},
    },
    'polite': {
        'label': 'Polite',
        'description': 'Lower concurrency and higher delays for fragile targets.',
        'defaults': {'depth': 2, 'threads': 2, 'delay': 0.75, 'timeout': 10.0},
    },
    'document-heavy': {
        'label': 'Document-heavy',
        'description': 'Bias toward linked document harvesting and archive context.',
        'defaults': {'depth': 2, 'threads': 3, 'delay': 0.25, 'timeout': 10.0, 'archive_seeds': True},
    },
    'javascript-heavy': {
        'label': 'JavaScript-heavy',
        'description': 'Bias toward rendering and script archaeology.',
        'defaults': {'depth': 2, 'threads': 4, 'delay': 0.15, 'timeout': 10.0, 'render_js': True, 'extract_secrets': True},
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
    'hidden_probe_sources',
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
JS_URL_RE = re.compile(r'https?://[^\s"\']{4,240}')
JS_ANALYTICS_RE = re.compile(r'(?i)\b(?:G-[A-Z0-9]{6,12}|UA-\d{4,12}-\d+|GTM-[A-Z0-9]{4,12})\b')
JS_STORAGE_RE = re.compile(r'https?://[^\s"\']+(?:amazonaws\.com|cloudfront\.net|blob\.core\.windows\.net|storage\.googleapis\.com|cdn\.)[^\s"\']*', re.I)
JS_ERROR_RE = re.compile(r'(?i)(?:throw\s+new\s+\w+\(|console\.(?:error|warn)\(|error\s*:\s*["\'])([^"\']{6,180})')
JS_COMMENT_RE = re.compile(r'(?://[^\n]{5,200}|/\*[\s\S]{5,240}?\*/)')
JS_VIEW_RE = re.compile(r'(?i)\b(?:template|view|screen|component|page)\b\s*[:=]\s*["\']([^"\']{2,120})["\']')
JS_ENV_RE = re.compile(r'(?i)\b(?:process\.env\.[A-Z0-9_]+|REACT_APP_[A-Z0-9_]+|NEXT_PUBLIC_[A-Z0-9_]+|VITE_[A-Z0-9_]+)\b')
META_COORD_KEYS = (
    'geo.position',
    'icbm',
)
META_LAT_KEYS = ('place:location:latitude', 'og:latitude')
META_LON_KEYS = ('place:location:longitude', 'og:longitude')
META_PLACE_KEYS = ('geo.placename', 'place:location:name')
WEAK_PLACE_STOPWORDS = frozenset({
    'Breaking News', 'Last Chance', 'Crypto Only', 'Official Store',
    'Limited Time', 'Selling Fast', 'Trusted Seller',
})


def coerce_mode(value: str | None) -> str:
    """Return a supported crawl mode."""
    if value in MODE_DEFINITIONS:
        return value
    return 'generic'


def coerce_ritual_chain(value: str | None) -> str:
    """Return a supported ritual chain."""
    if value in RITUAL_CHAIN_DEFINITIONS:
        return value
    return 'domain_necropsy'


def coerce_preset(value: str | None) -> str:
    """Return a supported crawl preset."""
    if value in PRESET_DEFINITIONS:
        return value
    return 'balanced'


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
    try:
        text = payload.decode('utf-8')
    except UnicodeDecodeError:
        text = payload.decode('latin-1', 'ignore')

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
    for match in JS_URL_RE.findall(response):
        if '/graphql' in match.lower():
            findings.add(f'script={script_url} graphql={match}')
        elif '/api/' in match.lower():
            findings.add(f'script={script_url} api_url={match}')
    for match in JS_ANALYTICS_RE.findall(response):
        findings.add(f'script={script_url} analytics_id={match}')
    for match in JS_STORAGE_RE.findall(response):
        findings.add(f'script={script_url} storage={match}')
    for match in JS_ERROR_RE.findall(response):
        findings.add(f'script={script_url} error_hint={match.strip()[:140]}')
    for match in JS_COMMENT_RE.findall(response):
        compact = re.sub(r'\s+', ' ', match.replace('/*', '').replace('*/', '').replace('//', '')).strip()
        if compact and len(compact) >= 8:
            findings.add(f'script={script_url} comment={compact[:140]}')
    for match in JS_VIEW_RE.findall(response):
        findings.add(f'script={script_url} view={match}')
    for match in JS_ENV_RE.findall(response):
        findings.add(f'script={script_url} env_hint={match}')
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
    meta = dict((key.lower(), value) for key, value in META_RE.findall(response))
    for lat, lon in COORD_RE.findall(response):
        key = ('text', lat, lon)
        if key in seen:
            continue
        seen.add(key)
        records.add(f'url={page_url} kind=coordinate confidence=exact source=text label=coordinate lat={lat} lon={lon}')

    for key in META_COORD_KEYS:
        lat, lon = _extract_meta_coordinate_pair(meta.get(key, ''))
        if not lat or not lon:
            continue
        pair = (key, lat, lon)
        if pair in seen:
            continue
        seen.add(pair)
        records.add(f'url={page_url} kind=geotag confidence=high source=meta label={key} lat={lat} lon={lon}')

    meta_lat = _first_meta_value(meta, META_LAT_KEYS)
    meta_lon = _first_meta_value(meta, META_LON_KEYS)
    if meta_lat and meta_lon:
        pair = ('meta-pair', meta_lat, meta_lon)
        if pair not in seen:
            seen.add(pair)
            records.add(
                f'url={page_url} kind=geotag confidence=high source=meta '
                f'label={META_LAT_KEYS[0]}+{META_LON_KEYS[0]} lat={meta_lat} lon={meta_lon}'
            )

    for key in META_PLACE_KEYS:
        place = meta.get(key, '').strip()
        if place:
            records.add(f'url={page_url} kind=place confidence=medium source=meta label={place}')

    visible_text = strip_tags(response)
    for place in PLACE_RE.findall(visible_text):
        cleaned = place.strip()
        if not _looks_like_place_guess(cleaned):
            continue
        records.add(f'url={page_url} kind=place confidence=weak source=text label={cleaned}')
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
    time_match = TIME_RE.search(response)
    published = meta.get('article:published_time') or (time_match.group(1) if time_match else '')
    language = LANG_RE.search(response)
    site_name = meta.get('og:site_name') or (urlsplit(page_url).netloc or '')
    page_domain = urlsplit(page_url).netloc or ''
    cluster = f'{story_id}@{page_domain or "unknown"}'
    references = sorted(set(ABSOLUTE_LINK_RE.findall(response)))
    quotes = QUOTE_RE.findall(strip_tags(response))
    metadata_fingerprint = f'source={site_name or "-"} published={published or "-"} lang={(language.group(1) if language else "-")}'
    records.add(
        f'story={story_id} cluster={cluster} relation=page title={title} source={site_name} '
        f'published={published or "-"} lang={(language.group(1) if language else "-")} '
        f'url={page_url} refs={len(references)}'
    )
    records.add(f'story={story_id} cluster={cluster} relation=metadata {metadata_fingerprint} url={page_url}')
    for reference in references[:10]:
        reference_domain = urlsplit(reference).netloc or ''
        relation = 'reference'
        if reference_domain and reference_domain != page_domain:
            relation = 'mirror'
        records.add(
            f'story={story_id} cluster={cluster} relation={relation} '
            f'reference={reference} reference_domain={reference_domain or "-"} url={page_url}'
        )
    for quote in quotes[:5]:
        records.add(f'story={story_id} cluster={cluster} relation=quote quote={quote} url={page_url}')
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


def build_hidden_candidate_records(
    main_url: str,
    internal: set[str],
    scripts: set[str],
    endpoints: set[str],
    extra_words: tuple[str, ...] | list[str] | None = None,
) -> list[dict[str, str]]:
    """Return bounded hidden-path candidate records with provenance."""
    parsed = urlsplit(main_url)
    root = f'{parsed.scheme}://{parsed.netloc}/'
    token_sources: dict[str, set[str]] = {}
    for token in HIDDEN_WORDLIST:
        token_sources.setdefault(token, set()).add('wordlist:default')
    for token in extra_words or ():
        normalized = _normalize_hidden_token(token)
        if normalized:
            token_sources.setdefault(normalized, set()).add('wordlist:user')
    for collection_name, collection in (('internal', internal), ('script', scripts)):
        for item in collection:
            for token in _tokenize_hidden_source(urlsplit(item).path):
                token_sources.setdefault(token, set()).add(f'learned:{collection_name}:{item}')
    for endpoint in endpoints:
        for token in _tokenize_hidden_source(endpoint):
            token_sources.setdefault(token, set()).add(f'learned:endpoint:{endpoint}')

    records = []
    seen = set()
    for token in sorted(token_sources, key=lambda item: _hidden_token_sort_key(item, token_sources[item])):
        sources = sorted(token_sources[token])
        strategy = 'learned' if any(source.startswith('learned:') for source in sources) else 'wordlist'
        source_label = '|'.join(sources[:4])
        for suffix in ('', '/'):
            probe = root + token + suffix
            if probe in seen:
                continue
            seen.add(probe)
            records.append({
                'probe': probe,
                'token': token,
                'strategy': strategy,
                'source': source_label,
            })
            if len(records) >= 48:
                return records
    return records


def build_hidden_candidates(
    main_url: str,
    internal: set[str],
    scripts: set[str],
    endpoints: set[str],
    extra_words: tuple[str, ...] | list[str] | None = None,
) -> list[str]:
    """Return a bounded list of hidden-path guesses."""
    return [item['probe'] for item in build_hidden_candidate_records(main_url, internal, scripts, endpoints, extra_words=extra_words)]


def _extract_meta_coordinate_pair(value: str) -> tuple[str, str]:
    if not value:
        return '', ''
    for separator in (';', ','):
        if separator in value:
            lat, lon = [part.strip() for part in value.split(separator, 1)]
            if lat and lon:
                return lat, lon
    return '', ''


def _first_meta_value(meta: dict[str, str], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = meta.get(key, '').strip()
        if value:
            return value
    return ''


def _looks_like_place_guess(value: str) -> bool:
    if not value or value in WEAK_PLACE_STOPWORDS:
        return False
    if len(value.split()) < 2:
        return False
    return True


def _normalize_hidden_token(value: str) -> str:
    token = (value or '').strip().strip('.').lower()
    if re.fullmatch(r'[a-z0-9][a-z0-9._-]{1,24}', token or ''):
        return token
    return ''


def _tokenize_hidden_source(value: str) -> list[str]:
    tokens = []
    for part in value.split('/'):
        token = _normalize_hidden_token(part)
        if token:
            tokens.append(token)
    return tokens


def _hidden_token_sort_key(token: str, sources: set[str]) -> tuple[int, int, str]:
    if 'wordlist:user' in sources:
        return (0, 0, token)
    if any(source.startswith('learned:') for source in sources):
        return (1, 0, token)
    return (2, 0, token)


def build_temporal_diffs(previous_snapshot: dict[str, object], current_snapshot: dict[str, object]) -> set[str]:
    """Return added/removed/changed records between two snapshots."""
    diffs = set()
    dataset_names = set(previous_snapshot) | set(current_snapshot)
    for name in sorted(dataset_names):
        diffs.update(_build_temporal_diff_records([name], previous_snapshot.get(name), current_snapshot.get(name)))
    return diffs


def _build_temporal_diff_records(path: list[str], previous: object, current: object) -> set[str]:
    if isinstance(previous, dict) or isinstance(current, dict):
        previous_map = previous if isinstance(previous, dict) else {}
        current_map = current if isinstance(current, dict) else {}
        diffs = set()
        for key in sorted(set(previous_map) | set(current_map)):
            diffs.update(_build_temporal_diff_records(path + [str(key)], previous_map.get(key), current_map.get(key)))
        return diffs
    if _is_temporal_sequence(previous) or _is_temporal_sequence(current):
        previous_values = set(_normalize_temporal_sequence(previous))
        current_values = set(_normalize_temporal_sequence(current))
        diffs = set()
        for item in sorted(current_values - previous_values):
            diffs.add(_format_temporal_list_diff(path, 'added', item))
        for item in sorted(previous_values - current_values):
            diffs.add(_format_temporal_list_diff(path, 'removed', item))
        return diffs
    if previous == current:
        return set()
    return {_format_temporal_scalar_diff(path, previous, current)}


def _is_temporal_sequence(value: object) -> bool:
    return isinstance(value, (list, tuple, set))


def _normalize_temporal_sequence(value: object) -> list[str]:
    if not _is_temporal_sequence(value):
        return []
    return [str(item) for item in value if item is not None]


def _format_temporal_list_diff(path: list[str], change: str, value: str) -> str:
    dataset = path[0]
    if len(path) == 1:
        return f'dataset={dataset} change={change} value={value}'
    return f'dataset={dataset} item={" / ".join(path[1:])} change={change} value={value}'


def _format_temporal_scalar_diff(path: list[str], previous: object, current: object) -> str:
    dataset = path[0]
    if len(path) == 1:
        return f'dataset={dataset} metric=value before={previous} after={current}'
    if len(path) == 2:
        return f'dataset={dataset} metric={path[1]} before={previous} after={current}'
    return f'dataset={dataset} item={" / ".join(path[1:-1])} field={path[-1]} before={previous} after={current}'
