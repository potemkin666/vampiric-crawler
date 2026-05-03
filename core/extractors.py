"""Modular page and script extractors for Vampiric Crawler."""
from html.parser import HTMLParser
import posixpath
import re
from urllib.parse import urlsplit

from core.regex import rintels, rendpoint, rhref, rscript, rentropy, rsecrets
from core.utils import (
    entropy,
    is_in_scope,
    is_link,
    normalize_url,
    regxy,
)


PAGE_EXTRACTORS = []
SCRIPT_EXTRACTORS = []


INLINE_URL_RE = re.compile(r'["\']((?:https?://|//|/|\.\./|\./)[^"\'<>\s]{1,300})["\']', re.I)
INLINE_PATH_RE = re.compile(r'["\']((?:/|\.\./|\./)(?:api|graphql|graphiql|playground|openapi|swagger|assets?|static|manifest)[^"\'<>\s]{0,300})["\']', re.I)
GRAPHQL_HINT_RE = re.compile(r'(?:https?://[^\s"\']+)?/(?:api/)?graphql(?:\b|/)', re.I)
SOURCE_MAP_RE = re.compile(r'[#@]\s*sourceMappingURL\s*=\s*([^\s]+)', re.I)


class VisibleTextExtractor(HTMLParser):
    """Collect visible text while ignoring script/style blocks."""

    def __init__(self):
        super().__init__()
        self._skip_tags = []
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self._skip_tags.append(tag)

    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self._skip_tags:
            for index in range(len(self._skip_tags) - 1, -1, -1):
                if self._skip_tags[index] == tag:
                    del self._skip_tags[index]
                    break

    def handle_data(self, data):
        if not self._skip_tags and data.strip():
            self.parts.append(data)


def register_page_extractor(func):
    PAGE_EXTRACTORS.append(func)
    return func


def register_script_extractor(func):
    SCRIPT_EXTRACTORS.append(func)
    return func


def run_page_extractors(url, response, context):
    for extractor in PAGE_EXTRACTORS:
        extractor(url, response, context)


def run_script_extractors(url, response, context):
    for extractor in SCRIPT_EXTRACTORS:
        extractor(url, response, context)


def extract_visible_text(response):
    parser = VisibleTextExtractor()
    parser.feed(response)
    return ' '.join(parser.parts)


@register_page_extractor
def link_extractor(page_url, response, context):
    for link_match in rhref.findall(response):
        link = link_match[2].replace("'", '').replace('"', '').split('#')[0]
        normalized_link = normalize_url(link, base_url=page_url)
        candidate = normalized_link or link
        if not is_link(candidate, context['processed'], context['files']):
            continue
        scoped_link = context['mark_scope'](candidate)
        if not scoped_link:
            continue
        if context['verbose']:
            if is_in_scope(scoped_link, context['host'], context['domain'], context['scope_mode'],
                           context.get('scope_allow'), context.get('scope_deny')):
                print(context['verbose_prefix_internal'].format(url=scoped_link))
            else:
                print(context['verbose_prefix_external'].format(url=scoped_link))


@register_page_extractor
def intel_extractor(url, response, context):
    res = extract_visible_text(response)
    for name, pattern in rintels:
        for match in pattern.findall(res):
            context['bad_intel'].add((match, name, url))


@register_page_extractor
def script_reference_extractor(page_url, response, context):
    for match in rscript.findall(response):
        src = normalize_url(match[2].replace("'", '').replace('"', ''), base_url=page_url)
        if not src:
            continue
        context['bad_scripts'].add(src)


@register_page_extractor
def form_extractor(page_url, response, context):
    for form_match in re.finditer(r'<form\b([^>]*)>(.*?)</form>', response, re.I | re.S):
        attrs = form_match.group(1)
        body = form_match.group(2)
        action_match = re.search(r'action\s*=\s*(["\'])(.*?)\1', attrs, re.I)
        method_match = re.search(r'method\s*=\s*(["\'])(.*?)\1', attrs, re.I)
        action = normalize_url(
            action_match.group(2) if action_match else page_url,
            base_url=page_url,
        )
        method = (method_match.group(2) if method_match else 'GET').upper()
        fields = []
        for input_match in re.finditer(r'<(?:input|textarea|select)\b([^>]*)>', body, re.I | re.S):
            tag_attrs = input_match.group(1)
            name_match = re.search(r'name\s*=\s*(["\'])(.*?)\1', tag_attrs, re.I)
            if not name_match:
                continue
            field_name = name_match.group(2)
            type_match = re.search(r'type\s*=\s*(["\'])(.*?)\1', tag_attrs, re.I)
            field_type = (type_match.group(2) if type_match else 'text').lower()
            fields.append(f'{field_name}:{field_type}')
        context['forms'].add(
            f'action={action or page_url} method={method} inputs={",".join(sorted(fields))}'
        )


@register_page_extractor
def structured_discovery_extractor(page_url, response, context):
    for match in INLINE_URL_RE.findall(response) + INLINE_PATH_RE.findall(response):
        _record_discovered_reference(page_url, match, context)

    lower = response.lower()
    if 'swagger' in lower or 'openapi' in lower:
        for candidate in ('/openapi.json', '/swagger.json', '/v2/api-docs', '/v3/api-docs'):
            _record_discovered_reference(page_url, candidate, context)
    if 'graphql' in lower:
        for match in GRAPHQL_HINT_RE.findall(response):
            _record_discovered_reference(page_url, match, context)
        _record_discovered_reference(page_url, '/graphql', context)
    if 'asset-manifest' in lower:
        _record_discovered_reference(page_url, '/asset-manifest.json', context)
    if 'manifest.json' in lower:
        _record_discovered_reference(page_url, '/manifest.json', context)


@register_page_extractor
def custom_regex_extractor(url, response, context):
    pattern = context.get('custom_regex')
    if pattern:
        regxy(pattern, response, False, context['custom'])


@register_page_extractor
def secret_extractor(url, response, context):
    if not context.get('extract_secrets'):
        return
    seen = set()
    for secret_name, pattern in rsecrets:
        for match in pattern.findall(response):
            token = first_secret_group(match)
            if token and (secret_name, token) not in seen:
                context['keys'].add(f'{url}:{secret_name}:{token}')
                seen.add((secret_name, token))
    for match in rentropy.findall(response):
        if entropy(match) >= 4:
            context['keys'].add(f'{url}:HIGH_ENTROPY:{match}')


@register_script_extractor
def endpoint_extractor(url, response, context):
    for match in rendpoint.findall(response):
        path = match if isinstance(match, str) else (match[0] or match[1])
        if path and not re.search(r'[}{><"\']', path) and path != '/':
            context['endpoints'].add(path)


@register_script_extractor
def script_artifact_extractor(url, response, context):
    for source_map in SOURCE_MAP_RE.findall(response):
        normalized = normalize_url(source_map.strip(), base_url=url)
        if normalized:
            context['files'].add(normalized)
    for match in INLINE_URL_RE.findall(response) + INLINE_PATH_RE.findall(response):
        _record_discovered_reference(url, match, context, from_script=True)
    if 'graphql' in response.lower():
        for match in GRAPHQL_HINT_RE.findall(response):
            _record_discovered_reference(url, match, context, from_script=True)


def first_secret_group(match):
    if isinstance(match, str):
        return match.strip()
    for item in match:
        if item is not None and item != '':
            return item.strip()
    return ''


COMMON_DISCOVERY_FILES = frozenset((
    '.json', '.map', '.yaml', '.yml', '.txt', '.xml'
))


def _record_discovered_reference(page_url, candidate, context, from_script=False):
    normalized = normalize_url(candidate, base_url=page_url)
    if not normalized:
        return
    path = urlsplit(normalized).path.lower()
    if any(path.endswith(ext) for ext in COMMON_DISCOVERY_FILES):
        context['files'].add(normalized)
        context['mark_scope'](normalized)
    if '/graphql' in path:
        context['endpoints'].add(posixpath.normpath(urlsplit(normalized).path) or '/graphql')
    if '/api/' in path or path.endswith('/graphql') or path.endswith('/graphiql'):
        context['endpoints'].add(posixpath.normpath(urlsplit(normalized).path) or path)
    if is_link(normalized, context['processed'], context['files']):
        context['mark_scope'](normalized)
