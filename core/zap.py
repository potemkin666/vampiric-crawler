"""Seed harvester: robots.txt, sitemaps, and archive sources."""
from collections import deque
import json
import warnings
from urllib.parse import quote
from xml.etree import ElementTree

from core.requester import get_session
from core.utils import normalize_url

warnings.filterwarnings('ignore')

_ROBOTS_AGENT = 'vampiriccrawler/1.0'
_MAX_SITEMAPS = 25
_MAX_ARCHIVE_INDEXES = 3
_ARCHIVE_LIMIT = 200
_DEFAULT_SITEMAPS = ('/sitemap.xml', '/sitemap_index.xml')
SEED_PROVIDERS = []


def register_seed_provider(name):
    """Register a seed provider that enriches crawler state."""
    def decorator(func):
        SEED_PROVIDERS.append((name, func))
        return func
    return decorator


def _fetch(url, timeout=8, headers=None, proxies=None):
    """Return the text body of *url* or ''."""
    try:
        req_headers = {'User-Agent': 'VampiricCrawler/1.0'}
        if headers:
            req_headers.update(headers)
        response = get_session().get(
            url,
            timeout=timeout,
            verify=False,
            headers=req_headers,
            proxies=proxies,
            allow_redirects=True,
        )
        return response.text
    except Exception:
        return ''


def _local_name(tag):
    """Return the XML local-name portion of *tag*."""
    return tag.rsplit('}', 1)[-1].lower() if tag else ''


def _match_robot_agent(agent):
    """Return a specificity score if *agent* applies to this crawler."""
    agent = agent.strip().lower()
    if not agent:
        return -1
    if agent == '*':
        return 0
    if _ROBOTS_AGENT.startswith(agent):
        return len(agent)
    return -1


def _parse_robot_groups(body):
    """Parse *body* into robots groups and sitemap hints."""
    groups = []
    sitemaps = set()
    current_agents = []
    current_rules = []
    current_crawl_delay = None

    def flush_group():
        if current_agents or current_rules or current_crawl_delay is not None:
            groups.append({
                'agents': tuple(current_agents),
                'rules': tuple(current_rules),
                'crawl_delay': current_crawl_delay,
            })

    for raw_line in body.splitlines():
        line = raw_line.split('#', 1)[0].strip()
        if not line:
            flush_group()
            current_agents = []
            current_rules = []
            current_crawl_delay = None
            continue

        directive, sep, value = line.partition(':')
        if not sep:
            continue

        directive = directive.strip().lower()
        value = value.strip()

        if directive == 'user-agent':
            if current_rules or current_crawl_delay is not None:
                flush_group()
                current_agents = []
                current_rules = []
                current_crawl_delay = None
            current_agents.append(value.lower())
        elif directive in ('allow', 'disallow'):
            if current_agents:
                current_rules.append((directive.upper(), value))
        elif directive == 'crawl-delay' and current_agents:
            try:
                current_crawl_delay = max(float(value), 0.0)
            except ValueError:
                current_crawl_delay = None
        elif directive == 'sitemap':
            normalized = normalize_url(value)
            if normalized:
                sitemaps.add(normalized)

    flush_group()
    return groups, sitemaps


def _applicable_robot_rules(body):
    """Return applicable robots rules, sitemap URLs, and crawl-delay seconds."""
    groups, sitemaps = _parse_robot_groups(body)
    matched = []
    best_score = -1

    for group in groups:
        score = max((_match_robot_agent(agent) for agent in group['agents']), default=-1)
        if score < 0:
            continue
        if score > best_score:
            matched = [group]
            best_score = score
        elif score == best_score:
            matched.append(group)

    rules = []
    seen_rules = set()
    crawl_delay = None
    for group in matched:
        if group.get('crawl_delay') is not None:
            crawl_delay = max(crawl_delay or 0.0, group['crawl_delay'])
        for rule in group['rules']:
            if rule not in seen_rules:
                rules.append(rule)
                seen_rules.add(rule)

    return rules, sitemaps, crawl_delay


def _seedable_robot_path(path):
    """Return a normalized path seed from a robots rule or ''."""
    candidate = path.strip()
    if not candidate or candidate == '/' or '*' in candidate or '$' in candidate:
        return ''
    if not candidate.startswith('/'):
        candidate = '/' + candidate
    return candidate


def _parse_robots(main_url, internal, headers=None, proxies=None):
    """Seed URLs from the applicable robots rules and return robots entries."""
    body = _fetch(
        main_url.rstrip('/') + '/robots.txt',
        headers=headers,
        proxies=proxies,
    )
    rules, sitemaps, crawl_delay = _applicable_robot_rules(body)
    robots = set()

    for _, path in rules:
        robots.add(path)
        seed_path = _seedable_robot_path(path)
        if seed_path:
            seeded = normalize_url(seed_path, base_url=main_url)
            if seeded:
                internal.add(seeded)

    robots.update(sitemaps)
    return robots, rules, sitemaps, crawl_delay


def _parse_sitemap_body(body, base_url):
    """Return (page_urls, nested_sitemaps) extracted from a sitemap body."""
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError:
        text_urls = set()
        for line in body.splitlines():
            normalized = normalize_url(line.strip(), base_url=base_url)
            if normalized:
                text_urls.add(normalized)
        return text_urls, set()

    root_name = _local_name(root.tag)
    page_urls = set()
    nested_sitemaps = set()

    for loc in root.iter():
        if _local_name(loc.tag) != 'loc' or not loc.text:
            continue
        normalized = normalize_url(loc.text.strip(), base_url=base_url)
        if not normalized:
            continue
        if root_name == 'sitemapindex':
            nested_sitemaps.add(normalized)
        else:
            page_urls.add(normalized)

    return page_urls, nested_sitemaps


def _parse_sitemaps(main_url, internal, sitemap_hints=None, headers=None, proxies=None):
    """Discover URLs from sitemap files, following nested sitemap indexes."""
    queue = deque()
    visited = set()
    discovered_urls = set()

    def enqueue(url):
        normalized = normalize_url(url, base_url=main_url)
        if normalized and normalized not in visited and normalized not in queue:
            queue.append(normalized)

    for candidate in _DEFAULT_SITEMAPS:
        enqueue(candidate)
    for sitemap_url in sitemap_hints or ():
        enqueue(sitemap_url)

    while queue and len(visited) < _MAX_SITEMAPS:
        sitemap_url = queue.popleft()
        if sitemap_url in visited:
            continue
        visited.add(sitemap_url)

        body = _fetch(sitemap_url, headers=headers, proxies=proxies)
        if not body:
            continue

        page_urls, nested_sitemaps = _parse_sitemap_body(body, base_url=sitemap_url)
        internal.update(page_urls)
        discovered_urls.update(page_urls)
        for nested in nested_sitemaps:
            enqueue(nested)

    return visited, discovered_urls


def _archive_queries(domain, host):
    """Return normalized archive query targets from *domain* and *host*."""
    targets = []
    for target in (host, domain, f'*.{domain}'):
        target = (target or '').strip()
        if target and target not in targets:
            targets.append(target)
    return tuple(targets)


def _seed_archive_urls(lines, internal):
    """Normalize archive URL lines into *internal*."""
    for line in lines:
        candidate = line.strip()
        if not candidate:
            continue
        if candidate.startswith('{'):
            try:
                candidate = json.loads(candidate).get('url', '')
            except (TypeError, ValueError):
                candidate = ''
        normalized = normalize_url(candidate)
        if normalized:
            internal.add(normalized)


def _query_wayback(target, internal, headers=None, proxies=None):
    """Populate *internal* from the Wayback CDX API for *target*."""
    api = (
        'https://web.archive.org/cdx/search/cdx'
        f'?url={quote(target, safe="*")}%2F*'
        f'&output=text&fl=original&collapse=urlkey&limit={_ARCHIVE_LIMIT}'
    )
    body = _fetch(api, timeout=15, headers=headers, proxies=proxies)
    _seed_archive_urls(body.splitlines(), internal)


def _query_commoncrawl(target, internal, headers=None, proxies=None):
    """Populate *internal* from a bounded set of Common Crawl indexes."""
    collections = _fetch(
        'https://index.commoncrawl.org/collinfo.json',
        timeout=15,
        headers=headers,
        proxies=proxies,
    )
    if not collections:
        return

    try:
        indexes = json.loads(collections)
    except ValueError:
        return

    sorted_indexes = sorted(
        (entry for entry in indexes if entry.get('id')),
        key=lambda entry: entry['id'],
        reverse=True,
    )

    for entry in sorted_indexes[:_MAX_ARCHIVE_INDEXES]:
        api_id = entry.get('id')
        endpoint = (
            f'https://index.commoncrawl.org/{api_id}-index'
            f'?url={quote(target, safe="*")}%2F*&output=json&limit={_ARCHIVE_LIMIT}'
        )
        body = _fetch(endpoint, timeout=15, headers=headers, proxies=proxies)
        if body:
            _seed_archive_urls(body.splitlines(), internal)


def _archives(domain, host, internal, headers=None, proxies=None):
    """Fetch archived URLs from multiple archive sources."""
    for target in _archive_queries(domain, host):
        _query_wayback(target, internal, headers=headers, proxies=proxies)
        _query_commoncrawl(target, internal, headers=headers, proxies=proxies)


@register_seed_provider('robots')
def _seed_from_robots(main_url, use_wayback, domain, host, internal, robots, proxies,
                      headers=None):
    proxy = proxies[0] if proxies else None
    robot_entries, rules, sitemap_hints, crawl_delay = _parse_robots(
        main_url,
        internal,
        headers=headers,
        proxies=proxy,
    )
    robots.update(robot_entries)
    discovered_sitemaps, queued_urls = _parse_sitemaps(
        main_url,
        internal,
        sitemap_hints=sitemap_hints,
        headers=headers,
        proxies=proxy,
    )
    return {
        'crawl_delay': crawl_delay,
        'robots_rules': [
            {'directive': directive, 'path': path}
            for directive, path in rules
        ],
        'sitemap_urls': sorted(discovered_sitemaps | set(sitemap_hints)),
        'sitemap_queued_urls': sorted(queued_urls),
    }


@register_seed_provider('archives')
def _seed_from_archives(main_url, use_wayback, domain, host, internal, robots, proxies,
                        headers=None):
    if use_wayback:
        proxy = proxies[0] if proxies else None
        _archives(domain, host, internal, headers=headers, proxies=proxy)
    return {}


def zap(main_url, use_wayback, domain, host, internal, robots, proxies,
        headers=None):
    """Populate *internal* with seed URLs from registered providers."""
    metadata = {}
    for _, provider in SEED_PROVIDERS:
        result = provider(main_url, use_wayback, domain, host, internal, robots, proxies, headers=headers) or {}
        metadata.update({key: value for key, value in result.items() if value is not None})
    return metadata
